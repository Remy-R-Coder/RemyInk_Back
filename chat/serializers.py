from typing import Optional, Any
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db import transaction

from .models import (
    ChatThread,
    ChatMessage,
    MessageReadStatus,
    ChatAttachment,
)
from .services import GuestNameService
from .constants import MAX_ATTACHMENT_SIZE, ALLOWED_ATTACHMENT_TYPES

User = get_user_model()


class MessageReadStatusSerializer(serializers.ModelSerializer):
    
    user = serializers.CharField(source='user.username', read_only=True)
    
    class Meta:
        model = MessageReadStatus
        fields = ['user', 'read_at']
        read_only_fields = ['user', 'read_at']


class ChatAttachmentSerializer(serializers.ModelSerializer):
    
    uploaded_by = serializers.CharField(
        source='uploaded_by.username',
        read_only=True,
        allow_null=True
    )
    size_kb = serializers.FloatField(read_only=True)
    size_mb = serializers.FloatField(read_only=True)
    is_linked = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = ChatAttachment
        fields = [
            'id', 'file_url', 'name', 'mime_type', 'size',
            'size_kb', 'size_mb', 'uploaded_by', 'uploaded_at', 'is_linked'
        ]
        read_only_fields = [
            'id', 'uploaded_by', 'uploaded_at', 'size_kb', 'size_mb', 'is_linked'
        ]


class ChatAttachmentUploadSerializer(serializers.Serializer):
    
    file = serializers.FileField()
    message_id = serializers.IntegerField(required=False, allow_null=True)
    
    def validate_file(self, value):
        if value.size > MAX_ATTACHMENT_SIZE:
            raise serializers.ValidationError(
                f"File size cannot exceed {MAX_ATTACHMENT_SIZE / (1024 * 1024)} MB"
            )
        if value.content_type not in ALLOWED_ATTACHMENT_TYPES:
            raise serializers.ValidationError(
                f"File type {value.content_type} is not allowed"
            )
        return value


class OfferSerializer(serializers.Serializer):
    
    id = serializers.IntegerField(read_only=True)
    title = serializers.CharField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    timeline = serializers.IntegerField(min_value=1)
    revisions = serializers.IntegerField(min_value=0, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    status = serializers.CharField(read_only=True)
    
    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than 0")
        return value

class ChatMessageSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(source='timestamp', format=None, read_only=True)
    sender_name = serializers.SerializerMethodField()
    sender_user_id = serializers.SerializerMethodField()
    sender_guest_key = serializers.SerializerMethodField()
    offer = serializers.SerializerMethodField()
    message = serializers.CharField(
        required=False, 
        allow_blank=True, 
        allow_null=True
    )

    offer_title = serializers.CharField(required=False)
    offer_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    offer_timeline = serializers.IntegerField(required=False)
    offer_revisions = serializers.IntegerField(required=False, min_value=0)
    offer_description = serializers.CharField(required=False, allow_blank=True)

    attachments = ChatAttachmentSerializer(many=True, read_only=True)
    attachment_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        write_only=True,
        required=False,
        queryset=ChatAttachment.objects.all()
    )

    class Meta:
        model = ChatMessage
        fields = [
            'id', 'thread', 'message', 'created_at', 'updated_at',
            'is_offer', 'sender_name', 'sender_user_id', 'sender_guest_key',
            'offer', 'offer_title', 'offer_price', 'offer_timeline', 'offer_revisions', 'offer_description',
            'attachments', 'attachment_ids'
        ]
        read_only_fields = [
            'id', 'thread', 'created_at', 'updated_at', 'sender_name', 'sender_user_id', 'sender_guest_key'
        ]


    def validate(self, attrs):
        # CHANGE 2: Content Validation Logic
        message_text = attrs.get('message')
        is_offer = attrs.get('is_offer', False)
        attachment_ids = attrs.get('attachment_ids', [])

        # Logic: A message is valid IF it has text OR it is an offer OR it has attachments
        if not message_text and not is_offer and not attachment_ids:
            raise serializers.ValidationError(
                "Cannot send an empty message. Provide text, an offer, or an attachment."
            )
        
        if attachment_ids:
            # Get the thread from context (passed by ViewSet)
            thread_id = self.context.get('view').kwargs.get('thread_pk')
            
            # Ensure these attachments aren't already linked to another message
            # and (ideally) belong to this thread or were uploaded by this user
            for attachment in attachment_ids:
                if attachment.message_id is not None:
                    raise serializers.ValidationError(
                        f"Attachment {attachment.id} is already linked to another message."
                    )
                # SECURITY ADDITION: Ensure attachment belongs to this thread
                # This assumes your ChatAttachment model has a 'thread' field
                if attachment.thread_id and str(attachment.thread_id) != str(thread_id):
                     raise serializers.ValidationError(
                        f"Attachment {attachment.id} does not belong to this conversation."
                    )

        if attrs.get("is_offer"):
            missing = [
                f for f in ("offer_title", "offer_price", "offer_timeline")
                if not attrs.get(f)
            ]
            if missing:
                raise serializers.ValidationError(
                    f"Offer messages require: {', '.join(missing)}"
                )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        attachment_ids = validated_data.pop('attachment_ids', [])
        
        message = ChatMessage.objects.create(**validated_data)
        
        if attachment_ids:
            
            for attachment in attachment_ids:
                attachment.message = message
                attachment.thread = message.thread 
                attachment.save(update_fields=['message', 'thread'])
            
        return message

    def get_sender_name(self, obj: ChatMessage) -> str:
        if obj.sender:
            return obj.sender.username
        if obj.thread.guest_session_key:
            return GuestNameService.get_guest_display_name(obj.thread.guest_session_key)
        return "Unknown"

    def get_sender_user_id(self, obj: ChatMessage) -> Optional[str]:
        return obj.sender.id if obj.sender else None

    def get_sender_guest_key(self, obj: ChatMessage) -> Optional[str]:
        return None if obj.sender else obj.thread.guest_session_key

    def get_offer(self, obj: ChatMessage) -> Optional[dict[str, Any]]:
        if obj.is_offer:
            offer_data = {
                "id": obj.id,
                "title": obj.offer_title,
                "price": obj.offer_price,
                "currency": "USD",  # Add this line explicitly
                "timeline": obj.offer_timeline,
                "revisions": obj.offer_revisions,
                "description": obj.offer_description,
                "status": obj.offer_status
            }

            # Include attachments if any
            if obj.attachments.exists():
                offer_data['attachments'] = ChatAttachmentSerializer(
                    obj.attachments.all(),
                    many=True
                ).data

            # Include created job info if offer was accepted
            if obj.created_job:
                offer_data['created_job'] = {
                    'id': str(obj.created_job.id),
                    'status': obj.created_job.status,
                    'status_display': obj.created_job.get_status_display(),
                    'payment_required': obj.created_job.status in ['PROVISIONAL', 'PENDING_PAYMENT', 'PAYMENT_FAILED']
                }

            return offer_data
        return None


