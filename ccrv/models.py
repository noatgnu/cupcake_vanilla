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
