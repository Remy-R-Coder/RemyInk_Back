import hashlib
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from django.core.cache import cache
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction

logger = logging.getLogger(__name__)
User = get_user_model()


def generate_session_hash(session_key: str) -> str:
    return hashlib.sha256(session_key.encode()).hexdigest()[:16]


def format_timestamp(dt: datetime) -> str:
    now = timezone.now()
    diff = now - dt
    
    if diff < timedelta(minutes=1):
        return "Just now"
    elif diff < timedelta(hours=1):
        minutes = int(diff.total_seconds() / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif diff < timedelta(days=1):
        hours = int(diff.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif diff < timedelta(days=7):
        days = diff.days
        return f"{days} day{'s' if days != 1 else ''} ago"
    else:
        return dt.strftime("%b %d, %Y at %I:%M %p")


def sanitize_message(message: str, max_length: int = 10000) -> str:
    if not message:
        raise ValueError("Message cannot be empty")
    
    message = message.strip()
    
    if not message:
        raise ValueError("Message cannot be empty")
    
    if len(message) > max_length:
        raise ValueError(f"Message exceeds maximum length of {max_length}")
    
    message = message.replace('\x00', '')
    
    return message


def get_online_users_in_thread(thread_id: int) -> List[str]:
    cache_key = f"thread_{thread_id}_online_users"
    online_users = cache.get(cache_key, [])
    return online_users


def mark_user_online_in_thread(thread_id: int, username: str, timeout: int = 300):
    cache_key = f"thread_{thread_id}_online_users"
    online_users = cache.get(cache_key, [])
    
    if username not in online_users:
        online_users.append(username)
        cache.set(cache_key, online_users, timeout=timeout)
        
        logger.debug(f"Marked {username} as online in thread {thread_id}")


def mark_user_offline_in_thread(thread_id: int, username: str):
    cache_key = f"thread_{thread_id}_online_users"
    online_users = cache.get(cache_key, [])
    
    if username in online_users:
        online_users.remove(username)
        cache.set(cache_key, online_users, timeout=300)
        
        logger.debug(f"Marked {username} as offline in thread {thread_id}")


def validate_file_upload(file, max_size: int = 10 * 1024 * 1024) -> Dict[str, Any]:
    errors = []
    
    if file.size > max_size:
        errors.append(f"File size exceeds maximum of {max_size / (1024 * 1024)}MB")
    
    if file.size == 0:
        errors.append("File is empty")
    
    dangerous_chars = ['..', '/', '\\', '\x00']
    if any(char in file.name for char in dangerous_chars):
        errors.append("Invalid filename")
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'file_info': {
            'name': file.name,
            'size': file.size,
            'content_type': file.content_type,
        }
    }


def calculate_unread_count(thread, user: Optional[User], session_key: Optional[str]) -> int:
    from .models import ChatMessage
    
    if user and user.is_authenticated:
        return (
            ChatMessage.objects
            .filter(thread=thread)
            .exclude(sender=user)
            .exclude(read_by__user=user)
            .count()
        )
    
    if session_key and str(thread.guest_session_key).strip() == str(session_key).strip():
        from .models import MessageReadStatus
        
        return (
            ChatMessage.objects
            .filter(thread=thread, sender=thread.freelancer)
            .exclude(read_by__guest_session_key=session_key)
            .count()
        )
    
    return 0


def batch_serialize_messages(messages: List) -> List[Dict[str, Any]]:
    from .services import GuestNameService
    
    serialized = []
    
    for msg in messages:
        sender_name = (
            msg.sender.username if msg.sender else
            GuestNameService.get_guest_display_name(msg.thread.guest_session_key)
        )
        
        offer_data = None
        if msg.is_offer:
            offer_data = {
                'id': str(msg.id),
                'title': msg.offer_title,
                'price': str(msg.offer_price) if msg.offer_price else None,
                'timeline': msg.offer_timeline,
                'revisions': msg.offer_revisions,
                'description': msg.offer_description,
                'status': msg.offer_status,
            }
        
        serialized.append({
            'id': str(msg.id),
            'thread_id': str(msg.thread_id),
            'sender_name': sender_name,
            'message': msg.message,
            'is_offer': msg.is_offer,
            'offer': offer_data,
            'timestamp': msg.timestamp.isoformat(),
        })
    
    return serialized


def get_or_create_session_key(request) -> str:
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def is_valid_uuid(uuid_string: str) -> bool:
    import uuid
    try:
        uuid.UUID(uuid_string)
        return True
    except (ValueError, AttributeError):
        return False
