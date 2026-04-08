from rest_framework import viewsets, permissions, status, serializers
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser

from django.db.models import Q
from django.db import transaction
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage

from drf_spectacular.utils import extend_schema

from .models import (
    ChatThread,
    ChatMessage,
    MessageReadStatus,
    ChatAttachment,
    GuestSession
)
from .serializers import (
    ChatThreadSerializer,
    ChatMessageSerializer,
    ChatAttachmentSerializer,
    ChatAttachmentUploadSerializer,
)
from .services import ChatMessageService, GuestNameService
from .authentication import OptionalJWTAuthentication
from .throttles import ChatAnonRateThrottle, ChatUserRateThrottle
from user_module.models import Role
from orders.models import Job, JobStatus

import logging

User = get_user_model()
logger = logging.getLogger(__name__)


class EmptySerializer(serializers.Serializer):
    pass


class SessionKeyMixin:
    def get_session_key(self, request):
        return (
            getattr(request.session, 'session_key', None)
            or request.query_params.get('session_key')
        )

    def ensure_session_key(self, request):
        if not request.session.session_key:
            request.session.save()
        return self.get_session_key(request)

def get_thread_or_404(thread_id: int) -> ChatThread:
    try:
        # We fetch the thread simply. Related objects can be fetched later if needed.
        return ChatThread.objects.get(pk=thread_id)
    except ChatThread.DoesNotExist:
        raise NotFound({'error': 'Chat thread does not exist.'})

class IsThreadParticipant(BasePermission):
    def has_permission(self, request, view):
        thread_id = (
            view.kwargs.get('thread_pk')
            or view.kwargs.get('thread_id')
            or view.kwargs.get('pk')
        )

        if not thread_id:
            return True

        try:
            thread = ChatThread.objects.get(id=thread_id)
        except ChatThread.DoesNotExist:
            return False

        user = getattr(request, 'user', None)
        session_key = (
            getattr(request.session, 'session_key', None)
            or request.query_params.get('session_key')
        )

        if user and user.is_authenticated:
            if thread.client == user or thread.freelancer == user:
                return True
            
            if thread.is_guest_thread and thread.guest_session_key:
                try:
                    if GuestSession.objects.filter(
                        session_key=thread.guest_session_key, 
                        converted_to_user=user
                    ).exists():
                        return True
                except Exception:
                    pass

        if session_key:
            if str(thread.guest_session_key).strip() == str(session_key).strip():
                request.session['manual_guest_key'] = session_key
                return True

        return False


