"""
CUPCAKE vocabulary plugin template: provides the vocabularies in manifest.json from ``terms/<key>.tsv``.

Environment:
  PLUGIN_TOKEN       startup token written by ``cupcake-plugin register`` (required)
  CUPCAKE_BACKEND    backend address, for example http://localhost:8000 (required)
  PLUGIN_PORT        port the plugin serves on (default 8101)
  PLUGIN_BASE_URL    address the backend reaches the plugin at (default http://localhost:<port>)
  REFRESH_HOURS      hours between reloads; 0 loads once (default 24)
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
BATCH_SIZE = 1000
SEARCH_LIMIT = 25
TRUE_VALUES = {"1", "true", "yes", "y"}
SEARCH_PATH = re.compile(r"^/cupcake/vocabularies/([a-z0-9][a-z0-9_]*)/search$")

logger = logging.getLogger("vocabulary-plugin")


class Backend:
    """Calls to the CUPCAKE backend authenticated with the plugin token."""

    def __init__(self, base_url: str, token: str, timeout: float = 60):
        """Call the backend at base_url with the plugin token."""
        self.base_url = base_url.rstrip("/") + "/api/v1/"
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, body: dict | None = None) -> dict | list:
        """Send a JSON request and return the decoded JSON response."""
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Plugin-Token": self.token, "Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read() or b"null")

    def post(self, path: str, body: dict) -> dict:
        return self.request("POST", path, body)

    def get(self, path: str) -> dict | list:
        return self.request("GET", path)


def read_manifest(path: Path = HERE / "manifest.json") -> dict:
    """The plugin manifest."""
    return json.loads(path.read_text())


def live_search_keys(manifest: dict) -> set[str]:
    """Keys of the vocabularies declared with ``liveSearch``."""
    return {entry["key"] for entry in manifest.get("vocabularies", []) if entry.get("liveSearch") is True}


def load_terms(local_key: str, directory: Path = HERE / "terms") -> Iterator[dict]:
    """
    Terms of one vocabulary as the backend expects them.

    Reads ``<directory>/<local_key>.tsv``; rows without an id or a name are skipped.
    """
    with open(directory / f"{local_key}.tsv", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            term_id = (row.get("id") or "").strip()
            name = (row.get("name") or "").strip()
            if not term_id or not name:
                continue
            yield {
                "id": term_id,
                "name": name,
                "description": (row.get("description") or "").strip(),
                "synonyms": [part.strip() for part in (row.get("synonyms") or "").split(";") if part.strip()],
                "obsolete": (row.get("obsolete") or "").strip().lower() in TRUE_VALUES,
            }


def search_terms(local_key: str, text: str, limit: int) -> list[dict]:
    """Terms of a live-search vocabulary whose id, name or a synonym contains text, at most limit of them."""
    needle = text.strip().casefold()
    found = []
    for term in load_terms(local_key):
        if term["obsolete"]:
            continue
        if any(needle in value.casefold() for value in (term["id"], term["name"], *term["synonyms"])):
            found.append(term)
            if len(found) >= limit:
                break
    return found


def batches(terms: Iterable[dict], size: int = BATCH_SIZE) -> Iterator[list[dict]]:
    """Terms in lists of at most size."""
    batch: list[dict] = []
    for term in terms:
        batch.append(term)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def sync_vocabulary(backend: Backend, local_key: str, terms: Iterable[dict], version: str = "") -> dict:
    """
    Send all terms of one vocabulary and finish the load, removing the terms that were not sent again.

    Returns:
        The vocabulary as the backend reports it after the load.
    """
    replace_before = None
    sent = 0
    for batch in batches(terms):
        stored = backend.post(f"plugin-vocabularies/{local_key}/terms/", {"terms": batch})
        replace_before = replace_before or stored["received_at"]
        sent += len(batch)
        logger.info("%s: sent %d terms", local_key, sent)
    return backend.post(
        f"plugin-vocabularies/{local_key}/finish/", {"replace_before": replace_before, "version": version}
    )


def sync_all(backend: Backend, manifest: dict) -> None:
    """Load every vocabulary of the manifest that is not searched live, reporting progress to the backend."""
    live = live_search_keys(manifest)
    vocabularies = [entry for entry in manifest.get("vocabularies", []) if entry["key"] not in live]
    for index, vocabulary in enumerate(vocabularies, start=1):
        local_key = vocabulary["key"]
        backend.post(
            "plugins/report-progress/",
            {
                "progress_message": f"Loading {vocabulary['label']}",
                "progress_data": {"step": index, "total": len(vocabularies)},
            },
        )
        try:
            result = sync_vocabulary(backend, local_key, load_terms(local_key), manifest.get("version", ""))
        except (OSError, urllib.error.URLError, KeyError, ValueError) as error:
            logger.error("%s: load failed: %s", local_key, error)
            continue
        state = "approved" if result["approved"] else "waiting for staff approval"
        logger.info("%s: %d terms, %s", result["key"], result["term_count"], state)
    backend.post("plugins/report-progress/", {"lifecycle_status": "running", "progress_message": "Running"})


def refresh_loop(backend: Backend, manifest: dict, refresh_hours: float) -> None:
    """Load every vocabulary now and then again every refresh_hours; once when refresh_hours is 0."""
    while True:
        sync_all(backend, manifest)
        if refresh_hours <= 0:
            return
        time.sleep(refresh_hours * 3600)


def sign(secret: str, message: str) -> str:
    """The hex HMAC-SHA256 of message keyed with secret."""
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


class PluginHandler(BaseHTTPRequestHandler):
    """The plugin's endpoints: /health, the handshake, and ping and search for the backend."""

    manifest: dict = {}
    token: str = ""
    callback_key: str = ""

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path.rstrip("/")
        if path == "/health":
            self.send_json(200, {"name": self.manifest.get("name"), "version": self.manifest.get("version")})
            return
        if not self.from_backend():
            self.send_json(401, {"error": "Cupcake-Key missing or not valid"})
            return
        if path == "/cupcake/ping":
            self.send_json(200, {"name": self.manifest.get("name"), "version": self.manifest.get("version")})
            return
        match = SEARCH_PATH.match(path)
        if not match or match.group(1) not in live_search_keys(self.manifest):
            self.send_json(404, {"error": "Not found"})
            return
        query = parse_qs(url.query)
        text = (query.get("q") or [""])[0]
        try:
            limit = min(max(int((query.get("limit") or [SEARCH_LIMIT])[0]), 1), SEARCH_LIMIT)
        except ValueError:
            limit = SEARCH_LIMIT
        try:
            results = search_terms(match.group(1), text, limit) if text.strip() else []
        except OSError as error:
            logger.error("%s: search failed: %s", match.group(1), error)
            self.send_json(503, {"error": "Search failed"})
            return
        self.send_json(200, {"results": results})

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
        expected = sign(self.token, f"handshake:{nonce}:{key}")
        if not hmac.compare_digest(self.headers.get("Cupcake-Signature", ""), expected):
            self.send_json(401, {"error": "Handshake not signed with this plugin's token"})
            return
        type(self).callback_key = key
        self.send_json(200, {"name": self.manifest.get("name"), "proof": sign(self.token, f"proof:{nonce}")})

    def from_backend(self) -> bool:
        """Whether the request carries the callback key from the last handshake."""
        key = self.headers.get("Cupcake-Key", "")
        return bool(self.callback_key) and hmac.compare_digest(key, self.callback_key)

    def send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        logger.debug(format, *args)


