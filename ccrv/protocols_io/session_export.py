"""Export of Cupcake sessions into protocols.io runs."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from choux import APIError, Draft, DraftValidationError, ProtocolsIO, UploadError, records
from choux.draft import bold, hyperlink

from ccrv.models import ProtocolsIOExport, ProtocolsIORun, ProtocolsIORunComment, StepAnnotation, StepVariation
from ccrv.protocols_io.annotations import annotation_comment, annotation_digest
from ccrv.protocols_io.exporter import export_protocol, export_step_guid, ordered_steps, plain_text

logger = logging.getLogger(__name__)

Progress = Callable[[int, int, str], None]


class SessionExportError(Exception):
    """A session cannot be exported until the user changes something."""


@dataclass
class SessionExportResult:
    """
    Outcome of exporting a session.

    Attributes:
        run_id: Id of the Cupcake run entry.
        protocol_id: Id of the Cupcake protocol the run follows.
        record_guid: GUID of the protocols.io run.
        record_url: Address of the protocols.io run.
        title: Title of the protocols.io run.
        created: Whether the run was created by this export.
        variations_used: Number of steps whose session variation replaces the step.
        protocol_copy_url: Address of the protocols.io protocol with the session variations, empty when the
            run follows the exported protocol.
        comments_added: Number of annotations posted as new comments.
        comments_updated: Number of comments replaced because their annotation changed.
        comments_deleted: Number of comments removed because their annotation is gone or scratched.
        comments_unchanged: Number of comments left as they were.
        files_uploaded: Number of files uploaded.
        warnings: Messages about content that was left out or runs that were replaced.
    """

    run_id: int
    protocol_id: int
    record_guid: str
    record_url: str
    title: str
    created: bool = False
    variations_used: int = 0
    protocol_copy_url: str = ""
    comments_added: int = 0
    comments_updated: int = 0
    comments_deleted: int = 0
    comments_unchanged: int = 0
    files_uploaded: int = 0
    warnings: list[str] = field(default_factory=list)


def session_title(session: Any, protocol: Any = None, parts: int = 1) -> str:
    """
    Return the protocols.io run title for a session.

    Args:
        session: A :class:`ccrv.models.Session`.
        protocol: The :class:`ccrv.models.ProtocolModel` the run follows.
        parts: Number of protocols of the session being exported.
    """
    title = (session.name or "").strip() or f"Cupcake session {session.unique_id}"
    if protocol is not None and parts > 1:
        title = f"{title} - {protocol.protocol_title}"
    return title[:255]


def session_variations(session: Any, protocol: Any) -> dict[int, Any]:
    """
    Return the step variations of a session on the steps of a protocol, the latest one for each step.

    Args:
        session: A :class:`ccrv.models.Session`.
        protocol: A :class:`ccrv.models.ProtocolModel`.
    """
    variations = {}
    for variation in StepVariation.objects.filter(session=session, step__protocol=protocol).order_by("id"):
        variations[variation.step_id] = variation
    return variations


def variation_hash(variations: dict[int, Any]) -> str:
    """
    Return a hash of the text and duration of step variations, empty when there are none.

    Args:
        variations: Step variations by step id.
    """
    if not variations:
        return ""
    content = sorted(
        (step_id, variation.variation_description, variation.variation_duration)
        for step_id, variation in variations.items()
    )
    return hashlib.sha256(json.dumps(content).encode()).hexdigest()


def protocol_exports(protocol: Any):
    """
    Return the exports of a protocol that follow its own steps, most recent first.

    Args:
        protocol: A :class:`ccrv.models.ProtocolModel`.
    """
    return protocol.protocols_io_exports.filter(session__isnull=True)


def check_export(export: ProtocolsIOExport | None, protocol: Any, client: ProtocolsIO) -> ProtocolsIOExport:
    """
    Check that an export still matches the protocol in Cupcake and on protocols.io.

    Args:
        export: The export to check.
        protocol: A :class:`ccrv.models.ProtocolModel`.
        client: Client for the account that owns the protocols.io protocol.

    Raises:
        SessionExportError: When there is no export, or either copy changed since.
    """
    if export is None:
        raise SessionExportError("Export the protocol to protocols.io before exporting a session that uses it")
    if [step.pk for step in ordered_steps(protocol)] != list(export.step_ids):
        raise SessionExportError(
            "The protocol changed in Cupcake since it was exported to protocols.io; export the protocol again first"
        )
    expected = [export_step_guid(export.protocols_io_guid, step_id) for step_id in export.step_ids]
    remote = [step.get("guid") for step in client.get_steps(export.protocols_io_uri or export.protocols_io_id)]
    if remote != expected:
        raise SessionExportError(
            "The protocols.io protocol changed since it was exported from Cupcake; export the protocol again first"
        )
    return export


def check_protocol_export(protocol: Any, client: ProtocolsIO) -> ProtocolsIOExport:
    """
    Return the latest export of a protocol after checking that both copies still match.

    Args:
        protocol: A :class:`ccrv.models.ProtocolModel`.
        client: Client for the account that owns the protocols.io protocol.

    Raises:
        SessionExportError: When the protocol was never exported, or either copy changed since.
    """
    return check_export(protocol_exports(protocol).first(), protocol, client)


def copy_description(session: Any, protocol: Any) -> str:
    """
    Return the description of the protocols.io protocol that follows the variations of a session.

    Args:
        session: A :class:`ccrv.models.Session`.
        protocol: A :class:`ccrv.models.ProtocolModel` of the session.
    """
    lines = [f"Steps as performed in the Cupcake session {session_title(session)}."]
    original = protocol_exports(protocol).first()
    if original is not None and original.protocols_io_url:
        lines.append(f"Based on {original.protocols_io_url}")
    description = plain_text(protocol.protocol_description)
    if description:
        lines.append(description)
    return "\n".join(lines)


def protocol_copy(
    session: Any,
    protocol: Any,
    client: ProtocolsIO,
    variations: dict[int, Any],
    *,
    user: Any = None,
    progress: Progress | None = None,
) -> ProtocolsIOExport:
    """
    Return the protocols.io protocol whose steps follow the variations of a session.

    The latest copy with the same variations is reused while it still matches the protocol in Cupcake
    and on protocols.io; otherwise a new protocol is created.

    Args:
        session: A :class:`ccrv.models.Session`.
        protocol: A :class:`ccrv.models.ProtocolModel` of the session.
        client: Client for the exporting user's account.
        variations: Step variations of the session by step id.
        user: The exporting user.
        progress: Passed to :func:`ccrv.protocols_io.export_protocol`.
    """
    digest = variation_hash(variations)
    existing = protocol.protocols_io_exports.filter(session=session, exported_by=user, variation_hash=digest).first()
    if existing is not None:
        try:
            return check_export(existing, protocol, client)
        except (SessionExportError, APIError) as error:
            logger.info("Protocol copy %s cannot be reused: %s", existing.protocols_io_guid, error)
    created = client.create_protocol(uuid.uuid4().hex.upper())
    target = created.get("uri") or str(created["id"])
    result = export_protocol(
        protocol,
        client,
        target,
        variations=variations,
        title=f"{protocol.protocol_title} - {session_title(session)}"[:255],
        description=copy_description(session, protocol),
        progress=progress,
    )
    return ProtocolsIOExport.remember(protocol, user, result, session=session, variation_hash=digest)


def reference_comment(
    session: Any, protocol: Any, session_url: str = "", part: tuple[int, int] = (1, 1), variations_used: int = 0
) -> Draft:
    """
    Build the run comment that points back to the Cupcake session.

    Args:
        session: A :class:`ccrv.models.Session`.
        protocol: The :class:`ccrv.models.ProtocolModel` the run follows.
        session_url: Address of the session in Cupcake.
        part: Position of the protocol among the exported protocols of the session, and their number.
        variations_used: Number of steps replaced by session variations.
    """
    draft = Draft().paragraph("Exported from the Cupcake session ", bold(session_title(session)), ".")
    index, parts = part
    if parts > 1:
        draft.paragraph(f"Part {index} of {parts}: protocol ", bold(protocol.protocol_title), ".")
    if variations_used:
        draft.paragraph(f"{variations_used} step(s) follow the variations used in this session.")
    draft.paragraph(f"Cupcake session id: {session.unique_id}")
    if session_url:
        draft.paragraph(hyperlink("Open the session in Cupcake", session_url))
    return draft


def create_run(
    session: Any,
    protocol: Any,
    client: ProtocolsIO,
    export: ProtocolsIOExport,
    *,
    user: Any = None,
    folder_guid: str | None = None,
    session_url: str = "",
    part: tuple[int, int] = (1, 1),
    variations_used: int = 0,
) -> ProtocolsIORun:
    """
    Create a protocols.io run for a session from a checked protocol export.

    Args:
        session: A :class:`ccrv.models.Session`.
        protocol: A :class:`ccrv.models.ProtocolModel` of the session.
        client: Client for the account that owns the protocols.io protocol.
        export: The export the run is created from.
        user: The exporting user.
        folder_guid: File manager folder for the run.
        session_url: Address of the session in Cupcake.
        part: Position of the protocol among the exported protocols of the session, and their number.
        variations_used: Number of steps replaced by session variations.

    Raises:
        SessionExportError: When the run steps do not match the export.
    """
    record = client.create_record(export.protocols_io_uri or str(export.protocols_io_id), folder_guid=folder_guid)
    steps = record.get("steps") or []
    if len(steps) != len(export.step_ids):
        if record.get("item_id"):
            client.trash([record["item_id"]])
        raise SessionExportError("The new protocols.io run does not have the steps of the exported protocol")
    title = session_title(session, protocol, part[1])
    client.save_record(record["guid"], [records.set_title(title)])
    run = ProtocolsIORun.objects.create(
        session=session,
        protocol=protocol,
        protocol_export=export,
        exported_by=user,
        record_id=int(record.get("id") or 0),
        record_guid=record["guid"],
        item_id=int(record.get("item_id") or 0),
        title=title,
        variation_hash=export.variation_hash,
        step_map=[
            {"step": step_id, "id": step["id"], "guid": step["guid"]} for step_id, step in zip(export.step_ids, steps)
        ],
    )
    comment = client.add_record_comment(
        record["guid"], reference_comment(session, protocol, session_url, part, variations_used)
    )
    run.reference_comment_id = comment.get("discussion_id")
    run.save(update_fields=["reference_comment_id"])
    return run


def export_session(
    session: Any,
    protocol: Any,
    client: ProtocolsIO,
    run: ProtocolsIORun,
    *,
    created: bool = False,
    user: Any = None,
    part: tuple[int, int] = (1, 1),
    progress: Progress | None = None,
) -> SessionExportResult:
    """
    Write the step annotations on one protocol of a session into its protocols.io run as step comments.

    Comments whose annotation changed are replaced, and comments whose annotation is gone or
    scratched are deleted.

    Args:
        session: A :class:`ccrv.models.Session`.
        protocol: A :class:`ccrv.models.ProtocolModel` of the session.
        client: Client for the account that owns the run.
        run: The run to write into.
        created: Whether the run was created by this export.
        user: The exporting user.
        part: Position of the protocol among the exported protocols of the session, and their number.
        progress: Called with the number of completed items, the number of items, and a
            description of the item that starts next.

    Raises:
        choux.APIError: When protocols.io rejects a request.
    """
    report = progress or (lambda done, total, description: None)
    if not created:
        title = session_title(session, protocol, part[1])
        if title != run.title:
            client.save_record(run.record_guid, [records.set_title(title)])
            run.title = title
        run.exported_by = user or run.exported_by
        run.save(update_fields=["title", "exported_by", "exported_at"])
    export = run.protocol_export
    result = SessionExportResult(
        run_id=run.pk,
        protocol_id=protocol.pk,
        record_guid=run.record_guid,
        record_url=run.record_url,
        title=run.title,
        created=created,
        variations_used=len(session_variations(session, protocol)) if run.variation_hash else 0,
        protocol_copy_url=export.protocols_io_url if export is not None and export.session_id else "",
    )

    positions = {entry["step"]: index for index, entry in enumerate(run.step_map)}
    record_steps = {entry["step"]: entry["id"] for entry in run.step_map}
    step_annotations = sorted(
        StepAnnotation.objects.filter(session=session, step_id__in=positions, annotation__scratched=False)
        .select_related("annotation", "annotation__owner")
        .prefetch_related("instrument_usage_links__instrument_usage__instrument"),
        key=lambda item: (positions[item.step_id], item.order, item.created_at),
    )
    outside = (
        StepAnnotation.objects.filter(session=session, step__protocol=protocol, annotation__scratched=False)
        .exclude(step_id__in=positions)
        .count()
    )
    if outside:
        result.warnings.append(f"{outside} annotation(s) on steps that are not in the protocols.io run were left out")

    existing = {comment.step_annotation_id: comment for comment in run.comments.all() if comment.step_annotation_id}
    total = len(step_annotations) + 1
    kept = set()
    for done, step_annotation in enumerate(step_annotations, start=1):
        report(done, total, f"Exporting annotation {done} of {len(step_annotations)}")
        record_step_id = record_steps[step_annotation.step_id]
        digest = annotation_digest(step_annotation)
        comment = existing.get(step_annotation.pk)
        if comment is not None and comment.content_hash == digest and comment.record_step_id == record_step_id:
            kept.add(comment.pk)
            result.comments_unchanged += 1
            continue
        try:
            content = annotation_comment(step_annotation, client)
            if comment is not None and comment.record_step_id == record_step_id:
                client.edit_discussion(comment.discussion_id, content.draft)
                comment.content_hash = digest
                comment.save(update_fields=["content_hash", "exported_at"])
                result.comments_updated += 1
            else:
                posted = client.add_step_comment(run.record_guid, record_step_id, content.draft)
                if comment is not None:
                    _delete_discussion(client, comment.discussion_id, result)
                    comment.delete()
                comment = ProtocolsIORunComment.objects.create(
                    run=run,
                    step_annotation=step_annotation,
                    step_id=step_annotation.step_id,
                    record_step_id=record_step_id,
                    discussion_id=posted["discussion_id"],
                    content_hash=digest,
                )
                result.comments_added += 1
        except (DraftValidationError, UploadError) as error:
            result.warnings.append(f"Annotation {step_annotation.annotation_id} was left out: {error}")
            continue
        kept.add(comment.pk)
        result.files_uploaded += content.files_uploaded
        result.warnings.extend(content.warnings)

    report(total - 1, total, "Removing comments of deleted annotations")
    for comment in run.comments.exclude(pk__in=kept):
        _delete_discussion(client, comment.discussion_id, result)
        comment.delete()
        result.comments_deleted += 1
    report(total, total, "Done")
    logger.info(
        "Exported session %s to protocols.io run %s: %s added, %s updated, %s deleted, %s unchanged",
        session.pk,
        run.record_guid,
        result.comments_added,
        result.comments_updated,
        result.comments_deleted,
        result.comments_unchanged,
    )
    return result


def export_session_protocols(
    session: Any,
    protocols: list[Any],
    client: ProtocolsIO,
    *,
    user: Any = None,
    new_runs: bool = False,
    folder_guid: str | None = None,
    session_url: str = "",
    progress: Progress | None = None,
) -> list[SessionExportResult]:
    """
    Export a session into one protocols.io run for each of the given protocols.

    A protocol whose steps the session varied gets a protocols.io copy in which each varied step
    is replaced by its variation, and its run is created from that copy. The latest run of each
    protocol exported by ``user`` is updated unless ``new_runs`` is set or the variations changed
    since it was created. Every protocol whose run follows the exported protocol is checked before
    anything is written.

    Args:
        session: A :class:`ccrv.models.Session`.
        protocols: Protocols of the session, in the order of their runs.
        client: Client for the exporting user's account.
        user: The exporting user.
        new_runs: Create new runs even where earlier runs exist.
        folder_guid: File manager folder for new runs.
        session_url: Address of the session in Cupcake.
        progress: Called with the completed share, out of 100 for each protocol, the total, and a
            description of the step that starts next.

    Raises:
        SessionExportError: When a protocol export does not match the session.
        choux.APIError: When protocols.io rejects a request.
    """
    report = progress or (lambda done, total, description: None)
    parts = len(protocols)
    plans = []
    for protocol in protocols:
        variations = session_variations(session, protocol)
        digest = variation_hash(variations)
        run = None
        replaced = None
        if not new_runs:
            run = ProtocolsIORun.objects.filter(session=session, protocol=protocol, exported_by=user).first()
            if run is not None and run.variation_hash != digest:
                replaced, run = run, None
        plans.append((protocol, variations, run, replaced))
    report(0, parts * 100, "Checking the protocols on protocols.io")
    checked = {}
    for protocol, variations, run, _ in plans:
        if run is None and not variations:
            checked[protocol.pk] = check_protocol_export(protocol, client)
    results = []
    for index, (protocol, variations, run, replaced) in enumerate(plans, start=1):

        def step_progress(done, total, description, index=index, protocol=protocol):
            label = f"{protocol.protocol_title}: {description}" if parts > 1 else description
            report((index - 1) * 100 + done * 100 // max(total, 1), parts * 100, label)

        created = run is None
        if created:
            if variations:
                step_progress(0, 1, "Writing the protocol with the session variations")
                export = protocol_copy(session, protocol, client, variations, user=user)
            else:
                export = checked[protocol.pk]
            run = create_run(
                session,
                protocol,
                client,
                export,
                user=user,
                folder_guid=folder_guid,
                session_url=session_url,
                part=(index, parts),
                variations_used=len(variations),
            )
        result = export_session(
            session, protocol, client, run, created=created, user=user, part=(index, parts), progress=step_progress
        )
        if replaced is not None:
            result.warnings.insert(
                0,
                f"The step variations changed since the run {replaced.title} was created, so a new run was created",
            )
        results.append(result)
    report(parts * 100, parts * 100, "Done")
    return results


def _delete_discussion(client: ProtocolsIO, discussion_id: int, result: SessionExportResult) -> None:
    try:
        client.delete_discussion(discussion_id)
    except APIError as error:
        result.warnings.append(f"Comment {discussion_id} could not be removed from protocols.io: {error}")
