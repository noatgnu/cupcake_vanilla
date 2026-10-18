"""Protocol steps and their ordering."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from choux.draft.builder import Draft
from choux.draft.entities import new_guid
from choux.draft.validation import load_draft


@dataclass
class Step:
    """
    One protocol step.

    Attributes:
        content: Step text as a :class:`Draft`, a raw Draft.js dictionary, Draft.js JSON text, or
            plain text.
        guid: Step GUID. Reuse the same GUID to update a step instead of adding a new one.
        previous_guid: GUID of the step before this one, ``None`` for the first step.
        section: Name of the section the step belongs to.
        section_color: Section colour as a hex code such as ``#84CE84``.
        is_substep: Whether the step is shown as a substep.
    """

    content: Draft | dict[str, Any] | str
    guid: str = field(default_factory=new_guid)
    previous_guid: str | None = None
    section: str | None = None
    section_color: str | None = None
    is_substep: bool = False

    def draft(self) -> dict[str, Any]:
        """Return the step text as a raw Draft.js dictionary; plain text becomes one paragraph per line."""
        if isinstance(self.content, str):
            try:
                loaded = load_draft(self.content)
            except ValueError:
                loaded = None
            if isinstance(loaded, dict) and "blocks" in loaded:
                return loaded
            return Draft.from_text(self.content).to_dict()
        return load_draft(self.content)

    def to_api(self) -> dict[str, Any]:
        """Return the step as the protocols.io steps endpoint expects it."""
        return {
            "guid": self.guid,
            "previous_guid": self.previous_guid,
            "step": json.dumps(self.draft(), separators=(",", ":"), ensure_ascii=False),
            "section": self.section,
            "section_color": self.section_color,
            "is_substep": self.is_substep,
        }


def chain(steps: Iterable[Step], *, after: str | None = None) -> list[Step]:
    """
    Link steps in the given order by setting each ``previous_guid``.

    Args:
        steps: Steps in reading order.
        after: GUID of an existing step the first given step should follow.

    Returns:
        The same steps as a list.
    """
    ordered = list(steps)
    previous = after
    for step in ordered:
        step.previous_guid = previous
        previous = step.guid
    return ordered
