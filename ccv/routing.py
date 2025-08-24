"""
WebSocket URL routing for CUPCAKE Vanilla.
"""

from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/notifications/", consumers.NotificationConsumer.as_asgi()),
    path("ws/admin/", consumers.AdminNotificationConsumer.as_asgi()),
]
