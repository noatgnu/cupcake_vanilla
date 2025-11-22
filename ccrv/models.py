"""
CUPCAKE Red Velvet (CCRV) - Project and Protocol Models.

This module contains project and protocol management models migrated from
the legacy CUPCAKE project, preserving all original functionality while
integrating with the new modular architecture where appropriate.
"""

from datetime import datetime

from django.conf import settings
from django.db import models, transaction

import requests
from bs4 import BeautifulSoup
from simple_history.models import HistoricalRecords

from ccc.models import AbstractResource
from ccm.models import Reagent


class Project(AbstractResource):
    """
    Project management model migrated from legacy CUPCAKE.

    Integrated with AbstractResource for consistent ownership and permissions.
    """

    # Original fields preserved
    project_name = models.CharField(max_length=255)
    project_description = models.TextField(blank=True, null=True)

    # Relationships (preserved from original)
    sessions = models.ManyToManyField("Session", related_name="projects", blank=True)

    # Distributed system fields (preserved from original)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "ccc.RemoteHost", on_delete=models.CASCADE, related_name="projects", blank=True, null=True
    )

    # Vaulting system for imported data (preserved from original)
    is_vaulted = models.BooleanField(default=False, help_text="True if this project is in a user's import vault")

    class Meta:
        app_label = "ccrv"
        ordering = ["-created_at"]  # Updated to use AbstractResource ordering

    def __str__(self):
        return self.project_name

    def __repr__(self):
        return self.project_name


class ProtocolRating(models.Model):
    """
    Protocol rating model migrated from legacy CUPCAKE.

    Preserves original validation and distributed system integration.
    """

    history = HistoricalRecords()

    protocol = models.ForeignKey("ProtocolModel", on_delete=models.CASCADE, related_name="ratings")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="protocol_ratings")

    # Original fields preserved
    complexity_rating = models.IntegerField(blank=False, null=False, default=0)
    duration_rating = models.IntegerField(blank=False, null=False, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Distributed system fields (preserved from original)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "ccc.RemoteHost", on_delete=models.CASCADE, related_name="protocol_ratings", blank=True, null=True
    )

    class Meta:
        app_label = "ccrv"
        ordering = ["id"]  # Preserved from original
        unique_together = ["protocol", "user"]

    def __str__(self):
        return f"{self.protocol} - {self.user} - {self.complexity_rating}"

    def __repr__(self):
        return f"{self.protocol} - {self.user} - {self.complexity_rating}"

    def save(self, *args, **kwargs):
        """Original validation logic preserved."""
        if self.complexity_rating < 0 or self.complexity_rating > 10:
            raise ValueError("Rating must be between 0 and 10")
        if self.duration_rating < 0 or self.duration_rating > 10:
            raise ValueError("Rating must be between 0 and 10")
        super().save(*args, **kwargs)


