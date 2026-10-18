"""Assembly of Draft.js documents from text, styled spans and entities."""

from __future__ import annotations

import json
import secrets
import string
from dataclasses import dataclass
from typing import Any, Union

from choux.draft.entities import Entity, link
from choux.draft.schema import PLACEHOLDER

KEY_ALPHABET = string.ascii_lowercase + string.digits


@dataclass(frozen=True)
class Span:
    """
    Text with inline styles.

    Attributes:
        text: The text.
        bold: Render in bold.
        italic: Render in italics.
        sup: Render as superscript.
        sub: Render as subscript.
    """

    text: str
    bold: bool = False
    italic: bool = False
    sup: bool = False
    sub: bool = False

    @property
    def styles(self) -> list[str]:
        """Names of the inline styles this span carries."""
        return [name for name in ("bold", "italic", "sup", "sub") if getattr(self, name)]


@dataclass(frozen=True)
class Linked:
    """
    Text that links to an address.

    Attributes:
        span: The visible text and its styles.
        entity: The link entity.
    """

    span: Span
    entity: Entity


Part = Union[str, Span, Linked, Entity]


def bold(text: str) -> Span:
    """Return ``text`` in bold."""
    return Span(text, bold=True)


def italic(text: str) -> Span:
    """Return ``text`` in italics."""
    return Span(text, italic=True)


def superscript(text: str) -> Span:
    """Return ``text`` as superscript."""
    return Span(text, sup=True)


def subscript(text: str) -> Span:
    """Return ``text`` as subscript."""
    return Span(text, sub=True)


def hyperlink(text: str | Span, url: str) -> Linked:
    """
    Return text that links to ``url``.

    Args:
        text: Visible text.
        url: Target address.
    """
    span = text if isinstance(text, Span) else Span(text)
    return Linked(span, link(url))


class Draft:
    """
    A Draft.js document as used for protocols.io step text, descriptions and notes.

    Inline entities such as amounts and durations take one placeholder character in the text and
    protocols.io renders their value in its place, so text around an entity should not repeat
    the value. Images and note boxes go in their own block through :meth:`block_entity`.

    Example:
        >>> draft = Draft()
        >>> draft.paragraph("Spin for ", duration(300), " at ", temperature(4), ".")
    """

    def __init__(self) -> None:
        """Start an empty document."""
        self._blocks: list[dict[str, Any]] = []
        self._entities: list[Entity] = []
        self._keys: set[str] = set()

    @property
    def is_empty(self) -> bool:
        """Whether the document has no blocks."""
        return not self._blocks

    @property
    def entities(self) -> list[Entity]:
        """Entities in the order they were added."""
        return list(self._entities)

    def paragraph(self, *parts: Part, depth: int = 0, block_type: str = "unstyled") -> Draft:
        """
        Add a block of text.

        Args:
            parts: Plain strings, styled spans, links and inline entities, in reading order.
            depth: Nesting level, used for lists.
            block_type: Draft.js block type.

        Returns:
            This document, for chaining.

        Raises:
            ValueError: When an entity that needs its own block is passed.
        """
        text: list[str] = []
        styles: list[dict[str, Any]] = []
        ranges: list[dict[str, Any]] = []
        offset = 0
        for part in parts:
            if isinstance(part, str):
                part = Span(part)
            if isinstance(part, Span):
                styles.extend(self._style_ranges(part, offset))
                text.append(part.text)
                offset += len(part.text)
            elif isinstance(part, Linked):
                if part.span.text:
                    styles.extend(self._style_ranges(part.span, offset))
                    ranges.append({"offset": offset, "length": len(part.span.text), "key": self._add(part.entity)})
                    text.append(part.span.text)
                    offset += len(part.span.text)
            elif isinstance(part, Entity):
                if part.is_atomic:
                    raise ValueError(f"{part.type} entities need their own block, use block_entity()")
                ranges.append({"offset": offset, "length": 1, "key": self._add(part)})
                text.append(PLACEHOLDER)
                offset += 1
            else:
                raise TypeError(f"unsupported paragraph part {type(part).__name__}")
        self._blocks.append(self._block("".join(text), block_type, depth, styles, ranges))
        return self

    def bullet(self, *parts: Part, depth: int = 0) -> Draft:
        """Add an item of a bulleted list. See :meth:`paragraph` for the arguments."""
        return self.paragraph(*parts, depth=depth, block_type="unordered-list-item")

    def numbered(self, *parts: Part, depth: int = 0) -> Draft:
        """Add an item of a numbered list. See :meth:`paragraph` for the arguments."""
        return self.paragraph(*parts, depth=depth, block_type="ordered-list-item")

    def block_entity(self, entity: Entity) -> Draft:
        """
        Add an entity that is shown as its own block, such as an image or a note box.

        Args:
            entity: The entity.

        Returns:
            This document, for chaining.

        Raises:
            ValueError: When the entity belongs inside text instead.
        """
        if not entity.is_atomic:
            raise ValueError(f"{entity.type} entities go inside text, use paragraph()")
        key = self._add(entity)
        self._blocks.append(self._block(PLACEHOLDER, "atomic", 0, [], [{"offset": 0, "length": 1, "key": key}]))
        return self

    def extend(self, other: Draft) -> Draft:
        """
        Append every block of another document.

        Args:
            other: Document to copy blocks from.

        Returns:
            This document, for chaining.
        """
        payload = other.to_dict()
        for block in payload["blocks"]:
            remapped = [
                {**entity_range, "key": self._add(other._entities[entity_range["key"]])}
                for entity_range in block["entityRanges"]
            ]
            self._blocks.append(
                self._block(block["text"], block["type"], block["depth"], block["inlineStyleRanges"], remapped)
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        """Return the raw Draft.js document."""
        return {
            "blocks": [dict(block) for block in self._blocks],
            "entityMap": {str(index): entity.to_dict() for index, entity in enumerate(self._entities)},
        }

    def to_json(self) -> str:
        """Return the document as the JSON text protocols.io stores."""
        return json.dumps(self.to_dict(), separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_text(cls, text: str) -> Draft:
        """
        Build a document from plain text, one paragraph per non-empty line.

        Args:
            text: Plain text.
        """
        draft = cls()
        for line in text.splitlines():
            if line.strip():
                draft.paragraph(line.strip())
        if draft.is_empty:
            draft.paragraph("")
        return draft

    def _add(self, entity: Entity) -> int:
        self._entities.append(entity)
        return len(self._entities) - 1

    def _new_key(self) -> str:
        while True:
            key = "".join(secrets.choice(KEY_ALPHABET) for _ in range(5))
            if key not in self._keys:
                self._keys.add(key)
                return key

    @staticmethod
    def _style_ranges(span: Span, offset: int) -> list[dict[str, Any]]:
        if not span.text:
            return []
        return [{"offset": offset, "length": len(span.text), "style": style} for style in span.styles]

    def _block(
        self,
        text: str,
        block_type: str,
        depth: int,
        styles: list[dict[str, Any]],
        ranges: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "key": self._new_key(),
            "text": text,
            "type": block_type,
            "depth": depth,
            "inlineStyleRanges": styles,
            "entityRanges": ranges,
            "data": {},
        }
