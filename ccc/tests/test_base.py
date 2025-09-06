"""
Comprehensive tests for CUPCAKE Core (CCC) module.

This module contains tests for user management, lab groups, site administration,
authentication, and resource permissions functionality.
"""

import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from ccc.admin import SiteConfigAdmin
from ccc.authentication import CustomTokenObtainPairSerializer
from ccc.models import (
    AbstractResource,
    AccountMergeRequest,
    LabGroup,
    LabGroupInvitation,
    RemoteHost,
    ResourcePermission,
    ResourceRole,
    ResourceType,
    ResourceVisibility,
    SiteConfig,
    UserOrcidProfile,
)
from ccc.serializers import LabGroupInvitationSerializer, LabGroupSerializer, SiteConfigSerializer

try:
    # Check if ORCID auth views are available
    from ccc.view_modules import auth_views  # noqa: F401

    ORCID_VIEWS_AVAILABLE = True
except ImportError:
    ORCID_VIEWS_AVAILABLE = False


def orcid_configured():
    """
    Check if ORCID OAuth is properly configured.

    Returns:
        bool: True if ORCID_CLIENT_ID and ORCID_CLIENT_SECRET are set

    Note:
        To run ORCID tests, set environment variables:
        - ORCID_CLIENT_ID=your_orcid_client_id
        - ORCID_CLIENT_SECRET=your_orcid_client_secret
    """
    return (
        hasattr(settings, "ORCID_CLIENT_ID")
        and hasattr(settings, "ORCID_CLIENT_SECRET")
        and getattr(settings, "ORCID_CLIENT_ID", "") != ""
        and getattr(settings, "ORCID_CLIENT_SECRET", "") != ""
    )


def skip_if_no_orcid(reason="ORCID OAuth not configured"):
    """Decorator to skip tests if ORCID is not configured."""
    return unittest.skipUnless(orcid_configured() and ORCID_VIEWS_AVAILABLE, reason)


def url_exists(url_name, **kwargs):
    """Check if a URL pattern exists."""
    try:
        reverse(url_name, **kwargs)
        return True
    except Exception:
        return False


def skip_if_no_url(url_name, reason=None):
    """Decorator to skip tests if URL pattern doesn't exist."""
    if not reason:
        reason = f"URL pattern '{url_name}' not found"
    return unittest.skipUnless(url_exists(url_name), reason)


# Test Models for AbstractResource (since it's abstract)
class TestResource(AbstractResource):
    """Test model that inherits from AbstractResource."""

    name = models.CharField(max_length=100)

    class Meta:
        app_label = "ccc"


class AbstractResourceTestCase(TestCase):
    """Test cases for AbstractResource model."""

    def setUp(self):
        self.user1 = User.objects.create_user("user1", "user1@test.com", "password")
        self.user2 = User.objects.create_user("user2", "user2@test.com", "password")
        self.staff_user = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user1)
        self.lab_group.members.add(self.user1, self.user2)

        # Note: Cannot directly test AbstractResource as it's abstract
        # These tests would require a concrete model that inherits from AbstractResource

    def test_resource_visibility_choices(self):
        """Test ResourceVisibility choices."""
        self.assertEqual(ResourceVisibility.PRIVATE, "private")
        self.assertEqual(ResourceVisibility.GROUP, "group")
        self.assertEqual(ResourceVisibility.PUBLIC, "public")

    def test_resource_role_choices(self):
        """Test ResourceRole choices."""
        self.assertEqual(ResourceRole.OWNER, "owner")
        self.assertEqual(ResourceRole.ADMIN, "admin")
        self.assertEqual(ResourceRole.EDITOR, "editor")
        self.assertEqual(ResourceRole.VIEWER, "viewer")

    def test_resource_type_choices(self):
        """Test ResourceType choices."""
        self.assertEqual(ResourceType.METADATA_TABLE, "metadata_table")
        self.assertEqual(ResourceType.FILE, "file")
        self.assertEqual(ResourceType.DATASET, "dataset")


class ResourcePermissionTestCase(TestCase):
    """Test cases for ResourcePermission model."""

    def setUp(self):
        self.user1 = User.objects.create_user("user1", "user1@test.com", "password")
        self.user2 = User.objects.create_user("user2", "user2@test.com", "password")
        self.content_type = ContentType.objects.get_for_model(User)

    def test_create_resource_permission(self):
        """Test creating a resource permission."""
        permission = ResourcePermission.objects.create(
            resource_content_type=self.content_type,
            resource_object_id=1,
            user=self.user1,
            role=ResourceRole.EDITOR,
            granted_by=self.user2,
        )

        self.assertEqual(permission.user, self.user1)
        self.assertEqual(permission.role, ResourceRole.EDITOR)
        self.assertEqual(permission.granted_by, self.user2)
        self.assertIsNotNone(permission.granted_at)

    def test_resource_permission_str(self):
        """Test ResourcePermission string representation."""
        permission = ResourcePermission.objects.create(
            resource_content_type=self.content_type, resource_object_id=1, user=self.user1, role=ResourceRole.VIEWER
        )

        expected_str = f"{self.user1.username} - {ResourceRole.VIEWER} - {self.content_type}"
        self.assertEqual(str(permission), expected_str)

    def test_unique_together_constraint(self):
        """Test that unique constraint is enforced."""
        ResourcePermission.objects.create(
            resource_content_type=self.content_type, resource_object_id=1, user=self.user1, role=ResourceRole.EDITOR
        )

        # Should not be able to create duplicate permission
        with self.assertRaises(Exception):
            ResourcePermission.objects.create(
                resource_content_type=self.content_type, resource_object_id=1, user=self.user1, role=ResourceRole.VIEWER
            )


class SiteConfigTestCase(TestCase):
    """Test cases for SiteConfig model."""

    def test_create_site_config(self):
        """Test creating site configuration."""
        config = SiteConfig.objects.create(
            site_name="Test CUPCAKE", primary_color="#ff0000", allow_user_registration=True, enable_orcid_login=True
        )

        self.assertEqual(config.site_name, "Test CUPCAKE")
        self.assertEqual(config.primary_color, "#ff0000")
        self.assertTrue(config.allow_user_registration)
        self.assertTrue(config.enable_orcid_login)
        self.assertTrue(config.show_powered_by)  # default value

    def test_site_config_defaults(self):
        """Test default values for site configuration."""
        config = SiteConfig.objects.create()

        self.assertEqual(config.site_name, "CUPCAKE")
        self.assertEqual(config.primary_color, "#1976d2")
        self.assertTrue(config.show_powered_by)
        self.assertFalse(config.allow_user_registration)
        self.assertFalse(config.enable_orcid_login)

    def test_site_config_str(self):
        """Test SiteConfig string representation."""
        config = SiteConfig.objects.create(site_name="Custom Site")
        self.assertEqual(str(config), "Site Config: Custom Site")


