"""Import of protocols.io protocols into Cupcake protocols."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from django.db import transaction

import requests
from bs4 import BeautifulSoup
from choux import ProtocolsIO

from ccrv.models import ProtocolModel, ProtocolSection, ProtocolStep
from cupcake_protocols_io import conf

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


def resolve_protocols_io_url(url: str) -> tuple[str, str]:
    """
    Return the canonical address of a protocols.io protocol and its URI.

    The page at ``url`` is read for its ``og:url`` meta tag, so DOI links and addresses with a
    version suffix resolve to the protocol itself.

    Args:
        url: Address or DOI link of a protocols.io protocol.

    Returns:
        Tuple of the canonical address and the protocol URI.

    Raises:
        ValueError: When the page has no protocols.io address.
    """
    page = requests.get(url, timeout=30)
    soup = BeautifulSoup(page.content, "html.parser")
    for tag in soup.find_all("meta"):
        if tag.get("property", None) == "og:url":
            url = tag.get("content", None)
            break
    if not url:
        raise ValueError("Could not find protocol.io url")
    path_parts = [p for p in urlparse(url).path.split("/") if p]
    if not path_parts:
        raise ValueError(f"Could not find protocol.io protocol with url {url}")
    slug = path_parts[-2] if len(path_parts) > 1 and re.match(r"^v\d+$", path_parts[-1]) else path_parts[-1]
    return url, slug


def import_protocol_from_url(url: str, client: ProtocolsIO | None = None) -> ProtocolModel:
    """
    Create a protocol from a protocols.io address or DOI link.

    Args:
        url: Address or DOI link of a protocols.io protocol.
        client: protocols.io client acting as the importing user; the ``PROTOCOLS_IO_ACCESS_TOKEN``
            setting is used when omitted.

    Raises:
        ValueError: When the protocol cannot be found with the server token.
        choux.APIError: When protocols.io rejects the request made with ``client``.
    """
    url, slug = resolve_protocols_io_url(url)
    if client is not None:
        return import_protocol(client.get_protocol_v3(slug), url)

    protocol_meta = requests.get(
        f"https://www.protocols.io/api/v3/protocols/{slug}",
        headers={"Authorization": f"Bearer {conf.access_token()}"},
        timeout=30,
    )
    if protocol_meta.status_code != 200:
        raise ValueError(f"Could not find protocol.io protocol with url {url}")
    data = (protocol_meta.json() or {}).get("protocol")
    if not data:
        raise ValueError("Failed to import protocol from protocols.io")
    return import_protocol(data, url)


def import_protocol(data: Mapping[str, Any], url: str) -> ProtocolModel:
    """
    Create a protocol from a protocols.io protocol in the v3 format.

    Every step is placed in a section: consecutive steps without a section on protocols.io
    form an untitled section at their position.

    Args:
        data: The ``protocol`` object of the protocols.io v3 protocol response.
        url: Address of the protocol on protocols.io.

    Returns:
        The created :class:`ccrv.models.ProtocolModel`.
    """
    with transaction.atomic():
        protocol = ProtocolModel()
        protocol.protocol_id = data["id"]
        protocol.protocol_created_on = datetime.fromtimestamp(data["created_on"])
        protocol.protocol_doi = data["doi"]
        protocol.protocol_title = data["title"]
        protocol.protocol_description = data["description"]
        protocol.protocol_url = url
        protocol.protocol_version_uri = data["version_uri"]
        protocol.save()

        imported_steps = data["steps"] or []
        created = {}
        for section_order, imported in enumerate(group_into_sections(imported_steps)):
            section = ProtocolSection.objects.create(
                protocol=protocol,
                section_description=imported.title,
                section_duration=imported.duration,
                order=section_order,
            )
            for step_order, step in enumerate(imported.steps):
                description = next(
                    (
                        (component.get("source") or {}).get("description") or ""
                        for component in step.get("components") or []
                        if component.get("title") == "description"
                    ),
                    "",
                )
                created[step["id"]] = ProtocolStep.objects.create(
                    protocol=protocol,
                    step_section=section,
                    step_id=step["id"],
                    step_duration=step.get("duration"),
                    step_description=description,
                    order=step_order,
                )
        for step in imported_steps:
            previous = created.get(step.get("previous_id"))
            if previous is not None:
                created[step["id"]].previous_step = previous
                created[step["id"]].save(update_fields=["previous_step"])
    return protocol
