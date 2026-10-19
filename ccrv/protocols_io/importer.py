"""Arrangement of imported protocols.io steps into Cupcake sections."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

UNTITLED_SECTION = "Untitled section"


@dataclass
class ImportedSection:
    """
    A run of consecutive protocols.io steps that becomes one Cupcake section.

    Attributes:
        title: Section name; :data:`UNTITLED_SECTION` for steps that had no section.
        named: Whether the steps had a section on protocols.io.
        steps: Steps in order.
    """

    title: str
    named: bool
    steps: list[Mapping[str, Any]] = field(default_factory=list)

    @property
    def duration(self) -> int:
        """Section total stored on the first step, or 0 for untitled sections."""
        if not self.named or not self.steps:
            return 0
        return self.steps[0].get("section_duration") or 0


def step_section_title(step: Mapping[str, Any]) -> str:
    """
    Return the section name of a protocols.io step, or an empty string when it has none.

    Args:
        step: Step from the protocols.io v3 protocol response.
    """
    for component in step.get("components") or []:
        if component.get("title") == "Section":
            title = ((component.get("source") or {}).get("title") or "").strip()
            if title:
                return title
    return (step.get("section") or "").strip()


def steps_in_order(steps: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """
    Return protocols.io steps in reading order, following ``previous_id``.

    Steps outside the chain keep their position after the chained steps.

    Args:
        steps: Steps from the protocols.io v3 protocol response.
    """
    remaining = list(steps)
    by_previous: dict[Any, list[Mapping[str, Any]]] = {}
    for step in remaining:
        by_previous.setdefault(step.get("previous_id") or 0, []).append(step)
    ordered: list[Mapping[str, Any]] = []
    seen: set[Any] = set()
    queue = list(by_previous.get(0, []))
    while queue:
        step = queue.pop(0)
        if step["id"] in seen:
            continue
        seen.add(step["id"])
        ordered.append(step)
        queue = by_previous.get(step["id"], []) + queue
    ordered.extend(step for step in remaining if step["id"] not in seen)
    return ordered


def group_into_sections(steps: Iterable[Mapping[str, Any]]) -> list[ImportedSection]:
    """
    Split protocols.io steps into Cupcake sections.

    Consecutive steps with the same section name form one section. Consecutive steps without a
    section form an untitled section at their position.

    Args:
        steps: Steps from the protocols.io v3 protocol response.

    Returns:
        Sections in reading order.
    """
    sections: list[ImportedSection] = []
    for step in steps_in_order(steps):
        title = step_section_title(step)
        named = bool(title)
        current = sections[-1] if sections else None
        if current is None or current.named != named or (named and current.title != title):
            current = ImportedSection(title=title if named else UNTITLED_SECTION, named=named)
            sections.append(current)
        current.steps.append(step)
    return sections
