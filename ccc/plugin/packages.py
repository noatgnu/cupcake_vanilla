"""Plugin packages uploaded by staff: checked, previewed and given a local port before installation."""

from __future__ import annotations

import re
import socket
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings

from ccc.plugin.model import Plugin
from cupcake_plugin_dev.checks import PackageError, check_package

UPLOAD_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class PluginPackageError(Exception):
    """Raised when an uploaded file is not a valid plugin package."""


def upload_dir() -> Path:
    """The directory uploaded packages wait in until they are installed: PLUGIN_UPLOAD_DIR, else media/plugin-uploads."""
    return Path(settings.PLUGIN_UPLOAD_DIR or Path(settings.MEDIA_ROOT) / "plugin-uploads")


def upload_path(upload_id: str) -> Path:
    """
    The file of an uploaded package.

    Raises:
        PluginPackageError: When the id is not one the backend issues.
    """
    if not UPLOAD_ID_PATTERN.match(upload_id or ""):
        raise PluginPackageError("Unknown upload")
    return upload_dir() / f"{upload_id}.tar.gz"


def read_package(path: Path) -> dict:
    """
    The manifest of a plugin package, after the checks of ``cupcake_plugin_dev.checks.check_package``.

    Raises:
        PluginPackageError: When the package or its manifest is not valid.
    """
    try:
        return check_package(path, max_unpacked_bytes=settings.PLUGIN_PACKAGE_MAX_UNPACKED_BYTES)
    except PackageError as error:
        raise PluginPackageError(str(error))


def preview(manifest: dict) -> dict:
    """What installing the package adds, for staff to confirm."""
    installed = Plugin.objects.filter(name=manifest["name"]).first()
    pages = manifest.get("pages") if isinstance(manifest.get("pages"), list) else []
    vocabularies = manifest.get("vocabularies") if isinstance(manifest.get("vocabularies"), list) else []
    return {
        "name": manifest["name"],
        "display_name": str(manifest.get("displayName") or manifest["name"]),
        "version": manifest["version"],
        "description": str(manifest.get("description") or ""),
        "pages": [str(page.get("title") or page.get("path")) for page in pages if isinstance(page, dict)],
        "vocabularies": [
            str(entry.get("label") or entry.get("key")) for entry in vocabularies if isinstance(entry, dict)
        ],
        "installed_version": installed.version if installed else None,
    }


def _port_of(base_url: str) -> int | None:
    try:
        return urlsplit(base_url).port
    except ValueError:
        return None


def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def choose_port(manifest: dict) -> int:
    """
    The local port for the plugin: the one it already has, else the manifest's port, else a free one in the range.

    Raises:
        PluginPackageError: When every port in ``PLUGIN_PORT_RANGE`` is taken.
    """
    current = Plugin.objects.filter(name=manifest["name"]).values_list("base_url", flat=True).first()
    if current and _port_of(current):
        return _port_of(current)
    taken = {_port_of(url) for url in Plugin.objects.exclude(name=manifest["name"]).values_list("base_url", flat=True)}
    first, last = settings.PLUGIN_PORT_RANGE
    candidates = ([manifest["port"]] if manifest.get("port") else []) + list(range(first, last + 1))
    for port in candidates:
        if port not in taken and _is_free(port):
            return port
    raise PluginPackageError(f"No free port from {first} to {last}")
