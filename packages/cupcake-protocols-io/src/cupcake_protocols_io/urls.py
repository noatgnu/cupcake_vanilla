"""URL configuration of the protocols.io app."""

from django.urls import include, path

from rest_framework.routers import DefaultRouter

from cupcake_protocols_io.views import (
    ProtocolsIOAccountViewSet,
    ProtocolsIOBrowseViewSet,
    ProtocolsIOProtocolViewSet,
    ProtocolsIOSessionViewSet,
)

app_name = "protocols_io"

router = DefaultRouter()
router.register("protocols-io/account", ProtocolsIOAccountViewSet, basename="account")
router.register("protocols-io/browse", ProtocolsIOBrowseViewSet, basename="browse")
router.register("protocols-io/protocols", ProtocolsIOProtocolViewSet, basename="protocol")
router.register("protocols-io/sessions", ProtocolsIOSessionViewSet, basename="session")

urlpatterns = [
    path("", include(router.urls)),
]