def serve(manifest: dict, token: str, port: int, host: str = "0.0.0.0") -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Serve the plugin's endpoints on port in a background thread."""
    PluginHandler.manifest = manifest
    PluginHandler.token = token
    server = ThreadingHTTPServer((host, port), PluginHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def announce(backend: Backend, base_url: str, manifest: dict) -> dict:
    """
    Announce the plugin to the backend.

    Raises:
        SystemExit: When the backend refuses the startup.
    """
    try:
        return backend.post("plugins/startup/", {"base_url": base_url, "manifest": manifest})
    except urllib.error.HTTPError as error:
        logger.error("Startup refused (%s): %s", error.code, error.read().decode(errors="replace"))
        raise SystemExit(1)


def main() -> None:
    """Serve the plugin's endpoints, announce the plugin and keep its vocabularies loaded."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    manifest = read_manifest()
    port = int(os.environ.get("PLUGIN_PORT", "8101"))
    base_url = os.environ.get("PLUGIN_BASE_URL", f"http://localhost:{port}")
    refresh_hours = float(os.environ.get("REFRESH_HOURS", "24"))
    token = os.environ["PLUGIN_TOKEN"]
    backend = Backend(os.environ["CUPCAKE_BACKEND"], token)

    _, server_thread = serve(manifest, token, port)
    announce(backend, base_url, manifest)
    threading.Thread(target=refresh_loop, args=(backend, manifest, refresh_hours), daemon=True).start()
    server_thread.join()


if __name__ == "__main__":
    main()
