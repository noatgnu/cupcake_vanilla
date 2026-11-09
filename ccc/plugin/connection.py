"""Calls from the backend to a plugin at its registered address."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets

from django.conf import settings
from django.utils.crypto import salted_hmac

import requests

from ccc.plugin.model import Plugin

HANDSHAKE_PATH = "cupcake/handshake"
PING_PATH = "cupcake/ping"
SIGNATURE_HEADER = "Cupcake-Signature"
KEY_HEADER = "Cupcake-Key"
USER_ID_HEADER = "Cupcake-User-Id"
USERNAME_HEADER = "Cupcake-Username"
USER_STAFF_HEADER = "Cupcake-User-Staff"
GET_WIDGET_TYPES = {"card", "list", "table", "chart"}


class PluginConnectionError(Exception):
    """Raised when the backend cannot reach a plugin or the plugin's answer is not valid."""


def callback_key(plugin: Plugin) -> str:
    """The key the backend sends with its calls to the plugin; it changes when the plugin's token is reset."""
    return salted_hmac("ccc.plugin.callback", plugin.token, algorithm="sha256").hexdigest()


def sign(secret: str, message: str) -> str:
    """The hex HMAC-SHA256 of message keyed with secret."""
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def plugin_url(base_url: str, path: str) -> str:
    """The address of path on the plugin at base_url."""
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _json(response: requests.Response) -> dict:
    if response.status_code != 200:
        raise PluginConnectionError(f"answered {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise PluginConnectionError("answered with something other than JSON")
    if not isinstance(body, dict):
        raise PluginConnectionError("answered with JSON that is not an object")
    return body


def verify_connection(plugin: Plugin, plain_token: str, base_url: str) -> None:
    """
    Run the handshake with the plugin at base_url.

    Raises:
        PluginConnectionError: When the plugin cannot be reached, or its answer is not signed with its token.
    """
    nonce = secrets.token_hex(16)
    key = callback_key(plugin)
    try:
        response = requests.post(
            plugin_url(base_url, HANDSHAKE_PATH),
            json={"plugin": plugin.name, "nonce": nonce, "callback_key": key},
            headers={SIGNATURE_HEADER: sign(plain_token, f"handshake:{nonce}:{key}")},
            timeout=settings.PLUGIN_CONNECTION_TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as error:
        raise PluginConnectionError(str(error))
    body = _json(response)
    if body.get("name") != plugin.name:
        raise PluginConnectionError(f"answered as {body.get('name')!r} instead of {plugin.name!r}")
    if not hmac.compare_digest(str(body.get("proof", "")), sign(plain_token, f"proof:{nonce}")):
        raise PluginConnectionError("answered without a valid proof of its token")


def call_plugin(plugin: Plugin, path: str, params: dict | None = None, timeout: float | None = None) -> dict:
    """
    GET path from the plugin with its callback key and return the JSON object it answers.

    Raises:
        PluginConnectionError: When the plugin has no address, cannot be reached or does not answer with a JSON object.
    """
    if not plugin.base_url:
        raise PluginConnectionError("has no registered address")
    try:
        response = requests.get(
            plugin_url(plugin.base_url, path),
            params=params,
            headers={KEY_HEADER: callback_key(plugin), "Accept": "application/json"},
            timeout=timeout or settings.PLUGIN_CONNECTION_TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as error:
        raise PluginConnectionError(str(error))
    return _json(response)


def ping(plugin: Plugin) -> None:
    """
    Check that the plugin answers at its registered address and still holds its callback key.

    Raises:
        PluginConnectionError: When it does not.
    """
    body = call_plugin(plugin, PING_PATH)
    if body.get("name") != plugin.name:
        raise PluginConnectionError(f"answered as {body.get('name')!r} instead of {plugin.name!r}")


def declared_calls(manifest: dict) -> set[tuple[str, str]]:
    """The (method, endpoint) pairs declared by the widgets and widget actions of the manifest's pages."""
    calls: set[tuple[str, str]] = set()
    pages = (manifest or {}).get("pages") or []
    for page in pages if isinstance(pages, list) else []:
        widgets = page.get("widgets") if isinstance(page, dict) else None
        for widget in widgets if isinstance(widgets, list) else []:
            if not isinstance(widget, dict):
                continue
            endpoint = widget.get("endpoint")
            if isinstance(endpoint, str) and endpoint:
                if widget.get("type") in GET_WIDGET_TYPES:
                    calls.add(("GET", endpoint))
                elif widget.get("type") == "form":
                    calls.add(("POST", endpoint))
            for action in widget.get("actions") or []:
                if isinstance(action, dict) and isinstance(action.get("endpoint"), str):
                    calls.add((str(action.get("method", "GET")).upper(), action["endpoint"]))
    return calls


def forward(plugin: Plugin, method: str, endpoint: str, user, data: dict | None = None) -> tuple[int, object]:
    """
    Call a plugin endpoint for a user with the callback key and user headers; return the status and JSON answered.

    Raises:
        PluginConnectionError: When the plugin cannot be reached, answers too much, answers something other
            than JSON, or fails with a server error.
    """
    if not plugin.base_url:
        raise PluginConnectionError("has no registered address")
    headers = {
        KEY_HEADER: callback_key(plugin),
        USER_ID_HEADER: str(user.pk),
        USERNAME_HEADER: user.get_username(),
        USER_STAFF_HEADER: "true" if user.is_staff else "false",
        "Accept": "application/json",
    }
    try:
        response = requests.request(
            method,
            plugin_url(plugin.base_url, endpoint),
            json=data if method != "GET" else None,
            headers=headers,
            timeout=settings.PLUGIN_CONNECTION_TIMEOUT,
            allow_redirects=False,
            stream=True,
        )
        content = b""
        for chunk in response.iter_content(65536):
            content += chunk
            if len(content) > settings.PLUGIN_RESPONSE_MAX_BYTES:
                response.close()
                raise PluginConnectionError(f"answered more than {settings.PLUGIN_RESPONSE_MAX_BYTES} bytes")
    except requests.RequestException as error:
        raise PluginConnectionError(str(error))
    if response.status_code >= 500:
        raise PluginConnectionError(f"answered {response.status_code}")
    try:
        body = json.loads(content) if content else None
    except ValueError:
        raise PluginConnectionError("answered with something other than JSON")
    return response.status_code, body
