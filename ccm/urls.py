"""
CUPCAKE Macaron (CCM) URL Configuration.

URL patterns for instrument and inventory management endpoints.
"""

from django.urls import include, path

from rest_framework.routers import DefaultRouter

from .viewsets import (
    ExternalContactDetailsViewSet,
    ExternalContactViewSet,
    InstrumentJobViewSet,
    InstrumentUsageViewSet,
    InstrumentViewSet,
    MaintenanceLogViewSet,
    ReagentActionViewSet,
    ReagentSubscriptionViewSet,
    ReagentViewSet,
    StorageObjectViewSet,
    StoredReagentViewSet,
    SupportInformationViewSet,
)

app_name = "ccm"

# Router for API endpoints
router = DefaultRouter()

# Register viewsets
router.register(r"instruments", InstrumentViewSet, basename="instrument")
router.register(r"instrument-jobs", InstrumentJobViewSet, basename="instrumentjob")
router.register(r"instrument-usage", InstrumentUsageViewSet, basename="instrumentusage")
router.register(r"maintenance-logs", MaintenanceLogViewSet, basename="maintenancelog")
router.register(r"storage-objects", StorageObjectViewSet, basename="storageobject")
router.register(r"reagents", ReagentViewSet, basename="reagent")
router.register(r"stored-reagents", StoredReagentViewSet, basename="storedreagent")
router.register(r"external-contacts", ExternalContactViewSet, basename="externalcontact")
router.register(r"external-contact-details", ExternalContactDetailsViewSet, basename="externalcontactdetails")
router.register(r"support-information", SupportInformationViewSet, basename="supportinformation")
router.register(r"reagent-subscriptions", ReagentSubscriptionViewSet, basename="reagentsubscription")
router.register(r"reagent-actions", ReagentActionViewSet, basename="reagentaction")

# URL patterns
urlpatterns = [
    # API endpoints
    path("", include(router.urls)),
]
