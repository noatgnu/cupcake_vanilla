"""State of the remote access set up on the appliance: Tailscale and the Cloudflare tunnel."""

from __future__ import annotations

import json
import shutil
import subprocess

from django.conf import settings

import requests

COMMAND_TIMEOUT = 5
TAILSCALE_NOT_SET_UP = {"NoState", "NeedsLogin"}


def _run(*command: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=COMMAND_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None


def tailscale_status() -> dict:
    """
    Tailscale as ``tailscale status`` reports it.

    Returns:
        ``installed``, ``configured`` (logged in to a tailnet), ``connected``, ``state``, ``dns_name``,
        ``addresses``, ``online``, ``health`` and ``error``.
    """
    status = {
        "installed": bool(shutil.which("tailscale")),
        "configured": False,
        "connected": False,
        "state": "",
        "dns_name": "",
        "addresses": [],
        "online": False,
        "health": [],
        "error": "",
    }
    if not status["installed"]:
        return status
    result = _run("tailscale", "status", "--json")
    try:
        report = json.loads(result.stdout) if result else None
    except ValueError:
        report = None
    if not isinstance(report, dict):
        status["error"] = (result.stderr.strip() if result else "") or "tailscale did not answer"
        return status
    me = report.get("Self") or {}
    status.update(
        state=report.get("BackendState", ""),
        configured=report.get("BackendState", "") not in TAILSCALE_NOT_SET_UP,
        connected=report.get("BackendState") == "Running",
        dns_name=(me.get("DNSName") or "").rstrip("."),
        addresses=list(me.get("TailscaleIPs") or []),
        online=bool(me.get("Online")),
        health=[str(issue) for issue in report.get("Health") or []],
    )
    return status


def _systemctl(verb: str, unit: str) -> str:
    result = _run("systemctl", verb, unit)
    return result.stdout.strip() if result else ""


def cloudflare_status() -> dict:
    """
    The Cloudflare tunnel service and its connections, from systemd and the tunnel's local ready endpoint.

    Returns:
        ``installed``, ``configured`` (service enabled), ``active``, ``connected``, ``connections`` and ``error``.
    """
    status = {
        "installed": bool(shutil.which("cloudflared")),
        "configured": False,
        "active": False,
        "connected": False,
        "connections": 0,
        "error": "",
    }
    if not status["installed"]:
        return status
    status["configured"] = _systemctl("is-enabled", "cloudflared") == "enabled"
    status["active"] = _systemctl("is-active", "cloudflared") == "active"
    if not status["active"]:
        return status
    try:
        response = requests.get(f"{settings.CLOUDFLARED_METRICS_URL}/ready", timeout=COMMAND_TIMEOUT)
        connections = response.json().get("readyConnections", 0)
    except (requests.RequestException, ValueError, AttributeError) as error:
        status["error"] = f"Tunnel state unavailable: {error}"
        return status
    status["connections"] = connections if isinstance(connections, int) else 0
    status["connected"] = status["connections"] > 0
    return status
