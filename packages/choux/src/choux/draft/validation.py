"""Checks that Draft.js content matches what the protocols.io web interface can render."""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from choux.draft.builder import Draft
from choux.draft.schema import (
    ATOMIC_ENTITY_FIELDS,
    ATOMIC_ENTITY_TYPES,
    BLOCK_TYPES,
    INLINE_ENTITY_FIELDS,
    INLINE_ENTITY_TYPES,
    INLINE_STYLES,
    NESTED_DRAFT_ENTITIES,
    PLACEHOLDER,
    SPANNING_ENTITY_TYPES,
    UNCHECKED_ATOMIC_ENTITIES,
    UNCHECKED_INLINE_ENTITIES,
    VENDOR_FIELDS,
    Field,
)
from choux.exceptions import DraftValidationError
from choux.units import UNIT_TYPES

Units = Collection[int] | Collection[Mapping[str, Any]]
GUID_PATTERN = re.compile(r"^[0-9A-F]{32}$")
COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


class Severity(str, Enum):
    """How serious a validation issue is."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    """
    One problem found in content.

    Attributes:
        path: Location of the problem, for example ``blocks[0].entityRanges[1]``.
        message: Description of the problem.
        severity: Errors block submission; warnings do not.
    """

    path: str
    message: str
    severity: Severity = Severity.ERROR

    @property
    def is_error(self) -> bool:
        """Whether the issue blocks submission."""
        return self.severity is Severity.ERROR


def load_draft(content: Draft | dict[str, Any] | str) -> dict[str, Any]:
    """
    Return content as a raw Draft.js dictionary.

    Args:
        content: A :class:`Draft`, a raw dictionary, or its JSON text.

    Raises:
        ValueError: When the text is not JSON.
    """
    if isinstance(content, Draft):
        return content.to_dict()
    if isinstance(content, str):
        return json.loads(content)
    return content


def validate_draft(
    content: Draft | dict[str, Any] | str,
    *,
    units: Units | None = None,
    path: str = "",
) -> list[Issue]:
    """
    Check Draft.js content.

    Args:
        content: A :class:`Draft`, a raw dictionary, or its JSON text.
        units: Unit ids accepted by the target protocol, or the units from
            :meth:`choux.ProtocolsIO.get_units` to also check that each unit suits its entity.
            Unit checks are skipped when omitted.
        path: Prefix for issue paths.

    Returns:
        Every issue found, errors and warnings together. An empty list means the content is valid.
    """
    try:
        draft = load_draft(content)
    except ValueError as error:
        return [Issue(path or "content", f"not valid JSON: {error}")]
    return _Validator(_unit_types(units), path).run(draft)


def ensure_valid(content: Draft | dict[str, Any] | str, *, units: Units | None = None, path: str = "") -> list[Issue]:
    """
    Check Draft.js content and raise when it has errors.

    Args:
        content: A :class:`Draft`, a raw dictionary, or its JSON text.
        units: Unit ids or units of the target protocol, as for :func:`validate_draft`.
        path: Prefix for issue paths.

    Returns:
        The warnings found.

    Raises:
        DraftValidationError: When at least one error is found.
    """
    issues = validate_draft(content, units=units, path=path)
    raise_for_issues(issues)
    return issues


def raise_for_issues(issues: list[Issue]) -> None:
    """
    Raise when ``issues`` contains an error.

    Raises:
        DraftValidationError: When at least one issue is an error.
    """
    if any(issue.is_error for issue in issues):
        raise DraftValidationError(issues)


def validate_step_fields(guid: Any, previous_guid: Any, section_color: Any, *, path: str = "") -> list[Issue]:
    """
    Check the fields of a step that sit outside its text.

    Args:
        guid: Step GUID.
        previous_guid: GUID of the step before it, or ``None`` for the first step.
        section_color: Section colour, or ``None``.
        path: Prefix for issue paths.
    """
    issues = []
    if not isinstance(guid, str) or not GUID_PATTERN.match(guid):
        issues.append(Issue(_join(path, "guid"), "must be 32 upper case hex characters"))
    if previous_guid is not None and (not isinstance(previous_guid, str) or not GUID_PATTERN.match(previous_guid)):
        issues.append(Issue(_join(path, "previous_guid"), "must be 32 upper case hex characters or null"))
    if previous_guid is not None and previous_guid == guid:
        issues.append(Issue(_join(path, "previous_guid"), "a step cannot follow itself"))
    if section_color is not None and (not isinstance(section_color, str) or not COLOR_PATTERN.match(section_color)):
        issues.append(Issue(_join(path, "section_color"), "must be a hex colour such as #84CE84"))
    return issues


def _join(path: str, name: str) -> str:
    if not path:
        return name
    return f"{path}{name}" if name.startswith("[") else f"{path}.{name}"


class _Validator:
    def __init__(self, units: dict[int, int | None] | None, path: str):
        self.units = units
        self.path = path
        self.issues: list[Issue] = []

    def error(self, path: str, message: str) -> None:
        self.issues.append(Issue(path, message))

    def warn(self, path: str, message: str) -> None:
        self.issues.append(Issue(path, message, Severity.WARNING))

    def run(self, draft: Any) -> list[Issue]:
        if not isinstance(draft, dict):
            self.error(self.path or "content", "must be an object with blocks and entityMap")
            return self.issues
        blocks = draft.get("blocks")
        entity_map = draft.get("entityMap")
        if not isinstance(blocks, list) or not blocks:
            self.error(_join(self.path, "blocks"), "must be a non-empty list")
            return self.issues
        if entity_map == []:
            entity_map = {}
        if not isinstance(entity_map, dict):
            self.error(_join(self.path, "entityMap"), "must be an object")
            return self.issues
        used: set[str] = set()
        keys: set[str] = set()
        for index, block in enumerate(blocks):
            self.check_block(block, _join(self.path, f"blocks[{index}]"), entity_map, used, keys)
        for key, entity in entity_map.items():
            entity_path = _join(self.path, f"entityMap[{key}]")
            if key not in used:
                self.warn(entity_path, "entity is not referenced by any block")
            self.check_entity(entity, entity_path)
        return self.issues

    def check_block(self, block: Any, path: str, entity_map: dict[str, Any], used: set[str], keys: set[str]) -> None:
        if not isinstance(block, dict):
            self.error(path, "must be an object")
            return
        key = block.get("key")
        if not isinstance(key, str) or not key:
            self.error(_join(path, "key"), "must be a non-empty string")
        elif key in keys:
            self.error(_join(path, "key"), f"duplicate block key {key!r}")
        else:
            keys.add(key)
        text = block.get("text")
        if not isinstance(text, str):
            self.error(_join(path, "text"), "must be a string")
            return
        block_type = block.get("type")
        if block_type not in BLOCK_TYPES:
            self.error(_join(path, "type"), f"unknown block type {block_type!r}")
        depth = block.get("depth", 0)
        if not _is_int(depth) or depth < 0:
            self.error(_join(path, "depth"), "must be a non-negative integer")
        self.check_styles(block.get("inlineStyleRanges", []), text, _join(path, "inlineStyleRanges"))
        ranges = block.get("entityRanges", [])
        if not isinstance(ranges, list):
            self.error(_join(path, "entityRanges"), "must be a list")
            return
        if block_type == "atomic":
            self.check_atomic_block(text, ranges, path, entity_map, used)
            return
        for index, entity_range in enumerate(ranges):
            range_path = _join(path, f"entityRanges[{index}]")
            entity = self.resolve_range(entity_range, text, range_path, entity_map, used)
            if entity is None:
                continue
            entity_type = entity.get("type")
            if entity_type in ATOMIC_ENTITY_TYPES:
                self.error(range_path, f"{entity_type} must be placed in an atomic block")
            elif entity_type not in SPANNING_ENTITY_TYPES:
                if entity_range["length"] != 1:
                    self.error(range_path, f"{entity_type} must cover exactly one placeholder character")
                elif text[entity_range["offset"]] != PLACEHOLDER:
                    self.warn(range_path, f"{entity_type} covers visible text, which is shown next to its value")

    def check_atomic_block(
        self, text: str, ranges: list[Any], path: str, entity_map: dict[str, Any], used: set[str]
    ) -> None:
        if len(ranges) != 1:
            self.error(_join(path, "entityRanges"), "an atomic block must hold exactly one entity")
            return
        range_path = _join(path, "entityRanges[0]")
        entity = self.resolve_range(ranges[0], text, range_path, entity_map, used)
        if entity is None:
            return
        entity_type = entity.get("type")
        if entity_type in INLINE_ENTITY_TYPES:
            self.error(range_path, f"{entity_type} must be placed inside text, not in an atomic block")

    def resolve_range(
        self, entity_range: Any, text: str, path: str, entity_map: dict[str, Any], used: set[str]
    ) -> dict[str, Any] | None:
        if not isinstance(entity_range, dict):
            self.error(path, "must be an object")
            return None
        offset = entity_range.get("offset")
        length = entity_range.get("length")
        key = entity_range.get("key")
        if not _is_int(offset) or not _is_int(length) or length < 1 or offset < 0 or offset + length > len(text):
            self.error(path, "offset and length must lie inside the block text")
            return None
        if not _is_int(key) and not isinstance(key, str):
            self.error(_join(path, "key"), "must be an entityMap key")
            return None
        entity = entity_map.get(str(key))
        if entity is None:
            self.error(_join(path, "key"), f"no entity with key {key!r}")
            return None
        used.add(str(key))
        return entity if isinstance(entity, dict) else None

    def check_styles(self, styles: Any, text: str, path: str) -> None:
        if not isinstance(styles, list):
            self.error(path, "must be a list")
            return
        for index, style in enumerate(styles):
            style_path = _join(path, f"[{index}]")
            if not isinstance(style, dict):
                self.error(style_path, "must be an object")
                continue
            if style.get("style") not in INLINE_STYLES:
                self.error(_join(style_path, "style"), f"unsupported style {style.get('style')!r}")
            offset = style.get("offset")
            length = style.get("length")
            if not _is_int(offset) or not _is_int(length) or offset < 0 or length < 1 or offset + length > len(text):
                self.error(style_path, "offset and length must lie inside the block text")

    def check_entity(self, entity: Any, path: str) -> None:
        if not isinstance(entity, dict):
            self.error(path, "must be an object")
            return
        entity_type = entity.get("type")
        data = entity.get("data")
        if not isinstance(data, dict):
            self.error(_join(path, "data"), "must be an object")
            return
        if entity_type in UNCHECKED_INLINE_ENTITIES or entity_type in UNCHECKED_ATOMIC_ENTITIES:
            self.warn(_join(path, "type"), f"{entity_type} entities are passed through without field checks")
            return
        fields = INLINE_ENTITY_FIELDS.get(entity_type) or ATOMIC_ENTITY_FIELDS.get(entity_type)
        if fields is None:
            self.error(_join(path, "type"), f"unsupported entity type {entity_type!r}")
            return
        for name, field in fields.items():
            self.check_field(data, name, field, _join(path, f"data.{name}"))
        if entity_type in UNIT_TYPES and self.units is not None and _is_int(data.get("unit")):
            self.check_unit(entity_type, data["unit"], _join(path, "data.unit"))
        if entity_type == "reagents" and isinstance(data.get("vendor"), dict):
            for name, field in VENDOR_FIELDS.items():
                self.check_field(data["vendor"], name, field, _join(path, f"data.vendor.{name}"))
        if entity_type in NESTED_DRAFT_ENTITIES:
            self.issues.extend(_Validator(self.units, _join(path, "data")).run(data))

    def check_unit(self, entity_type: str, unit: int, path: str) -> None:
        if unit not in self.units:
            self.error(path, f"unit id {unit} is not available in this protocol")
            return
        type_id = self.units[unit]
        if type_id is not None and type_id != UNIT_TYPES[entity_type]:
            self.error(path, f"unit id {unit} is not a unit for {entity_type}")

    def check_field(self, data: dict[str, Any], name: str, field: Field, path: str) -> None:
        if name not in data:
            self.error(path, "is missing")
            return
        value = data[name]
        if value is None:
            if not field.nullable:
                self.error(path, "must not be null")
            return
        if field.nullable and not field.kinds:
            self.error(path, "must be null")
            return
        if not any(_matches(kind, value) for kind in field.kinds):
            self.error(path, f"expected {' or '.join(field.kinds)}, got {type(value).__name__}")
            return
        if "draft_text" in field.kinds:
            self.check_legend(value, path)

    def check_legend(self, value: str, path: str) -> None:
        legend = json.loads(value)
        if legend.get("blocks") is None and legend.get("entityMap") is None:
            return
        self.issues.extend(_Validator(self.units, path).run(legend))


def _unit_types(units: Units | None) -> dict[int, int | None] | None:
    if units is None:
        return None
    types: dict[int, int | None] = {}
    for unit in units:
        if isinstance(unit, Mapping):
            if _is_int(unit.get("id")):
                types[unit["id"]] = unit.get("type_id")
        elif _is_int(unit):
            types[unit] = None
    return types


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _matches(kind: str, value: Any) -> bool:
    if kind == "str":
        return isinstance(value, str)
    if kind == "int":
        return _is_int(value)
    if kind == "number":
        return _is_int(value) or isinstance(value, float)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "list":
        return isinstance(value, list)
    if kind == "dict":
        return isinstance(value, dict)
    if kind == "number_text":
        if not isinstance(value, str):
            return False
        try:
            return Decimal(value).is_finite()
        except InvalidOperation:
            return False
    if kind == "draft_text":
        if not isinstance(value, str):
            return False
        try:
            parsed = json.loads(value)
        except ValueError:
            return False
        return isinstance(parsed, dict) and "blocks" in parsed and "entityMap" in parsed
    return False
