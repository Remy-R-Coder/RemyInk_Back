from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)


class GuestSessionCounter(models.Model):
    last_id = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Guest Session Counter"
        verbose_name_plural = "Guest Session Counters"

    @classmethod
    def get_next_id(cls):
        with transaction.atomic():
            counter, _ = cls.objects.select_for_update().get_or_create(pk=1)
            counter.last_id += 1
            counter.save(update_fields=['last_id'])
            return counter.last_id


class GuestSession(models.Model):
    session_key = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Django session key for this guest"
    )
    display_name = models.CharField(
        max_length=50,
        help_text="Display name shown to freelancers (e.g., Client001)"
    )
    display_number = models.PositiveIntegerField(
        help_text="Sequential number used in display name"
    )

    first_seen = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(auto_now=True)
    converted_to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='converted_guest_sessions',
        help_text="User account created from this guest session"
    )
    conversion_date = models.DateTimeField(null=True, blank=True)

    user_agent = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    referrer = models.URLField(max_length=500, blank=True, null=True)

    is_active = models.BooleanField(
        default=True,
        help_text="Whether this session is still active"
    )

    class Meta:
        ordering = ['-last_seen']
        indexes = [
            models.Index(fields=['session_key']),
            models.Index(fields=['display_number']),
            models.Index(fields=['is_active', '-last_seen']),
            models.Index(fields=['converted_to_user']),
        ]
        verbose_name = "Guest Session"
        verbose_name_plural = "Guest Sessions"

    def __str__(self):
        status = f" → {self.converted_to_user.username}" if self.converted_to_user else ""
        return f"{self.display_name} ({self.session_key[:8]}...){status}"

    @property
    def is_converted(self):
        return self.converted_to_user is not None

    @property
    def session_age(self):
        return timezone.now() - self.first_seen

    @property
    def days_since_last_activity(self):
        delta = timezone.now() - self.last_seen
        return delta.days

    @classmethod
    @transaction.atomic
    def get_or_create_session(cls, session_key, user_agent=None, ip_address=None, referrer=None):
        try:
            session = cls.objects.select_for_update().get(session_key=session_key)
            session.save(update_fields=['last_seen'])
            return session, False
        except cls.DoesNotExist:
            next_id = GuestSessionCounter.get_next_id()
            display_name = f"Client{next_id:03d}"

            session = cls.objects.create(
                session_key=session_key,
                display_name=display_name,
                display_number=next_id,
                user_agent=user_agent,
                ip_address=ip_address,
                referrer=referrer,
            )
            return session, True

    def mark_converted(self, user):
        self.converted_to_user = user
        self.conversion_date = timezone.now()
        self.is_active = False
        self.save(update_fields=['converted_to_user', 'conversion_date', 'is_active'])

    def deactivate(self):
        self.is_active = False
        self.save(update_fields=['is_active'])


def get_guest_display_name(session_key):
    if not session_key:
        return "Guest"

    try:
        session, _ = GuestSession.get_or_create_session(session_key)
        return session.display_name
    except Exception as e:
        logger.error(f"Error getting guest display name: {e}")
        key = f"guest_display_name_{session_key}"
        name = cache.get(key)

        if not name:
            if not cache.get("guest_display_counter"):
                cache.set("guest_display_counter", 0)

            counter = cache.incr("guest_display_counter")
            name = f"Client{counter:03d}"
            cache.set(key, name, timeout=60 * 60 * 24 * 7)

        return name


class ChatThread(models.Model):
    freelancer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='freelancer_threads'
    )
    guest_session_key = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True
    )
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='client_threads',
        null=True,
        blank=True
    )
    last_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        unique_together = ('freelancer', 'guest_session_key')
        ordering = ['-created_at']

    @property
    def is_guest_thread(self):
        return self.client is None and self.guest_session_key is not None

    def is_participant(self, user):
        if not user or not user.is_authenticated:
            return False
        # The primary check now ONLY uses the `client` and `freelancer` FKs.
        # It relies on a separate process (login/registration) to update
        # `self.client` when a guest converts.
        return self.freelancer == user or self.client == user

    def get_other_party(self, user, session_key):
        if user and user.is_authenticated:
            if self.freelancer == user:
                return self.client
            if self.client == user:
                return self.freelancer
        return None

    def __str__(self):
        if self.client:
            who = self.client.username
        else:
            who = get_guest_display_name(self.guest_session_key) if self.guest_session_key else "Guest(None)"
        return f"Chat between {self.freelancer.username} and {who}"


