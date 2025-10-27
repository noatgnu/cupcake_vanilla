from django.conf import settings
from django.db import models
from django.utils import timezone

from simple_history.models import HistoricalRecords

from ccc.models import LabGroup, SiteConfig


class Instrument(models.Model):
    history = HistoricalRecords()
    instrument_name = models.TextField(blank=False, null=False, default="Unnamed Instrument")
    instrument_description = models.TextField(blank=True, null=True)
    image = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "ccc.RemoteHost", on_delete=models.CASCADE, related_name="instruments", blank=True, null=True
    )
    max_days_ahead_pre_approval = models.IntegerField(blank=True, null=True, default=0)
    max_days_within_usage_pre_approval = models.IntegerField(blank=True, null=True, default=0)
    support_information = models.ManyToManyField("SupportInformation", blank=True)
    last_warranty_notification_sent = models.DateTimeField(blank=True, null=True)
    last_maintenance_notification_sent = models.DateTimeField(blank=True, null=True)
    days_before_warranty_notification = models.IntegerField(blank=True, null=True, default=30)
    days_before_maintenance_notification = models.IntegerField(blank=True, null=True, default=14)
    accepts_bookings = models.BooleanField(default=True)
    allow_overlapping_bookings = models.BooleanField(default=False)

    # Vaulting system for imported data
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_instruments",
        blank=True,
        null=True,
        help_text="Owner of this instrument",
    )
    is_vaulted = models.BooleanField(default=False, help_text="True if this instrument is in a user's import vault")

    # Metadata table for instrument specifications and settings
    metadata_table = models.OneToOneField(
        "ccv.MetadataTable",
        on_delete=models.CASCADE,
        related_name="instrument",
        blank=True,
        null=True,
        help_text="Metadata table storing instrument specifications that jobs can reference",
    )

    def __str__(self):
        return self.instrument_name

    def __repr__(self):
        return self.instrument_name

    class Meta:
        app_label = "ccm"
        ordering = ["id"]

    def check_warranty_expiration(self, days_threshold=30):
        """
        Check if instrument warranty is expiring soon and send notification
        """
        from datetime import timedelta

        from django.utils import timezone

        from .communication import send_maintenance_alert

        if not days_threshold:
            days_threshold = self.days_before_warranty_notification or 30

        today = timezone.now().date()

        if self.last_warranty_notification_sent and timezone.now() - self.last_warranty_notification_sent < timedelta(
            days=7
        ):
            return False

        for support_info in self.support_information.all():
            if not support_info.warranty_end_date:
                continue

            days_remaining = (support_info.warranty_end_date - today).days

            if 0 < days_remaining <= days_threshold:
                # Send CCMC notification if available
                maintenance_info = {
                    "warranty_end_date": support_info.warranty_end_date.isoformat(),
                    "days_remaining": days_remaining,
                    "vendor": support_info.vendor_name,
                }
                send_maintenance_alert(
                    instrument=self, message_type="warranty_expiring", maintenance_info=maintenance_info
                )

                self.last_warranty_notification_sent = timezone.now()
                self.save(update_fields=["last_warranty_notification_sent"])
                return True

        return False

    def is_maintenance_overdue(self, days_threshold=14):
        """
        Check if instrument maintenance is overdue WITHOUT sending notifications.
        Used for status display in serializers.
        """
        from datetime import timedelta

        from django.utils import timezone

        if not days_threshold:
            days_threshold = self.days_before_maintenance_notification or 14

        today = timezone.now().date()

        for support_info in self.support_information.all():
            if not support_info.maintenance_frequency_days:
                continue

            last_maintenance = self.maintenance_logs.filter(status="completed").order_by("-maintenance_date").first()

            if last_maintenance:
                next_maintenance_date = last_maintenance.maintenance_date.date() + timedelta(
                    days=support_info.maintenance_frequency_days
                )
                days_remaining = (next_maintenance_date - today).days

                if days_remaining <= days_threshold:
                    return True
            else:
                if support_info.maintenance_frequency_days <= days_threshold:
                    return True

        return False

    def check_upcoming_maintenance(self, days_threshold=14):
        """
        Check if instrument is due for maintenance and send notification
        """
        from datetime import timedelta

        from django.utils import timezone

        from .communication import send_maintenance_alert

        if not days_threshold:
            days_threshold = self.days_before_maintenance_notification or 14

        today = timezone.now().date()

        if (
            self.last_maintenance_notification_sent
            and timezone.now() - self.last_maintenance_notification_sent < timedelta(days=7)
        ):
            return False

        for support_info in self.support_information.all():
            if not support_info.maintenance_frequency_days:
                continue

            # Check actual maintenance logs
            last_maintenance = self.maintenance_logs.filter(status="completed").order_by("-maintenance_date").first()

            if last_maintenance:
                next_maintenance_date = last_maintenance.maintenance_date.date() + timedelta(
                    days=support_info.maintenance_frequency_days
                )

                days_remaining = (next_maintenance_date - today).days

                if days_remaining <= days_threshold:
                    # Send CCMC notification if available
                    maintenance_info = {
                        "next_maintenance_date": next_maintenance_date.isoformat(),
                        "days_remaining": days_remaining,
                        "frequency_days": support_info.maintenance_frequency_days,
                        "last_maintenance": last_maintenance.maintenance_date.isoformat(),
                    }
                    send_maintenance_alert(
                        instrument=self, message_type="maintenance_due", maintenance_info=maintenance_info
                    )

                    self.last_maintenance_notification_sent = timezone.now()
                    self.save(update_fields=["last_maintenance_notification_sent"])
                    return True
            else:
                # No maintenance history - trigger initial maintenance notification
                if support_info.maintenance_frequency_days <= days_threshold:
                    # Send CCMC notification if available
                    maintenance_info = {
                        "frequency_days": support_info.maintenance_frequency_days,
                        "initial_maintenance": True,
                    }
                    send_maintenance_alert(
                        instrument=self, message_type="maintenance_due", maintenance_info=maintenance_info
                    )

                    self.last_maintenance_notification_sent = timezone.now()
                    self.save(update_fields=["last_maintenance_notification_sent"])
                    return True

        return False

    @classmethod
    def check_all_instruments(cls, days_threshold=30):
        """
        Check all instruments for warranty expiration and upcoming maintenance
        """
        warranty_count = 0
        maintenance_count = 0

        instruments = cls.objects.filter(enabled=True).prefetch_related("support_information")

        for instrument in instruments:
            if instrument.check_warranty_expiration(days_threshold):
                warranty_count += 1

            if instrument.check_upcoming_maintenance(days_threshold):
                maintenance_count += 1

        return warranty_count, maintenance_count

    def create_default_folders(self):
        """
        Create default folders for the instrument
        """
        from ccc.models import AnnotationFolder, ResourceType

        # Check if folders already exist for this instrument
        existing_folders = AnnotationFolder.objects.filter(
            resource_type=ResourceType.FILE, owner=self.user, folder_name__in=["Manuals", "Certificates", "Maintenance"]
        )

        if existing_folders.count() >= 3:
            return

        # Create default folders for this instrument
        for folder_name in ["Manuals", "Certificates", "Maintenance"]:
            if not existing_folders.filter(folder_name=folder_name).exists():
                AnnotationFolder.objects.create(
                    folder_name=folder_name, resource_type=ResourceType.FILE, owner=self.user, visibility="private"
                )

    def user_can_view(self, user):
        """
        Check if user can view this instrument.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always view
        if user.is_staff or user.is_superuser:
            return True

        # Owner can always view
        if self.user == user:
            return True

        # Check explicit permission
        permission = self.instrument_permissions.filter(user=user).first()
        if permission and permission.can_view:
            return True

        return False

    def user_can_book(self, user):
        """
        Check if user can book/reserve this instrument.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always book
        if user.is_staff or user.is_superuser:
            return True

        # Owner can always book
        if self.user == user:
            return True

        # Check explicit permission
        permission = self.instrument_permissions.filter(user=user).first()
        if permission and permission.can_book:
            return True

        return False

    def user_can_manage(self, user):
        """
        Check if user can manage this instrument (modify settings, manage permissions).
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always manage
        if user.is_staff or user.is_superuser:
            return True

        # Owner can always manage
        if self.user == user:
            return True

        # Check explicit permission
        permission = self.instrument_permissions.filter(user=user).first()
        if permission and permission.can_manage:
            return True

        return False


class StorageObject(models.Model):
    history = HistoricalRecords()
    object_type_choices = [
        ("shelf", "Shelf"),
        ("box", "Box"),
        ("fridge", "Fridge"),
        ("freezer", "Freezer"),
        ("room", "Room"),
        ("building", "Building"),
        ("floor", "Floor"),
        ("other", "Other"),
    ]

    object_type = models.CharField(max_length=20, choices=object_type_choices, default="shelf")
    object_name = models.TextField(blank=False, null=False, default="Unnamed Storage")
    object_description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    stored_at = models.ForeignKey(
        "StorageObject", on_delete=models.CASCADE, related_name="storage_objects", blank=True, null=True
    )
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "ccc.RemoteHost", on_delete=models.CASCADE, related_name="storage_objects", blank=True, null=True
    )
    can_delete = models.BooleanField(default=False)
    png_base64 = models.TextField(blank=True, null=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="storage_objects", blank=True, null=True
    )
    access_lab_groups = models.ManyToManyField("ccc.LabGroup", related_name="storage_objects", blank=True)

    # Vaulting system for imported data
    is_vaulted = models.BooleanField(default=False, help_text="True if this storage object is in a user's import vault")

    class Meta:
        app_label = "ccm"
        ordering = ["id"]

    def __str__(self):
        return f"{self.object_name} ({self.object_type})"

    def get_full_path(self):
        """
        Get the full hierarchical path to root as an array of objects.
        Each object contains id and name for frontend navigation.
        """
        path = []
        current = self
        while current:
            path.insert(0, {"id": current.id, "name": current.object_name})
            current = current.stored_at
        return path

    def get_all_accessible_lab_groups(self):
        """
        Get all lab groups that have access to this storage object.
        Includes lab groups from parent storage objects (inheritance).

        Returns:
            QuerySet: LabGroup objects that have access
        """
        lab_group_ids = set()

        current = self
        while current:
            lab_group_ids.update(current.access_lab_groups.values_list("id", flat=True))
            current = current.stored_at

        return LabGroup.objects.filter(id__in=lab_group_ids)

    def can_access(self, user):
        """
        Check if user can access this storage object.

        Access is granted if:
        - User is staff/superuser
        - User is the owner
        - User is member of any lab group that has access (including inherited from parents)

        Args:
            user: Django User instance to check

        Returns:
            bool: True if user can access the storage object
        """
        if not user or not user.is_authenticated:
            return False

        if user.is_staff or user.is_superuser:
            return True

        if self.user == user:
            return True

        for lab_group in self.get_all_accessible_lab_groups():
            if lab_group.is_member(user):
                return True

        return False


class Reagent(models.Model):
    history = HistoricalRecords()
    name = models.CharField(max_length=255, default="Unnamed Reagent")
    unit = models.CharField(max_length=255, default="units")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccm"
        ordering = ["name"]

    def __str__(self):
        return self.name


class StoredReagent(models.Model):
    history = HistoricalRecords()
    reagent = models.ForeignKey(
        Reagent, on_delete=models.CASCADE, related_name="stored_reagents", blank=True, null=True
    )
    storage_object = models.ForeignKey(
        StorageObject, on_delete=models.CASCADE, related_name="stored_reagents", blank=True, null=True
    )
    quantity = models.FloatField(default=0.0)
    notes = models.TextField(blank=True, null=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stored_reagents", blank=True, null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    remote_host = models.ForeignKey(
        "ccc.RemoteHost", on_delete=models.CASCADE, related_name="stored_reagents", blank=True, null=True
    )
    png_base64 = models.TextField(blank=True, null=True)
    barcode = models.TextField(blank=True, null=True)
    shareable = models.BooleanField(default=True)
    access_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="shared_reagents", blank=True)
    access_lab_groups = models.ManyToManyField("ccc.LabGroup", related_name="shared_reagents", blank=True)
    access_all = models.BooleanField(default=False)
    expiration_date = models.DateField(blank=True, null=True)
    low_stock_threshold = models.FloatField(
        blank=True, null=True, help_text="Threshold quantity for low stock notifications"
    )
    notify_on_low_stock = models.BooleanField(default=False)
    last_notification_sent = models.DateTimeField(blank=True, null=True)

    # Metadata table for reagent specifications and properties
    metadata_table = models.OneToOneField(
        "ccv.MetadataTable",
        on_delete=models.CASCADE,
        related_name="stored_reagent",
        blank=True,
        null=True,
        help_text="Metadata table storing reagent specifications and properties",
    )

    class Meta:
        app_label = "ccm"
        ordering = ["reagent__name"]

    def __str__(self):
        return f"{self.reagent.name} in {self.storage_object.object_name}"

    def check_low_stock(self):
        """
        Check if reagent stock is below threshold and send notification
        """
        from datetime import timedelta

        from django.utils import timezone

        from .communication import send_reagent_alert

        if not self.notify_on_low_stock or not self.low_stock_threshold:
            return False

        # Avoid spam notifications - only send once per week
        if self.last_notification_sent and timezone.now() - self.last_notification_sent < timedelta(days=7):
            return False

        if self.quantity <= self.low_stock_threshold:
            # Send CCMC notification if available
            success = send_reagent_alert(stored_reagent=self, alert_type="low_stock")

            if success:
                self.last_notification_sent = timezone.now()
                self.save(update_fields=["last_notification_sent"])

            return success

        return False

    def check_expiration(self, days_threshold=7):
        """
        Check if reagent is expiring soon and send notification
        """
        from datetime import timedelta

        from django.utils import timezone

        from .communication import send_reagent_alert

        if not self.expiration_date:
            return False

        today = timezone.now().date()
        days_until_expiry = (self.expiration_date - today).days

        # Avoid spam notifications
        if self.last_notification_sent and timezone.now() - self.last_notification_sent < timedelta(days=3):
            return False

        if days_until_expiry <= 0:
            # Expired
            success = send_reagent_alert(stored_reagent=self, alert_type="expired")
        elif days_until_expiry <= days_threshold:
            # Expiring soon
            success = send_reagent_alert(stored_reagent=self, alert_type="expiring_soon")
        else:
            return False

        if success:
            self.last_notification_sent = timezone.now()
            self.save(update_fields=["last_notification_sent"])

        return success

    def create_default_folders(self):
        """
        Create default folders for the stored reagent: MSDS, Certificates, Manuals
        """
        from ccc.models import AnnotationFolder, ResourceType

        if not self.user:
            return

        # Check if folders already exist for this stored reagent
        existing_folders = AnnotationFolder.objects.filter(
            resource_type=ResourceType.FILE, owner=self.user, folder_name__in=["MSDS", "Certificates", "Manuals"]
        )

        if existing_folders.count() >= 3:
            return

        # Create default folders for this stored reagent
        for folder_name in ["MSDS", "Certificates", "Manuals"]:
            if not existing_folders.filter(folder_name=folder_name).exists():
                AnnotationFolder.objects.create(
                    folder_name=folder_name, resource_type=ResourceType.FILE, owner=self.user, visibility="private"
                )


class ExternalContactDetails(models.Model):
    history = HistoricalRecords()
    contact_method_alt_name = models.CharField(max_length=255, blank=False, null=False)
    contact_type_choices = [
        ("email", "Email"),
        ("phone", "Phone"),
        ("address", "Address"),
        ("other", "Other"),
    ]
    contact_type = models.CharField(max_length=20, choices=contact_type_choices, default="email")
    contact_value = models.TextField(blank=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccm"
        ordering = ["id"]

    def __str__(self):
        return f"{self.contact_method_alt_name}: {self.contact_value}"


class ExternalContact(models.Model):
    history = HistoricalRecords()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="external_contact_details",
        blank=True,
        null=True,
    )
    contact_name = models.CharField(max_length=255, blank=False, null=False)
    contact_details = models.ManyToManyField(ExternalContactDetails, blank=True, related_name="external_contact")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccm"
        ordering = ["id"]

    def __str__(self):
        return self.contact_name


class SupportInformation(models.Model):
    history = HistoricalRecords()
    vendor_name = models.CharField(max_length=255, blank=True, null=True)
    vendor_contacts = models.ManyToManyField("ExternalContact", blank=True, related_name="vendor_contact")
    manufacturer_name = models.CharField(max_length=255, blank=True, null=True)
    manufacturer_contacts = models.ManyToManyField("ExternalContact", blank=True, related_name="manufacturer_contact")
    serial_number = models.TextField(blank=True, null=True)
    maintenance_frequency_days = models.IntegerField(blank=True, null=True)
    location = models.ForeignKey(
        "StorageObject", on_delete=models.SET_NULL, blank=True, related_name="instrument_location", null=True
    )
    warranty_start_date = models.DateField(blank=True, null=True)
    warranty_end_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccm"
        ordering = ["id"]

    def __str__(self):
        return f"Support for {self.manufacturer_name or 'Unknown'}"


class ReagentSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reagent_subscriptions")
    stored_reagent = models.ForeignKey(StoredReagent, on_delete=models.CASCADE, related_name="subscriptions")
    notify_on_low_stock = models.BooleanField(default=True)
    notify_on_expiry = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "ccm"
        unique_together = ["user", "stored_reagent"]

    def __str__(self):
        return f"{self.user.username} - {self.stored_reagent.reagent.name}"


class ReagentAction(models.Model):
    history = HistoricalRecords()
    action_type_choices = [
        ("add", "Add"),
        ("reserve", "Reserve"),
    ]
    action_type = models.CharField(max_length=20, choices=action_type_choices, default="add")
    reagent = models.ForeignKey(StoredReagent, on_delete=models.CASCADE, related_name="reagent_actions")
    quantity = models.FloatField(default=0)
    notes = models.TextField(blank=True, null=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="reagent_actions", blank=True, null=True
    )
    session = models.ForeignKey(
        "ccrv.Session", on_delete=models.SET_NULL, related_name="reagent_actions", blank=True, null=True
    )
    step = models.ForeignKey(
        "ccrv.ProtocolStep", on_delete=models.SET_NULL, related_name="reagent_actions", blank=True, null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccm"
        ordering = ["id"]

    def __str__(self):
        return f"{self.action_type} {self.quantity} - {self.reagent.reagent.name}"

    def is_within_deletion_window(self):
        """
        Check if this reagent action is still within the deletion time window.

        Returns:
            bool: True if action is within deletion window, False otherwise
        """
        config = SiteConfig.objects.first()
        if not config:
            return True

        time_window = timezone.timedelta(minutes=config.booking_deletion_window_minutes)
        time_since_creation = timezone.now() - self.created_at

        return time_since_creation <= time_window

    def user_can_delete(self, user):
        """
        Check if user can delete this reagent action.

        Deletion is restricted by a time window after creation.
        Regular users can only delete their actions within the configured time window.
        Staff/superusers can delete at any time.
        """
        if not user or not user.is_authenticated:
            return False

        if user.is_staff or user.is_superuser:
            return True

        if self.user == user and self.is_within_deletion_window():
            return True

        return False


class InstrumentUsage(models.Model):
    history = HistoricalRecords()
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="instrument_usage")
    time_started = models.DateTimeField(blank=True, null=True)
    time_ended = models.DateTimeField(blank=True, null=True)
    usage_hours = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.0, help_text="Total hours of usage for billing"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remote_id = models.BigIntegerField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="instrument_usage", blank=True, null=True
    )
    remote_host = models.ForeignKey(
        "ccc.RemoteHost", on_delete=models.CASCADE, related_name="instrument_usages", blank=True, null=True
    )
    approved = models.BooleanField(default=False)
    maintenance = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="approved_by_instrument_usage",
        blank=True,
        null=True,
    )

    class Meta:
        app_label = "ccm"
        ordering = ["id"]

    def __str__(self):
        return f"{self.instrument.instrument_name} - {self.time_started}"

    def user_can_create(self, user):
        """
        Check if user can create an instrument usage booking.
        Requires can_book permission for the instrument.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always book
        if user.is_staff or user.is_superuser:
            return True

        # Check instrument booking permissions
        return self.instrument.user_can_book(user)

    def user_can_view(self, user):
        """
        Check if user can view this instrument usage.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always view
        if user.is_staff or user.is_superuser:
            return True

        # Must have instrument view permissions to see bookings
        # (This includes owners and users with explicit permissions)
        return self.instrument.user_can_view(user)

    def user_can_edit(self, user):
        """
        Check if user can edit this instrument usage.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always edit
        if user.is_staff or user.is_superuser:
            return True

        # User who created the booking can edit if they still have booking permissions
        if self.user == user and self.instrument.user_can_book(user):
            return True

        # Users with instrument manage permissions can edit all bookings
        if self.instrument.user_can_manage(user):
            return True

        return False

    def user_can_delete(self, user):
        """
        Check if user can delete this instrument usage.
        """
        return self.user_can_edit(user)


