"""The plugin against a fake CUPCAKE backend that runs the real handshake."""

import importlib.util
import json
import secrets
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("plugin_under_test", ROOT / "plugin.py")
plugin = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = plugin
SPEC.loader.exec_module(plugin)

TOKEN = "t" * 64


class FakeBackend(BaseHTTPRequestHandler):
    """Records plugin calls and, on startup, runs the backend's handshake with the announced address."""

    calls: list = []
    callback_key = "k" * 64

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Plugin-Token") != TOKEN:
            self.answer(401, {"detail": "Invalid or inactive plugin token."})
            return
        path = self.path.removeprefix("/api/v1/")
        type(self).calls.append((path, body))
        if path == "plugins/startup/" and not self.handshake(body["base_url"]):
            self.answer(502, {"error": "CUPCAKE could not reach the plugin"})
            return
        self.answer(200, {"ok": True})

    def handshake(self, base_url):
        nonce = secrets.token_hex(8)
        request = urllib.request.Request(
            f"{base_url}/cupcake/handshake",
            data=json.dumps({"nonce": nonce, "callback_key": self.callback_key}).encode(),
            headers={
                "Content-Type": "application/json",
                "Cupcake-Signature": plugin.sign(TOKEN, f"handshake:{nonce}:{self.callback_key}"),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read()).get("proof") == plugin.sign(TOKEN, f"proof:{nonce}")
        except urllib.error.URLError:
            return False

    def answer(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


class PluginTests(unittest.TestCase):
    def setUp(self):
        FakeBackend.calls = []
        self.backend_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend)
        threading.Thread(target=self.backend_server.serve_forever, daemon=True).start()
        self.addCleanup(self.backend_server.server_close)
        self.addCleanup(self.backend_server.shutdown)
        self.backend = plugin.Backend(f"http://127.0.0.1:{self.backend_server.server_port}", TOKEN)
        self.manifest = plugin.read_manifest()
        server, _ = plugin.serve(self.manifest, TOKEN, 0, host="127.0.0.1")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base_url = f"http://127.0.0.1:{server.server_port}"

    def get(self, path, key=None):
        request = urllib.request.Request(f"{self.base_url}{path}", headers={"Cupcake-Key": key or ""})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read())

    def test_startup_completes_the_handshake(self):
        plugin.announce(self.backend, self.base_url, self.manifest)
        self.assertEqual(self.get("/cupcake/ping", FakeBackend.callback_key)["name"], self.manifest["name"])

    def test_the_status_card_answers_only_the_backend(self):
        plugin.announce(self.backend, self.base_url, self.manifest)
        self.assertIn("Updated", self.get("/api/status", FakeBackend.callback_key))
        with self.assertRaises(urllib.error.HTTPError) as refused:
            self.get("/api/status", "wrong")
        self.assertEqual(refused.exception.code, 401)

    def test_health_answers_anyone(self):
        self.assertEqual(self.get("/health")["name"], self.manifest["name"])

    def test_the_status_is_pushed_to_the_page(self):
        plugin.publish(self.backend)
        pushed = [body["payload"] for path, body in FakeBackend.calls if path == "plugins/push/"]
        self.assertEqual(pushed[0]["widget"], "status")

    def test_a_refused_startup_stops_the_plugin(self):
        with self.assertRaises(SystemExit):
            plugin.announce(self.backend, "http://127.0.0.1:1", self.manifest)


if __name__ == "__main__":
    unittest.main()