class ChatMessageQuerySet(models.QuerySet):
    def with_related(self):
        return self.select_related('sender', 'thread').prefetch_related('attachments')
    
    def offers(self):
        return self.filter(is_offer=True)
    
    def regular_messages(self):
        return self.filter(is_offer=False)
    
    def pending_offers(self):
        return self.filter(is_offer=True, offer_status='pending')
    
    def unread_by_user(self, user):
        return self.exclude(sender=user).exclude(read_by__user=user)


class ChatMessageManager(models.Manager):
    def get_queryset(self):
        return ChatMessageQuerySet(self.model, using=self._db)
    
    def with_related(self):
        return self.get_queryset().with_related()
    
    def offers(self):
        return self.get_queryset().offers()
    
    def regular_messages(self):
        return self.get_queryset().regular_messages()
    
    def pending_offers(self):
        return self.get_queryset().pending_offers()
    
    def unread_by_user(self, user):
        return self.get_queryset().unread_by_user(user)


class ChatMessage(models.Model):
    thread = models.ForeignKey(
        ChatThread,
        on_delete=models.CASCADE,
        related_name='messages',
        db_index=True
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='sent_messages',
        null=True,
        blank=True
    )
    guest_session = models.ForeignKey(
        'GuestSession',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='messages',
        help_text="Guest session if message was sent by a guest"
    )
    message = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    is_offer = models.BooleanField(default=False)
    offer_title = models.CharField(max_length=200, blank=True, null=True)
    offer_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True
    )
    offer_timeline = models.IntegerField(blank=True, null=True)
    offer_revisions = models.PositiveIntegerField(blank=True, null=True, default=2)
    offer_description = models.TextField(blank=True, null=True)

    OFFER_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ]
    offer_status = models.CharField(
        max_length=10,
        choices=OFFER_STATUS_CHOICES,
        default='pending',
        blank=True,
        null=True
    )

    created_job = models.ForeignKey(
        'orders.Job',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='source_offer',
        help_text="Job created from this offer (if accepted)"
    )

    objects = ChatMessageManager()

    class Meta:
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['thread', '-timestamp']),
            models.Index(fields=['thread', 'is_offer', 'offer_status']),
            models.Index(fields=['sender', '-timestamp']),
        ]

    @property
    def sender_display_name(self):
        if self.sender:
            return self.sender.username
        return get_guest_display_name(self.thread.guest_session_key)

    @property
    def is_pending_offer(self):
        return self.is_offer and self.offer_status == 'pending'

    @property
    def is_accepted_offer(self):
        return self.is_offer and self.offer_status == 'accepted'

    def __str__(self):
        if self.sender:
            sender_name = self.sender.username
        else:
            sender_name = get_guest_display_name(self.thread.guest_session_key)

        return f"{'Offer' if self.is_offer else 'Message'} from {sender_name} in Thread {self.thread.id}"


class MessageReadStatus(models.Model):
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name='read_by'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='read_messages',
        null=True,
        blank=True
    )
    guest_session_key = models.CharField(max_length=255, null=True, blank=True)
    read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['message', 'user'],
                condition=models.Q(user__isnull=False),
                name='unique_message_user_read'
            ),
            models.UniqueConstraint(
                fields=['message', 'guest_session_key'],
                condition=models.Q(guest_session_key__isnull=False),
                name='unique_message_guest_read'
            ),
        ]
        indexes = [
            models.Index(fields=['message', 'user']),
            models.Index(fields=['user', '-read_at']),
        ]
        verbose_name_plural = 'Message Read Statuses'

    def __str__(self):
        label = self.user.username if self.user else self.guest_session_key or "Unknown"
        return f"Message {self.message.id} read by {label}"


class ChatAttachment(models.Model):
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.SET_NULL,
        related_name='attachments',
        null=True,
        blank=True
    )
    file_url = models.URLField(max_length=1000)
    name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, blank=True, null=True)
    size = models.PositiveIntegerField(null=True, blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_attachments'
    )
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['uploaded_at']

    @property
    def is_linked(self):
        return self.message_id is not None

    @property
    def size_kb(self):
        if self.size:
            return round(self.size / 1024, 2)
        return 0

    @property
    def size_mb(self):
        if self.size:
            return round(self.size / (1024 * 1024), 2)
        return 0

    def __str__(self):
        if self.message:
            return f"Attachment {self.name} for Message {self.message.id}"
        return f"Attachment {self.name} (unlinked)"
