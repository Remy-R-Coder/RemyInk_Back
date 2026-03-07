from rest_framework import status, viewsets, serializers
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
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


class InitializePaymentView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentInitializeSerializer

    def post(self, request):
        serializer = PaymentInitializeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        job = get_object_or_404(Job, id=serializer.validated_data['job_id'])
        callback_url = serializer.validated_data.get('callback_url')
        paystack = PaystackService()

        try:
            payment = Payment.objects.create(
                job=job,
                user=request.user,
                amount=job.total_amount,
                currency='USD',
                reference=paystack.generate_reference(),
                status=PaymentStatus.PENDING,
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )

            response_data = paystack.initialize_payment(
                email=request.user.email,
                amount=job.total_amount,
                reference=payment.reference,
                callback_url=callback_url,
                metadata={
                    'job_id': str(job.id),
                    'job_title': job.title,
                    'user_id': str(request.user.id),
                    'payment_id': str(payment.id)
                }
            )

            if not response_data.get('success'):
                raise ValueError(response_data.get('message', 'Payment initialization failed'))

            paystack_payload = response_data.get('data', {})
            currency_used = paystack_payload.get('_currency_used', payment.currency)
            payment.authorization_url = paystack_payload.get('authorization_url')
            payment.access_code = paystack_payload.get('access_code')
            payment.currency = currency_used
            payment.paystack_response = response_data
            payment.save(update_fields=['authorization_url', 'access_code', 'currency', 'paystack_response', 'updated_at'])

            job.status = JobStatus.PENDING_PAYMENT
            job.paystack_reference = payment.reference
            job.paystack_authorization_url = payment.authorization_url
            job.paystack_status = 'pending'
            job.save(update_fields=['status', 'paystack_reference', 'paystack_authorization_url', 'paystack_status', 'updated_at'])

            return Response({
                'message': 'Payment initialized successfully',
                'payment': PaymentSerializer(payment).data,
                'authorization_url': payment.authorization_url,
                'reference': payment.reference
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Payment initialization failed: {str(e)}")
            return Response({'error': 'Failed to initialize payment', 'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        return x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')


class VerifyPaymentView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentVerifySerializer

    def post(self, request):
        serializer = PaymentVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment = get_object_or_404(Payment, reference=serializer.validated_data['reference'])

        if payment.user != request.user:
            return Response({'error': 'You are not authorized to verify this payment'}, status=status.HTTP_403_FORBIDDEN)

        if payment.is_successful:
            return Response({'message': 'Payment already verified', 'payment': PaymentSerializer(payment).data}, status=status.HTTP_200_OK)

        paystack = PaystackService()

        try:
            verification_data = paystack.verify_payment(payment.reference)

            if verification_data.get('success'):
                with transaction.atomic():
                    payment.mark_as_successful(paystack_data=verification_data.get('data'))

                return Response({'message': 'Payment verified successfully', 'payment': PaymentSerializer(payment).data, 'job_status': payment.job.get_status_display()}, status=status.HTTP_200_OK)
            else:
                error_detail = verification_data.get('message') or verification_data.get('data', {}).get('gateway_response')
                payment.mark_as_failed(reason=error_detail or 'Payment verification failed')
                return Response({'error': 'Payment verification failed', 'payment': PaymentSerializer(payment).data, 'detail': error_detail}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Payment verification failed: {str(e)}")
            return Response({'error': 'Failed to verify payment', 'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PaymentStatusView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request, job_id):
        job = get_object_or_404(Job, id=job_id)

        if job.client != request.user and job.freelancer != request.user:
            return Response({'error': 'You are not authorized to view this payment'}, status=status.HTTP_403_FORBIDDEN)

        payment = job.payments.order_by('-created_at').first()
        if not payment:
            return Response({'error': 'No payment found for this job'}, status=status.HTTP_404_NOT_FOUND)

        return Response(PaymentStatusSerializer({
            'reference': payment.reference,
            'status': payment.get_status_display(),
            'amount': payment.amount,
            'paid_at': payment.paid_at,
            'job_id': job.id,
            'job_status': job.get_status_display()
        }).data, status=status.HTTP_200_OK)


class PaystackWebhookView(APIView):
    permission_classes = [AllowAny]
    serializer_class = EmptySerializer

    def post(self, request):
        signature = request.headers.get('X-Paystack-Signature')
        if not signature:
            return Response({'error': 'No signature'}, status=status.HTTP_400_BAD_REQUEST)

        payload = request.body
        paystack = PaystackService()
        if not paystack.verify_webhook_signature(payload, signature):
            return Response({'error': 'Invalid signature'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return Response({'error': 'Invalid JSON'}, status=status.HTTP_400_BAD_REQUEST)

        event_type = data.get('event')
        event_data = data.get('data', {})
        reference = event_data.get('reference')

        webhook_log = PaymentWebhookLog.objects.create(event_type=event_type, reference=reference or 'unknown', payload=data)

        try:
            if event_type == 'charge.success':
                self._handle_successful_payment(event_data, webhook_log)
            elif event_type == 'charge.failed':
                self._handle_failed_payment(event_data, webhook_log)

            webhook_log.processed = True
            webhook_log.save(update_fields=['processed'])

        except Exception as e:
            webhook_log.processing_error = str(e)
            webhook_log.save(update_fields=['processing_error'])
            return Response({'error': 'Processing failed'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({'message': 'Webhook processed'}, status=status.HTTP_200_OK)

    def _handle_successful_payment(self, event_data, webhook_log):
        reference = event_data.get('reference')
        try:
            payment = Payment.objects.get(reference=reference)
            webhook_log.payment = payment
            webhook_log.save(update_fields=['payment'])
            if not payment.is_successful:
                with transaction.atomic():
                    payment.mark_as_successful(paystack_data=event_data)
        except Payment.DoesNotExist:
            raise

    def _handle_failed_payment(self, event_data, webhook_log):
        reference = event_data.get('reference')
        try:
            payment = Payment.objects.get(reference=reference)
            webhook_log.payment = payment
            webhook_log.save(update_fields=['payment'])
            gateway_response = event_data.get('gateway_response', 'Payment failed')
            payment.mark_as_failed(reason=gateway_response)
        except Payment.DoesNotExist:
            raise


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    queryset = Payment.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payment.objects.none()
        if not getattr(self.request, 'user', None) or not self.request.user.is_authenticated:
            return Payment.objects.none()
        return Payment.objects.filter(user=self.request.user).select_related('job', 'user')


class PaymentWebhookLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentWebhookLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff:
            return PaymentWebhookLog.objects.all().select_related('payment')
        return PaymentWebhookLog.objects.none()
