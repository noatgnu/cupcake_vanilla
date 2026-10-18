"""Matching unit text to protocols.io unit ids."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

UNIT_TYPES = {"amount": 3, "temperature": 24, "concentration": 25}
MU_VARIANTS = str.maketrans({"µ": "u", "μ": "u"})


def normalise(text: str) -> str:
    """
    Return unit text in comparable form: trimmed, inner spaces removed, both mu characters as ``u``.

    Args:
        text: Unit text such as ``" µL "`` or ``"x g"``.
    """
    return "".join(text.translate(MU_VARIANTS).split())


def unit_kind(unit: Mapping[str, Any]) -> str | None:
    """
    Return the entity kind a unit belongs to: ``amount``, ``temperature``, ``concentration`` or ``None``.

    Args:
        unit: Unit from :meth:`choux.ProtocolsIO.get_units`.
    """
    for kind, type_id in UNIT_TYPES.items():
        if unit.get("type_id") == type_id:
            return kind
    return None


def match_unit(text: str, units: Iterable[Mapping[str, Any]], *, kind: str | None = None) -> Mapping[str, Any] | None:
    """
    Find the protocols.io unit for unit text.

    Names and aliases are compared exactly after :func:`normalise`. When nothing matches exactly,
    a case-insensitive comparison is used, but only if it finds a single unit.

    Args:
        text: Unit text such as ``"uL"``, ``"microliters"`` or ``"°C"``.
        units: Units from :meth:`choux.ProtocolsIO.get_units`.
        kind: Restrict matching to ``amount``, ``temperature`` or ``concentration`` units.

    Returns:
        The matching unit, or ``None``.

    Raises:
        ValueError: When ``kind`` is not a known kind.
    """
    if kind is not None and kind not in UNIT_TYPES:
        raise ValueError(f"unknown unit kind {kind!r}, expected one of {', '.join(UNIT_TYPES)}")
    wanted = normalise(text)
    if not wanted:
        return None
    candidates = [
        unit
        for unit in units
        if not unit.get("deleted")
        and not unit.get("read_only")
        and (kind is None or unit.get("type_id") == UNIT_TYPES[kind])
    ]
    for unit in candidates:
        if wanted in _names(unit):
            return unit
    folded = wanted.casefold()
    loose = [unit for unit in candidates if folded in {name.casefold() for name in _names(unit)}]
    return loose[0] if len(loose) == 1 else None


def _names(unit: Mapping[str, Any]) -> set[str]:
    names = [unit.get("name") or ""]
    names.extend(unit.get("aliases") or [])
    return {normalise(name) for name in names if name}
