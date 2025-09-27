"""
ASGI config for cupcake_vanilla project in Electron environment with WebSocket support.

This configuration allows file:// origins for Electron applications.
"""

import os

from django.core.asgi import get_asgi_application

from channels.routing import ProtocolTypeRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cupcake_vanilla.settings_electron")

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

from ccc.websocket_routing import create_websocket_router
from ccv.middleware import JWTAuthMiddleware
from cupcake_vanilla.settings_electron import electron_websocket_origin_validator

# Create WebSocket router with automatic pattern discovery and conflict detection
websocket_router = create_websocket_router(
    auto_discover=True, raise_on_conflict=False  # Don't raise on conflicts for debugging
)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": electron_websocket_origin_validator(JWTAuthMiddleware(websocket_router)),
    }
)
