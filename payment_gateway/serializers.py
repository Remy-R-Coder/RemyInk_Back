from rest_framework import serializers
from .models import Payment, PaymentStatus, PaymentWebhookLog
from orders.models import Job, JobStatus


# =============================
# IDENTITY RESOLVER (SAFE + FIXED)
# =============================
def resolve_actor_context(request):
    """
    Supports:
    - Auth users
    - Session-based users
    - Guest checkout users
    """

    if not request:
        return None

    # -----------------------------
    # AUTH USER
    # -----------------------------
    user = getattr(request, "user", None)

    if user and user.is_authenticated:
        return {
            "user": user,
            "type": "auth",
            "id": str(user.pk)
        }

    # -----------------------------
    # SESSION / GUEST
    # -----------------------------
    session_key = (
        getattr(request, "query_params", {}).get("session_key")
        or getattr(request, "data", {}).get("session_key")
        or request.COOKIES.get("sessionid")
    )

    if not session_key:
        return None

    try:
        from django.contrib.sessions.models import Session
        from django.contrib.auth import get_user_model

        User = get_user_model()

        session = Session.objects.get(session_key=session_key)
        session_data = session.get_decoded()

        uid = session_data.get("_auth_user_id")

        if uid:
            user = User.objects.get(pk=uid)
            return {
                "user": user,
                "type": "session",
                "id": str(user.pk)
            }

        # PURE GUEST
        return {
            "user": None,
            "type": "guest",
            "id": session_key
        }

    except Exception:
        return None


# =============================
# PAYMENT SERIALIZER
# =============================
class PaymentSerializer(serializers.ModelSerializer):

    job_title = serializers.CharField(source='job.title', read_only=True)
    job_id = serializers.ReadOnlyField(source='job.id')

    # FIX: prevent crash when user is NULL (guest payments)
    user_email = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()

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
        read_only_fields = fields

    def get_user_email(self, obj):
        return getattr(obj.user, "email", None) if obj.user else None

    def get_username(self, obj):
        return getattr(obj.user, "username", None) if obj.user else "Guest"


# =============================
# PAYMENT INIT
# =============================
class PaymentInitializeSerializer(serializers.Serializer):

    job_id = serializers.UUIDField(required=True)
    callback_url = serializers.URLField(required=False, allow_blank=True)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)  # 🔥 FIX: explicit guest support

    def validate(self, attrs):
        request = self.context.get("request")

        actor = resolve_actor_context(request)

        if not actor:
            raise serializers.ValidationError(
                "Identity verification failed."
            )

        actor_id = actor["id"]
        job_id = attrs.get("job_id")

        try:
            job = Job.objects.only("id", "client_id", "status").get(id=job_id)
        except Job.DoesNotExist:
            raise serializers.ValidationError("Job not found")

        # -----------------------------
        # OWNERSHIP CHECK
        # -----------------------------
        if str(job.client_id) != str(actor_id):
            raise serializers.ValidationError(
                "You are not authorized to pay for this job."
            )

        # -----------------------------
        # JOB STATE CHECK
        # -----------------------------
        if job.status not in [
            JobStatus.PROVISIONAL,
            JobStatus.PENDING_PAYMENT,
            JobStatus.PAYMENT_FAILED
        ]:
            raise serializers.ValidationError(
                f"Job not payable. Current status: {job.get_status_display()}"
            )

        # -----------------------------
        # PAYMENT ALREADY EXISTS
        # -----------------------------
        if job.payments.filter(status=PaymentStatus.SUCCESS).exists():
            raise serializers.ValidationError(
                "This job is already paid."
            )

        # -----------------------------
        # IDEMPOTENCY
        # -----------------------------
        idempotency_key = attrs.get("idempotency_key")

        if idempotency_key:
            existing = job.payments.filter(
                idempotency_key=idempotency_key
            ).exclude(
                status=PaymentStatus.SUCCESS
            ).first()

            if existing:
                attrs["existing_payment"] = existing

        # -----------------------------
        # SAFE EMAIL STORAGE FOR VIEW
        # -----------------------------
        attrs["job"] = job
        attrs["actor"] = actor

        return attrs


# =============================
# VERIFY
# =============================
class PaymentVerifySerializer(serializers.Serializer):
    reference = serializers.CharField(required=True, max_length=255)


# =============================
# WEBHOOK LOG
# =============================
class PaymentWebhookLogSerializer(serializers.ModelSerializer):

    class Meta:
        model = PaymentWebhookLog
        fields = [
            'id', 'event_type', 'reference', 'payload',
            'payment', 'processed', 'processing_error', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


# =============================
# STATUS RESPONSE
# =============================
class PaymentStatusSerializer(serializers.Serializer):

    reference = serializers.CharField()
    status = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    paid_at = serializers.DateTimeField(allow_null=True)
    job_id = serializers.UUIDField()
    job_status = serializers.CharField()