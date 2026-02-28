import json
import logging
from typing import Optional, Dict, Any
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from .models import ChatThread, ChatMessage
from .services import (
    ChatThreadService,
    ChatMessageService,
    GuestNameService,
)
from .constants import WSMessageType, WSCloseCode, OfferStatus

logger = logging.getLogger(__name__)
User = get_user_model()


class GlobalChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for handling real-time chat.
    
    Supports both authenticated and guest users.
    Routes:
      - /ws/chat/thread/<thread_id>/     -> Join existing thread
      - /ws/chat/new/<freelancer_id>/    -> Create or join thread
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user: Optional[User] = None
        self.session = None
        self.session_key: Optional[str] = None
        self.is_authenticated: bool = False
        self.thread_id: Optional[str] = None
        self.freelancer_id: Optional[str] = None
        self.thread: Optional[ChatThread] = None
        self.room_group_name: Optional[str] = None
        self.is_thread_newly_created: bool = False
    
    async def connect(self):
        """Handle WebSocket connection."""
        # Initialize connection parameters
        await self._initialize_connection()
        
        # Resolve thread
        thread_resolved = await self._resolve_thread()
        if not thread_resolved:
            return
        
        # Verify access permissions
        has_access = await self._verify_access()
        if not has_access:
            return
        
        # Join channel group
        await self._join_channel_group()
        
        # Accept connection
        await self.accept()
        
        # Send initial data
        await self._send_connection_data()
        
        logger.info(
            f"WebSocket connected: Thread={self.thread.id}, "
            f"User={self.user.username if self.user else f'Guest:{self.session_key[:8]}...'}"
        )
    
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if self.room_group_name:
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
            
            logger.info(
                f"WebSocket disconnected: Room={self.room_group_name}, "
                f"Code={close_code}"
            )
    
    async def receive(self, text_data=None, bytes_data=None):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data or '{}')
        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
            return await self._send_error("Invalid JSON format")
        
        msg_type = data.get('type')
        
        if not self.thread:
            return await self._send_error("No active thread connection")
        
        # Route message to appropriate handler
        handlers = {
            WSMessageType.CHAT_MESSAGE: self._handle_chat_message,
            WSMessageType.OFFER: self._handle_offer_create,
            WSMessageType.OFFER_DECISION: self._handle_offer_decision,
            WSMessageType.TYPING: self._handle_typing,
        }
        
        handler = handlers.get(msg_type)
        if handler:
            await handler(data)
        else:
            logger.warning(f"Unknown message type: {msg_type}")
            await self._send_error(f"Unknown message type: {msg_type}")

    async def _initialize_connection(self):
        """Initialize connection parameters from scope."""
        self.user = self.scope.get('user')
        self.session = self.scope.get('session')
        self.is_authenticated = (
            self.user and
            getattr(self.user, 'is_authenticated', False)
        )
        
        # Extract guest session key from query params
        query_params = parse_qs(self.scope['query_string'].decode())
        url_session_key = query_params.get('session_key', [None])[0]
        
        # Ensure session exists
        if not getattr(self.session, 'session_key', None):
            await sync_to_async(self.session.save, thread_sensitive=True)()
        
        # Use URL key if provided, otherwise use session key
        self.session_key = url_session_key or self.session.session_key
        
        # Extract route parameters
        route_kwargs = self.scope['url_route']['kwargs']
        self.thread_id = route_kwargs.get('thread_id')
        self.freelancer_id = route_kwargs.get('freelancer_id')
        
        logger.info(
            f"WebSocket connection attempt: Thread={self.thread_id}, "
            f"Freelancer={self.freelancer_id}, Auth={self.is_authenticated}, "
            f"Session={self.session_key[:8] if self.session_key else 'None'}..."
        )
    
    async def _resolve_thread(self) -> bool:
        """Resolve the thread based on route parameters."""
        if self.thread_id:
            # Existing thread
            self.thread = await self._get_thread_by_id(self.thread_id)
            
            if not self.thread:
                logger.warning(f"Thread {self.thread_id} not found")
                await self.close(code=WSCloseCode.THREAD_NOT_FOUND)
                return False
        
        elif self.freelancer_id:
            # New thread - create or get
            if self.is_authenticated:
                self.thread, created = await self._get_or_create_authenticated_thread()
            else:
                self.thread, created = await self._get_or_create_guest_thread()
            
            self.is_thread_newly_created = created
            
            if self.thread:
                self.thread_id = str(self.thread.id)
            else:
                logger.error("Failed to create/retrieve thread")
                await self.close(code=WSCloseCode.THREAD_NOT_FOUND)
                return False
        
        else:
            logger.warning("No thread_id or freelancer_id provided")
            await self.close(code=WSCloseCode.MISSING_PARAMS)
            return False
        
        return True
    
    async def _verify_access(self) -> bool:
        """Verify user has access to the thread."""
        has_access = await database_sync_to_async(
            ChatThreadService.is_user_participant
        )(self.thread, self.user, self.session_key)
        
        if not has_access:
            logger.warning(
                f"Access denied: Thread={self.thread.id}, "
                f"User={self.user.username if self.user else f'Guest:{self.session_key[:8]}...'}"
            )
            await self.close(code=WSCloseCode.ACCESS_DENIED)
            return False
        
        return True
    
    async def _join_channel_group(self):
        """Join the channel group for this thread."""
        self.room_group_name = f'chat_{self.thread.id}'
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
    
    async def _send_connection_data(self):
        """Send initial data after successful connection."""
        # Send thread info
        thread_info = await self._serialize_thread_info(self.thread)
        await self.send(text_data=json.dumps({
            'type': WSMessageType.THREAD_JOINED,
            'thread': thread_info,
        }))
        
        # Notify if newly created
        if self.is_thread_newly_created:
            await self._broadcast_thread_created(self.thread)
        
        # Send message history
        messages = await self._get_messages(self.thread)
        serialized_messages = [
            await self._serialize_message(msg)
            for msg in messages
        ]
        
        await self.send(text_data=json.dumps({
            'type': WSMessageType.THREAD_HISTORY,
            'thread_id': str(self.thread.id),
            'messages': serialized_messages,
        }))
    
    async def _handle_chat_message(self, data: Dict[str, Any]):
        """Handle regular chat message."""
        message_text = data.get('message', '').strip()
        
        if not message_text:
            return await self._send_error("Message cannot be empty")
        
        # Create message
        message = await self._create_message(
            message=message_text,
            is_offer=False
        )
        
        # Broadcast to group
        serialized = await self._serialize_message(message)
        await self._broadcast({
            'type': WSMessageType.CHAT_MESSAGE,
            'thread_id': str(self.thread.id),
            'message': serialized,
        })
    
    async def _handle_offer_create(self, data: Dict[str, Any]):
        """Handle offer creation."""
        offer_data = data.get('offer', {})
        
        # Validate required fields
        title = offer_data.get('title', '').strip()
        price = offer_data.get('price')
        timeline = offer_data.get('timeline')
        description = offer_data.get('description', '').strip()
        
        if not all([title, price, timeline]):
            return await self._send_error(
                "Offer requires title, price, and timeline"
            )
        
        # Validate user is freelancer
        if self.user and not getattr(self.user, 'is_freelancer', False):
            return await self._send_error(
                "Only freelancers can send offers"
            )
        
        # Create offer message
        message = await self._create_message(
            message=title,
            is_offer=True,
            offer_data={
                'title': title,
                'price': float(price),
                'timeline': int(timeline),
                'description': description,
                'status': OfferStatus.PENDING,
            }
        )
        
        # Broadcast to group
        serialized = await self._serialize_message(message)
        await self._broadcast({
            'type': WSMessageType.OFFER,
            'thread_id': str(self.thread.id),
            'message': serialized,
        })
    
    async def _handle_offer_decision(self, data: Dict[str, Any]):
        """Handle offer acceptance/rejection."""
        offer_id = data.get('offer_id')
        decision = data.get('decision')
        
        if decision not in [OfferStatus.ACCEPTED, OfferStatus.REJECTED]:
            return await self._send_error("Invalid offer decision")
        
        # Update offer status
        offer = await self._update_offer_status(offer_id, decision)
        
        if not offer:
            return await self._send_error(
                "Offer not found or permission denied"
            )
        
        # Broadcast decision
        await self._broadcast({
            'type': WSMessageType.OFFER_DECISION,
            'thread_id': str(self.thread.id),
            'offer_id': str(offer.id),
            'decision': decision,
            'title': offer.offer_title,
        })
    
    async def _handle_typing(self, data: Dict[str, Any]):
        """Handle typing indicator."""
        is_typing = data.get('is_typing', False)
        
        sender_name = (
            self.user.username if self.user else
            GuestNameService.get_guest_display_name(self.session_key)
        )
        
        await self._broadcast({
            'type': WSMessageType.TYPING,
            'thread_id': str(self.thread.id),
            'sender_name': sender_name,
            'is_typing': is_typing,
        })
    
    @database_sync_to_async
    def _get_thread_by_id(self, thread_id: str) -> Optional[ChatThread]:
        """Get thread by ID."""
        return ChatThreadService.get_thread_by_id(int(thread_id))
    
    @database_sync_to_async
    def _get_or_create_authenticated_thread(self):
        """Get or create thread for authenticated user."""
        return ChatThreadService.get_or_create_authenticated_thread(
            self.user,
            self.freelancer_id
        )
    
    @database_sync_to_async
    def _get_or_create_guest_thread(self):
        """Get or create thread for guest user."""
        return ChatThreadService.get_or_create_guest_thread(
            self.session_key,
            self.freelancer_id
        )
    
    @database_sync_to_async
    def _get_messages(self, thread: ChatThread, limit: int = 100):
        """Get messages for the thread."""
        return ChatMessageService.get_thread_messages(thread, limit)
    
    @database_sync_to_async
    def _create_message(
        self,
        message: str,
        is_offer: bool = False,
        offer_data: Optional[Dict] = None
    ) -> ChatMessage:
        """Create a new message."""
        return ChatMessageService.create_message(
            thread=self.thread,
            sender=self.user if self.is_authenticated else None,
            message_text=message,
            is_offer=is_offer,
            offer_data=offer_data
        )
    
    @database_sync_to_async
    def _update_offer_status(
        self,
        offer_id: str,
        new_status: str
    ) -> Optional[ChatMessage]:
        """Update offer status."""
        try:
            offer = ChatMessage.objects.get(
                id=offer_id,
                thread=self.thread,
                is_offer=True
            )
        except ChatMessage.DoesNotExist:
            logger.warning(f"Offer {offer_id} not found")
            return None
        
        success = ChatMessageService.update_offer_status(
            offer,
            new_status,
            self.user if self.is_authenticated else None,
            self.session_key
        )
        
        return offer if success else None
    
    @database_sync_to_async
    def _serialize_thread_info(self, thread: ChatThread) -> Dict[str, Any]:
        """Serialize thread information."""
        display_name = (
            thread.freelancer.username if thread.freelancer else
            GuestNameService.get_guest_display_name(thread.guest_session_key)
        )
        
        return {
            'id': str(thread.id),
            'display_name': display_name,
            'freelancer_id': str(thread.freelancer_id) if thread.freelancer_id else None,
            'is_guest_thread': thread.is_guest_thread,
        }
    
    @database_sync_to_async
    def _serialize_message(self, message: ChatMessage) -> Dict[str, Any]:
        """Serialize a chat message."""
        sender_name = message.sender_display_name
        
        offer_data = None
        if message.is_offer:
            offer_data = {
                'id': str(message.id),
                'title': message.offer_title,
                'price': str(message.offer_price),
                'timeline': message.offer_timeline,
                'revisions': message.offer_revisions,
                'description': message.offer_description,
                'status': message.offer_status,
                'sender_name': sender_name,
            }
        
        return {
            'id': str(message.id),
            'thread_id': str(message.thread_id),
            'sender_name': sender_name,
            'message': message.message,
            'is_offer': message.is_offer,
            'offer': offer_data,
            'timestamp': message.timestamp.isoformat(),
        }
    
    async def _broadcast(self, payload: Dict[str, Any]):
        """Broadcast message to all clients in the thread."""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'websocket_message',
                'data': payload,
            }
        )
    
    async def _broadcast_thread_created(self, thread: ChatThread):
        """Broadcast thread creation event."""
        thread_info = await self._serialize_thread_info(thread)
        await self._broadcast({
            'type': WSMessageType.THREAD_CREATED,
            'thread': thread_info,
        })
    
    async def _send_error(self, message: str):
        """Send error message to the client."""
        logger.error(f"WebSocket error: {message}")
        await self.send(text_data=json.dumps({
            'type': WSMessageType.ERROR,
            'message': message,
        }))
    
    async def websocket_message(self, event: Dict[str, Any]):
        """Forward websocket message to the client."""
        await self.send(text_data=json.dumps(event['data']))
