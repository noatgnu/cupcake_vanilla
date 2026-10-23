"""Conversion of Cupcake step annotations into protocols.io run comments."""

from __future__ import annotations

import hashlib
import json
import logging
import struct
import zlib
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.utils import timezone

from choux import Draft, ProtocolsIO, image_dimensions
from choux.draft import bold, file_attachment, image, italic

logger = logging.getLogger(__name__)

DIGEST_VERSION = "3"
MAX_IMAGE_WIDTH = 600
MAX_SKETCH_SIDE = 2000
SKETCH_BACKGROUND = b"\xff\xff\xff"
STRUCTURED_TYPES = frozenset({"checklist", "counter", "table", "alignment", "randomization"})
TYPE_LABELS = {
    "text": "Note",
    "file": "File",
    "image": "Image",
    "video": "Video",
    "audio": "Audio",
    "sketch": "Sketch",
    "other": "Attachment",
    "checklist": "Checklist",
    "counter": "Counter",
    "table": "Table",
    "alignment": "Alignment",
    "calculator": "Calculator",
    "mcalculator": "Molarity calculator",
    "randomization": "Randomization",
    "metadata": "Metadata",
    "booking": "Instrument booking",
}


@dataclass
class CommentContent:
    """
    A run comment built from a step annotation.

    Attributes:
        draft: Comment content.
        files_uploaded: Number of files uploaded to protocols.io for the comment.
        warnings: Messages about content that was left out.
    """

    draft: Draft
    files_uploaded: int = 0
    warnings: list[str] = field(default_factory=list)


def max_upload_bytes() -> int:
    """Return the largest annotation file uploaded to protocols.io."""
    return settings.PROTOCOLS_IO_MAX_UPLOAD_BYTES


def author_name(user: Any) -> str:
    """
    Return the name shown for an annotation author.

    Args:
        user: A Django user or ``None``.
    """
    if user is None:
        return "unknown"
    return user.get_full_name() or user.username


def file_size(annotation: Any) -> int | None:
    """
    Return the size of an annotation file, or ``None`` when it has no readable file.

    Args:
        annotation: A :class:`ccc.models.Annotation`.
    """
    if not annotation.file:
        return None
    try:
        return annotation.file.size
    except (OSError, ValueError):
        return None


def booking_lines(step_annotation: Any) -> list[str]:
    """
    Return one line for each instrument usage linked to a step annotation.

    Args:
        step_annotation: A :class:`ccrv.models.StepAnnotation`.
    """
    lines = []
    for link in step_annotation.instrument_usage_links.all():
        usage = link.instrument_usage
        name = usage.instrument.instrument_name if usage.instrument_id else "Unknown instrument"
        start = _format_time(usage.time_started)
        end = _format_time(usage.time_ended)
        lines.append(f"{name}: {start or 'not set'} to {end or 'not set'}")
    return lines


