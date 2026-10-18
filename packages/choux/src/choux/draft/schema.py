"""Shapes of Draft.js content that the protocols.io web interface can render."""

from __future__ import annotations

from dataclasses import dataclass

PLACEHOLDER = " "

BLOCK_TYPES = frozenset(
    {
        "unstyled",
        "atomic",
        "align-left",
        "align-center",
        "align-right",
        "align-justify",
        "unordered-list-item",
        "ordered-list-item",
    }
)

INLINE_STYLES = frozenset({"bold", "italic", "sup", "sub"})


@dataclass(frozen=True)
class Field:
    """
    Expected value of one entity data field.

    Attributes:
        kinds: Accepted value kinds, any of ``str``, ``number_text``, ``int``, ``number``, ``bool``,
            ``list``, ``dict``, ``draft`` and ``draft_text``.
        nullable: Whether ``None`` is accepted.
    """

    kinds: tuple[str, ...]
    nullable: bool = False


TEXT = Field(("str",))
NUMBER_TEXT = Field(("number_text",))
INTEGER = Field(("int",))
NUMBER = Field(("number",))
BOOLEAN = Field(("bool",))
NULL = Field((), nullable=True)
LIST = Field(("list",))
DRAFT = Field(("draft",))
DRAFT_TEXT = Field(("draft_text",))

INLINE_ENTITY_FIELDS: dict[str, dict[str, Field]] = {
    "amount": {
        "amount": NUMBER_TEXT,
        "error": BOOLEAN,
        "guid": TEXT,
        "id": INTEGER,
        "label": TEXT,
        "scientificNotation": BOOLEAN,
        "unit": INTEGER,
    },
    "temperature": {
        "temperature": NUMBER_TEXT,
        "error_temperature": BOOLEAN,
        "guid": TEXT,
        "id": INTEGER,
        "label": TEXT,
        "scientificNotation": BOOLEAN,
        "unit": INTEGER,
    },
    "concentration": {
        "concentration": NUMBER_TEXT,
        "error_concentration": BOOLEAN,
        "guid": TEXT,
        "id": INTEGER,
        "label": TEXT,
        "scientificNotation": BOOLEAN,
        "unit": INTEGER,
    },
    "duration": {
        "duration": INTEGER,
        "guid": TEXT,
        "id": INTEGER,
        "label": TEXT,
        "pause": NULL,
        "preset": LIST,
        "start": NULL,
    },
    "file": {
        "guid": TEXT,
        "id": INTEGER,
        "original_name": TEXT,
        "placeholder": TEXT,
        "size": INTEGER,
        "source": TEXT,
    },
    "link": {
        "guid": TEXT,
        "url": TEXT,
    },
    "gotostep": {
        "guid": TEXT,
        "step_guid": TEXT,
        "title": TEXT,
    },
    "reagents": {
        "id": INTEGER,
        "guid": TEXT,
        "name": TEXT,
        "mol_weight": NUMBER,
        "sku": TEXT,
        "url": TEXT,
        "cas_number": TEXT,
        "rrid": TEXT,
        "vendor": Field(("dict",)),
        "is_public": BOOLEAN,
        "can_edit": BOOLEAN,
    },
}

VENDOR_FIELDS: dict[str, Field] = {
    "id": INTEGER,
    "name": TEXT,
    "link": TEXT,
    "is_requested": BOOLEAN,
    "image": Field(("dict",)),
}

ATOMIC_ENTITY_FIELDS: dict[str, dict[str, Field]] = {
    "image": {
        "alt": TEXT,
        "guid": TEXT,
        "height": NUMBER,
        "id": INTEGER,
        "is_video": BOOLEAN,
        "legend": DRAFT_TEXT,
        "mime": TEXT,
        "nestedSelector": NULL,
        "original_name": TEXT,
        "placeholder": TEXT,
        "shadow": BOOLEAN,
        "source": TEXT,
        "width": NUMBER,
    },
    "notes": {"blocks": LIST, "entityMap": Field(("dict", "list"))},
    "result": {"blocks": LIST, "entityMap": Field(("dict", "list"))},
    "safety": {"blocks": LIST, "entityMap": Field(("dict", "list"))},
}

NESTED_DRAFT_ENTITIES = frozenset({"notes", "result", "safety"})

UNCHECKED_INLINE_ENTITIES = frozenset({"ph", "centrifuge", "shaker", "tex_formula", "formula", "software"})

UNCHECKED_ATOMIC_ENTITIES = frozenset(
    {"equipment", "tables", "protocols", "video", "dataset", "command", "embed", "code_insert", "documents"}
)

INLINE_ENTITY_TYPES = frozenset(INLINE_ENTITY_FIELDS) | UNCHECKED_INLINE_ENTITIES
ATOMIC_ENTITY_TYPES = frozenset(ATOMIC_ENTITY_FIELDS) | UNCHECKED_ATOMIC_ENTITIES
SPANNING_ENTITY_TYPES = frozenset({"link"})
