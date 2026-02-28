from rest_framework import serializers
from .models import Payment, PaymentStatus, PaymentWebhookLog
from orders.models import Job


class PaymentSerializer(serializers.ModelSerializer):
    """Serializer for Payment model"""

    job_title = serializers.CharField(source='job.title', read_only=True)
    job_id = serializers.UUIDField(source='job.id', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id', 'job', 'job_id', 'job_title', 'user', 'user_email', 'username',
            'amount', 'currency', 'reference', 'authorization_url', 'access_code',
            'status', 'verified_at', 'paid_at', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'job_id', 'job_title', 'user_email', 'username',
            'reference', 'authorization_url', 'access_code', 'status',
            'verified_at', 'paid_at', 'created_at', 'updated_at'
        ]


class PaymentInitializeSerializer(serializers.Serializer):
    """Serializer for payment initialization request"""

    job_id = serializers.UUIDField(required=True)
    callback_url = serializers.URLField(required=False, allow_blank=True)

    def validate_job_id(self, value):
        """Validate that job exists and belongs to the user"""
        try:
            job = Job.objects.get(id=value)
        except Job.DoesNotExist:
            raise serializers.ValidationError("Job not found")

        # Check if user is the client for this job
        user = self.context['request'].user
        if job.client != user:
            raise serializers.ValidationError("You are not authorized to pay for this job")

        # Check if job is in PROVISIONAL or PAYMENT_FAILED status
        from orders.models import JobStatus
        if job.status not in [JobStatus.PROVISIONAL, JobStatus.PAYMENT_FAILED, JobStatus.PENDING_PAYMENT]:
            raise serializers.ValidationError(
                f"Job is not awaiting payment. Current status: {job.get_status_display()}"
            )

        # Check if there's already a successful payment
        if job.payments.filter(status=PaymentStatus.SUCCESS).exists():
            raise serializers.ValidationError("This job has already been paid for")

        return value


class PaymentVerifySerializer(serializers.Serializer):
    """Serializer for payment verification request"""

    reference = serializers.CharField(required=True, max_length=255)


class PaymentWebhookLogSerializer(serializers.ModelSerializer):
    """Serializer for webhook logs"""

    class Meta:
        model = PaymentWebhookLog
        fields = [
            'id', 'event_type', 'reference', 'payload',
            'payment', 'processed', 'processing_error', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class PaymentStatusSerializer(serializers.Serializer):
    """Serializer for payment status response"""

    reference = serializers.CharField()
    status = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    paid_at = serializers.DateTimeField(allow_null=True)
    job_id = serializers.UUIDField()
    job_status = serializers.CharField()
