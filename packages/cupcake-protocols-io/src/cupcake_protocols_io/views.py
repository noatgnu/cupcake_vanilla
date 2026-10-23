"""API endpoints for protocols.io accounts, browsing, imports and exports."""

import logging

from django.db.models import Count, Q

from choux import APIError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ccc.models import AsyncTaskStatus, LabGroup
from ccc.permissions import IsOwnerEditorViewerOrNoAccess
from ccrv.models import ProtocolModel, Session, StepVariation
from ccrv.serializers import ProtocolModelSerializer
from cupcake_protocols_io import browser
from cupcake_protocols_io.accounts import ProtocolsIOAccountMissing, client_for, connect_account, disconnect_account
from cupcake_protocols_io.exporter import protocol_reference
from cupcake_protocols_io.importer import import_protocol, import_protocol_from_url
from cupcake_protocols_io.models import ProtocolsIOAccount
from cupcake_protocols_io.serializers import (
    ProtocolsIOAccountSerializer,
    ProtocolsIOConnectSerializer,
    ProtocolsIOExportSerializer,
    ProtocolsIORunSerializer,
)
from cupcake_protocols_io.session_export import session_variations, variation_hash
from cupcake_protocols_io.tasks import export_protocol_to_protocols_io_task, export_session_to_protocols_io_task

logger = logging.getLogger(__name__)


def visible_to(queryset, user):
    """
    Limit a queryset of Cupcake resources to those the user owns, edits, views or reaches through a lab group.

    Args:
        queryset: Queryset of a model with ``owner``, ``editors``, ``viewers`` and ``lab_group``.
        user: The requesting user.
    """
    if user.is_superuser:
        return queryset
    accessible_groups = LabGroup.get_accessible_group_ids(user)
    return queryset.filter(
        Q(owner=user) | Q(editors=user) | Q(viewers=user) | Q(lab_group_id__in=accessible_groups)
    ).distinct()


