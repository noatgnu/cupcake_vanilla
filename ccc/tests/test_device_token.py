from datetime import timedelta

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from ccc.device_token.auth import DeviceTokenAuthentication
from ccc.device_token.model import DeviceToken
from ccc.device_token.permissions import IsDeviceTokenAuthenticated


def _make_user(username, password="password"):
    return User.objects.create_user(username, f"{username}@test.com", password)


def _make_token(user, permission=DeviceToken.PERMISSION_READ, enabled=True, expires_at=None):
    return DeviceToken.objects.create(
        label=f"token-{user.username}",
        permission=permission,
        enabled=enabled,
        user=user,
        expires_at=expires_at,
    )


class DeviceTokenModelTest(APITestCase):
    def setUp(self):
        self.user = _make_user("modeluser")

    def test_token_auto_generated_on_create(self):
        token = _make_token(self.user)
        self.assertEqual(len(token.token), 128)

    def test_token_not_overwritten_on_resave(self):
        token = _make_token(self.user)
        original = token.token
        token.label = "updated"
        token.save()
        self.assertEqual(token.token, original)

    def test_str(self):
        token = _make_token(self.user)
        self.assertIn(token.label, str(token))
        self.assertIn(token.permission, str(token))

    def test_is_expired_false_when_no_expiry(self):
        token = _make_token(self.user)
        self.assertFalse(token.is_expired())

    def test_is_expired_false_when_future(self):
        token = _make_token(self.user, expires_at=timezone.now() + timedelta(days=1))
        self.assertFalse(token.is_expired())

    def test_is_expired_true_when_past(self):
        token = _make_token(self.user, expires_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(token.is_expired())

    def test_default_permission_is_read(self):
        token = DeviceToken.objects.create(label="t", user=self.user)
        self.assertEqual(token.permission, DeviceToken.PERMISSION_READ)


class DeviceTokenAuthenticationTest(APITestCase):
    def setUp(self):
        self.user = _make_user("authuser")
        self.token = _make_token(self.user)
        self.auth = DeviceTokenAuthentication()
        self.client = APIClient()

    def _request_with_header(self, value):
        request = self.client.get("/").wsgi_request
        request.META["HTTP_AUTHORIZATION"] = value
        return request

    def test_valid_token_authenticates(self):
        request = self._request_with_header(f"DeviceToken {self.token.token}")
        result = self.auth.authenticate(request)
        self.assertIsNotNone(result)
        user, auth = result
        self.assertEqual(user, self.user)
        self.assertEqual(auth.pk, self.token.pk)

    def test_missing_header_returns_none(self):
        request = self._request_with_header("")
        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_wrong_scheme_returns_none(self):
        request = self._request_with_header(f"Bearer {self.token.token}")
        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_invalid_token_raises(self):
        from rest_framework.exceptions import AuthenticationFailed

        request = self._request_with_header("DeviceToken invalidtoken")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_disabled_token_raises(self):
        from rest_framework.exceptions import AuthenticationFailed

        disabled = _make_token(self.user, enabled=False)
        request = self._request_with_header(f"DeviceToken {disabled.token}")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_expired_token_raises(self):
        from rest_framework.exceptions import AuthenticationFailed

        expired = _make_token(self.user, expires_at=timezone.now() - timedelta(seconds=1))
        request = self._request_with_header(f"DeviceToken {expired.token}")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_malformed_header_raises(self):
        from rest_framework.exceptions import AuthenticationFailed

        request = self._request_with_header("DeviceToken a b c")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_last_used_at_updated_on_auth(self):
        self.assertIsNone(self.token.last_used_at)
        request = self._request_with_header(f"DeviceToken {self.token.token}")
        self.auth.authenticate(request)
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)

    def test_authenticate_header(self):
        request = self.client.get("/").wsgi_request
        self.assertEqual(self.auth.authenticate_header(request), "DeviceToken")


