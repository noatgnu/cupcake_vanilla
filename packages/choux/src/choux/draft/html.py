"""Conversion of HTML fragments into Draft.js documents."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from html.parser import HTMLParser

from choux.draft.builder import Draft, Linked, Part, Span
from choux.draft.entities import Entity, link

ImageResolver = Callable[[str, dict[str, str]], Entity | None]
TextResolver = Callable[[str], Iterable[Part]]

BLOCK_TAGS = frozenset({"p", "div", "li", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"})
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
SKIPPED_TAGS = frozenset({"script", "style", "head", "title"})
STYLE_TAGS = {"strong": "bold", "b": "bold", "em": "italic", "i": "italic", "sup": "sup", "sub": "sub"}
ALIGNMENTS = {
    "left": "align-left",
    "center": "align-center",
    "right": "align-right",
    "justify": "align-justify",
}
WHITESPACE = re.compile(r"\s+")
TEXT_ALIGN = re.compile(r"text-align\s*:\s*(left|center|right|justify)", re.IGNORECASE)


def html_to_draft(
    html: str, *, image_resolver: ImageResolver | None = None, text_resolver: TextResolver | None = None
) -> Draft:
    """
    Convert an HTML fragment into a Draft.js document.

    Paragraphs, headings, line breaks, bulleted and numbered lists, bold, italics, superscript,
    subscript, links and text alignment are kept. Table rows become one paragraph each with cells
    separated by ``" | "``. Other markup is reduced to its text.

    Args:
        html: The HTML fragment.
        image_resolver: Called with the ``src`` and all attributes of each ``img`` element. Return
            an image entity, for example from :func:`choux.draft.entities.image` after uploading
            the file, or ``None`` to leave the image out. Images are left out when omitted.
        text_resolver: Called with each run of text, after whitespace is collapsed. Return the parts
            that replace it: strings, :class:`Span` objects and entities. Strings and spans take the
            styles of the surrounding markup, inline entities are placed in the text, and entities
            that need their own block start one. Text is kept as it is when omitted.

    Returns:
        The document, with at least one block.
    """
    parser = _DraftParser(image_resolver, text_resolver)
    parser.feed(html or "")
    parser.close()
    return parser.finish()


@dataclass
class _PendingBlock:
    parts: list[Part] = field(default_factory=list)
    block_type: str = "unstyled"
    depth: int = 0


class _DraftParser(HTMLParser):
    def __init__(self, image_resolver: ImageResolver | None, text_resolver: TextResolver | None):
        super().__init__(convert_charrefs=True)
        self.image_resolver = image_resolver
        self.text_resolver = text_resolver
        self.draft = Draft()
        self.block = _PendingBlock()
        self.styles: dict[str, int] = {"bold": 0, "italic": 0, "sup": 0, "sub": 0}
        self.lists: list[str] = []
        self.skip_depth = 0
        self.link_url: str | None = None
        self.link_parts: list[Span] = []
        self.cell_index = 0
        self.preformatted = 0
        self.open_items = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag in SKIPPED_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in ("ul", "ol"):
            self.flush()
            self.lists.append(tag)
        elif tag in BLOCK_TAGS:
            self.flush()
            self.block = _PendingBlock(block_type=self.block_type_for(tag, attributes), depth=self.list_depth(tag))
            if tag in HEADING_TAGS:
                self.styles["bold"] += 1
            if tag == "tr":
                self.cell_index = 0
            if tag == "pre":
                self.preformatted += 1
            if tag == "li":
                self.open_items += 1
        elif tag in ("td", "th"):
            if self.cell_index:
                self.add_text(" | ", collapse=False)
            self.cell_index += 1
            if tag == "th":
                self.styles["bold"] += 1
        elif tag == "br":
            self.flush(keep_type=True)
        elif tag in STYLE_TAGS:
            self.styles[STYLE_TAGS[tag]] += 1
        elif tag == "a" and attributes.get("href"):
            self.close_link()
            self.link_url = attributes["href"]
            self.link_parts = []
        elif tag == "img":
            self.add_image(attributes)

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in ("ul", "ol"):
            self.flush()
            if self.lists:
                self.lists.pop()
        elif tag in BLOCK_TAGS:
            self.flush()
            if tag in HEADING_TAGS:
                self.styles["bold"] = max(0, self.styles["bold"] - 1)
            if tag == "pre":
                self.preformatted = max(0, self.preformatted - 1)
            if tag == "li":
                self.open_items = max(0, self.open_items - 1)
        elif tag == "th":
            self.styles["bold"] = max(0, self.styles["bold"] - 1)
        elif tag in STYLE_TAGS:
            name = STYLE_TAGS[tag]
            self.styles[name] = max(0, self.styles[name] - 1)
        elif tag == "a":
            self.close_link()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.preformatted:
            lines = data.split("\n")
            for index, line in enumerate(lines):
                if index:
                    self.flush(keep_type=True)
                self.add_text(line, collapse=False)
            return
        self.add_text(data)

    def block_type_for(self, tag: str, attributes: dict[str, str]) -> str:
        if self.lists and (tag == "li" or self.open_items):
            return "ordered-list-item" if self.lists[-1] == "ol" else "unordered-list-item"
        alignment = TEXT_ALIGN.search(attributes.get("style", ""))
        if alignment:
            return ALIGNMENTS[alignment.group(1).lower()]
        for name in attributes.get("class", "").split():
            for value, block_type in ALIGNMENTS.items():
                if name.endswith(f"align-{value}"):
                    return block_type
        return "unstyled"

    def list_depth(self, tag: str) -> int:
        return max(0, len(self.lists) - 1) if self.lists and (tag == "li" or self.open_items) else 0

    def current_span(self, text: str) -> Span:
        return Span(
            text,
            bold=self.styles["bold"] > 0,
            italic=self.styles["italic"] > 0,
            sup=self.styles["sup"] > 0,
            sub=self.styles["sub"] > 0,
        )

    def add_text(self, data: str, *, collapse: bool = True) -> None:
        text = WHITESPACE.sub(" ", data) if collapse else data
        if not text:
            return
        if collapse and text.startswith(" ") and self.ends_with_space():
            text = text[1:]
        if not text:
            return
        if self.text_resolver is None:
            self.append_span(self.current_span(text))
            return
        for part in self.text_resolver(text):
            if isinstance(part, str):
                if part:
                    self.append_span(self.current_span(part))
            elif isinstance(part, Span):
                if part.text:
                    self.append_span(self.styled(part))
            elif isinstance(part, Entity):
                if part.is_atomic:
                    self.insert_block_entity(part)
                else:
                    self.close_link()
                    self.block.parts.append(part)
            else:
                raise TypeError(f"text_resolver returned unsupported part {type(part).__name__}")

    def append_span(self, span: Span) -> None:
        if self.link_url is not None:
            self.link_parts.append(span)
        else:
            self.block.parts.append(span)

    def styled(self, span: Span) -> Span:
        current = self.current_span(span.text)
        return Span(
            span.text,
            bold=span.bold or current.bold,
            italic=span.italic or current.italic,
            sup=span.sup or current.sup,
            sub=span.sub or current.sub,
        )

    def ends_with_space(self) -> bool:
        parts = self.link_parts if self.link_url is not None and self.link_parts else self.block.parts
        if not parts:
            return True
        last = parts[-1]
        if isinstance(last, Span):
            return last.text.endswith(" ")
        if isinstance(last, Linked):
            return last.span.text.endswith(" ")
        return False

    def close_link(self) -> None:
        if self.link_url is None:
            return
        url = self.link_url
        parts = self.link_parts
        self.link_url = None
        self.link_parts = []
        text = "".join(part.text for part in parts)
        if not text.strip():
            return
        first = parts[0]
        span = Span(text, bold=first.bold, italic=first.italic, sup=first.sup, sub=first.sub)
        self.block.parts.append(Linked(span, link(url)))

    def add_image(self, attributes: dict[str, str]) -> None:
        if self.image_resolver is None or not attributes.get("src"):
            return
        entity = self.image_resolver(attributes["src"], attributes)
        if entity is not None:
            self.insert_block_entity(entity)

    def insert_block_entity(self, entity: Entity) -> None:
        block_type, depth = self.block.block_type, self.block.depth
        self.flush()
        self.draft.block_entity(entity)
        self.block = _PendingBlock(block_type=block_type, depth=depth)

    def flush(self, *, keep_type: bool = False) -> None:
        self.close_link()
        block_type, depth = self.block.block_type, self.block.depth
        parts = _trim(self.block.parts)
        if parts:
            self.draft.paragraph(*parts, depth=depth, block_type=block_type)
        self.block = _PendingBlock(block_type=block_type, depth=depth) if keep_type else _PendingBlock()

    def finish(self) -> Draft:
        self.flush()
        if self.draft.is_empty:
            self.draft.paragraph("")
        return self.draft


def _trim(parts: list[Part]) -> list[Part]:
    trimmed = list(parts)
    while trimmed and isinstance(trimmed[0], Span) and not trimmed[0].text.strip():
        trimmed.pop(0)
    while trimmed and isinstance(trimmed[-1], Span) and not trimmed[-1].text.strip():
        trimmed.pop()
    if trimmed and isinstance(trimmed[0], Span):
        first = trimmed[0]
        trimmed[0] = Span(first.text.lstrip(), first.bold, first.italic, first.sup, first.sub)
    if trimmed and isinstance(trimmed[-1], Span):
        last = trimmed[-1]
        trimmed[-1] = Span(last.text.rstrip(), last.bold, last.italic, last.sup, last.sub)
    return trimmed
