"""
Standalone test plugin server.

Starts an HTTP server that mimics a real plugin container.
After startup, registers itself with the cupcake backend.

Usage:
    python plugin_server.py --host 127.0.0.1 --port 8001 \
        --backend http://localhost:8000 \
        --username admin --password password
"""

import argparse
import json
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

_CARD_DATA = {"status": "ok", "version": "1.0.0", "uptime_seconds": 9999}
_LIST_DATA = [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}, {"id": 3, "name": "Gamma"}]
_TABLE_DATA = [
    {"id": 1, "event": "started", "ts": "2024-01-01T00:00:00Z"},
    {"id": 2, "event": "synced", "ts": "2024-01-01T01:00:00Z"},
]
_CHART_DATA = {
    "labels": ["Jan", "Feb", "Mar"],
    "datasets": [{"label": "Requests", "data": [120, 240, 180]}],
}


def _manifest(base_url: str) -> dict:
    return {
        "name": "ci-test-plugin",
        "displayName": "CI Test Plugin",
        "version": "1.0.0",
        "description": "Automated integration-test plugin",
        "baseUrl": base_url,
        "nav": [{"label": "Dashboard", "icon": "bi bi-speedometer2", "path": "dashboard"}],
        "pages": [
            {
                "path": "dashboard",
                "title": "Plugin Dashboard",
                "widgets": [
                    {"id": "w-card", "type": "card", "title": "Status", "endpoint": "/api/status"},
                    {"id": "w-list", "type": "list", "title": "Items", "endpoint": "/api/items"},
                    {
                        "id": "w-table",
                        "type": "table",
                        "title": "Events",
                        "endpoint": "/api/rows",
                        "columns": ["id", "event", "ts"],
                    },
                    {"id": "w-chart", "type": "chart", "title": "Metrics", "endpoint": "/api/chart"},
                    {
                        "id": "w-form",
                        "type": "form",
                        "title": "Submit",
                        "endpoint": "/api/submit",
                        "fields": ["name", "value"],
                    },
                ],
            }
        ],
    }


class _Handler(BaseHTTPRequestHandler):
    base_url: str = ""

    def do_GET(self):
        routes = {
            "/manifest": _manifest(self.base_url),
            "/api/status": _CARD_DATA,
            "/api/items": _LIST_DATA,
            "/api/rows": _TABLE_DATA,
            "/api/chart": _CHART_DATA,
        }
        if self.path in routes:
            self._json(200, routes[self.path])
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        self._json(200, {"success": True, "received": body})

    def _json(self, code: int, data) -> None:
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass


def _get_token(backend: str, username: str, password: str) -> str:
    url = f"{backend}/api/v1/auth/token/"
    body = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access"]


def _register(backend: str, token: str, base_url: str) -> dict:
    url = f"{backend}/api/v1/plugins/register/"
    body = json.dumps(
        {
            "name": "ci-test-plugin",
            "version": "1.0.0",
            "display_name": "CI Test Plugin",
            "description": "Automated integration-test plugin",
            "manifest": _manifest(base_url),
            "base_url": base_url,
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    """Parse arguments, start the HTTP server, register with the backend, and serve forever."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--backend", default="http://localhost:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="password")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"

    handler = type("Handler", (_Handler,), {"base_url": base_url})
    server = HTTPServer((args.host, args.port), handler)

    print(f"[plugin] server started at {base_url}", flush=True)

    token = _get_token(args.backend, args.username, args.password)
    result = _register(args.backend, token, base_url)
    print(f"[plugin] registered with backend, id={result.get('id')}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[plugin] shutting down", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
