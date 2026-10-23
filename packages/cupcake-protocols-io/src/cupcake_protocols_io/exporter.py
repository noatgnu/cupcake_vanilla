"""Export of Cupcake protocols into existing protocols.io protocols."""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import mimetypes
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from django.conf import settings

from choux import ProtocolsIO, Step, chain, html_to_draft, image_dimensions
from choux.draft import Entity, image, number_text, raise_for_issues

from cupcake_protocols_io.step_templates import step_to_draft

logger = logging.getLogger(__name__)

STEP_GUID_NAMESPACE = uuid.UUID("6f1c3a52-8b0e-4f7d-9a35-2d7c0e4b91a6")
EXPORT_STAGES = 6


@dataclass
class ExportResult:
    """
    Outcome of exporting a protocol.

    Attributes:
        protocol_uri: URI of the protocols.io protocol.
        protocol_url: Address of the protocol on protocols.io.
        protocol_guid: GUID of the protocols.io protocol.
        protocol_id: Numeric id of the protocols.io protocol.
        step_ids: Ids of the exported Cupcake steps in protocols.io step order.
        steps_saved: Number of steps written.
        steps_deleted: GUIDs of deleted protocols.io steps that are not in the Cupcake protocol.
        images_uploaded: Number of images uploaded from step text.
        warnings: Messages about content that was left out or changed.
        unresolved_templates: Reagent templates naming reagents that are not on their step.
    """

    protocol_uri: str
    protocol_url: str
    protocol_guid: str = ""
    protocol_id: int = 0
    step_ids: list[int] = field(default_factory=list)
    steps_saved: int = 0
    steps_deleted: list[str] = field(default_factory=list)
    images_uploaded: int = 0
    warnings: list[str] = field(default_factory=list)
    unresolved_templates: list[str] = field(default_factory=list)


def export_step_guid(target_guid: str, step_id: int) -> str:
    """
    Return the protocols.io GUID used for a Cupcake step in a target protocol.

    The same step exported to the same target always gets the same GUID.

    Args:
        target_guid: GUID of the protocols.io protocol.
        step_id: Id of the Cupcake step.
    """
    return uuid.uuid5(STEP_GUID_NAMESPACE, f"{target_guid}:{step_id}").hex.upper()


def protocol_reference(text: str) -> str:
    """
    Return the protocol id, URI or GUID from what a user entered.

    Addresses of protocols.io protocol pages, such as ``https://www.protocols.io/edit/<uri>`` or
    ``https://www.protocols.io/view/<uri>/v2``, give their URI; anything else is returned trimmed.

    Args:
        text: Address, URI, id or GUID.
    """
    text = (text or "").strip()
    parsed = urlparse(text)
    if not parsed.netloc.endswith("protocols.io"):
        return text
    parts = [part for part in parsed.path.split("/") if part]
    if parts and re.fullmatch(r"v\d+", parts[-1]):
        parts = parts[:-1]
    return parts[-1] if parts else ""


def ordered_steps(protocol: Any) -> list[Any]:
    """
    Return the steps of a protocol in reading order, section by section.

    Steps outside any section are not included.

    Args:
        protocol: A :class:`ccrv.models.ProtocolModel`.
    """
    steps = []
    for section in protocol.sections.order_by("order", "id"):
        steps.extend(section.get_steps_by_order())
    return steps


def plain_text(content: str | None) -> str:
    """
    Return text with any HTML markup reduced to one line per paragraph.

    Args:
        content: Plain text or an HTML fragment.
    """
    if not content:
        return ""
    if "<" not in content:
        return content.strip()
    blocks = html_to_draft(content).to_dict()["blocks"]
    return "\n".join(block["text"] for block in blocks if block["text"].strip())


