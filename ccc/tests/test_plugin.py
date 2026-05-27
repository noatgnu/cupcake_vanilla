import asyncio
import json
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from ccc.consumers import NotificationConsumer
from ccc.plugin.model import Plugin

BASE = "/api/v1/plugins"


def _make_user(username, password="password", staff=False):
    return User.objects.create_user(username, f"{username}@test.com", password, is_staff=staff)


def _make_plugin(name="test-plugin", version="1.0.0", manifest=None, base_url="http://plugin.local"):
    return Plugin.objects.create(
        name=name,
        display_name=name.replace("-", " ").title(),
        version=version,
        manifest_cache=manifest or {},
        base_url=base_url,
    )


class PluginModelTest(TestCase):
    def setUp(self):
        self.plugin = _make_plugin()

    def test_str_contains_display_name_and_version(self):
        s = str(self.plugin)
        self.assertIn(self.plugin.display_name, s)
        self.assertIn(self.plugin.version, s)

    def test_defaults(self):
        self.assertTrue(self.plugin.is_active)
        self.assertEqual(self.plugin.description, "")
        self.assertEqual(self.plugin.manifest_cache, {})

    def test_token_auto_generated_on_save(self):
        self.assertTrue(self.plugin.token)
        self.assertEqual(len(self.plugin.token), 64)

    def test_token_unique_per_plugin(self):
        other = _make_plugin("other-plugin")
        self.assertNotEqual(self.plugin.token, other.token)

    def test_token_stable_across_updates(self):
        original_token = self.plugin.token
        self.plugin.name = "renamed"
        self.plugin.save()
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.token, original_token)

    def test_id_is_stable_identifier(self):
        pk = self.plugin.pk
        self.plugin.name = "renamed"
        self.plugin.save()
        self.assertEqual(Plugin.objects.get(pk=pk).name, "renamed")

    def test_ordering_by_name_then_id(self):
        _make_plugin("alpha-plugin")
        _make_plugin("zeta-plugin")
        names = list(Plugin.objects.values_list("name", flat=True))
        self.assertEqual(names, sorted(names))