def annotation_digest(step_annotation: Any) -> str:
    """
    Return a hash of everything a step annotation contributes to its run comment.

    Args:
        step_annotation: A :class:`ccrv.models.StepAnnotation`.
    """
    annotation = step_annotation.annotation
    content = {
        "version": DIGEST_VERSION,
        "type": annotation.annotation_type,
        "text": annotation.annotation,
        "transcription": annotation.transcription,
        "translation": annotation.translation,
        "language": annotation.language,
        "file": annotation.file.name if annotation.file else None,
        "size": file_size(annotation),
        "author": author_name(annotation.owner),
        "created": annotation.created_at.isoformat() if annotation.created_at else None,
        "bookings": booking_lines(step_annotation) if annotation.annotation_type == "booking" else [],
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()


def annotation_comment(step_annotation: Any, client: ProtocolsIO) -> CommentContent:
    """
    Build the run comment for a step annotation, uploading its file to protocols.io.

    Args:
        step_annotation: A :class:`ccrv.models.StepAnnotation`.
        client: Client for the account that owns the run.
    """
    annotation = step_annotation.annotation
    kind = annotation.annotation_type
    content = CommentContent(Draft())
    created = _format_time(annotation.created_at)
    content.draft.paragraph(
        bold(f"{TYPE_LABELS.get(kind, kind.title())} from Cupcake"),
        f" by {author_name(annotation.owner)}" + (f", {created}" if created else ""),
    )
    if kind == "calculator":
        _lines(content.draft, calculator_lines(annotation.annotation))
    elif kind == "mcalculator":
        _lines(content.draft, molarity_lines(annotation.annotation))
    elif kind in STRUCTURED_TYPES:
        _lines(content.draft, structured_lines(annotation.annotation))
    else:
        _lines(content.draft, (annotation.annotation or "").splitlines())
    if kind == "booking":
        _lines(content.draft, booking_lines(step_annotation))
    if annotation.file:
        _attach_file(content, annotation, client)
    language = f" ({annotation.language})" if annotation.language else ""
    transcription = annotation.transcription
    if transcription and transcription == annotation.translation:
        transcription = None
    for label, text, suffix in (
        (f"Transcription{language}", transcription, "transcription"),
        ("Translation", annotation.translation, "translation"),
    ):
        if text:
            content.draft.paragraph(italic(label))
            _lines(content.draft, vtt_lines(text))
            _attach_subtitles(content, annotation, text, suffix, client)
    return content


def calculator_lines(text: str) -> list[str]:
    """
    Return one line for each calculation in a calculator annotation.

    Args:
        text: The JSON history stored in the annotation.
    """
    entries = _json_list(text)
    if entries is None:
        return (text or "").splitlines()
    lines = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("scratched"):
            continue
        first = entry.get("inputPromptFirstValue")
        second = entry.get("inputPromptSecondValue")
        operation = entry.get("operation", "")
        if second is None or second == "":
            lines.append(f"{operation}({_number(first)}) = {_number(entry.get('result'))}")
        else:
            lines.append(f"{_number(first)} {operation} {_number(second)} = {_number(entry.get('result'))}")
    return lines


def molarity_lines(text: str) -> list[str]:
    """
    Return one line for each calculation in a molarity calculator annotation.

    Args:
        text: The JSON history stored in the annotation.
    """
    entries = _json_list(text)
    if entries is None:
        return (text or "").splitlines()
    lines = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("scratched"):
            continue
        data = entry.get("data") or {}
        inputs = []
        for name, unit_key in (
            ("concentration", "concentrationUnit"),
            ("volume", "volumeUnit"),
            ("weight", "weightUnit"),
            ("molecularWeight", None),
        ):
            value = data.get(name)
            if value is None or value == "":
                continue
            unit = data.get(unit_key) if unit_key else "g/mol"
            inputs.append(f"{_label(name)} {_number(value)}{' ' + unit if unit else ''}")
        target = _label(entry.get("calculatedField") or entry.get("operationType") or "result")
        line = f"{target} = {_number(entry.get('result'))}"
        if inputs:
            line += f" (from {', '.join(inputs)})"
        lines.append(line)
    return lines


def structured_lines(text: str) -> list[str]:
    """
    Return readable lines for annotation content stored as JSON.

    Args:
        text: The annotation text.
    """
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return (text or "").splitlines()
    return list(_describe(data))


def vtt_lines(text: str) -> list[str]:
    """
    Return one line for each cue of a WebVTT transcript, starting with its start time, or the lines of plain text.

    Args:
        text: Transcript text.
    """
    if not is_webvtt(text):
        return [line.strip() for line in text.splitlines() if line.strip()]
    lines = []
    start = None
    cue: list[str] = []
    in_note = False
    for raw in text.splitlines() + [""]:
        line = raw.strip()
        if not line:
            if start is not None and cue:
                lines.append(f"{start} {' '.join(cue)}")
            start, cue, in_note = None, [], False
            continue
        if in_note or line.startswith("WEBVTT"):
            continue
        if line.startswith("NOTE") and start is None:
            in_note = True
        elif "-->" in line:
            start = cue_time(line.split("-->")[0])
        elif start is not None:
            cue.append(line)
    return lines


def is_webvtt(text: str) -> bool:
    """
    Whether text is a WebVTT document.

    Args:
        text: Transcript text.
    """
    return text.lstrip("\ufeff").lstrip().startswith("WEBVTT")


def cue_time(timestamp: str) -> str:
    """
    Return a cue timestamp such as ``00:01:02.500`` as ``1:02``.

    Args:
        timestamp: WebVTT timestamp.
    """
    whole = timestamp.strip().split(".")[0]
    parts = [int(part) for part in whole.split(":") if part.isdigit()]
    if not parts:
        return timestamp.strip()
    while len(parts) < 3:
        parts.insert(0, 0)
    hours, minutes, seconds = parts[-3:]
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def sketch_png(text: str) -> tuple[bytes, int, int] | None:
    """
    Draw the strokes of a Cupcake sketch as a PNG image on a white background.

    Sketches larger than ``MAX_SKETCH_SIDE`` pixels on a side are scaled down.

    Args:
        text: The JSON stroke data of the sketch file.

    Returns:
        The PNG content, its width and its height, or ``None`` when the data cannot be read.
    """
    try:
        data = json.loads(text)
        source_width = int(data["width"])
        source_height = int(data["height"])
        strokes = data.get("strokes") or []
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    if source_width <= 0 or source_height <= 0:
        return None
    scale = min(1.0, MAX_SKETCH_SIDE / max(source_width, source_height))
    width = max(1, round(source_width * scale))
    height = max(1, round(source_height * scale))
    pixels = bytearray(SKETCH_BACKGROUND * (width * height))
    for stroke in strokes:
        if not isinstance(stroke, dict):
            continue
        try:
            points = [(float(point["x"]) * scale, float(point["y"]) * scale) for point in stroke.get("points") or []]
            radius = max(0.5, float(stroke.get("width") or 1) * scale / 2)
        except (TypeError, ValueError, KeyError):
            continue
        if len(points) < 2:
            continue
        colour = SKETCH_BACKGROUND if stroke.get("color") == "eraser" else _rgb(stroke.get("color"))
        disc = _disc(radius)
        spacing = max(0.5, radius / 2)
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            steps = max(1, int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / spacing))
            for step in range(steps + 1):
                cx = round(x0 + (x1 - x0) * step / steps)
                cy = round(y0 + (y1 - y0) * step / steps)
                for dx, dy in disc:
                    x, y = cx + dx, cy + dy
                    if 0 <= x < width and 0 <= y < height:
                        offset = (y * width + x) * 3
                        pixels[offset : offset + 3] = colour
    return _encode_png(pixels, width, height), width, height