class ProtocolsIOProtocolViewSet(viewsets.GenericViewSet):
    """Import Cupcake protocols from protocols.io and export them into protocols.io protocols."""

    queryset = ProtocolModel.objects.all()
    permission_classes = [IsAuthenticated, IsOwnerEditorViewerOrNoAccess]

    def get_queryset(self):
        """Return the protocols the user can see."""
        return visible_to(self.queryset, self.request.user)

    def created(self, protocol):
        """Return the representation of an imported protocol."""
        return ProtocolModelSerializer(protocol, context=self.get_serializer_context()).data

    @action(detail=False, methods=["post"], url_path="import")
    def import_protocol(self, request):
        """
        Import a protocol from a protocols.io address or DOI link.

        Uses the user's own protocols.io account when one is connected, and the server's token otherwise.
        """
        url = request.data.get("url")
        if not url:
            return Response({"error": "URL is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if ProtocolsIOAccount.objects.filter(user=request.user).exists():
                with client_for(request.user) as client:
                    protocol = import_protocol_from_url(url, client=client)
            else:
                protocol = import_protocol_from_url(url)
        except ValueError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        except APIError as error:
            return Response(
                {"error": "protocols.io request failed", "detail": str(error)}, status=status.HTTP_502_BAD_GATEWAY
            )
        except Exception as error:
            logger.exception("protocols.io import from %s failed", url)
            return Response(
                {"error": f"Failed to import protocol: {error}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        protocol.owner = request.user
        protocol.save()
        return Response(self.created(protocol), status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def import_from_account(self, request):
        """
        Import a protocol from protocols.io with the user's own account.

        Body: ``protocol``, the address, URI or id of a protocols.io protocol the user can open.
        """
        reference = protocol_reference(str(request.data.get("protocol") or ""))
        if not reference:
            return Response({"error": "protocol is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            with client_for(request.user) as client:
                data = client.get_protocol_v3(reference)
        except ProtocolsIOAccountMissing:
            return Response({"error": "Connect a protocols.io account first"}, status=status.HTTP_400_BAD_REQUEST)
        except APIError as error:
            return Response(
                {"error": "protocols.io request failed", "detail": str(error)}, status=status.HTTP_502_BAD_GATEWAY
            )
        if data.get("type_id") not in (None, 1):
            return Response({"error": "Only protocols can be imported"}, status=status.HTTP_400_BAD_REQUEST)
        url = data.get("url") or f"https://www.protocols.io/view/{data.get('uri') or reference}"
        protocol = import_protocol(data, url)
        protocol.owner = request.user
        protocol.save()
        return Response(self.created(protocol), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def export(self, request, pk=None):
        """
        Queue an export of this protocol into an existing protocols.io protocol with the user's own account.

        Body: ``target``, the address, URI, id or GUID of the protocols.io protocol, and optionally
        ``scaling_factor`` for scalable reagents.
        """
        protocol = self.get_object()
        target = protocol_reference(str(request.data.get("target") or ""))
        if not target:
            return Response({"error": "target is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            scaling_factor = float(request.data.get("scaling_factor", 1.0))
        except (TypeError, ValueError):
            return Response({"error": "scaling_factor must be a number"}, status=status.HTTP_400_BAD_REQUEST)
        if not ProtocolsIOAccount.objects.filter(user=request.user).exists():
            return Response({"error": "Connect a protocols.io account first"}, status=status.HTTP_400_BAD_REQUEST)
        task = AsyncTaskStatus.objects.create(
            task_type="EXPORT_PROTOCOLS_IO",
            user=request.user,
            parameters={"protocol_id": protocol.id, "target": target, "scaling_factor": scaling_factor},
        )
        job = export_protocol_to_protocols_io_task.delay(
            protocol.id, request.user.id, target, str(task.id), scaling_factor
        )
        if job:
            task.rq_job_id = job.id
            task.save(update_fields=["rq_job_id"])
        return Response(
            {"task_id": str(task.id), "message": "protocols.io export queued"}, status=status.HTTP_202_ACCEPTED
        )

    @action(detail=True, methods=["get"])
    def exports(self, request, pk=None):
        """List the protocols.io protocols this protocol was exported into, most recent first."""
        protocol = self.get_object()
        exports = protocol.protocols_io_exports.select_related("exported_by")
        return Response(ProtocolsIOExportSerializer(exports, many=True).data)


class ProtocolsIOSessionViewSet(viewsets.GenericViewSet):
    """Export Cupcake sessions into protocols.io runs."""

    queryset = Session.objects.all()
    permission_classes = [IsAuthenticated, IsOwnerEditorViewerOrNoAccess]

    def get_queryset(self):
        """Return the sessions the user can see."""
        return visible_to(self.queryset, self.request.user)

    @action(detail=True, methods=["post"])
    def export(self, request, pk=None):
        """
        Queue an export of the step annotations of this session into protocols.io runs, one for each protocol.

        Body, all optional: ``protocols``, ids of session protocols to export, every protocol of the
        session when omitted; ``new_runs``, create new runs instead of updating the runs the user
        exported before; ``folder``, the GUID of the protocols.io folder for new runs; and
        ``session_url``, the address of the session in Cupcake.
        """
        session = self.get_object()
        session_protocols = {protocol.pk: protocol for protocol in session.protocols.all()}
        requested = request.data.get("protocols")
        if requested is None:
            protocols = list(session_protocols.values())
        elif isinstance(requested, list):
            try:
                protocols = [session_protocols[int(protocol_id)] for protocol_id in requested]
            except (KeyError, TypeError, ValueError):
                protocols = []
        else:
            protocols = []
        if not protocols:
            return Response(
                {"error": "protocols must list protocols of this session"}, status=status.HTTP_400_BAD_REQUEST
            )
        session_url = str(request.data.get("session_url") or "").strip()
        if session_url and not session_url.startswith(("https://", "http://")):
            return Response({"error": "session_url must be a web address"}, status=status.HTTP_400_BAD_REQUEST)
        folder = str(request.data.get("folder") or "").strip() or None
        new_runs = request.data.get("new_runs") in (True, "true", "1", 1)
        if not ProtocolsIOAccount.objects.filter(user=request.user).exists():
            return Response({"error": "Connect a protocols.io account first"}, status=status.HTTP_400_BAD_REQUEST)
        varied = set(
            StepVariation.objects.filter(session=session, step__protocol__in=protocols).values_list(
                "step__protocol_id", flat=True
            )
        )
        missing = [
            protocol.protocol_title
            for protocol in protocols
            if protocol.pk not in varied and not protocol.protocols_io_exports.filter(session__isnull=True).exists()
        ]
        if missing:
            return Response(
                {
                    "error": "Export these protocols to protocols.io first: " + ", ".join(missing),
                    "protocols_not_exported": missing,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        protocol_ids = [protocol.pk for protocol in protocols]
        task = AsyncTaskStatus.objects.create(
            task_type="EXPORT_RUN_PROTOCOLS_IO",
            user=request.user,
            parameters={"session_id": session.id, "protocol_ids": protocol_ids, "new_runs": new_runs, "folder": folder},
        )
        job = export_session_to_protocols_io_task.delay(
            session.id, protocol_ids, request.user.id, str(task.id), new_runs, folder, session_url
        )
        if job:
            task.rq_job_id = job.id
            task.save(update_fields=["rq_job_id"])
        return Response(
            {"task_id": str(task.id), "message": "protocols.io session export queued"}, status=status.HTTP_202_ACCEPTED
        )

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        """
        Describe how each protocol of this session would be exported to protocols.io by the current user.

        Each entry has the protocol, its latest export that follows the protocol's own steps, the
        number of steps this session varied, and the user's latest run of it with whether that run
        still matches the variations.
        """
        session = self.get_object()
        entries = []
        for protocol in session.protocols.all():
            variations = session_variations(session, protocol)
            export = protocol.protocols_io_exports.filter(session__isnull=True).first()
            run = (
                session.protocols_io_runs.filter(protocol=protocol, exported_by=request.user)
                .select_related("protocol", "exported_by")
                .annotate(comment_count=Count("comments"))
                .first()
            )
            entries.append(
                {
                    "protocol": protocol.pk,
                    "protocol_title": protocol.protocol_title,
                    "protocol_export": ProtocolsIOExportSerializer(export).data if export else None,
                    "varied_steps": len(variations),
                    "run": ProtocolsIORunSerializer(run).data if run else None,
                    "run_is_current": run is not None and run.variation_hash == variation_hash(variations),
                }
            )
        return Response(entries)

    @action(detail=True, methods=["get"])
    def runs(self, request, pk=None):
        """List the protocols.io runs this session was exported into, most recent first."""
        session = self.get_object()
        runs = session.protocols_io_runs.select_related("protocol", "exported_by").annotate(
            comment_count=Count("comments")
        )
        return Response(ProtocolsIORunSerializer(runs, many=True).data)


class ProtocolsIOAccountViewSet(viewsets.ViewSet):
    """Connect, inspect and disconnect the requesting user's protocols.io account."""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        """Return whether the user has a connected account and which one."""
        account = ProtocolsIOAccount.objects.filter(user=request.user).first()
        if account is None:
            return Response({"connected": False})
        return Response({"connected": True, **ProtocolsIOAccountSerializer(account).data})

    def create(self, request):
        """Check a protocols.io access token and save it for the user."""
        serializer = ProtocolsIOConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            account = connect_account(request.user, serializer.validated_data["access_token"])
        except APIError as error:
            return Response(
                {"error": "protocols.io did not accept this token", "detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"connected": True, **ProtocolsIOAccountSerializer(account).data}, status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["delete"])
    def disconnect(self, request):
        """Remove the user's saved protocols.io account."""
        disconnect_account(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProtocolsIOBrowseViewSet(viewsets.ViewSet):
    """Browse the requesting user's protocols.io workspaces, folders and protocols with their own account."""

    permission_classes = [IsAuthenticated]

    def _respond(self, request, fetch):
        try:
            page = int(request.query_params.get("page", 1))
        except (TypeError, ValueError):
            return Response({"error": "page must be a number"}, status=status.HTTP_400_BAD_REQUEST)
        if page < 1:
            return Response({"error": "page must be 1 or more"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            with client_for(request.user) as client:
                return Response(fetch(client, page))
        except ProtocolsIOAccountMissing:
            return Response({"error": "Connect a protocols.io account first"}, status=status.HTTP_400_BAD_REQUEST)
        except APIError as error:
            return Response(
                {"error": "protocols.io request failed", "detail": str(error)}, status=status.HTTP_502_BAD_GATEWAY
            )

    @action(detail=False, methods=["get"])
    def workspaces(self, request):
        """List the workspaces the user is a member of."""
        return self._respond(request, browser.list_workspaces)

    @action(detail=False, methods=["get"])
    def workspace_items(self, request):
        """List the top-level folders of the workspace given by ``workspace``."""
        workspace = (request.query_params.get("workspace") or "").strip()
        if not workspace:
            return Response({"error": "workspace is required"}, status=status.HTTP_400_BAD_REQUEST)
        return self._respond(request, lambda client, page: browser.workspace_folders(client, workspace, page))

    @action(detail=False, methods=["get"])
    def folder_items(self, request):
        """List the folders and protocols in the folder given by ``folder``."""
        folder = (request.query_params.get("folder") or "").strip()
        if not folder:
            return Response({"error": "folder is required"}, status=status.HTTP_400_BAD_REQUEST)
        return self._respond(request, lambda client, page: browser.folder_items(client, folder, page))

    @action(detail=False, methods=["get"])
    def search(self, request):
        """Search protocols in every workspace the user can see for the text given by ``q``."""
        text = (request.query_params.get("q") or "").strip()
        if not text:
            return Response({"error": "q is required"}, status=status.HTTP_400_BAD_REQUEST)
        return self._respond(request, lambda client, page: browser.search_protocols(client, text, page))
