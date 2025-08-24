"""
Custom WebSocket middleware for JWT authentication in Django Channels.
"""

import logging
from urllib.parse import parse_qs

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken

User = get_user_model()
logger = logging.getLogger(__name__)


@database_sync_to_async
def get_user_from_token(token_string):
    """
    Get user from JWT token.
    """
    try:
        # Validate the token
        UntypedToken(token_string)

        # Get user from token
        from rest_framework_simplejwt.authentication import JWTAuthentication

        jwt_auth = JWTAuthentication()
        validated_token = jwt_auth.get_validated_token(token_string)
        user = jwt_auth.get_user(validated_token)

        return user
    except (InvalidToken, TokenError, User.DoesNotExist) as e:
        logger.warning(f"WebSocket JWT authentication failed: {e}")
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """
    Custom JWT authentication middleware for WebSocket connections.

    Supports authentication via:
    1. Query parameter: ?token=<jwt_token>
    2. Subprotocol header: Sec-WebSocket-Protocol with token
    """

    async def __call__(self, scope, receive, send):
        # Only authenticate WebSocket connections
        if scope["type"] != "websocket":
            return await super().__call__(scope, receive, send)

        # Try to get token from query parameters first
        query_params = parse_qs(scope.get("query_string", b"").decode())
        token = query_params.get("token", [None])[0]

        # If no token in query params, try subprotocols
        if not token and "subprotocols" in scope:
            for subprotocol in scope["subprotocols"]:
                if subprotocol.startswith("access_token."):
                    token = subprotocol.replace("access_token.", "")
                    break

        # Authenticate user
        if token:
            scope["user"] = await get_user_from_token(token)
            if scope["user"].is_authenticated:
                logger.info(f"WebSocket authenticated user: {scope['user'].username}")
            else:
                logger.warning("WebSocket authentication failed - invalid token")
        else:
            scope["user"] = AnonymousUser()
            logger.warning("WebSocket authentication failed - no token provided")

        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    """
    Convenience function to create the full middleware stack with JWT auth.
    """
    return JWTAuthMiddleware(AuthMiddlewareStack(inner))
