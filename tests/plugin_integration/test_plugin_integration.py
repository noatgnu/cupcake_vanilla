"""
End-to-end integration tests for the plugin system.

Requires two live servers:
  DJANGO_BASE_URL  - running cupcake backend  (default: http://localhost:8000)
  PLUGIN_BASE_URL  - running test plugin server (default: http://localhost:8001)
  ADMIN_USERNAME   - staff user on the Django server (default: admin)
  ADMIN_PASSWORD   - password                         (default: password)

Run after starting both servers:
    pytest tests/plugin_integration/test_plugin_integration.py -v
"""

import json
import os
import urllib.request

import pytest

DJANGO_BASE = os.environ.get("DJANGO_BASE_URL", "http://localhost:8000")
PLUGIN_BASE = os.environ.get("PLUGIN_BASE_URL", "http://localhost:8001")
USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "password")

API = f"{DJANGO_BASE}/api/v1/plugins"


def _get(url: str, token: str | None = None) -> dict | list:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _post(url: str, body: dict, token: str | None = None) -> dict | list:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


@pytest.fixture(scope="module")
def token():
    """Obtain a JWT access token for the CI admin user."""
    data = _post(f"{DJANGO_BASE}/api/v1/auth/token/", {"username": USERNAME, "password": PASSWORD})
    return data["access"]


@pytest.fixture(scope="module")
def registered_plugin(token):
    """Ensure the test plugin is registered and return its record."""
    manifest = _get(f"{PLUGIN_BASE}/manifest")
    data = _post(
        f"{API}/register/",
        {
            "name": "ci-test-plugin",
            "version": "1.0.0",
            "display_name": "CI Test Plugin",
            "manifest": manifest,
            "base_url": PLUGIN_BASE,
        },
        token=token,
    )
    return data


class TestPluginServerEndpoints:
    """Verify the plugin server itself serves correct data."""

    def test_manifest_has_required_fields(self):
        data = _get(f"{PLUGIN_BASE}/manifest")
        assert data["name"] == "ci-test-plugin"
        assert "pages" in data
        assert data["baseUrl"] == PLUGIN_BASE

    def test_card_endpoint_returns_dict(self):
        data = _get(f"{PLUGIN_BASE}/api/status")
        assert isinstance(data, dict)
        assert data["status"] == "ok"

    def test_list_endpoint_returns_list(self):
        data = _get(f"{PLUGIN_BASE}/api/items")
        assert isinstance(data, list)
        assert len(data) > 0

    def test_table_endpoint_returns_rows(self):
        data = _get(f"{PLUGIN_BASE}/api/rows")
        assert isinstance(data, list)
        assert "event" in data[0]

    def test_chart_endpoint_returns_labels_and_datasets(self):
        data = _get(f"{PLUGIN_BASE}/api/chart")
        assert "labels" in data
        assert "datasets" in data

    def test_form_post_returns_success(self):
        data = _post(f"{PLUGIN_BASE}/api/submit", {"name": "test", "value": "42"})
        assert data["success"] is True
        assert data["received"]["name"] == "test"


class TestPluginRegistration:
    """Verify registration through the Django backend API."""

    def test_register_returns_plugin_record(self, token, registered_plugin):
        assert "id" in registered_plugin
        assert registered_plugin["name"] == "ci-test-plugin"

    def test_register_is_idempotent(self, token, registered_plugin):
        manifest = _get(f"{PLUGIN_BASE}/manifest")
        second = _post(
            f"{API}/register/",
            {"name": "ci-test-plugin", "version": "1.0.0", "manifest": manifest, "base_url": PLUGIN_BASE},
            token=token,
        )
        assert second["id"] == registered_plugin["id"]

    def test_plugin_appears_in_list(self, token, registered_plugin):
        data = _get(f"{API}/", token=token)
        ids = [p["id"] for p in (data["results"] if "results" in data else data)]
        assert registered_plugin["id"] in ids

    def test_plugin_detail_accessible(self, token, registered_plugin):
        pid = registered_plugin["id"]
        data = _get(f"{API}/{pid}/", token=token)
        assert data["id"] == pid
        assert data["base_url"] == PLUGIN_BASE

    def test_manifest_cache_reflects_plugin_server(self, token, registered_plugin):
        pid = registered_plugin["id"]
        data = _get(f"{API}/{pid}/manifest/", token=token)
        assert data["name"] == "ci-test-plugin"
        assert data["baseUrl"] == PLUGIN_BASE
        assert len(data["pages"][0]["widgets"]) == 5

    def test_base_url_stored_correctly(self, registered_plugin):
        assert registered_plugin["base_url"] == PLUGIN_BASE


class TestPluginWidgetEndpointsReachable:
    """Verify every widget endpoint declared in the manifest is actually reachable."""

    def test_all_get_widget_endpoints_return_200(self, token, registered_plugin):
        widgets = registered_plugin["manifest_cache"]["pages"][0]["widgets"]
        for widget in widgets:
            if not widget.get("endpoint") or widget["type"] == "form":
                continue
            url = f"{PLUGIN_BASE}{widget['endpoint']}"
            data = _get(url)
            assert data is not None, f"endpoint {url} returned no data"