def materials_text(protocol: Any) -> str:
    """
    Return the materials list of a protocol as plain text, one reagent per line.

    Protocol reagents are listed with their quantity; reagents used only in steps follow by name.

    Args:
        protocol: A :class:`ccrv.models.ProtocolModel`.
    """
    lines = []
    listed = set()
    for protocol_reagent in protocol.protocol_reagents.select_related("reagent").order_by("id"):
        reagent = protocol_reagent.reagent
        unit = f" {reagent.unit}" if reagent.unit else ""
        lines.append(f"{reagent.name} - {number_text(protocol_reagent.quantity)}{unit}")
        listed.add(reagent.id)
    for step in ordered_steps(protocol):
        for step_reagent in step.reagents.select_related("reagent").order_by("id"):
            if step_reagent.reagent_id not in listed:
                lines.append(step_reagent.reagent.name)
                listed.add(step_reagent.reagent_id)
    return "\n".join(lines)


class StepImageUploader:
    """
    Image resolver for step text that uploads embedded and locally stored images to protocols.io.

    Data URLs and files under ``MEDIA_URL`` are uploaded once each; other images are left out
    with a warning.

    Attributes:
        uploaded: Number of images uploaded.
        warnings: Messages about images that were left out.
    """

    def __init__(self, client: ProtocolsIO):
        """Start with no uploaded images."""
        self.client = client
        self.uploaded = 0
        self.warnings: list[str] = []
        self._entities: dict[str, Entity] = {}

    def __call__(self, src: str, attributes: dict[str, str]) -> Entity | None:
        loaded = self._load(src)
        if loaded is None:
            self.warnings.append(f"Image left out because it is not stored in Cupcake: {src[:120]}")
            return None
        name, content = loaded
        digest = hashlib.sha256(content).hexdigest()
        if digest not in self._entities:
            width, height = self._dimensions(content, attributes)
            if width is None or height is None:
                self.warnings.append(f"Image left out because its size could not be read: {name}")
                return None
            uploaded = self.client.upload_file(name, content, width=width, height=height)
            self.uploaded += 1
            self._entities[digest] = image(uploaded, alt=attributes.get("alt", ""))
        return self._entities[digest]

    @staticmethod
    def _load(src: str) -> tuple[str, bytes] | None:
        if src.startswith("data:"):
            header, _, payload = src.partition(",")
            if ";base64" not in header:
                return None
            mime = header[5:].split(";")[0] or "image/png"
            try:
                content = base64.b64decode(payload, validate=False)
            except (binascii.Error, ValueError):
                return None
            extension = mimetypes.guess_extension(mime) or ".png"
            return f"step-image{extension}", content
        path = unquote(urlparse(src).path)
        media_url = urlparse(settings.MEDIA_URL).path
        if not media_url or not path.startswith(media_url):
            return None
        media_root = Path(settings.MEDIA_ROOT).resolve()
        file_path = (media_root / path[len(media_url) :]).resolve()
        if media_root not in file_path.parents or not file_path.is_file():
            return None
        return file_path.name, file_path.read_bytes()

    @staticmethod
    def _dimensions(content: bytes, attributes: dict[str, str]) -> tuple[int | None, int | None]:
        detected = image_dimensions(content)
        width, height = detected if detected else (None, None)
        if attributes.get("width", "").isdigit():
            width = int(attributes["width"])
        if attributes.get("height", "").isdigit():
            height = int(attributes["height"])
        return width, height


