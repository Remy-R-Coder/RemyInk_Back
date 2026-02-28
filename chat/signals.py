import logging
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.core.cache import cache
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import ChatMessage, ChatThread
from .constants import GUEST_DISPLAY_NAME_PREFIX

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ChatMessage)
def update_thread_on_message(sender, instance, created, **kwargs):
    if created and instance.thread:
        if not instance.thread.last_message:
            instance.thread.last_message = instance.message or 'New message'
            instance.thread.save(update_fields=['last_message', 'updated_at'])
            logger.debug(f"Signal: Updated thread {instance.thread_id} on new message {instance.id}")


@receiver(pre_delete, sender=ChatThread)
def cleanup_thread_cache(sender, instance, **kwargs):
    if instance.guest_session_key:
        cache_key = f"{GUEST_DISPLAY_NAME_PREFIX}{instance.guest_session_key}"
        cache.delete(cache_key)
        logger.debug(f"Signal: Cleaned up cache for guest session {instance.guest_session_key[:8]}...")


@receiver(post_save, sender=ChatMessage)
def broadcast_new_message(sender, instance, created, **kwargs):
    if created:
        channel_layer = get_channel_layer()
        room_group_name = f'chat_{instance.thread_id}'
        
        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'chat_message',
                'message': {
                    'id': str(instance.id),
                    'text': instance.message,
                    'sender': instance.sender.username if instance.sender else 'Guest',
                    'timestamp': instance.timestamp.isoformat(),
                }
            }
        )