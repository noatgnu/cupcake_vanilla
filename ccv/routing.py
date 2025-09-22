"""
WebSocket URL routing for CUPCAKE Vanilla.
"""

from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("notifications/", consumers.NotificationConsumer.as_asgi()),
    path("admin/", consumers.AdminNotificationConsumer.as_asgi()),
]
