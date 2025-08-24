"""
CUPCAKE Core (CCC) URL Configuration.

URL patterns for user management, lab groups, and site administration functionality.
"""

from django.urls import include, path

from rest_framework.routers import DefaultRouter

from .views import LabGroupInvitationViewSet, LabGroupViewSet, SiteConfigViewSet, UserManagementViewSet

app_name = "ccc"

# Create router and register CCC ViewSets
router = DefaultRouter()
router.register(r"users", UserManagementViewSet, basename="users")
router.register(r"lab-groups", LabGroupViewSet, basename="labgroup")
router.register(r"site-config", SiteConfigViewSet, basename="siteconfig")
router.register(r"lab-group-invitations", LabGroupInvitationViewSet, basename="labgroupinvitation")

urlpatterns = [
    # DRF ViewSet endpoints (api/v1/ prefix comes from main urls.py)
    path("", include(router.urls)),
]
