"""
Permission classes that handle cross-app metadata access patterns.
"""

from rest_framework.permissions import BasePermission


class MetadataTableAccessPermission(BasePermission):
    """
    Permission class that handles both CCV and CCM metadata table access.
    Uses dynamic permission checking based on source_app field.
    """

    def has_object_permission(self, request, view, obj):
        """
        Check permissions for metadata table access.
        Handles both CCV tables and CCM tables with different business logic.
        """
        # For CCV tables, use standard CCV permissions
        if obj.source_app == "ccv":
            return (
                obj.can_view(request.user)
                if request.method in ["GET", "HEAD", "OPTIONS"]
                else obj.can_edit(request.user)
            )

        # For CCM tables, check related CCM object permissions
        elif obj.source_app == "ccm":
            return self._check_ccm_permissions(request, obj)

        # Default to standard table permissions for other apps
        return (
            obj.can_view(request.user) if request.method in ["GET", "HEAD", "OPTIONS"] else obj.can_edit(request.user)
        )

    def _check_ccm_permissions(self, request, metadata_table):
        """
        Check CCM-specific permissions without importing CCM models.
        Uses reverse foreign key lookups to find related CCM objects.
        Handles cases where CCM is not installed or unavailable.
        """
        user = request.user
        is_read_only = request.method in ["GET", "HEAD", "OPTIONS"]

        try:
            # Check if this is an instrument metadata table
            if hasattr(metadata_table, "instrument"):
                instrument = metadata_table.instrument
                if is_read_only:
                    # View permissions: owner, staff/admin
                    return user.is_staff or user.is_superuser or instrument.user == user
                else:
                    # Edit permissions: only owner
                    return instrument.user == user

            # Check if this is an instrument job metadata table
            elif hasattr(metadata_table, "instrument_jobs") and metadata_table.instrument_jobs.exists():
                job = metadata_table.instrument_jobs.first()
                if is_read_only:
                    # Use job's can_user_view_metadata method
                    return self._check_job_view_permission(user, job)
                else:
                    # Use job's can_user_edit_metadata method
                    return self._check_job_edit_permission(user, job)
        except (AttributeError, ImportError):
            # CCM not available or models not accessible, fallback to standard permissions
            pass

        # Fallback to standard permissions
        return metadata_table.can_view(user) if is_read_only else metadata_table.can_edit(user)

    def _check_job_view_permission(self, user, job):
        """
        Check job view permissions using duck typing.
        Safe for use when CCM may not be available.
        """
        try:
            # Draft status check
            if hasattr(job, "status") and job.status == "draft":
                if user.is_staff or user.is_superuser:
                    return True
                return hasattr(job, "user") and job.user == user

            # Non-draft permissions
            if user.is_staff or user.is_superuser:
                return True
            if hasattr(job, "user") and job.user == user:
                return True
            if hasattr(job, "staff") and user in job.staff.all():
                return True
        except (AttributeError, ImportError):
            # CCM models not available or error accessing job attributes
            pass

        return False

    def _check_job_edit_permission(self, user, job):
        """
        Check job edit permissions using duck typing.
        Safe for use when CCM may not be available.

        Rules:
        - Draft status: Job owner can edit
        - If staff assigned: Only staff members (who must be in lab_group if lab_group exists) can edit
        - If no staff but lab_group exists: lab_group members can edit
        - Django staff/superuser: Same rules as regular users (must be owner/assigned)
        """
        try:
            # Job owner can edit in draft status
            if hasattr(job, "user") and hasattr(job, "status"):
                if job.user == user and job.status == "draft":
                    return True

            # Check if there are staff assigned to this job
            if hasattr(job, "staff"):
                assigned_staff = job.staff.all()
                has_assigned_staff = (
                    assigned_staff.exists() if hasattr(assigned_staff, "exists") else len(assigned_staff) > 0
                )

                if has_assigned_staff:
                    # If staff are assigned, only those staff can edit
                    # Staff must also be members of the lab_group if lab_group exists
                    if user in assigned_staff:
                        if hasattr(job, "lab_group") and job.lab_group:
                            if hasattr(job.lab_group, "is_member"):
                                return job.lab_group.is_member(user)
                        return True
                else:
                    # No staff assigned, lab_group members can edit (after draft)
                    if hasattr(job, "status") and job.status != "draft":
                        if hasattr(job, "lab_group") and job.lab_group and hasattr(job.lab_group, "is_member"):
                            if job.lab_group.is_member(user):
                                return True
        except (AttributeError, ImportError):
            # CCM models not available or error accessing job attributes
            pass

        return False


class MetadataColumnAccessPermission(BasePermission):
    """
    Permission class for metadata column access with staff_only support.
    """

    def has_object_permission(self, request, view, obj):
        """Check column-level permissions including staff_only logic."""
        metadata_table = obj.metadata_table
        user = request.user
        is_read_only = request.method in ["GET", "HEAD", "OPTIONS"]

        # First check table-level permissions
        table_permission = MetadataTableAccessPermission()
        if not table_permission.has_object_permission(request, view, metadata_table):
            return False

        # For read operations, staff_only columns require special handling
        if is_read_only and obj.staff_only:
            return self._can_view_staff_only_column(user, metadata_table)

        # For write operations, staff_only columns require staff assignment
        if not is_read_only and obj.staff_only:
            return self._can_edit_staff_only_column(user, metadata_table)

        # Non-staff-only columns follow table permissions
        return True

    def _can_view_staff_only_column(self, user, metadata_table):
        """Check if user can view staff_only columns."""
        if metadata_table.source_app == "ccm":
            # For CCM tables, check job staff assignment
            if hasattr(metadata_table, "instrument_jobs") and metadata_table.instrument_jobs.exists():
                job = metadata_table.instrument_jobs.first()
                return user.is_staff or user.is_superuser or (hasattr(job, "staff") and user in job.staff.all())

        # Default to staff/admin only
        return user.is_staff or user.is_superuser

    def _can_edit_staff_only_column(self, user, metadata_table):
        """Check if user can edit staff_only columns."""
        if metadata_table.source_app == "ccm":
            # For CCM tables, only assigned job staff can edit staff_only columns
            if hasattr(metadata_table, "instrument_jobs") and metadata_table.instrument_jobs.exists():
                job = metadata_table.instrument_jobs.first()
                return hasattr(job, "staff") and user in job.staff.all()

        # Default to staff/admin only
        return user.is_staff or user.is_superuser
