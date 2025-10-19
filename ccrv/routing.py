"""
WebSocket URL routing for CCRV module.
"""

from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("timekeepers/", consumers.TimeKeeperConsumer.as_asgi()),
]