class ProtocolModel(AbstractResource):
    """
    Protocol documentation model migrated from legacy CUPCAKE.

    Preserves all original functionality including protocols.io integration
    while integrating with AbstractResource.
    """

    # Original fields preserved exactly
    protocol_id = models.BigIntegerField(blank=True, null=True)
    protocol_created_on = models.DateTimeField(blank=False, null=False, auto_now=True)
    protocol_doi = models.TextField(blank=True, null=True)
    protocol_title = models.TextField(blank=False, null=False)
    protocol_url = models.TextField(blank=True, null=True)  # Kept as TextField
    protocol_version_uri = models.TextField(blank=True, null=True)
    protocol_description = models.TextField(blank=True, null=True)

    # Status
    enabled = models.BooleanField(default=False)

    # Collaboration features (preserved from original)
    editors = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="editor_protocols", blank=True)
    viewers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="viewer_protocols", blank=True)

    # Version control (preserved from original)
    model_hash = models.TextField(blank=True, null=True)

    # Distributed system fields (preserved from original)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "ccc.RemoteHost", on_delete=models.CASCADE, related_name="protocols", blank=True, null=True
    )

    # Vaulting system for imported data (preserved from original)
    is_vaulted = models.BooleanField(default=False, help_text="True if this protocol is in a user's import vault")

    class Meta:
        app_label = "ccrv"
        ordering = ["-created_at"]  # Updated to use AbstractResource ordering

    def __str__(self):
        return self.protocol_title

    @staticmethod
    def create_protocol_from_url(url):
        """
        Original protocols.io integration preserved exactly.

        Creates a protocol from a protocols.io URL with full metadata import.
        """
        initial_start = requests.get(url)
        # get url from meta tag using beautifulsoup
        soup = BeautifulSoup(initial_start.content, "html.parser")
        meta = soup.find_all("meta")
        for tag in meta:
            if tag.get("property", None) == "og:url":
                url = tag.get("content", None)
                break
        if not url:
            raise ValueError("Could not find protocol.io url")

        # get protocol.io id from url
        protocol_meta = requests.get(
            f"https://www.protocols.io/api/v3/protocols/{url.split('/')[-1]}",
            headers={"Authorization": f"Bearer {settings.PROTOCOLS_IO_ACCESS_TOKEN}"},
        )

        if protocol_meta.status_code == 200:
            protocol_meta = protocol_meta.json()
            if protocol_meta:
                with transaction.atomic():
                    sections_dict = {}
                    protocol = ProtocolModel()
                    protocol.protocol_id = protocol_meta["protocol"]["id"]
                    # convert unix timestamp to datetime
                    protocol.protocol_created_on = datetime.fromtimestamp(protocol_meta["protocol"]["created_on"])
                    protocol.protocol_doi = protocol_meta["protocol"]["doi"]
                    protocol.protocol_title = protocol_meta["protocol"]["title"]
                    protocol.protocol_description = protocol_meta["protocol"]["description"]
                    protocol.protocol_url = url
                    protocol.protocol_version_uri = protocol_meta["protocol"]["version_uri"]
                    protocol.save()

                    for step in protocol_meta["protocol"]["steps"]:
                        protocol_step = ProtocolStep()
                        for c in step["components"]:
                            if c["title"] == "Section":
                                if c["source"]["title"] not in sections_dict:
                                    section = ProtocolSection()
                                    section.protocol = protocol
                                    section.section_description = c["source"]["title"]
                                    section.section_duration = step["section_duration"]
                                    section.save()
                                    sections_dict[c["source"]["title"]] = section
                                protocol_step.step_section = sections_dict[c["source"]["title"]]

                            elif c["title"] == "description":
                                protocol_step.step_description = c["source"]["description"]
                        protocol_step.protocol = protocol
                        protocol_step.step_id = step["id"]
                        protocol_step.step_duration = step["duration"]
                        protocol_step.save()

                with transaction.atomic():
                    for step in protocol_meta["protocol"]["steps"]:
                        protocol_step = protocol.steps.get(step_id=step["id"])
                        if step["previous_id"] != 0:
                            protocol_step.previous_step = protocol.steps.get(step_id=step["previous_id"])
                        protocol_step.save()
                return protocol
        else:
            raise ValueError(f"Could not find protocol.io protocol with url {url}")

        raise ValueError("Failed to import protocol from protocols.io")

    def get_session_annotations(self, session):
        """
        Get all step annotations for this protocol within a session context.

        Args:
            session: Session instance

        Returns:
            dict: Mapping of step_id to list of StepAnnotation objects
        """
        from ccrv.models import StepAnnotation

        step_annotations = {}
        protocol_steps = ProtocolStep.objects.filter(step_section__protocol=self).prefetch_related(
            "step_annotations__annotation__owner"
        )

        for step in protocol_steps:
            annotations = (
                StepAnnotation.objects.filter(session=session, step=step)
                .select_related("annotation", "annotation__owner")
                .order_by("order")
            )

            if annotations.exists():
                step_annotations[step.id] = list(annotations)

        return step_annotations

    def gather_session_files(self, session):
        """
        Gather all annotation file paths for this protocol in a session.

        Args:
            session: Session instance

        Returns:
            list: List of (annotation, file_path) tuples
        """
        files = []
        step_annotations = self.get_session_annotations(session)

        for step_id, annotations in step_annotations.items():
            for step_ann in annotations:
                if step_ann.annotation.file:
                    files.append((step_ann.annotation, step_ann.annotation.file.path))

        return files

    def generate_html(self):
        """
        Generate HTML representation of this protocol without session context.

        Returns:
            str: HTML content for this protocol structure only
        """
        from django.utils.html import escape

        sections_html = []

        for section in self.sections.all().order_by("order"):
            steps_html = []

            for step in section.get_steps_by_order():
                reagents_html = ""
                if step.reagents.exists():
                    reagent_items = []
                    for sr in step.reagents.all():
                        unit = sr.unit or sr.reagent.unit or ""
                        quantity_part = f" - {sr.quantity} {unit}" if sr.quantity else ""
                        scalable_part = " (scalable)" if sr.scalable else ""
                        reagent_items.append(f"<li>{sr.reagent.name}{quantity_part}{scalable_part}</li>")
                    reagents_list = "".join(reagent_items)
                    reagents_html = f"""
                    <div class="step-reagents">
                        <h4>Required Reagents</h4>
                        <ul class="reagent-list">{reagents_list}</ul>
                    </div>
                    """

                import re

                step_desc = step.step_description or ""

                step_reagents = step.reagents.all().select_related("reagent")
                for step_reagent in step_reagents:
                    reagent = step_reagent.reagent
                    reagent_id = step_reagent.id

                    base_quantity = step_reagent.quantity or 0
                    scaled_quantity = (
                        step_reagent.scaled_quantity
                        if hasattr(step_reagent, "scaled_quantity") and step_reagent.scaled_quantity is not None
                        else base_quantity
                    )

                    reagent_name_escaped = escape(reagent.name)
                    unit_value = escape(step_reagent.unit or reagent.unit or "")

                    step_desc = re.sub(rf"%{reagent_id}\.quantity%", f"{{{{REAGENT_QTY_{reagent_id}}}}}", step_desc)
                    step_desc = re.sub(
                        rf"%{reagent_id}\.scaled_quantity%", f"{{{{REAGENT_SCALED_{reagent_id}}}}}", step_desc
                    )
                    step_desc = re.sub(rf"%{reagent_id}\.name%", f"{{{{REAGENT_NAME_{reagent_id}}}}}", step_desc)
                    step_desc = re.sub(rf"%{reagent_id}\.unit%", f"{{{{REAGENT_UNIT_{reagent_id}}}}}", step_desc)

                step_desc = escape(step_desc)

                for step_reagent in step_reagents:
                    reagent = step_reagent.reagent
                    reagent_id = step_reagent.id

                    base_quantity = step_reagent.quantity or 0
                    scaled_quantity = (
                        step_reagent.scaled_quantity
                        if hasattr(step_reagent, "scaled_quantity") and step_reagent.scaled_quantity is not None
                        else base_quantity
                    )

                    reagent_name_escaped = escape(reagent.name)
                    unit_value = escape(step_reagent.unit or reagent.unit or "")

                    step_desc = step_desc.replace(
                        f"{{{{REAGENT_QTY_{reagent_id}}}}}",
                        f'<span class="template-value" title="Reagent quantity: {reagent_name_escaped}">{base_quantity}</span>',
                    )
                    step_desc = step_desc.replace(
                        f"{{{{REAGENT_SCALED_{reagent_id}}}}}",
                        f'<span class="template-value template-value-scaled" title="Scaled quantity: {reagent_name_escaped}">{scaled_quantity}</span>',
                    )
                    step_desc = step_desc.replace(
                        f"{{{{REAGENT_NAME_{reagent_id}}}}}",
                        f'<span class="template-value template-value-name" title="Reagent name">{reagent_name_escaped or "Unknown"}</span>',
                    )
                    step_desc = step_desc.replace(
                        f"{{{{REAGENT_UNIT_{reagent_id}}}}}",
                        f'<span class="template-value template-value-unit" title="Reagent unit: {reagent_name_escaped}">{unit_value}</span>',
                    )

                step_desc = step_desc.replace("\n", "<br>")

                duration_html = ""
                if step.step_duration:
                    hours = step.step_duration // 3600
                    minutes = (step.step_duration % 3600) // 60
                    seconds = step.step_duration % 60

                    duration_parts = []
                    if hours > 0:
                        duration_parts.append(f"{hours}h")
                    if minutes > 0:
                        duration_parts.append(f"{minutes}m")
                    if seconds > 0 or not duration_parts:
                        duration_parts.append(f"{seconds}s")

                    duration_display = " ".join(duration_parts)
                    duration_html = f'<span class="step-duration">{duration_display}</span>'

                steps_html.append(
                    f"""
                <div class="step">
                    <div class="step-header">
                        <span class="step-number">{step.order}</span>
                        <span class="step-title">Step {step.order}</span>
                        {duration_html}
                    </div>
                    <div class="step-description">{step_desc}</div>
                    {reagents_html}
                </div>
                """
                )

            section_desc = escape(section.section_description)
            section_desc = section_desc.replace("\n", "<br>")

            section_duration_html = ""
            if section.section_duration:
                hours = section.section_duration // 3600
                minutes = (section.section_duration % 3600) // 60
                seconds = section.section_duration % 60

                duration_parts = []
                if hours > 0:
                    duration_parts.append(f"{hours}h")
                if minutes > 0:
                    duration_parts.append(f"{minutes}m")
                if seconds > 0 or not duration_parts:
                    duration_parts.append(f"{seconds}s")

                duration_display = " ".join(duration_parts)
                section_duration_html = (
                    f'<span style="font-size: 0.9em; color: #7f8c8d; margin-left: 10px;">({duration_display})</span>'
                )

            sections_html.append(
                f"""
            <div class="section">
                <div class="section-header">
                    {section_desc}
                    {section_duration_html}
                </div>
                {''.join(steps_html)}
            </div>
            """
            )

        protocol_desc = escape(self.protocol_description) if self.protocol_description else ""
        protocol_desc = protocol_desc.replace("\n", "<br>") if protocol_desc else ""
        protocol_title = escape(self.protocol_title)
        protocol_doi = escape(self.protocol_doi) if self.protocol_doi else ""
        protocol_url = escape(self.protocol_url) if self.protocol_url else ""

        return f"""
        <div class="protocol">
            <div class="protocol-header">
                <h2>{protocol_title}</h2>
                {f'<div class="protocol-description">{protocol_desc}</div>' if protocol_desc else ''}
                <div class="protocol-meta">
                    {f'<span><strong>DOI:</strong> {protocol_doi}</span>' if protocol_doi else ''}
                    {f'<span><strong>URL:</strong> {protocol_url}</span>' if protocol_url else ''}
                </div>
            </div>
            {''.join(sections_html)}
        </div>
        """

    def generate_html_for_session(self, session):
        """
        Generate HTML representation of this protocol for a specific session.

        Args:
            session: Session instance

        Returns:
            str: HTML content for this protocol with session-specific annotations
        """
        step_annotations = self.get_session_annotations(session)

        sections_html = []

        for section in self.sections.all().order_by("order"):
            steps_html = []

            for step in section.get_steps_by_order():
                reagents_html = ""
                if step.reagents.exists():
                    reagents_list = "".join(
                        [
                            f"<li>{sr.reagent.name}"
                            f"{f' - {sr.quantity}' if sr.quantity else ''}"
                            f"{' (scalable)' if sr.scalable else ''}</li>"
                            for sr in step.reagents.all()
                        ]
                    )
                    reagents_html = f"""
                    <div class="step-reagents">
                        <h4>Required Reagents</h4>
                        <ul class="reagent-list">{reagents_list}</ul>
                    </div>
                    """

                annotations_html = ""
                if step.id in step_annotations:
                    annotations_items = []
                    for step_ann in step_annotations[step.id]:
                        from ccrv.export_utils import _process_annotation_file

                        annotation = step_ann.annotation
                        file_html = _process_annotation_file(annotation) or ""

                        from django.utils.html import escape

                        transcription_html = ""
                        if annotation.transcription:
                            trans_text = escape(annotation.transcription).replace("\n", "<br>")
                            transcription_html = f"""
                            <div class="transcription">
                                <h5>Transcription:</h5>
                                {trans_text}
                            </div>
                            """

                        ann_text = escape(annotation.annotation) if annotation.annotation else ""
                        ann_text = ann_text.replace("\n", "<br>") if ann_text else ""
                        annotations_items.append(
                            f"""
                        <div class="annotation">
                            <div class="annotation-meta">
                                <strong>{annotation.owner.get_full_name() or annotation.owner.username}</strong>
                                - {annotation.created_at.strftime('%B %d, %Y, %I:%M %p')}
                                {f'<span class="badge badge-{annotation.annotation_type}">{annotation.annotation_type}</span>' if annotation.annotation_type else ''}
                            </div>
                            {f'<div class="annotation-text">{ann_text}</div>' if ann_text else ''}
                            {f'<div class="annotation-file">{file_html}</div>' if file_html else ''}
                            {transcription_html}
                        </div>
                        """
                        )

                    annotations_html = f"""
                    <div class="step-annotations">
                        <h4>Annotations</h4>
                        {''.join(annotations_items)}
                    </div>
                    """

                import re

                step_desc = step.step_description or ""

                step_reagents = step.reagents.all().select_related("reagent")
                for step_reagent in step_reagents:
                    reagent = step_reagent.reagent
                    reagent_id = step_reagent.id

                    base_quantity = step_reagent.quantity or 0
                    scaled_quantity = (
                        step_reagent.scaled_quantity
                        if hasattr(step_reagent, "scaled_quantity") and step_reagent.scaled_quantity is not None
                        else base_quantity
                    )

                    reagent_name_escaped = escape(reagent.name)
                    unit_value = escape(step_reagent.unit or reagent.unit or "")

                    step_desc = re.sub(rf"%{reagent_id}\.quantity%", f"{{{{REAGENT_QTY_{reagent_id}}}}}", step_desc)
                    step_desc = re.sub(
                        rf"%{reagent_id}\.scaled_quantity%", f"{{{{REAGENT_SCALED_{reagent_id}}}}}", step_desc
                    )
                    step_desc = re.sub(rf"%{reagent_id}\.name%", f"{{{{REAGENT_NAME_{reagent_id}}}}}", step_desc)
                    step_desc = re.sub(rf"%{reagent_id}\.unit%", f"{{{{REAGENT_UNIT_{reagent_id}}}}}", step_desc)

                step_desc = escape(step_desc)

                for step_reagent in step_reagents:
                    reagent = step_reagent.reagent
                    reagent_id = step_reagent.id

                    base_quantity = step_reagent.quantity or 0
                    scaled_quantity = (
                        step_reagent.scaled_quantity
                        if hasattr(step_reagent, "scaled_quantity") and step_reagent.scaled_quantity is not None
                        else base_quantity
                    )

                    reagent_name_escaped = escape(reagent.name)
                    unit_value = escape(step_reagent.unit or reagent.unit or "")

                    step_desc = step_desc.replace(
                        f"{{{{REAGENT_QTY_{reagent_id}}}}}",
                        f'<span class="template-value" title="Reagent quantity: {reagent_name_escaped}">{base_quantity}</span>',
                    )
                    step_desc = step_desc.replace(
                        f"{{{{REAGENT_SCALED_{reagent_id}}}}}",
                        f'<span class="template-value template-value-scaled" title="Scaled quantity: {reagent_name_escaped}">{scaled_quantity}</span>',
                    )
                    step_desc = step_desc.replace(
                        f"{{{{REAGENT_NAME_{reagent_id}}}}}",
                        f'<span class="template-value template-value-name" title="Reagent name">{reagent_name_escaped or "Unknown"}</span>',
                    )
                    step_desc = step_desc.replace(
                        f"{{{{REAGENT_UNIT_{reagent_id}}}}}",
                        f'<span class="template-value template-value-unit" title="Reagent unit: {reagent_name_escaped}">{unit_value}</span>',
                    )

                step_desc = step_desc.replace("\n", "<br>")

                duration_html = ""
                if step.step_duration:
                    hours = step.step_duration // 3600
                    minutes = (step.step_duration % 3600) // 60
                    seconds = step.step_duration % 60

                    duration_parts = []
                    if hours > 0:
                        duration_parts.append(f"{hours}h")
                    if minutes > 0:
                        duration_parts.append(f"{minutes}m")
                    if seconds > 0 or not duration_parts:
                        duration_parts.append(f"{seconds}s")

                    duration_display = " ".join(duration_parts)
                    duration_html = f'<span class="step-duration">{duration_display}</span>'

                steps_html.append(
                    f"""
                <div class="step">
                    <div class="step-header">
                        <span class="step-number">{step.order}</span>
                        <span class="step-title">Step {step.order}</span>
                        {duration_html}
                    </div>
                    <div class="step-description">{step_desc}</div>
                    {reagents_html}
                    {annotations_html}
                </div>
                """
                )

            section_desc = escape(section.section_description)
            section_desc = section_desc.replace("\n", "<br>")

            section_duration_html = ""
            if section.section_duration:
                hours = section.section_duration // 3600
                minutes = (section.section_duration % 3600) // 60
                seconds = section.section_duration % 60

                duration_parts = []
                if hours > 0:
                    duration_parts.append(f"{hours}h")
                if minutes > 0:
                    duration_parts.append(f"{minutes}m")
                if seconds > 0 or not duration_parts:
                    duration_parts.append(f"{seconds}s")

                duration_display = " ".join(duration_parts)
                section_duration_html = (
                    f'<span style="font-size: 0.9em; color: #7f8c8d; margin-left: 10px;">({duration_display})</span>'
                )

            sections_html.append(
                f"""
            <div class="section">
                <div class="section-header">
                    {section_desc}
                    {section_duration_html}
                </div>
                {''.join(steps_html)}
            </div>
            """
            )

        from django.utils.html import escape

        protocol_desc = escape(self.protocol_description) if self.protocol_description else ""
        protocol_desc = protocol_desc.replace("\n", "<br>") if protocol_desc else ""
        protocol_title = escape(self.protocol_title)
        protocol_doi = escape(self.protocol_doi) if self.protocol_doi else ""
        protocol_url = escape(self.protocol_url) if self.protocol_url else ""

        return f"""
        <div class="protocol">
            <div class="protocol-header">
                <h2>{protocol_title}</h2>
                {f'<div class="protocol-description">{protocol_desc}</div>' if protocol_desc else ''}
                <div class="protocol-meta">
                    {f'<span><strong>DOI:</strong> {protocol_doi}</span>' if protocol_doi else ''}
                    {f'<span><strong>URL:</strong> {protocol_url}</span>' if protocol_url else ''}
                </div>
            </div>
            {''.join(sections_html)}
        </div>
        """

    def export_html(self, session=None):
        """
        Export protocol as complete HTML document.

        Args:
            session: Optional Session instance. If provided, includes session-specific annotations.

        Returns:
            str: Complete HTML document
        """
        from datetime import datetime

        from django.utils.html import escape

        from ccrv.export_utils import get_html_template

        if session:
            protocol_html = self.generate_html_for_session(session)
            session_name = escape(session.name)
            owner_name = escape(session.owner.get_full_name() or session.owner.username)
            started_at_html = (
                f'<div class="meta-info-item"><strong>Started:</strong> {session.started_at.strftime("%B %d, %Y, %I:%M %p")}</div>'
                if session.started_at
                else ""
            )
            ended_at_html = (
                f'<div class="meta-info-item"><strong>Ended:</strong> {session.ended_at.strftime("%B %d, %Y, %I:%M %p")}</div>'
                if session.ended_at
                else ""
            )
            session_annotations_section = ""
        else:
            protocol_html = self.generate_html()
            session_name = escape(self.protocol_title)
            owner_name = escape(self.owner.get_full_name() or self.owner.username) if self.owner else "Unknown"
            started_at_html = ""
            ended_at_html = ""
            session_annotations_section = ""

        export_date = datetime.now().strftime("%B %d, %Y, %I:%M %p")

        template = get_html_template()

        html_content = template.format(
            session_name=session_name,
            owner_name=owner_name,
            started_at_html=started_at_html,
            ended_at_html=ended_at_html,
            export_date=export_date,
            session_annotations_section=session_annotations_section,
            protocols_html=protocol_html,
        )

        return html_content

    def generate_export_token(self, user, session_id=None):
        """
        Generate a signed export token for this protocol.

        Args:
            user: The user requesting the export
            session_id: Optional session ID for session-specific export

        Returns:
            str: Signed token containing protocol ID, user ID, and optional session ID
        """
        from django.core.signing import TimestampSigner

        signer = TimestampSigner()
        if session_id:
            payload = f"protocol:{self.id}:{user.id}:{session_id}"
        else:
            payload = f"protocol:{self.id}:{user.id}"
        return signer.sign(payload)

    @classmethod
    def verify_export_token(cls, signed_token):
        """
        Verify a signed export token and return the Protocol and session if valid.

        Returns:
            tuple: (protocol, user, session_id or None) or (None, None, None) if invalid
        """
        from django.conf import settings
        from django.contrib.auth import get_user_model
        from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

        User = get_user_model()
        signer = TimestampSigner()

        try:
            max_age = getattr(settings, "EXPORT_TOKEN_MAX_AGE", 600)
            payload = signer.unsign(signed_token, max_age=max_age)

            parts = payload.split(":")
            if parts[0] != "protocol":
                return None, None, None

            if len(parts) == 3:
                _, protocol_id, user_id = parts
                session_id = None
            elif len(parts) == 4:
                _, protocol_id, user_id, session_id = parts
            else:
                return None, None, None

            user = User.objects.get(id=user_id)
            protocol = cls.objects.get(id=protocol_id)

            return protocol, user, session_id

        except (BadSignature, SignatureExpired, ValueError, User.DoesNotExist, cls.DoesNotExist):
            return None, None, None


