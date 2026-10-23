"""Conversion of protocol step text with reagent templates into protocols.io Draft.js content."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from choux import Draft, html_to_draft, match_unit
from choux.draft import amount, number_text
from choux.draft.builder import Part
from choux.draft.html import ImageResolver

TEMPLATE_TOKEN = re.compile(r"%(?P<id>\d+)\.(?P<property>name|quantity|scaled_quantity|unit)%")
QUANTITY_PROPERTIES = frozenset({"quantity", "scaled_quantity"})


@dataclass(frozen=True)
class TemplateReagent:
    """
    Values a step's reagent templates refer to.

    Attributes:
        id: Id of the step reagent, as written in ``%<id>.<property>%``.
        name: Reagent name.
        unit: Unit text of the reagent.
        quantity: Quantity used in the step.
        scaled_quantity: Quantity after scaling.
    """

    id: int
    name: str
    unit: str
    quantity: float
    scaled_quantity: float

    @classmethod
    def from_step_reagent(cls, step_reagent: Any, *, scaling_factor: float = 1.0) -> TemplateReagent:
        """
        Read the template values of a step reagent.

        Args:
            step_reagent: A :class:`ccrv.models.StepReagent`.
            scaling_factor: Extra factor applied to the scaled quantity of scalable reagents.
        """
        quantity = step_reagent.quantity or 0
        scaled = quantity
        if step_reagent.scalable:
            scaled = quantity * (step_reagent.scalable_factor or 1.0) * scaling_factor
        return cls(
            id=step_reagent.id,
            name=step_reagent.reagent.name or "",
            unit=step_reagent.reagent.unit or "",
            quantity=quantity,
            scaled_quantity=scaled,
        )


@dataclass
class StepTemplateResolver:
    """
    Text resolver for :func:`choux.html_to_draft` that expands ``%<id>.<property>%`` reagent templates.

    A quantity followed by the unit of the same reagent becomes a protocols.io amount when the
    unit is known to protocols.io; the amount is labelled with the reagent name unless the step
    shows the name itself. Every other template becomes plain text. Templates naming a reagent
    that is not on the step are kept as written and listed in :attr:`unresolved`.

    Attributes:
        reagents: Reagents of the step, by step reagent id.
        units: Units of the target protocol, from :meth:`choux.ProtocolsIO.get_units`.
        named: Ids of reagents whose name template appears in the step.
        unresolved: Templates that could not be expanded, in the order found.
    """

    reagents: dict[int, TemplateReagent]
    units: Sequence[Mapping[str, Any]]
    named: frozenset[int] = frozenset()
    unresolved: list[str] = field(default_factory=list)

    @classmethod
    def for_step(
        cls, html: str, reagents: Iterable[TemplateReagent], units: Sequence[Mapping[str, Any]]
    ) -> StepTemplateResolver:
        """
        Build a resolver for one step.

        Args:
            html: Step text, used to find which reagent names the step shows.
            reagents: Reagents of the step.
            units: Units of the target protocol.
        """
        named = frozenset(
            int(match.group("id")) for match in TEMPLATE_TOKEN.finditer(html or "") if match.group("property") == "name"
        )
        return cls({reagent.id: reagent for reagent in reagents}, units, named)

    def __call__(self, text: str) -> list[Part]:
        parts: list[Part] = []
        position = 0
        while True:
            match = TEMPLATE_TOKEN.search(text, position)
            if match is None:
                parts.append(text[position:])
                return parts
            parts.append(text[position : match.start()])
            position = self._expand(text, match, parts)

    def _expand(self, text: str, match: re.Match[str], parts: list[Part]) -> int:
        reagent_id = int(match.group("id"))
        prop = match.group("property")
        reagent = self.reagents.get(reagent_id)
        if reagent is None:
            self.unresolved.append(match.group(0))
            parts.append(match.group(0))
            return match.end()
        if prop == "name":
            parts.append(reagent.name)
            return match.end()
        if prop == "unit":
            parts.append(reagent.unit)
            return match.end()
        value = reagent.scaled_quantity if prop == "scaled_quantity" else reagent.quantity
        unit_token = re.compile(rf"(\s*)%{reagent_id}\.unit%").match(text, match.end())
        if unit_token is None:
            parts.append(number_text(value))
            return match.end()
        unit = match_unit(reagent.unit, self.units, kind="amount") if reagent.unit else None
        if unit is None:
            parts.append(f"{number_text(value)}{unit_token.group(1)}{reagent.unit}")
            return unit_token.end()
        label = "" if reagent.id in self.named else reagent.name
        parts.append(amount(value, unit["id"], label))
        return unit_token.end()


def step_to_draft(
    step: Any,
    units: Sequence[Mapping[str, Any]],
    *,
    scaling_factor: float = 1.0,
    image_resolver: ImageResolver | None = None,
    text: str | None = None,
) -> tuple[Draft, list[str]]:
    """
    Convert the text of a protocol step into protocols.io Draft.js content.

    Args:
        step: A :class:`ccrv.models.ProtocolStep`.
        units: Units of the target protocol, from :meth:`choux.ProtocolsIO.get_units`.
        scaling_factor: Extra factor applied to scaled quantities of scalable reagents.
        image_resolver: Passed to :func:`choux.html_to_draft` for images in the step text.
        text: Text to convert instead of the step description, using the reagents of the step.

    Returns:
        The content, and the templates that could not be expanded.
    """
    html = (step.step_description if text is None else text) or ""
    reagents = [
        TemplateReagent.from_step_reagent(step_reagent, scaling_factor=scaling_factor)
        for step_reagent in step.reagents.select_related("reagent")
    ]
    resolver = StepTemplateResolver.for_step(html, reagents, units)
    draft = html_to_draft(html, image_resolver=image_resolver, text_resolver=resolver)
    return draft, resolver.unresolved
