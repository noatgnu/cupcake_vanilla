"""The vocabulary plugin against a fake CUPCAKE backend that runs the real handshake."""

import importlib.util
import json
import secrets
import sys
import tempfile
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
    """Records the terms sent and, on startup, runs the backend's handshake with the announced address."""

    calls: list = []
    callback_key = "k" * 64

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Plugin-Token") != TOKEN:
            self.answer(401, {"detail": "Invalid or inactive plugin token."})
            return
        path = self.path.removeprefix("/api/v1/")
        type(self).calls.append((path, body))
        if path == "plugins/startup/":
            if not self.handshake(body["base_url"]):
                self.answer(502, {"error": "CUPCAKE could not reach the plugin"})
                return
            self.answer(200, {"lifecycle_status": "running"})
        elif path.endswith("/terms/"):
            self.answer(200, {"stored": len(body["terms"]), "received_at": "2026-01-01T00:00:00Z"})
        elif path.endswith("/finish/"):
            sent = sum(len(b["terms"]) for p, b in self.calls if p.endswith("/terms/"))
            self.answer(200, {"key": path.split("/")[1], "term_count": sent, "approved": False, "removed": 0})
        else:
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


class VocabularyPluginTests(unittest.TestCase):
    def setUp(self):
        FakeBackend.calls = []
        self.backend_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend)
        threading.Thread(target=self.backend_server.serve_forever, daemon=True).start()
        self.addCleanup(self.backend_server.server_close)
        self.addCleanup(self.backend_server.shutdown)
        self.backend = plugin.Backend(f"http://127.0.0.1:{self.backend_server.server_port}", TOKEN)
        self.manifest = plugin.read_manifest()
        self.key = self.manifest["vocabularies"][0]["key"]
        server, _ = plugin.serve(self.manifest, TOKEN, 0, host="127.0.0.1")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base_url = f"http://127.0.0.1:{server.server_port}"

    def test_every_declared_vocabulary_has_a_terms_file(self):
        for vocabulary in self.manifest["vocabularies"]:
            self.assertTrue(list(plugin.load_terms(vocabulary["key"])), vocabulary["key"])

    def test_terms_have_an_id_and_a_name(self):
        for term in plugin.load_terms(self.key):
            self.assertTrue(term["id"] and term["name"])

    def test_startup_completes_the_handshake(self):
        plugin.announce(self.backend, self.base_url, self.manifest)
        request = urllib.request.Request(
            f"{self.base_url}/cupcake/ping", headers={"Cupcake-Key": FakeBackend.callback_key}
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(json.loads(response.read())["name"], self.manifest["name"])

    def test_terms_are_sent_in_batches_of_at_most_a_thousand(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = "".join(f"T:{index:05d}\tterm {index}\t\t\t\n" for index in range(2500))
            Path(directory, f"{self.key}.tsv").write_text("id\tname\tdescription\tsynonyms\tobsolete\n" + rows)
            result = plugin.sync_vocabulary(self.backend, self.key, plugin.load_terms(self.key, Path(directory)))
        sizes = [len(body["terms"]) for path, body in FakeBackend.calls if path.endswith("/terms/")]
        self.assertEqual((sizes, result["term_count"]), ([1000, 1000, 500], 2500))


if __name__ == "__main__":
    unittest.main()
