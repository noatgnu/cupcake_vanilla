"""Shared ViewSet mixins reused across CUPCAKE apps."""

from django.contrib.contenttypes.models import ContentType

from ccc.models import DeletionLog


class DeletionLogMixin:
    """
    Records a `DeletionLog` tombstone before hard-deleting an instance.

    Mix into any `ModelViewSet` whose model is part of the mobile delta-sync subset, so a
    deleted record can be detected via `GET /api/v1/deletions/?since=<timestamp>` instead of
    just silently disappearing from `updated_at__gte` pages. Subclasses with their own
    `perform_destroy` override (permission checks, cascade deletes, etc.) should call
    `super().perform_destroy(instance)` instead of `instance.delete()` directly so the
    tombstone is still written.
    """

    def perform_destroy(self, instance):
        user = getattr(self.request, "user", None)
        DeletionLog.objects.create(
            content_type=ContentType.objects.get_for_model(instance),
            object_id=instance.pk,
            deleted_by=user if user and user.is_authenticated else None,
            lab_group=getattr(instance, "lab_group", None),
        )
        instance.delete()
