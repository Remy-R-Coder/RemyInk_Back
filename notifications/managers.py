"""
Custom QuerySet and Manager classes for Notification models

Provides convenient methods for common notification queries:
- Filtering by read/unread status
- Category and priority filtering
- Expiration handling
- Bulk operations
"""

from django.db import models
from django.db.models import Q, Count, Case, When, IntegerField
from django.utils import timezone
from datetime import timedelta


class NotificationQuerySet(models.QuerySet):
    """Custom QuerySet for Notification model"""

    def for_user(self, user):
        """Get notifications for specific user"""
        return self.filter(recipient=user)

    def unread(self):
        """Get unread notifications"""
        return self.filter(is_read=False)

    def read(self):
        """Get read notifications"""
        return self.filter(is_read=True)

    def archived(self):
        """Get archived notifications"""
        return self.filter(is_archived=True)

    def active(self):
        """Get active (non-archived) notifications"""
        return self.filter(is_archived=False)

    def by_category(self, category):
        """Filter by category"""
        return self.filter(category=category)

    def by_type(self, notification_type):
        """Filter by notification type"""
        return self.filter(notification_type=notification_type)

    def by_priority(self, priority):
        """Filter by priority"""
        return self.filter(priority=priority)

    def high_priority(self):
        """Get high and urgent priority notifications"""
        from notifications.models import NotificationPriority
        return self.filter(
            priority__in=[NotificationPriority.HIGH, NotificationPriority.URGENT]
        )

    def expired(self):
        """Get expired notifications"""
        return self.filter(
            expires_at__isnull=False,
            expires_at__lt=timezone.now()
        )

    def not_expired(self):
        """Get non-expired notifications"""
        return self.filter(
            Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
        )

    def scheduled(self):
        """Get scheduled (future) notifications"""
        return self.filter(
            scheduled_for__isnull=False,
            scheduled_for__gt=timezone.now()
        )

    def ready_to_deliver(self):
        """Get notifications ready for delivery"""
        now = timezone.now()
        return self.filter(
            Q(scheduled_for__isnull=True) | Q(scheduled_for__lte=now)
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gte=now)
        )

    def recent(self, days=7):
        """Get notifications from last N days"""
        since = timezone.now() - timedelta(days=days)
        return self.filter(created_at__gte=since)

    def older_than(self, days):
        """Get notifications older than N days"""
        cutoff = timezone.now() - timedelta(days=days)
        return self.filter(created_at__lt=cutoff)

    def with_related_object(self, content_type=None):
        """Get notifications with related objects"""
        qs = self.filter(content_type__isnull=False, object_id__isnull=False)
        if content_type:
            qs = qs.filter(content_type=content_type)
        return qs

    def mark_all_as_read(self):
        """Bulk mark notifications as read"""
        now = timezone.now()
        return self.filter(is_read=False).update(
            is_read=True,
            read_at=now
        )

    def mark_all_as_unread(self):
        """Bulk mark notifications as unread"""
        return self.filter(is_read=True).update(
            is_read=False,
            read_at=None
        )

    def archive_all(self):
        """Bulk archive notifications"""
        now = timezone.now()
        return self.filter(is_archived=False).update(
            is_archived=True,
            archived_at=now
        )

    def unarchive_all(self):
        """Bulk unarchive notifications"""
        return self.filter(is_archived=True).update(
            is_archived=False,
            archived_at=None
        )

    def delete_expired(self):
        """Delete expired notifications"""
        return self.expired().delete()

    def delete_old(self, days=90):
        """Delete notifications older than N days"""
        return self.older_than(days).delete()

    def with_statistics(self):
        """Annotate queryset with statistics"""
        return self.annotate(
            unread_count=Count(
                Case(
                    When(is_read=False, then=1),
                    output_field=IntegerField()
                )
            )
        )


class NotificationManager(models.Manager):
    """Custom Manager for Notification model"""

    def get_queryset(self):
        return NotificationQuerySet(self.model, using=self._db)

    def for_user(self, user):
        return self.get_queryset().for_user(user)

    def unread(self):
        return self.get_queryset().unread()

    def read(self):
        return self.get_queryset().read()

    def archived(self):
        return self.get_queryset().archived()

    def active(self):
        return self.get_queryset().active()

    def by_category(self, category):
        return self.get_queryset().by_category(category)

    def by_type(self, notification_type):
        return self.get_queryset().by_type(notification_type)

    def by_priority(self, priority):
        return self.get_queryset().by_priority(priority)

    def high_priority(self):
        return self.get_queryset().high_priority()

    def expired(self):
        return self.get_queryset().expired()

    def not_expired(self):
        return self.get_queryset().not_expired()

    def scheduled(self):
        return self.get_queryset().scheduled()

    def ready_to_deliver(self):
        return self.get_queryset().ready_to_deliver()

    def recent(self, days=7):
        return self.get_queryset().recent(days)

    def older_than(self, days):
        return self.get_queryset().older_than(days)

    def create_notification(self, recipient, title, message, **kwargs):
        """
        Convenience method to create a notification

        Args:
            recipient: User instance
            title: Notification title
            message: Notification message
            **kwargs: Additional fields

        Returns:
            Notification instance
        """
        return self.create(
            recipient=recipient,
            title=title,
            message=message,
            **kwargs
        )

    def cleanup_expired(self):
        """Remove expired notifications"""
        count, _ = self.get_queryset().delete_expired()
        return count

    def cleanup_old(self, days=90):
        """Remove old notifications"""
        count, _ = self.get_queryset().delete_old(days)
        return count


