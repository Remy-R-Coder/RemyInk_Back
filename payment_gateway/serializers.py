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
    job_id = serializers.UUIDField(required=True)
    callback_url = serializers.URLField(required=False, allow_blank=True)

    def validate(self, attrs):
        request = self.context['request']
        user = request.user

        job_id = attrs.get('job_id')

        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist:
            raise serializers.ValidationError({"job_id": "Job not found"})

        # Updated: Allow access if user is authenticated client OR if it's a valid guest session
        # This prevents the 400 error for unauthenticated guest checkouts
        is_authenticated_client = user.is_authenticated and job.client == user
        is_guest_checkout = not user.is_authenticated and request.query_params.get('session_key')

        if not (is_authenticated_client or is_guest_checkout):
            raise serializers.ValidationError({"job_id": "Not authorized for this job"})

        from orders.models import JobStatus

        if job.status not in [
            JobStatus.PROVISIONAL,
            JobStatus.PAYMENT_FAILED,
            JobStatus.PENDING_PAYMENT
        ]:
            raise serializers.ValidationError({
                "job_id": f"Invalid job status: {job.get_status_display()}"
            })

        if job.payments.filter(status=PaymentStatus.SUCCESS).exists():
            raise serializers.ValidationError({
                "job_id": "Job already paid"
            })

        attrs["job"] = job  # attach job object (important optimization)
        return attrs


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