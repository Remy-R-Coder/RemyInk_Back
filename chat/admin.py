from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta

from .models import (
    ChatThread,
    ChatMessage,
    MessageReadStatus,
    ChatAttachment,
    GuestSession,
    GuestSessionCounter,
)


class MessageReadStatusInline(admin.TabularInline):
    """Inline admin for message read statuses."""
    
    model = MessageReadStatus
    extra = 0
    fields = ('user', 'guest_session_key', 'read_at')
    readonly_fields = ('user', 'guest_session_key', 'read_at')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


class ChatAttachmentInline(admin.TabularInline):
    """Inline admin for message attachments."""
    
    model = ChatAttachment
    extra = 0
    fields = ('name', 'file_url', 'mime_type', 'size_mb', 'uploaded_by', 'uploaded_at')
    readonly_fields = ('name', 'file_url', 'mime_type', 'size_mb', 'uploaded_by', 'uploaded_at')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ChatThread)
class ChatThreadAdmin(admin.ModelAdmin):
    """Admin interface for chat threads."""
    
    list_display = (
        'id',
        'thread_participants',
        # 'thread_type',
        'message_count',
        'unread_count',
        'created_at',
        'updated_at',
    )
    
    list_filter = (
        'created_at',
        'updated_at',
    )
    
    search_fields = (
        'freelancer__username',
        'client__username',
        'guest_session_key',
        'id',
    )
    
    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        # 'participant_count',
        'is_guest_thread',
        'last_message',
    )
    
    autocomplete_fields = ['freelancer', 'client']
    
    fieldsets = (
        ('Participants', {
            'fields': ('freelancer', 'client', 'guest_session_key')
        }),
        ('Thread Info', {
            'fields': ('id', 'is_guest_thread', 'last_message')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def get_queryset(self, request):
        """Optimize queryset with annotations."""
        qs = super().get_queryset(request)
        return qs.select_related('freelancer', 'client').annotate(
            msg_count=Count('messages'),
            unread_messages=Count(
                'messages',
                filter=Q(messages__read_by__isnull=True)
            )
        )
    
    @admin.display(description='Participants')
    def thread_participants(self, obj):
        """Display thread participants."""
        freelancer = obj.freelancer.username if obj.freelancer else 'N/A'
        
        if obj.client:
            client = obj.client.username
        elif obj.guest_session_key:
            client = f'Guest ({obj.guest_session_key[:8]}...)'
        else:
            client = 'N/A'
        
        return f'{freelancer} ↔ {client}'
    
    # @admin.display(description='Type')
    # def thread_type(self, obj):
    #     """Display thread type."""
    #     if obj.is_guest_thread:
    #         return format_html('<span style="color: orange;">Guest</span>')
    #     return format_html('<span style="color: green;">Registered</span>')
    
    @admin.display(description='Messages')
    def message_count(self, obj):
        """Display message count."""
        return obj.msg_count
    
    @admin.display(description='Unread')
    def unread_count(self, obj):
        """Display unread message count."""
        count = obj.unread_messages
        if count > 0:
            return format_html('<span style="color: red; font-weight: bold;">{}</span>', count)
        return count


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    """Admin interface for chat messages."""
    
    list_display = (
        'id',
        'message_type',
        'thread_link',
        'sender_info',
        'message_preview',
        'timestamp',
        'read_count',
    )
    
    list_filter = (
        'is_offer',
        'offer_status',
        'timestamp',
    )
    
    search_fields = (
        'message',
        'sender__username',
        'thread__id',
        'offer_title',
    )
    
    readonly_fields = (
        'id',
        'timestamp',
        'updated_at',
        'sender_display_name',
        'is_pending_offer',
        'is_accepted_offer',
    )
    
    raw_id_fields = ('thread', 'sender')
    
    inlines = [MessageReadStatusInline, ChatAttachmentInline]
    
    fieldsets = (
        ('Message Info', {
            'fields': ('id', 'thread', 'sender', 'sender_display_name', 'message')
        }),
        ('Offer Details', {
            'fields': (
                'is_offer',
                'offer_title',
                'offer_price',
                'offer_timeline',
                'offer_description',
                'offer_status',
                'is_pending_offer',
                'is_accepted_offer',
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('timestamp', 'updated_at')
        }),
    )
    
    def get_queryset(self, request):
        """Optimize queryset."""
        qs = super().get_queryset(request)
        return qs.select_related('sender', 'thread').prefetch_related('read_by', 'attachments')
    
    @admin.display(description='Type')
    def message_type(self, obj):
        """Display message type."""
        if obj.is_offer:
            color = {
                'pending': 'orange',
                'accepted': 'green',
                'rejected': 'red',
            }.get(obj.offer_status, 'gray')
            
            return format_html(
                '<span style="color: {};">Offer ({})</span>',
                color,
                obj.offer_status.title()
            )
        return format_html('<span style="color: blue;">Message</span>')
    
    @admin.display(description='Thread')
    def thread_link(self, obj):
        """Display link to thread."""
        url = reverse('admin:chat_chatthread_change', args=[obj.thread_id])
        return format_html('<a href="{}">{}</a>', url, obj.thread_id)
    
    @admin.display(description='Sender')
    def sender_info(self, obj):
        """Display sender information."""
        return obj.sender_display_name
    
    @admin.display(description='Message')
    def message_preview(self, obj):
        """Display message preview."""
        if obj.is_offer:
            return f'Offer: {obj.offer_title}'
        
        if obj.message:
            max_length = 50
            if len(obj.message) > max_length:
                return f'{obj.message[:max_length]}...'
            return obj.message
        
        return '-'
    
    @admin.display(description='Read By')
    def read_count(self, obj):
        """Display read count."""
        count = obj.read_by.count()
        return f'{count} user(s)'


@admin.register(MessageReadStatus)
class MessageReadStatusAdmin(admin.ModelAdmin):
    """Admin interface for message read statuses."""
    
    list_display = ('id', 'message_link', 'reader', 'read_at')
    
    list_filter = ('read_at',)
    
    search_fields = (
        'user__username',
        'guest_session_key',
        'message__id',
    )
    
    readonly_fields = ('message', 'user', 'guest_session_key', 'read_at')
    
    raw_id_fields = ('message', 'user')
    
    def has_add_permission(self, request):
        return False
    
    @admin.display(description='Message')
    def message_link(self, obj):
        """Display link to message."""
        url = reverse('admin:chat_chatmessage_change', args=[obj.message_id])
        return format_html('<a href="{}">{}</a>', url, obj.message_id)
    
    @admin.display(description='Reader')
    def reader(self, obj):
        """Display reader information."""
        if obj.user:
            return obj.user.username
        if obj.guest_session_key:
            return f'Guest ({obj.guest_session_key[:8]}...)'
        return 'Unknown'


@admin.register(GuestSession)
class GuestSessionAdmin(admin.ModelAdmin):
    """Admin interface for guest sessions."""

    list_display = (
        'display_name',
        'display_number',
        'session_key_short',
        'status_badge',
        'thread_count',
        'message_count',
        'first_seen',
        'last_activity',
        'conversion_info',
    )

    list_filter = (
        'is_active',
        ('converted_to_user', admin.EmptyFieldListFilter),
        'first_seen',
        'last_seen',
    )

    search_fields = (
        'session_key',
        'display_name',
        'display_number',
        'ip_address',
        'converted_to_user__username',
        'converted_to_user__email',
    )

    readonly_fields = (
        'session_key',
        'display_name',
        'display_number',
        'first_seen',
        'last_seen',
        'conversion_date',
        'session_age_display',
        'days_inactive',
        'related_threads',
        'related_messages',
    )

    autocomplete_fields = ['converted_to_user']

    fieldsets = (
        ('Guest Information', {
            'fields': ('display_name', 'display_number', 'session_key')
        }),
        ('Activity', {
            'fields': (
                'first_seen',
                'last_seen',
                'session_age_display',
                'days_inactive',
                'is_active',
            )
        }),
        ('Conversion', {
            'fields': ('converted_to_user', 'conversion_date'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('user_agent', 'ip_address', 'referrer'),
            'classes': ('collapse',)
        }),
        ('Related Data', {
            'fields': ('related_threads', 'related_messages'),
            'classes': ('collapse',)
        }),
    )

    actions = ['deactivate_sessions', 'mark_as_inactive_if_old']

    def get_queryset(self, request):
        """Optimize queryset with annotations."""
        qs = super().get_queryset(request)
        return qs.select_related('converted_to_user').annotate(
            message_cnt=Count('messages', distinct=True),
        )

    @admin.display(description='Session')
    def session_key_short(self, obj):
        """Display shortened session key."""
        return f"{obj.session_key[:16]}..." if len(obj.session_key) > 16 else obj.session_key

    @admin.display(description='Status')
    def status_badge(self, obj):
        """Display status with color badge."""
        if obj.is_converted:
            return format_html(
                '<span style="background-color: #28a745; color: white; padding: 3px 8px; border-radius: 3px;">Converted</span>'
            )
        elif obj.is_active:
            return format_html(
                '<span style="background-color: #007bff; color: white; padding: 3px 8px; border-radius: 3px;">Active</span>'
            )
        else:
            return format_html(
                '<span style="background-color: #6c757d; color: white; padding: 3px 8px; border-radius: 3px;">Inactive</span>'
            )

    @admin.display(description='Threads')
    def thread_count(self, obj):
        """Display number of related threads."""
        from .models import ChatThread
        count = ChatThread.objects.filter(guest_session_key=obj.session_key).count()
        if count > 0:
            return format_html('<strong>{}</strong>', count)
        return count

    @admin.display(description='Messages')
    def message_count(self, obj):
        """Display number of messages sent."""
        count = obj.message_cnt
        if count > 0:
            return format_html('<strong>{}</strong>', count)
        return count

    @admin.display(description='Last Activity', ordering='last_seen')
    def last_activity(self, obj):
        """Display last activity time."""
        delta = timezone.now() - obj.last_seen
        if delta < timedelta(hours=1):
            return format_html('<span style="color: green;">{}m ago</span>', int(delta.total_seconds() / 60))
        elif delta < timedelta(days=1):
            return format_html('<span style="color: orange;">{}h ago</span>', int(delta.total_seconds() / 3600))
        else:
            return format_html('<span style="color: red;">{} days ago</span>', delta.days)

    @admin.display(description='Conversion')
    def conversion_info(self, obj):
        """Display conversion information."""
        if obj.converted_to_user:
            url = reverse('admin:user_module_user_change', args=[obj.converted_to_user.pk])
            return format_html('<a href="{}">{}</a>', url, obj.converted_to_user.username)
        return '-'

    @admin.display(description='Session Age')
    def session_age_display(self, obj):
        """Display how long the session has existed."""
        age = obj.session_age
        if age < timedelta(hours=1):
            return f"{int(age.total_seconds() / 60)} minutes"
        elif age < timedelta(days=1):
            return f"{int(age.total_seconds() / 3600)} hours"
        else:
            return f"{age.days} days"

    @admin.display(description='Days Inactive')
    def days_inactive(self, obj):
        """Display days since last activity."""
        days = obj.days_since_last_activity
        if days == 0:
            return "Active today"
        elif days == 1:
            return "1 day"
        else:
            return f"{days} days"

    @admin.display(description='Related Threads')
    def related_threads(self, obj):
        """Display links to related threads."""
        from .models import ChatThread
        threads = ChatThread.objects.filter(guest_session_key=obj.session_key)[:5]
        if not threads:
            return "No threads"

        links = []
        for thread in threads:
            url = reverse('admin:chat_chatthread_change', args=[thread.pk])
            links.append(format_html('<a href="{}">Thread #{}</a>', url, thread.pk))

        result = format_html('<br>'.join(links))
        if threads.count() > 5:
            result += format_html('<br><em>... and {} more</em>', threads.count() - 5)
        return result

    @admin.display(description='Related Messages')
    def related_messages(self, obj):
        """Display count of related messages."""
        count = obj.messages.count()
        return f"{count} message(s)"

    @admin.action(description='Deactivate selected sessions')
    def deactivate_sessions(self, request, queryset):
        """Deactivate selected guest sessions."""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} session(s) deactivated.')

    @admin.action(description='Mark as inactive if older than 30 days')
    def mark_as_inactive_if_old(self, request, queryset):
        """Mark sessions as inactive if they haven't been active in 30 days."""
        threshold = timezone.now() - timedelta(days=30)
        updated = queryset.filter(last_seen__lt=threshold).update(is_active=False)
        self.message_user(request, f'{updated} old session(s) marked as inactive.')


@admin.register(GuestSessionCounter)
class GuestSessionCounterAdmin(admin.ModelAdmin):
    """Admin interface for guest session counter."""

    list_display = ('id', 'last_id')
    readonly_fields = ('last_id',)

    def has_add_permission(self, request):
        # Only allow one counter instance
        return not GuestSessionCounter.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ChatAttachment)
class ChatAttachmentAdmin(admin.ModelAdmin):
    """Admin interface for chat attachments."""
    
    list_display = (
        'id',
        'name',
        'message_link',
        'file_type',
        'file_size',
        'uploaded_by',
        'uploaded_at',
        'status',
    )
    
    list_filter = (
        'mime_type',
        'uploaded_at',
    )
    
    search_fields = (
        'name',
        'uploaded_by__username',
        'message__id',
    )
    
    readonly_fields = (
        'id',
        'file_url',
        'uploaded_at',
        'size_kb',
        'size_mb',
        'is_linked',
    )
    
    raw_id_fields = ('message', 'uploaded_by')
    
    fieldsets = (
        ('File Info', {
            'fields': ('id', 'name', 'file_url', 'mime_type')
        }),
        ('Size', {
            'fields': ('size', 'size_kb', 'size_mb')
        }),
        ('Metadata', {
            'fields': ('message', 'uploaded_by', 'uploaded_at', 'is_linked')
        }),
    )
    
    @admin.display(description='Message')
    def message_link(self, obj):
        """Display link to message."""
        if obj.message_id:
            url = reverse('admin:chat_chatmessage_change', args=[obj.message_id])
            return format_html('<a href="{}">{}</a>', url, obj.message_id)
        return format_html('<span style="color: orange;">Unlinked</span>')
    
    @admin.display(description='Type')
    def file_type(self, obj):
        """Display file type."""
        return obj.mime_type or 'Unknown'
    
    @admin.display(description='Size')
    def file_size(self, obj):
        """Display file size."""
        if obj.size_mb:
            return f'{obj.size_mb} MB'
        if obj.size_kb:
            return f'{obj.size_kb} KB'
        if obj.size:
            return f'{obj.size} bytes'
        return 'Unknown'
    
    @admin.display(description='Status')
    def status(self, obj):
        """Display attachment status."""
        if obj.is_linked:
            return format_html('<span style="color: green;">✓ Linked</span>')
        return format_html('<span style="color: orange;">⚠ Unlinked</span>')