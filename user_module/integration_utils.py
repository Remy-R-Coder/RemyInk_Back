from typing import Optional, Dict, List, Tuple
from django.db.models import Count, Q, Exists, OuterRef
from django.utils import timezone
from datetime import timedelta

from chat.models import ChatThread, ChatMessage, MessageReadStatus
from chat.services import GuestNameService, ChatThreadService
from .models import User, Role


class ChatIntegrationHelper:
    @staticmethod
    def get_user_chat_stats(user: User) -> Dict:
        if user.role == Role.FREELANCER or user.is_superuser:
            threads = ChatThread.objects.filter(freelancer=user)
        elif user.role == Role.CLIENT:
            threads = ChatThread.objects.filter(client=user)
        else:
            return {
                'total_threads': 0,
                'unread_messages': 0,
                'active_threads_7d': 0,
                'total_messages_sent': 0,
                'total_messages_received': 0,
            }

        seven_days_ago = timezone.now() - timedelta(days=7)
        
        stats = threads.aggregate(
            total_threads=Count('id'),
            active_threads_7d=Count(
                'id',
                filter=Q(updated_at__gte=seven_days_ago)
            )
        )

        unread_messages = ChatMessage.objects.filter(
            thread__in=threads
        ).exclude(
            sender=user
        ).exclude(
            read_by__user=user
        ).count()

        messages_sent = ChatMessage.objects.filter(
            thread__in=threads,
            sender=user
        ).count()

        messages_received = ChatMessage.objects.filter(
            thread__in=threads
        ).exclude(
            sender=user
        ).count()

        return {
            'total_threads': stats['total_threads'] or 0,
            'unread_messages': unread_messages,
            'active_threads_7d': stats['active_threads_7d'] or 0,
            'total_messages_sent': messages_sent,
            'total_messages_received': messages_received,
        }

    @staticmethod
    def get_thread_for_users(
        user1: User,
        user2: User,
        create: bool = False
    ) -> Optional[ChatThread]:
        if user1.role in [Role.FREELANCER, Role.ADMIN]:
            freelancer, client = user1, user2
        else:
            freelancer, client = user2, user1

        if create:
            thread, _ = ChatThread.objects.get_or_create(
                freelancer=freelancer,
                client=client,
                guest_session_key=None
            )
            return thread
        else:
            return ChatThread.objects.filter(
                freelancer=freelancer,
                client=client
            ).first()

    @staticmethod
    def mark_thread_as_read(thread: ChatThread, user: User) -> int:
        unread_messages = ChatMessage.objects.filter(
            thread=thread
        ).exclude(
            sender=user
        ).exclude(
            read_by__user=user
        )

        read_statuses = [
            MessageReadStatus(message=msg, user=user)
            for msg in unread_messages
        ]

        MessageReadStatus.objects.bulk_create(
            read_statuses,
            ignore_conflicts=True
        )

        return len(read_statuses)

    @staticmethod
    def get_recent_chat_partners(
        user: User,
        limit: int = 10
    ) -> List[Dict]:
        if user.role == Role.FREELANCER or user.is_superuser:
            threads = ChatThread.objects.filter(
                freelancer=user
            ).select_related('client').order_by('-updated_at')[:limit]
        elif user.role == Role.CLIENT:
            threads = ChatThread.objects.filter(
                client=user
            ).select_related('freelancer').order_by('-updated_at')[:limit]
        else:
            return []

        partners = []
        for thread in threads:
            if thread.freelancer == user:
                partner = thread.client
                partner_name = (
                    partner.username if partner
                    else GuestNameService.get_guest_display_name(
                        thread.guest_session_key
                    )
                )
            else:
                partner = thread.freelancer
                partner_name = partner.username

            unread_count = ChatMessage.objects.filter(
                thread=thread
            ).exclude(
                sender=user
            ).exclude(
                read_by__user=user
            ).count()

            partners.append({
                'thread_id': thread.id,
                'partner_id': str(partner.id) if partner else None,
                'partner_name': partner_name,
                'last_message': thread.last_message,
                'unread_count': unread_count,
                'updated_at': thread.updated_at,
            })

        return partners

    @staticmethod
    def get_unread_threads_count(user: User) -> int:
        if user.role == Role.FREELANCER or user.is_superuser:
            threads = ChatThread.objects.filter(freelancer=user)
        elif user.role == Role.CLIENT:
            threads = ChatThread.objects.filter(client=user)
        else:
            return 0

        has_unread = ChatMessage.objects.filter(
            thread=OuterRef('pk')
        ).exclude(
            sender=user
        ).exclude(
            read_by__user=user
        )

        return threads.annotate(
            has_unread_messages=Exists(has_unread)
        ).filter(has_unread_messages=True).count()

    @staticmethod
    def calculate_response_time(user: User, days: int = 30) -> Optional[float]:
        if not (user.role == Role.FREELANCER or user.is_superuser):
            return None

        cutoff_date = timezone.now() - timedelta(days=days)
        threads = ChatThread.objects.filter(
            freelancer=user,
            created_at__gte=cutoff_date
        )[:20]  

        response_times = []
        for thread in threads:
            first_client_msg = thread.messages.exclude(
                sender=user
            ).order_by('timestamp').first()

            if not first_client_msg:
                continue

            first_response = thread.messages.filter(
                sender=user,
                timestamp__gt=first_client_msg.timestamp
            ).order_by('timestamp').first()

            if first_response:
                time_diff = (
                    first_response.timestamp - 
                    first_client_msg.timestamp
                )
                response_times.append(time_diff.total_seconds() / 60)

        if response_times:
            return sum(response_times) / len(response_times)
        
        return None


