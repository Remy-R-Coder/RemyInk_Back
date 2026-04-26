from rest_framework import serializers
from .models import Payment, PaymentStatus, PaymentWebhookLog
from orders.models import Job, JobStatus

from payments.utils import resolve_actor_context


class PaymentSerializer(serializers.ModelSerializer):
    """Serializer for Payment model"""

    job_title = serializers.CharField(source='job.title', read_only=True)
    job_id = serializers.ReadOnlyField(source='job.id')

    user_email = serializers.EmailField(source='user.email', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id', 'job', 'job_id', 'job_title',
            'user', 'user_email', 'username',
            'amount', 'currency',
            'reference',
            'authorization_url', 'access_code',
            'status',
            'verified_at', 'paid_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id',
            'job_id', 'job_title',
            'user_email', 'username',
            'reference', 'authorization_url', 'access_code',
            'status',
            'verified_at', 'paid_at',
            'created_at', 'updated_at'
        ]


class PaymentInitializeSerializer(serializers.Serializer):
    """Serializer for payment initialization request"""

    job_id = serializers.UUIDField(required=True)
    callback_url = serializers.URLField(required=False, allow_blank=True)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        request = self.context.get('request')
        actor_context = resolve_actor_context(request)

        if not actor_context:
            raise serializers.ValidationError(
                "Identity verification failed. Invalid session or authentication."
            )

        actor_user = actor_context["user"]
        job_id = attrs.get("job_id")

        try:
            job = Job.objects.only("id", "client_id", "status").get(id=job_id)
        except Job.DoesNotExist:
            raise serializers.ValidationError("Job not found")

        # -----------------------------
        # OWNERSHIP CHECK (ID SAFE)
        # -----------------------------
        if job.client_id != actor_user.pk:
            raise serializers.ValidationError(
                "You are not authorized to pay for this job."
            )

        # -----------------------------
        # VALID JOB STATE CHECK
        # -----------------------------
        if job.status not in [
            JobStatus.PROVISIONAL,
            JobStatus.PENDING_PAYMENT,
            JobStatus.PAYMENT_FAILED
        ]:
            raise serializers.ValidationError(
                f"Job is not awaiting payment. Current status: {job.get_status_display()}"
            )

        # -----------------------------
        # SUCCESS PAYMENT GUARD
        # -----------------------------
        if job.payments.filter(status=PaymentStatus.SUCCESS).exists():
            raise serializers.ValidationError(
                "This job has already been paid for."
            )

        # -----------------------------
        # IDEMPOTENCY SAFETY CHECK
        # -----------------------------
        idempotency_key = attrs.get("idempotency_key")

        if idempotency_key:
            existing_payment = job.payments.filter(
                idempotency_key=idempotency_key
            ).exclude(
                status__in=[PaymentStatus.SUCCESS, PaymentStatus.FAILED]
            ).select_related("job", "user").first()

            if existing_payment:
                # ownership safety check
                if existing_payment.user_id != actor_user.pk:
                    raise serializers.ValidationError(
                        "Invalid payment session ownership."
                    )

                attrs["existing_payment"] = existing_payment

        # attach validated objects for view layer
        attrs["job"] = job
        attrs["actor_user"] = actor_user

        return attrs


class PaymentVerifySerializer(serializers.Serializer):
    """Serializer for payment verification request"""

    reference = serializers.CharField(required=True, max_length=255)


class PaymentWebhookLogSerializer(serializers.ModelSerializer):
    """Immutable webhook audit log serializer"""

    class Meta:
        model = PaymentWebhookLog
        fields = [
            'id',
            'event_type',
            'reference',
            'payload',
            'payment',
            'processed',
            'processing_error',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class PaymentStatusSerializer(serializers.Serializer):
    """Serializer for payment status response"""

    reference = serializers.CharField()
    status = serializers.CharField()

    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    paid_at = serializers.DateTimeField(allow_null=True)
    job_id = serializers.UUIDField()
    job_status = serializers.CharField()