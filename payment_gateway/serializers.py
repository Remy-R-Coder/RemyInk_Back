from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import Payment, PaymentStatus, PaymentWebhookLog
from orders.models import Job, JobStatus

User = get_user_model()


# =============================
# IDENTITY RESOLVER
# =============================
def resolve_actor_context(request):
    if not request:
        return None

    user = getattr(request, "user", None)

    # AUTH USER
    if user and user.is_authenticated:
        return {
            "user": user,
            "type": "auth",
            "id": str(user.pk),
            "email": user.email
        }

    # GUEST
    email = (
        getattr(request, "data", {}).get("email")
        or getattr(request, "query_params", {}).get("email")
    )

    session_key = (
        getattr(request, "data", {}).get("session_key")
        or getattr(request, "query_params", {}).get("session_key")
    )

    if email or session_key:
        return {
            "user": None,
            "type": "guest",
            "id": email or session_key,
            "email": email
        }

    return None


# =============================
# PAYMENT SERIALIZER
# =============================
class PaymentSerializer(serializers.ModelSerializer):

    job_title = serializers.CharField(source="job.title", read_only=True)
    job_id = serializers.ReadOnlyField(source="job.id")

    user_email = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id", "job", "job_id", "job_title",
            "user", "user_email", "username",
            "amount", "currency",
            "reference",
            "authorization_url", "access_code",
            "status",
            "verified_at", "paid_at",
            "created_at", "updated_at"
        ]
        read_only_fields = fields

    def get_user_email(self, obj):
        if obj.user:
            return obj.user.email
        return getattr(obj, "guest_email", None)

    def get_username(self, obj):
        if obj.user:
            return obj.user.username
        return "Guest"


# =============================
# PAYMENT INIT SERIALIZER
# =============================
class PaymentInitializeSerializer(serializers.Serializer):

    job_id = serializers.UUIDField(required=True)
    callback_url = serializers.URLField(required=False, allow_blank=True)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)


    def validate(self, attrs):
        request = self.context.get("request")

        actor = resolve_actor_context(request)
        if not actor:
            raise serializers.ValidationError("Invalid actor")

        job_id = attrs["job_id"]

        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist:
            raise serializers.ValidationError("Job not found")

        email = attrs.get("email")

        # =========================
        # AUTH USER RULE
        # =========================
        if actor["type"] == "auth":
            if str(job.client_id) != str(actor["id"]):
                raise serializers.ValidationError(
                    "Not authorized to pay for this job."
                )

            # fallback email from user account
            if not email:
                email = actor["user"].email

        # =========================
        # GUEST RULE
        # =========================
        elif actor["type"] == "guest":
            if not email:
                raise serializers.ValidationError(
                    "Guest checkout requires email."
                )

        # =========================
        # JOB STATUS CHECK
        # =========================
        if job.status not in [
            JobStatus.PROVISIONAL,
            JobStatus.PENDING_PAYMENT,
            JobStatus.PAYMENT_FAILED
        ]:
            raise serializers.ValidationError("Job not payable")

        # =========================
        # ALREADY PAID CHECK
        # =========================
        if job.payments.filter(status=PaymentStatus.SUCCESS).exists():
            raise serializers.ValidationError("Job already paid")

        # =========================
        # IDEMPOTENCY CHECK
        # =========================
        idempotency_key = attrs.get("idempotency_key")

        if idempotency_key:
            existing = job.payments.filter(
                idempotency_key=idempotency_key
            ).exclude(status=PaymentStatus.SUCCESS).first()

            if existing:
                attrs["existing_payment"] = existing

        # =========================
        # FINAL OUTPUT
        # =========================
        attrs["job"] = job
        attrs["actor"] = actor
        attrs["email"] = email

        return attrs

# =============================
# VERIFY SERIALIZER
# =============================
class PaymentVerifySerializer(serializers.Serializer):
    reference = serializers.CharField()


# =============================
# WEBHOOK LOG SERIALIZER
# =============================
class PaymentWebhookLogSerializer(serializers.ModelSerializer):

    class Meta:
        model = PaymentWebhookLog
        fields = "__all__"
        read_only_fields = fields


# =============================
# STATUS SERIALIZER
# =============================
class PaymentStatusSerializer(serializers.Serializer):
    reference = serializers.CharField()
    status = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    paid_at = serializers.DateTimeField(allow_null=True)
    job_id = serializers.UUIDField()
    job_status = serializers.CharField()