"""
WebSocket URL routing for CCMC (Mint Chocolate) communication system.
"""

from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("communications/", consumers.CommunicationConsumer.as_asgi()),
]
