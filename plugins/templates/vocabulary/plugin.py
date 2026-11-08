"""
CUPCAKE vocabulary plugin template.

Announces the vocabularies in manifest.json to the CUPCAKE backend, sends their terms in batches and
reloads them on a schedule. Terms come from ``terms/<key>.tsv`` (columns id, name, description, synonyms
separated by ``;``, obsolete); replace ``load_terms`` to read them from another source.

Environment:
  PLUGIN_TOKEN       startup token written by ``cupcake-plugin register`` (required)
  CUPCAKE_BACKEND    backend address, for example http://localhost:8000 (required)
  PLUGIN_PORT        port of the plugin's health endpoint (default 8101)
  PLUGIN_BASE_URL    address the browser uses to reach the plugin (default http://localhost:<port>)
  REFRESH_HOURS      hours between reloads; 0 loads once (default 24)
"""

from __future__ import annotations

import csv
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
BATCH_SIZE = 1000
TRUE_VALUES = {"1", "true", "yes", "y"}

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
    """Load every vocabulary of the manifest, reporting progress to the backend."""
    vocabularies = manifest.get("vocabularies", [])
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


class HealthHandler(BaseHTTPRequestHandler):
    """Answers /health with the plugin's name and version."""

    manifest: dict = {}

    def do_GET(self):
        if self.path.rstrip("/") != "/health":
            self.send_error(404)
            return
        body = json.dumps({"name": self.manifest.get("name"), "version": self.manifest.get("version")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        logger.debug(format, *args)


def main() -> None:
    """Announce the plugin, serve its health endpoint and keep its vocabularies loaded."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    manifest = read_manifest()
    port = int(os.environ.get("PLUGIN_PORT", "8101"))
    base_url = os.environ.get("PLUGIN_BASE_URL", f"http://localhost:{port}")
    refresh_hours = float(os.environ.get("REFRESH_HOURS", "24"))
    backend = Backend(os.environ["CUPCAKE_BACKEND"], os.environ["PLUGIN_TOKEN"])

    HealthHandler.manifest = manifest
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    backend.post("plugins/startup/", {"base_url": base_url, "manifest": manifest})
    threading.Thread(target=refresh_loop, args=(backend, manifest, refresh_hours), daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