@extend_schema(responses={200: dict})
@api_view(['GET'])
@permission_classes([AllowAny])
def guest_threads(request):
    session_key = request.query_params.get('session_key')
    if not session_key:
        return Response(
            {'error': 'Session key is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    session_key = session_key.strip()

    threads = (
        ChatThread.objects.filter(guest_session_key=session_key)
        .select_related('freelancer', 'client')
        .prefetch_related('messages')
        .order_by('-updated_at')
    )

    serializer = ChatThreadSerializer(
        threads,
        many=True,
        context={'request': request}
    )
    return Response({'results': serializer.data}, status=status.HTTP_200_OK)


@extend_schema(tags=['Chat Threads'])
class ChatThreadViewSet(viewsets.ModelViewSet):
    serializer_class = ChatThreadSerializer
    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [ChatAnonRateThrottle, ChatUserRateThrottle]
    queryset = ChatThread.objects.all().select_related('freelancer', 'client')

    def get_serializer_class(self):
        if self.action == 'list':
            from .serializers import ChatThreadListSerializer
            return ChatThreadListSerializer
        return ChatThreadSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'create', 'sent_offers']:
            return [AllowAny()]
        return [permissions.IsAuthenticated()]

    def check_permissions(self, request):
        super().check_permissions(request)

        if self.action not in ['list', 'retrieve', 'create', 'sent_offers'] and not request.user.is_authenticated:
            from rest_framework.exceptions import AuthenticationFailed
            raise AuthenticationFailed('Authentication credentials were not provided or are invalid.')

    def get_queryset(self):
        user = self.request.user
        base_qs = ChatThread.objects.select_related('freelancer', 'client').order_by('-created_at')

        if user.is_authenticated:
            return base_qs.filter(Q(client=user) | Q(freelancer=user))

        session_key = (
            getattr(self.request.session, 'session_key', None)
            or self.request.query_params.get('session_key')
        )

        if session_key:
            return base_qs.filter(guest_session_key=str(session_key).strip())

        return ChatThread.objects.none()

    def retrieve(self, request, *args, **kwargs):
        thread = self.get_object()
        session_key = getattr(request.session, 'session_key', None) or request.query_params.get('session_key')

        is_participant = False
        if request.user.is_authenticated:
            if request.user == thread.freelancer or request.user == thread.client:
                is_participant = True
            elif thread.is_guest_thread and thread.guest_session_key:
                if GuestSession.objects.filter(
                    session_key=thread.guest_session_key, 
                    converted_to_user=request.user
                ).exists():
                    is_participant = True
        elif thread.guest_session_key and str(thread.guest_session_key).strip() == str(session_key).strip():
            is_participant = True

        if not is_participant:
            raise PermissionDenied({'error': 'You are not a participant in this chat thread.'})

        serializer = self.get_serializer(thread)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary='Create or get a chat thread between freelancer and client/guest',
        request={
            'application/json': {
                'type': 'object',
                'properties': {'other_user_username': {'type': 'string'}},
                'required': ['other_user_username'],
            }
        },
        responses={200: ChatThreadSerializer, 201: ChatThreadSerializer},
    )
    def create(self, request, *args, **kwargs):
        logger.info(f"Create thread request - User: {request.user}, Authenticated: {request.user.is_authenticated}, Auth header: {request.META.get('HTTP_AUTHORIZATION', 'None')[:50] if request.META.get('HTTP_AUTHORIZATION') else 'None'}")

        # Backward compatibility: some clients send freelancer_username.
        other_user_username = request.data.get('other_user_username') or request.data.get('freelancer_username')
        if not other_user_username:
            raise ValidationError({'other_user_username': 'This field is required.'})

        try:
            other_user = User.objects.get(username=other_user_username)
        except User.DoesNotExist:
            raise NotFound({'error': f'User "{other_user_username}" not found.'})

        if not (other_user.role == Role.FREELANCER or other_user.is_superuser):
            raise ValidationError({'error': 'Target user is not a freelancer.'})

        if not request.user.is_authenticated:
            if not request.session.session_key:
                request.session.save()
            django_session_key = request.session.session_key.strip()
            client_session_key = request.query_params.get('session_key') or request.data.get('session_key')
            guest_session_key = str(client_session_key).strip() if client_session_key else django_session_key

            if other_user_username == 'anonymoususer':
                raise ValidationError({'other_user_username': 'Cannot chat with an anonymous user.'})

            with transaction.atomic():
                thread, created = ChatThread.objects.get_or_create(
                    freelancer=other_user,
                    guest_session_key=guest_session_key,
                    defaults={'client': None}
                )

            serializer = self.get_serializer(thread)
            return Response(
                serializer.data,
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )

        if other_user_username == request.user.username:
            raise ValidationError({'other_user_username': 'Cannot chat with yourself.'})

        if request.user.role == other_user.role:
            role = 'Freelancers' if request.user.role == Role.FREELANCER else 'Clients'
            raise PermissionDenied({'error': f'{role} cannot chat with each other.'})

        with transaction.atomic():
            freelancer, client = other_user, request.user

            thread, created = ChatThread.objects.get_or_create(
                freelancer=freelancer,
                client=client
            )

        serializer = self.get_serializer(thread)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=False, methods=['get'], url_path='preview-guest-threads')
    def preview_guest_threads(self, request):
        guest_session_key = request.query_params.get('guest_session_key')
        if not guest_session_key:
            raise ValidationError({'guest_session_key': 'This query parameter is required.'})

        from .serializers import GuestThreadPreviewSerializer
        from .services import ChatThreadService

        threads = ChatThreadService.preview_guest_threads(guest_session_key)
        serializer = GuestThreadPreviewSerializer(threads, many=True)

        return Response({
            'session_key': guest_session_key,
            'thread_count': len(threads),
            'threads': serializer.data
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='link-guest-threads')
    def link_guest_threads(self, request):
        if request.user.role != Role.CLIENT:
            raise PermissionDenied({'error': 'Only clients can link guest threads.'})

        from .serializers import LinkGuestThreadsSerializer
        from .services import ChatThreadService

        serializer = LinkGuestThreadsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        guest_session_key = serializer.validated_data['guest_session_key']
        thread_ids = serializer.validated_data.get('thread_ids', None)

        updated = ChatThreadService.link_guest_threads_to_client(
            client=request.user,
            guest_session_key=guest_session_key,
            thread_ids=thread_ids
        )

        return Response({
            'status': f'{updated} thread(s) linked successfully',
            'linked_count': updated,
            'selective': thread_ids is not None
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='sent-offers')
    def sent_offers(self, request):
        if not request.user.is_authenticated:
            raise permissions.AuthenticationFailed("Authentication required.")

        user_threads = ChatThread.objects.filter(freelancer=request.user)

        offers = ChatMessage.objects.filter(
            thread__in=user_threads,
            is_offer=True
        ).exclude(
            sender=request.user
        ).select_related(
            'thread', 'sender', 'thread__freelancer', 'thread__client', 'created_job'
        ).prefetch_related(
            'attachments'
        ).order_by('-timestamp')

        offers_data = []
        from .serializers import ChatMessageSerializer

        for offer in offers:
            offer_dict = ChatMessageSerializer(offer, context={'request': request}).data

            if offer.sender:
                sender_name = offer.sender.username
            elif offer.thread.guest_session_key:
                sender_name = GuestNameService.get_guest_display_name(offer.thread.guest_session_key)
            else:
                sender_name = 'Unknown Client'

            offer_dict['thread_info'] = {
                'id': offer.thread.id,
                'freelancer_username': offer.thread.freelancer.username if offer.thread.freelancer else None,
                'client_username': offer.thread.client.username if offer.thread.client else None,
                'sender_username': sender_name,
                'other_party_name': sender_name,
                'guest_session_key': offer.thread.guest_session_key,
            }
            offers_data.append(offer_dict)

        return Response({
            'sent_pending_offers': offers_data,
            'count': len(offers_data)
        }, status=status.HTTP_200_OK)
    @action(detail=True, methods=['put'], url_path='mark-as-read')
    def mark_as_read(self, request, pk=None, **kwargs): # Added **kwargs to catch thread_pk
        thread = self.get_object()
        
        # Manually verify permissions since this ViewSet lacks the helper method
        session_key = request.query_params.get('session_key') or getattr(request.session, 'session_key', None)
        is_participant = False

        if request.user.is_authenticated:
            if thread.client == request.user or thread.freelancer == request.user:
                is_participant = True
        elif thread.guest_session_key and session_key:
            if str(thread.guest_session_key).strip() == str(session_key).strip():
                is_participant = True

        if not is_participant:
            raise PermissionDenied({'error': 'You are not a participant in this chat thread.'})

        # Process marking messages as read
        if request.user.is_authenticated:
            messages_to_read = ChatMessage.objects.filter(thread=thread).exclude(sender=request.user)
            MessageReadStatus.objects.bulk_create(
                [MessageReadStatus(message=m, user=request.user) for m in messages_to_read],
                ignore_conflicts=True
            )
        elif session_key:
            # For guests, mark messages from the freelancer as read
            messages_to_read = ChatMessage.objects.filter(thread=thread, sender=thread.freelancer)
            MessageReadStatus.objects.bulk_create(
                [MessageReadStatus(message=m, guest_session_key=session_key) for m in messages_to_read],
                ignore_conflicts=True
            )

        return Response({'status': 'messages marked as read'}, status=status.HTTP_200_OK)

class GuestThreadCreateView(APIView, SessionKeyMixin):
    permission_classes = [AllowAny]
    serializer_class = EmptySerializer

    def post(self, request):
        freelancer_username = request.data.get('freelancer_username')
        client_session_key = request.data.get('session_key')

        if not request.session.session_key:
            request.session.save()
        django_session_key = request.session.session_key.strip()

        definitive_guest_key = client_session_key if client_session_key else django_session_key

        if not freelancer_username:
            return Response(
                {'error': 'Freelancer username is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            freelancer_user = User.objects.get(username=freelancer_username)
        except User.DoesNotExist:
            raise NotFound({'error': f'User "{freelancer_username}" not found.'})

        if not (freelancer_user.role == Role.FREELANCER or freelancer_user.is_superuser):
            raise ValidationError({'error': 'Target user is not a freelancer.'})

        if request.user.is_authenticated and request.user.role == Role.CLIENT:
            thread, created = ChatThread.objects.get_or_create(
                freelancer=freelancer_user,
                client=request.user,
            )
        else:
            thread = ChatThread.objects.filter(
                freelancer=freelancer_user,
                guest_session_key=definitive_guest_key,
            ).first()

            if not thread:
                thread = ChatThread.objects.create(
                    freelancer=freelancer_user,
                    guest_session_key=definitive_guest_key,
                    client=None,
                )
                created = True
            else:
                created = False
                thread.save(update_fields=['updated_at'])

        serializer = ChatThreadSerializer(thread, context={'request': request})
        response_data = serializer.data
        response_data['guest_session_key'] = definitive_guest_key

        return Response(
            response_data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


@extend_schema(tags=['Chat Messages'])
class ChatMessageViewSet(viewsets.ModelViewSet, SessionKeyMixin):
    serializer_class = ChatMessageSerializer
    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [ChatAnonRateThrottle, ChatUserRateThrottle]
    lookup_field = 'pk'
    queryset = ChatMessage.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ChatMessage.objects.none()
        thread_id = self.kwargs.get('thread_pk')
        thread = get_thread_or_404(thread_id)
        return thread.messages.select_related('sender').prefetch_related('attachments').all()

    def _check_permission(self, request, thread):
        session_key = self.get_session_key(request)

        if request.user.is_authenticated:
            if thread.client == request.user or thread.freelancer == request.user:
                return True, None
            
            if thread.is_guest_thread and thread.guest_session_key:
                try:
                    if GuestSession.objects.filter(
                        session_key=thread.guest_session_key, 
                        converted_to_user=request.user
                    ).exists():
                        return True, None
                except Exception:
                    pass

        if thread.guest_session_key and session_key and str(session_key).strip() == str(thread.guest_session_key).strip():
            return True, session_key

        return False, None

    def list(self, request, *args, **kwargs):
        thread_id = self.kwargs.get('thread_pk')
        thread = get_thread_or_404(thread_id)

        allowed, session_key = self._check_permission(request, thread)
        if not allowed:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)

        queryset = self.get_queryset()

        if request.user.is_authenticated:
            unread_messages = queryset.exclude(sender=request.user).exclude(
                read_by__user=request.user
            )
            MessageReadStatus.objects.bulk_create(
                [MessageReadStatus(message=m, user=request.user) for m in unread_messages],
                ignore_conflicts=True,
            )
        elif session_key:
            unread_messages = queryset.filter(sender=thread.freelancer).exclude(
                read_by__guest_session_key=session_key
            )
            MessageReadStatus.objects.bulk_create(
                [MessageReadStatus(message=m, guest_session_key=session_key) for m in unread_messages],
                ignore_conflicts=True,
            )

        serializer = self.get_serializer(queryset, many=True)
        return Response({'messages': serializer.data}, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        thread_id = self.kwargs.get('thread_pk')
        
        with transaction.atomic():
            # 1. LOCK the thread row to prevent simultaneous message/user creation issues
            try:
                # We use of=('self',) to avoid the 500 error with Outer Joins on NULL clients
                thread = ChatThread.objects.select_for_update(of=('self',)).get(pk=thread_id)
            except ChatThread.DoesNotExist:
                raise NotFound({'error': 'Chat thread does not exist.'})

            # 2. Check permissions
            allowed, session_key = self._check_permission(request, thread)
            if not allowed:
                return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
    
            sender = request.user if request.user.is_authenticated else None
            
            # 3. Validate the message data
            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            guest_session = None
            
            # 4. Handle Guest Identity (Inside the transaction)
            if not sender and session_key:
                try:
                    # Link to GuestSession model for tracking
                    guest_session, _ = GuestSession.get_or_create_session(session_key)
                    
                    # Create or get shadow client (Actual User object) for the guest
                    shadow_client = User.objects.create_shadow_client(session_key)

                    # Link thread to shadow client if it's the first time
                    if thread.is_guest_thread and not thread.client:
                        thread.client = shadow_client
                        thread.save(update_fields=['client'])
                        logger.info(f"Linked thread {thread.id} to shadow client {shadow_client.username}")
                except Exception as e:
                    logger.warning(f"Guest identity linking failed: {e}")

            # 5. Save the message
            message = serializer.save(
                thread=thread,
                sender=sender,
                guest_session=guest_session,
            )

            return Response(self.get_serializer(message).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='update-offer-status')
    @transaction.atomic
    def update_offer_status(self, request, *args, **kwargs):
        thread_id = self.kwargs.get('thread_pk')
        thread = get_thread_or_404(thread_id)

        allowed, session_key = self._check_permission(request, thread)
        if not allowed:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            message = self.get_object() 
        except ChatMessage.DoesNotExist:
            raise NotFound({'error': 'Message not found'})

        if not message.is_offer:
            raise ValidationError({'error': 'This message is not an offer'})

        if message.offer_status != 'pending':
            raise ValidationError({'error': f'This offer has already been {message.offer_status}'})

        user = request.user if request.user.is_authenticated else None

        is_freelancer_accepting = False
        client_user = None

        if message.sender == thread.freelancer:
            is_thread_client = bool(user and user == thread.client)
            is_guest_client = bool(
                session_key
                and thread.guest_session_key
                and str(session_key).strip() == str(thread.guest_session_key).strip()
            )

            if not is_thread_client and not is_guest_client:
                raise PermissionDenied({'error': 'Only the client can respond to this offer'})
            client_user = thread.client if thread.client else None
        else:
            if not user or user != thread.freelancer:
                raise PermissionDenied({'error': 'Only the freelancer can respond to this offer'})
            is_freelancer_accepting = True
            client_user = thread.client if thread.client else message.sender

        offer_status = request.data.get('offer_status')
        if offer_status:
            normalized_status = str(offer_status).strip().lower()
            if normalized_status in ('accept', 'accepted'):
                offer_status = 'accepted'
            elif normalized_status in ('reject', 'rejected'):
                offer_status = 'rejected'
            else:
                offer_status = normalized_status
        if not offer_status:
            action = (request.data.get('action') or '').strip().lower()
            if action in ('accept', 'accepted'):
                offer_status = 'accepted'
            elif action in ('reject', 'rejected'):
                offer_status = 'rejected'
        if offer_status not in ['accepted', 'rejected']:
            logger.warning(f"Invalid offer status payload for message {message.id}: {request.data}")
            raise ValidationError({'offer_status': 'Must be either "accepted" or "rejected"'})


        message.offer_status = offer_status
        message.save(update_fields=['offer_status', 'updated_at'])

        if offer_status == 'accepted':
            # Ensure we have a client account for payment and job ownership.
            if not client_user:
                if thread.is_guest_thread and thread.guest_session_key:
                    shadow_client = User.objects.create_shadow_client(thread.guest_session_key)
                    thread.client = shadow_client
                    thread.save(update_fields=['client'])
                    client_user = shadow_client
                    logger.info(f"Created shadow client {shadow_client.username} during offer acceptance.")
                else:
                    raise ValidationError({'error': 'Cannot create job without a client account.'})

            # Client account finalization now happens after successful payment.
            # `client_email` should be supplied during payment initialization.
            account_created = False
            account_email_sent = False

            job = Job.objects.create(
                title=message.offer_title,
                description=message.offer_description or message.offer_title,
                client=client_user,
                freelancer=thread.freelancer,
                price=message.offer_price,
                total_amount=message.offer_price,
                delivery_time_days=message.offer_timeline,
                allowed_reviews=message.offer_revisions or 2,
                status=JobStatus.PROVISIONAL,
            )

            message.created_job = job
            message.save(update_fields=['created_job', 'updated_at'])

            from notifications.models import Notification
            Notification.objects.create(
                recipient=client_user,
                notification_type='JOB_CREATED',
                title='Payment Required for New Job',
                message=f'Offer "{job.title}" was accepted. Please proceed with payment to start the job.',
                link=f'/job/{job.id}',
                metadata={
                    'job_id': str(job.id),
                    'offer_id': str(message.id),
                    'amount': str(job.total_amount),
                    'freelancer': thread.freelancer.username
                }
            )

            Notification.objects.create(
                recipient=thread.freelancer,
                notification_type='OFFER_ACCEPTED',
                title='Offer Accepted',
                message=f'Your offer for "{job.title}" was accepted. Waiting for client payment to begin work.',
                link=f'/job/{job.id}',
                metadata={
                    'job_id': str(job.id),
                    'offer_id': str(message.id),
                    'client': client_user.username
                }
            )

            response_data = self.get_serializer(message).data
            response_data['job_created'] = {
                'id': str(job.id),
                'title': job.title,
                'status': job.status,
                'status_display': job.get_status_display(),
                'amount': str(job.total_amount),
                'allowed_reviews': job.allowed_reviews,
                'payment_required': True,
                'message': 'Job created successfully! Client must now complete payment to start work.'
            }
            response_data['account_created'] = account_created
            response_data['account_email_sent'] = account_email_sent

            return Response(response_data, status=status.HTTP_200_OK)

        return Response(self.get_serializer(message).data, status=status.HTTP_200_OK)


class UploadAPIView(APIView, SessionKeyMixin):
    parser_classes = [MultiPartParser, FormParser]   # ← ADD THIS LINE
    permission_classes = [AllowAny]
    serializer_class = ChatAttachmentUploadSerializer

    @transaction.atomic
    def post(self, request):
        serializer = ChatAttachmentUploadSerializer(data=request.data)
        if serializer.is_valid():
            file = serializer.validated_data['file']

            file_path = default_storage.save(f'chat_attachments/{file.name}', file)
            file_url = default_storage.url(file_path)

            attachment = ChatAttachment.objects.create(
                file_url=file_url,
                name=file.name,
                mime_type=file.content_type,
                size=file.size,
                uploaded_by=request.user if request.user.is_authenticated else None,
            )

            return Response(
                ChatAttachmentSerializer(attachment).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UnreadCountView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request):
        user = request.user
        unread_count = ChatMessageService.get_unread_count_for_user(user)
        return Response({'unread_count': unread_count}, status=status.HTTP_200_OK)


class ThreadUnreadsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request):
        user = request.user
        thread_unreads = ChatMessageService.get_thread_unreads_for_user(user)
        return Response({'thread_unreads': thread_unreads}, status=status.HTTP_200_OK)


class PendingOffersView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request):
        user = request.user

        threads = ChatThread.objects.filter(
            Q(freelancer=user) | Q(client=user)
        ).select_related('freelancer', 'client')

        thread_ids = [thread.id for thread in threads]

        pending_offers = ChatMessage.objects.filter(
            thread_id__in=thread_ids,
            is_offer=True,
            offer_status='pending'
        ).exclude(sender=user).select_related('thread', 'sender', 'thread__freelancer', 'thread__client')

        from .serializers import ChatMessageSerializer

        offers_data = []
        for offer in pending_offers:
            offer_dict = ChatMessageSerializer(offer, context={'request': request}).data
            offer_dict['thread_info'] = {
                'id': offer.thread.id,
                'freelancer_username': offer.thread.freelancer.username if offer.thread.freelancer else None,
                'client_username': offer.thread.client.username if offer.thread.client else None,
                'sender_username': offer.sender.username if offer.sender else 'Guest',
            }
            offers_data.append(offer_dict)

        return Response({
            'pending_offers': offers_data,
            'count': len(offers_data)
        }, status=status.HTTP_200_OK)

