from rest_framework import serializers
from .models import Payment, PaymentStatus, PaymentWebhookLog
from orders.models import Job, JobStatus

# --- INTERNAL HELPER ---
# Since utils.py doesn't exist, we define the identity resolver here.
def resolve_actor_context(request):
    """
    Determines if the requester is an Authenticated User 
    or a Guest with a valid session key.
    """
    if not request:
        return None
        
    # 1. Standard Auth (Highest Priority)
    if request.user and request.user.is_authenticated:
        return {"user": request.user, "type": "auth", "id": request.user.pk}

    # 2. Extract Session Key from multiple possible sources
    session_key = (
        request.query_params.get('session_key') or 
        request.data.get('session_key') or 
        request.COOKIES.get('sessionid')
    )
    
    if session_key:
        from django.contrib.sessions.models import Session
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            session = Session.objects.get(session_key=session_key)
            session_data = session.get_decoded()
            
            # Look for the user ID tied to this session
            uid = session_data.get('_auth_user_id')
            if uid:
                user = User.objects.get(pk=uid)
                return {"user": user, "type": "session", "id": user.pk}
            
            # --- GUEST FALLBACK ---
            # If there's no user ID, treat the session_key string as the identifier.
            # This allows unauthenticated users to pay for jobs linked to their session.
            return {"user": None, "type": "guest", "id": session_key}
            
        except (Session.DoesNotExist, User.DoesNotExist):
            import logging
            logging.getLogger(__name__).warning(f"Session {session_key} not found or user missing.")
            
    return None

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
            'id', 'job_id', 'job_title',
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
            
            # 1. Identity Check
            actor_context = resolve_actor_context(request)

            if not actor_context:
                raise serializers.ValidationError(
                    "Identity verification failed. Invalid session or authentication."
                )

            # Use the 'id' key (can be User PK or Session String)
            actor_id = actor_context["id"]
            actor_user = actor_context["user"] # Might be None for guests
            job_id = attrs.get("job_id")

            try:
                job = Job.objects.only("id", "client_id", "status").get(id=job_id)
            except Job.DoesNotExist:
                raise serializers.ValidationError("Job not found")

            # -----------------------------
            # 2. OWNERSHIP CHECK (Guest Safe)
            # -----------------------------
            # Convert both to strings to ensure UUIDs and Session Strings match correctly
            if str(job.client_id) != str(actor_id):
                raise serializers.ValidationError(
                    "You are not authorized to pay for this job."
                )

            # 3. Valid Job State Check
            if job.status not in [
                JobStatus.PROVISIONAL,
                JobStatus.PENDING_PAYMENT,
                JobStatus.PAYMENT_FAILED
            ]:
                raise serializers.ValidationError(
                    f"Job is not awaiting payment. Current status: {job.get_status_display()}"
                )

            # 4. Success Payment Guard
            if job.payments.filter(status=PaymentStatus.SUCCESS).exists():
                raise serializers.ValidationError(
                    "This job has already been paid for."
                )

            # 5. Idempotency Safety Check
            idempotency_key = attrs.get("idempotency_key")

            if idempotency_key:
                existing_payment = job.payments.filter(
                    idempotency_key=idempotency_key
                ).exclude(
                    status__in=[PaymentStatus.SUCCESS, PaymentStatus.FAILED]
                ).select_related("job", "user").first()

                if existing_payment:
                    # Compare stored user/session against current actor
                    # Using getattr to avoid errors if actor_user is None
                    existing_user_id = existing_payment.user_id or existing_payment.session_key
                    if str(existing_user_id) != str(actor_id):
                        raise serializers.ValidationError(
                            "Invalid payment session ownership."
                        )

                    attrs["existing_payment"] = existing_payment

            # Attach validated objects for the view layer
            attrs["job"] = job
            attrs["actor_user"] = actor_user # View handles if this is None

            return attrs

class PaymentVerifySerializer(serializers.Serializer):
    """Serializer for payment verification request"""
    reference = serializers.CharField(required=True, max_length=255)


class PaymentWebhookLogSerializer(serializers.ModelSerializer):
    """Immutable webhook audit log serializer"""

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