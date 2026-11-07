"""Who may manage custom vocabularies."""

from ccv.models import Vocabulary


def can_manage_lab_group_vocabularies(user, lab_group) -> bool:
    """Whether the user may create and change vocabularies of the lab group; global ones (no lab group) need staff."""
    if user.is_staff or user.is_superuser:
        return True
    return lab_group is not None and lab_group.can_manage(user)


def can_manage_vocabulary(user, vocabulary: Vocabulary) -> bool:
    """Whether the user may change a custom vocabulary and its terms."""
    return vocabulary.provider == Vocabulary.PROVIDER_CUSTOM and can_manage_lab_group_vocabularies(
        user, vocabulary.lab_group
    )
