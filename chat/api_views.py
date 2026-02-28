"""
Production-grade API views for logged-in user messaging.
Provides comprehensive endpoints for viewing, sending, and managing messages.
"""
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError

from django.db import transaction
from django.db.models import Q, Count, Exists, OuterRef, Prefetch
from django.utils import timezone
from django.contrib.auth import get_user_model

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from .models import ChatThread, ChatMessage, MessageReadStatus, ChatAttachment
from .serializers import (
    ChatThreadSerializer,
    ChatMessageSerializer,
    ChatThreadListSerializer,
)
from .services import ChatMessageService, ChatThreadService
from orders.models import Job, JobStatus
from user_module.models import Role

import logging

User = get_user_model()
logger = logging.getLogger(__name__)


class UserMessagingViewSet(viewsets.ViewSet):
    """
    Comprehensive messaging API for logged-in users.
    Handles thread listing, message viewing, sending, and offer management.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="List all chat threads for current user",
        description="Returns all chat threads where the user is a participant (freelancer or client)",
        responses={200: ChatThreadListSerializer(many=True)}
    )
    def list(self, request):
        """List all threads for the authenticated user"""
        user = request.user

        # Get threads where user is participant
        threads = ChatThread.objects.filter(
            Q(freelancer=user) | Q(client=user)
        ).select_related(
            'freelancer', 'client'
        ).prefetch_related(
            Prefetch(
                'messages',
                queryset=ChatMessage.objects.select_related('sender', 'guest_session').order_by('-timestamp')[:1],
                to_attr='latest_message_list'
            )
        ).annotate(
            unread_count=Count(
                'messages',
                filter=Q(messages__read_by__user__isnull=True) & ~Q(messages__sender=user)
            )
        ).order_by('-updated_at')

        serializer = ChatThreadListSerializer(
            threads,
            many=True,
            context={'request': request}
        )

        logger.info(f"User {user.username} retrieved {threads.count()} threads")
        return Response({
            'count': threads.count(),
            'threads': serializer.data
        })

    @extend_schema(
        summary="Get thread details with messages",
        description="Retrieve a specific thread with all messages. Marks messages as read.",
        responses={200: ChatThreadSerializer}
    )
    def retrieve(self, request, pk=None):
        """Get thread details with messages"""
        user = request.user

        try:
            thread = ChatThread.objects.select_related(
                'freelancer', 'client'
            ).prefetch_related(
                Prefetch(
                    'messages',
                    queryset=ChatMessage.objects.select_related(
                        'sender', 'guest_session'
                    ).prefetch_related('attachments').order_by('timestamp')
                )
            ).get(pk=pk)
        except ChatThread.DoesNotExist:
            raise NotFound({'error': 'Thread not found'})

        # Check permission
        if thread.freelancer != user and thread.client != user:
            raise PermissionDenied({'error': 'You are not a participant in this thread'})

        # Mark messages as read
        unread_messages = thread.messages.exclude(sender=user).exclude(read_by__user=user)
        MessageReadStatus.objects.bulk_create(
            [MessageReadStatus(message=msg, user=user) for msg in unread_messages],
            ignore_conflicts=True
        )

        serializer = ChatThreadSerializer(thread, context={'request': request})

        logger.info(f"User {user.username} viewed thread {pk}")
        return Response(serializer.data)

    @extend_schema(
        summary="Send a message in a thread",
        description="Send a new message or offer in an existing thread",
        request=ChatMessageSerializer,
        responses={201: ChatMessageSerializer}
    )
    @action(detail=True, methods=['post'], url_path='send-message')
    def send_message(self, request, pk=None):
        """Send a message in a thread"""
        user = request.user

        try:
            thread = ChatThread.objects.get(pk=pk)
        except ChatThread.DoesNotExist:
            raise NotFound({'error': 'Thread not found'})

        # Check permission
        if thread.freelancer != user and thread.client != user:
            raise PermissionDenied({'error': 'You are not a participant in this thread'})

        # Validate data
        serializer = ChatMessageSerializer(data=request.data)
        if not serializer.is_valid():
            logger.error(f"Message validation failed: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Create message
        with transaction.atomic():
            message = serializer.save(
                thread=thread,
                sender=user,
                guest_session=None  # Logged-in users don't have guest sessions
            )

            thread.last_message = message.message or f"Offer: {message.offer_title}"
            thread.updated_at = timezone.now()
            thread.save(update_fields=['last_message', 'updated_at'])

        logger.info(
            f"User {user.username} sent {'offer' if message.is_offer else 'message'} "
            f"in thread {pk}"
        )

        return Response(
            ChatMessageSerializer(message, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )

    @extend_schema(
        summary="Respond to an offer (accept/reject)",
        description="Accept or reject a pending offer. Accepting creates a Job.",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['accept', 'reject'],
                        'description': 'Action to take on the offer'
                    }
                },
                'required': ['action']
            }
        },
        responses={
            200: ChatMessageSerializer,
            400: OpenApiResponse(description='Invalid action or offer state'),
            403: OpenApiResponse(description='Not authorized to respond to this offer'),
            404: OpenApiResponse(description='Message or offer not found')
        }
    )
    @action(detail=True, methods=['post'], url_path='messages/(?P<message_id>[^/.]+)/respond')
    def respond_to_offer(self, request, pk=None, message_id=None):
        """Respond to an offer (accept/reject)"""
        user = request.user
        action_type = request.data.get('action')

        if action_type not in ['accept', 'reject']:
            raise ValidationError({'action': 'Must be either "accept" or "reject"'})

        try:
            thread = ChatThread.objects.select_related('freelancer', 'client').get(pk=pk)
        except ChatThread.DoesNotExist:
            raise NotFound({'error': 'Thread not found'})

        # Check permission
        if thread.freelancer != user and thread.client != user:
            raise PermissionDenied({'error': 'You are not a participant in this thread'})

        try:
            message = ChatMessage.objects.select_related('sender', 'thread').get(
                pk=message_id,
                thread=thread
            )
        except ChatMessage.DoesNotExist:
            raise NotFound({'error': 'Message not found'})

        # Validate it's an offer
        if not message.is_offer:
            raise ValidationError({'error': 'This message is not an offer'})

        # Check offer status
        if message.offer_status != 'pending':
            raise ValidationError({
                'error': f'This offer has already been {message.offer_status}'
            })

        # Check user is the recipient
        if message.sender == user:
            raise PermissionDenied({'error': 'You cannot respond to your own offer'})

        # Determine who sent the offer and who should respond
        if message.sender == thread.freelancer:
            # Freelancer sent offer, client should respond
            if user != thread.client and not thread.is_guest_thread:
                raise PermissionDenied({'error': 'Only the client can respond to this offer'})
            recipient_user = thread.client
        else:
            # Client sent offer, freelancer should respond
            if user != thread.freelancer:
                raise PermissionDenied({'error': 'Only the freelancer can respond to this offer'})
            recipient_user = thread.freelancer

        # Process the response
        with transaction.atomic():
            new_status = 'accepted' if action_type == 'accept' else 'rejected'
            message.offer_status = new_status
            message.save(update_fields=['offer_status', 'updated_at'])

            job_data = None

            # If accepted and freelancer is accepting, create job
            if action_type == 'accept' and user == thread.freelancer:
                # Ensure we have a registered client
                if not thread.client:
                    raise ValidationError({
                        'error': 'Cannot create job without a registered client. '
                                'Guest must sign up first.'
                    })

                # Create job
                job = Job.objects.create(
                    title=message.offer_title,
                    description=message.offer_description or message.offer_title,
                    client=thread.client,
                    freelancer=thread.freelancer,
                    price=message.offer_price,
                    total_amount=message.offer_price,
                    delivery_time_days=message.offer_timeline,
                    allowed_reviews=message.offer_revisions or 2,
                    status=JobStatus.PROVISIONAL,
                )

                job_data = {
                    'id': str(job.id),
                    'title': job.title,
                    'price': str(job.price),
                    'status': job.status,
                    'delivery_days': job.delivery_time_days,
                    'allowed_reviews': job.allowed_reviews,
                }

                logger.info(
                    f"Job {job.id} created from offer {message.id} "
                    f"(freelancer: {thread.freelancer.username}, client: {thread.client.username})"
                )

        logger.info(
            f"User {user.username} {action_type}ed offer {message.id} in thread {pk}"
        )

        response_data = ChatMessageSerializer(message, context={'request': request}).data
        if job_data:
            response_data['job_created'] = job_data

        return Response(response_data)

    @extend_schema(
        summary="Get unread message count",
        description="Get total count of unread messages for the current user",
        responses={200: {'type': 'object', 'properties': {'unread_count': {'type': 'integer'}}}}
    )
    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        """Get unread message count for user"""
        user = request.user

        unread_count = ChatMessage.objects.filter(
            Q(thread__freelancer=user) | Q(thread__client=user)
        ).exclude(
            sender=user
        ).exclude(
            read_by__user=user
        ).count()

        return Response({'unread_count': unread_count})

    @extend_schema(
        summary="Get pending offers",
        description="Get all pending offers where user needs to respond",
        responses={200: {'type': 'object'}}
    )
    @action(detail=False, methods=['get'], url_path='pending-offers')
    def pending_offers(self, request):
        """Get pending offers for user to respond to"""
        user = request.user

        # Get threads where user is participant
        thread_ids = ChatThread.objects.filter(
            Q(freelancer=user) | Q(client=user)
        ).values_list('id', flat=True)

        # Get pending offers in those threads where user is NOT the sender
        pending_offers = ChatMessage.objects.filter(
            thread_id__in=thread_ids,
            is_offer=True,
            offer_status='pending'
        ).exclude(
            sender=user
        ).select_related(
            'thread', 'sender', 'thread__freelancer', 'thread__client'
        ).order_by('-timestamp')

        offers_data = []
        for offer in pending_offers:
            offer_dict = ChatMessageSerializer(offer, context={'request': request}).data
            offer_dict['thread_info'] = {
                'id': offer.thread.id,
                'freelancer_username': offer.thread.freelancer.username if offer.thread.freelancer else None,
                'client_username': offer.thread.client.username if offer.thread.client else None,
            }
            offer_dict['sender_username'] = offer.sender.username if offer.sender else 'Guest'
            offers_data.append(offer_dict)

        return Response({
            'pending_offers': offers_data,
            'count': len(offers_data)
        })

    @extend_schema(
        summary="Mark thread messages as read",
        description="Mark all messages in a thread as read by the current user",
        responses={200: {'type': 'object'}}
    )
    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_as_read(self, request, pk=None):
        """Mark all messages in thread as read"""
        user = request.user

        try:
            thread = ChatThread.objects.get(pk=pk)
        except ChatThread.DoesNotExist:
            raise NotFound({'error': 'Thread not found'})

        # Check permission
        if thread.freelancer != user and thread.client != user:
            raise PermissionDenied({'error': 'You are not a participant in this thread'})

        # Mark as read
        messages_to_read = thread.messages.exclude(sender=user).exclude(read_by__user=user)
        MessageReadStatus.objects.bulk_create(
            [MessageReadStatus(message=m, user=user) for m in messages_to_read],
            ignore_conflicts=True
        )

        marked_count = messages_to_read.count()
        logger.info(f"User {user.username} marked {marked_count} messages as read in thread {pk}")

        return Response({
            'status': f'{marked_count} message(s) marked as read',
            'marked_count': marked_count
        })


@extend_schema(
    summary="Create or get thread with another user",
    description="Create a new chat thread or retrieve existing one with specified user",
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'other_user_username': {'type': 'string', 'description': 'Username of user to chat with'}
            },
            'required': ['other_user_username']
        }
    },
    responses={
        200: ChatThreadSerializer,
        201: ChatThreadSerializer
    }
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_or_get_thread(request):
    """Create or get a thread with another user"""
    user = request.user
    other_username = request.data.get('other_user_username')

    if not other_username:
        raise ValidationError({'other_user_username': 'This field is required'})

    try:
        other_user = User.objects.get(username=other_username)
    except User.DoesNotExist:
        raise NotFound({'error': f'User "{other_username}" not found'})

    # Validate roles
    if user.username == other_username:
        raise ValidationError({'error': 'Cannot create thread with yourself'})

    if user.role == other_user.role:
        raise ValidationError({
            'error': f'{user.role.title()}s cannot chat with each other'
        })

    # Determine freelancer and client
    if user.role == Role.FREELANCER:
        freelancer, client = user, other_user
    else:
        freelancer, client = other_user, user

    # Get or create thread
    with transaction.atomic():
        thread, created = ChatThread.objects.get_or_create(
            freelancer=freelancer,
            client=client,
            guest_session_key__isnull=True
        )

        if not created:
            thread.updated_at = timezone.now()
            thread.save(update_fields=['updated_at'])

    logger.info(
        f"Thread {'created' if created else 'retrieved'}: "
        f"{thread.id} between {user.username} and {other_username}"
    )

    serializer = ChatThreadSerializer(thread, context={'request': request})
    return Response(
        serializer.data,
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
