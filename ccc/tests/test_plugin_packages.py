"""Plugin packages uploaded by staff: checks, preview, port choice, installation and uninstallation."""

import io
import json
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from rest_framework import status
from rest_framework.test import APITestCase

from ccc.plugin.model import Plugin
from ccc.plugin.packages import PluginPackageError, choose_port, read_package
from ccv.models import Vocabulary

BASE = "/api/v1/appliance"

MANIFEST = {
    "name": "device-temperature",
    "displayName": "Device temperature",
    "version": "1.0.0",
    "description": "Reports the temperature",
    "pages": [{"path": "temperature", "title": "Device temperature", "widgets": []}],
    "vocabularies": [{"key": "sensors", "label": "Sensors"}],
}


def package(files=None, manifest=MANIFEST, links=(), extra=()):
    """A gzipped tar holding run.sh, manifest.json and the given files, links and raw members."""
    buffer = io.BytesIO()
    contents = {"run.sh": b"#!/bin/sh\n", **({"manifest.json": json.dumps(manifest).encode()} if manifest else {})}
    contents.update(files or {})
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in contents.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        for name, target in links:
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            archive.addfile(info)
        for info in extra:
            archive.addfile(info)
    return buffer.getvalue()


class PackageTestCase(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def write(self, data, name="plugin.tar.gz"):
        path = self.root / name
        path.write_bytes(data)
        return path


class ReadPackageTests(PackageTestCase):
    def test_a_valid_package_gives_its_manifest(self):
        self.assertEqual(read_package(self.write(package({"lib/util.py": b"x = 1\n"})))["name"], "device-temperature")

    def test_packages_built_from_a_dot_directory_are_accepted(self):
        self.assertEqual(read_package(self.write(package({"./extra.txt": b"x"})))["version"], "1.0.0")

    def test_files_other_than_gzipped_tars_are_refused(self):
        with self.assertRaisesMessage(PluginPackageError, "not a .tar.gz"):
            read_package(self.write(b"plain text"))

    def test_links_are_refused(self):
        with self.assertRaisesMessage(PluginPackageError, "link or special file"):
            read_package(self.write(package(links=[("secret", "/etc/shadow")])))

    def test_paths_outside_the_plugin_are_refused(self):
        with self.assertRaisesMessage(PluginPackageError, "outside the plugin"):
            read_package(self.write(package({"../escape.sh": b"x"})))
        with self.assertRaisesMessage(PluginPackageError, "outside the plugin"):
            read_package(self.write(package({"/etc/cron.d/evil": b"x"})))

    def test_run_sh_and_manifest_are_required_at_the_top(self):
        with self.assertRaisesMessage(PluginPackageError, "manifest.json at the top level"):
            read_package(self.write(package(manifest=None)))

    def test_the_manifest_name_must_be_safe(self):
        for name in ("Device Temperature", "../x", "", "-x"):
            with self.subTest(name=name), self.assertRaises(PluginPackageError):
                read_package(self.write(package(manifest={**MANIFEST, "name": name})))

    def test_the_manifest_needs_a_version_and_a_valid_port(self):
        with self.assertRaisesMessage(PluginPackageError, "version"):
            read_package(self.write(package(manifest={**MANIFEST, "version": ""})))
        with self.assertRaisesMessage(PluginPackageError, "port"):
            read_package(self.write(package(manifest={**MANIFEST, "port": 80})))

    @override_settings(PLUGIN_PACKAGE_MAX_UNPACKED_BYTES=100)
    def test_packages_too_large_unpacked_are_refused(self):
        with self.assertRaisesMessage(PluginPackageError, "too large unpacked"):
            read_package(self.write(package({"data.bin": b"x" * 200})))


class ChoosePortTests(TestCase):
    @override_settings(PLUGIN_PORT_RANGE=(8101, 8103))
    def test_the_manifest_port_is_used_when_free(self):
        with patch("ccc.plugin.packages._is_free", return_value=True):
            self.assertEqual(choose_port({**MANIFEST, "port": 8150}), 8150)

    @override_settings(PLUGIN_PORT_RANGE=(8101, 8103))
    def test_ports_of_other_plugins_and_busy_ports_are_skipped(self):
        Plugin.objects.create(name="other", display_name="Other", version="1", base_url="http://127.0.0.1:8101")
        with patch("ccc.plugin.packages._is_free", side_effect=lambda port: port != 8102):
            self.assertEqual(choose_port(MANIFEST), 8103)

    def test_a_reinstalled_plugin_keeps_its_port(self):
        Plugin.objects.create(
            name="device-temperature", display_name="T", version="0.9", base_url="http://127.0.0.1:8177"
        )
        self.assertEqual(choose_port(MANIFEST), 8177)

    @override_settings(PLUGIN_PORT_RANGE=(8101, 8102))
    def test_no_free_port_is_reported(self):
        with patch("ccc.plugin.packages._is_free", return_value=False):
            with self.assertRaisesMessage(PluginPackageError, "No free port"):
                choose_port(MANIFEST)


class PluginUploadTests(APITestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.uploads = Path(directory.name)
        overrides = override_settings(PLUGIN_UPLOAD_DIR=str(self.uploads), PLUGIN_PORT_RANGE=(8101, 8199))
        overrides.enable()
        self.addCleanup(overrides.disable)
        self.staff = User.objects.create_user("staff", "staff@test.com", "pw", is_staff=True)
        self.client.force_authenticate(user=self.staff)
        self.commands = []
        manager = patch("ccc.viewsets.ApplianceViewSet._send_plugin_command", side_effect=self.manager)
        manager.start()
        self.addCleanup(manager.stop)
        free = patch("ccc.plugin.packages._is_free", return_value=True)
        free.start()
        self.addCleanup(free.stop)
        self.fail_on = None

    def manager(self, payload):
        self.commands.append(payload)
        if payload["command"] == self.fail_on:
            return {"ok": False, "error": f"{payload['command']} broke"}
        return {"ok": True, "output": f"{payload['command']} done"}

    def upload(self, data=None):
        upload = SimpleUploadedFile("plugin.tar.gz", data or package(), content_type="application/gzip")
        return self.client.post(f"{BASE}/plugin-upload/", {"file": upload}, format="multipart")

    def install(self, upload_id):
        return self.client.post(f"{BASE}/plugin-install-upload/", {"upload_id": upload_id}, format="json")

    def test_an_upload_shows_what_the_plugin_adds(self):
        response = self.upload()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["display_name"], "Device temperature")
        self.assertEqual(response.data["pages"], ["Device temperature"])
        self.assertEqual(response.data["vocabularies"], ["Sensors"])
        self.assertIsNone(response.data["installed_version"])
        self.assertTrue((self.uploads / f"{response.data['upload_id']}.tar.gz").exists())
        self.assertEqual(self.commands, [])

    def test_an_invalid_upload_is_refused_and_not_kept(self):
        response = self.upload(package(links=[("x", "/etc/shadow")]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(list(self.uploads.iterdir()), [])

    @override_settings(PLUGIN_UPLOAD_MAX_BYTES=10)
    def test_an_upload_too_large_is_refused(self):
        self.assertEqual(self.upload().status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    def test_only_staff_upload_and_install(self):
        self.client.force_authenticate(User.objects.create_user("user", "user@test.com", "pw"))
        self.assertEqual(self.upload().status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.install("0" * 32).status_code, status.HTTP_403_FORBIDDEN)

    def test_install_registers_configures_and_starts_the_plugin_on_a_local_port(self):
        upload_id = self.upload().data["upload_id"]
        response = self.install(upload_id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        port = response.data["port"]
        self.assertEqual([c["command"] for c in self.commands], ["install", "configure", "restart"])
        self.assertEqual(self.commands[0]["source"], str(self.uploads / f"{upload_id}.tar.gz"))
        env = self.commands[1]["env"]
        plugin = Plugin.objects.get(name="device-temperature")
        self.assertEqual(plugin.token, Plugin.hash_token(env["PLUGIN_TOKEN"]))
        self.assertEqual(plugin.base_url, f"http://127.0.0.1:{port}")
        self.assertEqual(
            (env["PLUGIN_BASE_URL"], env["PLUGIN_HOST"], env["PLUGIN_PORT"]),
            (f"http://127.0.0.1:{port}", "127.0.0.1", str(port)),
        )
        self.assertEqual(plugin.display_name, "Device temperature")
        self.assertFalse(Vocabulary.objects.get(key="plugin.device-temperature.sensors").approved)
        self.assertFalse((self.uploads / f"{upload_id}.tar.gz").exists())

    def test_reinstalling_shows_the_installed_version_and_keeps_the_port(self):
        self.install(self.upload().data["upload_id"])
        port = Plugin.objects.get(name="device-temperature").base_url
        preview = self.upload(package(manifest={**MANIFEST, "version": "1.1.0"})).data
        self.assertEqual(preview["installed_version"], "1.0.0")
        self.install(preview["upload_id"])
        plugin = Plugin.objects.get(name="device-temperature")
        self.assertEqual((plugin.version, plugin.base_url), ("1.1.0", port))

    def test_unknown_uploads_are_refused(self):
        self.assertEqual(self.install("../../etc/passwd").status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.install("f" * 32).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.commands, [])

    def test_a_failed_install_is_reported_and_nothing_registered(self):
        self.fail_on = "install"
        response = self.install(self.upload().data["upload_id"])
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("install broke", response.data["error"])
        self.assertFalse(Plugin.objects.filter(name="device-temperature").exists())

    def test_a_plugin_that_does_not_start_is_reported(self):
        self.fail_on = "restart"
        response = self.install(self.upload().data["upload_id"])
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("not started", response.data["error"])

    def test_uninstalling_removes_the_registration(self):
        self.install(self.upload().data["upload_id"])
        response = self.client.post(f"{BASE}/plugin-uninstall/", {"name": "device-temperature"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Plugin.objects.filter(name="device-temperature").exists())
        self.assertFalse(Vocabulary.objects.filter(key="plugin.device-temperature.sensors").exists())
