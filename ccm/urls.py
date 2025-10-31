"""
CUPCAKE Macaron (CCM) URL Configuration.

URL patterns for instrument and inventory management endpoints.
"""

from django.urls import include, path

from rest_framework.routers import DefaultRouter

from .annotation_chunked_upload import (
    InstrumentAnnotationChunkedUploadView,
    InstrumentJobAnnotationChunkedUploadView,
    MaintenanceLogAnnotationChunkedUploadView,
    StoredReagentAnnotationChunkedUploadView,
)
from .viewsets import (
    ExternalContactDetailsViewSet,
    ExternalContactViewSet,
    InstrumentAnnotationViewSet,
    InstrumentJobAnnotationViewSet,
    InstrumentJobViewSet,
    InstrumentPermissionViewSet,
    InstrumentUsageViewSet,
    InstrumentViewSet,
    MaintenanceLogAnnotationViewSet,
    MaintenanceLogViewSet,
    ReagentActionViewSet,
    ReagentSubscriptionViewSet,
    ReagentViewSet,
    StorageObjectViewSet,
    StoredReagentAnnotationViewSet,
    StoredReagentViewSet,
    SupportInformationViewSet,
)

app_name = "ccm"

# Router for API endpoints
router = DefaultRouter()

# Register viewsets
router.register(r"instruments", InstrumentViewSet, basename="instrument")
router.register(r"instrument-annotations", InstrumentAnnotationViewSet, basename="instrumentannotation")
router.register(r"instrument-jobs", InstrumentJobViewSet, basename="instrumentjob")
router.register(r"instrument-job-annotations", InstrumentJobAnnotationViewSet, basename="instrumentjobannotation")
router.register(r"instrument-usage", InstrumentUsageViewSet, basename="instrumentusage")
router.register(r"maintenance-logs", MaintenanceLogViewSet, basename="maintenancelog")
router.register(r"maintenance-log-annotations", MaintenanceLogAnnotationViewSet, basename="maintenancelogannotation")
router.register(r"storage-objects", StorageObjectViewSet, basename="storageobject")
router.register(r"reagents", ReagentViewSet, basename="reagent")
router.register(r"stored-reagents", StoredReagentViewSet, basename="storedreagent")
router.register(r"stored-reagent-annotations", StoredReagentAnnotationViewSet, basename="storedreagentannotation")
router.register(r"external-contacts", ExternalContactViewSet, basename="externalcontact")
router.register(r"external-contact-details", ExternalContactDetailsViewSet, basename="externalcontactdetails")
router.register(r"support-information", SupportInformationViewSet, basename="supportinformation")
router.register(r"reagent-subscriptions", ReagentSubscriptionViewSet, basename="reagentsubscription")
router.register(r"reagent-actions", ReagentActionViewSet, basename="reagentaction")
router.register(r"instrument-permissions", InstrumentPermissionViewSet, basename="instrumentpermission")

# URL patterns
urlpatterns = [
    # API endpoints
    path("", include(router.urls)),
    # Chunked upload endpoints
    path(
        "upload/instrument-annotation-chunks/",
        InstrumentAnnotationChunkedUploadView.as_view(),
        name="instrument-annotation-chunked-upload",
    ),
    path(
        "upload/instrument-annotation-chunks/<uuid:pk>/",
        InstrumentAnnotationChunkedUploadView.as_view(),
        name="instrument-annotation-chunked-upload-detail",
    ),
    path(
        "upload/instrument-job-annotation-chunks/",
        InstrumentJobAnnotationChunkedUploadView.as_view(),
        name="instrument-job-annotation-chunked-upload",
    ),
    path(
        "upload/instrument-job-annotation-chunks/<uuid:pk>/",
        InstrumentJobAnnotationChunkedUploadView.as_view(),
        name="instrument-job-annotation-chunked-upload-detail",
    ),
    path(
        "upload/stored-reagent-annotation-chunks/",
        StoredReagentAnnotationChunkedUploadView.as_view(),
        name="stored-reagent-annotation-chunked-upload",
    ),
    path(
        "upload/stored-reagent-annotation-chunks/<uuid:pk>/",
        StoredReagentAnnotationChunkedUploadView.as_view(),
        name="stored-reagent-annotation-chunked-upload-detail",
    ),
    path(
        "upload/maintenance-log-annotation-chunks/",
        MaintenanceLogAnnotationChunkedUploadView.as_view(),
        name="maintenance-log-annotation-chunked-upload",
    ),
    path(
        "upload/maintenance-log-annotation-chunks/<uuid:pk>/",
        MaintenanceLogAnnotationChunkedUploadView.as_view(),
        name="maintenance-log-annotation-chunked-upload-detail",
    ),
]