class MaintenanceLog(models.Model):
    history = HistoricalRecords()
    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="maintenance_logs", blank=True, null=True
    )
    maintenance_date = models.DateTimeField(help_text="When maintenance was performed", blank=True, null=True)

    MAINTENANCE_TYPE_CHOICES = [
        ("routine", "Routine"),
        ("emergency", "Emergency"),
        ("other", "Other"),
    ]
    maintenance_type = models.CharField(max_length=20, choices=MAINTENANCE_TYPE_CHOICES, default="routine")

    STATUS_CHOICES = [
        ("completed", "Completed"),
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("requested", "Requested"),
        ("cancelled", "Cancelled"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    maintenance_description = models.TextField(blank=True, null=True, help_text="Description of maintenance performed")
    maintenance_notes = models.TextField(blank=True, null=True, help_text="Additional notes about the maintenance")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="maintenance_logs", blank=True, null=True
    )

    is_template = models.BooleanField(default=False, help_text="Whether this is a maintenance template")
    annotation_folder = models.ForeignKey(
        "ccc.AnnotationFolder", on_delete=models.SET_NULL, related_name="maintenance_logs", blank=True, null=True
    )

    class Meta:
        app_label = "ccm"
        ordering = ["-maintenance_date"]

    def __str__(self):
        return f"{self.instrument.instrument_name} - {self.get_maintenance_type_display()} - {self.maintenance_date.strftime('%Y-%m-%d')}"

    def user_can_view(self, user):
        """
        Check if user can view this maintenance log.
        Requires can_manage permission on the instrument.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always view
        if user.is_staff or user.is_superuser:
            return True

        # Creator can always view
        if self.created_by == user:
            return True

        # Check instrument permissions
        if self.instrument:
            # Instrument owner can view maintenance logs
            if self.instrument.user == user:
                return True

            # Only users with manage permissions can see maintenance logs
            if self.instrument.user_can_manage(user):
                return True

        return False

    def user_can_edit(self, user):
        """
        Check if user can edit this maintenance log.
        Uses instrument permission system.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always edit
        if user.is_staff or user.is_superuser:
            return True

        # Creator can always edit
        if self.created_by == user:
            return True

        # Check instrument permissions
        if self.instrument:
            # Users with instrument manage permissions can edit maintenance logs
            if self.instrument.user_can_manage(user):
                return True

        return False

    def user_can_delete(self, user):
        """
        Check if user can delete this maintenance log.
        Uses instrument permission system.
        """
        return self.user_can_edit(user)  # Same as edit permissions


class InstrumentJob(models.Model):
    """
    Represents a specific job or task performed on an instrument.

    This is different from InstrumentUsage which tracks time-based usage.
    InstrumentJob tracks specific experiments, analyses, or procedures
    with detailed metadata and billing information.
    """

    history = HistoricalRecords()

    # Core relationships
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="instrument_jobs", blank=True, null=True
    )
    instrument = models.ForeignKey(
        Instrument, on_delete=models.SET_NULL, related_name="instrument_jobs", blank=True, null=True
    )
    instrument_usage = models.ForeignKey(
        InstrumentUsage, on_delete=models.SET_NULL, related_name="instrument_jobs", blank=True, null=True
    )
    lab_group = models.ForeignKey(
        "ccc.LabGroup",
        on_delete=models.SET_NULL,
        related_name="instrument_jobs",
        blank=True,
        null=True,
        help_text="Lab group responsible for processing this job",
    )
    project = models.ForeignKey(
        "ccrv.Project",
        on_delete=models.SET_NULL,
        related_name="instrument_jobs",
        blank=True,
        null=True,
        help_text="Project this instrument job is associated with",
    )

    # Job details
    JOB_TYPE_CHOICES = [
        ("maintenance", "Maintenance"),
        ("analysis", "Analysis"),
        ("other", "Other"),
    ]
    job_type = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES, default="analysis")
    job_name = models.TextField(blank=True, null=True)

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("in_progress", "In Progress"),
        ("cancelled", "Cancelled"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")

    # Sample information
    sample_number = models.IntegerField(blank=True, null=True)
    SAMPLE_TYPE_CHOICES = [
        ("wcl", "Whole Cell Lysate"),
        ("ip", "Immunoprecipitate"),
        ("other", "Other"),
    ]
    sample_type = models.CharField(max_length=20, choices=SAMPLE_TYPE_CHOICES, default="other")

    # Technical details
    injection_volume = models.FloatField(blank=True, null=True)
    injection_unit = models.TextField(blank=True, null=True, default="uL")
    search_engine = models.TextField(blank=True, null=True)
    search_engine_version = models.TextField(blank=True, null=True)
    search_details = models.TextField(blank=True, null=True)
    method = models.TextField(blank=True, null=True)
    location = models.TextField(blank=True, null=True)

    # Billing and administrative
    funder = models.TextField(blank=True, null=True)
    cost_center = models.TextField(blank=True, null=True)

    # Staff assignment
    assigned = models.BooleanField(default=False)
    staff = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="assigned_instrument_jobs", blank=True)

    # Metadata integration with CCV
    metadata_table = models.ForeignKey(
        "ccv.MetadataTable",
        on_delete=models.SET_NULL,
        related_name="instrument_jobs",
        blank=True,
        null=True,
        help_text="Metadata table containing job-specific data",
    )

    # Attachments via CCC annotation system
    user_annotations = models.ManyToManyField("ccc.Annotation", related_name="instrument_jobs", blank=True)
    staff_annotations = models.ManyToManyField("ccc.Annotation", related_name="assigned_instrument_jobs", blank=True)

    # Reagents
    stored_reagent = models.ForeignKey(
        StoredReagent, on_delete=models.SET_NULL, related_name="instrument_jobs", blank=True, null=True
    )

    # Time tracking for billing
    instrument_start_time = models.DateTimeField(
        null=True, blank=True, help_text="When instrument started for this job"
    )
    instrument_end_time = models.DateTimeField(null=True, blank=True, help_text="When instrument finished for this job")
    personnel_start_time = models.DateTimeField(
        null=True, blank=True, help_text="When personnel started working on this job"
    )
    personnel_end_time = models.DateTimeField(
        null=True, blank=True, help_text="When personnel finished working on this job"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        app_label = "ccm"
        ordering = ["-id"]

    def __str__(self):
        job_name = self.job_name or f"{self.get_job_type_display()} Job"
        instrument_name = self.instrument.instrument_name if self.instrument else "No Instrument"
        return f"{job_name} - {instrument_name}"

    @property
    def instrument_hours(self):
        """Calculate hours of instrument time for billing purposes."""
        from decimal import Decimal

        if self.instrument_start_time and self.instrument_end_time:
            delta = self.instrument_end_time - self.instrument_start_time
            hours = delta.total_seconds() / 3600
            return Decimal(str(hours))
        return Decimal("0")

    @property
    def personnel_hours(self):
        """Calculate hours of personnel time for billing purposes."""
        from decimal import Decimal

        if self.personnel_start_time and self.personnel_end_time:
            delta = self.personnel_end_time - self.personnel_start_time
            hours = delta.total_seconds() / 3600
            return Decimal(str(hours))
        return Decimal("0")

    def get_billable_hours(self, billing_type="instrument"):
        """
        Get billable hours for different billing types.

        Args:
            billing_type (str): 'instrument', 'personnel', or 'both'

        Returns:
            float: Hours to bill
        """
        if billing_type == "instrument":
            return self.instrument_hours
        elif billing_type == "personnel":
            return self.personnel_hours
        elif billing_type == "both":
            return max(self.instrument_hours, self.personnel_hours)
        return 0

    def is_billable(self):
        """Check if this job should be billed."""
        return self.status in ["completed"] and (self.instrument_hours > 0 or self.personnel_hours > 0)

    def get_editable_metadata_columns(self, user):
        """
        Get metadata columns that a user can edit based on staff_only permissions.

        Args:
            user: User instance

        Returns:
            QuerySet of MetadataColumn instances the user can edit
        """
        if not self.metadata_table:
            return None

        # Get all columns for this metadata table
        columns = self.metadata_table.columns.all()

        # Filter based on staff_only permissions
        if user and (user.is_staff or user.is_superuser):
            # Staff can edit all columns
            return columns
        else:
            # Non-staff can only edit non-staff_only columns
            return columns.filter(staff_only=False)

    def check_job_permissions(self, user, action="read"):
        """
        Check if user has permission to perform action on instrument job.

        Args:
            user: User instance
            action: 'read', 'write', or 'admin'

        Returns:
            tuple: (has_permission: bool, is_staff_user: bool)
        """
        if not user:
            return False, False

        # System admin always has access
        if user.is_staff or user.is_superuser:
            return True, True

        # Job owner has read access only (write access subject to staff_only restrictions)
        if self.user == user:
            return True, False

        # Check staff assignment
        if user in self.staff.all():
            return True, True

        return False, False

    def can_user_view_metadata(self, user):
        """
        Check if a user can view metadata for this job.

        Args:
            user: User instance

        Returns:
            bool: True if user can view metadata
        """
        if not user or not self.metadata_table:
            return False

        # Staff and admin users can view all metadata tables
        if user.is_staff or user.is_superuser:
            return True

        # If job is in draft status, only the job owner can view metadata
        if self.status == "draft":
            return self.user == user

        # Job owner can view their own metadata
        if self.user == user:
            return True

        # Staff assigned to job can view metadata
        if user in self.staff.all():
            return True

        # For other users, delegate to the metadata table's permissions
        return self.metadata_table.can_view(user)

    def can_user_edit_metadata(self, user):
        """
        Check if a user can edit metadata for this job.

        Args:
            user: User instance

        Returns:
            bool: True if user can edit metadata (column-level permissions checked separately)
        """
        if not user or not self.metadata_table:
            return False

        # Job owner can edit their own metadata
        if self.user == user:
            return True

        # Staff assigned to this specific job can edit metadata
        if user in self.staff.all():
            return True

        # For all other cases, no edit permission
        return False

    def get_staff_editable_metadata(self):
        """
        Get metadata table that staff can edit for this job.

        Returns:
            MetadataTable: The metadata table if it exists and is staff-editable, None otherwise
        """
        if not self.metadata_table:
            return None

        # Return the metadata table (staff permissions are checked separately)
        return self.metadata_table

    def get_metadata_summary(self):
        """
        Get a summary of metadata associated with this job.

        Returns:
            dict: Summary of metadata table info
        """
        if not self.metadata_table:
            return {"has_metadata": False, "total_columns": 0, "staff_only_columns": 0, "user_editable_columns": 0}

        columns = self.metadata_table.columns.all()
        staff_only_count = columns.filter(staff_only=True).count()

        return {
            "has_metadata": True,
            "metadata_table_name": self.metadata_table.name,
            "total_columns": columns.count(),
            "staff_only_columns": staff_only_count,
            "user_editable_columns": columns.count() - staff_only_count,
        }

    def can_transition_to_status(self, new_status, user):
        """
        Check if a job can transition to a new status.

        Args:
            new_status: Target status
            user: User attempting the transition

        Returns:
            bool: True if transition is allowed
        """
        if not user:
            return False

        has_permission, is_staff_user = self.check_job_permissions(user, "write")
        if not has_permission:
            return False

        # Define allowed transitions
        transitions = {
            "draft": ["submitted", "cancelled"],
            "submitted": ["pending", "cancelled"],
            "pending": ["in_progress", "cancelled"],
            "in_progress": ["completed", "cancelled"],
            "completed": [],  # Terminal state
            "cancelled": [],  # Terminal state
        }

        return new_status in transitions.get(self.status, [])

    def complete_job(self, user, completed_at=None):
        """
        Mark job as completed and trigger billing if applicable.

        Args:
            user: User completing the job
            completed_at: Completion timestamp (defaults to now)

        Returns:
            bool: True if job was successfully completed
        """
        from django.utils import timezone

        if not self.can_transition_to_status("completed", user):
            return False

        # Set completion timestamp
        if not completed_at:
            completed_at = timezone.now()

        self.completed_at = completed_at
        self.status = "completed"

        # Auto-set end times if not already set
        if not self.instrument_end_time and self.instrument_start_time:
            self.instrument_end_time = completed_at

        if not self.personnel_end_time and self.personnel_start_time:
            self.personnel_end_time = completed_at

        self.save()

        # Trigger billing record creation if CCSC is available
        self._trigger_billing_creation()

        return True

    def _trigger_billing_creation(self):
        """
        Trigger billing record creation if conditions are met.
        This will integrate with CCSC when it's available.
        """
        if not self.is_billable():
            return

        # TODO: Integrate with CCSC billing system when available
        # For now, this is a placeholder for the billing trigger
        try:
            from django.dispatch import Signal

            # Send custom signal for billing system to catch
            billing_trigger = Signal()
            billing_trigger.send(sender=self.__class__, instance=self, created=False, trigger_type="job_completed")
        except ImportError:
            # CCSC not available, skip billing trigger
            pass

    def get_billing_summary(self):
        """
        Get billing summary for this job.

        Returns:
            dict: Billing information
        """
        return {
            "is_billable": self.is_billable(),
            "instrument_hours": self.instrument_hours,
            "personnel_hours": self.personnel_hours,
            "cost_center": self.cost_center,
            "funder": self.funder,
            "status": self.status,
            "billable_hours_instrument": self.get_billable_hours("instrument"),
            "billable_hours_personnel": self.get_billable_hours("personnel"),
            "billable_hours_both": self.get_billable_hours("both"),
        }


# Annotation relationship models for CCM entities
class InstrumentAnnotation(models.Model):
    """
    Junction model linking Instruments to Annotations via predefined folders.

    Instruments have 3 default folders: Manuals, Certificates, Maintenance.
    All annotations must be organized within one of these folders.
    """

    instrument = models.ForeignKey(
        Instrument,
        on_delete=models.CASCADE,
        related_name="instrument_annotations",
        help_text="Instrument this annotation is attached to",
    )
    annotation = models.ForeignKey(
        "ccc.Annotation",
        on_delete=models.CASCADE,
        related_name="instrument_attachments",
        help_text="Annotation attached to this instrument",
    )
    folder = models.ForeignKey(
        "ccc.AnnotationFolder",
        on_delete=models.CASCADE,
        related_name="instrument_annotations",
        help_text="Folder (Manuals, Certificates, or Maintenance) containing this annotation",
    )

    # Ordering and organization
    order = models.PositiveIntegerField(default=0, help_text="Display order of annotations within the folder")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccm"
        unique_together = [["instrument", "annotation", "folder"]]
        ordering = ["order", "created_at"]

    def clean(self):
        """Validate that folder is one of the allowed instrument folders."""
        if self.folder and self.folder.folder_name not in ["Manuals", "Certificates", "Maintenance"]:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                f"Instrument annotations must use Manuals, Certificates, or Maintenance folders. Got: {self.folder.folder_name}"
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def can_view(self, user):
        """
        Check if user can view this instrument annotation.
        Uses instrument permission system for granular access control.
        """
        return self.instrument.user_can_view(user)

    def can_edit(self, user):
        """
        Check if user can edit this instrument annotation.
        Uses instrument permission system - requires manage permissions for editing.
        """
        return self.instrument.user_can_manage(user)

    def can_delete(self, user):
        """
        Check if user can delete this instrument annotation.
        Uses instrument permission system - requires manage permissions for deletion.
        """
        return self.instrument.user_can_manage(user)

    def __str__(self):
        return f"{self.instrument} - {self.folder.folder_name} - {self.annotation}"


class StoredReagentAnnotation(models.Model):
    """
    Junction model linking StoredReagents to Annotations via predefined folders.

    StoredReagents have 3 default folders: MSDS, Certificates, Manuals.
    All annotations must be organized within one of these folders.
    """

    stored_reagent = models.ForeignKey(
        StoredReagent,
        on_delete=models.CASCADE,
        related_name="stored_reagent_annotations",
        help_text="StoredReagent this annotation is attached to",
    )
    annotation = models.ForeignKey(
        "ccc.Annotation",
        on_delete=models.CASCADE,
        related_name="stored_reagent_attachments",
        help_text="Annotation attached to this stored reagent",
    )
    folder = models.ForeignKey(
        "ccc.AnnotationFolder",
        on_delete=models.CASCADE,
        related_name="stored_reagent_annotations",
        help_text="Folder (MSDS, Certificates, or Manuals) containing this annotation",
    )

    # Ordering and organization
    order = models.PositiveIntegerField(default=0, help_text="Display order of annotations within the folder")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccm"
        unique_together = [["stored_reagent", "annotation", "folder"]]
        ordering = ["order", "created_at"]

    def clean(self):
        """Validate that folder is one of the allowed stored reagent folders."""
        if self.folder and self.folder.folder_name not in ["MSDS", "Certificates", "Manuals"]:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                f"StoredReagent annotations must use MSDS, Certificates, or Manuals folders. Got: {self.folder.folder_name}"
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def can_view(self, user):
        """
        Check if user can view this stored reagent annotation.
        Inherits permissions from the parent stored reagent.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always view
        if user.is_staff or user.is_superuser:
            return True

        # Check stored reagent ownership
        if self.stored_reagent.user == user:
            return True

        # Check if stored reagent is shareable and accessible
        if self.stored_reagent.shareable:
            # Check if user has explicit access
            if user in self.stored_reagent.access_users.all():
                return True

            # Check lab group access (includes bubble-up from sub-groups)
            for lab_group in self.stored_reagent.access_lab_groups.all():
                if lab_group.is_member(user):
                    return True

            # Check if access is open to all
            if self.stored_reagent.access_all:
                return True

        return False

    def can_edit(self, user):
        """
        Check if user can edit this stored reagent annotation.
        Inherits permissions from the parent stored reagent.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff/superuser can always edit
        if user.is_staff or user.is_superuser:
            return True

        # Only stored reagent owner can edit annotations
        # (Shared access is typically read-only for safety documents)
        return self.stored_reagent.user == user

    def can_delete(self, user):
        """
        Check if user can delete this stored reagent annotation.
        Inherits permissions from the parent stored reagent.
        """
        return self.can_edit(user)  # Same as edit permissions

    def __str__(self):
        return f"{self.stored_reagent} - {self.folder.folder_name} - {self.annotation}"


class MaintenanceLogAnnotation(models.Model):
    """
    Junction model linking MaintenanceLogs to Annotations for direct attachment.

    MaintenanceLogs can have annotations directly attached without folder organization,
    or can be organized within the existing annotation_folder field.
    """

    maintenance_log = models.ForeignKey(
        MaintenanceLog,
        on_delete=models.CASCADE,
        related_name="maintenance_log_annotations",
        help_text="MaintenanceLog this annotation is attached to",
    )
    annotation = models.ForeignKey(
        "ccc.Annotation",
        on_delete=models.CASCADE,
        related_name="maintenance_log_attachments",
        help_text="Annotation attached to this maintenance log",
    )

    # Ordering and organization
    order = models.PositiveIntegerField(default=0, help_text="Display order of annotations within the maintenance log")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccm"
        unique_together = [["maintenance_log", "annotation"]]
        ordering = ["order", "created_at"]

    def can_view(self, user):
        """
        Check if user can view this maintenance log annotation.
        Inherits permissions from the parent maintenance log using instrument permission system.
        """
        return self.maintenance_log.user_can_view(user)

    def can_edit(self, user):
        """
        Check if user can edit this maintenance log annotation.
        Inherits permissions from the parent maintenance log using instrument permission system.
        """
        return self.maintenance_log.user_can_edit(user)

    def can_delete(self, user):
        """
        Check if user can delete this maintenance log annotation.
        Inherits permissions from the parent maintenance log using instrument permission system.
        """
        return self.maintenance_log.user_can_delete(user)

    def __str__(self):
        return f"{self.maintenance_log} - {self.annotation}"


class InstrumentPermission(models.Model):
    """
    Granular permission system for instruments.

    Provides three levels of permissions:
    - can_view: Can see instrument details and usage data
    - can_book: Can make bookings/reservations for the instrument
    - can_manage: Can modify instrument settings and manage other users' permissions
    """

    history = HistoricalRecords()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="instrument_permissions")
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="instrument_permissions")
    can_view = models.BooleanField(default=False, help_text="Can view instrument details and usage data")
    can_book = models.BooleanField(default=False, help_text="Can make bookings/reservations for the instrument")
    can_manage = models.BooleanField(default=False, help_text="Can modify instrument settings and manage permissions")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ccm"
        unique_together = [["user", "instrument"]]  # Each user can have one permission set per instrument
        ordering = ["created_at"]

    def __str__(self):
        permissions = []
        if self.can_view:
            permissions.append("view")
        if self.can_book:
            permissions.append("book")
        if self.can_manage:
            permissions.append("manage")
        permission_str = ", ".join(permissions) if permissions else "no permissions"
        return f"{self.user.username} - {self.instrument.instrument_name} ({permission_str})"
