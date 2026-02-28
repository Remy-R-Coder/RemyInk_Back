import uuid
from decimal import Decimal
from django.db import models, transaction
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from orders.models import Job 

class PayoutStatus(models.TextChoices):
    PENDING = "PENDING", "Pending Transfer Initiation"
    INITIATED = "INITIATED", "Transfer Initiated (Paystack Queue)"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"
    REVERSED = "REVERSED", "Reversed/Cancelled"

class PayoutManager(models.Manager):
    def pending(self):
        return self.filter(status=PayoutStatus.PENDING)
    
    def processing(self):
        return self.filter(status=PayoutStatus.INITIATED)
    
    def completed_successfully(self):
        return self.filter(status=PayoutStatus.SUCCESS)
    
    def failed(self):
        return self.filter(status=PayoutStatus.FAILED)

class Payout(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.SET_NULL, null=True, related_name='payouts')
    freelancer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='initiated_payouts')
    
    MINIMUM_PAYOUT = Decimal('100.00')
    
    payout_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    fee_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True, 
        default=Decimal('0.00')
    )
    
    recipient_code = models.CharField(max_length=255, help_text="Paystack Recipient Code for bank transfer")
    transfer_code = models.CharField(
        max_length=255, 
        null=True, 
        blank=True, 
        unique=True, 
        db_index=True, 
        help_text="Paystack Transfer Code (e.g., TRF_xxxx)"
    )
    
    status = models.CharField(
        max_length=20, 
        choices=PayoutStatus.choices, 
        default=PayoutStatus.PENDING, 
        db_index=True
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
    
    def __str__(self):
        job_id = self.job.id if self.job else "No Job"
        return f"Payout {self.id} for Job {job_id} ({self.status})"
    
    def clean(self):
        if self.payout_amount <= Decimal('0.00'):
            raise ValidationError({'payout_amount': 'Payout amount must be positive.'})
        
        if self.payout_amount < self.MINIMUM_PAYOUT:
            raise ValidationError({
                'payout_amount': f'Payout amount must be at least {self.MINIMUM_PAYOUT}.'
            })
        
        if self.job and self.freelancer != self.job.freelancer:
            raise ValidationError({'freelancer': 'Freelancer must match the job freelancer when job is specified.'})
    
    @property
    def is_completed(self):
        return self.status in [PayoutStatus.SUCCESS, PayoutStatus.FAILED, PayoutStatus.REVERSED]
    
    @property
    def is_processing(self):
        return self.status == PayoutStatus.INITIATED
    
    @property
    def net_amount(self):
        return self.payout_amount - (self.fee_amount or Decimal('0.00'))
    
    def can_retry(self):
        return self.status == PayoutStatus.FAILED and self.retry_count < 3
    
    @transaction.atomic
    def mark_as_initiated(self, transfer_code, user=None):
        self.status = PayoutStatus.INITIATED
        self.transfer_code = transfer_code
        self.save()
        self.log_status_update(f"Transfer initiated with code: {transfer_code}", user=user)
    
    @transaction.atomic
    def mark_as_success(self, response_data=None, user=None):
        self.status = PayoutStatus.SUCCESS
        self.response_data = response_data or self.response_data
        self.processed_at = timezone.now()
        self.save()
        self.log_status_update("Payout completed successfully", response_data, user)
    
    @transaction.atomic
    def mark_as_failed(self, error_message, response_data=None, user=None):
        self.status = PayoutStatus.FAILED
        self.error_message = error_message
        self.response_data = response_data or self.response_data
        self.save()
        self.log_status_update(f"Payout failed: {error_message}", response_data, user)
    
    def increment_retry_count(self):
        self.retry_count = models.F('retry_count') + 1
        self.last_retry_at = timezone.now()
        self.save(update_fields=['retry_count', 'last_retry_at'])
    
    def log_status_update(self, status_update, response_data=None, user=None):
        PayoutLog.objects.create(
            payout=self,
            status_update=status_update,
            response_data=response_data,
            triggered_by=user
        )
    
    def save(self, *args, **kwargs):
        if not self.reference and not self.pk:
            super().save(*args, **kwargs)
            self.reference = f"PAYOUT-{self.id.hex[:8].upper()}"
            kwargs['force_insert'] = False
            super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Payout Transfer"
        verbose_name_plural = "Payout Transfers"
        indexes = [
            models.Index(fields=['freelancer', 'status']),
            models.Index(fields=['freelancer', 'created_at']),
        ]

class PayoutLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payout = models.ForeignKey(Payout, on_delete=models.CASCADE, related_name='logs')
    status_update = models.CharField(max_length=255)
    response_data = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    
    def __str__(self):
        return f"{self.timestamp.strftime('%Y-%m-%d %H:%M')} - {self.status_update[:50]}"
    
    class Meta:
        ordering = ['timestamp']
        verbose_name = "Payout Log"
        verbose_name_plural = "Payout Logs"