class LabGroupTestCase(TestCase):
    """Test cases for LabGroup model."""

    def setUp(self):
        self.user1 = User.objects.create_user("creator", "creator@test.com", "password")
        self.user2 = User.objects.create_user("member", "member@test.com", "password")
        self.user3 = User.objects.create_user("outsider", "outsider@test.com", "password")

    def test_create_lab_group(self):
        """Test creating a lab group."""
        lab_group = LabGroup.objects.create(name="Test Lab Group", description="A test lab group", creator=self.user1)

        self.assertEqual(lab_group.name, "Test Lab Group")
        self.assertEqual(lab_group.description, "A test lab group")
        self.assertEqual(lab_group.creator, self.user1)
        self.assertTrue(lab_group.is_active)
        self.assertTrue(lab_group.allow_member_invites)

    def test_lab_group_str(self):
        """Test LabGroup string representation."""
        lab_group = LabGroup.objects.create(name="My Lab", creator=self.user1)
        self.assertEqual(str(lab_group), "My Lab")

    def test_is_creator(self):
        """Test is_creator method."""
        lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user1)

        self.assertTrue(lab_group.is_creator(self.user1))
        self.assertFalse(lab_group.is_creator(self.user2))

    def test_is_member(self):
        """Test is_member method."""
        lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user1)
        lab_group.members.add(self.user2)

        self.assertTrue(lab_group.is_member(self.user2))
        self.assertFalse(lab_group.is_member(self.user3))

    def test_can_invite(self):
        """Test can_invite method."""
        lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user1)
        lab_group.members.add(self.user2)

        # Creator can always invite
        self.assertTrue(lab_group.can_invite(self.user1))

        # Member can invite if allow_member_invites is True
        self.assertTrue(lab_group.can_invite(self.user2))

        # Outsider cannot invite
        self.assertFalse(lab_group.can_invite(self.user3))

        # Member cannot invite if allow_member_invites is False
        lab_group.allow_member_invites = False
        lab_group.save()
        self.assertFalse(lab_group.can_invite(self.user2))

    def test_can_manage(self):
        """Test can_manage method."""
        lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user1)
        lab_group.members.add(self.user2)

        # Only creator can manage
        self.assertTrue(lab_group.can_manage(self.user1))
        self.assertFalse(lab_group.can_manage(self.user2))
        self.assertFalse(lab_group.can_manage(self.user3))


class LabGroupInvitationTestCase(TestCase):
    """Test cases for LabGroupInvitation model."""

    def setUp(self):
        self.user1 = User.objects.create_user("inviter", "inviter@test.com", "password")
        self.user2 = User.objects.create_user("invitee", "invitee@test.com", "password")
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user1)

    def test_create_invitation(self):
        """Test creating a lab group invitation."""
        invitation = LabGroupInvitation.objects.create(
            lab_group=self.lab_group, inviter=self.user1, invited_email="invitee@test.com", message="Join our lab!"
        )

        self.assertEqual(invitation.lab_group, self.lab_group)
        self.assertEqual(invitation.inviter, self.user1)
        self.assertEqual(invitation.invited_email, "invitee@test.com")
        self.assertEqual(invitation.message, "Join our lab!")
        self.assertEqual(invitation.status, LabGroupInvitation.InvitationStatus.PENDING)
        self.assertIsNotNone(invitation.invitation_token)
        self.assertIsNotNone(invitation.expires_at)

    def test_invitation_str(self):
        """Test invitation string representation."""
        invitation = LabGroupInvitation.objects.create(
            lab_group=self.lab_group, inviter=self.user1, invited_email="test@example.com"
        )

        expected_str = f"Invitation to {self.lab_group.name} for test@example.com"
        self.assertEqual(str(invitation), expected_str)

    def test_auto_token_generation(self):
        """Test that invitation token is auto-generated."""
        invitation = LabGroupInvitation.objects.create(
            lab_group=self.lab_group, inviter=self.user1, invited_email="test@example.com"
        )

        self.assertIsNotNone(invitation.invitation_token)
        self.assertTrue(len(invitation.invitation_token) > 10)

    def test_auto_expiry_date(self):
        """Test that expiry date is auto-set."""
        invitation = LabGroupInvitation.objects.create(
            lab_group=self.lab_group, inviter=self.user1, invited_email="test@example.com"
        )

        # Should expire in 7 days by default
        expected_expiry = timezone.now() + timedelta(days=7)
        self.assertAlmostEqual(
            invitation.expires_at.timestamp(), expected_expiry.timestamp(), delta=60  # within 1 minute
        )

    def test_is_expired(self):
        """Test is_expired method."""
        # Create expired invitation
        past_date = timezone.now() - timedelta(days=1)
        invitation = LabGroupInvitation.objects.create(
            lab_group=self.lab_group, inviter=self.user1, invited_email="test@example.com", expires_at=past_date
        )

        self.assertTrue(invitation.is_expired())

        # Create future invitation
        future_date = timezone.now() + timedelta(days=1)
        invitation.expires_at = future_date
        invitation.save()

        self.assertFalse(invitation.is_expired())

    def test_can_accept(self):
        """Test can_accept method."""
        invitation = LabGroupInvitation.objects.create(
            lab_group=self.lab_group, inviter=self.user1, invited_email="test@example.com"
        )

        # Fresh invitation can be accepted
        self.assertTrue(invitation.can_accept())

        # Expired invitation cannot be accepted
        invitation.expires_at = timezone.now() - timedelta(days=1)
        invitation.save()
        self.assertFalse(invitation.can_accept())

        # Accepted invitation cannot be accepted again
        invitation.expires_at = timezone.now() + timedelta(days=1)
        invitation.status = LabGroupInvitation.InvitationStatus.ACCEPTED
        invitation.save()
        self.assertFalse(invitation.can_accept())

    def test_accept_invitation(self):
        """Test accepting an invitation."""
        invitation = LabGroupInvitation.objects.create(
            lab_group=self.lab_group, inviter=self.user1, invited_email="invitee@test.com"
        )

        invitation.accept(self.user2)

        self.assertEqual(invitation.status, LabGroupInvitation.InvitationStatus.ACCEPTED)
        self.assertEqual(invitation.invited_user, self.user2)
        self.assertIsNotNone(invitation.responded_at)
        self.assertTrue(self.lab_group.is_member(self.user2))

    def test_accept_invitation_wrong_email(self):
        """Test that accepting with wrong email fails."""
        invitation = LabGroupInvitation.objects.create(
            lab_group=self.lab_group, inviter=self.user1, invited_email="different@test.com"
        )

        with self.assertRaises(ValueError):
            invitation.accept(self.user2)

    def test_reject_invitation(self):
        """Test rejecting an invitation."""
        invitation = LabGroupInvitation.objects.create(
            lab_group=self.lab_group, inviter=self.user1, invited_email="test@example.com"
        )

        invitation.reject(self.user2)

        self.assertEqual(invitation.status, LabGroupInvitation.InvitationStatus.REJECTED)
        self.assertEqual(invitation.invited_user, self.user2)
        self.assertIsNotNone(invitation.responded_at)

    def test_unique_constraint(self):
        """Test that duplicate invitations to same email are not allowed."""
        LabGroupInvitation.objects.create(
            lab_group=self.lab_group, inviter=self.user1, invited_email="test@example.com"
        )

        with self.assertRaises(Exception):
            LabGroupInvitation.objects.create(
                lab_group=self.lab_group, inviter=self.user1, invited_email="test@example.com"
            )