class PluginViewSetListRetrieveTest(APITestCase):
    def setUp(self):
        self.user = _make_user("listuser")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.plugin = _make_plugin()

    def test_list_returns_all_plugins(self):
        _make_plugin("second-plugin")
        response = self.client.get(f"{BASE}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 2)

    def test_retrieve_single_plugin(self):
        response = self.client.get(f"{BASE}/{self.plugin.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.plugin.pk)
        self.assertEqual(response.data["name"], self.plugin.name)

    def test_retrieve_does_not_expose_token(self):
        response = self.client.get(f"{BASE}/{self.plugin.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("token", response.data)

    def test_list_does_not_expose_token(self):
        response = self.client.get(f"{BASE}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for item in response.data.get("results", []):
            self.assertNotIn("token", item)

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(f"{BASE}/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_nonexistent_returns_404(self):
        response = self.client.get(f"{BASE}/99999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class PluginRegisterTest(APITestCase):
    def setUp(self):
        self.admin = _make_user("regadmin", staff=True)
        self.user = _make_user("reguser")
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _register(self, payload):
        return self.client.post(f"{BASE}/register/", payload, format="json")

    def test_register_creates_plugin(self):
        response = self._register({"name": "new-plugin", "version": "1.0.0"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(Plugin.objects.filter(name="new-plugin").exists())

    def test_register_returns_id(self):
        response = self._register({"name": "id-plugin", "version": "1.0.0"})
        self.assertIn("id", response.data)
        self.assertIsInstance(response.data["id"], int)

    def test_register_returns_token(self):
        response = self._register({"name": "token-plugin", "version": "1.0.0"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)
        self.assertEqual(len(response.data["token"]), 64)

    def test_register_sets_lifecycle_installing(self):
        response = self._register({"name": "lifecycle-plugin", "version": "1.0.0"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        plugin = Plugin.objects.get(pk=response.data["id"])
        self.assertEqual(plugin.lifecycle_status, "installing")

    def test_register_upsert_does_not_return_token_on_update(self):
        r1 = self._register({"name": "stable-token-plugin", "version": "1.0.0"})
        r2 = self._register({"name": "stable-token-plugin", "version": "1.1.0"})
        self.assertIn("token", r1.data)
        self.assertNotIn("token", r2.data)

    def test_register_sets_fields(self):
        manifest = {"nav": [{"label": "Home", "path": "home"}]}
        response = self._register(
            {
                "name": "full-plugin",
                "version": "2.0.0",
                "display_name": "Full Plugin",
                "description": "A test plugin",
                "manifest": manifest,
                "base_url": "http://full.local",
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        plugin = Plugin.objects.get(pk=response.data["id"])
        self.assertEqual(plugin.display_name, "Full Plugin")
        self.assertEqual(plugin.description, "A test plugin")
        self.assertEqual(plugin.manifest_cache, manifest)
        self.assertEqual(plugin.base_url, "http://full.local")

    def test_register_upserts_by_name(self):
        self._register({"name": "upsert-plugin", "version": "1.0.0"})
        self._register({"name": "upsert-plugin", "version": "1.1.0"})
        self.assertEqual(Plugin.objects.filter(name="upsert-plugin").count(), 1)
        plugin = Plugin.objects.get(name="upsert-plugin")
        self.assertEqual(plugin.version, "1.1.0")

    def test_register_upsert_reactivates_plugin(self):
        plugin = _make_plugin("inactive-plugin")
        plugin.is_active = False
        plugin.save()
        self._register({"name": "inactive-plugin", "version": "2.0.0"})
        plugin.refresh_from_db()
        self.assertTrue(plugin.is_active)

    def test_register_missing_name_returns_400(self):
        response = self._register({"version": "1.0.0"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_register_missing_version_returns_400(self):
        response = self._register({"name": "no-version-plugin"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_non_admin_register_returns_403(self):
        self.client.force_authenticate(user=self.user)
        response = self._register({"name": "x", "version": "1.0.0"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_register_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self._register({"name": "x", "version": "1.0.0"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PluginStartupTest(APITestCase):
    """Tests for the plugin startup endpoint authenticated via plugin token."""

    def setUp(self):
        self.plugin = _make_plugin("startup-plugin", base_url="http://old.local")
        self.client = APIClient()

    def _startup(self, token, payload):
        return self.client.post(
            f"{BASE}/startup/",
            payload,
            format="json",
            HTTP_PLUGIN_TOKEN=token,
        )

    def test_startup_updates_base_url(self):
        response = self._startup(self.plugin._plain_token, {"base_url": "http://new.local"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.base_url, "http://new.local")

    def test_startup_updates_manifest(self):
        manifest = {"name": "startup-plugin", "version": "2.0.0"}
        response = self._startup(self.plugin._plain_token, {"manifest": manifest})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.manifest_cache, manifest)

    def test_startup_updates_both_fields(self):
        manifest = {"nav": []}
        response = self._startup(
            self.plugin._plain_token,
            {"base_url": "http://updated.local", "manifest": manifest},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.base_url, "http://updated.local")
        self.assertEqual(self.plugin.manifest_cache, manifest)

    def test_startup_sets_lifecycle_running(self):
        response = self._startup(self.plugin._plain_token, {"base_url": "http://new.local"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.lifecycle_status, "running")

    def test_startup_returns_plugin_data(self):
        response = self._startup(self.plugin._plain_token, {"base_url": "http://new.local"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.plugin.pk)
        self.assertEqual(response.data["name"], self.plugin.name)
        self.assertEqual(response.data["lifecycle_status"], "running")

    def test_startup_does_not_return_token(self):
        response = self._startup(self.plugin._plain_token, {})
        self.assertNotIn("token", response.data)

    def test_startup_invalid_token_returns_401(self):
        response = self._startup("invalid-token-xyz", {"base_url": "http://x.local"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_startup_no_token_returns_401(self):
        response = self.client.post(f"{BASE}/startup/", {"base_url": "http://x.local"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_startup_inactive_plugin_token_returns_401(self):
        plain = self.plugin._plain_token
        self.plugin.is_active = False
        self.plugin.save()
        response = self._startup(plain, {"base_url": "http://x.local"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_startup_partial_update_preserves_other_fields(self):
        original_manifest = {"nav": [{"label": "Home", "path": "home"}]}
        self.plugin.manifest_cache = original_manifest
        self.plugin.save()
        self._startup(self.plugin._plain_token, {"base_url": "http://new.local"})
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.manifest_cache, original_manifest)


class PluginReportProgressTest(APITestCase):
    """Tests for the plugin-token-authenticated self-reporting endpoint."""

    def setUp(self):
        self.plugin = _make_plugin("progress-plugin")
        self.client = APIClient()

    def _report(self, token, payload):
        return self.client.post(
            f"{BASE}/report-progress/",
            payload,
            format="json",
            HTTP_PLUGIN_TOKEN=token,
        )

    def test_report_sets_lifecycle_status(self):
        response = self._report(self.plugin._plain_token, {"lifecycle_status": "error"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.lifecycle_status, "error")

    def test_report_sets_progress_message(self):
        response = self._report(
            self.plugin._plain_token, {"lifecycle_status": "starting", "progress_message": "Loading data..."}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.progress_message, "Loading data...")

    def test_report_sets_progress_data(self):
        data = {"step": 2, "total": 5}
        response = self._report(self.plugin._plain_token, {"progress_data": data})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.progress_data, data)

    def test_report_invalid_status_returns_400(self):
        response = self._report(self.plugin._plain_token, {"lifecycle_status": "bogus"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_report_invalid_token_returns_401(self):
        response = self._report("bad-token", {"lifecycle_status": "running"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_report_no_token_returns_401(self):
        response = self.client.post(f"{BASE}/report-progress/", {"lifecycle_status": "running"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_report_returns_updated_plugin_data(self):
        response = self._report(
            self.plugin._plain_token, {"lifecycle_status": "stopped", "progress_message": "Shutting down"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["lifecycle_status"], "stopped")
        self.assertEqual(response.data["progress_message"], "Shutting down")

    def test_report_only_updates_provided_fields(self):
        self.plugin.progress_message = "original"
        self.plugin.save()
        self._report(self.plugin._plain_token, {"lifecycle_status": "error"})
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.progress_message, "original")


class PluginPushTest(APITestCase):
    """Tests for the plugin-token-authenticated runtime broadcast endpoint."""

    def setUp(self):
        self.plugin = _make_plugin("push-plugin")
        self.client = APIClient()

    def _push(self, token, payload):
        return self.client.post(
            f"{BASE}/push/",
            payload,
            format="json",
            HTTP_PLUGIN_TOKEN=token,
        )

    def test_push_with_valid_token_returns_200(self):
        response = self._push(self.plugin._plain_token, {"payload": {"msg": "hello"}})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["sent"])

    def test_push_with_invalid_token_returns_401(self):
        response = self._push("bad-token", {"payload": {}})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_push_without_token_returns_401(self):
        response = self.client.post(f"{BASE}/push/", {"payload": {}}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_push_inactive_plugin_returns_401(self):
        plain = self.plugin._plain_token
        self.plugin.is_active = False
        self.plugin.save()
        response = self._push(plain, {"payload": {}})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PluginManifestTest(APITestCase):
    def setUp(self):
        self.user = _make_user("manifestuser")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.manifest = {
            "nav": [{"label": "Home", "path": "home"}],
            "pages": [{"path": "home", "title": "Home", "widgets": []}],
        }
        self.plugin = _make_plugin(manifest=self.manifest)

    def test_manifest_returns_cached_manifest(self):
        response = self.client.get(f"{BASE}/{self.plugin.pk}/manifest/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, self.manifest)

    def test_manifest_empty_when_not_set(self):
        plugin = _make_plugin("empty-manifest-plugin")
        response = self.client.get(f"{BASE}/{plugin.pk}/manifest/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {})

    def test_manifest_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(f"{BASE}/{self.plugin.pk}/manifest/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PluginBroadcastTest(APITestCase):
    def setUp(self):
        self.user = _make_user("broaduser")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.plugin = _make_plugin()

    def _broadcast(self, payload):
        return self.client.post(f"{BASE}/{self.plugin.pk}/broadcast/", payload, format="json")

    def test_broadcast_global_scope(self):
        mock_layer = MagicMock()
        with patch("ccc.plugin.viewset.get_channel_layer", return_value=mock_layer):
            with patch("ccc.plugin.viewset.async_to_sync") as mock_a2s:
                mock_a2s.return_value = lambda *args, **kwargs: None
                response = self._broadcast({"scope": "global", "payload": {"key": "value"}})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["sent"])
        self.assertIn(f"plugin__{self.plugin.pk}__global", response.data["group"])

    def test_broadcast_user_scope(self):
        mock_layer = MagicMock()
        with patch("ccc.plugin.viewset.get_channel_layer", return_value=mock_layer):
            with patch("ccc.plugin.viewset.async_to_sync") as mock_a2s:
                mock_a2s.return_value = lambda *args, **kwargs: None
                response = self._broadcast({"scope": "user", "user_id": self.user.pk, "payload": {}})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(f"plugin__{self.plugin.pk}__user_{self.user.pk}", response.data["group"])

    def test_broadcast_lab_group_scope(self):
        mock_layer = MagicMock()
        with patch("ccc.plugin.viewset.get_channel_layer", return_value=mock_layer):
            with patch("ccc.plugin.viewset.async_to_sync") as mock_a2s:
                mock_a2s.return_value = lambda *args, **kwargs: None
                response = self._broadcast({"scope": "lab_group", "lab_group_id": 42, "payload": {}})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(f"plugin__{self.plugin.pk}__lab_group_42", response.data["group"])

    def test_broadcast_lab_group_missing_id_returns_400(self):
        response = self._broadcast({"scope": "lab_group", "payload": {}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_broadcast_invalid_scope_returns_400(self):
        response = self._broadcast({"scope": "invalid", "payload": {}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_broadcast_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self._broadcast({"scope": "global", "payload": {}})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PluginStaffMutationTest(APITestCase):
    def setUp(self):
        self.user = _make_user("normaluser")
        self.staff = _make_user("staffuser", staff=True)
        self.client = APIClient()
        self.plugin = _make_plugin()

    def test_patch_as_staff_succeeds(self):
        self.client.force_authenticate(user=self.staff)
        response = self.client.patch(f"{BASE}/{self.plugin.pk}/", {"is_active": False}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.plugin.refresh_from_db()
        self.assertFalse(self.plugin.is_active)

    def test_patch_as_non_staff_returns_403(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(f"{BASE}/{self.plugin.pk}/", {"is_active": False}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_as_staff_succeeds(self):
        self.client.force_authenticate(user=self.staff)
        response = self.client.delete(f"{BASE}/{self.plugin.pk}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Plugin.objects.filter(pk=self.plugin.pk).exists())

    def test_delete_as_non_staff_returns_403(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f"{BASE}/{self.plugin.pk}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class PluginResetTokenTest(APITestCase):
    """Tests for the admin reset-token endpoint."""

    def setUp(self):
        self.staff = _make_user("resetstaff", staff=True)
        self.user = _make_user("resetuser")
        self.plugin = _make_plugin("reset-plugin")
        self.client = APIClient()

    def test_reset_token_as_staff_returns_new_token(self):
        old_hash = self.plugin.token
        self.client.force_authenticate(user=self.staff)
        response = self.client.post(f"{BASE}/{self.plugin.pk}/reset-token/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)
        self.assertEqual(len(response.data["token"]), 64)
        self.plugin.refresh_from_db()
        self.assertNotEqual(self.plugin.token, old_hash)

    def test_reset_token_new_token_authenticates(self):
        self.client.force_authenticate(user=self.staff)
        response = self.client.post(f"{BASE}/{self.plugin.pk}/reset-token/")
        new_plain = response.data["token"]
        plugin_client = APIClient()
        result = plugin_client.post(
            f"{BASE}/startup/",
            {"base_url": "http://x.local"},
            format="json",
            HTTP_PLUGIN_TOKEN=new_plain,
        )
        self.assertEqual(result.status_code, status.HTTP_200_OK)

    def test_reset_token_old_token_no_longer_authenticates(self):
        old_plain = self.plugin._plain_token
        self.client.force_authenticate(user=self.staff)
        self.client.post(f"{BASE}/{self.plugin.pk}/reset-token/")
        plugin_client = APIClient()
        result = plugin_client.post(
            f"{BASE}/startup/",
            {"base_url": "http://x.local"},
            format="json",
            HTTP_PLUGIN_TOKEN=old_plain,
        )
        self.assertEqual(result.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reset_token_as_non_staff_returns_403(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(f"{BASE}/{self.plugin.pk}/reset-token/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reset_token_unauthenticated_returns_401(self):
        response = self.client.post(f"{BASE}/{self.plugin.pk}/reset-token/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class RotatePluginTokensCommandTest(TestCase):
    """Tests for the rotate_plugin_tokens management command."""

    def test_command_rotates_active_plugin_tokens(self):
        plugin = _make_plugin("cmd-plugin")
        old_hash = plugin.token
        out = StringIO()
        call_command("rotate_plugin_tokens", stdout=out)
        plugin.refresh_from_db()
        self.assertNotEqual(plugin.token, old_hash)
        output = out.getvalue()
        self.assertIn("cmd-plugin", output)

    def test_command_outputs_name_and_plain_token(self):
        _make_plugin("output-plugin")
        out = StringIO()
        call_command("rotate_plugin_tokens", stdout=out)
        line = next(ln for ln in out.getvalue().splitlines() if "output-plugin" in ln)
        parts = line.split("\t")
        self.assertEqual(parts[0], "output-plugin")
        self.assertEqual(len(parts[1]), 64)

    def test_command_skips_inactive_by_default(self):
        plugin = _make_plugin("inactive-cmd-plugin")
        plugin.is_active = False
        plugin.save()
        old_hash = plugin.token
        out = StringIO()
        call_command("rotate_plugin_tokens", stdout=out)
        plugin.refresh_from_db()
        self.assertEqual(plugin.token, old_hash)
        self.assertNotIn("inactive-cmd-plugin", out.getvalue())

    def test_command_all_flag_includes_inactive(self):
        plugin = _make_plugin("inactive-all-plugin")
        plugin.is_active = False
        plugin.save()
        old_hash = plugin.token
        out = StringIO()
        call_command("rotate_plugin_tokens", all=True, stdout=out)
        plugin.refresh_from_db()
        self.assertNotEqual(plugin.token, old_hash)


class PluginConsumerTest(TestCase):
    """Tests for plugin channel subscription and broadcast via WebSocket consumer."""

    def _make_subscription_message(self, plugin_id, scope="global", lab_group_id=None):
        msg = {
            "type": "subscribe",
            "subscription_type": "plugin_updates",
            "plugin_id": plugin_id,
            "scope": scope,
        }
        if lab_group_id:
            msg["lab_group_id"] = lab_group_id
        return msg

    def test_handle_subscription_global_adds_group(self):
        consumer = self._build_consumer(user_id=1)
        data = self._make_subscription_message(plugin_id=5, scope="global")

        asyncio.run(consumer.handle_subscription(data))

        consumer.channel_layer.group_add.assert_called_once_with("plugin__5__global", "test-channel")

    def test_handle_subscription_user_adds_group(self):
        consumer = self._build_consumer(user_id=7)
        data = self._make_subscription_message(plugin_id=3, scope="user")

        asyncio.run(consumer.handle_subscription(data))

        consumer.channel_layer.group_add.assert_called_once_with("plugin__3__user_7", "test-channel")

    def test_handle_subscription_lab_group_adds_group(self):
        consumer = self._build_consumer(user_id=1)
        data = self._make_subscription_message(plugin_id=2, scope="lab_group", lab_group_id=9)

        asyncio.run(consumer.handle_subscription(data))

        consumer.channel_layer.group_add.assert_called_once_with("plugin__2__lab_group_9", "test-channel")

    def test_handle_subscription_lab_group_missing_id_does_nothing(self):
        consumer = self._build_consumer(user_id=1)
        data = self._make_subscription_message(plugin_id=2, scope="lab_group")

        asyncio.run(consumer.handle_subscription(data))

        consumer.channel_layer.group_add.assert_not_called()

    def test_handle_subscription_invalid_scope_does_nothing(self):
        consumer = self._build_consumer(user_id=1)
        data = {
            "type": "subscribe",
            "subscription_type": "plugin_updates",
            "plugin_id": 1,
            "scope": "unknown",
        }

        asyncio.run(consumer.handle_subscription(data))

        consumer.channel_layer.group_add.assert_not_called()

    def test_handle_subscription_missing_plugin_id_does_nothing(self):
        consumer = self._build_consumer(user_id=1)
        data = {"type": "subscribe", "subscription_type": "plugin_updates", "scope": "global"}

        asyncio.run(consumer.handle_subscription(data))

        consumer.channel_layer.group_add.assert_not_called()

    def test_plugin_message_handler_sends_correct_payload(self):
        consumer = self._build_consumer(user_id=1)
        event = {
            "type": "plugin_message",
            "plugin_id": 5,
            "plugin_name": "test-plugin",
            "scope": "global",
            "payload": {"key": "val"},
        }

        asyncio.run(consumer.plugin_message(event))

        sent = json.loads(consumer.send.call_args[1]["text_data"])
        self.assertEqual(sent["type"], "plugin.message")
        self.assertEqual(sent["plugin_id"], 5)
        self.assertEqual(sent["plugin_name"], "test-plugin")
        self.assertEqual(sent["scope"], "global")
        self.assertEqual(sent["payload"], {"key": "val"})

    def _build_consumer(self, user_id=1):
        consumer = NotificationConsumer.__new__(NotificationConsumer)
        consumer.channel_name = "test-channel"

        mock_user = MagicMock()
        mock_user.id = user_id
        consumer.user = mock_user

        channel_layer = MagicMock()
        channel_layer.group_add = AsyncMock()
        consumer.channel_layer = channel_layer

        consumer.send = AsyncMock()
        return consumer
