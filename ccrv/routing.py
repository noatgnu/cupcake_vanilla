"""
WebSocket URL routing for CCRV module.

Only module-specific routes. General notifications use CCC's core routes.
"""

from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("timekeepers/", consumers.TimeKeeperConsumer.as_asgi()),
]
