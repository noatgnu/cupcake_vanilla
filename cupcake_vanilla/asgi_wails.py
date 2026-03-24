"""
ASGI config for cupcake_vanilla project in Wails environment with WebSocket support.

This configuration allows wails:// and localhost origins for Wails applications.
"""

import os

from django.core.asgi import get_asgi_application

from channels.routing import ProtocolTypeRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cupcake_vanilla.settings_wails")

django_asgi_app = get_asgi_application()

from ccc.websocket_routing import create_websocket_router
from ccv.middleware import JWTAuthMiddleware
from cupcake_vanilla.settings_wails import wails_websocket_origin_validator

websocket_router = create_websocket_router(auto_discover=True, raise_on_conflict=False)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": wails_websocket_origin_validator(JWTAuthMiddleware(websocket_router)),
    }
)
