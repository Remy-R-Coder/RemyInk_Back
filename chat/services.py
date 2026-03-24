import logging
from typing import Optional, Tuple, List
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.core.cache import cache
from django.db.models import Q, Prefetch

from .models import ChatThread, ChatMessage, MessageReadStatus, ChatAttachment
from .constants import OfferStatus, GUEST_DISPLAY_NAME_PREFIX, GUEST_DISPLAY_COUNTER_KEY
from user_module.models import Role

logger = logging.getLogger(__name__)
User = get_user_model()


class ChatThreadService:
    
    @staticmethod
    def get_thread_by_id(thread_id: int) -> Optional[ChatThread]:
        try:
            return ChatThread.objects.select_related(
                'freelancer', 'client'
            ).prefetch_related(
                'messages__sender',
                'messages__attachments'
            ).get(pk=thread_id)
        except ChatThread.DoesNotExist:
            logger.warning(f"Thread {thread_id} not found")
            return None
    
    @staticmethod
    def is_user_participant(
        thread: ChatThread,
        user: Optional[User],
        session_key: Optional[str]
    ) -> bool:
        if user and user.is_authenticated:
            return thread.freelancer_id == user.pk or thread.client_id == user.pk
        
        if session_key and thread.guest_session_key:
            return str(thread.guest_session_key).strip() == str(session_key).strip()
        
        return False
    
    @staticmethod
    @transaction.atomic
    def get_or_create_authenticated_thread(
        user: User,
        freelancer_id: str
    ) -> Tuple[Optional[ChatThread], bool]:
        try:
            freelancer = User.objects.select_for_update().get(pk=freelancer_id)
        except User.DoesNotExist:
            logger.warning(f"Freelancer {freelancer_id} not found")
            return None, False
        
        if user.role == Role.FREELANCER:
            thread_freelancer, client = user, freelancer
        else:
            thread_freelancer, client = freelancer, user
        
        thread, created = ChatThread.objects.get_or_create(
            freelancer=thread_freelancer,
            client=client,
            guest_session_key__isnull=True,
            defaults={'updated_at': timezone.now()}
        )
        
        if not created:
            thread.updated_at = timezone.now()
            thread.save(update_fields=['updated_at'])
        
        logger.info(
            f"Thread {'created' if created else 'retrieved'}: "
            f"ID={thread.id}, Freelancer={thread_freelancer.username}"
        )
        
        return thread, created
    
    @staticmethod
    @transaction.atomic
    def get_or_create_guest_thread(
        session_key: str,
        freelancer_id: str
    ) -> Tuple[Optional[ChatThread], bool]:
        try:
            freelancer = User.objects.select_for_update().get(pk=freelancer_id)
        except User.DoesNotExist:
            logger.warning(f"Freelancer {freelancer_id} not found")
            return None, False
        
        thread, created = ChatThread.objects.get_or_create(
            freelancer=freelancer,
            guest_session_key=session_key,
            client__isnull=True,
            defaults={'updated_at': timezone.now()}
        )
        
        if not created:
            thread.updated_at = timezone.now()
            thread.save(update_fields=['updated_at'])
        
        logger.info(
            f"Guest thread {'created' if created else 'retrieved'}: "
            f"ID={thread.id}, Session={session_key[:8]}..."
        )
        
        return thread, created
    
    @staticmethod
    @transaction.atomic
    def link_guest_threads_to_client(
        client: User,
        guest_session_key: str,
        thread_ids: Optional[List[int]] = None
    ) -> int:
        """
        Link guest threads to a registered client account.

        Args:
            client: The user to link threads to
            guest_session_key: The session key identifying the guest
            thread_ids: Optional list of specific thread IDs to link.
                       If None, all threads for this session will be linked.

        Returns:
            Number of threads linked
        """
        query = ChatThread.objects.filter(
            guest_session_key=guest_session_key,
            client__isnull=True
        )

        # If specific thread IDs provided, filter to only those
        if thread_ids is not None:
            query = query.filter(id__in=thread_ids)

        updated_count = query.update(
            client=client,
            updated_at=timezone.now()
        )

        logger.info(
            f"Linked {updated_count} guest threads to client {client.username} "
            f"(session: {guest_session_key[:8]}..., selective: {thread_ids is not None})"
        )

        # Mark the guest session as converted
        GuestNameService.mark_session_converted(guest_session_key, client)

        return updated_count

    @staticmethod
    def preview_guest_threads(guest_session_key: str) -> List[ChatThread]:
        """
        Preview guest threads before linking to a client account.
        Returns list of threads with message counts and metadata.
        """
        threads = ChatThread.objects.filter(
            guest_session_key=guest_session_key,
            client__isnull=True
        ).select_related(
            'freelancer'
        ).prefetch_related(
            'messages'
        ).order_by('-updated_at')

        logger.info(f"Previewing {threads.count()} threads for session {guest_session_key[:8]}...")
        return list(threads)
    
    @staticmethod
    def get_user_threads(user: User) -> List[ChatThread]:
        base_query = ChatThread.objects.select_related(
            'freelancer', 'client'
        ).prefetch_related(
            'messages__sender'
        )
        
        if user.role == Role.FREELANCER or user.is_superuser:
            return base_query.filter(freelancer=user).order_by('-updated_at')
        
        if user.role == Role.CLIENT:
            return base_query.filter(
                Q(client=user) | Q(guest_session_key__isnull=False)
            ).order_by('-updated_at')
        
        return ChatThread.objects.none()
    
    @staticmethod
    def get_guest_threads(session_key: str) -> List[ChatThread]:
        return ChatThread.objects.filter(
            guest_session_key=session_key
        ).select_related(
            'freelancer', 
            'client'
        ).prefetch_related(
            'messages__sender'
        ).order_by('-updated_at')


