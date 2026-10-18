"""Change entries for experiment records, applied with :meth:`choux.ProtocolsIO.save_record`."""

from __future__ import annotations

from typing import Any


def set_title(title: str) -> dict[str, Any]:
    """
    Rename the record.

    Args:
        title: New title.
    """
    return {"type": "base", "data": {"title": title}}


def add_note(text: str, *, step_id: int = 0) -> dict[str, Any]:
    """
    Add a note to the record or to one of its steps.

    Args:
        text: Note text.
        step_id: Numeric id of the record step, ``0`` for a note on the whole record.
    """
    return {"type": "notes", "data": {"id": None, "note": text, "step_id": step_id}}


def edit_note(note_id: int, text: str) -> dict[str, Any]:
    """
    Replace the text of an existing note.

    Args:
        note_id: Id of the note.
        text: New note text.
    """
    return {"type": "notes", "data": {"id": note_id, "note": text}}


def mark_step(step_guid: str, *, checked: bool | None = None, skipped: bool | None = None) -> dict[str, Any]:
    """
    Mark a record step as done or skipped.

    Args:
        step_guid: GUID of the record step.
        checked: Whether the step is done.
        skipped: Whether the step was skipped.

    Raises:
        ValueError: When neither flag is given.
    """
    if checked is None and skipped is None:
        raise ValueError("pass checked, skipped, or both")
    data: dict[str, Any] = {"guid": step_guid}
    if checked is not None:
        data["is_checked"] = int(checked)
    if skipped is not None:
        data["is_skipped"] = int(skipped)
    return {"type": "step", "data": data}
