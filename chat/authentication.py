from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import BaseAuthentication
import logging

logger = logging.getLogger(__name__)


class OptionalJWTAuthentication(JWTAuthentication):
    """
    JWT authentication that doesn't fail if token is invalid.
    Allows guest/unauthenticated access to continue.
    """
    def authenticate(self, request):
        try:
            result = super().authenticate(request)
            if result:
                logger.info(f"JWT auth successful for user: {result[0]}")
            else:
                logger.info("JWT auth returned None (no auth header present)")
            return result
        except Exception as e:
            logger.warning(f"JWT auth failed: {type(e).__name__}: {str(e)}")
            # If JWT authentication fails, return None to allow guest access
            return None
