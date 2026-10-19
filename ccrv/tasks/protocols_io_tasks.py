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
from ccrv.models import ProtocolModel
from ccrv.protocols_io import export_protocol
from ccrv.protocols_io.accounts import ProtocolsIOAccountMissing, client_for

logger = logging.getLogger(__name__)


def _failure_message(error: Exception) -> str:
    if isinstance(error, DraftValidationError):
        return "Step content could not be converted: " + "; ".join(
            f"{issue.path}: {issue.message}" for issue in error.issues if issue.is_error
        )
    if isinstance(error, ProtocolsIOAccountMissing):
        return "Connect a protocols.io account before exporting"
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
