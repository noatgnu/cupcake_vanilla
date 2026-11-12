"""Plugin packages built from a plugin's folder."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

from cupcake_plugin_dev.checks import PackageError, check_package
from cupcake_plugin_dev.manifest import manifest_problems

LEFT_OUT_DIRECTORIES = {".git", ".github", ".idea", ".venv", "venv", "__pycache__", "dist", "tests", "node_modules"}
LEFT_OUT_SUFFIXES = (".pyc", ".tar.gz", ".tgz")
LEFT_OUT_FILES = {".DS_Store", ".gitignore"}


def read_manifest(plugin_dir: Path) -> dict:
    """
    The plugin's manifest.

    Raises:
        PackageError: When manifest.json is missing or not valid JSON.
    """
    try:
        return json.loads((Path(plugin_dir) / "manifest.json").read_text())
    except FileNotFoundError:
        raise PackageError("manifest.json is missing")
    except ValueError as error:
        raise PackageError(f"manifest.json is not valid JSON: {error}")


def plugin_problems(plugin_dir: Path) -> list[str]:
    """Everything that stops the plugin in plugin_dir from being packaged, empty when nothing does."""
    plugin_dir = Path(plugin_dir)
    try:
        problems = manifest_problems(read_manifest(plugin_dir))
    except PackageError as error:
        problems = [str(error)]
    run_sh = plugin_dir / "run.sh"
    if not run_sh.is_file():
        problems.append("run.sh is missing")
    for path in _files(plugin_dir):
        if path.is_symlink():
            problems.append(f"{path.relative_to(plugin_dir)} is a link; packages may only hold regular files")
    return problems


def _files(plugin_dir: Path):
    for path in sorted(plugin_dir.iterdir()):
        if path.name in LEFT_OUT_FILES or path.name.endswith(LEFT_OUT_SUFFIXES):
            continue
        if path.is_dir() and not path.is_symlink():
            if path.name in LEFT_OUT_DIRECTORIES:
                continue
            yield path
            yield from _files(path)
        else:
            yield path


def _normalise(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    if info.isdir() or info.name.endswith(".sh"):
        info.mode = 0o755
    else:
        info.mode = 0o644
    return info


def build_package(plugin_dir: Path, output_dir: Path | None = None) -> Path:
    """
    Build plugin_dir into <output_dir>/<name>-<version>.tar.gz and check it as CUPCAKE checks an upload.

    Raises:
        PackageError: When the plugin cannot be packaged or the package fails the checks.
    """
    plugin_dir = Path(plugin_dir)
    problems = plugin_problems(plugin_dir)
    if problems:
        raise PackageError("; ".join(problems))
    manifest = read_manifest(plugin_dir)
    output_dir = Path(output_dir) if output_dir else plugin_dir / "dist"
    output_dir.mkdir(parents=True, exist_ok=True)
    package = output_dir / f"{manifest['name']}-{manifest['version']}.tar.gz"
    with tarfile.open(package, "w:gz") as archive:
        for path in _files(plugin_dir):
            archive.add(path, arcname=path.relative_to(plugin_dir).as_posix(), recursive=False, filter=_normalise)
    check_package(package)
    return package