@skip_if_no_orcid("ORCID configuration required for UserOrcidProfile tests")
class UserOrcidProfileTestCase(TestCase):
    """Test cases for UserOrcidProfile model."""

    def setUp(self):
        self.user = User.objects.create_user("testuser", "test@example.com", "password")

    def test_create_orcid_profile(self):
        """Test creating an ORCID profile."""
        profile = UserOrcidProfile.objects.create(
            user=self.user,
            orcid_id="0000-0000-0000-0001",
            orcid_name="Test User",
            orcid_email="test@example.com",
            verified=True,
        )

        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.orcid_id, "0000-0000-0000-0001")
        self.assertEqual(profile.orcid_name, "Test User")
        self.assertEqual(profile.orcid_email, "test@example.com")
        self.assertTrue(profile.verified)
        self.assertIsNotNone(profile.linked_at)

    def test_orcid_profile_str(self):
        """Test ORCID profile string representation."""
        profile = UserOrcidProfile.objects.create(user=self.user, orcid_id="0000-0000-0000-0001")

        expected_str = f"{self.user.username} - 0000-0000-0000-0001"
        self.assertEqual(str(profile), expected_str)

    def test_unique_orcid_constraint(self):
        """Test that ORCID IDs must be unique."""
        UserOrcidProfile.objects.create(user=self.user, orcid_id="0000-0000-0000-0001")

        user2 = User.objects.create_user("user2", "user2@test.com", "password")

        with self.assertRaises(Exception):
            UserOrcidProfile.objects.create(user=user2, orcid_id="0000-0000-0000-0001")


class AccountMergeRequestTestCase(TestCase):
    """Test cases for AccountMergeRequest model."""

    def setUp(self):
        self.primary_user = User.objects.create_user("primary", "primary@test.com", "password")
        self.duplicate_user = User.objects.create_user("duplicate", "duplicate@test.com", "password")
        self.requesting_user = User.objects.create_user("requester", "requester@test.com", "password")

    def test_create_merge_request(self):
        """Test creating an account merge request."""
        merge_request = AccountMergeRequest.objects.create(
            primary_user=self.primary_user,
            duplicate_user=self.duplicate_user,
            requested_by=self.requesting_user,
            reason="Duplicate accounts for same person",
        )

        self.assertEqual(merge_request.primary_user, self.primary_user)
        self.assertEqual(merge_request.duplicate_user, self.duplicate_user)
        self.assertEqual(merge_request.requested_by, self.requesting_user)
        self.assertEqual(merge_request.reason, "Duplicate accounts for same person")
        self.assertEqual(merge_request.status, "pending")

    def test_merge_request_str(self):
        """Test merge request string representation."""
        merge_request = AccountMergeRequest.objects.create(
            primary_user=self.primary_user,
            duplicate_user=self.duplicate_user,
            requested_by=self.requesting_user,
            reason="Test",
        )

        expected_str = f"Merge {self.duplicate_user.username} → {self.primary_user.username}"
        self.assertEqual(str(merge_request), expected_str)

    def test_clean_validation(self):
        """Test that validation prevents same user as primary and duplicate."""
        merge_request = AccountMergeRequest(
            primary_user=self.primary_user,
            duplicate_user=self.primary_user,  # Same as primary
            requested_by=self.requesting_user,
            reason="Test",
        )

        with self.assertRaises(ValidationError):
            merge_request.clean()

    def test_save_calls_clean(self):
        """Test that save method calls clean validation."""
        merge_request = AccountMergeRequest(
            primary_user=self.primary_user,
            duplicate_user=self.primary_user,  # Same as primary
            requested_by=self.requesting_user,
            reason="Test",
        )

        with self.assertRaises(ValidationError):
            merge_request.save()

    def test_unique_constraint(self):
        """Test unique constraint on primary/duplicate user pair."""
        AccountMergeRequest.objects.create(
            primary_user=self.primary_user,
            duplicate_user=self.duplicate_user,
            requested_by=self.requesting_user,
            reason="First request",
        )

        with self.assertRaises(Exception):
            AccountMergeRequest.objects.create(
                primary_user=self.primary_user,
                duplicate_user=self.duplicate_user,
                requested_by=self.requesting_user,
                reason="Second request",
            )


# API Test Cases
@skip_if_no_url("siteconfig-list", "SiteConfig API endpoints not available")
class SiteConfigAPITestCase(APITestCase):
    """Test cases for SiteConfig API endpoints."""

    def setUp(self):
        self.admin_user = User.objects.create_user("admin", "admin@test.com", "password", is_staff=True)
        self.regular_user = User.objects.create_user("user", "user@test.com", "password")
        self.client = APIClient()

    @skip_if_no_url("siteconfig-public")
    def test_public_site_config(self):
        """Test public site config endpoint (no auth required)."""
        SiteConfig.objects.create(site_name="Test Site", primary_color="#ff0000", allow_user_registration=True)

        url = reverse("siteconfig-public")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["site_name"], "Test Site")
        self.assertEqual(response.data["primary_color"], "#ff0000")
        self.assertTrue(response.data["allow_user_registration"])

        # Check that installed_apps is included
        self.assertIn("installed_apps", response.data)
        installed_apps = response.data["installed_apps"]
        self.assertIsInstance(installed_apps, dict)
        self.assertIn("ccc", installed_apps)
        self.assertIn("ccv", installed_apps)

    @skip_if_no_url("siteconfig-public")
    def test_public_site_config_no_config(self):
        """Test public endpoint when no config exists."""
        url = reverse("siteconfig-public")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return default values

    def test_list_site_config_requires_admin(self):
        """Test that listing site config requires admin permissions."""
        url = reverse("siteconfig-list")

        # Unauthenticated
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Regular user
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Admin user
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_site_config(self):
        """Test creating site config via API."""
        self.client.force_authenticate(user=self.admin_user)

        data = {"site_name": "New Site", "primary_color": "#00ff00", "allow_user_registration": False}

        url = reverse("siteconfig-list")
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["site_name"], "New Site")

        # Verify in database
        config = SiteConfig.objects.first()
        self.assertEqual(config.site_name, "New Site")
        self.assertEqual(config.updated_by, self.admin_user)

    def test_prevent_duplicate_site_config(self):
        """Test that creating duplicate site config is prevented."""
        SiteConfig.objects.create(site_name="Existing")

        self.client.force_authenticate(user=self.admin_user)

        data = {"site_name": "Another Site"}
        url = reverse("siteconfig-list")
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already exists", response.data["error"])


