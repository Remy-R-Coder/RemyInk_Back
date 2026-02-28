import logging
from typing import Optional

from channels.sessions import SessionMiddlewareStack
from channels.auth import AuthMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.models import Session
from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger(__name__)
User = get_user_model()


@database_sync_to_async
def get_user_for_scope(scope: dict) -> User:
    """
    Load the authenticated user from the session.
    
    Handles UUID primary keys and provides comprehensive error handling.
    
    Args:
        scope: The ASGI scope dictionary
    
    Returns:
        The authenticated User or AnonymousUser
    """
    session = scope.get('session')
    
    # No session available
    if not session or not session.session_key:
        logger.debug("No session found in scope")
        return AnonymousUser()
    
    try:
        # Retrieve session from database
        session_db = Session.objects.get(session_key=session.session_key)
        session_data = session_db.get_decoded()
        
        # Extract user ID from session
        user_id = session_data.get('_auth_user_id')
        
        if not user_id:
            logger.debug(
                f"No user ID in session {session.session_key[:8]}..."
            )
            return AnonymousUser()
        
        # Retrieve user by primary key (handles UUID)
        user = User.objects.get(pk=user_id)
        
        logger.debug(
            f"Successfully loaded user {user.username} from session"
        )
        
        return user
    
    except Session.DoesNotExist:
        logger.warning(
            f"Session {session.session_key[:8]}... not found in database"
        )
        return AnonymousUser()
    
    except ObjectDoesNotExist:
        logger.warning(
            f"User {user_id} not found in database"
        )
        return AnonymousUser()
    
    except Exception as e:
        logger.error(
            f"Unexpected error loading user from session: {type(e).__name__}: {e}",
            exc_info=True
        )
        return AnonymousUser()


class UUIDAuthMiddleware(AuthMiddleware):
    """
    Custom authentication middleware for WebSocket connections.
    
    Extends the default AuthMiddleware to handle UUID primary keys
    and provide better error handling.
    """
    
    async def resolve_scope(self, scope: dict):
        """
        Resolve the user for the given scope.
        
        Args:
            scope: The ASGI scope dictionary
        """
        scope['user'] = await get_user_for_scope(scope)
        
        # Log connection attempt
        user = scope['user']
        path = scope.get('path', 'unknown')
        
        if user and user.is_authenticated:
            logger.info(
                f"WebSocket auth: User {user.username} connecting to {path}"
            )
        else:
            session_key = scope.get('session', {}).session_key if scope.get('session') else None
            logger.info(
                f"WebSocket auth: Guest user (session={session_key[:8] if session_key else 'None'}...) "
                f"connecting to {path}"
            )


def UUIDAuthMiddlewareStack(inner):
    """
    Middleware stack that includes session handling and UUID-aware authentication.
    
    Usage:
        application = ProtocolTypeRouter({
            'websocket': UUIDAuthMiddlewareStack(
                URLRouter(websocket_urlpatterns)
            ),
        })
    
    Args:
        inner: The inner ASGI application
    
    Returns:
        The complete middleware stack
    """
    return SessionMiddlewareStack(UUIDAuthMiddleware(inner))