def export_protocol(
    protocol: Any,
    client: ProtocolsIO,
    target: int | str,
    *,
    scaling_factor: float = 1.0,
    progress: Callable[[int, int, str], None] | None = None,
    variations: Mapping[int, Any] | None = None,
    title: str | None = None,
    description: str | None = None,
) -> ExportResult:
    """
    Write a Cupcake protocol into an existing protocols.io protocol.

    The title, description, materials, steps, step times and section totals of the target are
    replaced. Steps of the target that do not come from this Cupcake protocol are deleted.
    Only steps inside sections are exported. Every step is validated before any step of the
    target is changed.

    Args:
        protocol: A :class:`ccrv.models.ProtocolModel`.
        client: Client for the account that owns the target.
        target: Id, URI or GUID of the protocols.io protocol.
        scaling_factor: Extra factor applied to scaled quantities of scalable reagents.
        progress: Called with the number of completed stages, the number of stages, and a
            description of the stage that starts next.
        variations: Step variations by Cupcake step id, whose text and duration replace those of their step.
        title: Title to use instead of the protocol title.
        description: Plain text description to use instead of the protocol description.

    Returns:
        What was written and any warnings.

    Raises:
        choux.DraftValidationError: When converted step content fails validation.
        choux.APIError: When protocols.io rejects a request.
    """
    report = progress or (lambda done, total, description: None)
    report(0, EXPORT_STAGES, "Reading the protocols.io protocol")
    details = client.get_protocol(target)
    target_guid = details["guid"]
    units = details.get("units") or []
    result = ExportResult(
        protocol_uri=details.get("uri", ""),
        protocol_url=details.get("url", ""),
        protocol_guid=target_guid,
        protocol_id=int(details.get("id") or 0),
    )
    images = StepImageUploader(client)

    report(1, EXPORT_STAGES, "Converting steps")
    cupcake_steps = ordered_steps(protocol)
    steps = []
    durations = {}
    replaced = variations or {}
    for cupcake_step in cupcake_steps:
        variation = replaced.get(cupcake_step.pk)
        draft, unresolved = step_to_draft(
            cupcake_step,
            units,
            scaling_factor=scaling_factor,
            image_resolver=images,
            text=variation.variation_description if variation is not None else None,
        )
        result.unresolved_templates.extend(unresolved)
        guid = export_step_guid(target_guid, cupcake_step.pk)
        section = cupcake_step.step_section.section_description if cupcake_step.step_section else None
        steps.append(Step(draft, guid=guid, section=plain_text(section) or None))
        durations[guid] = (variation.variation_duration if variation is not None else cupcake_step.step_duration) or 0
    chain(steps)
    result.step_ids = [cupcake_step.pk for cupcake_step in cupcake_steps]
    raise_for_issues(client.validate_steps(steps, units=units))

    report(2, EXPORT_STAGES, "Removing steps that are no longer in Cupcake")
    new_guids = {step.guid for step in steps}
    stale = [step["guid"] for step in client.get_steps(target) if step["guid"] not in new_guids]
    if stale:
        client.delete_steps(target, stale)
    result.steps_deleted = stale

    report(3, EXPORT_STAGES, "Saving steps")
    if steps:
        result.warnings.extend(issue.message for issue in client.save_steps(target, steps, units=units))
    result.steps_saved = len(steps)
    report(4, EXPORT_STAGES, "Saving title, description and materials")
    client.update_protocol(
        target,
        title=title or protocol.protocol_title,
        description=plain_text(protocol.protocol_description) if description is None else description,
        materials_text=materials_text(protocol),
    )
    report(5, EXPORT_STAGES, "Setting step times")
    client.set_step_durations(target, durations)
    saved = client.get_protocol(result.protocol_id or target)
    result.protocol_uri = saved.get("uri") or result.protocol_uri
    result.protocol_url = saved.get("url") or result.protocol_url
    report(EXPORT_STAGES, EXPORT_STAGES, "Done")

    result.images_uploaded = images.uploaded
    result.warnings.extend(images.warnings)
    outside = protocol.steps.filter(step_section__isnull=True).count()
    if outside:
        result.warnings.append(f"{outside} step(s) outside any section were not exported")
    for template in result.unresolved_templates:
        result.warnings.append(f"Reagent template {template} names a reagent that is not on its step")
    logger.info(
        "Exported protocol %s to protocols.io %s: %s steps, %s deleted, %s images",
        protocol.pk,
        result.protocol_uri,
        result.steps_saved,
        len(result.steps_deleted),
        result.images_uploaded,
    )
    return result
