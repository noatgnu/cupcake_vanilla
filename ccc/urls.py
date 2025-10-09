"""
CUPCAKE Core (CCC) URL Configuration.

URL patterns for user management, lab groups, and site administration functionality.
"""

from django.urls import include, path

from rest_framework.routers import DefaultRouter

from .annotation_chunked_upload import AnnotationChunkedUploadView
from .viewsets import (
    AnnotationFolderViewSet,
    AnnotationViewSet,
    LabGroupInvitationViewSet,
    LabGroupPermissionViewSet,
    LabGroupViewSet,
    RemoteHostViewSet,
    ResourcePermissionViewSet,
    SiteConfigViewSet,
    UserManagementViewSet,
)

app_name = "ccc"

# Create router and register CCC ViewSets
router = DefaultRouter()
router.register(r"users", UserManagementViewSet, basename="users")
router.register(r"lab-groups", LabGroupViewSet, basename="labgroup")
router.register(r"site-config", SiteConfigViewSet, basename="siteconfig")
router.register(r"lab-group-invitations", LabGroupInvitationViewSet, basename="labgroupinvitation")
router.register(r"lab-group-permissions", LabGroupPermissionViewSet, basename="labgrouppermission")
router.register(r"annotation-folders", AnnotationFolderViewSet, basename="annotationfolder")
router.register(r"annotations", AnnotationViewSet, basename="annotation")
router.register(r"remote-hosts", RemoteHostViewSet, basename="remotehost")
router.register(r"resource-permissions", ResourcePermissionViewSet, basename="resourcepermission")

urlpatterns = [
    # DRF ViewSet endpoints (api/v1/ prefix comes from main urls.py)
    path("", include(router.urls)),
    # Chunked upload endpoints
    path("annotation-chunked-upload/", AnnotationChunkedUploadView.as_view(), name="annotation-chunked-upload"),
    path(
        "annotation-chunked-upload/<uuid:pk>/",
        AnnotationChunkedUploadView.as_view(),
        name="annotation-chunked-upload-detail",
    ),
]
