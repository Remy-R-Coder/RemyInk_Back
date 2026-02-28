"""
Comprehensive Notification System Models

This module provides a complete notification system with support for:
- Multiple notification types and categories
- Priority levels and expiration
- User preferences per channel/category/type
- Generic foreign keys for related objects
- Batch operations and digest support
- Actions/CTAs in notifications
"""

from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.db.models import JSONField
import uuid


class NotificationType(models.TextChoices):
    """Notification types for different events"""
    MESSAGE = 'MESSAGE', 'Message'
    JOB_CREATED = 'JOB_CREATED', 'Job Created'
    JOB_UPDATED = 'JOB_UPDATED', 'Job Updated'
    JOB_CANCELLED = 'JOB_CANCELLED', 'Job Cancelled'
    JOB_COMPLETED = 'JOB_COMPLETED', 'Job Completed'
    OFFER_RECEIVED = 'OFFER_RECEIVED', 'Offer Received'
    OFFER_ACCEPTED = 'OFFER_ACCEPTED', 'Offer Accepted'
    OFFER_REJECTED = 'OFFER_REJECTED', 'Offer Rejected'
    PAYMENT_RECEIVED = 'PAYMENT_RECEIVED', 'Payment Received'
    PAYMENT_SENT = 'PAYMENT_SENT', 'Payment Sent'
    PAYMENT_FAILED = 'PAYMENT_FAILED', 'Payment Failed'
    PAYOUT_PROCESSED = 'PAYOUT_PROCESSED', 'Payout Processed'
    REVIEW_RECEIVED = 'REVIEW_RECEIVED', 'Review Received'
    ACCOUNT_VERIFIED = 'ACCOUNT_VERIFIED', 'Account Verified'
    ACCOUNT_SUSPENDED = 'ACCOUNT_SUSPENDED', 'Account Suspended'
    SYSTEM_ANNOUNCEMENT = 'SYSTEM_ANNOUNCEMENT', 'System Announcement'
    SYSTEM_MAINTENANCE = 'SYSTEM_MAINTENANCE', 'System Maintenance'


class NotificationPriority(models.TextChoices):
    """Priority levels for notifications"""
    LOW = 'LOW', 'Low'
    NORMAL = 'NORMAL', 'Normal'
    HIGH = 'HIGH', 'High'
    URGENT = 'URGENT', 'Urgent'


class NotificationCategory(models.TextChoices):
    """Categories for organizing notifications"""
    CHAT = 'CHAT', 'Chat'
    JOB = 'JOB', 'Job'
    PAYMENT = 'PAYMENT', 'Payment'
    ACCOUNT = 'ACCOUNT', 'Account'
    SYSTEM = 'SYSTEM', 'System'


class DeliveryChannel(models.TextChoices):
    """Delivery channels for notifications"""
    IN_APP = 'IN_APP', 'In-App'
    EMAIL = 'EMAIL', 'Email'
    PUSH = 'PUSH', 'Push Notification'
    SMS = 'SMS', 'SMS'


