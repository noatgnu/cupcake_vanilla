"""Links between Cupcake protocols and sessions and their protocols.io counterparts."""

from django.conf import settings
from django.db import models

from ccc.encryption import EncryptedTextField
from ccrv.models import ProtocolModel, ProtocolStep, Session, StepAnnotation

PROTOCOLS_IO_RUN_URL = "https://www.protocols.io/run/"


class ProtocolsIOAccount(models.Model):
    """A user's protocols.io access token and the protocols.io account it belongs to."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="protocols_io_account")
    access_token = EncryptedTextField(help_text="protocols.io access token, stored encrypted")
    username = models.CharField(max_length=255, help_text="protocols.io username the token belongs to")
    name = models.CharField(max_length=255, blank=True, default="", help_text="protocols.io display name")
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        app_label = "protocols_io"
        db_table = "protocols_io_account"
        verbose_name = "protocols.io account"
        verbose_name_plural = "protocols.io accounts"

    def __str__(self):
        return f"{self.user} - {self.username}"


class ProtocolsIOExport(models.Model):
    """A protocols.io protocol that a Cupcake protocol, or its steps as varied in one session, was exported into."""

    protocol = models.ForeignKey(ProtocolModel, on_delete=models.CASCADE, related_name="protocols_io_exports")
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="protocols_io_protocol_copies",
        help_text="Session whose step variations the protocols.io protocol follows",
    )
    variation_hash = models.CharField(
        max_length=64, blank=True, default="", help_text="Hash of the session step variations that were exported"
    )
    exported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="protocols_io_exports"
    )
    protocols_io_id = models.IntegerField(default=0, help_text="Numeric id of the protocols.io protocol")
    protocols_io_guid = models.CharField(max_length=64, help_text="GUID of the protocols.io protocol")
    protocols_io_uri = models.CharField(
        max_length=255, blank=True, default="", help_text="URI of the protocols.io protocol"
    )
    protocols_io_url = models.URLField(max_length=500, blank=True, default="", help_text="Address on protocols.io")
    step_ids = models.JSONField(default=list, help_text="Ids of the exported Cupcake steps in protocols.io step order")
    exported_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "protocols_io"
        db_table = "protocols_io_export"
        ordering = ["-exported_at"]
        verbose_name = "protocols.io export"
        verbose_name_plural = "protocols.io exports"
        constraints = [
            models.UniqueConstraint(fields=["protocol", "protocols_io_guid"], name="unique_protocols_io_export_target")
        ]

    def __str__(self):
        return f"{self.protocol} - {self.protocols_io_uri or self.protocols_io_guid}"

    @classmethod
    def remember(cls, protocol, user, result, *, session=None, variation_hash=""):
        """
        Store where a protocol was exported.

        Args:
            protocol: The exported :class:`ProtocolModel`.
            user: The user who exported it, or ``None``.
            result: The :class:`cupcake_protocols_io.exporter.ExportResult` of the export.
            session: The :class:`Session` whose step variations were exported, or ``None``.
            variation_hash: Hash of those step variations.

        Returns:
            The stored export.
        """
        export, _ = cls.objects.update_or_create(
            protocol=protocol,
            protocols_io_guid=result.protocol_guid,
            defaults={
                "session": session,
                "variation_hash": variation_hash,
                "exported_by": user,
                "protocols_io_id": result.protocol_id,
                "protocols_io_uri": result.protocol_uri,
                "protocols_io_url": result.protocol_url,
                "step_ids": result.step_ids,
            },
        )
        return export


class ProtocolsIORun(models.Model):
    """A protocols.io run that a Cupcake session was exported into."""

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="protocols_io_runs")
    protocol = models.ForeignKey(ProtocolModel, on_delete=models.CASCADE, related_name="protocols_io_runs")
    protocol_export = models.ForeignKey(
        ProtocolsIOExport, on_delete=models.SET_NULL, null=True, blank=True, related_name="runs"
    )
    exported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="protocols_io_runs"
    )
    record_id = models.IntegerField(help_text="Numeric id of the protocols.io run")
    record_guid = models.CharField(max_length=64, unique=True, help_text="GUID of the protocols.io run")
    item_id = models.IntegerField(default=0, help_text="File manager item id of the protocols.io run")
    title = models.CharField(max_length=255, blank=True, default="")
    step_map = models.JSONField(
        default=list,
        help_text="Run steps in order, each with its Cupcake step id and protocols.io run step id and GUID",
    )
    reference_comment_id = models.IntegerField(
        blank=True, null=True, help_text="Discussion id of the run comment that points back to Cupcake"
    )
    variation_hash = models.CharField(
        max_length=64, blank=True, default="", help_text="Hash of the session step variations the run steps follow"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    exported_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "protocols_io"
        db_table = "protocols_io_run"
        ordering = ["-exported_at"]
        verbose_name = "protocols.io run"
        verbose_name_plural = "protocols.io runs"

    def __str__(self):
        return f"{self.session} - {self.record_guid}"

    @property
    def record_url(self):
        """Address of the run on protocols.io."""
        return f"{PROTOCOLS_IO_RUN_URL}{self.record_guid}"


class ProtocolsIORunComment(models.Model):
    """A comment on a protocols.io run that holds one Cupcake step annotation."""

    run = models.ForeignKey(ProtocolsIORun, on_delete=models.CASCADE, related_name="comments")
    step_annotation = models.ForeignKey(
        StepAnnotation, on_delete=models.SET_NULL, null=True, blank=True, related_name="protocols_io_comments"
    )
    step = models.ForeignKey(
        ProtocolStep, on_delete=models.SET_NULL, null=True, blank=True, related_name="protocols_io_comments"
    )
    record_step_id = models.IntegerField(help_text="Id of the protocols.io run step the comment is on")
    discussion_id = models.IntegerField(help_text="Discussion id of the comment on protocols.io")
    content_hash = models.CharField(max_length=64, help_text="Hash of the annotation content that was exported")
    exported_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "protocols_io"
        db_table = "protocols_io_run_comment"
        ordering = ["id"]
        verbose_name = "protocols.io run comment"
        verbose_name_plural = "protocols.io run comments"

    def __str__(self):
        return f"{self.run} - {self.discussion_id}"
