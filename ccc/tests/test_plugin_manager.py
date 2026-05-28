"""
Tests for the plugin manager appliance endpoints.

Two test suites are provided:

MockedPluginManagerTest
    Exercises every endpoint in isolation by patching _send_plugin_command so
    the plugin manager socket is never touched.  These run in any environment.

RealPluginManagerTest
    Sends real commands to the cupcake-plugin-manager socket.  A minimal sample
    plugin is created in a temporary directory and installed, started, stopped,
    reinstalled and finally uninstalled.  These tests are skipped automatically
    when the socket is not present (i.e. outside the appliance image / VM).
"""

import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

BASE = "/api/v1/appliance"


def _staff(username="pluginstaff"):
    return User.objects.create_user(username, f"{username}@test.com", "pw", is_staff=True)


def _regular(username="pluginreg"):
    return User.objects.create_user(username, f"{username}@test.com", "pw")


def _sample_plugin_dir(tmp_path: Path, name: str = "test-plugin") -> Path:
    """Return a minimal valid plugin directory inside tmp_path."""
    plugin_src = tmp_path / name
    plugin_src.mkdir(parents=True, exist_ok=True)
    run_sh = plugin_src / "run.sh"
    run_sh.write_text("#!/bin/bash\necho running\n")
    run_sh.chmod(run_sh.stat().st_mode | stat.S_IEXEC)
    return plugin_src


