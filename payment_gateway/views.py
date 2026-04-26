from rest_framework import status, viewsets, serializers
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.conf import settings
import logging
import json

from .models import Payment, PaymentWebhookLog, PaymentStatus
from .serializers import (
    PaymentSerializer,
    PaymentInitializeSerializer,
    PaymentVerifySerializer,
    PaymentStatusSerializer,
    PaymentWebhookLogSerializer
)
from .services import PaystackService
from orders.models import Job, JobStatus

logger = logging.getLogger(__name__)


class EmptySerializer(serializers.Serializer):
    pass


# =========================
# INITIALIZE PAYMENT
# =========================
class InitializePaymentView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PaymentInitializeSerializer(
            data=request.data,
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        job = serializer.validated_data["job"]
        actor = serializer.validated_data["actor"]
        email = serializer.validated_data["email"]
        callback_url = serializer.validated_data.get("callback_url") or settings.PAYSTACK_CALLBACK_URL
        existing_payment = serializer.validated_data.get("existing_payment")

        paystack = PaystackService()

        try:
            # -------------------------
            # RESUME PAYMENT
            # -------------------------
            if existing_payment:
                return Response({
                    "message": "Existing payment session resumed",
                    "payment": PaymentSerializer(existing_payment).data,
                    "authorization_url": existing_payment.authorization_url,
                    "reference": existing_payment.reference
                }, status=status.HTTP_200_OK)

            # -------------------------
            # EMAIL CHECK
            # -------------------------
            email = email or getattr(actor.get("user"), "email", None)

            if not email:
                return Response(
                    {"error": "Email is required for payment"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # -------------------------
            # CREATE PAYMENT
            # -------------------------
            with transaction.atomic():
                payment = Payment.objects.create(
                    job=job,
                    user=actor["user"] if actor["type"] == "auth" else None,
                    amount=job.total_amount,
                    currency="USD",
                    reference=paystack.generate_reference() if hasattr(paystack, 'generate_reference') else f"JOB-{job.id}-{int(transaction.now().timestamp())}",
                    status=PaymentStatus.PENDING,
                    ip_address=self._get_client_ip(request),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )

            # -------------------------
            # PAYSTACK INIT (FIXED METHOD NAME 🔥)
            # -------------------------
            # Your PaystackService uses 'initialize_transaction'
            response = paystack.initialize_transaction(
                email=email,
                amount=job.total_amount,
                reference=payment.reference,
                metadata={
                    "job_id": str(job.id),
                    "actor_type": actor["type"],
                    "payment_id": str(payment.id),
                    "callback_url": callback_url
                }
            )

            if not response or not response.get("status"):
                raise ValueError(
                    response.get("message", "Paystack initialization failed")
                    if response else "No response from Paystack"
                )

            data = response.get("data", {})

            payment.authorization_url = data.get("authorization_url")
            payment.access_code = data.get("access_code")
            payment.paystack_response = response
            payment.save()

            # Update Job
            job.status = JobStatus.PENDING_PAYMENT
            # Using hasattr to prevent crashes if fields aren't on Job model
            if hasattr(job, 'paystack_reference'):
                job.paystack_reference = payment.reference
            if hasattr(job, 'paystack_authorization_url'):
                job.paystack_authorization_url = payment.authorization_url
            
            job.save()

            return Response({
                "message": "Payment initialized successfully",
                "payment": PaymentSerializer(payment).data,
                "authorization_url": payment.authorization_url,
                "reference": payment.reference
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            # Adding exc_info=True will print the full traceback to your server logs
            logger.error(f"Payment initialization failed: {str(e)}", exc_info=True)
            return Response(
                {"error": "Payment initialization failed", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _get_client_ip(self, request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        return xff.split(",")[0] if xff else request.META.get("REMOTE_ADDR")


# =========================
# VERIFY PAYMENT
# =========================
class VerifyPaymentView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PaymentVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment = get_object_or_404(
            Payment,
            reference=serializer.validated_data["reference"]
        )

        if payment.user:
            if not request.user.is_authenticated:
                return Response({"error": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)

            if payment.user != request.user:
                return Response({"error": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)

        if payment.is_successful:
            return Response({
                "message": "Already verified",
                "payment": PaymentSerializer(payment).data
            })

        paystack = PaystackService()

        try:
            # FIXED: Updated to match service method name 'verify_transaction'
            result = paystack.verify_transaction(payment.reference)

            if result and result.get("status"):
                with transaction.atomic():
                    payment.mark_as_successful(result.get("data"))

                return Response({
                    "message": "Payment verified successfully",
                    "payment": PaymentSerializer(payment).data,
                    "job_status": payment.job.get_status_display()
                })

            payment.mark_as_failed(reason="Verification failed")

            return Response(
                {"error": "Verification failed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            logger.error(f"Verification error: {str(e)}", exc_info=True)
            return Response(
                {"error": "Verification error", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# =========================
# PAYMENT STATUS
# =========================
class PaymentStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        job = get_object_or_404(Job, id=job_id)

        if job.client != request.user and job.freelancer != request.user:
            return Response({"error": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)

        payment = job.payments.order_by("-created_at").first()

        if not payment:
            return Response({"error": "No payment found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(PaymentStatusSerializer({
            "reference": payment.reference,
            "status": payment.status,
            "amount": payment.amount,
            "paid_at": payment.paid_at,
            "job_id": job.id,
            "job_status": job.status
        }).data)


# =========================
# WEBHOOK
# =========================
class PaystackWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            try:
                data = json.loads(request.body.decode("utf-8"))
            except json.JSONDecodeError:
                return Response({"error": "Invalid payload"}, status=400)

            event = data.get("event")
            payload = data.get("data", {})
            reference = payload.get("reference")

            log = PaymentWebhookLog.objects.create(
                event_type=event,
                reference=reference or "unknown",
                payload=data
            )

            payment = Payment.objects.filter(reference=reference).first()

            if payment:
                log.payment = payment
                log.save(update_fields=["payment"])

                if payment.is_successful:
                    return Response({"status": "already processed"})

                if event == "charge.success":
                    payment.mark_as_successful(payload)

                elif event == "charge.failed":
                    payment.mark_as_failed(reason="Webhook failure")

            log.processed = True
            log.save(update_fields=["processed"])

            return Response({"status": "ok"})

        except Exception as e:
            logger.error(f"Webhook processing failed: {str(e)}", exc_info=True)
            return Response({"error": "Webhook failed"}, status=500)


# =========================
# VIEWSETS
# =========================
class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Payment.objects.filter(user=self.request.user)


class PaymentWebhookLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentWebhookLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff:
            return PaymentWebhookLog.objects.all()
        return PaymentWebhookLog.objects.none()