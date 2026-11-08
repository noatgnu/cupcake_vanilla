"""
Calls from the backend to a plugin at the address the plugin registered.

When a plugin starts, the backend checks the connection in both directions with a handshake: it posts
a nonce and the plugin's callback key to ``<base_url>/cupcake/handshake``, signed with the plugin's
token, and the plugin answers with a proof made from the same token. Later calls carry the callback
key in the ``Cupcake-Key`` header.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from django.conf import settings
from django.utils.crypto import salted_hmac

import requests

from ccc.plugin.model import Plugin

HANDSHAKE_PATH = "cupcake/handshake"
PING_PATH = "cupcake/ping"
SIGNATURE_HEADER = "Cupcake-Signature"
KEY_HEADER = "Cupcake-Key"


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
