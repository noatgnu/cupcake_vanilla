"""
CUPCAKE Red Velvet (CCRV) URL Configuration.

REST API endpoints for project and protocol management.
"""

from django.urls import include, path

from rest_framework.routers import DefaultRouter

from .viewsets import (
    InstrumentUsageSessionAnnotationViewSet,
    ProjectViewSet,
    ProtocolModelViewSet,
    ProtocolRatingViewSet,
    ProtocolReagentViewSet,
    ProtocolSectionViewSet,
    ProtocolStepViewSet,
    RemoteHostViewSet,
    SessionAnnotationFolderViewSet,
    SessionAnnotationViewSet,
    SessionViewSet,
    StepAnnotationViewSet,
    StepReagentViewSet,
    StepVariationViewSet,
    TimeKeeperViewSet,
)

app_name = "ccrv"

router = DefaultRouter()
router.register("projects", ProjectViewSet, basename="project")
router.register("protocols", ProtocolModelViewSet, basename="protocolmodel")
router.register("sessions", SessionViewSet, basename="session")
router.register("session-annotations", SessionAnnotationViewSet, basename="sessionannotation")
router.register("ratings", ProtocolRatingViewSet, basename="protocolrating")
router.register("sections", ProtocolSectionViewSet, basename="protocolsection")
router.register("steps", ProtocolStepViewSet, basename="protocolstep")
router.register("remote-hosts", RemoteHostViewSet, basename="remotehost")
router.register("protocol-reagents", ProtocolReagentViewSet, basename="protocolreagent")
router.register("step-reagents", StepReagentViewSet, basename="stepreagent")
router.register("step-variations", StepVariationViewSet, basename="stepvariation")
router.register("time-keepers", TimeKeeperViewSet, basename="timekeeper")
router.register("step-annotations", StepAnnotationViewSet, basename="stepannotation")
router.register("session-annotation-folders", SessionAnnotationFolderViewSet, basename="sessionannotationfolder")
router.register(
    "instrument-usage-session-annotations",
    InstrumentUsageSessionAnnotationViewSet,
    basename="instrumentusagesessionannotation",
)

urlpatterns = [
    path("", include(router.urls)),
]
