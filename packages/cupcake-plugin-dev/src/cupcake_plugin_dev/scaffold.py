"""New plugins created from the templates."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path

from cupcake_plugin_dev.manifest import manifest_problems

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
KINDS = {
    "service": {"port": 8110, "description": "A CUPCAKE plugin with a page that updates live"},
    "vocabulary": {"port": 8101, "description": "Provides vocabularies to CUPCAKE metadata columns"},
}
RENAMED = {"README.template": "README.md", "gitignore": ".gitignore"}
SKIPPED = {"__pycache__"}


class ScaffoldError(Exception):
    """Raised when a plugin cannot be created."""


def _render(text: str, values: dict, suffix: str) -> str:
    for placeholder, value in values.items():
        if suffix == ".json":
            value = json.dumps(value)[1:-1]
        elif suffix == ".py":
            value = value.replace("\\", "/").replace('"""', "'''")
        text = text.replace(placeholder, value)
    return text


def _copy(source, target: Path, values: dict) -> None:
    for entry in source.iterdir():
        if entry.name in SKIPPED:
            continue
        destination = target / RENAMED.get(entry.name, entry.name)
        if entry.is_dir():
            destination.mkdir()
            _copy(entry, destination, values)
            continue
        destination.write_text(_render(entry.read_text(), values, Path(entry.name).suffix))
        if entry.name.endswith(".sh"):
            destination.chmod(0o755)


def create_plugin(
    name: str,
    kind: str,
    parent: Path,
    display_name: str | None = None,
    port: int | None = None,
    description: str | None = None,
) -> Path:
    """
    Create a working plugin from the kind's template in parent/name.

    Raises:
        ScaffoldError: When the name or kind is not valid, the port is out of range or parent/name exists.
    """
    if not NAME_PATTERN.match(name):
        raise ScaffoldError("The name must be lower-case letters, digits, '-' and '_', starting with a letter or digit")
    if kind not in KINDS:
        raise ScaffoldError(f"The kind must be one of: {', '.join(KINDS)}")
    port = port or KINDS[kind]["port"]
    if not 1024 <= port <= 65535:
        raise ScaffoldError("The port must be from 1024 to 65535")
    target = Path(parent) / name
    if target.exists():
        raise ScaffoldError(f"{target} already exists")
    values = {
        "__PLUGIN_NAME__": name,
        "__DISPLAY_NAME__": display_name or name.replace("-", " ").replace("_", " ").capitalize(),
        "__DESCRIPTION__": description or KINDS[kind]["description"],
    }
    target.mkdir(parents=True)
    _copy(resources.files("cupcake_plugin_dev").joinpath("templates", kind), target, values)
    manifest_file = target / "manifest.json"
    manifest_file.write_text(manifest_file.read_text().replace('"port": "__PORT__"', f'"port": {port}'))
    for python_file in target.rglob("*.py"):
        python_file.write_text(python_file.read_text().replace("__PORT__", str(port)))
    problems = manifest_problems(json.loads(manifest_file.read_text()))
    if problems:
        raise ScaffoldError("The created manifest is not valid: " + "; ".join(problems))
    return target
