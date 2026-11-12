"""Checks a plugin package must pass before it is installed."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path, PurePosixPath

from cupcake_plugin_dev.manifest import manifest_problems

MAX_MEMBERS = 10000
MAX_MANIFEST_BYTES = 1024 * 1024
DEFAULT_MAX_UNPACKED_BYTES = 4 * 1024 * 1024 * 1024
REQUIRED_FILES = ("run.sh", "manifest.json")


class PackageError(Exception):
    """Raised when a file is not a valid plugin package."""


def _member_path(member: tarfile.TarInfo) -> PurePosixPath:
    path = PurePosixPath(member.name)
    parts = [part for part in path.parts if part not in ("", ".")]
    if path.is_absolute() or ".." in parts:
        raise PackageError(f"The package contains a path outside the plugin: {member.name}")
    if not (member.isfile() or member.isdir()):
        raise PackageError(f"The package contains a link or special file: {member.name}")
    return PurePosixPath(*parts) if parts else PurePosixPath(".")


def check_package(path: Path, max_unpacked_bytes: int = DEFAULT_MAX_UNPACKED_BYTES) -> dict:
    """
    The manifest of a plugin package, after checking the package and its manifest.

    Raises:
        PackageError: When the file is not a gzipped tar of regular files and directories with ``run.sh`` and
            ``manifest.json`` at the top, is too large unpacked, or its manifest is not valid.
    """
    try:
        archive = tarfile.open(path, "r:gz")
    except (tarfile.TarError, OSError, EOFError):
        raise PackageError("The file is not a .tar.gz archive")
    with archive:
        top_level: dict[str, tarfile.TarInfo] = {}
        unpacked = 0
        try:
            for count, member in enumerate(archive, start=1):
                if count > MAX_MEMBERS:
                    raise PackageError(f"The package has more than {MAX_MEMBERS} files")
                member_path = _member_path(member)
                unpacked += member.size
                if unpacked > max_unpacked_bytes:
                    raise PackageError("The package is too large unpacked")
                if len(member_path.parts) == 1 and member.isfile():
                    top_level[member_path.name] = member
        except (tarfile.TarError, EOFError, OSError):
            raise PackageError("The archive is damaged")
        missing = [name for name in REQUIRED_FILES if name not in top_level]
        if missing:
            raise PackageError(f"The package needs {' and '.join(missing)} at the top level")
        if top_level["manifest.json"].size > MAX_MANIFEST_BYTES:
            raise PackageError("manifest.json is too large")
        try:
            manifest = json.loads(archive.extractfile(top_level["manifest.json"]).read())
        except (ValueError, UnicodeDecodeError):
            raise PackageError("manifest.json is not valid JSON")
    problems = manifest_problems(manifest)
    if problems:
        raise PackageError("manifest.json is not valid: " + "; ".join(problems))
    return manifest
