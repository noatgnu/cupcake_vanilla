"""A plugin created from cupcake-plugin-dev's service template, run against the backend."""

import importlib.util
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from django.contrib.auth.models import User
from django.test import override_settings

from rest_framework.test import APIClient, APITestCase

from ccc.plugin.model import Plugin
from cupcake_plugin_dev.scaffold import create_plugin

SCAFFOLD = tempfile.TemporaryDirectory()
TEMPLATE = create_plugin("example-service", "service", Path(SCAFFOLD.name))
SPEC = importlib.util.spec_from_file_location("service_plugin_template", TEMPLATE / "plugin.py")
template = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = template
SPEC.loader.exec_module(template)


class ClientBackend(template.Backend):
    """The template's backend calls sent through the Django test client."""

    def __init__(self, token):
        """Authenticate the test client with the plugin token."""
        super().__init__("http://testserver", token)
        self.client = APIClient()
        self.client.credentials(HTTP_PLUGIN_TOKEN=token)

    def post(self, path, body):
        response = self.client.post(f"/api/v1/{path}", body, format="json")
        assert response.status_code < 300, f"POST {path}: {response.status_code} {response.content[:300]!r}"
        return response.json()


@override_settings(ALLOWED_HOSTS=["testserver"])
class ServicePluginTemplateTests(APITestCase):
    def setUp(self):
        self.manifest = template.read_manifest()
        self.plugin = Plugin.objects.create(name=self.manifest["name"], display_name="Example", version="0.1.0")
        self.backend = ClientBackend(self.plugin._plain_token)
        server, _ = template.serve(self.manifest, self.plugin._plain_token, 0, host="127.0.0.1")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base_url = f"http://127.0.0.1:{server.server_port}"
        template.announce(self.backend, self.base_url, self.manifest)
        self.user = User.objects.create_user("viewer", "viewer@test.com", "password")

    def test_startup_completes_the_handshake(self):
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.lifecycle_status, Plugin.LIFECYCLE_RUNNING)
        self.assertIsNotNone(self.plugin.connection_verified_at)

    def test_users_read_the_status_card_through_the_backend(self):
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(f"/api/v1/plugins/{self.plugin.pk}/call/", {"endpoint": "/api/status"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Updated", response.data)

    def test_the_status_is_pushed_through_the_backend(self):
        template.publish(self.backend)

    def test_the_plugin_refuses_callers_other_than_the_backend(self):
        with self.assertRaises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(f"{self.base_url}/api/status", timeout=5)
        self.assertEqual(refused.exception.code, 401)
