class WSMessageType:
    CHAT_MESSAGE = 'chat_message'
    OFFER = 'offer'
    OFFER_DECISION = 'offer_decision'
    TYPING = 'typing'
    THREAD_JOINED = 'thread_joined'
    THREAD_CREATED = 'thread_created'
    THREAD_HISTORY = 'thread_history'
    ERROR = 'error'


class WSCloseCode:
    NORMAL = 1000
    MISSING_PARAMS = 4003
    THREAD_NOT_FOUND = 4004
    ACCESS_DENIED = 4005


class OfferStatus:
    PENDING = 'pending'
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    
    CHOICES = [
        (PENDING, 'Pending'),
        (ACCEPTED, 'Accepted'),
        (REJECTED, 'Rejected'),
    ]
    
    ALL = [PENDING, ACCEPTED, REJECTED]


GUEST_DISPLAY_NAME_PREFIX = 'guest_display_name_'
GUEST_DISPLAY_COUNTER_KEY = 'guest_display_counter'
GUEST_NAME_CACHE_TIMEOUT = 60 * 60 * 24 * 7

DEFAULT_MESSAGE_HISTORY_LIMIT = 100
MAX_MESSAGE_HISTORY_LIMIT = 500

MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
ALLOWED_ATTACHMENT_TYPES = [
    'image/jpeg',
    'image/png',
    'image/gif',
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]