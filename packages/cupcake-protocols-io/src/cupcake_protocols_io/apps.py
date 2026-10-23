"""Django app configuration of the protocols.io app."""

from django.apps import AppConfig

from ccc.task_types import register_task_type

TASK_TYPES = [
    ("EXPORT_PROTOCOLS_IO", "Export to protocols.io"),
    ("EXPORT_RUN_PROTOCOLS_IO", "Export session to protocols.io"),
]


class ProtocolsIOConfig(AppConfig):
    """Links Cupcake protocols and sessions with protocols.io."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "cupcake_protocols_io"
    label = "protocols_io"
    verbose_name = "protocols.io"

    def ready(self):
        """Register the export task types."""
        for code, label in TASK_TYPES:
            register_task_type(code, label)
