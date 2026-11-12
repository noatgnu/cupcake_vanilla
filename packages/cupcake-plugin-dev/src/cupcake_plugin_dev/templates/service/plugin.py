"""
__DISPLAY_NAME__: a CUPCAKE plugin with a page that updates live.

Environment:
  PLUGIN_TOKEN       startup token written when the plugin is registered (required)
  CUPCAKE_BACKEND    backend address, for example http://localhost:8000 (required)
  PLUGIN_HOST        address the plugin listens on (default 0.0.0.0)
  PLUGIN_PORT        port the plugin serves on (default __PORT__)
  PLUGIN_BASE_URL    address the backend reaches the plugin at (default http://localhost:<port>)
  INTERVAL_SECONDS   seconds between live updates (default 5)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
STARTED = time.monotonic()

logger = logging.getLogger("__PLUGIN_NAME__")


def status() -> dict:
    """The status card: one row per key, in this order."""
    return {
        "Running for": f"{int(time.monotonic() - STARTED)} s",
        "Updated": datetime.now().strftime("%H:%M:%S"),
    }


class Backend:
    """Calls to the CUPCAKE backend authenticated with the plugin token."""

    def __init__(self, base_url: str, token: str, timeout: float = 30):
        """Call the backend at base_url with the plugin token."""
        self.base_url = base_url.rstrip("/") + "/api/v1/"
        self.token = token
        self.timeout = timeout

    def post(self, path: str, body: dict) -> dict:
        """POST a JSON body and return the decoded JSON response."""
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Plugin-Token": self.token, "Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read() or b"null")


def read_manifest(path: Path = HERE / "manifest.json") -> dict:
    """The plugin manifest."""
    return json.loads(path.read_text())


def sign(secret: str, message: str) -> str:
    """The hex HMAC-SHA256 of message keyed with secret."""
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


class PluginHandler(BaseHTTPRequestHandler):
    """The plugin's endpoints: /health for anyone, the handshake, and the rest for the backend only."""

    manifest: dict = {}
    token: str = ""
    callback_key: str = ""

    def do_GET(self):
        path = urlsplit(self.path).path.rstrip("/")
        identity = {"name": self.manifest.get("name"), "version": self.manifest.get("version")}
        if path == "/health":
            self.send_json(200, identity)
            return
        if not self.from_backend():
            self.send_json(401, {"error": "Cupcake-Key missing or not valid"})
            return
        routes = {"/cupcake/ping": lambda: identity, "/api/status": status}
        if path in routes:
            self.send_json(200, routes[path]())
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if urlsplit(self.path).path.rstrip("/") != "/cupcake/handshake":
            self.send_json(404, {"error": "Not found"})
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            nonce, key = str(body["nonce"]), str(body["callback_key"])
        except (ValueError, KeyError, TypeError):
            self.send_json(400, {"error": "Handshake needs a nonce and a callback_key"})
            return
        if not hmac.compare_digest(
            self.headers.get("Cupcake-Signature", ""), sign(self.token, f"handshake:{nonce}:{key}")
        ):
            self.send_json(401, {"error": "Handshake not signed with this plugin's token"})
            return
        type(self).callback_key = key
        self.send_json(200, {"name": self.manifest.get("name"), "proof": sign(self.token, f"proof:{nonce}")})

    def from_backend(self) -> bool:
        """Whether the request carries the callback key from the last handshake."""
        key = self.headers.get("Cupcake-Key", "")
        return bool(self.callback_key) and hmac.compare_digest(key, self.callback_key)

    def send_json(self, code: int, body) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        logger.debug(format, *args)


def serve(manifest: dict, token: str, port: int, host: str = "0.0.0.0") -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Serve the plugin's endpoints on port in a background thread."""
    PluginHandler.manifest = manifest
    PluginHandler.token = token
    PluginHandler.callback_key = ""
    server = ThreadingHTTPServer((host, port), PluginHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def announce(backend: Backend, base_url: str, manifest: dict) -> dict:
    """
    Announce the plugin to the backend.

    Raises:
        SystemExit: When the backend cannot be reached or refuses the startup.
    """
    try:
        return backend.post("plugins/startup/", {"base_url": base_url, "manifest": manifest})
    except urllib.error.HTTPError as error:
        logger.error("Startup refused (%s): %s", error.code, error.read().decode(errors="replace"))
        raise SystemExit(1)
    except (urllib.error.URLError, OSError) as error:
        logger.error("Could not reach the backend at %s: %s", backend.base_url, error)
        raise SystemExit(1)


def publish(backend: Backend) -> None:
    """Push the status card to everyone viewing the page."""
    backend.post("plugins/push/", {"payload": {"widget": "status", "data": status()}})


def report_loop(backend: Backend, interval: float, stop: threading.Event) -> None:
    """Publish every interval seconds until stop is set."""
    reported = False
    while not stop.is_set():
        try:
            publish(backend)
            if not reported:
                backend.post("plugins/report-progress/", {"lifecycle_status": "running", "progress_message": "Running"})
                reported = True
        except (urllib.error.URLError, OSError, ValueError) as error:
            logger.warning("Could not reach the backend: %s", error)
            reported = False
        stop.wait(interval)


def main() -> None:
    """Serve the endpoints, announce the plugin and publish its status."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    manifest = read_manifest()
    port = int(os.environ.get("PLUGIN_PORT", "__PORT__"))
    base_url = os.environ.get("PLUGIN_BASE_URL", f"http://localhost:{port}")
    interval = max(float(os.environ.get("INTERVAL_SECONDS", "5")), 1)
    token = os.environ["PLUGIN_TOKEN"]
    backend = Backend(os.environ["CUPCAKE_BACKEND"], token)

    _, server_thread = serve(manifest, token, port, host=os.environ.get("PLUGIN_HOST", "0.0.0.0"))
    announce(backend, base_url, manifest)
    threading.Thread(target=report_loop, args=(backend, interval, threading.Event()), daemon=True).start()
    server_thread.join()


if __name__ == "__main__":
    main()