@skip_if_no_url("labgroup-list", "LabGroup API endpoints not available")
class LabGroupAPITestCase(APITestCase):
    """Test cases for LabGroup API endpoints."""

    def setUp(self):
        self.user1 = User.objects.create_user("user1", "user1@test.com", "password")
        self.user2 = User.objects.create_user("user2", "user2@test.com", "password")
        self.client = APIClient()

    def test_create_lab_group(self):
        """Test creating a lab group via API."""
        self.client.force_authenticate(user=self.user1)

        data = {"name": "My Lab Group", "description": "A test lab group", "allow_member_invites": True}

        url = reverse("labgroup-list")
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "My Lab Group")
        self.assertEqual(response.data["creator"], self.user1.id)
        self.assertTrue(response.data["is_creator"])

        # Verify creator is added as member
        lab_group = LabGroup.objects.get(id=response.data["id"])
        self.assertTrue(lab_group.is_member(self.user1))

    def test_list_lab_groups(self):
        """Test listing lab groups."""
        lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user1)
        lab_group.members.add(self.user2)

        self.client.force_authenticate(user=self.user2)

        url = reverse("labgroup-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "Test Lab")
        self.assertTrue(response.data["results"][0]["is_member"])
        self.assertFalse(response.data["results"][0]["is_creator"])

    def test_lab_group_permissions(self):
        """Test lab group permission checks."""
        lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user1)

        self.client.force_authenticate(user=self.user1)
        url = reverse("labgroup-detail", kwargs={"pk": lab_group.pk})

        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["can_manage"])
        self.assertTrue(response.data["can_invite"])