class Notification(models.Model):
    """
    Main notification model with comprehensive features

    Supports:
    - Multiple types, priorities, and categories
    - Generic foreign keys for related objects
    - Scheduled delivery and expiration
    - Action buttons/CTAs
    - Read/archived states
    """

    # Core fields
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        db_index=True
    )

    # Classification
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        default=NotificationType.MESSAGE,
        db_index=True
    )
    category = models.CharField(
        max_length=50,
        choices=NotificationCategory.choices,
        default=NotificationCategory.SYSTEM,
        db_index=True
    )
    priority = models.CharField(
        max_length=20,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
        db_index=True
    )

    # Content
    title = models.CharField(max_length=255)
    message = models.TextField()
    summary = models.CharField(max_length=500, blank=True, help_text="Short summary for push/email")

    # Related object (generic foreign key)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications'
    )
    object_id = models.CharField(max_length=255, null=True, blank=True)
    related_object = GenericForeignKey('content_type', 'object_id')

    # Links and actions
    link = models.URLField(max_length=500, blank=True, null=True, help_text="Primary action link")
    actions = JSONField(
        default=list,
        blank=True,
        help_text="List of action buttons with label, url, and type"
    )

    # Metadata
    metadata = JSONField(
        default=dict,
        blank=True,
        help_text="Additional data for notification rendering"
    )

    # State
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    # Delivery
    channels_sent = JSONField(
        default=list,
        blank=True,
        help_text="List of channels this notification was sent to"
    )
    delivery_status = JSONField(
        default=dict,
        blank=True,
        help_text="Delivery status per channel"
    )

    # Scheduling
    scheduled_for = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Schedule notification for future delivery"
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Expiration time for notification"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Batch support
    batch = models.ForeignKey(
        'NotificationBatch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['recipient', 'is_read', '-created_at']),
            models.Index(fields=['recipient', 'category', '-created_at']),
            models.Index(fields=['scheduled_for', 'created_at']),
            models.Index(fields=['expires_at']),
        ]
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'

    def __str__(self):
        return f"{self.get_notification_type_display()} - {self.recipient.email}"

    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

    def mark_as_unread(self):
        """Mark notification as unread"""
        if self.is_read:
            self.is_read = False
            self.read_at = None
            self.save(update_fields=['is_read', 'read_at'])

    def archive(self):
        """Archive notification"""
        if not self.is_archived:
            self.is_archived = True
            self.archived_at = timezone.now()
            self.save(update_fields=['is_archived', 'archived_at'])

    def unarchive(self):
        """Unarchive notification"""
        if self.is_archived:
            self.is_archived = False
            self.archived_at = None
            self.save(update_fields=['is_archived', 'archived_at'])

    def is_expired(self):
        """Check if notification has expired"""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    def should_deliver(self):
        """Check if notification should be delivered now"""
        if self.is_expired():
            return False
        if self.scheduled_for and self.scheduled_for > timezone.now():
            return False
        return True


