"""Plugin packages uploaded by staff: checked, previewed and given a local port before installation."""

from __future__ import annotations

import json
import re
import socket
import tarfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from django.conf import settings

from ccc.plugin.model import Plugin

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
UPLOAD_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
MAX_MEMBERS = 10000
MAX_MANIFEST_BYTES = 1024 * 1024
REQUIRED_FILES = ("run.sh", "manifest.json")


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


def _member_path(member: tarfile.TarInfo) -> PurePosixPath:
    path = PurePosixPath(member.name)
    parts = [part for part in path.parts if part not in ("", ".")]
    if path.is_absolute() or ".." in parts:
        raise PluginPackageError(f"The package contains a path outside the plugin: {member.name}")
    if not (member.isfile() or member.isdir()):
        raise PluginPackageError(f"The package contains a link or special file: {member.name}")
    return PurePosixPath(*parts) if parts else PurePosixPath(".")


def read_package(path: Path) -> dict:
    """
    The manifest of a plugin package, after checking the package.

    Raises:
        PluginPackageError: When the file is not a gzipped tar of regular files and directories with ``run.sh``
            and ``manifest.json`` at the top, is too large unpacked, or its manifest is not valid.
    """
    try:
        archive = tarfile.open(path, "r:gz")
    except (tarfile.TarError, OSError, EOFError):
        raise PluginPackageError("The file is not a .tar.gz archive")
    with archive:
        top_level: dict[str, tarfile.TarInfo] = {}
        unpacked = 0
        try:
            for count, member in enumerate(archive, start=1):
                if count > MAX_MEMBERS:
                    raise PluginPackageError(f"The package has more than {MAX_MEMBERS} files")
                member_path = _member_path(member)
                unpacked += member.size
                if unpacked > settings.PLUGIN_PACKAGE_MAX_UNPACKED_BYTES:
                    raise PluginPackageError("The package is too large unpacked")
                if len(member_path.parts) == 1 and member.isfile():
                    top_level[member_path.name] = member
        except (tarfile.TarError, EOFError, OSError):
            raise PluginPackageError("The archive is damaged")
        missing = [name for name in REQUIRED_FILES if name not in top_level]
        if missing:
            raise PluginPackageError(f"The package needs {' and '.join(missing)} at the top level")
        if top_level["manifest.json"].size > MAX_MANIFEST_BYTES:
            raise PluginPackageError("manifest.json is too large")
        try:
            manifest = json.loads(archive.extractfile(top_level["manifest.json"]).read())
        except (ValueError, UnicodeDecodeError):
            raise PluginPackageError("manifest.json is not valid JSON")
    if not isinstance(manifest, dict):
        raise PluginPackageError("manifest.json must be an object")
    name = manifest.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        raise PluginPackageError(
            "The manifest name must be lower-case letters, digits, '-' and '_', starting with a letter or digit"
        )
    if not isinstance(manifest.get("version"), str) or not manifest["version"].strip():
        raise PluginPackageError("The manifest needs a version")
    port = manifest.get("port")
    if port is not None and (not isinstance(port, int) or not 1024 <= port <= 65535):
        raise PluginPackageError("The manifest port must be a number from 1024 to 65535")
    return manifest


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
