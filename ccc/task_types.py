"""Task types accepted by async task statuses, including those registered by installed apps."""

BUILTIN_TASK_TYPES = [
    ("EXPORT_EXCEL", "Export Excel Template"),
    ("EXPORT_SDRF", "Export SDRF File"),
    ("IMPORT_SDRF", "Import SDRF File"),
    ("IMPORT_EXCEL", "Import Excel File"),
    ("EXPORT_MULTIPLE_SDRF", "Export Multiple SDRF Files"),
    ("EXPORT_MULTIPLE_EXCEL", "Export Multiple Excel Templates"),
    ("VALIDATE_TABLE", "Validate Metadata Table"),
    ("REORDER_TABLE_COLUMNS", "Reorder Table Columns"),
    ("REORDER_TEMPLATE_COLUMNS", "Reorder Template Columns"),
    ("TRANSCRIBE_AUDIO", "Transcribe Audio"),
    ("TRANSCRIBE_VIDEO", "Transcribe Video"),
]

TASK_TYPE_MAX_LENGTH = 25

_registered: dict[str, str] = {}


def register_task_type(code: str, label: str) -> None:
    """
    Add a task type that async task statuses accept.

    Registering the same code with the same label again has no effect.

    Args:
        code: Value stored on the task status.
        label: Name shown to users.

    Raises:
        ValueError: When the code is too long, is built in, or is registered with another label.
    """
    if len(code) > TASK_TYPE_MAX_LENGTH:
        raise ValueError(f"task type {code!r} is longer than {TASK_TYPE_MAX_LENGTH} characters")
    if any(code == builtin for builtin, _ in BUILTIN_TASK_TYPES):
        raise ValueError(f"task type {code!r} is built in")
    if _registered.get(code, label) != label:
        raise ValueError(f"task type {code!r} is already registered as {_registered[code]!r}")
    _registered[code] = label


def task_type_choices() -> list[tuple[str, str]]:
    """Return the built-in task types followed by the registered ones."""
    return [*BUILTIN_TASK_TYPES, *_registered.items()]
