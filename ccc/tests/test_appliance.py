"""
Tests for ApplianceViewSet covering storage, backup, and WiFi management.

All privileged OS operations (socket calls, netplan, mount) are mocked so
these tests run cleanly in CI without root access or physical hardware.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from ccc.viewsets import ApplianceViewSet

BASE = "/api/v1/appliance"

VALID_WIFI_PERSONAL = {
    "ssid": "HomeNet",
    "interfaceName": "wlan0",
    "authType": "wpa2-personal",
    "password": "secret123",
}

VALID_WIFI_ENTERPRISE_PEAP = {
    "ssid": "CorpNet",
    "interfaceName": "wlan0",
    "authType": "wpa2-enterprise",
    "eapMethod": "peap",
    "phase2Auth": "mschapv2",
    "identity": "user@corp.com",
    "password": "secret123",
}

SAMPLE_PEM = b"-----BEGIN CERTIFICATE-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA\n-----END CERTIFICATE-----\n"


def _staff(username="staff"):
    return User.objects.create_user(username, f"{username}@test.com", "pw", is_staff=True)


def _regular(username="regular"):
    return User.objects.create_user(username, f"{username}@test.com", "pw")


class WifiConfigValidationTest(APITestCase):
    """Unit tests for _validate_wifi_config — no HTTP, no mocking needed."""

    def _v(self, cfg):
        return ApplianceViewSet._validate_wifi_config(cfg)

    def test_valid_personal(self):
        self.assertIsNone(self._v(VALID_WIFI_PERSONAL))

    def test_valid_enterprise_peap(self):
        self.assertIsNone(self._v(VALID_WIFI_ENTERPRISE_PEAP))

    def test_valid_enterprise_ttls(self):
        cfg = {**VALID_WIFI_ENTERPRISE_PEAP, "eapMethod": "ttls", "phase2Auth": "pap"}
        self.assertIsNone(self._v(cfg))

    def test_missing_ssid(self):
        cfg = {**VALID_WIFI_PERSONAL, "ssid": ""}
        self.assertIn("ssid", self._v(cfg))

    def test_ssid_too_long(self):
        cfg = {**VALID_WIFI_PERSONAL, "ssid": "A" * 33}
        self.assertIn("ssid", self._v(cfg))

    def test_missing_interface(self):
        cfg = {**VALID_WIFI_PERSONAL, "interfaceName": ""}
        self.assertIn("interfaceName", self._v(cfg))

    def test_invalid_interface_chars(self):
        cfg = {**VALID_WIFI_PERSONAL, "interfaceName": "wlan0; rm -rf /"}
        self.assertIn("interfaceName", self._v(cfg))

    def test_invalid_auth_type(self):
        cfg = {**VALID_WIFI_PERSONAL, "authType": "wep"}
        self.assertIn("authType", self._v(cfg))

    def test_personal_missing_password(self):
        cfg = {**VALID_WIFI_PERSONAL, "password": ""}
        self.assertIn("password", self._v(cfg))

    def test_enterprise_missing_eap_method(self):
        cfg = {**VALID_WIFI_ENTERPRISE_PEAP, "eapMethod": ""}
        self.assertIn("eapMethod", self._v(cfg))

    def test_enterprise_invalid_eap_method(self):
        cfg = {**VALID_WIFI_ENTERPRISE_PEAP, "eapMethod": "md5"}
        self.assertIn("eapMethod", self._v(cfg))

    def test_enterprise_missing_identity(self):
        cfg = {**VALID_WIFI_ENTERPRISE_PEAP, "identity": ""}
        self.assertIn("identity", self._v(cfg))

    def test_enterprise_peap_missing_password(self):
        cfg = {**VALID_WIFI_ENTERPRISE_PEAP, "password": ""}
        self.assertIn("password", self._v(cfg))

    def test_enterprise_invalid_phase2(self):
        cfg = {**VALID_WIFI_ENTERPRISE_PEAP, "phase2Auth": "ntlm"}
        self.assertIn("phase2Auth", self._v(cfg))

    def test_enterprise_tls_missing_client_cert(self):
        cfg = {**VALID_WIFI_ENTERPRISE_PEAP, "eapMethod": "tls", "clientCertFilename": "", "clientKeyFilename": "k.pem"}
        self.assertIn("clientCertFilename", self._v(cfg))

    def test_enterprise_tls_missing_client_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "c.pem").write_bytes(SAMPLE_PEM)
            cfg = {
                **VALID_WIFI_ENTERPRISE_PEAP,
                "eapMethod": "tls",
                "clientCertFilename": "c.pem",
                "clientKeyFilename": "",
            }
            with patch("ccc.viewsets._WIFI_CERT_DIR", tmp_path):
                self.assertIn("clientKeyFilename", self._v(cfg))


class StorageConfigValidationTest(APITestCase):
    """Unit tests for _validate_storage_config."""

    def _v(self, cfg):
        return ApplianceViewSet._validate_storage_config(cfg)

    def test_valid_usb(self):
        self.assertIsNone(self._v({"mountType": "usb", "label": "BACKUP"}))

    def test_valid_nfs(self):
        self.assertIsNone(self._v({"mountType": "nfs", "host": "192.168.1.1", "share": "/data"}))

    def test_valid_smb(self):
        self.assertIsNone(self._v({"mountType": "smb", "host": "fileserver", "share": "share1"}))

    def test_invalid_mount_type(self):
        self.assertIn("mountType", self._v({"mountType": "ftp", "label": "x"}))

    def test_usb_missing_label(self):
        self.assertIn("label", self._v({"mountType": "usb", "label": ""}))

    def test_shell_injection_in_label(self):
        self.assertIn("invalid", self._v({"mountType": "usb", "label": "GOOD; rm -rf /"}))

    def test_nfs_missing_host(self):
        self.assertIn("host", self._v({"mountType": "nfs", "host": "", "share": "/data"}))

    def test_nfs_missing_share(self):
        self.assertIn("share", self._v({"mountType": "nfs", "host": "server", "share": ""}))


class ApplianceAuthTest(APITestCase):
    """Verify that all appliance endpoints require staff access."""

    def setUp(self):
        self.regular = _regular()
        self.client = APIClient()
        self.client.force_authenticate(user=self.regular)

    def _assert_forbidden(self, path, method="get"):
        resp = getattr(self.client, method)(path, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN, f"{method.upper()} {path} should be 403")

    def test_wifi_status_requires_staff(self):
        self._assert_forbidden(f"{BASE}/wifi-status/", "get")

    def test_wifi_interfaces_requires_staff(self):
        self._assert_forbidden(f"{BASE}/wifi-interfaces/", "get")

    def test_apply_wifi_requires_staff(self):
        self._assert_forbidden(f"{BASE}/apply-wifi/", "post")

    def test_disable_wifi_requires_staff(self):
        self._assert_forbidden(f"{BASE}/disable-wifi/", "post")

    def test_upload_cert_requires_staff(self):
        self._assert_forbidden(f"{BASE}/upload-wifi-cert/", "post")

    def test_storage_status_requires_staff(self):
        self._assert_forbidden(f"{BASE}/storage-status/", "get")

    def test_apply_storage_requires_staff(self):
        self._assert_forbidden(f"{BASE}/apply-storage/", "post")

    def test_run_backup_requires_staff(self):
        self._assert_forbidden(f"{BASE}/run-backup/", "post")


class WifiStatusTest(APITestCase):
    """Tests for GET /api/v1/appliance/wifi-status/."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=_staff())

    def test_no_config_file_returns_disconnected(self):
        with tempfile.TemporaryDirectory() as tmp:
            nonexistent = Path(tmp) / "wifi-config.json"
            with patch("ccc.viewsets._WIFI_CONFIG_PATH", nonexistent):
                resp = self.client.get(f"{BASE}/wifi-status/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["connected"])
        self.assertIsNone(resp.data["config"])

    def test_config_returned_without_password(self):
        cfg = {**VALID_WIFI_PERSONAL, "password": "topsecret"}
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "wifi-config.json"
            config_file.write_text(json.dumps(cfg))
            with patch("ccc.viewsets._WIFI_CONFIG_PATH", config_file):
                with patch("ccc.viewsets.subprocess.check_output", side_effect=Exception("no iw")):
                    resp = self.client.get(f"{BASE}/wifi-status/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertNotIn("password", resp.data.get("config") or {})
        self.assertEqual(resp.data["config"]["ssid"], "HomeNet")


class WifiInterfacesTest(APITestCase):
    """Tests for GET /api/v1/appliance/wifi-interfaces/."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=_staff())

    def test_returns_wireless_interfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            net_dir = Path(tmp)
            wlan0 = net_dir / "wlan0"
            wlan0.mkdir()
            (wlan0 / "wireless").mkdir()
            (net_dir / "eth0").mkdir()

            original_path = Path

            def patched_path(*args, **kwargs):
                if args and str(args[0]) == "/sys/class/net":
                    return net_dir
                return original_path(*args, **kwargs)

            with patch("ccc.viewsets.Path", side_effect=patched_path):
                resp = self.client.get(f"{BASE}/wifi-interfaces/")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("wlan0", resp.data["interfaces"])
        self.assertNotIn("eth0", resp.data["interfaces"])

    def test_returns_empty_list_when_no_wireless(self):
        with tempfile.TemporaryDirectory() as tmp:
            net_dir = Path(tmp)
            (net_dir / "eth0").mkdir()

            original_path = Path

            def patched_path(*args, **kwargs):
                if args and str(args[0]) == "/sys/class/net":
                    return net_dir
                return original_path(*args, **kwargs)

            with patch("ccc.viewsets.Path", side_effect=patched_path):
                resp = self.client.get(f"{BASE}/wifi-interfaces/")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["interfaces"], [])


class ApplyWifiTest(APITestCase):
    """Tests for POST /api/v1/appliance/apply-wifi/."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=_staff())

    def _post(self, config, tmp_path):
        with patch("ccc.viewsets._WIFI_CONFIG_PATH", tmp_path / "wifi-config.json"):
            return self.client.post(f"{BASE}/apply-wifi/", {"config": config}, format="json")

    def test_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ApplianceViewSet, "_send_network_command", return_value={"ok": True, "output": "done"}):
                resp = self._post(VALID_WIFI_PERSONAL, Path(tmp))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("output", resp.data)

    def test_config_saved_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_file = tmp_path / "wifi-config.json"
            with patch.object(ApplianceViewSet, "_send_network_command", return_value={"ok": True, "output": ""}):
                self._post(VALID_WIFI_PERSONAL, tmp_path)
            saved = json.loads(config_file.read_text())
        self.assertEqual(saved["ssid"], "HomeNet")

    def test_missing_config_body_returns_400(self):
        resp = self.client.post(f"{BASE}/apply-wifi/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_config_returns_400(self):
        cfg = {**VALID_WIFI_PERSONAL, "ssid": ""}
        with tempfile.TemporaryDirectory() as tmp:
            resp = self._post(cfg, Path(tmp))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_socket_error_returns_500(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ApplianceViewSet, "_send_network_command", side_effect=OSError("no socket")):
                resp = self._post(VALID_WIFI_PERSONAL, Path(tmp))
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_socket_not_ok_returns_500(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ApplianceViewSet, "_send_network_command", return_value={"ok": False, "error": "failed"}):
                resp = self._post(VALID_WIFI_PERSONAL, Path(tmp))
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)


class DisableWifiTest(APITestCase):
    """Tests for POST /api/v1/appliance/disable-wifi/."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=_staff())

    def test_success_removes_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "wifi-config.json"
            config_file.write_text("{}")
            with patch("ccc.viewsets._WIFI_CONFIG_PATH", config_file):
                with patch.object(ApplianceViewSet, "_send_network_command", return_value={"ok": True, "output": ""}):
                    resp = self.client.post(f"{BASE}/disable-wifi/", format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(config_file.exists())

    def test_socket_error_returns_500(self):
        with patch.object(ApplianceViewSet, "_send_network_command", side_effect=OSError("no socket")):
            resp = self.client.post(f"{BASE}/disable-wifi/", format="json")
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)


class UploadWifiCertTest(APITestCase):
    """Tests for POST /api/v1/appliance/upload-wifi-cert/."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=_staff())

    def _upload(self, cert_type, content, tmp_path):
        uploaded = SimpleUploadedFile("cert.pem", content, content_type="application/x-pem-file")
        with patch("ccc.viewsets._WIFI_CERT_DIR", tmp_path):
            return self.client.post(
                f"{BASE}/upload-wifi-cert/",
                {"file": uploaded, "cert_type": cert_type},
                format="multipart",
            )

    def test_upload_ca_cert_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            resp = self._upload("ca", SAMPLE_PEM, Path(tmp))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["filename"], "ca.pem")

    def test_upload_client_cert_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            resp = self._upload("client_cert", SAMPLE_PEM, Path(tmp))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["filename"], "client_cert.pem")

    def test_upload_client_key_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            resp = self._upload("client_key", SAMPLE_PEM, Path(tmp))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["filename"], "client_key.pem")

    def test_file_saved_to_cert_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._upload("ca", SAMPLE_PEM, tmp_path)
            self.assertEqual((tmp_path / "ca.pem").read_bytes(), SAMPLE_PEM)

    def test_invalid_cert_type_returns_400(self):
        with tempfile.TemporaryDirectory() as tmp:
            resp = self._upload("intermediate", SAMPLE_PEM, Path(tmp))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_file_returns_400(self):
        with patch("ccc.viewsets._WIFI_CERT_DIR", Path(tempfile.mkdtemp())):
            resp = self.client.post(f"{BASE}/upload-wifi-cert/", {"cert_type": "ca"}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_pem_content_returns_400(self):
        with tempfile.TemporaryDirectory() as tmp:
            resp = self._upload("ca", b"not a certificate", Path(tmp))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_oversized_file_returns_400(self):
        with tempfile.TemporaryDirectory() as tmp:
            large = b"-----BEGIN CERTIFICATE-----\n" + b"A" * 70000
            resp = self._upload("ca", large, Path(tmp))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class StorageStatusTest(APITestCase):
    """Tests for GET /api/v1/appliance/storage-status/."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=_staff())

    def test_unmounted_state(self):
        mock_content = "/dev/sda1 /boot ext4 rw 0 0\n"
        m = _mock_open(mock_content)
        with patch("builtins.open", m):
            resp = self.client.get(f"{BASE}/storage-status/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["mounted"])

    def test_mounted_state(self):
        mock_content = "/dev/sdb1 /mnt/cupcake-data ext4 rw 0 0\n"
        m = _mock_open(mock_content)
        with patch("builtins.open", m):
            resp = self.client.get(f"{BASE}/storage-status/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["mounted"])
        self.assertEqual(resp.data["device"], "/dev/sdb1")


class ApplyStorageTest(APITestCase):
    """Tests for POST /api/v1/appliance/apply-storage/."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=_staff())

    def test_success(self):
        with patch.object(ApplianceViewSet, "_send_storage_command", return_value={"ok": True, "output": "mounted"}):
            resp = self.client.post(
                f"{BASE}/apply-storage/",
                {"config": {"mountType": "usb", "label": "BACKUP"}},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_invalid_config_returns_400(self):
        resp = self.client.post(f"{BASE}/apply-storage/", {"config": {"mountType": "usb", "label": ""}}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_config_key_returns_400(self):
        resp = self.client.post(f"{BASE}/apply-storage/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_socket_error_returns_500(self):
        with patch.object(ApplianceViewSet, "_send_storage_command", side_effect=OSError("no socket")):
            resp = self.client.post(
                f"{BASE}/apply-storage/",
                {"config": {"mountType": "nfs", "host": "server", "share": "/data"}},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)


class BackupListTest(APITestCase):
    """Tests for GET /api/v1/appliance/ (backup log list)."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=_staff())

    def test_returns_empty_list(self):
        resp = self.client.get(f"{BASE}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, [])


class RunBackupTest(APITestCase):
    """Tests for POST /api/v1/appliance/run-backup/."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=_staff())

    def test_invalid_backup_type_returns_400(self):
        resp = self.client.post(
            f"{BASE}/run-backup/",
            {"backup_type": "logs", "destination": "/opt/cupcake/backups"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_destination_returns_400(self):
        resp = self.client.post(
            f"{BASE}/run-backup/",
            {"backup_type": "full", "destination": "/tmp/evil"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_path_traversal_destination_returns_400(self):
        resp = self.client.post(
            f"{BASE}/run-backup/",
            {"backup_type": "database", "destination": "/opt/cupcake/backups/../../../etc"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_valid_backup_enqueued(self):
        with patch("ccc.viewsets.run_backup_task") as mock_task:
            mock_task.delay = MagicMock()
            resp = self.client.post(
                f"{BASE}/run-backup/",
                {"backup_type": "database", "destination": "/opt/cupcake/backups"},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["status"], "running")
        mock_task.delay.assert_called_once()


def _mock_open(read_data):
    """Return a mock for builtins.open that supports line iteration."""
    from unittest.mock import mock_open

    m = mock_open(read_data=read_data)
    m.return_value.__iter__ = lambda self: iter(read_data.splitlines(keepends=True))
    return m