class NotificationPreference(models.Model):
    """
    User preferences for notification delivery

    Allows users to control:
    - Which notification types they receive
    - Which channels to use per type/category
    - Quiet hours
    - Digest frequency
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )

    # Global settings
    enabled = models.BooleanField(
        default=True,
        help_text="Master switch for all notifications"
    )

    # Channel preferences (global defaults)
    in_app_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=False)
    sms_enabled = models.BooleanField(default=False)

    # Category-specific preferences
    category_preferences = JSONField(
        default=dict,
        blank=True,
        help_text="Per-category channel preferences"
    )

    # Type-specific preferences
    type_preferences = JSONField(
        default=dict,
        blank=True,
        help_text="Per-type channel preferences"
    )

    # Quiet hours
    quiet_hours_enabled = models.BooleanField(default=False)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    quiet_hours_timezone = models.CharField(max_length=50, default='UTC')

    # Digest settings
    digest_enabled = models.BooleanField(default=False)
    digest_frequency = models.CharField(
        max_length=20,
        choices=[
            ('DAILY', 'Daily'),
            ('WEEKLY', 'Weekly'),
            ('MONTHLY', 'Monthly'),
        ],
        default='DAILY'
    )
    digest_time = models.TimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Notification Preference'
        verbose_name_plural = 'Notification Preferences'

    def __str__(self):
        return f"Preferences for {self.user.email}"

    def is_channel_enabled(self, channel, notification_type=None, category=None):
        """
        Check if a specific channel is enabled for given type/category

        Priority: type_preferences > category_preferences > global settings
        """
        if not self.enabled:
            return False

        # Check type-specific preference
        if notification_type and notification_type in self.type_preferences:
            type_pref = self.type_preferences[notification_type]
            if channel.lower() in type_pref:
                return type_pref[channel.lower()]

        # Check category-specific preference
        if category and category in self.category_preferences:
            cat_pref = self.category_preferences[category]
            if channel.lower() in cat_pref:
                return cat_pref[channel.lower()]

        # Fall back to global setting
        channel_map = {
            'IN_APP': self.in_app_enabled,
            'EMAIL': self.email_enabled,
            'PUSH': self.push_enabled,
            'SMS': self.sms_enabled,
        }
        return channel_map.get(channel, False)

    def is_in_quiet_hours(self):
        """Check if current time is within quiet hours"""
        if not self.quiet_hours_enabled or not self.quiet_hours_start or not self.quiet_hours_end:
            return False

        import pytz
        tz = pytz.timezone(self.quiet_hours_timezone)
        now = timezone.now().astimezone(tz).time()

        if self.quiet_hours_start < self.quiet_hours_end:
            return self.quiet_hours_start <= now <= self.quiet_hours_end
        else:
            # Quiet hours span midnight
            return now >= self.quiet_hours_start or now <= self.quiet_hours_end


class NotificationTemplate(models.Model):
    """
    Templates for notification content

    Supports template variables and multi-channel content
    """

    name = models.CharField(max_length=100, unique=True)
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        unique=True
    )

    # Template content per channel
    in_app_title_template = models.CharField(max_length=255)
    in_app_message_template = models.TextField()

    email_subject_template = models.CharField(max_length=255, blank=True)
    email_body_template = models.TextField(blank=True)
    email_html_template = models.TextField(blank=True)

    push_title_template = models.CharField(max_length=255, blank=True)
    push_body_template = models.TextField(blank=True)

    sms_template = models.CharField(max_length=160, blank=True)

    # Default settings
    default_priority = models.CharField(
        max_length=20,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL
    )
    default_category = models.CharField(
        max_length=50,
        choices=NotificationCategory.choices,
        default=NotificationCategory.SYSTEM
    )
    default_expires_in_hours = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Default expiration time in hours"
    )

    # Metadata
    variables = JSONField(
        default=list,
        blank=True,
        help_text="List of available template variables"
    )

    # State
    is_active = models.BooleanField(default=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Notification Template'
        verbose_name_plural = 'Notification Templates'

    def __str__(self):
        return f"{self.name} ({self.get_notification_type_display()})"

    def render(self, channel, context):
        """
        Render template for specific channel with context

        Args:
            channel: DeliveryChannel value
            context: Dictionary of template variables

        Returns:
            Dictionary with rendered content
        """
        from django.template import Context, Template

        if channel == DeliveryChannel.IN_APP:
            title_tmpl = Template(self.in_app_title_template)
            message_tmpl = Template(self.in_app_message_template)
            return {
                'title': title_tmpl.render(Context(context)),
                'message': message_tmpl.render(Context(context)),
            }

        elif channel == DeliveryChannel.EMAIL:
            subject_tmpl = Template(self.email_subject_template)
            body_tmpl = Template(self.email_body_template)
            html_tmpl = Template(self.email_html_template) if self.email_html_template else None
            return {
                'subject': subject_tmpl.render(Context(context)),
                'body': body_tmpl.render(Context(context)),
                'html': html_tmpl.render(Context(context)) if html_tmpl else None,
            }

        elif channel == DeliveryChannel.PUSH:
            title_tmpl = Template(self.push_title_template)
            body_tmpl = Template(self.push_body_template)
            return {
                'title': title_tmpl.render(Context(context)),
                'body': body_tmpl.render(Context(context)),
            }

        elif channel == DeliveryChannel.SMS:
            sms_tmpl = Template(self.sms_template)
            return {
                'message': sms_tmpl.render(Context(context)),
            }

        return {}


class NotificationBatch(models.Model):
    """
    Batch of notifications for digest emails or bulk operations
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    batch_type = models.CharField(
        max_length=20,
        choices=[
            ('DIGEST', 'Digest'),
            ('BULK', 'Bulk'),
            ('SCHEDULED', 'Scheduled'),
        ],
        default='BULK'
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('PENDING', 'Pending'),
            ('PROCESSING', 'Processing'),
            ('COMPLETED', 'Completed'),
            ('FAILED', 'Failed'),
        ],
        default='PENDING',
        db_index=True
    )

    # Schedule
    scheduled_for = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    # Statistics
    total_notifications = models.IntegerField(default=0)
    sent_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)

    # Metadata
    metadata = JSONField(default=dict, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Notification Batch'
        verbose_name_plural = 'Notification Batches'

    def __str__(self):
        return f"{self.name} ({self.status})"

    def update_statistics(self):
        """Update batch statistics from related notifications"""
        self.total_notifications = self.notifications.count()
        self.sent_count = self.notifications.filter(
            delivery_status__has_key='sent'
        ).count()
        self.save(update_fields=['total_notifications', 'sent_count'])
