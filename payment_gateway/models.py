import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class PaymentStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    PROCESSING = 'PROCESSING', 'Processing'
    SUCCESS = 'SUCCESS', 'Success'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    REFUNDED = 'REFUNDED', 'Refunded'


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey('orders.Job', on_delete=models.PROTECT, related_name='payments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='payments_made')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    reference = models.CharField(max_length=255, unique=True, db_index=True)
    authorization_url = models.URLField(max_length=500, blank=True, null=True)
    access_code = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True)
    paystack_response = models.JSONField(default=dict, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['job', '-created_at']),
            models.Index(fields=['reference']),
            models.Index(fields=['status', '-created_at']),
        ]
        verbose_name = "Payment"
        verbose_name_plural = "Payments"

    def __str__(self):
        return f"Payment {self.reference} - {self.status} - {self.currency} {self.amount}"

    @property
    def is_successful(self):
        return self.status == PaymentStatus.SUCCESS

    @property
    def is_pending(self):
        return self.status == PaymentStatus.PENDING

    def mark_as_successful(self, paystack_data=None):
        self.status = PaymentStatus.SUCCESS
        self.verified_at = timezone.now()
        self.paid_at = timezone.now()
        if paystack_data:
            self.paystack_response = paystack_data
        self.save(update_fields=['status', 'verified_at', 'paid_at', 'paystack_response', 'updated_at'])
        from orders.models import JobStatus
        self.job.status = JobStatus.PAID
        self.job.paystack_status = 'success'
        self.job.save(update_fields=['status', 'paystack_status', 'updated_at'])
        return True

    def mark_as_failed(self, reason=None):
        self.status = PaymentStatus.FAILED
        if reason:
            self.paystack_response['failure_reason'] = reason
        self.save(update_fields=['status', 'paystack_response', 'updated_at'])
        from orders.models import JobStatus
        self.job.status = JobStatus.PAYMENT_FAILED
        self.job.paystack_status = 'failed'
        self.job.save(update_fields=['status', 'paystack_status', 'updated_at'])
        return True


class PaymentWebhookLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=100, db_index=True)
    reference = models.CharField(max_length=255, db_index=True)
    payload = models.JSONField()
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='webhook_logs')
    processed = models.BooleanField(default=False)
    processing_error = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reference', '-created_at']),
            models.Index(fields=['event_type', '-created_at']),
            models.Index(fields=['processed', '-created_at']),
        ]
        verbose_name = "Payment Webhook Log"
        verbose_name_plural = "Payment Webhook Logs"

    def __str__(self):
        return f"{self.event_type} - {self.reference} - {'Processed' if self.processed else 'Pending'}"
