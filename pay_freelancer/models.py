import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from orders.models import Job


# =========================
# Payout Status Choices
# =========================
class PayoutStatus(models.TextChoices):
    PENDING = "PENDING", "Pending Transfer Initiation"
    INITIATED = "INITIATED", "Transfer Initiated (Paystack Queue)"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"
    REVERSED = "REVERSED", "Reversed/Cancelled"


# =========================
# Custom Manager
# =========================
class PayoutManager(models.Manager):
    def pending(self):
        return self.filter(status=PayoutStatus.PENDING)

    def processing(self):
        return self.filter(status=PayoutStatus.INITIATED)

    def completed_successfully(self):
        return self.filter(status=PayoutStatus.SUCCESS)

    def failed(self):
        return self.filter(status=PayoutStatus.FAILED)


# =========================
# Payout Model
# =========================
class Payout(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    job = models.ForeignKey(
        Job,
        on_delete=models.SET_NULL,
        null=True,
        related_name="payouts",
    )

    freelancer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="initiated_payouts",
    )

    # ---- Constants ----
    EXCHANGE_RATE = Decimal("110.00")  # 1 USD = 110 KES
    MINIMUM_PAYOUT_KES = Decimal("1000.00")

    currency = models.CharField(max_length=3, default="KES", editable=False)

    # USD withdrawn from earnings
    usd_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        null=True,  # Add this
        blank=True, # Add this
        help_text="Amount in USD to withdraw",
    )

    # Calculated KES sent via Paystack
    payout_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        editable=False,
        null=True,  # Add this
        blank=True, # Add this
        help_text="Calculated amount in KES",
    )

    fee_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        blank=True,
        null=True,
    )

    recipient_code = models.CharField(
        max_length=255,
        help_text="Paystack Recipient Code",
    )

    transfer_code = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
    )

    status = models.CharField(
        max_length=20,
        choices=PayoutStatus.choices,
        default=PayoutStatus.PENDING,
        db_index=True,
    )

    reference = models.CharField(max_length=255, unique=True, blank=True)

    response_data = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    retry_count = models.PositiveIntegerField(default=0)
    last_retry_at = models.DateTimeField(null=True, blank=True)

    processed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PayoutManager()

    # =========================
    # Properties (Fixes Admin errors)
    # =========================
    @property
    def is_completed(self):
        return self.status in [
            PayoutStatus.SUCCESS,
            PayoutStatus.FAILED,
            PayoutStatus.REVERSED,
        ]

    @property
    def can_retry(self):
        return self.status == PayoutStatus.FAILED and self.retry_count < 3

    @property
    def net_amount(self):
        return self.payout_amount - (self.fee_amount or Decimal("0.00"))

    # =========================
    # Validation
    # =========================
    def clean(self):
        # Calculate payout amount
        if self.usd_amount:
            self.payout_amount = (
                self.usd_amount * self.EXCHANGE_RATE
            ).quantize(Decimal("0.01"))

        # Minimum payout validation
        if (
            self.payout_amount is not None
            and self.payout_amount < self.MINIMUM_PAYOUT_KES
        ):
            raise ValidationError(
                {
                    "usd_amount": (
                        f"At {self.EXCHANGE_RATE} KES/$, this equals "
                        f"{self.payout_amount} KES. Minimum payout is "
                        f"{self.MINIMUM_PAYOUT_KES} KES."
                    )
                }
            )

        # Freelancer ownership validation
        if self.job and self.freelancer != self.job.freelancer:
            raise ValidationError(
                {"freelancer": "Freelancer must match the job owner."}
            )

    # =========================
    # Save Override
    # =========================
    def save(self, *args, **kwargs):
        # Ensure ID is generated for reference segment
        if not self.id:
            self.id = uuid.uuid4()

        # Generate unique reference
        if not self.reference:
            self.reference = f"PAY-{str(self.id).split('-')[0].upper()}"

        # Ensure conversion always happens
        if self.usd_amount:
            self.payout_amount = (
                self.usd_amount * self.EXCHANGE_RATE
            ).quantize(Decimal("0.01"))

        # Run validations (business logic)
        self.full_clean()

        super().save(*args, **kwargs)

    # =========================
    # Status Transitions
    # =========================
    @transaction.atomic
    def mark_as_initiated(self, transfer_code, user=None):
        self.status = PayoutStatus.INITIATED
        self.transfer_code = transfer_code
        self.save()
        self.log_status_update(
            f"Transfer initiated: {transfer_code}", user=user
        )

    @transaction.atomic
    def mark_as_success(self, response_data=None, user=None):
        self.status = PayoutStatus.SUCCESS
        self.response_data = response_data or self.response_data
        self.processed_at = timezone.now()
        self.save()
        self.log_status_update("Payout successful", response_data, user)

    @transaction.atomic
    def mark_as_failed(self, error_message, response_data=None, user=None):
        self.status = PayoutStatus.FAILED
        self.error_message = error_message
        self.retry_count += 1
        self.last_retry_at = timezone.now()
        self.save()
        self.log_status_update(
            f"Failed: {error_message}", response_data, user
        )

    # =========================
    # Logging
    # =========================
    def log_status_update(self, status_update, response_data=None, user=None):
        PayoutLog.objects.create(
            payout=self,
            status_update=status_update,
            response_data=response_data,
            triggered_by=user,
        )

    def __str__(self):
        return (
            f"Payout {self.reference} "
            f"(${self.usd_amount} → {self.payout_amount} KES)"
        )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["freelancer", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(usd_amount__gt=0),
                name="usd_amount_positive",
            )
        ]


# =========================
# Payout Log Model
# =========================
class PayoutLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    payout = models.ForeignKey(
        Payout,
        on_delete=models.CASCADE,
        related_name="logs",
    )

    status_update = models.CharField(max_length=255)
    response_data = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    def __str__(self):
        return (
            f"{self.timestamp.strftime('%Y-%m-%d %H:%M')} - "
            f"{self.status_update[:50]}"
        )

    class Meta:
        ordering = ["timestamp"]
        verbose_name = "Payout Log"
        verbose_name_plural = "Payout Logs"