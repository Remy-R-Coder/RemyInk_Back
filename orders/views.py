import json
import hashlib
import hmac
import logging
import mimetypes
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.http import FileResponse
from rest_framework import viewsets, status, serializers
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.exceptions import PermissionDenied, ValidationError, NotAuthenticated
from rest_framework.decorators import action
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiExample

from .models import Job, JobStatus, Dispute
from .serializers import JobSerializer, JobCreateSerializer, JobSubmissionSerializer, DisputeSerializer
from .paystack_service import PaystackService
from .throttles import OrdersAnonRateThrottle, OrdersUserRateThrottle
from user_module.models import Role, Rating, GuestSession as ShadowGuestSession

logger = logging.getLogger(__name__)
User = get_user_model()


class EmptySerializer(serializers.Serializer):
    pass


def _is_guest_linked_client(user):
    if not user or user.role != Role.CLIENT:
        return False

    if ShadowGuestSession.objects.filter(shadow_client=user).exists():
        return True

    try:
        from chat.models import GuestSession as ChatGuestSession
        if ChatGuestSession.objects.filter(converted_to_user=user).exists():
            return True
    except Exception:
        pass

    return False


def _mark_guest_session_converted(job, client_user):
    source_offer = job.source_offer.select_related('thread').first()
    if not source_offer or not source_offer.thread or not source_offer.thread.guest_session_key:
        return

    session_key = source_offer.thread.guest_session_key
    try:
        from chat.models import GuestSession
        guest_session = GuestSession.objects.filter(session_key=session_key).first()
        if guest_session:
            guest_session.mark_converted(client_user)
    except Exception as exc:
        logger.warning(f"Failed to mark guest session converted for job {job.id}: {exc}")


def _send_password_setup_email(user, job):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    frontend_base = str(getattr(settings, 'FRONTEND_URL', '') or '').strip().rstrip('/')
    if frontend_base:
        setup_link = f"{frontend_base}/set-password?uid={uid}&token={token}"
    else:
        backend_base = str(getattr(settings, 'BACKEND_BASE_URL', 'http://127.0.0.1:8000')).strip().rstrip('/')
        setup_link = f"{backend_base}/api/users/password/setup/confirm/?uid={uid}&token={token}"

    send_mail(
        subject='Your RemyInk client account is ready',
        message=(
            f'Hello {user.username},\n\n'
            f'Your account has been created after your payment for "{job.title}".\n'
            f'Email: {user.email}\n'
            'Set your password securely using this link:\n'
            f'{setup_link}\n\n'
            'This link is time-limited and can only be used once.\n\n'
            'RemyInk Team'
        ),
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
        recipient_list=[user.email],
        fail_silently=False,
    )


def _send_account_activated_email(user, job):
    send_mail(
        subject='Your RemyInk client account is now active',
        message=(
            f'Hello {user.username},\n\n'
            f'Payment received for "{job.title}".\n'
            f'Your account is now active with this email: {user.email}\n\n'
            'You can now log in and continue.\n\n'
            'RemyInk Team'
        ),
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
        recipient_list=[user.email],
        fail_silently=False,
    )