class ChatThreadListSerializer(serializers.ModelSerializer):

    freelancer_username = serializers.CharField(source='freelancer.username', read_only=True)
    freelancer_id = serializers.UUIDField(source='freelancer.id', read_only=True) 
    client_username = serializers.CharField(source='client.username', read_only=True, allow_null=True)
    client_id = serializers.UUIDField(source='client.id', read_only=True, allow_null=True)
    other_party_name = serializers.SerializerMethodField()
    is_guest_thread = serializers.BooleanField(read_only=True)
    last_message_preview = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = ChatThread
        fields = [
            'id', 'freelancer_username', 'freelancer_id',
            'client_username', 'client_id', 'is_guest_thread',
            'other_party_name', 'last_message_preview', 'last_message', 'unread_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = fields
    
    def get_other_party_name(self, obj: ChatThread) -> str:
        request = self.context.get('request')
        if not request:
            return f"Chat {obj.id}"
        user = request.user
        session_key = self._get_session_key(request)
        is_freelancer = user.is_authenticated and user.pk == obj.freelancer_id
        is_client = user.is_authenticated and obj.client_id and user.pk == obj.client_id
        is_guest = not user.is_authenticated and obj.guest_session_key and str(session_key).strip() == str(obj.guest_session_key).strip()
        if is_freelancer:
            if obj.client:
                return obj.client.username
            if obj.guest_session_key:
                return GuestNameService.get_guest_display_name(obj.guest_session_key)
        if is_client or is_guest:
            return obj.freelancer.username
        return f"Chat {obj.id}"
    
    def get_last_message_preview(self, obj: ChatThread) -> str:
        if obj.last_message:
            max_length = 50
            return obj.last_message[:max_length] + "..." if len(obj.last_message) > max_length else obj.last_message
        return "No messages yet"

    def get_last_message(self, obj: ChatThread) -> dict:
        """Return the full last message object with all details"""
        last_msg = obj.messages.order_by('-timestamp').first()
        if last_msg:
            return {
                'id': last_msg.id,
                'message': last_msg.message,
                'created_at': last_msg.timestamp,
                'sender_username': last_msg.sender.username if last_msg.sender else 'Guest',
                'is_offer': last_msg.is_offer,
                'offer_title': last_msg.offer_title if last_msg.is_offer else None,
                'offer_currency': "USD", # Add this here as well
                'offer_status': last_msg.offer_status if last_msg.is_offer else None,
            }
        return None

    def get_unread_count(self, obj: ChatThread) -> int:
        request = self.context.get('request')
        if not request:
            return 0
        user = request.user
        session_key = self._get_session_key(request)
        if user.is_authenticated:
            return obj.messages.unread_by_user(user).count()
        if session_key and str(obj.guest_session_key).strip() == str(session_key).strip():
            from .models import MessageReadStatus
            
            return (
                obj.messages
                .filter(sender=obj.freelancer)
                .exclude(read_by__guest_session_key=session_key)
                .count()
            )
        return 0
    
    @staticmethod
    def _get_session_key(request) -> Optional[str]:
        return getattr(request.session, 'session_key', None) or request.query_params.get('session_key')


class ChatThreadDetailSerializer(ChatThreadListSerializer):
    
    messages = ChatMessageSerializer(many=True, read_only=True)
    participant_count = serializers.IntegerField(read_only=True)
    
    class Meta(ChatThreadListSerializer.Meta):
        fields = ChatThreadListSerializer.Meta.fields + ['messages', 'participant_count']


ChatThreadSerializer = ChatThreadDetailSerializer


class ChatThreadCreateSerializer(serializers.Serializer):
    other_user_username = serializers.CharField(max_length=150)
    
    def validate_other_user_username(self, value):
        try:
            User.objects.get(username=value)
        except User.DoesNotExist:
            raise serializers.ValidationError(f"User '{value}' does not exist")
        request = self.context.get('request')
        if request and request.user.username == value:
            raise serializers.ValidationError("Cannot create a chat with yourself")
        return value


class GuestThreadCreateSerializer(serializers.Serializer):
    freelancer_username = serializers.CharField(max_length=150)
    session_key = serializers.CharField(max_length=255, required=False, allow_blank=True)
    
    def validate_freelancer_username(self, value):
        try:
            user = User.objects.get(username=value)
        except User.DoesNotExist:
            raise serializers.ValidationError(f"Freelancer '{value}' does not exist")
        from user_module.models import Role
        if not (user.role == Role.FREELANCER or user.is_superuser):
            raise serializers.ValidationError(f"User '{value}' is not a freelancer")
        return value


class GuestThreadPreviewSerializer(serializers.ModelSerializer):
    """Serializer for previewing guest threads before linking"""
    freelancer_username = serializers.CharField(source='freelancer.username', read_only=True)
    message_count = serializers.SerializerMethodField()
    last_activity = serializers.DateTimeField(source='updated_at', read_only=True)
    has_pending_offers = serializers.SerializerMethodField()

    class Meta:
        model = ChatThread
        fields = [
            'id', 'freelancer_username', 'message_count',
            'last_activity', 'has_pending_offers', 'created_at'
        ]
        read_only_fields = fields

    def get_message_count(self, obj):
        return obj.messages.count()

    def get_has_pending_offers(self, obj):
        return obj.messages.filter(is_offer=True, offer_status='pending').exists()


class LinkGuestThreadsSerializer(serializers.Serializer):
    guest_session_key = serializers.CharField(max_length=255)
    thread_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
        help_text="Optional list of specific thread IDs to link. If not provided, all threads will be linked."
    )

    def validate_guest_session_key(self, value):
        if not ChatThread.objects.filter(guest_session_key=value).exists():
            raise serializers.ValidationError("No threads found for this session key")
        return value

    def validate_thread_ids(self, value):
        if value:
            # Ensure all thread IDs exist
            existing_ids = set(ChatThread.objects.filter(id__in=value).values_list('id', flat=True))
            requested_ids = set(value)
            missing_ids = requested_ids - existing_ids
            if missing_ids:
                raise serializers.ValidationError(
                    f"Thread IDs not found: {', '.join(map(str, missing_ids))}"
                )
        return value

    def validate(self, attrs):
        guest_session_key = attrs.get('guest_session_key')
        thread_ids = attrs.get('thread_ids')

        if thread_ids:
            # Ensure requested threads belong to this session
            mismatched = ChatThread.objects.filter(
                id__in=thread_ids
            ).exclude(guest_session_key=guest_session_key).values_list('id', flat=True)

            if mismatched:
                raise serializers.ValidationError({
                    'thread_ids': f"Threads {', '.join(map(str, mismatched))} do not belong to this session"
                })

        return attrs