class Session(AbstractResource):
    """
    Experimental session model migrated from legacy CUPCAKE.

    Preserves all original functionality including import tracking
    while integrating with AbstractResource.
    """

    # Original fields preserved
    unique_id = models.UUIDField(blank=False, null=False, unique=True, db_index=True)
    enabled = models.BooleanField(default=False)
    protocols = models.ManyToManyField(ProtocolModel, related_name="sessions", blank=True)
    name = models.TextField(blank=True, null=True)

    # Collaboration features (preserved from original)
    editors = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="editor_sessions", blank=True)
    viewers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="viewer_sessions", blank=True)

    # Time tracking (preserved from original)
    started_at = models.DateTimeField(blank=True, null=True)
    ended_at = models.DateTimeField(blank=True, null=True)
    processing = models.BooleanField(default=False)

    # Distributed system fields (preserved from original)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "ccc.RemoteHost", on_delete=models.CASCADE, related_name="sessions", blank=True, null=True
    )

    # WebRTC collaboration
    webrtc_sessions = models.ManyToManyField("ccmc.WebRTCSession", related_name="ccrv_sessions", blank=True)

    class Meta:
        app_label = "ccrv"
        ordering = ["-created_at"]  # Updated to use AbstractResource ordering

    def can_view(self, user):
        """
        Check if user can view this session.
        Override AbstractResource to handle editors/viewers fields.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always view
        if user.is_staff or user.is_superuser:
            return True

        # Owner can always view
        if self.owner == user:
            return True

        # Check editors and viewers
        if user in self.editors.all() or user in self.viewers.all():
            return True

        # Check visibility settings (delegate to parent)
        return super().can_view(user)

    def can_edit(self, user):
        """
        Check if user can edit this session.
        Override AbstractResource to handle editors field.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always edit
        if user.is_staff or user.is_superuser:
            return True

        # Owner can always edit
        if self.owner == user:
            return True

        # Check editors (viewers cannot edit)
        if user in self.editors.all():
            return True

        # Check other AbstractResource permissions (lab groups, etc.)
        return super().can_edit(user)

    def can_delete(self, user):
        """
        Check if user can delete this session.
        Override AbstractResource to handle editors field.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always delete
        if user.is_staff or user.is_superuser:
            return True

        # Owner can always delete
        if self.owner == user:
            return True

        # Check editors (viewers cannot delete)
        if user in self.editors.all():
            return True

        # Check other AbstractResource permissions
        return super().can_delete(user)

    def __str__(self):
        return self.name or f"Session {self.unique_id}"

    @property
    def is_imported(self):
        """Check if this session was imported from another system."""
        return self.name and "[IMPORTED]" in self.name

    @property
    def import_source_info(self):
        """Get information about the import source."""
        try:
            # This would reference ImportedObject from the original system
            # Implementation preserved but may need adjustment for new architecture
            from ccc.models import ImportedObject  # Assuming this exists

            imported_obj = ImportedObject.objects.filter(model_name="Session", object_id=self.pk).first()
            if imported_obj:
                return {
                    "import_tracker": imported_obj.import_tracker,
                    "original_id": imported_obj.original_id,
                    "imported_at": imported_obj.created_at,
                }
        except Exception:
            pass
        return None

    def sync_session_upstream(self, upstream_node_url: str):
        """
        Sync session with upstream node.

        Original method signature preserved - implementation would need
        to be completed based on original requirements.
        """
        # Original implementation would go here
        pass

    def get_session_annotations(self):
        """
        Get all session-level annotations.

        Returns:
            QuerySet: SessionAnnotation objects for this session
        """
        from ccrv.models import SessionAnnotation

        return (
            SessionAnnotation.objects.filter(session=self)
            .select_related("annotation", "annotation__owner")
            .order_by("order")
        )

    def gather_all_files(self):
        """
        Gather all annotation files from session and protocol annotations.

        Returns:
            list: List of (annotation, file_path) tuples
        """
        files = []

        for sa in self.get_session_annotations():
            if sa.annotation.file:
                files.append((sa.annotation, sa.annotation.file.path))

        for protocol in self.protocols.all():
            files.extend(protocol.gather_session_files(self))

        return files

    def export_protocols_html(self):
        """
        Export all protocols with annotations as HTML.

        Returns:
            str: Complete HTML document with all protocols and annotations
        """
        from datetime import datetime

        from django.utils.html import escape

        from ccrv.export_utils import get_html_template

        session_annotations_html = []
        for sa in self.get_session_annotations():
            from ccrv.export_utils import _process_annotation_file

            annotation = sa.annotation
            file_html = _process_annotation_file(annotation) or ""

            transcription_html = ""
            if annotation.transcription:
                trans_text = escape(annotation.transcription).replace("\n", "<br>")
                transcription_html = f"""
                <div class="transcription">
                    <h5>Transcription:</h5>
                    {trans_text}
                </div>
                """

            ann_text = escape(annotation.annotation) if annotation.annotation else ""
            ann_text = ann_text.replace("\n", "<br>") if ann_text else ""
            session_annotations_html.append(
                f"""
            <div class="annotation">
                <div class="annotation-meta">
                    <strong>{escape(annotation.owner.get_full_name() or annotation.owner.username)}</strong>
                    - {annotation.created_at.strftime('%B %d, %Y, %I:%M %p')}
                    {f'<span class="badge badge-{escape(annotation.annotation_type)}">{escape(annotation.annotation_type)}</span>' if annotation.annotation_type else ''}
                </div>
                {f'<div class="annotation-text">{ann_text}</div>' if ann_text else ''}
                {f'<div class="annotation-file">{file_html}</div>' if file_html else ''}
                {transcription_html}
            </div>
            """
            )

        session_annotations_section = ""
        if session_annotations_html:
            session_annotations_section = f"""
        <div class="session-annotations">
            <h2>Session Annotations</h2>
            {''.join(session_annotations_html)}
        </div>
            """

        protocols_html = []
        for protocol in self.protocols.all():
            protocols_html.append(protocol.generate_html_for_session(self))

        session_name = escape(self.name)
        owner_name = escape(self.owner.get_full_name() or self.owner.username)

        started_at_html = (
            f'<div class="meta-info-item"><strong>Started:</strong> {self.started_at.strftime("%B %d, %Y, %I:%M %p")}</div>'
            if self.started_at
            else ""
        )
        ended_at_html = (
            f'<div class="meta-info-item"><strong>Ended:</strong> {self.ended_at.strftime("%B %d, %Y, %I:%M %p")}</div>'
            if self.ended_at
            else ""
        )

        export_date = datetime.now().strftime("%B %d, %Y, %I:%M %p")

        template = get_html_template()

        html_content = template.format(
            session_name=session_name,
            owner_name=owner_name,
            started_at_html=started_at_html,
            ended_at_html=ended_at_html,
            export_date=export_date,
            session_annotations_section=session_annotations_section,
            protocols_html="".join(protocols_html),
        )

        return html_content

    def generate_export_token(self, user):
        """
        Generate a signed export token for this session.

        Args:
            user: The user requesting the export

        Returns:
            str: Signed token containing session ID and user ID
        """
        from django.core.signing import TimestampSigner

        signer = TimestampSigner()
        payload = f"session:{self.id}:{user.id}"
        return signer.sign(payload)

    @classmethod
    def verify_export_token(cls, signed_token):
        """
        Verify a signed export token and return the Session if valid.

        Returns:
            tuple: (session, user) or (None, None) if invalid
        """
        from django.conf import settings
        from django.contrib.auth import get_user_model
        from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

        User = get_user_model()
        signer = TimestampSigner()

        try:
            max_age = getattr(settings, "EXPORT_TOKEN_MAX_AGE", 600)
            payload = signer.unsign(signed_token, max_age=max_age)

            parts = payload.split(":")
            if parts[0] != "session" or len(parts) != 3:
                return None, None

            _, session_id, user_id = parts

            user = User.objects.get(id=user_id)
            session = cls.objects.get(id=session_id)

            return session, user

        except (BadSignature, SignatureExpired, ValueError, User.DoesNotExist, cls.DoesNotExist):
            return None, None


class ProtocolSection(models.Model):
    """
    Protocol sections model migrated from legacy CUPCAKE.

    Preserves original linked-list navigation and distributed system integration.
    """

    history = HistoricalRecords()

    protocol = models.ForeignKey(ProtocolModel, on_delete=models.CASCADE, related_name="sections")

    # Original fields preserved exactly
    section_description = models.TextField(blank=True, null=True)
    section_duration = models.IntegerField(blank=True, null=True)

    # Efficient ordering attribute (new addition for performance)
    order = models.PositiveIntegerField(default=0, help_text="Position of section in protocol for efficient ordering")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Distributed system fields (preserved from original)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "ccc.RemoteHost", on_delete=models.CASCADE, related_name="protocol_sections", blank=True, null=True
    )

    class Meta:
        app_label = "ccrv"
        ordering = ["order", "id"]  # Efficient ordering by position, fallback to id

    def __str__(self):
        return self.section_description or f"Section {self.id}"

    def __repr__(self):
        return self.section_description or f"Section {self.id}"

    def get_first_in_section(self):
        """Get the first step in this section (original logic preserved)."""
        step_list = self.steps.all()
        if step_list:
            for i in step_list:
                if not i.previous_step:
                    return i
                else:
                    if i.previous_step not in step_list:
                        return i

    def get_last_in_section(self):
        """Get the last step in this section (original logic preserved)."""
        step_list = self.steps.all()
        if step_list:
            for i in step_list:
                if not i.next_step.exists():
                    return i
                else:
                    counter = 0
                    for s in i.next_step.all():
                        if s not in step_list:
                            counter += 1
                    if counter == len(i.next_step.all()):
                        return i

    def get_step_in_order(self):
        """Get steps in order using linked-list traversal (original logic)."""
        first_step = self.get_first_in_section()
        if not first_step:
            return []

        steps_in_section = self.steps.all()
        step_list = [first_step]
        current_step = first_step

        while current_step.next_step.exists():
            next_steps = current_step.next_step.filter(id__in=steps_in_section)
            if next_steps.exists():
                current_step = next_steps.first()
                step_list.append(current_step)
            else:
                break

        return step_list

    def get_steps_by_order(self):
        """Get steps efficiently ordered by order attribute (new efficient method)."""
        return self.steps.all().order_by("order", "id")

    def reorder_steps(self):
        """Reorder steps based on their order attribute values."""
        steps = self.get_steps_by_order()
        for index, step in enumerate(steps, 1):
            if step.order != index:
                step.order = index
                step.save(update_fields=["order"])

    def move_to_order(self, new_order):
        """
        Efficiently move this section to a specific order position within the protocol.

        Updates order values of other sections to maintain sequential ordering.
        """
        other_sections = ProtocolSection.objects.filter(protocol=self.protocol).exclude(id=self.id)

        # Shift other sections to make room
        other_sections.filter(order__gte=new_order).update(order=models.F("order") + 1)

        # Update this section's order
        self.order = new_order
        self.save(update_fields=["order"])

    @classmethod
    def reorder_by_protocol(cls, protocol):
        """
        Reorder all sections in a protocol based on their current order values.

        Ensures sequential ordering starting from 0.
        """
        sections = cls.objects.filter(protocol=protocol).order_by("order", "id")
        for index, section in enumerate(sections):
            if section.order != index:
                section.order = index
                section.save(update_fields=["order"])


class ProtocolStep(models.Model):
    """
    Protocol steps model migrated from legacy CUPCAKE.

    Preserves original linked-list ordering system and complex move operations.
    """

    history = HistoricalRecords()

    protocol = models.ForeignKey(ProtocolModel, on_delete=models.CASCADE, related_name="steps")

    # Original fields preserved exactly
    step_id = models.BigIntegerField(blank=True, null=True)
    step_description = models.TextField(blank=False, null=False)
    step_section = models.ForeignKey(
        ProtocolSection, on_delete=models.CASCADE, related_name="steps", blank=True, null=True
    )
    step_duration = models.IntegerField(blank=True, null=True)

    # Efficient ordering attribute (new addition for performance)
    order = models.PositiveIntegerField(
        default=0, help_text="Position of step in section/protocol for efficient ordering"
    )

    # Linked-list navigation (preserved from original)
    previous_step = models.ForeignKey("self", on_delete=models.CASCADE, related_name="next_step", blank=True, null=True)

    # Branching support (preserved from original)
    original = models.BooleanField(default=True)
    branch_from = models.ForeignKey(
        "self", on_delete=models.CASCADE, related_name="branch_steps", blank=True, null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Distributed system fields (preserved from original)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "ccc.RemoteHost", on_delete=models.CASCADE, related_name="protocol_steps", blank=True, null=True
    )

    class Meta:
        app_label = "ccrv"
        ordering = ["order", "id"]  # Efficient ordering by position, fallback to id

    def __str__(self):
        return self.step_description

    def __repr__(self):
        return self.step_description

    def delete(self, using=None, keep_parents=False):
        """Original delete logic preserved - updates linked list on deletion."""
        with transaction.atomic():
            if self.next_step.exists():
                next_steps = self.next_step.all()
                previous_step = self.previous_step
                for i in next_steps:
                    if self.previous_step:
                        i.previous_step = previous_step
                        i.save()
                self.next_step.clear()
        super(ProtocolStep, self).delete(using=using, keep_parents=keep_parents)

    def move_up(self):
        """
        Original move_up logic preserved.

        Complex linked-list manipulation within sections.
        """
        if self.previous_step:
            previous_step = self.previous_step
            next_steps = list(self.next_step.all())
            if self.step_section == previous_step.step_section:
                self.next_step.clear()
                if previous_step.previous_step:
                    previous_previous_step = previous_step.previous_step
                    self.previous_step = previous_previous_step
                    self.save()
                    previous_step.previous_step = self
                    previous_step.save()
                    for i in next_steps:
                        i.previous_step = previous_step
                        i.save()
                else:
                    previous_step.previous_step = self
                    previous_step.save()
                    self.previous_step = None
                    self.save()
                    for i in next_steps:
                        i.previous_step = previous_step
                        i.save()

    def move_down(self):
        """
        Original move_down logic preserved.

        Complex linked-list manipulation within sections.
        """
        if self.next_step.exists():
            next_steps = list(self.next_step.all())
            if next_steps:
                next_step = next_steps[0]
                if self.step_section == next_step.step_section:
                    self.next_step.remove(next_step)
                    self.save()
                    if next_step.next_step.exists():
                        next_next_steps = next_step.next_step.all()
                        for i in next_next_steps:
                            i.previous_step = self
                            i.save()
                    next_step.next_step.add(self)
                    self.previous_step = next_step
                    self.save()

    def move_to_order(self, new_order):
        """
        Efficiently move this step to a specific order position.

        Updates order values of other steps in the same context to maintain sequential ordering.
        This is much more efficient than the original linked-list traversal methods.
        """
        if self.step_section:
            # Move within section
            context_steps = ProtocolStep.objects.filter(step_section=self.step_section).exclude(id=self.id)
        else:
            # Move within protocol (steps without sections)
            context_steps = ProtocolStep.objects.filter(protocol=self.protocol, step_section__isnull=True).exclude(
                id=self.id
            )

        # Shift other steps to make room
        context_steps.filter(order__gte=new_order).update(order=models.F("order") + 1)

        # Update this step's order
        self.order = new_order
        self.save(update_fields=["order"])

    @classmethod
    def reorder_by_linked_list(cls):
        """
        Migrate existing data by setting order attributes based on linked-list traversal.

        This method should be run once to populate order fields for existing data,
        then the efficient order-based methods can be used going forward.
        """
        protocols = ProtocolModel.objects.all()

        for protocol in protocols:
            # Handle steps without sections first
            root_steps = cls.objects.filter(protocol=protocol, step_section__isnull=True, previous_step__isnull=True)

            order = 0
            for root_step in root_steps:
                order = cls._traverse_and_order(root_step, order)

            # Handle sections
            sections = protocol.sections.all().order_by("id")
            for section in sections:
                section_root_steps = cls.objects.filter(step_section=section, previous_step__isnull=True)

                section_order = 0
                for root_step in section_root_steps:
                    section_order = cls._traverse_and_order(root_step, section_order, section_context=True)

    @classmethod
    def _traverse_and_order(cls, step, start_order, section_context=False):
        """
        Helper method to recursively traverse linked list and assign order values.
        """
        current_order = start_order
        current_step = step

        while current_step:
            current_step.order = current_order
            current_step.save(update_fields=["order"])
            current_order += 1

            # Move to next step in the linked list
            next_steps = current_step.next_step.all()
            current_step = next_steps.first() if next_steps.exists() else None

        return current_order


class ProtocolReagent(models.Model):
    """
    Link between protocols and reagents with quantities.
    """

    history = HistoricalRecords()
    protocol = models.ForeignKey(ProtocolModel, on_delete=models.CASCADE, related_name="protocol_reagents")
    reagent = models.ForeignKey(Reagent, on_delete=models.CASCADE)
    quantity = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)

    class Meta:
        app_label = "ccrv"
        ordering = ["id"]

    def __str__(self):
        return f"{self.protocol.protocol_title} - {self.reagent.name} ({self.quantity})"

    def __repr__(self):
        return f"ProtocolReagent({self.protocol.protocol_title}, {self.reagent.name}, {self.quantity})"


class StepReagent(models.Model):
    """
    Link between protocol steps and reagents with quantities and scaling factors.
    """

    history = HistoricalRecords()
    step = models.ForeignKey(ProtocolStep, on_delete=models.CASCADE, related_name="reagents")
    reagent = models.ForeignKey(Reagent, on_delete=models.CASCADE)
    quantity = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    scalable = models.BooleanField(default=False)
    scalable_factor = models.FloatField(default=1.0)
    remote_id = models.BigIntegerField(blank=True, null=True)

    class Meta:
        app_label = "ccrv"
        ordering = ["id"]

    def __str__(self):
        return f"{self.step.step_description[:50]}... - {self.reagent.name} ({self.quantity})"

    def __repr__(self):
        return f"StepReagent({self.step.id}, {self.reagent.name}, {self.quantity})"


class StepVariation(models.Model):
    """
    Alternative variations of protocol steps with different descriptions and durations.
    """

    history = HistoricalRecords()
    step = models.ForeignKey(ProtocolStep, on_delete=models.CASCADE, related_name="variations")
    variation_description = models.TextField(blank=False, null=False)
    variation_duration = models.IntegerField(blank=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "ccc.RemoteHost", on_delete=models.CASCADE, related_name="step_variations", blank=True, null=True
    )

    class Meta:
        app_label = "ccrv"
        ordering = ["id"]

    def __str__(self):
        return self.variation_description

    def __repr__(self):
        return self.variation_description


class TimeKeeper(models.Model):
    """
    Time tracking model for protocol sessions and steps.
    """

    history = HistoricalRecords()
    name = models.CharField(max_length=255, blank=True, null=True)
    start_time = models.DateTimeField(blank=True, null=True)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="time_keeper", blank=True, null=True)
    step = models.ForeignKey(ProtocolStep, on_delete=models.CASCADE, related_name="time_keeper", blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="time_keeper")
    started = models.BooleanField(default=False)
    current_duration = models.IntegerField(blank=True, null=True)
    original_duration = models.IntegerField(
        blank=True, null=True, help_text="Original/target duration in seconds for reset functionality"
    )
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "ccc.RemoteHost", on_delete=models.CASCADE, related_name="time_keeper", blank=True, null=True
    )

    class Meta:
        app_label = "ccrv"
        ordering = ["id"]

    def __str__(self):
        return f"{self.start_time} - {self.session} - {self.step}"

    def __repr__(self):
        return f"{self.start_time} - {self.session} - {self.step}"


class TimeKeeperEvent(models.Model):
    """
    Event history for TimeKeeper tracking start and stop events.
    """

    EVENT_TYPE_CHOICES = [
        ("started", "Started"),
        ("stopped", "Stopped"),
        ("reset", "Reset"),
    ]

    time_keeper = models.ForeignKey(TimeKeeper, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    event_time = models.DateTimeField(auto_now_add=True)
    duration_at_event = models.IntegerField(blank=True, null=True, help_text="Duration in seconds at time of event")
    notes = models.TextField(blank=True, null=True)

    class Meta:
        app_label = "ccrv"
        ordering = ["-event_time"]

    def __str__(self):
        return f"{self.time_keeper.name or self.time_keeper.id} - {self.event_type} at {self.event_time}"


class SessionAnnotation(models.Model):
    """
    Junction model linking Sessions to Annotations for session-level notes.

    Allows multiple sessions to have separate annotation spaces.
    """

    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="session_annotations",
        help_text="Session this annotation is attached to",
    )
    annotation = models.ForeignKey(
        "ccc.Annotation",
        on_delete=models.CASCADE,
        related_name="session_attachments",
        help_text="Annotation attached to this session",
    )

    # Ordering and organization
    order = models.PositiveIntegerField(default=0, help_text="Display order of annotations within the session")

    # Metadata table for session-specific experimental metadata
    metadata_table = models.OneToOneField(
        "ccv.MetadataTable",
        on_delete=models.CASCADE,
        related_name="session_annotation",
        blank=True,
        null=True,
        help_text="Metadata table for experimental data associated with this session annotation",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccrv"
        unique_together = [["session", "annotation"]]
        ordering = ["order", "created_at"]

    def can_view(self, user):
        """
        Check if user can view this session annotation.
        Inherits permissions from the parent session.
        """
        return self.session.can_view(user)

    def can_edit(self, user):
        """
        Check if user can edit this session annotation.
        Inherits permissions from the parent session.
        """
        return self.session.can_edit(user)

    def can_delete(self, user):
        """
        Check if user can delete this session annotation.
        Inherits permissions from the parent session.
        """
        return self.session.can_delete(user)

    def create_metadata_table(self):
        """
        Create a metadata table for this session annotation if it doesn't exist.
        """
        if not self.metadata_table:
            from ccv.models import MetadataTable

            self.metadata_table = MetadataTable.objects.create(
                name=f"SessionAnnotation-{self.session.name}-{self.annotation.id}",
                description=f"Metadata table for session annotation: {self.session.name}",
                owner=self.session.owner,
                visibility=self.session.visibility,
                source_app="ccrv",
            )
            self.save()
        return self.metadata_table

    def add_metadata_column(self, column_data):
        """
        Add a metadata column to this session annotation's metadata table.

        Args:
            column_data (dict): Column configuration with required fields:
                - name: Column name/header (required)
                - type: Column type (optional, defaults to 'characteristics')
                - value: Default value (optional)
                - mandatory: Whether column is required (optional, defaults to False)
                - position: Column position (optional)

        Returns:
            MetadataColumn: The created column object

        Raises:
            ValueError: If required fields are missing or invalid
        """
        if not column_data.get("name"):
            raise ValueError("Column name is required")

        # Create metadata table if it doesn't exist
        if not self.metadata_table:
            self.create_metadata_table()

        # Use the metadata table's add_column method for proper positioning
        position = column_data.get("position")

        # Prepare column data for MetadataTable.add_column()
        table_column_data = {
            "name": column_data["name"],
            "type": column_data.get("type", "characteristics"),
            "value": column_data.get("value", ""),
            "mandatory": column_data.get("mandatory", False),
            "hidden": column_data.get("hidden", False),
            "readonly": column_data.get("readonly", False),
        }

        # Use the table's add_column method which handles positioning correctly
        column = self.metadata_table.add_column(table_column_data, position=position)

        return column

    def remove_metadata_column(self, column_id):
        """
        Remove a metadata column from this session annotation's metadata table.

        Args:
            column_id (int): ID of the column to remove

        Returns:
            bool: True if column was removed successfully

        Raises:
            ValueError: If no metadata table exists or column not found
        """
        if not self.metadata_table:
            raise ValueError("No metadata table found for this session annotation")

        from ccv.models import MetadataColumn

        try:
            column = MetadataColumn.objects.get(id=column_id, metadata_table=self.metadata_table)
            column.delete()
            return True
        except MetadataColumn.DoesNotExist:
            raise ValueError(f"Column with ID {column_id} not found in this metadata table")

    def get_metadata_columns(self):
        """
        Get all metadata columns for this session annotation.

        Returns:
            QuerySet: All metadata columns ordered by position
        """
        if not self.metadata_table:
            from ccv.models import MetadataColumn

            return MetadataColumn.objects.none()

        return self.metadata_table.columns.all().order_by("column_position", "id")

    def update_metadata_column_value(self, column_id, value):
        """
        Update the default value of a metadata column.

        Args:
            column_id (int): ID of the column to update
            value (str): New default value

        Returns:
            bool: True if value was updated successfully

        Raises:
            ValueError: If no metadata table exists or column not found
        """
        if not self.metadata_table:
            raise ValueError("No metadata table found for this session annotation")

        from ccv.models import MetadataColumn

        try:
            column = MetadataColumn.objects.get(id=column_id, metadata_table=self.metadata_table)
            column.value = value
            column.save(update_fields=["value"])
            return True
        except MetadataColumn.DoesNotExist:
            raise ValueError(f"Column with ID {column_id} not found in this metadata table")

    def __str__(self):
        return f"{self.session} - {self.annotation}"


class StepAnnotation(models.Model):
    """
    Junction model linking Protocol Steps to Annotations within Session context.

    Enables session-specific annotations for protocol steps, so the same
    protocol step can have different annotations in different sessions.
    """

    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="step_annotations",
        help_text="Session context for this step annotation",
    )
    step = models.ForeignKey(
        ProtocolStep,
        on_delete=models.CASCADE,
        related_name="step_annotations",
        help_text="Protocol step this annotation is attached to",
    )
    annotation = models.ForeignKey(
        "ccc.Annotation",
        on_delete=models.CASCADE,
        related_name="step_attachments",
        help_text="Annotation attached to this step",
    )

    # Ordering and organization
    order = models.PositiveIntegerField(default=0, help_text="Display order of annotations within the step")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccrv"
        unique_together = [["session", "step", "annotation"]]
        ordering = ["order", "created_at"]

    def can_view(self, user):
        """
        Check if user can view this step annotation.
        Inherits permissions from the parent session.
        """
        return self.session.can_view(user)

    def can_edit(self, user):
        """
        Check if user can edit this step annotation.
        Inherits permissions from the parent session.
        """
        return self.session.can_edit(user)

    def can_delete(self, user):
        """
        Check if user can delete this step annotation.
        Inherits permissions from the parent session.
        """
        return self.session.can_delete(user)

    def __str__(self):
        return f"{self.session} - {self.step} - {self.annotation}"


class InstrumentUsageStepAnnotation(models.Model):
    """
    Junction model linking StepAnnotations to InstrumentUsage bookings.

    This allows step annotations to be associated with specific instrument
    usage bookings, enabling documentation of which instrument bookings
    were used for specific protocol steps.
    """

    step_annotation = models.ForeignKey(
        StepAnnotation,
        on_delete=models.CASCADE,
        related_name="instrument_usage_links",
        help_text="Step annotation linked to instrument usage",
    )
    instrument_usage = models.ForeignKey(
        "ccm.InstrumentUsage",
        on_delete=models.CASCADE,
        related_name="step_annotation_links",
        help_text="Instrument usage booking this step annotation is linked to",
    )

    order = models.PositiveIntegerField(
        default=0, help_text="Display order of step annotations within the instrument usage"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccrv"
        unique_together = [["step_annotation", "instrument_usage"]]
        ordering = ["order", "created_at"]

    def can_view(self, user):
        """
        Check if user can view this step annotation to instrument usage link.
        Can view if they can view either the step annotation OR the instrument usage.
        """
        return self.step_annotation.can_view(user) or self.instrument_usage.user_can_view(user)

    def can_edit(self, user):
        """
        Check if user can edit this step annotation to instrument usage link.
        Can edit if they can edit the step annotation OR manage the instrument.
        """
        return self.step_annotation.can_edit(user) or self.instrument_usage.user_can_edit(user)

    def can_delete(self, user):
        """
        Check if user can delete this step annotation to instrument usage link.
        Can delete if they can delete the step annotation OR edit the instrument usage.
        """
        return self.step_annotation.can_delete(user) or self.instrument_usage.user_can_edit(user)

    def __str__(self):
        return f"{self.step_annotation.session.name} - Step {self.step_annotation.step.step_number} - {self.instrument_usage.instrument.instrument_name}"


class SessionAnnotationFolder(models.Model):
    """
    Junction model linking Sessions to AnnotationFolders for session-specific folder organization.

    Enables each session to have its own folder structure for organizing
    annotations that don't belong to specific steps.
    """

    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="session_annotation_folders",
        help_text="Session this folder belongs to",
    )
    folder = models.ForeignKey(
        "ccc.AnnotationFolder",
        on_delete=models.CASCADE,
        related_name="session_attachments",
        help_text="Annotation folder attached to this session",
    )

    # Ordering and organization
    order = models.PositiveIntegerField(default=0, help_text="Display order of folders within the session")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccrv"
        unique_together = [["session", "folder"]]
        ordering = ["order", "created_at"]

    def can_view(self, user):
        """
        Check if user can view this session folder.
        Inherits permissions from the parent session.
        """
        return self.session.can_view(user)

    def can_edit(self, user):
        """
        Check if user can edit this session folder.
        Inherits permissions from the parent session.
        """
        return self.session.can_edit(user)

    def can_delete(self, user):
        """
        Check if user can delete this session folder.
        Inherits permissions from the parent session.
        """
        return self.session.can_delete(user)

    def __str__(self):
        return f"{self.session} - {self.folder}"


class InstrumentUsageSessionAnnotation(models.Model):
    """
    Junction model linking SessionAnnotations to InstrumentUsage bookings.

    This allows session annotations to be associated with specific instrument
    usage bookings, enabling rich documentation of experimental sessions
    that use instruments from the CCM app.
    """

    session_annotation = models.ForeignKey(
        SessionAnnotation,
        on_delete=models.CASCADE,
        related_name="instrument_usage_links",
        help_text="Session annotation linked to instrument usage",
    )
    instrument_usage = models.ForeignKey(
        "ccm.InstrumentUsage",
        on_delete=models.CASCADE,
        related_name="session_annotation_links",
        help_text="Instrument usage booking this session annotation is linked to",
    )

    # Ordering and organization
    order = models.PositiveIntegerField(
        default=0, help_text="Display order of session annotations within the instrument usage"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccrv"
        unique_together = [["session_annotation", "instrument_usage"]]
        ordering = ["order", "created_at"]

    def can_view(self, user):
        """
        Check if user can view this session annotation to instrument usage link.
        Can view if they can view either the session annotation OR the instrument usage.
        """
        # Can view if they can view either the session annotation or the instrument usage
        return self.session_annotation.can_view(user) or self.instrument_usage.user_can_view(user)

    def can_edit(self, user):
        """
        Check if user can edit this session annotation to instrument usage link.
        Can edit if they can edit the session annotation OR manage the instrument.
        """
        # Can edit if they can edit the session annotation or manage the instrument
        return self.session_annotation.can_edit(user) or self.instrument_usage.user_can_edit(user)

    def can_delete(self, user):
        """
        Check if user can delete this session annotation to instrument usage link.
        Can delete if they can delete the session annotation OR edit the instrument usage.
        """
        return self.session_annotation.can_delete(user) or self.instrument_usage.user_can_edit(user)

    def __str__(self):
        return f"{self.session_annotation.session.name} - {self.instrument_usage.instrument.instrument_name}"
