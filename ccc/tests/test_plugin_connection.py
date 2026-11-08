"""The handshake the backend runs with a plugin at its registered address, and the admin connection check."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from django.contrib.auth.models import User

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from ccc.plugin.connection import callback_key, sign
from ccc.plugin.model import Plugin

BASE = "/api/v1/plugins"


class FakePlugin(BaseHTTPRequestHandler):
    """A plugin that answers the handshake with its token, or the way a test sets."""

    name = "fake"
    token = ""
    answer_as = None
    proof_secret = None
    key = ""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        expected = sign(self.token, f"handshake:{body['nonce']}:{body['callback_key']}")
        if self.headers.get("Cupcake-Signature") != expected:
            self.answer(401, {"error": "bad signature"})
            return
        type(self).key = body["callback_key"]
        proof = sign(self.proof_secret or self.token, f"proof:{body['nonce']}")
        self.answer(200, {"name": self.answer_as or self.name, "proof": proof})

    def do_GET(self):
        if self.headers.get("Cupcake-Key") != self.key:
            self.answer(401, {"error": "bad key"})
            return
        self.answer(200, {"name": self.answer_as or self.name})

    def answer(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


class PluginConnectionTests(APITestCase):
    def setUp(self):
        self.plugin = Plugin.objects.create(name="fake", display_name="Fake", version="1.0")
        FakePlugin.token = self.plugin._plain_token
        FakePlugin.answer_as = None
        FakePlugin.proof_secret = None
        FakePlugin.key = ""
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakePlugin)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.staff = User.objects.create_user("staff", "staff@test.com", "password", is_staff=True)

    def startup(self, base_url=None):
        client = APIClient()
        return client.post(
            f"{BASE}/startup/",
            {"base_url": base_url or self.base_url},
            format="json",
            HTTP_PLUGIN_TOKEN=self.plugin._plain_token,
        )

    def check(self, user=None):
        client = APIClient()
        client.force_authenticate(user=user or self.staff)
        return client.post(f"{BASE}/{self.plugin.pk}/check-connection/")

    def test_a_plugin_that_answers_the_handshake_is_running(self):
        response = self.startup()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.lifecycle_status, Plugin.LIFECYCLE_RUNNING)
        self.assertIsNotNone(self.plugin.connection_verified_at)
        self.assertEqual(FakePlugin.key, callback_key(self.plugin))

    def test_an_unreachable_plugin_is_in_error_with_the_reason(self):
        self.server.shutdown()
        self.server.server_close()
        response = self.startup()
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn(self.base_url, response.data["error"])
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.lifecycle_status, Plugin.LIFECYCLE_ERROR)
        self.assertTrue(self.plugin.progress_message.startswith("CUPCAKE could not reach the plugin"))
        self.assertIsNone(self.plugin.connection_verified_at)

    def test_a_service_without_the_plugin_token_fails_the_handshake(self):
        FakePlugin.proof_secret = "not-the-token"
        response = self.startup()
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("proof", response.data["error"])

    def test_a_service_answering_as_another_plugin_fails_the_handshake(self):
        FakePlugin.answer_as = "other"
        self.assertEqual(self.startup().status_code, status.HTTP_502_BAD_GATEWAY)

    def test_the_address_is_kept_when_the_handshake_fails(self):
        self.startup(base_url="http://127.0.0.1:1")
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.base_url, "http://127.0.0.1:1")

    def test_staff_check_the_connection_with_the_callback_key(self):
        self.startup()
        Plugin.objects.filter(pk=self.plugin.pk).update(connection_verified_at=None)
        response = self.check()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data["connection_verified_at"])

    def test_the_check_fails_when_the_plugin_lost_its_callback_key(self):
        self.startup()
        FakePlugin.key = "lost"
        response = self.check()
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.lifecycle_status, Plugin.LIFECYCLE_ERROR)

    def test_only_staff_check_the_connection(self):
        user = User.objects.create_user("user", "user@test.com", "password")
        self.assertEqual(self.check(user).status_code, status.HTTP_403_FORBIDDEN)

    def test_resetting_the_token_changes_the_callback_key(self):
        before = callback_key(self.plugin)
        self.plugin.token = ""
        self.plugin.save()
        self.assertNotEqual(callback_key(self.plugin), before)
