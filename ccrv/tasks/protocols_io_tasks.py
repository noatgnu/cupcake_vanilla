"""
Export of Cupcake protocols to protocols.io in the background.
"""

import logging
import traceback
from dataclasses import asdict

from django.contrib.auth import get_user_model

from choux import ChouxError, DraftValidationError
from django_rq import job

from ccc.models import AsyncTaskStatus
from ccrv.models import ProtocolModel, ProtocolsIOExport, Session
from ccrv.protocols_io import export_protocol
from ccrv.protocols_io.accounts import ProtocolsIOAccountMissing, client_for
from ccrv.protocols_io.session_export import SessionExportError, export_session_protocols

logger = logging.getLogger(__name__)


def _failure_message(error: Exception) -> str:
    if isinstance(error, DraftValidationError):
        return "Step content could not be converted: " + "; ".join(
            f"{issue.path}: {issue.message}" for issue in error.issues if issue.is_error
        )
    if isinstance(error, ProtocolsIOAccountMissing):
        return "Connect a protocols.io account before exporting"
    if isinstance(error, SessionExportError):
        return str(error)
    if "SUBSCRIPTION_LIMIT" in str(error):
        return "protocols.io refused to create another run because the account has reached the run limit of its plan"
    return f"protocols.io export failed: {error}"


@job("default", timeout=1800)
def export_protocol_to_protocols_io_task(
    protocol_id: int, user_id: int, target: str, task_id: str, scaling_factor: float = 1.0
) -> dict:
    """
    Export a Cupcake protocol into an existing protocols.io protocol with the user's own account.

    Args:
        protocol_id: Id of the Cupcake protocol.
        user_id: Id of the user whose protocols.io account is used.
        target: Id, URI or GUID of the protocols.io protocol.
        task_id: Id of the :class:`ccc.models.AsyncTaskStatus` tracking the export.
        scaling_factor: Extra factor applied to scaled quantities of scalable reagents.

    Returns:
        The export result, also stored on the task status.
    """
    task = AsyncTaskStatus.objects.get(id=task_id)
    task.mark_started()
    try:
        protocol = ProtocolModel.objects.get(pk=protocol_id)
        user = get_user_model().objects.get(pk=user_id)
        with client_for(user) as client:
            result = export_protocol(
                protocol,
                client,
                target,
                scaling_factor=scaling_factor,
                progress=lambda done, total, description: task.update_progress(done, total, description),
            )
        ProtocolsIOExport.remember(protocol, user, result)
    except (ChouxError, ProtocolsIOAccountMissing) as error:
        logger.warning("protocols.io export of protocol %s failed: %s", protocol_id, error)
        task.mark_failure(_failure_message(error), traceback.format_exc())
        return {"success": False, "error": task.error_message}
    except Exception as error:
        logger.exception("protocols.io export of protocol %s failed", protocol_id)
        task.mark_failure(f"protocols.io export failed: {error}", traceback.format_exc())
        return {"success": False, "error": task.error_message}
    outcome = {"success": True, **asdict(result)}
    task.mark_success(outcome)
    return outcome


@job("default", timeout=3600)
def export_session_to_protocols_io_task(
    session_id: int,
    protocol_ids: list[int],
    user_id: int,
    task_id: str,
    new_runs: bool = False,
    folder_guid: str | None = None,
    session_url: str = "",
) -> dict:
    """
    Export the step annotations of a session into protocols.io runs with the user's own account.

    Args:
        session_id: Id of the Cupcake session.
        protocol_ids: Ids of the session protocols to export, one run each, in run order.
        user_id: Id of the user whose protocols.io account is used.
        task_id: Id of the :class:`ccc.models.AsyncTaskStatus` tracking the export.
        new_runs: Create new runs even where the user exported the session before.
        folder_guid: File manager folder for new runs.
        session_url: Address of the session in Cupcake.

    Returns:
        The export result, also stored on the task status.
    """
    task = AsyncTaskStatus.objects.get(id=task_id)
    task.mark_started()
    try:
        session = Session.objects.get(pk=session_id)
        found = ProtocolModel.objects.in_bulk(protocol_ids)
        protocols = [found[protocol_id] for protocol_id in protocol_ids]
        user = get_user_model().objects.get(pk=user_id)
        with client_for(user) as client:
            results = export_session_protocols(
                session,
                protocols,
                client,
                user=user,
                new_runs=new_runs,
                folder_guid=folder_guid,
                session_url=session_url,
                progress=lambda done, total, description: task.update_progress(done, total, description),
            )
    except (ChouxError, ProtocolsIOAccountMissing, SessionExportError) as error:
        logger.warning("protocols.io export of session %s failed: %s", session_id, error)
        task.mark_failure(_failure_message(error), traceback.format_exc())
        return {"success": False, "error": task.error_message}
    except Exception as error:
        logger.exception("protocols.io export of session %s failed", session_id)
        task.mark_failure(f"protocols.io export failed: {error}", traceback.format_exc())
        return {"success": False, "error": task.error_message}
    outcome = {"success": True, "runs": [asdict(result) for result in results]}
    task.mark_success(outcome)
    return outcome
