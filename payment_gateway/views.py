from rest_framework import status, viewsets, serializers
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.db import transaction
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
    serializer_class = PaymentInitializeSerializer

    def post(self, request):
        serializer = PaymentInitializeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        job = get_object_or_404(Job, id=serializer.validated_data['job_id'])
        callback_url = serializer.validated_data.get('callback_url')
        paystack = PaystackService()

        try:
            user = request.user if request.user.is_authenticated else None

            payment = Payment.objects.create(
                job=job,
                user=user,
                amount=job.total_amount,
                currency='USD',
                reference=paystack.generate_reference(),
                status=PaymentStatus.PENDING,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )

            # ✅ SAFE EMAIL HANDLING
            email = (
                request.user.email
                if request.user.is_authenticated
                else serializer.validated_data.get("client_email")
            )

            if not email:
                return Response(
                    {"error": "Email is required for payment"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            response_data = paystack.initialize_payment(
                email=email,
                amount=job.total_amount,
                reference=payment.reference,
                callback_url=callback_url,
                metadata={
                    'job_id': str(job.id),
                    'job_title': job.title,
                    'user_id': str(request.user.id) if request.user.is_authenticated else None,
                    'payment_id': str(payment.id)
                }
            )

            if not response_data or not response_data.get('status'):
                raise ValueError(
                    response_data.get('message', 'Payment initialization failed')
                    if response_data else "No response from Paystack"
                )

            paystack_payload = response_data.get('data', {})

            payment.authorization_url = paystack_payload.get('authorization_url')
            payment.access_code = paystack_payload.get('access_code')
            payment.currency = paystack_payload.get('_currency_used', payment.currency)
            payment.paystack_response = response_data
            payment.save()

            job.status = JobStatus.PENDING_PAYMENT
            job.paystack_reference = payment.reference
            job.paystack_authorization_url = payment.authorization_url
            job.paystack_status = 'pending'
            job.save()

            return Response({
                'message': 'Payment initialized successfully',
                'payment': PaymentSerializer(payment).data,
                'authorization_url': payment.authorization_url,
                'reference': payment.reference
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Payment initialization failed: {str(e)}")
            return Response(
                {'error': 'Failed to initialize payment', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        return x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')


# =========================
# VERIFY PAYMENT
# =========================
class VerifyPaymentView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentVerifySerializer

    def post(self, request):
        serializer = PaymentVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment = get_object_or_404(Payment, reference=serializer.validated_data['reference'])

        if payment.user and payment.user != request.user:
            return Response(
                {'error': 'You are not authorized to verify this payment'},
                status=status.HTTP_403_FORBIDDEN
            )

        if payment.is_successful:
            return Response({
                'message': 'Payment already verified',
                'payment': PaymentSerializer(payment).data
            })

        paystack = PaystackService()

        try:
            verification_data = paystack.verify_payment(payment.reference)

            if verification_data and verification_data.get('status'):
                with transaction.atomic():
                    payment.mark_as_successful(
                        paystack_data=verification_data.get('data')
                    )

                return Response({
                    'message': 'Payment verified successfully',
                    'payment': PaymentSerializer(payment).data,
                    'job_status': payment.job.get_status_display()
                })

            else:
                error_detail = (
                    verification_data.get('message')
                    if verification_data else 'Verification failed'
                )

                payment.mark_as_failed(reason=error_detail)

                return Response({
                    'error': 'Payment verification failed',
                    'payment': PaymentSerializer(payment).data,
                    'detail': error_detail
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Payment verification failed: {str(e)}")
            return Response(
                {'error': 'Failed to verify payment', 'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# =========================
# PAYMENT STATUS
# =========================
class PaymentStatusView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request, job_id):
        job = get_object_or_404(Job, id=job_id)

        if job.client != request.user and job.freelancer != request.user:
            return Response(
                {'error': 'You are not authorized to view this payment'},
                status=status.HTTP_403_FORBIDDEN
            )

        payment = job.payments.order_by('-created_at').first()

        if not payment:
            return Response(
                {'error': 'No payment found for this job'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(PaymentStatusSerializer({
            'reference': payment.reference,
            'status': payment.get_status_display(),
            'amount': payment.amount,
            'paid_at': payment.paid_at,
            'job_id': job.id,
            'job_status': job.get_status_display()
        }).data)


# =========================
# WEBHOOK
# =========================
class PaystackWebhookView(APIView):
    permission_classes = [AllowAny]
    serializer_class = EmptySerializer

    def post(self, request):
        signature = request.headers.get('X-Paystack-Signature')

        if not signature:
            return Response({'error': 'No signature'}, status=400)

        paystack = PaystackService()

        if not paystack.verify_webhook_signature(request.body, signature):
            return Response({'error': 'Invalid signature'}, status=401)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return Response({'error': 'Invalid JSON'}, status=400)

        event_type = data.get('event')
        event_data = data.get('data', {})

        reference = (
            event_data.get('reference')
            or event_data.get('data', {}).get('reference')
        )

        webhook_log = PaymentWebhookLog.objects.create(
            event_type=event_type,
            reference=reference or 'unknown',
            payload=data
        )

        try:
            if event_type == 'charge.success':
                self._handle_success(event_data, webhook_log)

            elif event_type == 'charge.failed':
                self._handle_failed(event_data, webhook_log)

            webhook_log.processed = True
            webhook_log.save(update_fields=['processed'])

        except Exception as e:
            webhook_log.processing_error = str(e)
            webhook_log.save(update_fields=['processing_error'])

            return Response({'error': 'Processing failed'}, status=500)

        return Response({'message': 'Webhook processed'}, status=200)

    # =========================
    def _handle_success(self, event_data, webhook_log):
        reference = (
            event_data.get('reference')
            or event_data.get('data', {}).get('reference')
        )

        if not reference:
            webhook_log.processing_error = "Missing reference"
            webhook_log.save()
            return

        try:
            payment = Payment.objects.get(reference=reference)
            webhook_log.payment = payment
            webhook_log.save(update_fields=['payment'])

            if not payment.is_successful:
                with transaction.atomic():
                    payment.mark_as_successful(paystack_data=event_data)

        except Payment.DoesNotExist:
            webhook_log.processing_error = "Payment not found"
            webhook_log.save()

    # =========================
    def _handle_failed(self, event_data, webhook_log):
        reference = (
            event_data.get('reference')
            or event_data.get('data', {}).get('reference')
        )

        if not reference:
            webhook_log.processing_error = "Missing reference"
            webhook_log.save()
            return

        try:
            payment = Payment.objects.get(reference=reference)
            webhook_log.payment = payment
            webhook_log.save(update_fields=['payment'])

            payment.refresh_from_db()
            reason = event_data.get('gateway_response', 'Payment failed')
            payment.mark_as_failed(reason=reason)

        except Payment.DoesNotExist:
            webhook_log.processing_error = "Payment not found"
            webhook_log.save()


# =========================
# VIEWSETS
# =========================
class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payment.objects.none()

        return Payment.objects.filter(
            user=self.request.user
        ).select_related('job', 'user')


class PaymentWebhookLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentWebhookLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff:
            return PaymentWebhookLog.objects.all().select_related('payment')

        return PaymentWebhookLog.objects.none()