class NotificationBatchQuerySet(models.QuerySet):
    """Custom QuerySet for NotificationBatch model"""

    def pending(self):
        """Get pending batches"""
        return self.filter(status='PENDING')

    def processing(self):
        """Get processing batches"""
        return self.filter(status='PROCESSING')

    def completed(self):
        """Get completed batches"""
        return self.filter(status='COMPLETED')

    def failed(self):
        """Get failed batches"""
        return self.filter(status='FAILED')

    def by_type(self, batch_type):
        """Filter by batch type"""
        return self.filter(batch_type=batch_type)

    def digests(self):
        """Get digest batches"""
        return self.filter(batch_type='DIGEST')

    def bulk(self):
        """Get bulk batches"""
        return self.filter(batch_type='BULK')

    def scheduled_batches(self):
        """Get scheduled batches"""
        return self.filter(batch_type='SCHEDULED')

    def ready_to_process(self):
        """Get batches ready to process"""
        now = timezone.now()
        return self.filter(
            status='PENDING',
            scheduled_for__lte=now
        )

    def with_notification_count(self):
        """Annotate with notification count"""
        return self.annotate(
            notification_count=Count('notifications')
        )


class NotificationBatchManager(models.Manager):
    """Custom Manager for NotificationBatch model"""

    def get_queryset(self):
        return NotificationBatchQuerySet(self.model, using=self._db)

    def pending(self):
        return self.get_queryset().pending()

    def processing(self):
        return self.get_queryset().processing()

    def completed(self):
        return self.get_queryset().completed()

    def failed(self):
        return self.get_queryset().failed()

    def by_type(self, batch_type):
        return self.get_queryset().by_type(batch_type)

    def digests(self):
        return self.get_queryset().digests()

    def bulk(self):
        return self.get_queryset().bulk()

    def scheduled_batches(self):
        return self.get_queryset().scheduled_batches()

    def ready_to_process(self):
        return self.get_queryset().ready_to_process()

    def create_batch(self, name, batch_type='BULK', **kwargs):
        """
        Convenience method to create a batch

        Args:
            name: Batch name
            batch_type: Type of batch
            **kwargs: Additional fields

        Returns:
            NotificationBatch instance
        """
        return self.create(
            name=name,
            batch_type=batch_type,
            **kwargs
        )


class NotificationPreferenceQuerySet(models.QuerySet):
    """Custom QuerySet for NotificationPreference model"""

    def enabled(self):
        """Get preferences with notifications enabled"""
        return self.filter(enabled=True)

    def disabled(self):
        """Get preferences with notifications disabled"""
        return self.filter(enabled=False)

    def email_enabled(self):
        """Get preferences with email enabled"""
        return self.filter(enabled=True, email_enabled=True)

    def push_enabled(self):
        """Get preferences with push enabled"""
        return self.filter(enabled=True, push_enabled=True)

    def digest_enabled(self):
        """Get preferences with digest enabled"""
        return self.filter(enabled=True, digest_enabled=True)

    def by_digest_frequency(self, frequency):
        """Filter by digest frequency"""
        return self.filter(digest_enabled=True, digest_frequency=frequency)


class NotificationPreferenceManager(models.Manager):
    """Custom Manager for NotificationPreference model"""

    def get_queryset(self):
        return NotificationPreferenceQuerySet(self.model, using=self._db)

    def enabled(self):
        return self.get_queryset().enabled()

    def disabled(self):
        return self.get_queryset().disabled()

    def email_enabled(self):
        return self.get_queryset().email_enabled()

    def push_enabled(self):
        return self.get_queryset().push_enabled()

    def digest_enabled(self):
        return self.get_queryset().digest_enabled()

    def by_digest_frequency(self, frequency):
        return self.get_queryset().by_digest_frequency(frequency)

    def get_or_create_for_user(self, user):
        """
        Get or create preferences for user

        Args:
            user: User instance

        Returns:
            tuple: (NotificationPreference, created)
        """
        return self.get_or_create(user=user)


class NotificationTemplateQuerySet(models.QuerySet):
    """Custom QuerySet for NotificationTemplate model"""

    def active(self):
        """Get active templates"""
        return self.filter(is_active=True)

    def inactive(self):
        """Get inactive templates"""
        return self.filter(is_active=False)

    def by_type(self, notification_type):
        """Get template by notification type"""
        return self.filter(notification_type=notification_type)


class NotificationTemplateManager(models.Manager):
    """Custom Manager for NotificationTemplate model"""

    def get_queryset(self):
        return NotificationTemplateQuerySet(self.model, using=self._db)

    def active(self):
        return self.get_queryset().active()

    def inactive(self):
        return self.get_queryset().inactive()

    def by_type(self, notification_type):
        return self.get_queryset().by_type(notification_type)

    def get_template_for_type(self, notification_type):
        """
        Get active template for notification type

        Args:
            notification_type: NotificationType value

        Returns:
            NotificationTemplate or None
        """
        try:
            return self.active().get(notification_type=notification_type)
        except self.model.DoesNotExist:
            return None
