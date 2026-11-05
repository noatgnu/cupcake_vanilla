"""Owner and editor rules of CUPCAKE Red Velvet protocols and sessions."""

from django.db.models import Q

from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

from ccc.models import LabGroup
from ccc.permissions import IsOwnerEditorViewerOrNoAccess
from ccm.models import InstrumentJob


def is_staff_or_superuser(user):
    """Whether the user is a Django staff user or superuser."""
    return user.is_staff or user.is_superuser


def is_owner_or_editor(resource, user):
    """Whether the user owns the protocol or session, is one of its editors, or is staff or a superuser."""
    if is_staff_or_superuser(user):
        return True
    return resource.owner_id == user.pk or resource.editors.filter(pk=user.pk).exists()


def is_rater(rating, user):
    """Whether the user gave the rating, or is staff or a superuser."""
    return rating.user_id == user.pk or is_staff_or_superuser(user)


def require_owner_or_editor(resource, user):
    """Raise PermissionDenied unless the user owns the protocol or session or is one of its editors."""
    if resource is not None and not is_owner_or_editor(resource, user):
        raise PermissionDenied("Only the owner or an editor can change this")


def session_member_q(user, prefix=""):
    """Protocols in sessions the user owns, edits or views."""
    return (
        Q(**{f"{prefix}sessions__owner": user})
        | Q(**{f"{prefix}sessions__editors": user})
        | Q(**{f"{prefix}sessions__viewers": user})
    )


def protocol_viewer_q(user, prefix="", include_public_sessions=False):
    """Protocols the user can view: owner, editors, viewers, lab group and session members, and public sessions the user unlocked when asked."""
    viewer_q = (
        Q(**{f"{prefix}owner": user})
        | Q(**{f"{prefix}editors": user})
        | Q(**{f"{prefix}viewers": user})
        | Q(**{f"{prefix}lab_group_id__in": LabGroup.get_accessible_group_ids(user)})
        | session_member_q(user, prefix)
    )
    if include_public_sessions:
        viewer_q |= Q(**{f"{prefix}sessions__enabled": True, f"{prefix}sessions__link_unlocked_by": user})
    return viewer_q


def protocol_visible_to(protocol, user):
    """Whether the user can view the protocol: staff, superusers, owner, editors, viewers, lab group and session members."""
    if is_staff_or_superuser(user) or protocol.owner_id == user.pk:
        return True
    if protocol.editors.filter(pk=user.pk).exists() or protocol.viewers.filter(pk=user.pk).exists():
        return True
    if protocol.lab_group_id in LabGroup.get_accessible_group_ids(user):
        return True
    return protocol.sessions.filter(Q(owner=user) | Q(editors=user) | Q(viewers=user)).exists()


def is_session_member(session, user):
    """Whether the user owns, edits or views the session, or is staff or a superuser."""
    if is_owner_or_editor(session, user):
        return True
    return session.viewers.filter(pk=user.pk).exists()


class ProtocolAccessPermission(IsOwnerEditorViewerOrNoAccess):
    """Reads need view access to the protocol or a public session using it that the user unlocked; changes follow owner and editor roles."""

    def has_object_permission(self, request, view, obj):
        """Read access for everyone who can view the protocol or an unlocked public session using it."""
        if request.method in permissions.SAFE_METHODS:
            user = request.user
            return protocol_visible_to(obj, user) or obj.sessions.filter(enabled=True, link_unlocked_by=user).exists()
        return super().has_object_permission(request, view, obj)


class SessionAccessPermission(IsOwnerEditorViewerOrNoAccess):
    """Session members read everything; unlocked public sessions are read through the view's public_actions."""

    def has_object_permission(self, request, view, obj):
        """Read access for session members, and for users who unlocked a public session, on its public actions."""
        if request.method in permissions.SAFE_METHODS:
            if is_session_member(obj, request.user):
                return True
            return obj.unlocked_by_link(request.user) and view.action in view.public_actions
        return super().has_object_permission(request, view, obj)


def session_viewer_q(user, prefix="session__"):
    """Rows whose session the user owns, edits or views."""
    return Q(**{f"{prefix}owner": user}) | Q(**{f"{prefix}editors": user}) | Q(**{f"{prefix}viewers": user})


def visible_through_session(queryset, user, prefix="session__", include_public=False):
    """Rows whose session the user can view: staff, superusers, owner, editors, viewers, and public sessions the user unlocked when asked."""
    if is_staff_or_superuser(user):
        return queryset
    viewer_q = session_viewer_q(user, prefix)
    if include_public:
        viewer_q |= Q(**{f"{prefix}enabled": True, f"{prefix}link_unlocked_by": user})
    return queryset.filter(viewer_q).distinct()


def asks_for_one(view, *params):
    """Whether the request is for one object, or a list narrowed by one of the given query parameters."""
    if view.detail:
        return True
    return any(view.request.query_params.get(param) for param in params)


def booking_viewer_q(user, prefix="instrument_usage__"):
    """Bookings the user can see: the booker, the instrument's owner and viewers, and staff and lab group of its jobs."""
    my_lab_groups = LabGroup.objects.filter(Q(members=user) | Q(creator=user)).values("id")
    job_bookings = InstrumentJob.objects.filter(
        Q(staff=user) | (Q(lab_group_id__in=my_lab_groups) & ~Q(status="draft"))
    ).values("instrument_usage_id")
    return (
        Q(**{f"{prefix}user": user})
        | Q(**{f"{prefix}instrument__user": user})
        | Q(
            **{
                f"{prefix}instrument__instrument_permissions__user": user,
                f"{prefix}instrument__instrument_permissions__can_view": True,
            }
        )
        | Q(**{f"{prefix}id__in": job_bookings})
    )


def visible_booking_links(queryset, user, session_prefix):
    """Booking links of sessions the user can view, and links to bookings the user can see under their own rules."""
    if is_staff_or_superuser(user):
        return queryset
    return queryset.filter(session_viewer_q(user, session_prefix) | booking_viewer_q(user)).distinct()


class ModelEditDeletePermission(permissions.BasePermission):
    """Changes need the object's can_edit, deletions its can_delete."""

    def has_object_permission(self, request, view, obj):
        """Reads are left to the queryset."""
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.method == "DELETE":
            return obj.can_delete(request.user)
        return obj.can_edit(request.user)


class OwnerOrEditorWritePermission(permissions.BasePermission):
    """Changes need the owner or an editor of the protocol or session returned by the view's resource_of."""

    def has_object_permission(self, request, view, obj):
        """Reads are left to the queryset; writes need the owner or an editor."""
        if request.method in permissions.SAFE_METHODS:
            return True
        return is_owner_or_editor(view.resource_of(obj), request.user)