class ChatMessageService:
    
    @staticmethod
    @transaction.atomic
    def create_message(
        thread: ChatThread,
        sender: Optional[User],
        message_text: str,
        is_offer: bool = False,
        offer_data: Optional[dict] = None,
        guest_session_key: Optional[str] = None
    ) -> ChatMessage:
        """
        Create a new chat message.

        Args:
            thread: The thread this message belongs to
            sender: The user sending the message (None for guests)
            message_text: The message content
            is_offer: Whether this is an offer message
            offer_data: Offer details if is_offer=True
            guest_session_key: Session key if message is from a guest

        Returns:
            The created ChatMessage instance
        """
        # Get or create guest session if this is a guest message
        guest_session = None
        if not sender and guest_session_key:
            try:
                from user_module.models import GuestSession
                guest_session, _ = GuestSession.get_or_create_session(guest_session_key)
            except Exception as e:
                logger.warning(f"Could not link guest session to message: {e}")

        message = ChatMessage.objects.create(
            thread=thread,
            sender=sender,
            guest_session=guest_session,
            message=message_text,
            is_offer=is_offer,
            offer_title=offer_data.get('title') if offer_data else None,
            offer_price=offer_data.get('price') if offer_data else None,
            offer_timeline=offer_data.get('timeline') if offer_data else None,
            offer_revisions=offer_data.get('revisions') if offer_data else None,
            offer_description=offer_data.get('description') if offer_data else None,
            offer_status=offer_data.get('status', OfferStatus.PENDING) if offer_data else OfferStatus.PENDING,
        )

        thread.last_message = message_text
        thread.updated_at = timezone.now()
        thread.save(update_fields=['last_message', 'updated_at'])

        sender_info = sender.username if sender else (guest_session.display_name if guest_session else "Unknown")
        logger.info(
            f"Message created: ID={message.id}, Thread={thread.id}, "
            f"Sender={sender_info}, Type={'Offer' if is_offer else 'Chat'}"
        )

        return message
    
    @staticmethod
    def get_thread_messages(
        thread: ChatThread,
        limit: int = 100
    ) -> List[ChatMessage]:
        return list(
            ChatMessage.objects.filter(thread=thread)
            .select_related('sender', 'thread')
            .prefetch_related('attachments')
            .order_by('-timestamp')[:limit][::-1]
        )
    
    @staticmethod
    @transaction.atomic
    def update_offer_status(
        offer: ChatMessage,
        new_status: str,
        user: Optional[User],
        session_key: Optional[str]
    ) -> bool:
        if not offer.is_offer:
            logger.warning(f"Message {offer.id} is not an offer")
            return False
        
        if user and user.is_authenticated:
            is_receiver = offer.sender_id != user.pk
        else:
            is_receiver = (
                offer.thread.guest_session_key == session_key and
                offer.sender_id != offer.thread.freelancer_id
            )
        
        if not is_receiver:
            logger.warning(
                f"Unauthorized offer update attempt: Message={offer.id}, User={user}"
            )
            return False
        
        if new_status not in OfferStatus.ALL:
            logger.warning(f"Invalid offer status: {new_status}")
            return False
        
        offer.offer_status = new_status
        offer.save(update_fields=['offer_status', 'updated_at'])
        
        logger.info(f"Offer {offer.id} status updated to {new_status}")
        return True
    
    @staticmethod
    @transaction.atomic
    def mark_messages_as_read(
        messages: List[ChatMessage],
        user: Optional[User],
        session_key: Optional[str]
    ) -> int:
        if user and user.is_authenticated:
            unread = [msg for msg in messages if msg.sender != user]
            existing_reads = MessageReadStatus.objects.filter(
                message__in=unread,
                user=user
            ).values_list('message_id', flat=True)
            
            to_create = [
                MessageReadStatus(message=msg, user=user)
                for msg in unread
                if msg.id not in existing_reads
            ]
        elif session_key and messages:
            thread = messages[0].thread
            unread = [msg for msg in messages if msg.sender == thread.freelancer]
            existing_reads = MessageReadStatus.objects.filter(
                message__in=unread,
                guest_session_key=session_key
            ).values_list('message_id', flat=True)
            
            to_create = [
                MessageReadStatus(message=msg, guest_session_key=session_key)
                for msg in unread
                if msg.id not in existing_reads
            ]
        else:
            return 0
        
        if to_create:
            MessageReadStatus.objects.bulk_create(to_create, ignore_conflicts=True)
            logger.info(f"Marked {len(to_create)} messages as read")
            return len(to_create)
        
        return 0
    
    @staticmethod
    def get_unread_count_for_user(user: User) -> int:
        return ChatMessage.objects.filter(
            thread__in=ChatThread.objects.filter(
                Q(freelancer=user) | Q(client=user)
            )
        ).exclude(
            sender=user
        ).exclude(
            read_by__user=user
        ).count()
    
    @staticmethod
    def get_thread_unreads_for_user(user: User) -> dict:
        threads = ChatThread.objects.filter(
            Q(freelancer=user) | Q(client=user)
        ).prefetch_related('messages', 'messages__read_by')
        
        thread_unreads = {}
        for thread in threads:
            unread = thread.messages.exclude(
                sender=user
            ).exclude(
                read_by__user=user
            ).count()
            thread_unreads[str(thread.id)] = unread
        
        return thread_unreads