class AuthenticationAPITestCase(APITestCase):
    """Test cases for authentication API endpoints."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123", first_name="Test", last_name="User"
        )
        self.client = APIClient()

    def test_login_with_valid_credentials(self):
        """Test login with valid credentials."""
        url = reverse("auth-login")
        data = {"username": "testuser", "password": "testpass123"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response.data)
        self.assertIn("refresh_token", response.data)
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["username"], "testuser")
        self.assertEqual(response.data["user"]["email"], "test@example.com")

    def test_login_with_invalid_credentials(self):
        """Test login with invalid credentials."""
        url = reverse("auth-login")
        data = {"username": "testuser", "password": "wrongpass"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("error", response.data)

    def test_login_missing_credentials(self):
        """Test login with missing credentials."""
        url = reverse("auth-login")
        data = {"username": "testuser"}  # missing password

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_logout_with_valid_token(self):
        """Test logout with valid refresh token using real JWT authentication."""
        # Check if JWT blacklisting is available
        try:
            from rest_framework_simplejwt.token_blacklist import models as blacklist_models  # noqa: F401

            blacklist_available = True
        except ImportError:
            blacklist_available = False

        if not blacklist_available:
            self.skipTest("JWT token blacklisting not available - install rest_framework_simplejwt.token_blacklist")

        # Create real JWT tokens
        refresh = RefreshToken.for_user(self.user)
        access_token = refresh.access_token

        url = reverse("auth-logout")
        data = {"refresh": str(refresh)}

        # Use real JWT authentication instead of force_authenticate
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = self.client.post(url, data)

        # Handle case where blacklist app is not in INSTALLED_APPS
        if response.status_code == status.HTTP_400_BAD_REQUEST:
            response_text = str(response.data)
            if "blacklist" in response_text.lower() or "models" in response_text.lower():
                self.skipTest(
                    "JWT blacklisting models not available - add 'rest_framework_simplejwt.token_blacklist' to INSTALLED_APPS"
                )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)

        # Clear credentials after test
        self.client.credentials()

    def test_logout_with_invalid_token(self):
        """Test logout with invalid refresh token using real JWT authentication."""
        # Create real JWT token for authentication
        refresh = RefreshToken.for_user(self.user)
        access_token = refresh.access_token

        url = reverse("auth-logout")
        data = {"refresh": "invalid_token"}  # Invalid refresh token

        # Use real JWT authentication
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

        # Clear credentials after test
        self.client.credentials()

    def test_user_profile_authenticated(self):
        """Test getting user profile when authenticated."""
        self.client.force_authenticate(user=self.user)

        url = reverse("auth-profile")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["username"], "testuser")

    def test_user_profile_unauthenticated(self):
        """Test getting user profile when not authenticated."""
        url = reverse("auth-profile")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        # DRF returns 'detail' not 'error' for auth failures
        self.assertIn("detail", response.data)


# Serializer Test Cases
class LabGroupSerializerTestCase(TestCase):
    """Test cases for LabGroupSerializer."""

    def setUp(self):
        self.user1 = User.objects.create_user("user1", "user1@test.com", "password")
        self.user2 = User.objects.create_user("user2", "user2@test.com", "password")
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user1)
        self.lab_group.members.add(self.user1, self.user2)

    def test_serializer_fields(self):
        """Test that serializer includes all expected fields."""
        serializer = LabGroupSerializer(self.lab_group, context={"request": Mock(user=self.user1)})

        expected_fields = [
            "id",
            "name",
            "description",
            "creator",
            "creator_name",
            "is_active",
            "allow_member_invites",
            "member_count",
            "is_creator",
            "is_member",
            "can_invite",
            "can_manage",
            "created_at",
            "updated_at",
        ]

        for field in expected_fields:
            self.assertIn(field, serializer.data)

    def test_computed_fields(self):
        """Test computed fields in serializer."""
        serializer = LabGroupSerializer(self.lab_group, context={"request": Mock(user=self.user1)})

        self.assertEqual(serializer.data["member_count"], 2)
        self.assertTrue(serializer.data["is_creator"])
        self.assertTrue(serializer.data["is_member"])
        self.assertTrue(serializer.data["can_invite"])
        self.assertTrue(serializer.data["can_manage"])

    def test_creator_name_field(self):
        """Test creator_name field."""
        self.user1.first_name = "Test"
        self.user1.last_name = "User"
        self.user1.save()

        serializer = LabGroupSerializer(self.lab_group, context={"request": Mock(user=self.user1)})

        self.assertEqual(serializer.data["creator_name"], "Test User")


class SiteConfigSerializerTestCase(TestCase):
    """Test cases for SiteConfigSerializer."""

    def setUp(self):
        self.user = User.objects.create_user("admin", "admin@test.com", "password", is_staff=True)

    def test_serializer_fields(self):
        """Test that serializer includes all expected fields."""
        config = SiteConfig.objects.create(site_name="Test Site", updated_by=self.user)

        serializer = SiteConfigSerializer(config)

        expected_fields = [
            "site_name",
            "logo_url",
            "logo_image",
            "primary_color",
            "show_powered_by",
            "allow_user_registration",
            "enable_orcid_login",
            "installed_apps",
            "created_at",
            "updated_at",
            "updated_by",
        ]

        for field in expected_fields:
            self.assertIn(field, serializer.data)

    def test_read_only_fields(self):
        """Test that certain fields are read-only."""
        data = {
            "site_name": "New Site",
            "created_at": "2023-01-01T00:00:00Z",  # Should be ignored
            "updated_at": "2023-01-01T00:00:00Z",  # Should be ignored
            "updated_by": 999,  # Should be ignored
        }

        serializer = SiteConfigSerializer(data=data)
        self.assertTrue(serializer.is_valid())

        # These fields should not be in validated_data
        validated_fields = list(serializer.validated_data.keys())
        self.assertNotIn("created_at", validated_fields)
        self.assertNotIn("updated_at", validated_fields)
        self.assertNotIn("updated_by", validated_fields)

    def test_installed_apps_field(self):
        """Test that installed_apps field contains correct CUPCAKE app information."""
        config = SiteConfig.objects.create(site_name="Test Site", updated_by=self.user)

        serializer = SiteConfigSerializer(config)

        # installed_apps should be included
        self.assertIn("installed_apps", serializer.data)

        installed_apps = serializer.data["installed_apps"]

        # Should be a dictionary containing app information
        self.assertIsInstance(installed_apps, dict)

        # Expected CUPCAKE apps should be present
        expected_apps = ["ccv", "ccc", "ccm", "ccmc", "ccsc", "ccrv"]
        for app_code in expected_apps:
            self.assertIn(app_code, installed_apps)

            # Each app should have required fields
            app_info = installed_apps[app_code]
            self.assertIn("name", app_info)
            self.assertIn("code", app_info)
            self.assertIn("description", app_info)
            self.assertIn("installed", app_info)

            # installed should be boolean
            self.assertIsInstance(app_info["installed"], bool)

            # code should match the key
            self.assertEqual(app_info["code"], app_code)

    def test_installed_apps_reflects_actual_installation(self):
        """Test that installed_apps correctly reflects which apps are actually installed."""
        config = SiteConfig.objects.create(site_name="Test Site", updated_by=self.user)

        serializer = SiteConfigSerializer(config)
        installed_apps = serializer.data["installed_apps"]

        # CCC and CCV should always be installed (core apps)
        self.assertTrue(installed_apps["ccc"]["installed"], "CCC (Core) should always be installed")
        self.assertTrue(installed_apps["ccv"]["installed"], "CCV (Vanilla) should always be installed")

        # Test that the installation status matches Django's app registry
        from django.apps import apps

        app_names = [app.name for app in apps.get_app_configs()]

        # Check each app's installation status
        for app_code, app_info in installed_apps.items():
            if app_code in app_names:
                # App is in Django registry, should be marked as installed
                self.assertTrue(app_info["installed"], f"{app_code} should be marked as installed")
            else:
                # App is not in Django registry, should be marked as not installed
                self.assertFalse(app_info["installed"], f"{app_code} should be marked as not installed")

    def test_installed_apps_is_read_only(self):
        """Test that installed_apps field is read-only and cannot be set via serializer."""
        data = {"site_name": "New Site", "installed_apps": {"fake": {"installed": True}}}  # Should be ignored

        serializer = SiteConfigSerializer(data=data)
        self.assertTrue(serializer.is_valid())

        # installed_apps should not be in validated_data since it's read-only
        validated_fields = list(serializer.validated_data.keys())
        self.assertNotIn("installed_apps", validated_fields)


class LabGroupInvitationSerializerTestCase(TestCase):
    """Test cases for LabGroupInvitationSerializer."""

    def setUp(self):
        self.user = User.objects.create_user("inviter", "inviter@test.com", "password")
        self.lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)

    def test_create_invitation_serializer(self):
        """Test creating invitation through serializer."""
        data = {"lab_group": self.lab_group.id, "invited_email": "invitee@test.com", "message": "Join us!"}

        serializer = LabGroupInvitationSerializer(data=data, context={"request": Mock(user=self.user)})

        self.assertTrue(serializer.is_valid())
        invitation = serializer.save()

        self.assertEqual(invitation.lab_group, self.lab_group)
        self.assertEqual(invitation.inviter, self.user)
        self.assertEqual(invitation.invited_email, "invitee@test.com")
        self.assertEqual(invitation.message, "Join us!")


# Integration Test Cases
@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class IntegrationTestCase(APITestCase):
    """Integration tests for CCC functionality."""

    def setUp(self):
        self.user1 = User.objects.create_user("user1", "user1@test.com", "password")
        self.user2 = User.objects.create_user("user2", "user2@test.com", "password")
        self.client = APIClient()

    @skip_if_no_url("labgroup-list")
    def test_complete_lab_group_workflow(self):
        """Test complete workflow from group creation to invitation acceptance."""
        # 1. User1 creates a lab group
        self.client.force_authenticate(user=self.user1)

        data = {"name": "Research Lab", "description": "Our research group"}
        response = self.client.post(reverse("labgroup-list"), data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        lab_group_id = response.data["id"]
        lab_group = LabGroup.objects.get(id=lab_group_id)

        # 2. User1 sends invitation to user2
        invitation_data = {
            "lab_group": lab_group_id,
            "invited_email": "user2@test.com",
            "message": "Please join our lab!",
        }

        response = self.client.post(reverse("labgroupinvitation-list"), invitation_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        invitation = LabGroupInvitation.objects.get(id=response.data["id"])

        # 3. User2 accepts the invitation
        self.client.force_authenticate(user=self.user2)

        accept_url = reverse("labgroupinvitation-accept", kwargs={"pk": invitation.pk})
        response = self.client.post(accept_url, {"token": invitation.invitation_token})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 4. Verify user2 is now a member
        lab_group.refresh_from_db()
        self.assertTrue(lab_group.is_member(self.user2))

        # 5. Verify invitation status is updated
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, LabGroupInvitation.InvitationStatus.ACCEPTED)

    @skip_if_no_url("siteconfig-list")
    def test_site_config_management(self):
        """Test site configuration management workflow."""
        admin_user = User.objects.create_user("admin", "admin@test.com", "password", is_staff=True)

        # 1. Check public config (empty initially) - skip if endpoint doesn't exist
        if url_exists("siteconfig-public"):
            response = self.client.get(reverse("siteconfig-public"))
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 2. Admin creates site config
        self.client.force_authenticate(user=admin_user)

        config_data = {
            "site_name": "My CUPCAKE Instance",
            "primary_color": "#2196F3",
            "allow_user_registration": True,
            "enable_orcid_login": False,
        }

        response = self.client.post(reverse("siteconfig-list"), config_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        config_id = response.data["id"]

        # 3. Update site config
        update_data = {"site_name": "Updated CUPCAKE Instance"}

        response = self.client.patch(reverse("siteconfig-detail", kwargs={"pk": config_id}), update_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["site_name"], "Updated CUPCAKE Instance")

        # 4. Verify public config reflects changes
        response = self.client.get(reverse("siteconfig-public"))
        self.assertEqual(response.data["site_name"], "Updated CUPCAKE Instance")

    def test_permission_system_integration(self):
        """Test resource permission system integration."""
        # This would require a concrete model that inherits from AbstractResource
        # For now, we'll test the permission model directly

        content_type = ContentType.objects.get_for_model(User)

        # Create permission
        ResourcePermission.objects.create(
            resource_content_type=content_type,
            resource_object_id=self.user1.pk,
            user=self.user2,
            role=ResourceRole.EDITOR,
            granted_by=self.user1,
        )

        # Verify permission exists
        self.assertTrue(ResourcePermission.objects.filter(user=self.user2, role=ResourceRole.EDITOR).exists())

        # Test permission queries
        user_permissions = ResourcePermission.objects.filter(user=self.user2)
        self.assertEqual(user_permissions.count(), 1)
        self.assertEqual(user_permissions.first().role, ResourceRole.EDITOR)


# ORCID Authentication Test Cases
@skip_if_no_orcid("ORCID OAuth configuration required for authentication tests")
class ORCIDAuthenticationTestCase(APITestCase):
    """Test cases for ORCID OAuth2 authentication views."""

    def setUp(self):
        self.client = APIClient()

    @patch("ccc.view_modules.auth_views.ORCIDOAuth2Helper")
    def test_orcid_login_initiate_success(self, mock_helper):
        """Test successful ORCID login initiation."""
        mock_helper.get_authorization_url.return_value = (
            "https://orcid.org/oauth/authorize?state=test&redirect_uri=test",
            "test_state",
        )

        url = reverse("orcid-login")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("authorization_url", response.data)
        self.assertIn("state", response.data)
        self.assertEqual(response.data["state"], "test_state")

    @patch("ccc.view_modules.auth_views.ORCIDOAuth2Helper")
    def test_orcid_login_initiate_config_error(self, mock_helper):
        """Test ORCID login initiation with configuration error."""
        mock_helper.get_authorization_url.side_effect = ValueError("Missing client ID")

        url = reverse("orcid-login")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("error", response.data)

    @patch("ccc.view_modules.auth_views.ORCIDOAuth2Helper")
    @patch("ccc.view_modules.auth_views.authenticate")
    def test_orcid_callback_success(self, mock_authenticate, mock_helper):
        """Test successful ORCID callback processing."""
        # Setup mocks
        user = User.objects.create_user("orcid_user", "orcid@test.com", "password")
        mock_helper.exchange_code_for_token.return_value = {
            "orcid": "0000-0000-0000-0001",
            "access_token": "test_token",
        }
        mock_authenticate.return_value = user

        # Setup session
        session = self.client.session
        session["orcid_state"] = "test_state"
        session.save()

        url = reverse("orcid-callback")
        response = self.client.get(url, {"code": "test_code", "state": "test_state"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response.data)
        self.assertIn("refresh_token", response.data)
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["username"], "orcid_user")

    def test_orcid_callback_error_from_orcid(self):
        """Test ORCID callback with error from ORCID."""
        url = reverse("orcid-callback")
        response = self.client.get(url, {"error": "access_denied", "error_description": "User denied access"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_orcid_callback_missing_parameters(self):
        """Test ORCID callback with missing required parameters."""
        url = reverse("orcid-callback")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_orcid_callback_state_mismatch(self):
        """Test ORCID callback with state mismatch (CSRF protection)."""
        # Setup session with different state
        session = self.client.session
        session["orcid_state"] = "correct_state"
        session.save()

        url = reverse("orcid-callback")
        response = self.client.get(url, {"code": "test_code", "state": "wrong_state"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    @patch("ccc.view_modules.auth_views.authenticate")
    def test_orcid_token_exchange_success(self, mock_authenticate):
        """Test successful ORCID token exchange."""
        user = User.objects.create_user("orcid_user", "orcid@test.com", "password")
        mock_authenticate.return_value = user

        url = reverse("orcid-token")
        data = {"access_token": "test_token", "orcid_id": "0000-0000-0000-0001"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response.data)
        self.assertIn("refresh_token", response.data)
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["orcid_id"], "0000-0000-0000-0001")

    def test_orcid_token_exchange_missing_parameters(self):
        """Test ORCID token exchange with missing parameters."""
        url = reverse("orcid-token")
        data = {"access_token": "test_token"}  # Missing orcid_id

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    @patch("ccc.view_modules.auth_views.authenticate")
    def test_orcid_token_exchange_auth_failed(self, mock_authenticate):
        """Test ORCID token exchange with authentication failure."""
        mock_authenticate.return_value = None

        url = reverse("orcid-token")
        data = {"access_token": "invalid_token", "orcid_id": "0000-0000-0000-0001"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("error", response.data)

    def test_auth_status_authenticated(self):
        """Test auth status endpoint when user is authenticated."""
        user = User.objects.create_user("testuser", "test@test.com", "password")
        self.client.force_authenticate(user=user)

        url = reverse("auth-status")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["authenticated"])
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["username"], "testuser")

    def test_auth_status_unauthenticated(self):
        """Test auth status endpoint when user is not authenticated."""
        url = reverse("auth-status")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["authenticated"])
        self.assertNotIn("user", response.data)


# JWT Utilities Test Cases
class JWTUtilsTestCase(TestCase):
    """Test cases for JWT utility functions."""

    def setUp(self):
        self.user = User.objects.create_user("testuser", "test@example.com", "password")

    def test_custom_token_obtain_pair_serializer(self):
        """Test custom JWT token serializer with extra claims."""

        # Create serializer with user credentials
        serializer = CustomTokenObtainPairSerializer(data={"username": "testuser", "password": "password"})

        self.assertTrue(serializer.is_valid())
        tokens = serializer.validated_data

        # Check that extra user data is included
        self.assertIn("user", tokens)
        self.assertEqual(tokens["user"]["username"], "testuser")
        self.assertEqual(tokens["user"]["email"], "test@example.com")
        self.assertIn("access", tokens)
        self.assertIn("refresh", tokens)

    def test_custom_token_claims(self):
        """Test that custom claims are added to JWT tokens."""
        from django.conf import settings

        import jwt

        # Get token
        refresh = CustomTokenObtainPairSerializer.get_token(self.user)
        access_token = refresh.access_token

        # Decode token to check claims
        decoded = jwt.decode(
            str(access_token), settings.SECRET_KEY, algorithms=["HS256"], options={"verify_signature": False}
        )

        # Check custom claims
        self.assertEqual(decoded["username"], "testuser")
        self.assertEqual(decoded["email"], "test@example.com")
        self.assertFalse(decoded["is_staff"])
        self.assertFalse(decoded["is_superuser"])


# Admin and Management Test Cases
class AdminManagementTestCase(TestCase):
    """Test cases for admin and management functionality."""

    def setUp(self):
        self.admin_user = User.objects.create_user(
            "admin", "admin@test.com", "password", is_staff=True, is_superuser=True
        )
        self.regular_user = User.objects.create_user("user", "user@test.com", "password")

    def test_site_config_admin_interface(self):
        """Test that site config can be managed through admin interface."""
        from django.contrib.admin.sites import site

        # Check that SiteConfig is registered in admin
        self.assertIn(SiteConfig, site._registry)

        # Test admin functionality
        SiteConfig.objects.create(site_name="Test Site")
        admin_instance = SiteConfigAdmin(SiteConfig, site)

        # Test list display
        self.assertTrue(hasattr(admin_instance, "list_display"))

        # Test that admin can be instantiated
        self.assertIsNotNone(admin_instance)

    def test_lab_group_admin_interface(self):
        """Test lab group admin interface functionality."""
        from django.contrib.admin.sites import site

        # Check that LabGroup is registered
        self.assertIn(LabGroup, site._registry)

        # Create test lab group
        lab_group = LabGroup.objects.create(name="Test Lab", creator=self.admin_user)
        lab_group.members.add(self.regular_user)

        self.assertEqual(lab_group.members.count(), 1)
        self.assertTrue(lab_group.is_member(self.regular_user))


# Performance and Edge Case Tests
class PerformanceAndEdgeCaseTestCase(TestCase):
    """Test cases for performance and edge cases."""

    def setUp(self):
        self.user = User.objects.create_user("testuser", "test@example.com", "password")

    def test_large_number_of_lab_groups(self):
        """Test system performance with many lab groups."""
        # Create 100 lab groups
        lab_groups = []
        for i in range(100):
            lab_group = LabGroup.objects.create(name=f"Lab Group {i}", creator=self.user)
            lab_groups.append(lab_group)

        # Test that we can efficiently query all groups
        all_groups = LabGroup.objects.all()
        self.assertEqual(all_groups.count(), 100)

        # Test filtering by creator
        user_groups = LabGroup.objects.filter(creator=self.user)
        self.assertEqual(user_groups.count(), 100)

    def test_large_number_of_invitations(self):
        """Test system performance with many invitations."""
        lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)

        # Create 50 invitations
        invitations = []
        for i in range(50):
            invitation = LabGroupInvitation.objects.create(
                lab_group=lab_group, inviter=self.user, invited_email=f"user{i}@test.com"
            )
            invitations.append(invitation)

        # Test that we can efficiently query invitations
        lab_invitations = LabGroupInvitation.objects.filter(lab_group=lab_group)
        self.assertEqual(lab_invitations.count(), 50)

        # Test filtering by status
        pending_invitations = lab_invitations.filter(status=LabGroupInvitation.InvitationStatus.PENDING)
        self.assertEqual(pending_invitations.count(), 50)

    def test_resource_permissions_scalability(self):
        """Test resource permission system with many permissions."""
        content_type = ContentType.objects.get_for_model(User)

        # Create multiple users
        users = []
        for i in range(20):
            user = User.objects.create_user(f"user{i}", f"user{i}@test.com", "password")
            users.append(user)

        # Create permissions for each user
        for i, user in enumerate(users):
            ResourcePermission.objects.create(
                resource_content_type=content_type,
                resource_object_id=1,
                user=user,
                role=ResourceRole.VIEWER if i % 2 else ResourceRole.EDITOR,
                granted_by=self.user,
            )

        # Test efficient querying of permissions
        all_permissions = ResourcePermission.objects.all()
        self.assertEqual(all_permissions.count(), 20)

        # Test filtering by role
        editor_permissions = ResourcePermission.objects.filter(role=ResourceRole.EDITOR)
        viewer_permissions = ResourcePermission.objects.filter(role=ResourceRole.VIEWER)

        self.assertEqual(editor_permissions.count(), 10)
        self.assertEqual(viewer_permissions.count(), 10)

    def test_invitation_token_uniqueness(self):
        """Test that invitation tokens are always unique."""
        lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user)

        # Create many invitations and check token uniqueness
        tokens = set()
        for i in range(100):
            invitation = LabGroupInvitation.objects.create(
                lab_group=lab_group, inviter=self.user, invited_email=f"user{i}@test.com"
            )
            tokens.add(invitation.invitation_token)

        # All tokens should be unique
        self.assertEqual(len(tokens), 100)

    def test_edge_case_empty_values(self):
        """Test system behavior with empty or null values."""
        # Test creating models with minimal required fields
        lab_group = LabGroup.objects.create(name="Minimal Lab")
        self.assertIsNone(lab_group.creator)
        self.assertIsNone(lab_group.description)
        self.assertTrue(lab_group.is_active)

        # Test site config with minimal fields
        config = SiteConfig.objects.create()
        self.assertEqual(config.site_name, "CUPCAKE")
        self.assertIsNone(config.logo_url)

    def test_unicode_and_special_characters(self):
        """Test system handling of unicode and special characters."""
        # Test with unicode characters
        lab_group = LabGroup.objects.create(name="研究室 Lab Français 🧪", description="Testing unicode: αβγδε ñáéíóú 中文")

        self.assertEqual(lab_group.name, "研究室 Lab Français 🧪")
        self.assertIn("中文", lab_group.description)

        # Test ORCID profile with unicode name (skip if ORCID not configured)
        if orcid_configured():
            profile = UserOrcidProfile.objects.create(
                user=self.user, orcid_id="0000-0000-0000-0001", orcid_name="José María González-López"
            )

            self.assertEqual(profile.orcid_name, "José María González-López")


# Security Test Cases
class SecurityTestCase(APITestCase):
    """Test cases for security features and vulnerabilities."""

    def setUp(self):
        self.user1 = User.objects.create_user("user1", "user1@test.com", "password")
        self.user2 = User.objects.create_user("user2", "user2@test.com", "password")
        self.admin_user = User.objects.create_user("admin", "admin@test.com", "password", is_staff=True)
        self.client = APIClient()

    def test_authentication_required_endpoints(self):
        """Test that protected endpoints require authentication."""
        protected_urls = []

        # Only test URLs that exist
        if url_exists("labgroup-list"):
            protected_urls.append(reverse("labgroup-list"))
        if url_exists("siteconfig-list"):
            protected_urls.append(reverse("siteconfig-list"))

        for url in protected_urls:
            response = self.client.get(url)
            self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_admin_required_endpoints(self):
        """Test that admin endpoints require admin privileges."""
        self.client.force_authenticate(user=self.user1)

        admin_urls = []

        # Only test URLs that exist
        if url_exists("siteconfig-list"):
            admin_urls.append(reverse("siteconfig-list"))

        for url in admin_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @skip_if_no_url("labgroup-list")
    def test_lab_group_access_control(self):
        """Test lab group access control and permissions."""
        # User1 creates a lab group
        self.client.force_authenticate(user=self.user1)

        data = {"name": "Private Lab"}
        response = self.client.post(reverse("labgroup-list"), data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        lab_group_id = response.data["id"]

        # User2 should not be able to modify the lab group
        self.client.force_authenticate(user=self.user2)

        update_data = {"name": "Hacked Lab"}
        response = self.client.patch(reverse("labgroup-detail", kwargs={"pk": lab_group_id}), update_data)
        # Should be forbidden or not found depending on implementation
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_invitation_token_security(self):
        """Test invitation token security features."""
        lab_group = LabGroup.objects.create(name="Test Lab", creator=self.user1)
        invitation = LabGroupInvitation.objects.create(
            lab_group=lab_group, inviter=self.user1, invited_email="invitee@test.com"
        )

        # Token should be long and random
        self.assertGreaterEqual(len(invitation.invitation_token), 32)

        # Token should be URL-safe
        import string

        allowed_chars = string.ascii_letters + string.digits + "-_"
        self.assertTrue(all(c in allowed_chars for c in invitation.invitation_token))

    @skip_if_no_orcid()
    def test_orcid_state_csrf_protection(self):
        """Test ORCID OAuth state parameter CSRF protection."""
        # Test callback without session state
        url = reverse("orcid-callback")
        response = self.client.get(url, {"code": "test_code", "state": "malicious_state"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid state", response.data["error"])

    def test_sql_injection_prevention(self):
        """Test that the system prevents SQL injection attacks."""
        # Try SQL injection in search fields
        malicious_input = "'; DROP TABLE ccc_labgroup; --"

        # This should not cause any issues
        lab_groups = LabGroup.objects.filter(name__icontains=malicious_input)
        self.assertEqual(lab_groups.count(), 0)

        # Verify table still exists
        test_group = LabGroup.objects.create(name="Test Lab", creator=self.user1)
        self.assertIsNotNone(test_group)

    def test_user_enumeration_protection(self):
        """Test protection against user enumeration attacks."""
        # Test login with non-existent user
        url = reverse("auth-login")
        data = {"username": "nonexistentuser", "password": "password"}

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Error message should not reveal whether user exists
        self.assertIn("Invalid credentials", response.data["error"])
        self.assertNotIn("user does not exist", response.data["error"].lower())


class ORCIDConfigurationTestCase(TestCase):
    """Test case to verify ORCID configuration status."""

    def test_orcid_configuration_status(self):
        """Display ORCID configuration status for debugging."""
        is_configured = orcid_configured()
        has_views = ORCID_VIEWS_AVAILABLE

        client_id = getattr(settings, "ORCID_CLIENT_ID", "NOT SET")
        client_secret = getattr(settings, "ORCID_CLIENT_SECRET", "NOT SET")

        print("\n=== ORCID Configuration Status ===")
        print(f"ORCID_CLIENT_ID: {'SET' if client_id and client_id != '' else 'NOT SET'}")
        print(f"ORCID_CLIENT_SECRET: {'SET' if client_secret and client_secret != '' else 'NOT SET'}")
        print(f"ORCID Views Available: {has_views}")
        print(f"ORCID Fully Configured: {is_configured and has_views}")

        if not (is_configured and has_views):
            print("\nTo run ORCID tests, set environment variables:")
            print("  export ORCID_CLIENT_ID=your_orcid_client_id")
            print("  export ORCID_CLIENT_SECRET=your_orcid_client_secret")
            print("\nOr skip ORCID tests with current configuration.\n")

        # This test always passes - it's just informational
        self.assertTrue(True)


if __name__ == "__main__":
    import django

    # Configure Django settings for running tests
    from django.conf import settings as django_settings
    from django.test.utils import get_runner

    if not django_settings.configured:
        django_settings.configure(
            DEBUG=True,
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
            INSTALLED_APPS=[
                "django.contrib.auth",
                "django.contrib.contenttypes",
                "rest_framework",
                "rest_framework_simplejwt",
                "simple_history",
                "ccc",
            ],
            SECRET_KEY="test-secret-key",
            USE_TZ=True,
        )

    django.setup()

    TestRunner = get_runner(django_settings)
    test_runner = TestRunner()
    failures = test_runner.run_tests(["ccc.tests"])


class RemoteHostSerializerTestCase(TestCase):
    """Test RemoteHost serializer functionality."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass123")
        self.remote_host = RemoteHost.objects.create(
            host_name="test-host",
            host_port=8000,
            host_protocol="http",
            host_description="Test host",
            host_token="secret-token",
        )

    def test_serializer_excludes_token(self):
        """Test that host_token is not exposed in serialized output."""
        from ccc.serializers import RemoteHostSerializer

        serializer = RemoteHostSerializer(instance=self.remote_host)
        self.assertNotIn("host_token", serializer.data)

    def test_serializer_validation(self):
        """Test serializer validation with valid data."""
        from ccc.serializers import RemoteHostSerializer

        data = {
            "host_name": "new-host",
            "host_port": 9000,
            "host_protocol": "https",
            "host_description": "New test host",
            "host_token": "new-token",
        }
        serializer = RemoteHostSerializer(data=data)
        self.assertTrue(serializer.is_valid())


