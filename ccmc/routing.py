"""
WebSocket URL routing for CCMC (Mint Chocolate) communication system.
"""

from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("communications/", consumers.CommunicationConsumer.as_asgi()),
    path("webrtc/<uuid:session_id>/", consumers.WebRTCSignalConsumer.as_asgi()),
]
