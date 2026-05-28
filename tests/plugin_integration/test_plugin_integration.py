"""
End-to-end integration tests for the plugin system.

Requires two live servers:
  DJANGO_BASE_URL  - running cupcake backend  (default: http://localhost:8000)
  PLUGIN_BASE_URL  - running test plugin server (default: http://localhost:8001)
  ADMIN_USERNAME   - staff user on the Django server (default: admin)
  ADMIN_PASSWORD   - password                         (default: password)

Run after starting both servers:
    pytest tests/plugin_integration/test_plugin_integration.py -v

Test classes follow the real plugin lifecycle in order:
  1. TestPluginServerEndpoints   - plugin server serves correct data
  2. TestPluginStartup           - lifecycle transitions to running on boot
  3. TestPluginRegistration      - backend registration API (idempotency resets
                                   lifecycle so this must run after startup checks)
  4. TestPluginWidgetEndpoints   - widget endpoints declared in manifest reachable
  5. TestPluginPush              - plugin pushes messages via plugin token
  6. TestPluginReportProgress    - plugin reports progress stages
  7. TestPluginTeardown          - plugin reports stopped lifecycle
  8. TestPluginDeregister        - admin deactivates then deletes plugin record
"""

import json
import os
import urllib.error
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


def _patch(url: str, body: dict, token: str | None = None) -> dict | list:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="PATCH")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _delete(url: str, token: str | None = None) -> int:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="DELETE")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


@pytest.fixture(scope="module")
def token():
    """Obtain a JWT access token for the CI admin user."""
    data = _post(f"{DJANGO_BASE}/api/v1/auth/token/", {"username": USERNAME, "password": PASSWORD})
    return data["access"]


@pytest.fixture(scope="module")
def registered_plugin(token):
    """Return the ci-test-plugin record.

    If the plugin server already registered on boot, return that record without
    calling register again.  Re-registering resets lifecycle_status to installing
    which would break the startup tests.
    """
    all_plugins = _get(f"{API}/", token=token)
    plugins = all_plugins["results"] if "results" in all_plugins else all_plugins
    existing = next((p for p in plugins if p["name"] == "ci-test-plugin"), None)
    if existing:
        return existing
    manifest = _get(f"{PLUGIN_BASE}/manifest")
    return _post(
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


class TestPluginStartup:
    """Verify lifecycle is running after the plugin server called startup on boot.

    Runs before TestPluginRegistration because the idempotency test in that class
    calls register again which resets lifecycle_status to installing.
    """

    def test_lifecycle_is_running(self, token, registered_plugin):
        data = _get(f"{API}/{registered_plugin['id']}/", token=token)
        assert data["lifecycle_status"] == "running"

    def test_progress_message_is_running(self, token, registered_plugin):
        data = _get(f"{API}/{registered_plugin['id']}/", token=token)
        assert data["progress_message"] == "Running"

    def test_plugin_is_active(self, token, registered_plugin):
        data = _get(f"{API}/{registered_plugin['id']}/", token=token)
        assert data["is_active"] is True

    def test_base_url_stored_correctly(self, registered_plugin):
        assert registered_plugin["base_url"] == PLUGIN_BASE


class TestPluginRegistration:
    """Verify the registration API."""

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

    def test_manifest_cache_has_correct_widget_count(self, token, registered_plugin):
        data = _get(f"{API}/{registered_plugin['id']}/manifest/", token=token)
        assert data["name"] == "ci-test-plugin"
        assert len(data["pages"][0]["widgets"]) == 5


class TestPluginWidgetEndpoints:
    """Verify every GET widget endpoint declared in the manifest is reachable."""

    def test_all_get_widget_endpoints_return_data(self, token, registered_plugin):
        widgets = registered_plugin["manifest_cache"]["pages"][0]["widgets"]
        for widget in widgets:
            if not widget.get("endpoint") or widget["type"] == "form":
                continue
            url = f"{PLUGIN_BASE}{widget['endpoint']}"
            data = _get(url)
            assert data is not None, f"endpoint {url} returned no data"


class TestPluginPush:
    """Verify the plugin can push messages to CUPCAKE via its plugin token."""

    def test_push_returns_sent(self, token, registered_plugin):
        data = _post(f"{PLUGIN_BASE}/api/push", {"event": "test", "value": 42})
        assert data.get("sent") is True

    def test_push_with_nested_payload(self, token, registered_plugin):
        data = _post(f"{PLUGIN_BASE}/api/push", {"items": [1, 2, 3], "count": 3})
        assert data.get("sent") is True


class TestPluginReportProgress:
    """Verify the plugin can report progress stages to CUPCAKE."""

    def test_custom_progress_message_persists(self, token, registered_plugin):
        pid = registered_plugin["id"]
        _post(
            f"{PLUGIN_BASE}/api/report-progress",
            {
                "lifecycle_status": "running",
                "progress_message": "Processing data",
            },
        )
        data = _get(f"{API}/{pid}/", token=token)
        assert data["progress_message"] == "Processing data"

    def test_progress_data_persists(self, token, registered_plugin):
        pid = registered_plugin["id"]
        _post(
            f"{PLUGIN_BASE}/api/report-progress",
            {
                "lifecycle_status": "running",
                "progress_message": "Syncing",
                "progress_data": {"records_processed": 50, "total": 100},
            },
        )
        data = _get(f"{API}/{pid}/", token=token)
        assert data["progress_data"]["records_processed"] == 50
        assert data["progress_data"]["total"] == 100


class TestPluginTeardown:
    """Verify the plugin can report a stopped lifecycle."""

    def test_plugin_reports_stopped(self, token, registered_plugin):
        pid = registered_plugin["id"]
        _post(f"{PLUGIN_BASE}/api/stopped", {})
        data = _get(f"{API}/{pid}/", token=token)
        assert data["lifecycle_status"] == "stopped"
        assert data["progress_message"] == "Stopped"

    def test_plugin_record_still_exists_after_stopped(self, token, registered_plugin):
        data = _get(f"{API}/{registered_plugin['id']}/", token=token)
        assert data["id"] == registered_plugin["id"]


class TestPluginDeregister:
    """Verify the full deregistration sequence: deactivate then delete.

    Mirrors what cupcake-plugin-deregister does:
      1. PATCH is_active=false  -- invalidates plugin token immediately
      2. Verify plugin token is rejected
      3. DELETE               -- removes the backend record
      4. Verify record is gone
    """

    def test_deactivate_invalidates_token(self, token, registered_plugin):
        pid = registered_plugin["id"]
        _patch(f"{API}/{pid}/", {"is_active": False}, token=token)
        result = _post(f"{PLUGIN_BASE}/api/push", {"event": "post-deactivate"})
        assert result.get("status") == 401 or result.get("error") is not None

    def test_delete_returns_204(self, token, registered_plugin):
        pid = registered_plugin["id"]
        code = _delete(f"{API}/{pid}/", token=token)
        assert code == 204

    def test_plugin_absent_from_list(self, token, registered_plugin):
        data = _get(f"{API}/", token=token)
        ids = [p["id"] for p in (data["results"] if "results" in data else data)]
        assert registered_plugin["id"] not in ids

    def test_plugin_detail_returns_404(self, token, registered_plugin):
        try:
            _get(f"{API}/{registered_plugin['id']}/", token=token)
            assert False, "expected 404"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
