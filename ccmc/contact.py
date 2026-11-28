"""
Who may contact whom through messages and notifications.

Staff are not limited. Other users may contact those who share a lab group with them, where the members of a
sub-group count as members of its parent groups, unless either has blocked the other.
"""

from django.db.models import Q

from ccc.models import LabGroup

from .models import UserBlock


def lab_group_ids(user):
    """The ids of the lab groups the user belongs to or created, with all their parent groups."""
    ids = set()
    for group in LabGroup.objects.filter(Q(members=user) | Q(creator=user)).distinct():
        current = group
        while current is not None and current.id not in ids:
            ids.add(current.id)
            current = current.parent_group
    return ids


def share_lab_group(user, other):
    """Whether the two users belong to a common lab group."""
    return bool(lab_group_ids(user) & lab_group_ids(other))


def blocked_between(user, other):
    """Whether either user has blocked the other."""
    return UserBlock.objects.filter(Q(blocker=user, blocked=other) | Q(blocker=other, blocked=user)).exists()


def may_contact(sender, recipient):
    """Whether the sender may start a thread with, add to a thread or notify the recipient."""
    if sender.is_staff or sender.is_superuser or sender == recipient:
        return True
    if blocked_between(sender, recipient):
        return False
    return share_lab_group(sender, recipient)


def blocked_by(user):
    """The ids of the users the user has blocked."""
    return UserBlock.objects.filter(blocker=user).values_list("blocked_id", flat=True)
