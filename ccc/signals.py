from django.db.models.signals import post_save
from django.dispatch import receiver

from ccc.models import LabGroup, LabGroupPermission


@receiver(post_save, sender=LabGroup)
def create_creator_permission(sender, instance, created, **kwargs):
    """
    Auto-create LabGroupPermission for creator when a lab group is created.

    Creator gets all permissions by default:
    - can_view: True
    - can_invite: True
    - can_manage: True
    - can_process_jobs: Based on lab group's allow_process_jobs setting
    """
    if created and instance.creator:
        LabGroupPermission.objects.get_or_create(
            user=instance.creator,
            lab_group=instance,
            defaults={
                "can_view": True,
                "can_invite": True,
                "can_manage": True,
                "can_process_jobs": instance.allow_process_jobs,
            },
        )