def _rgb(colour: Any) -> bytes:
    text = str(colour or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    try:
        return bytes.fromhex(text[:6]) if len(text) >= 6 else b"\x00\x00\x00"
    except ValueError:
        return b"\x00\x00\x00"


def _disc(radius: float) -> list[tuple[int, int]]:
    reach = int(radius + 0.5)
    return [
        (dx, dy)
        for dy in range(-reach, reach + 1)
        for dx in range(-reach, reach + 1)
        if dx * dx + dy * dy <= radius * radius + 0.25
    ]


def _encode_png(pixels: bytearray, width: int, height: int) -> bytes:
    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    row = width * 3
    raw = b"".join(b"\x00" + bytes(pixels[y * row : (y + 1) * row]) for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _attach_file(content: CommentContent, annotation: Any, client: ProtocolsIO) -> None:
    name = annotation.file.name.rsplit("/", 1)[-1]
    size = file_size(annotation)
    if size is None:
        content.warnings.append(f"File {name} is missing from Cupcake storage and was left out")
        return
    if size > max_upload_bytes():
        content.warnings.append(f"File {name} is larger than the upload limit and was left out")
        return
    with annotation.file.open("rb") as handle:
        data = handle.read()
    if annotation.annotation_type == "sketch":
        drawn = sketch_png(data.decode("utf-8", errors="replace"))
        if drawn is not None:
            picture, width, height = drawn
            uploaded = client.upload_file(
                name.rsplit(".", 1)[0] + ".png", picture, mime_type="image/png", width=width, height=height
            )
            content.files_uploaded += 1
            content.draft.block_entity(image(uploaded, **_display_size(width, height)))
            return
    if annotation.annotation_type == "image":
        dimensions = image_dimensions(data)
        if dimensions is not None:
            width, height = dimensions
            uploaded = client.upload_file(name, data, width=width, height=height)
            content.files_uploaded += 1
            content.draft.block_entity(image(uploaded, **_display_size(width, height)))
            return
    uploaded = client.upload_file(name, data)
    content.files_uploaded += 1
    content.draft.paragraph(file_attachment(uploaded))


def _attach_subtitles(content: CommentContent, annotation: Any, text: str, suffix: str, client: ProtocolsIO) -> None:
    if not is_webvtt(text):
        return
    data = text.encode("utf-8")
    if len(data) > max_upload_bytes():
        content.warnings.append(
            f"The {suffix} of annotation {annotation.pk} is larger than the upload limit and was left out"
        )
        return
    stem = (
        annotation.file.name.rsplit("/", 1)[-1].rsplit(".", 1)[0] if annotation.file else f"annotation-{annotation.pk}"
    )
    uploaded = client.upload_file(f"{stem}.{suffix}.vtt", data, mime_type="text/vtt")
    content.files_uploaded += 1
    content.draft.paragraph(file_attachment(uploaded))


def _display_size(width: int, height: int) -> dict[str, float]:
    if width <= MAX_IMAGE_WIDTH:
        return {"width": width, "height": height}
    return {"width": MAX_IMAGE_WIDTH, "height": round(height * MAX_IMAGE_WIDTH / width)}


def _lines(draft: Draft, lines: Any) -> None:
    for line in lines:
        if line.strip():
            draft.paragraph(line)


def _json_list(text: str) -> list[Any] | None:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _describe(data: Any, prefix: str = ""):
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                yield f"{prefix}{_label(str(key))}:"
                yield from _describe(value, prefix + "  ")
            else:
                yield f"{prefix}{_label(str(key))}: {_scalar(value)}"
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and all(not isinstance(value, (dict, list)) for value in item.values()):
                yield prefix + "; ".join(f"{_label(str(key))}: {_scalar(value)}" for key, value in item.items())
            elif isinstance(item, (dict, list)):
                yield from _describe(item, prefix + "  ")
            else:
                yield f"{prefix}{_scalar(item)}"
    else:
        yield f"{prefix}{_scalar(data)}"


def _label(name: str) -> str:
    spaced = "".join(f" {char.lower()}" if char.isupper() else char for char in name).replace("_", " ").strip()
    return spaced[:1].upper() + spaced[1:]


def _scalar(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if value is None:
        return ""
    return _number(value) if isinstance(value, (int, float)) else str(value)


def _number(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _format_time(value: Any) -> str:
    if not value:
        return ""
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M %Z")