class MockedPluginManagerTest(APITestCase):
    """All endpoints with _send_plugin_command patched; no socket required."""

    def setUp(self):
        self.staff = _staff()
        self.regular = _regular()
        self.client = APIClient()
        self.client.force_authenticate(user=self.staff)

    def _ok(self, **extra):
        return {"ok": True, "output": "done", **extra}

    def _err(self, msg="failed"):
        return {"ok": False, "error": msg}

    def test_install_success(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", return_value=self._ok()) as m:
            resp = self.client.post(
                f"{BASE}/plugin-install/",
                {"name": "myplugin", "source": "http://example.com/plugin.tar.gz"},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        m.assert_called_once_with(
            {"command": "install", "name": "myplugin", "source": "http://example.com/plugin.tar.gz"}
        )

    def test_install_missing_name_returns_400(self):
        resp = self.client.post(f"{BASE}/plugin-install/", {"source": "http://x.com/p.tar.gz"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_install_invalid_name_returns_400(self):
        resp = self.client.post(
            f"{BASE}/plugin-install/", {"name": "bad name!", "source": "http://x.com/p.tar.gz"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_install_missing_source_returns_400(self):
        resp = self.client.post(f"{BASE}/plugin-install/", {"name": "myplugin"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_install_manager_error_returns_500(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", return_value=self._err("disk full")):
            resp = self.client.post(
                f"{BASE}/plugin-install/", {"name": "myplugin", "source": "http://x.com/p.tar.gz"}, format="json"
            )
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("disk full", resp.data["error"])

    def test_install_socket_error_returns_500(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", side_effect=OSError("no socket")):
            resp = self.client.post(
                f"{BASE}/plugin-install/", {"name": "myplugin", "source": "http://x.com/p.tar.gz"}, format="json"
            )
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_install_requires_staff(self):
        self.client.force_authenticate(user=self.regular)
        resp = self.client.post(
            f"{BASE}/plugin-install/", {"name": "p", "source": "http://x.com/p.tar.gz"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_uninstall_success(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", return_value=self._ok()) as m:
            resp = self.client.post(f"{BASE}/plugin-uninstall/", {"name": "myplugin"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        m.assert_called_once_with({"command": "uninstall", "name": "myplugin"})

    def test_uninstall_missing_name_returns_400(self):
        resp = self.client.post(f"{BASE}/plugin-uninstall/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_uninstall_manager_error_returns_500(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", return_value=self._err("not found")):
            resp = self.client.post(f"{BASE}/plugin-uninstall/", {"name": "myplugin"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_uninstall_socket_error_returns_500(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", side_effect=OSError("no socket")):
            resp = self.client.post(f"{BASE}/plugin-uninstall/", {"name": "myplugin"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_uninstall_requires_staff(self):
        self.client.force_authenticate(user=self.regular)
        resp = self.client.post(f"{BASE}/plugin-uninstall/", {"name": "p"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_returns_plugin_list(self):
        plugins = [{"name": "a", "active": True, "enabled": True}]
        with patch(
            "ccc.viewsets.ApplianceViewSet._send_plugin_command", return_value={"ok": True, "plugins": plugins}
        ) as m:
            resp = self.client.get(f"{BASE}/plugin-list/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["plugins"], plugins)
        m.assert_called_once_with({"command": "list"})

    def test_list_socket_error_returns_500(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", side_effect=OSError("no socket")):
            resp = self.client.get(f"{BASE}/plugin-list/")
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_list_requires_staff(self):
        self.client.force_authenticate(user=self.regular)
        resp = self.client.get(f"{BASE}/plugin-list/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_status_success(self):
        with patch(
            "ccc.viewsets.ApplianceViewSet._send_plugin_command",
            return_value={"ok": True, "active": True, "enabled": True, "output": ""},
        ) as m:
            resp = self.client.get(f"{BASE}/plugin-status/", {"name": "myplugin"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["active"])
        m.assert_called_once_with({"command": "status", "name": "myplugin"})

    def test_status_missing_name_returns_400(self):
        resp = self.client.get(f"{BASE}/plugin-status/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_status_socket_error_returns_500(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", side_effect=OSError("no socket")):
            resp = self.client.get(f"{BASE}/plugin-status/", {"name": "myplugin"})
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_status_requires_staff(self):
        self.client.force_authenticate(user=self.regular)
        resp = self.client.get(f"{BASE}/plugin-status/", {"name": "p"})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_control_start(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", return_value=self._ok()) as m:
            resp = self.client.post(f"{BASE}/plugin-control/", {"name": "myplugin", "command": "start"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        m.assert_called_once_with({"command": "start", "name": "myplugin"})

    def test_control_stop(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", return_value=self._ok()) as m:
            resp = self.client.post(f"{BASE}/plugin-control/", {"name": "myplugin", "command": "stop"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        m.assert_called_once_with({"command": "stop", "name": "myplugin"})

    def test_control_restart(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", return_value=self._ok()):
            resp = self.client.post(
                f"{BASE}/plugin-control/", {"name": "myplugin", "command": "restart"}, format="json"
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_control_enable(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", return_value=self._ok()):
            resp = self.client.post(f"{BASE}/plugin-control/", {"name": "myplugin", "command": "enable"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_control_disable(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", return_value=self._ok()):
            resp = self.client.post(
                f"{BASE}/plugin-control/", {"name": "myplugin", "command": "disable"}, format="json"
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_control_invalid_command_returns_400(self):
        resp = self.client.post(f"{BASE}/plugin-control/", {"name": "myplugin", "command": "nuke"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_control_missing_name_returns_400(self):
        resp = self.client.post(f"{BASE}/plugin-control/", {"command": "start"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_control_socket_error_returns_500(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", side_effect=OSError("no socket")):
            resp = self.client.post(f"{BASE}/plugin-control/", {"name": "myplugin", "command": "start"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_control_requires_staff(self):
        self.client.force_authenticate(user=self.regular)
        resp = self.client.post(f"{BASE}/plugin-control/", {"name": "p", "command": "start"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_control_manager_error_returns_500(self):
        with patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", return_value=self._err("service failed")):
            resp = self.client.post(f"{BASE}/plugin-control/", {"name": "myplugin", "command": "start"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)


PLUGIN_SOCK = "/run/cupcake-plugin.sock"


def _socket_available():
    """Return True when the plugin manager socket exists (appliance/VM only)."""
    return os.path.exists(PLUGIN_SOCK)


@unittest.skipUnless(_socket_available(), "cupcake-plugin-manager socket not available")
class RealPluginManagerTest(APITestCase):
    """
    Live tests that exercise the full install/uninstall lifecycle against the
    real cupcake-plugin-manager daemon.  Only run inside the appliance image or
    VM where /run/cupcake-plugin.sock exists.

    Each test class uses a unique plugin name to avoid cross-test interference.
    """

    PLUGIN_NAME = "ci-sample-plugin"

    def setUp(self):
        self.staff = _staff("realstaff")
        self.client = APIClient()
        self.client.force_authenticate(user=self.staff)
        self.tmp = tempfile.mkdtemp()
        self.src = _sample_plugin_dir(Path(self.tmp), self.PLUGIN_NAME)
        self._uninstall_if_present()

    def tearDown(self):
        self._uninstall_if_present()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _uninstall_if_present(self):
        self.client.post(f"{BASE}/plugin-uninstall/", {"name": self.PLUGIN_NAME}, format="json")

    def test_install_creates_plugin(self):
        resp = self.client.post(
            f"{BASE}/plugin-install/", {"name": self.PLUGIN_NAME, "source": str(self.src)}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_installed_plugin_appears_in_list(self):
        self.client.post(f"{BASE}/plugin-install/", {"name": self.PLUGIN_NAME, "source": str(self.src)}, format="json")
        resp = self.client.get(f"{BASE}/plugin-list/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [p["name"] for p in resp.data["plugins"]]
        self.assertIn(self.PLUGIN_NAME, names)

    def test_status_after_install(self):
        self.client.post(f"{BASE}/plugin-install/", {"name": self.PLUGIN_NAME, "source": str(self.src)}, format="json")
        resp = self.client.get(f"{BASE}/plugin-status/", {"name": self.PLUGIN_NAME})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("active", resp.data)

    def test_uninstall_removes_plugin(self):
        self.client.post(f"{BASE}/plugin-install/", {"name": self.PLUGIN_NAME, "source": str(self.src)}, format="json")
        resp = self.client.post(f"{BASE}/plugin-uninstall/", {"name": self.PLUGIN_NAME}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        list_resp = self.client.get(f"{BASE}/plugin-list/")
        names = [p["name"] for p in list_resp.data["plugins"]]
        self.assertNotIn(self.PLUGIN_NAME, names)

    def test_reinstall_after_uninstall(self):
        self.client.post(f"{BASE}/plugin-install/", {"name": self.PLUGIN_NAME, "source": str(self.src)}, format="json")
        self.client.post(f"{BASE}/plugin-uninstall/", {"name": self.PLUGIN_NAME}, format="json")
        resp = self.client.post(
            f"{BASE}/plugin-install/", {"name": self.PLUGIN_NAME, "source": str(self.src)}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        list_resp = self.client.get(f"{BASE}/plugin-list/")
        names = [p["name"] for p in list_resp.data["plugins"]]
        self.assertIn(self.PLUGIN_NAME, names)

    def test_stop_and_start(self):
        self.client.post(f"{BASE}/plugin-install/", {"name": self.PLUGIN_NAME, "source": str(self.src)}, format="json")
        stop_resp = self.client.post(
            f"{BASE}/plugin-control/", {"name": self.PLUGIN_NAME, "command": "stop"}, format="json"
        )
        self.assertEqual(stop_resp.status_code, status.HTTP_200_OK)
        start_resp = self.client.post(
            f"{BASE}/plugin-control/", {"name": self.PLUGIN_NAME, "command": "start"}, format="json"
        )
        self.assertEqual(start_resp.status_code, status.HTTP_200_OK)

    def test_modify_run_sh_and_reinstall(self):
        self.client.post(f"{BASE}/plugin-install/", {"name": self.PLUGIN_NAME, "source": str(self.src)}, format="json")
        run_sh = self.src / "run.sh"
        run_sh.write_text("#!/bin/bash\necho modified\n")
        self.client.post(f"{BASE}/plugin-uninstall/", {"name": self.PLUGIN_NAME}, format="json")
        resp = self.client.post(
            f"{BASE}/plugin-install/", {"name": self.PLUGIN_NAME, "source": str(self.src)}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
