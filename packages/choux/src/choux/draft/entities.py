"""Builders for Draft.js entities with every field the protocols.io editor writes."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from choux.draft.schema import ATOMIC_ENTITY_TYPES, SPANNING_ENTITY_TYPES
from choux.models import UploadedFile

if TYPE_CHECKING:
    from choux.draft.builder import Draft

EMPTY_LEGEND = json.dumps({"blocks": None, "entityMap": None}, separators=(",", ":"))
CELSIUS = 10
VENDOR_PLACEHOLDER = "/img/vendors/placeholder.png"


def new_guid() -> str:
    """Return a new protocols.io style GUID: 32 upper case hex characters without dashes."""
    return uuid.uuid4().hex.upper()


def number_text(value: int | float | str | Decimal) -> str:
    """
    Format a quantity the way the protocols.io editor stores it.

    Args:
        value: Number or numeric string.

    Returns:
        Plain decimal text without exponent or trailing zeros, for example ``"0.0005"`` or ``"50"``.
    """
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError(f"{value!r} is not a finite number")
    text = format(number.normalize(), "f")
    return "0" if text in ("-0", "") else text


@dataclass(frozen=True)
class Entity:
    """
    One Draft.js entity.

    Attributes:
        type: Entity type such as ``amount`` or ``image``.
        data: Entity data.
        mutability: Draft.js mutability flag.
    """

    type: str
    data: dict[str, Any]
    mutability: str = "MUTABLE"

    @property
    def is_atomic(self) -> bool:
        """Whether the entity must be placed in its own atomic block."""
        return self.type in ATOMIC_ENTITY_TYPES

    @property
    def spans_text(self) -> bool:
        """Whether the entity covers visible text instead of a single placeholder character."""
        return self.type in SPANNING_ENTITY_TYPES

    def to_dict(self) -> dict[str, Any]:
        """Return the entity as it appears in an ``entityMap``."""
        return {"type": self.type, "mutability": self.mutability, "data": dict(self.data)}


def _quantity(kind: str, value: Any, unit: int, label: str, error_field: str) -> Entity:
    return Entity(
        kind,
        {
            kind: number_text(value),
            error_field: False,
            "guid": new_guid(),
            "id": 0,
            "label": label,
            "scientificNotation": False,
            "unit": int(unit),
        },
    )


def amount(value: int | float | str | Decimal, unit: int, label: str = "") -> Entity:
    """
    Build an amount, for example a volume or mass of a reagent.

    Args:
        value: Quantity.
        unit: protocols.io unit id, taken from the ``units`` list of a protocol.
        label: Text shown after the quantity, usually what the amount is of.
    """
    return _quantity("amount", value, unit, label, "error")


def temperature(value: int | float | str | Decimal, unit: int = CELSIUS, label: str = "") -> Entity:
    """
    Build a temperature.

    Args:
        value: Temperature value.
        unit: protocols.io unit id, degrees Celsius by default.
        label: Text shown after the temperature.
    """
    return _quantity("temperature", value, unit, label, "error_temperature")


def concentration(value: int | float | str | Decimal, unit: int, label: str = "") -> Entity:
    """
    Build a concentration.

    Args:
        value: Concentration value.
        unit: protocols.io unit id.
        label: Text shown after the concentration.
    """
    return _quantity("concentration", value, unit, label, "error_concentration")


def duration(seconds: int | float, label: str = "") -> Entity:
    """
    Build a duration, which protocols.io shows with a timer.

    Args:
        seconds: Length in seconds, rounded to a whole second.
        label: Text shown after the duration.
    """
    return Entity(
        "duration",
        {
            "duration": int(round(seconds)),
            "guid": new_guid(),
            "id": 0,
            "label": label,
            "pause": None,
            "preset": [],
            "start": None,
        },
    )


def link(url: str) -> Entity:
    """
    Build a hyperlink entity. Use :func:`choux.draft.builder.hyperlink` to attach it to text.

    Args:
        url: Target address.
    """
    return Entity("link", {"guid": new_guid(), "url": url})


def go_to_step(step_guid: str, title: str = "") -> Entity:
    """
    Build a reference to another step of the same protocol.

    Args:
        step_guid: GUID of the referenced step.
        title: Text shown with the reference.
    """
    return Entity("gotostep", {"guid": new_guid(), "step_guid": step_guid, "title": title})


def reagent(item: Mapping[str, Any]) -> Entity:
    """
    Build an inline reference to a reagent from the protocols.io catalogue.

    Args:
        item: A reagent from :meth:`choux.ProtocolsIO.search_reagents` or
            :meth:`choux.ProtocolsIO.get_materials`.

    Raises:
        ValueError: When the reagent has no id or name.
    """
    if not item.get("id") or not item.get("name"):
        raise ValueError("a catalogue reagent needs an id and a name")
    vendor = item.get("vendor") or {}
    image_data = vendor.get("image") or {}
    return Entity(
        "reagents",
        {
            "id": int(item["id"]),
            "guid": item.get("guid") or new_guid(),
            "name": item["name"],
            "mol_weight": item.get("mol_weight") or 0,
            "sku": item.get("sku") or "",
            "url": item.get("url") or "",
            "cas_number": item.get("cas_number") or "",
            "rrid": item.get("rrid") or "",
            "vendor": {
                "id": int(vendor.get("id") or 0),
                "name": vendor.get("name") or "",
                "link": vendor.get("link") or "",
                "is_requested": bool(vendor.get("is_requested", False)),
                "image": {
                    "source": image_data.get("source") or VENDOR_PLACEHOLDER,
                    "placeholder": image_data.get("placeholder") or VENDOR_PLACEHOLDER,
                },
            },
            "is_public": bool(item.get("is_public", True)),
            "can_edit": bool(item.get("can_edit", False)),
        },
    )


def file_attachment(uploaded: UploadedFile) -> Entity:
    """
    Build an inline attachment for a file uploaded with :meth:`choux.ProtocolsIO.upload_file`.

    Args:
        uploaded: The uploaded file.
    """
    return Entity(
        "file",
        {
            "guid": new_guid(),
            "id": uploaded.id,
            "original_name": uploaded.original_name,
            "placeholder": uploaded.thumb_url,
            "size": uploaded.size,
            "source": uploaded.source,
        },
    )


def image(
    uploaded: UploadedFile,
    *,
    width: float | None = None,
    height: float | None = None,
    caption: Draft | None = None,
    alt: str = "",
) -> Entity:
    """
    Build an image block for an image uploaded with :meth:`choux.ProtocolsIO.upload_file`.

    Args:
        uploaded: The uploaded image.
        width: Displayed width in pixels; defaults to the width given at upload.
        height: Displayed height in pixels; defaults to the height given at upload.
        caption: Caption shown under the image.
        alt: Alternative text.

    Raises:
        ValueError: When no width or height is known.
    """
    shown_width = width if width is not None else uploaded.width
    shown_height = height if height is not None else uploaded.height
    if shown_width is None or shown_height is None:
        raise ValueError("image width and height are required, pass them here or when uploading")
    legend = caption.to_json() if caption is not None and not caption.is_empty else EMPTY_LEGEND
    return Entity(
        "image",
        {
            "alt": alt,
            "guid": new_guid(),
            "height": shown_height,
            "id": uploaded.id,
            "is_video": False,
            "legend": legend,
            "mime": uploaded.mime_type,
            "nestedSelector": None,
            "original_name": uploaded.original_name,
            "placeholder": uploaded.source,
            "shadow": False,
            "source": uploaded.source,
            "width": shown_width,
        },
        mutability="IMMUTABLE",
    )


def _nested(kind: str, content: Draft) -> Entity:
    return Entity(kind, content.to_dict(), mutability="IMMUTABLE")


def note(content: Draft) -> Entity:
    """
    Build a note box.

    Args:
        content: Text of the note.
    """
    return _nested("notes", content)


def expected_result(content: Draft) -> Entity:
    """
    Build an expected result box.

    Args:
        content: Text of the expected result.
    """
    return _nested("result", content)


def safety(content: Draft) -> Entity:
    """
    Build a safety information box.

    Args:
        content: Text of the safety information.
    """
    return _nested("safety", content)