class IsDeviceTokenAuthenticatedTest(APITestCase):
    def setUp(self):
        self.user = _make_user("permuser")
        self.perm = IsDeviceTokenAuthenticated()

    def _mock_request(self, method, auth):
        request = self.client.get("/").wsgi_request
        request.method = method
        request.auth = auth
        return request

    def test_non_device_auth_passes(self):
        request = self._mock_request("DELETE", object())
        self.assertTrue(self.perm.has_permission(request, None))

    def test_read_token_allows_safe_methods(self):
        token = _make_token(self.user, permission=DeviceToken.PERMISSION_READ)
        for method in ("GET", "HEAD", "OPTIONS"):
            request = self._mock_request(method, token)
            self.assertTrue(self.perm.has_permission(request, None))

    def test_read_token_blocks_unsafe_methods(self):
        token = _make_token(self.user, permission=DeviceToken.PERMISSION_READ)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            request = self._mock_request(method, token)
            self.assertFalse(self.perm.has_permission(request, None))

    def test_write_token_allows_all_methods(self):
        token = _make_token(self.user, permission=DeviceToken.PERMISSION_WRITE)
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            request = self._mock_request(method, token)
            self.assertTrue(self.perm.has_permission(request, None))


class DeviceTokenViewSetTest(APITestCase):
    def setUp(self):
        self.user = _make_user("vsuser")
        self.other = _make_user("vsother")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_list_returns_only_own_tokens(self):
        _make_token(self.user)
        _make_token(self.other)
        response = self.client.get(reverse("ccc:devicetoken-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [t["user"] for t in response.data["results"]]
        self.assertTrue(all(i == self.user.pk for i in ids))

    def test_create_token(self):
        response = self.client.post(reverse("ccc:devicetoken-list"), {"label": "My Badge", "permission": "read"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["label"], "My Badge")
        self.assertEqual(len(response.data["token"]), 128)

    def test_create_assigns_current_user(self):
        self.client.post(reverse("ccc:devicetoken-list"), {"label": "Badge", "permission": "read"})
        token = DeviceToken.objects.get(label="Badge")
        self.assertEqual(token.user, self.user)

    def test_rotate_generates_new_token(self):
        token = _make_token(self.user)
        old_value = token.token
        response = self.client.post(reverse("ccc:devicetoken-rotate", args=[token.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotEqual(response.data["token"], old_value)
        self.assertEqual(len(response.data["token"]), 128)

    def test_toggle_flips_enabled(self):
        token = _make_token(self.user, enabled=True)
        response = self.client.post(reverse("ccc:devicetoken-toggle", args=[token.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["enabled"])
        response = self.client.post(reverse("ccc:devicetoken-toggle", args=[token.pk]))
        self.assertTrue(response.data["enabled"])

    def test_delete_token(self):
        token = _make_token(self.user)
        response = self.client.delete(reverse("ccc:devicetoken-detail", args=[token.pk]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DeviceToken.objects.filter(pk=token.pk).exists())

    def test_cannot_access_other_users_token(self):
        other_token = _make_token(self.other)
        response = self.client.get(reverse("ccc:devicetoken-detail", args=[other_token.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("ccc:devicetoken-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class DeviceTokenAPIAuthTest(APITestCase):
    def setUp(self):
        self.user = _make_user("apiuser")
        self.read_token = _make_token(self.user, permission=DeviceToken.PERMISSION_READ)
        self.write_token = _make_token(self.user, permission=DeviceToken.PERMISSION_WRITE)
        self.client = APIClient()

    def _auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"DeviceToken {token.token}")

    def test_read_token_can_list_own_tokens(self):
        self._auth(self.read_token)
        response = self.client.get(reverse("ccc:devicetoken-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_read_token_cannot_create(self):
        self._auth(self.read_token)
        response = self.client.post(reverse("ccc:devicetoken-list"), {"label": "X", "permission": "read"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_write_token_can_create(self):
        self._auth(self.write_token)
        response = self.client.post(reverse("ccc:devicetoken-list"), {"label": "Y", "permission": "read"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_summary_accessible_with_read_token(self):
        self._auth(self.read_token)
        response = self.client.get(reverse("ccc:device-summary"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for key in ("instruments", "active_jobs", "low_reagents", "users", "lab_groups", "active_timers"):
            self.assertIn(key, response.data)

    def test_expired_token_returns_401(self):
        expired = _make_token(self.user, expires_at=timezone.now() - timedelta(seconds=1))
        self._auth(expired)
        response = self.client.get(reverse("ccc:devicetoken-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_disabled_token_returns_401(self):
        disabled = _make_token(self.user, enabled=False)
        self._auth(disabled)
        response = self.client.get(reverse("ccc:devicetoken-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