def _finalize_shadow_client_after_payment(job, gateway_data=None):
    client_user = job.client
    if not client_user or not _is_guest_linked_client(client_user):
        return

    data = gateway_data or {}
    metadata = data.get('metadata') if isinstance(data, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    customer = data.get('customer') if isinstance(data, dict) else {}
    customer = customer if isinstance(customer, dict) else {}

    candidate_email = metadata.get('client_email') or customer.get('email') or client_user.email or ''
    normalized_email = User.objects.normalize_email(str(candidate_email).strip())
    if not normalized_email:
        logger.warning(f"Unable to finalize client for job {job.id}: no customer email from payment gateway.")
        return

    existing_user = (
        User.objects
        .filter(email__iexact=normalized_email)
        .exclude(pk=client_user.pk)
        .first()
    )

    if existing_user:
        if existing_user.role != Role.CLIENT:
            logger.warning(
                f"Cannot finalize shadow client for job {job.id}: "
                f"email {normalized_email} belongs to non-client account."
            )
            return

        if job.client_id != existing_user.id:
            job.client = existing_user
            job.save(update_fields=['client'])

        source_offer = job.source_offer.select_related('thread').first()
        if source_offer and source_offer.thread and source_offer.thread.client_id != existing_user.id:
            source_offer.thread.client = existing_user
            source_offer.thread.save(update_fields=['client'])

        _mark_guest_session_converted(job, existing_user)
        if not existing_user.has_usable_password() and _is_guest_linked_client(existing_user):
            try:
                _send_password_setup_email(existing_user, job)
            except Exception as exc:
                logger.warning(f"Failed to send setup email to existing client {existing_user.email}: {exc}")
        return

    update_fields = []
    if client_user.email != normalized_email:
        client_user.email = normalized_email
        update_fields.append('email')
    if not client_user.is_active:
        client_user.is_active = True
        update_fields.append('is_active')
    if update_fields:
        client_user.save(update_fields=update_fields)

    _mark_guest_session_converted(job, client_user)

    try:
        if client_user.has_usable_password():
            _send_account_activated_email(client_user, job)
        else:
            _send_password_setup_email(client_user, job)
    except Exception as exc:
        logger.warning(f"Failed to send post-payment account email to {client_user.email}: {exc}")

class InitializePaystackView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OrdersAnonRateThrottle, OrdersUserRateThrottle]

    @extend_schema(
        summary='Initialize Paystack payment for a job',
        request={
            'application/json': {
                'type': 'object',
                'required': ['job_id'],
                'properties': {
                    'job_id': {'type': 'string', 'format': 'uuid'},
                    'session_key': {'type': 'string', 'description': 'Optional if passed as query param.'},
                    'client_email': {
                        'type': 'string',
                        'format': 'email',
                        'description': 'Required for guest/shadow client jobs.',
                    },
                    'client_password': {
                        'type': 'string',
                        'minLength': 8,
                        'description': 'Required for guest/shadow client jobs when no existing client account matches client_email.',
                    },
                    'client_password_confirm': {
                        'type': 'string',
                        'minLength': 8,
                        'description': 'Must match client_password.',
                    },
                },
            }
        },
        responses={
            201: {
                'type': 'object',
                'properties': {
                    'authorizationUrl': {'type': 'string', 'format': 'uri'},
                    'reference': {'type': 'string'},
                },
            },
            400: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                    'detail': {'type': 'string'},
                    'client_email': {'type': 'string'},
                    'client_password': {'type': 'string'},
                    'client_password_confirm': {'type': 'string'},
                },
            },
            401: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                },
            },
            404: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                },
            },
        },
        examples=[
            OpenApiExample(
                'Guest init request',
                request_only=True,
                value={
                    'job_id': '7ced640e-1d73-423c-90bf-37796f564db1',
                    'client_email': 'client@example.com',
                    'client_password': 'StrongPass123!',
                    'client_password_confirm': 'StrongPass123!',
                },
            ),
            OpenApiExample(
                'Init success',
                response_only=True,
                status_codes=['201'],
                value={
                    'authorizationUrl': 'https://checkout.paystack.com/abcd1234',
                    'reference': 'JOB-7ced640e-1d73-423c-90bf-37796f564db1-1772259985',
                },
            ),
            OpenApiExample(
                'Missing guest password',
                response_only=True,
                status_codes=['400'],
                value={'client_password': 'This field is required.'},
            ),
            OpenApiExample(
                'Password mismatch',
                response_only=True,
                status_codes=['400'],
                value={'client_password_confirm': 'Passwords do not match.'},
            ),
            OpenApiExample(
                'Auth/session missing',
                response_only=True,
                status_codes=['401'],
                value={'error': 'Authentication required or session_key is required.'},
            ),
        ],
    )
    def post(self, request):
        job_id = request.data.get('job_id')
        if not job_id:
            return Response({'error': 'Job ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        payer_user = None
        allowed_retry_statuses = [JobStatus.PROVISIONAL, JobStatus.PAYMENT_FAILED]

        if request.user and request.user.is_authenticated:
            try:
                job = Job.objects.get(
                    id=job_id,
                    client=request.user,
                    status__in=allowed_retry_statuses
                )
                payer_user = request.user
            except Job.DoesNotExist:
                return Response(
                    {'error': 'Job not found or not eligible for payment retry.'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            session_key = request.query_params.get('session_key') or request.data.get('session_key')
            if not session_key:
                return Response(
                    {'error': 'Authentication required or session_key is required.'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            try:
                job = Job.objects.select_related('client').get(
                    id=job_id,
                    status__in=allowed_retry_statuses,
                    source_offer__thread__guest_session_key=str(session_key).strip()
                )
            except Job.DoesNotExist:
                return Response(
                    {'error': 'Job not found or not eligible for payment retry.'},
                    status=status.HTTP_404_NOT_FOUND
                )

            payer_user = job.client
            if not payer_user:
                return Response({'error': 'Job has no client account attached.'}, status=status.HTTP_400_BAD_REQUEST)

        if job.total_amount <= 0:
            return Response({'error': 'Job amount must be positive.'}, status=status.HTTP_400_BAD_REQUEST)

        if not payer_user.email:
            return Response({'error': 'Client account email is missing.'}, status=status.HTTP_400_BAD_REQUEST)

        payment_email = payer_user.email
        client_email = (request.data.get('client_email') or request.query_params.get('client_email') or '').strip()
        client_password = request.data.get('client_password') or request.query_params.get('client_password') or ''
        client_password_confirm = request.data.get('client_password_confirm') or request.query_params.get('client_password_confirm') or ''
        if str(payer_user.email).endswith('.shadow'):
            if not client_email:
                return Response(
                    {'error': 'client_email is required to initialize guest payment.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            normalized_email = User.objects.normalize_email(client_email)
            existing_user = (
                User.objects
                .filter(email__iexact=normalized_email)
                .exclude(pk=payer_user.pk)
                .first()
            )
            if existing_user and existing_user.role != Role.CLIENT:
                return Response({'client_email': 'This email is already registered.'}, status=status.HTTP_400_BAD_REQUEST)
            payment_email = normalized_email
            if not existing_user:
                if not client_password:
                    return Response({'client_password': 'This field is required.'}, status=status.HTTP_400_BAD_REQUEST)
                if len(client_password) < 8:
                    return Response({'client_password': 'Password must be at least 8 characters.'}, status=status.HTTP_400_BAD_REQUEST)
                if client_password != client_password_confirm:
                    return Response(
                        {'client_password_confirm': 'Passwords do not match.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                payer_user.email = normalized_email
                payer_user.set_password(client_password)
                payer_user.save(update_fields=['email', 'password'])

        if job.status == JobStatus.PAYMENT_FAILED:
            # Always issue a fresh reference on retry after failure.
            reference = f"JOB-{job_id}-{int(timezone.now().timestamp())}"
        else:
            reference = job.paystack_reference or f"JOB-{job_id}-{int(timezone.now().timestamp())}"

        try:
            paystack = PaystackService()
            metadata = {"job_id": str(job.id), "client_id": str(payer_user.id)}
            if client_email:
                metadata["client_email"] = payment_email
            response = paystack.initialize_transaction(
                email=payment_email,
                amount=job.total_amount,
                reference=reference,
                metadata=metadata
            )

            if response and response.get('status'):
                auth_url = response['data']['authorization_url']
                with transaction.atomic():
                    job.paystack_reference = reference
                    job.paystack_authorization_url = auth_url
                    job.status = JobStatus.PENDING_PAYMENT
                    job.save()
                logger.info(f"Paystack Init for Job {job_id} success. Ref: {reference}")
                return Response({'authorizationUrl': auth_url, 'reference': reference}, status=status.HTTP_201_CREATED)
            gateway_message = (response or {}).get('message', 'Payment initialization failed')
            logger.warning(f"Paystack initialization failed for job {job_id}: {gateway_message}")
            return Response(
                {'error': 'Payment initialization failed.', 'detail': gateway_message},
                status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            logger.error(f"Error during Paystack initialization for job {job_id}: {e}", exc_info=True)
            return Response({'error': 'Unexpected error during payment setup.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PaystackWebhookView(APIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = EmptySerializer

    def post(self, request):
        payload = request.body.decode('utf-8')
        sig_header = request.META.get('HTTP_X_PAYSTACK_SIGNATURE')

        try:
            computed_signature = hmac.new(
                key=settings.PAYSTACK_WEBHOOK_SECRET.encode('utf-8'),
                msg=payload.encode('utf-8'),
                digestmod=hashlib.sha512
            ).hexdigest()
            if computed_signature != sig_header:
                logger.error("Paystack Webhook: Signature verification failed.")
                return Response({'error': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error verifying Paystack signature: {e}")
            return Response(status=status.HTTP_400_BAD_REQUEST)

        event = json.loads(payload)
        reference = event.get('data', {}).get('reference')
        if not reference:
            return Response(status=status.HTTP_200_OK)

        event_type = event.get('event')
        logger.info(f"Paystack webhook received: Event: {event_type}, Ref: {reference}")

        try:
            job = Job.objects.get(paystack_reference=reference)
        except Job.DoesNotExist:
            logger.warning(f"Job not found for reference: {reference}")
            return Response(status=status.HTTP_200_OK)

        if event_type == 'charge.success' and job.status == JobStatus.PAID:
            return Response(status=status.HTTP_200_OK)

        try:
            with transaction.atomic():
                if event_type == 'charge.success':
                    verifier = PaystackService()
                    verification_response = verifier.verify_transaction(reference)
                    if (verification_response and verification_response.get('status') and
                        verification_response['data']['status'] == 'success' and
                        verification_response['data']['amount'] == int(job.total_amount * 100)):
                        job.status = JobStatus.PAID
                        job.paystack_status = event['data'].get('status')
                        job.save()
                        _finalize_shadow_client_after_payment(job, verification_response.get('data') or {})
                        logger.info(f"Job {job.id} updated to PAID via Webhook. Ref: {reference}")
                    else:
                        logger.error(f"Job {job.id}: Webhook success but verification failed.")
                elif event_type in ['charge.failed', 'transaction.abandoned']:
                    job.status = JobStatus.PAYMENT_FAILED
                    job.paystack_status = event['data'].get('status')
                    job.save()
                    logger.warning(f"Job {job.id} updated to PAYMENT_FAILED via Webhook.")
        except Exception as e:
            logger.error(f"Error processing webhook for job {job.id}: {e}", exc_info=True)
            return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(status=status.HTTP_200_OK)


class JobViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    throttle_classes = [OrdersAnonRateThrottle, OrdersUserRateThrottle]
    queryset = Job.objects.select_related('client', 'freelancer', 'submission')

    def get_serializer_class(self):
        if self.action == 'create':
            return JobCreateSerializer
        return JobSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user

        if user and user.is_authenticated:
            if user.role == 'CLIENT':
                return self.queryset.filter(client=user)
            elif user.role == 'FREELANCER':
                return self.queryset.filter(freelancer=user)
            elif getattr(user, 'is_staff', False) or user.role == 'ADMIN':
                return self.queryset
            return self.queryset.none()

        session_key = (self.request.query_params.get('session_key') or '').strip()
        if not session_key:
            raise NotAuthenticated('Authentication credentials were not provided.')

        return self.queryset.filter(source_offer__thread__guest_session_key=session_key).distinct()

    def _refresh_payment_status(self, job):
        if job.status != JobStatus.PENDING_PAYMENT or not job.paystack_reference:
            return job

        verification = PaystackService().verify_transaction(job.paystack_reference)
        if not verification or not verification.get('status'):
            return job

        data = verification.get('data') or {}
        gateway_status = str(data.get('status') or '').lower()
        gateway_amount = data.get('amount')
        expected_amount = int(job.total_amount * 100)

        update_fields = []
        if gateway_status == 'success' and gateway_amount == expected_amount and job.status != JobStatus.PAID:
            job.status = JobStatus.PAID
            update_fields.append('status')
        elif gateway_status in ['failed', 'abandoned', 'reversed'] and job.status != JobStatus.PAYMENT_FAILED:
            job.status = JobStatus.PAYMENT_FAILED
            update_fields.append('status')

        incoming_paystack_status = data.get('status')
        if incoming_paystack_status and job.paystack_status != incoming_paystack_status:
            job.paystack_status = incoming_paystack_status
            update_fields.append('paystack_status')

        if update_fields:
            job.save(update_fields=update_fields)
            if job.status == JobStatus.PAID:
                _finalize_shadow_client_after_payment(job, data)
            logger.info(
                f"Refreshed payment status for Job {job.id} via verify. "
                f"Status={job.status}, Ref={job.paystack_reference}"
            )

        return job

    @extend_schema(
        summary='Retrieve job details (guest or authenticated)',
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'id': {'type': 'string', 'format': 'uuid'},
                    'status': {'type': 'string'},
                    'status_display': {'type': 'string'},
                    'post_payment': {
                        'type': 'object',
                        'properties': {
                            'next': {'type': 'string', 'enum': ['login', 'password_setup']},
                            'redirect_to': {'type': 'string'},
                            'message': {'type': 'string'},
                        },
                    },
                },
            },
        },
        examples=[
            OpenApiExample(
                'Paid job response with login redirect',
                response_only=True,
                status_codes=['200'],
                value={
                    'id': '7ced640e-1d73-423c-90bf-37796f564db1',
                    'status': 'PAID',
                    'status_display': 'Paid by Client - Funds Held',
                    'post_payment': {
                        'next': 'login',
                        'redirect_to': '/login',
                        'message': 'Payment successful. Log in with your email and password to continue.'
                    }
                },
            )
        ],
    )
    def retrieve(self, request, *args, **kwargs):
        job = self.get_object()
        job = self._refresh_payment_status(job)
        if job.status == JobStatus.PAID and job.client and not job.client.is_active and _is_guest_linked_client(job.client):
            _finalize_shadow_client_after_payment(job)
            job.refresh_from_db()
        data = self.get_serializer(job).data
        if job.status == JobStatus.PAID and not (request.user and request.user.is_authenticated):
            if job.client and job.client.is_active and job.client.has_usable_password():
                data['post_payment'] = {
                    'next': 'login',
                    'redirect_to': '/login',
                    'message': 'Payment successful. Log in with your email and password to continue.'
                }
            elif job.client and not job.client.has_usable_password():
                data['post_payment'] = {
                    'next': 'password_setup',
                    'message': 'Payment successful. Check your email to finish password setup.'
                }
        return Response(data)

    def perform_create(self, serializer):
        if self.request.user.role != 'CLIENT':
            raise PermissionDenied("Only clients can create jobs.")
        base_price = serializer.validated_data['price']
        total_amount_client_pays = base_price + (base_price * settings.CLIENT_FEE_PERCENTAGE)
        serializer.save(client=self.request.user, total_amount=total_amount_client_pays, status=JobStatus.PROVISIONAL)

    def _start_work_transition(self, request, job):
        if request.user != job.freelancer:
            raise PermissionDenied("Only the assigned freelancer can start this job.")
        if job.status not in [JobStatus.PAID, JobStatus.ASSIGNED]:
            raise ValidationError(
                f"Job cannot be moved to 'In Progress' from {job.get_status_display()}."
            )
        job.status = JobStatus.IN_PROGRESS
        job.save(update_fields=['status', 'updated_at'])
        return Response(JobSerializer(job, context={'request': request}).data, status=status.HTTP_200_OK)

    def _validate_submission_download_access(self, request, job):
        if request.user and request.user.is_authenticated:
            if (
                request.user == job.client
                or request.user == job.freelancer
                or getattr(request.user, 'is_staff', False)
                or getattr(request.user, 'role', None) == 'ADMIN'
            ):
                return True
            raise PermissionDenied("You are not allowed to access this submission.")

        session_key = (request.query_params.get('session_key') or '').strip()
        if not session_key:
            raise NotAuthenticated('Authentication credentials were not provided.')

        if job.source_offer.filter(thread__guest_session_key=session_key).exists():
            return True

        raise PermissionDenied("Invalid guest session for this submission.")

    def _download_file_field(self, file_field):
        if not file_field:
            raise ValidationError({'detail': 'Attachment file not found.'})

        filename = (getattr(file_field, 'name', '') or '').split('/')[-1] or 'attachment'
        content_type, _ = mimetypes.guess_type(filename)
        return FileResponse(
            file_field.open('rb'),
            as_attachment=True,
            filename=filename,
            content_type=content_type or 'application/octet-stream',
        )

    def _ensure_dispute_access(self, request, job):
        user = request.user
        if not user or not user.is_authenticated:
            raise NotAuthenticated('Authentication credentials were not provided.')
        if (
            user == job.client
            or user == job.freelancer
            or getattr(user, 'is_staff', False)
            or getattr(user, 'role', None) == Role.ADMIN
        ):
            return True
        raise PermissionDenied("You are not allowed to access this dispute.")

    def _notify_dispute_event(self, recipient, title, message, job, dispute):
        try:
            from notifications.models import Notification
            Notification.objects.create(
                recipient=recipient,
                notification_type='JOB_UPDATED',
                category='JOB',
                title=title,
                message=message,
                link=f'/job/{job.id}',
                metadata={
                    'job_id': str(job.id),
                    'dispute_id': str(dispute.id),
                    'dispute_status': dispute.status,
                }
            )
        except Exception as exc:
            logger.warning(f"Failed to create dispute notification for job {job.id}: {exc}")

    @action(detail=True, methods=['post'], url_path='start-work')
    def start_work(self, request, pk=None):
        job = self.get_object()
        return self._start_work_transition(request, job)

    @action(detail=True, methods=['post'], url_path='start')
    def start(self, request, pk=None):
        job = self.get_object()
        return self._start_work_transition(request, job)

    @action(detail=True, methods=['post'], url_path='mark-in-progress')
    def mark_in_progress(self, request, pk=None):
        job = self.get_object()
        return self._start_work_transition(request, job)

    @action(detail=True, methods=['post'], url_path='in-progress')
    def in_progress(self, request, pk=None):
        job = self.get_object()
        return self._start_work_transition(request, job)

    @action(detail=True, methods=['post'], url_path='status')
    def update_status(self, request, pk=None):
        requested_status = str(request.data.get('status') or '').strip().upper()
        if requested_status != JobStatus.IN_PROGRESS:
            raise ValidationError({'status': 'Only IN_PROGRESS transition is supported on this endpoint.'})
        job = self.get_object()
        return self._start_work_transition(request, job)

    @action(detail=True, methods=['post'], url_path='submit')
    @extend_schema(
        request=JobSubmissionSerializer,
        responses={200: JobSerializer},
        examples=[
            OpenApiExample(
                'Text + attachments delivery',
                request_only=True,
                value={
                    'submission_text': 'Project delivered. Please review the attached files.',
                    'attachments': ['<file1>', '<file2>'],
                },
            )
        ],
    )
    def submit(self, request, pk=None):
        job = self.get_object()
        if request.user != job.freelancer:
            raise PermissionDenied("Only the assigned freelancer can submit this job.")
        if job.status not in [JobStatus.IN_PROGRESS, JobStatus.DISPUTE_OPEN]:
            raise ValidationError(
                f"Job can only be submitted from In Progress or Dispute Open. Current status: {job.get_status_display()}."
            )
        if job.status == JobStatus.DISPUTE_OPEN and int(job.reviews_used or 0) >= int(job.allowed_reviews or 0):
            raise ValidationError({'detail': 'No review rounds remaining for this order.'})

        payload = request.data.copy()
        merged_attachments = []
        if hasattr(request, 'FILES'):
            merged_attachments.extend(request.FILES.getlist('attachments'))
            merged_attachments.extend(request.FILES.getlist('attachments[]'))
        if merged_attachments:
            payload.setlist('attachments', merged_attachments)

        existing_submission = getattr(job, 'submission', None)
        revision_round = (existing_submission.revision_round + 1) if existing_submission else 1
        serializer = (
            JobSubmissionSerializer(existing_submission, data=payload, partial=True)
            if existing_submission
            else JobSubmissionSerializer(data=payload)
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            if existing_submission:
                serializer.save(revision_round=revision_round, submitted_at=timezone.now())
            else:
                serializer.save(job=job, revision_round=revision_round)

            update_fields = ['status', 'updated_at']
            if job.status == JobStatus.DISPUTE_OPEN:
                job.reviews_used = int(job.reviews_used or 0) + 1
                update_fields.append('reviews_used')
            job.status = JobStatus.DELIVERED
            job.save(update_fields=update_fields)

            if hasattr(job, 'dispute') and job.dispute.status in ['OPEN', 'IN_REVIEW']:
                job.dispute.status = 'OPEN'
                job.dispute.save(update_fields=['status'])
        return Response(JobSerializer(job, context={'request': request}).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='submission/attachments')
    def submission_attachments(self, request, pk=None):
        job = self.get_object()
        self._validate_submission_download_access(request, job)
        if not hasattr(job, 'submission'):
            raise ValidationError({'detail': 'No submission found for this job.'})

        submission = job.submission
        attachments = []
        for label, file_field in [
            ('assignment', submission.assignment),
            ('plag_report', submission.plag_report),
            ('ai_report', submission.ai_report),
        ]:
            if not file_field:
                continue
            name = (file_field.name or '').split('/')[-1]
            attachments.append({
                'kind': 'legacy',
                'label': label,
                'name': name,
                'download_url': f'/api/orders/jobs/{job.id}/submission/legacy/{label}/download/',
            })

        for att in submission.attachments.all():
            if not att.file:
                continue
            name = (att.file.name or '').split('/')[-1]
            attachments.append({
                'kind': 'deliverable',
                'id': att.id,
                'label': 'deliverable',
                'name': name,
                'download_url': f'/api/orders/jobs/{job.id}/submission/attachments/{att.id}/download/',
            })

        return Response({'attachments': attachments}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path=r'submission/attachments/(?P<attachment_id>\d+)/download')
    def download_submission_attachment(self, request, pk=None, attachment_id=None):
        job = self.get_object()
        self._validate_submission_download_access(request, job)
        if not hasattr(job, 'submission'):
            raise ValidationError({'detail': 'No submission found for this job.'})

        try:
            attachment = job.submission.attachments.get(id=attachment_id)
        except Exception:
            raise ValidationError({'detail': 'Attachment not found for this job.'})

        return self._download_file_field(attachment.file)

    @action(detail=True, methods=['get'], url_path=r'submission/legacy/(?P<legacy_key>assignment|plag_report|ai_report)/download')
    def download_legacy_submission_attachment(self, request, pk=None, legacy_key=None):
        job = self.get_object()
        self._validate_submission_download_access(request, job)
        if not hasattr(job, 'submission'):
            raise ValidationError({'detail': 'No submission found for this job.'})

        file_field = getattr(job.submission, legacy_key, None)
        return self._download_file_field(file_field)

    @action(detail=True, methods=['post'], url_path='complete')
    def complete(self, request, pk=None):
        job = self.get_object()
        if job.client != request.user:
            raise PermissionDenied("Only the client can mark the job complete.")
        if job.status != JobStatus.DELIVERED:
            raise ValidationError(f"Job is not yet delivered. Current status: {job.get_status_display()}.")
        with transaction.atomic():
            job.status = JobStatus.CLIENT_COMPLETED
            job.client_marked_complete_at = timezone.now()
            job.save(update_fields=['status', 'client_marked_complete_at', 'updated_at'])
            if hasattr(job, 'dispute') and job.dispute.status in ['OPEN', 'IN_REVIEW']:
                dispute = job.dispute
                dispute.status = 'RESOLVED_PAID'
                if not dispute.admin_resolution_notes:
                    dispute.admin_resolution_notes = 'Auto-resolved after client approved delivered revision.'
                dispute.resolved_at = timezone.now()
                dispute.save(update_fields=['status', 'admin_resolution_notes', 'resolved_at'])
        return Response(JobSerializer(job, context={'request': request}).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='rate-freelancer')
    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'required': ['score'],
                'properties': {
                    'score': {'type': 'number', 'format': 'float', 'minimum': 1, 'maximum': 5},
                    'review': {'type': 'string'},
                },
            }
        },
        responses={200: {'type': 'object'}},
        examples=[
            OpenApiExample(
                'Rate freelancer request',
                request_only=True,
                value={'score': 4.5, 'review': 'Great delivery and communication.'},
            ),
            OpenApiExample(
                'Rate freelancer response',
                response_only=True,
                status_codes=['200'],
                value={
                    'status': 'rated',
                    'created': True,
                    'rating': {
                        'score': '4.5',
                        'review': 'Great delivery and communication.',
                    },
                    'job_status': 'CLIENT_COMPLETED',
                },
            ),
        ],
    )
    def rate_freelancer(self, request, pk=None):
        from user_module.serializers import RatingSerializer

        job = self.get_object()
        if job.client != request.user:
            raise PermissionDenied("Only the client can rate the freelancer.")
        if not job.freelancer:
            raise ValidationError({'error': 'Job has no assigned freelancer.'})
        if job.status not in [JobStatus.DELIVERED, JobStatus.CLIENT_COMPLETED]:
            raise ValidationError(
                {'error': f'Freelancer can only be rated after delivery. Current status: {job.get_status_display()}.'}
            )

        score = request.data.get('score')
        if score in (None, ''):
            raise ValidationError({'score': 'This field is required.'})
        try:
            score_value = float(score)
        except (TypeError, ValueError):
            raise ValidationError({'score': 'Score must be a number between 1 and 5.'})
        if score_value < 1 or score_value > 5:
            raise ValidationError({'score': 'Score must be between 1 and 5.'})

        review = request.data.get('review', '')
        with transaction.atomic():
            rating, created = Rating.objects.update_or_create(
                job=job,
                rater=request.user,
                defaults={
                    'rated_user': job.freelancer,
                    'score': score_value,
                    'review': review,
                }
            )
            if job.status == JobStatus.DELIVERED:
                job.status = JobStatus.CLIENT_COMPLETED
                job.client_marked_complete_at = timezone.now()
                job.save(update_fields=['status', 'client_marked_complete_at', 'updated_at'])
                if hasattr(job, 'dispute') and job.dispute.status in ['OPEN', 'IN_REVIEW']:
                    dispute = job.dispute
                    dispute.status = 'RESOLVED_PAID'
                    if not dispute.admin_resolution_notes:
                        dispute.admin_resolution_notes = 'Auto-resolved after client approved delivered revision.'
                    dispute.resolved_at = timezone.now()
                    dispute.save(update_fields=['status', 'admin_resolution_notes', 'resolved_at'])

        payload = {
            'status': 'rated',
            'created': created,
            'rating': RatingSerializer(rating, context={'request': request}).data,
            'job_status': job.status,
            'job_status_display': job.get_status_display(),
        }
        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get', 'post'], url_path='dispute')
    @extend_schema(request=DisputeSerializer, responses={200: DisputeSerializer})
    def dispute(self, request, pk=None):
        job = self.get_object()

        if request.method == 'GET':
            self._ensure_dispute_access(request, job)
            if not hasattr(job, 'dispute'):
                raise ValidationError({'detail': 'No dispute found for this job.'})
            return Response(
                DisputeSerializer(job.dispute, context={'request': request}).data,
                status=status.HTTP_200_OK
            )

        if job.client != request.user:
            raise PermissionDenied("Only the client can raise disputes.")
        if job.status not in [JobStatus.DELIVERED, JobStatus.CLIENT_COMPLETED]:
            raise ValidationError(
                f"Disputes can only be raised on delivered or completed jobs. Current status: {job.get_status_display()}."
            )
        if hasattr(job, 'dispute'):
            existing_dispute = job.dispute
            if (
                existing_dispute.status in ['OPEN', 'IN_REVIEW']
                and job.status in [JobStatus.DELIVERED, JobStatus.CLIENT_COMPLETED]
            ):
                with transaction.atomic():
                    existing_dispute.reason = request.data.get('reason') or existing_dispute.reason
                    existing_dispute.status = 'OPEN'
                    existing_dispute.save(update_fields=['reason', 'status'])
                    job.status = JobStatus.DISPUTE_OPEN
                    job.save(update_fields=['status', 'updated_at'])
                return Response(
                    {
                        'detail': 'Dispute reopened for additional revision.',
                        'dispute': DisputeSerializer(existing_dispute, context={'request': request}).data,
                    },
                    status=status.HTTP_200_OK
                )
            return Response(
                {
                    'detail': 'Dispute already exists for this job.',
                    'dispute': DisputeSerializer(existing_dispute, context={'request': request}).data,
                },
                status=status.HTTP_200_OK
            )

        serializer = DisputeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            dispute = serializer.save(job=job, raised_by=request.user, status='OPEN')
            job.status = JobStatus.DISPUTE_OPEN
            job.save(update_fields=['status', 'updated_at'])

        if job.freelancer:
            self._notify_dispute_event(
                recipient=job.freelancer,
                title='Dispute Opened',
                message=f'A dispute was opened for "{job.title}".',
                job=job,
                dispute=dispute,
            )
        self._notify_dispute_event(
            recipient=job.client,
            title='Dispute Opened',
            message=f'Your dispute for "{job.title}" has been opened.',
            job=job,
            dispute=dispute,
        )

        return Response(
            DisputeSerializer(dispute, context={'request': request}).data,
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'], url_path='dispute/in-review')
    @extend_schema(request=None, responses={200: DisputeSerializer})
    def dispute_in_review(self, request, pk=None):
        job = self.get_object()
        if not (getattr(request.user, 'is_staff', False) or getattr(request.user, 'role', None) == Role.ADMIN):
            raise PermissionDenied("Only admins can move disputes to in review.")
        if not hasattr(job, 'dispute'):
            raise ValidationError({'detail': 'No dispute found for this job.'})

        dispute = job.dispute
        dispute.status = 'IN_REVIEW'
        dispute.save(update_fields=['status'])
        if job.status != JobStatus.DISPUTE_OPEN:
            job.status = JobStatus.DISPUTE_OPEN
            job.save(update_fields=['status', 'updated_at'])

        self._notify_dispute_event(
            recipient=job.client,
            title='Dispute In Review',
            message=f'Your dispute for "{job.title}" is now in review.',
            job=job,
            dispute=dispute,
        )
        if job.freelancer:
            self._notify_dispute_event(
                recipient=job.freelancer,
                title='Dispute In Review',
                message=f'The dispute for "{job.title}" is now in review.',
                job=job,
                dispute=dispute,
            )

        return Response(DisputeSerializer(dispute, context={'request': request}).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='dispute/resolve')
    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'required': ['resolution'],
                'properties': {
                    'resolution': {'type': 'string', 'enum': ['refund_client', 'pay_freelancer']},
                    'admin_resolution_notes': {'type': 'string'},
                },
            }
        },
        responses={200: DisputeSerializer},
    )
    def resolve_dispute(self, request, pk=None):
        job = self.get_object()
        if not (getattr(request.user, 'is_staff', False) or getattr(request.user, 'role', None) == Role.ADMIN):
            raise PermissionDenied("Only admins can resolve disputes.")
        if not hasattr(job, 'dispute'):
            raise ValidationError({'detail': 'No dispute found for this job.'})

        resolution = str(request.data.get('resolution') or '').strip().lower()
        if resolution not in ['refund_client', 'pay_freelancer']:
            raise ValidationError({'resolution': 'Must be one of: refund_client, pay_freelancer.'})
        notes = (request.data.get('admin_resolution_notes') or '').strip()

        dispute = job.dispute
        with transaction.atomic():
            dispute.status = 'RESOLVED_REFUND' if resolution == 'refund_client' else 'RESOLVED_PAID'
            dispute.admin_resolution_notes = notes
            dispute.resolved_at = timezone.now()
            dispute.save(update_fields=['status', 'admin_resolution_notes', 'resolved_at'])

            job.status = JobStatus.DISPUTE_RESOLVED
            job.save(update_fields=['status', 'updated_at'])

        self._notify_dispute_event(
            recipient=job.client,
            title='Dispute Resolved',
            message=f'Your dispute for "{job.title}" has been resolved.',
            job=job,
            dispute=dispute,
        )
        if job.freelancer:
            self._notify_dispute_event(
                recipient=job.freelancer,
                title='Dispute Resolved',
                message=f'The dispute for "{job.title}" has been resolved.',
                job=job,
                dispute=dispute,
            )

        return Response(DisputeSerializer(dispute, context={'request': request}).data, status=status.HTTP_200_OK)
