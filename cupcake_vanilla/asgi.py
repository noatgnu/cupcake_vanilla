"""
ASGI config for cupcake_vanilla project with WebSocket support.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

from channels.routing import ProtocolTypeRouter
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cupcake_vanilla.settings")

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

from ccc.websocket_routing import create_websocket_router
from ccv.middleware import JWTAuthMiddleware

# Create WebSocket router with automatic pattern discovery and conflict detection
websocket_router = create_websocket_router(
    auto_discover=True, raise_on_conflict=False  # Don't raise on conflicts for debugging
)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(JWTAuthMiddleware(websocket_router)),
    }
)
