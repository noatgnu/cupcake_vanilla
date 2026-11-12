"""The plugin manifest: its schema and the checks a manifest must pass."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources

from jsonschema import Draft202012Validator

DATA_WIDGET_TYPES = {"card", "list", "table", "chart"}
VOCABULARY_KEY_MAX_LENGTH = 100


@cache
def schema() -> dict:
    """The JSON Schema of manifest.json."""
    return json.loads(resources.files("cupcake_plugin_dev").joinpath("schema/manifest.schema.json").read_text())


def _location(path) -> str:
    parts = []
    for part in path:
        parts.append(f"[{part}]" if isinstance(part, int) else (f".{part}" if parts else str(part)))
    return "".join(parts) or "manifest"


def _rules(manifest: dict) -> list[str]:
    problems = []
    page_paths = [page.get("path") for page in manifest.get("pages", [])]
    for index, item in enumerate(manifest.get("nav", [])):
        if item.get("path") not in page_paths:
            problems.append(f"nav[{index}].path: no page has the path {item.get('path')!r}")
    for page_index, page in enumerate(manifest.get("pages", [])):
        seen = set()
        for index, widget in enumerate(page.get("widgets", [])):
            where = f"pages[{page_index}].widgets[{index}]"
            if widget.get("id") in seen:
                problems.append(f"{where}.id: {widget.get('id')!r} is used twice on this page")
            seen.add(widget.get("id"))
            if widget.get("type") in DATA_WIDGET_TYPES | {"form"} and not widget.get("endpoint"):
                problems.append(f"{where}: a {widget.get('type')} widget needs an endpoint")
            if widget.get("type") == "form" and not widget.get("fields"):
                problems.append(f"{where}: a form widget needs fields")
    keys = set()
    for index, vocabulary in enumerate(manifest.get("vocabularies", [])):
        key = vocabulary.get("key")
        if key in keys:
            problems.append(f"vocabularies[{index}].key: {key!r} is declared twice")
        keys.add(key)
        if len(f"plugin.{manifest.get('name', '')}.{key}") > VOCABULARY_KEY_MAX_LENGTH:
            problems.append(
                f"vocabularies[{index}].key: plugin.<name>.<key> is longer than {VOCABULARY_KEY_MAX_LENGTH} characters"
            )
    names = set()
    for index, setting in enumerate(manifest.get("settings", [])):
        if setting.get("name") in names:
            problems.append(f"settings[{index}].name: {setting.get('name')!r} is declared twice")
        names.add(setting.get("name"))
    return problems


def manifest_problems(manifest) -> list[str]:
    """Everything wrong with a manifest, one line per problem, empty when it is valid."""
    if not isinstance(manifest, dict):
        return ["manifest: must be a JSON object"]
    validator = Draft202012Validator(schema())
    problems = [
        f"{_location(error.absolute_path)}: {error.message}"
        for error in sorted(validator.iter_errors(manifest), key=lambda error: list(map(str, error.absolute_path)))
    ]
    return problems or _rules(manifest)