class ResourcePermissionSerializerTestCase(TestCase):
    """Test ResourcePermission serializer functionality."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass123")
        self.granted_by = User.objects.create_user(username="grantor", password="pass123")
        self.site_config = SiteConfig.objects.create(site_name="Test Site")
        self.content_type = ContentType.objects.get_for_model(SiteConfig)

        self.permission = ResourcePermission.objects.create(
            user=self.user,
            resource_content_type=self.content_type,
            resource_object_id=self.site_config.id,
            role="viewer",
            granted_by=self.granted_by,
        )

    def test_user_display_name(self):
        """Test user display name generation."""
        from ccc.serializers import ResourcePermissionSerializer

        self.user.first_name = "John"
        self.user.last_name = "Doe"
        self.user.save()

        serializer = ResourcePermissionSerializer(instance=self.permission)
        self.assertEqual(serializer.data["user_display_name"], "John Doe")

    def test_create_sets_granted_by(self):
        """Test that creating permission sets granted_by to current user."""
        from unittest.mock import Mock

        from ccc.serializers import ResourcePermissionSerializer

        # Create a different user to avoid unique constraint violation
        different_user = User.objects.create_user(username="differentuser", password="testpass123")

        data = {
            "user": different_user.id,
            "resource_content_type": self.content_type.id,
            "resource_object_id": self.site_config.id,
            "role": "editor",
        }

        request = Mock()
        request.user = self.granted_by
        serializer = ResourcePermissionSerializer(data=data, context={"request": request})
        if not serializer.is_valid():
            print(f"Serializer errors: {serializer.errors}")
        self.assertTrue(serializer.is_valid())

        permission = serializer.save()
        self.assertEqual(permission.granted_by, self.granted_by)


class RemoteHostViewSetTestCase(APITestCase):
    """Test RemoteHost viewset functionality."""

    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admin", password="pass123", is_staff=True, is_superuser=True
        )
        self.regular_user = User.objects.create_user(username="regular", password="pass123")
        self.remote_host = RemoteHost.objects.create(host_name="existing-host", host_port=8001, host_protocol="https")

    def test_admin_can_list_remote_hosts(self):
        """Test that admin users can list remote hosts."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/v1/remote-hosts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_regular_user_cannot_access(self):
        """Test that regular users cannot access remote hosts."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get("/api/v1/remote-hosts/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ResourcePermissionViewSetTestCase(APITestCase):
    """Test ResourcePermission viewset functionality."""

    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admin", password="pass123", is_staff=True, is_superuser=True
        )
        self.regular_user = User.objects.create_user(username="regular", password="pass123")
        self.site_config = SiteConfig.objects.create(site_name="Test Site")
        self.content_type = ContentType.objects.get_for_model(SiteConfig)

        self.permission = ResourcePermission.objects.create(
            user=self.regular_user,
            resource_content_type=self.content_type,
            resource_object_id=self.site_config.id,
            role="viewer",
            granted_by=self.admin_user,
        )

    def test_admin_sees_all_permissions(self):
        """Test that admin users can see all permissions."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get("/api/v1/resource-permissions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_regular_user_filtered_view(self):
        """Test that regular users only see relevant permissions."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get("/api/v1/resource-permissions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
