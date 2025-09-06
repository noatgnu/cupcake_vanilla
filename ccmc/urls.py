"""
URL configuration for CUPCAKE Core Macaron Communication (CCMC) API.

Provides REST API endpoints for messaging, notifications, and communication functionality.
"""

from django.urls import include, path

from rest_framework.routers import DefaultRouter

from .viewsets import MessageThreadViewSet, MessageViewSet, NotificationViewSet, ThreadParticipantViewSet

app_name = "ccmc"

# Create API router
router = DefaultRouter()
router.register(r"notifications", NotificationViewSet, basename="notification")
router.register(r"threads", MessageThreadViewSet, basename="messagethread")
router.register(r"messages", MessageViewSet, basename="message")
router.register(r"participants", ThreadParticipantViewSet, basename="threadparticipant")

urlpatterns = [
    path("", include(router.urls)),
]
