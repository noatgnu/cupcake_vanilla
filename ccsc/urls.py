"""
CUPCAKE Salted Caramel (CCSC) URL Configuration.

URL routing for billing and financial management API endpoints.
"""

from django.urls import include, path

from rest_framework.routers import DefaultRouter

from .viewsets import BillableItemTypeViewSet, BillingRecordViewSet, ServicePriceViewSet, ServiceTierViewSet

# Create router and register viewsets
router = DefaultRouter()
router.register(r"service-tiers", ServiceTierViewSet, basename="servicetier")
router.register(r"billable-item-types", BillableItemTypeViewSet, basename="billableitemtype")
router.register(r"service-prices", ServicePriceViewSet, basename="serviceprice")
router.register(r"billing-records", BillingRecordViewSet, basename="billingrecord")

# Wire up our API using automatic URL routing
urlpatterns = [
    path("", include(router.urls)),
]