class GuestToClientConverter:
    @staticmethod
    def link_guest_threads(
        guest_session_key: str,
        client: User
    ) -> Tuple[int, List[int]]:
        if client.role != Role.CLIENT:
            raise ValueError("User must be a client to link guest threads")

        threads = ChatThread.objects.filter(
            guest_session_key=guest_session_key,
            client__isnull=True
        )

        thread_ids = list(threads.values_list('id', flat=True))
        count = threads.update(client=client)

        return count, thread_ids

    @staticmethod
    def get_guest_thread_summary(guest_session_key: str) -> Dict:
        threads = ChatThread.objects.filter(
            guest_session_key=guest_session_key
        ).select_related('freelancer')

        return {
            'total_threads': threads.count(),
            'freelancers': list(
                threads.values_list('freelancer__username', flat=True)
            ),
            'thread_ids': list(threads.values_list('id', flat=True)),
            'first_created': (
                threads.order_by('created_at').first().created_at
                if threads.exists() else None
            ),
        }


class NotificationChatBridge:
    @staticmethod
    def create_message_notification(
        message: ChatMessage,
        recipient: User
    ) -> Optional['Notification']:
        from notifications.models import Notification

        # Don't notify sender
        if message.sender == recipient:
            return None

        # Get sender name
        if message.sender:
            sender_name = message.sender.username
        else:
            sender_name = GuestNameService.get_guest_display_name(
                message.thread.guest_session_key
            )

        # Create notification
        notification = Notification.objects.create(
            recipient=recipient,
            notification_type='MESSAGE',
            category='CHAT',
            title='New Message',
            message=f'New message from {sender_name}',
            link=f'/messages/{message.thread.id}',
        )

        return notification

    @staticmethod
    def mark_thread_notifications_read(
        thread: ChatThread,
        user: User
    ) -> int:
        """
        Mark all notifications for a thread as read.
        
        Args:
            thread: ChatThread instance
            user: User instance
            
        Returns:
            Number of notifications marked as read
        """
        from notifications.models import Notification

        count = Notification.objects.filter(
            recipient=user,
            link=f'/messages/{thread.id}',
            is_read=False
        ).update(is_read=True)

        return count