class AttachmentService:
    
    @staticmethod
    @transaction.atomic
    def create_attachment(
        file_url: str,
        name: str,
        mime_type: Optional[str],
        size: Optional[int],
        uploaded_by: Optional[User],
        message: Optional[ChatMessage] = None
    ) -> ChatAttachment:
        attachment = ChatAttachment.objects.create(
            file_url=file_url,
            name=name,
            mime_type=mime_type,
            size=size,
            uploaded_by=uploaded_by,
            message=message
        )
        
        logger.info(
            f"Attachment created: ID={attachment.id}, Name={name}, "
            f"Message={message.id if message else 'None'}"
        )
        
        return attachment
    
    @staticmethod
    @transaction.atomic
    def link_attachments_to_message(
        attachment_ids: List[int],
        message: ChatMessage
    ) -> int:
        updated = ChatAttachment.objects.filter(
            id__in=attachment_ids,
            message__isnull=True
        ).update(message=message)
        
        if updated > 0:
            logger.info(f"Linked {updated} attachments to message {message.id}")
        
        return updated
        
class GuestNameService:
    """
    Service for managing guest display names and session lifecycle.
    Points to user_module.models.GuestSession for data persistence.
    """

    @staticmethod
    def get_guest_display_name(session_key: str) -> str:
        if not session_key:
            return "Guest"

        try:
            # Consistently import from user_module
            from user_module.models import GuestSession
            session, _ = GuestSession.objects.get_or_create(session_key=session_key)
            return getattr(session, 'display_name', "Guest")
        except Exception as e:
            logger.error(f"Error getting guest display name: {e}")
            
            # Cache fallback logic
            cache_key = f"{GUEST_DISPLAY_NAME_PREFIX}{session_key}"
            name = cache.get(cache_key)
            if not name:
                if cache.get(GUEST_DISPLAY_COUNTER_KEY) is None:
                    cache.set(GUEST_DISPLAY_COUNTER_KEY, 0)
                counter = cache.incr(GUEST_DISPLAY_COUNTER_KEY)
                name = f"Client{counter:03d}"
                cache.set(cache_key, name, timeout=60 * 60 * 24 * 7)
            return name

    @staticmethod
    def get_or_create_guest_session(session_key: str, **kwargs):
        try:
            from user_module.models import GuestSession
            return GuestSession.objects.get_or_create(session_key=session_key)
        except Exception as e:
            logger.error(f"Error creating guest session: {e}")
            raise

    @staticmethod
    @transaction.atomic
    def mark_session_converted(session_key: str, user: User):
        """Link a guest session to a newly registered user account."""
        try:
            from user_module.models import GuestSession
            session = GuestSession.objects.get(session_key=session_key)
            
            # Using the logic from your user_module
            session.shadow_client = user
            session.is_converted = True
            session.save()
            
            logger.info(f"Marked session {session_key[:8]}... converted to {user.username}")
        except GuestSession.DoesNotExist:
            logger.warning(f"Non-existent session {session_key[:8]}...")
