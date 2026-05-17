"""
RQ tasks for CUPCAKE Core (CCC).
"""

import logging
import shutil
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.utils import timezone

from django_rq import job

from ccc.models import SiteConfig

logger = logging.getLogger(__name__)


@job("default", timeout="30m")
def run_management_command_async(execution_id):
    """
    Run a management command asynchronously.

    Args:
        execution_id: UUID of the ManagementCommandExecution record
    """
    from ccc.models import ManagementCommandExecution

    try:
        execution = ManagementCommandExecution.objects.get(id=execution_id)
    except ManagementCommandExecution.DoesNotExist:
        logger.error(f"ManagementCommandExecution {execution_id} not found")
        return {"status": "error", "error": "Execution record not found"}

    execution.status = "RUNNING"
    execution.started_at = timezone.now()
    execution.save(update_fields=["status", "started_at"])

    stdout = StringIO()
    stderr = StringIO()

    try:
        call_command(execution.command_name, stdout=stdout, stderr=stderr, **execution.command_args)
        execution.output = stdout.getvalue()
        execution.error_message = stderr.getvalue()
        execution.status = "SUCCESS"
        logger.info(f"Command {execution.command_name} completed successfully")
    except Exception as e:
        execution.error_message = f"{stderr.getvalue()}\n\nException: {str(e)}"
        execution.status = "FAILURE"
        logger.exception(f"Command {execution.command_name} failed")
    finally:
        execution.completed_at = timezone.now()
        execution.save(update_fields=["output", "error_message", "status", "completed_at"])

    return {
        "status": execution.status,
        "command": execution.command_name,
        "duration": str(execution.duration) if execution.duration else None,
    }


@job("transcribe", timeout="5m")
def refresh_available_whisper_models():
    """
    Scan for available Whisper.cpp models and update cache.

    This job should be queued on the transcribe worker which has
    access to the model files.

    Returns:
        dict: Information about scanned models
    """
    try:
        models = SiteConfig.scan_available_whisper_models()

        site_config = SiteConfig.objects.first()
        if not site_config:
            site_config = SiteConfig.objects.create()

        site_config.cached_available_models = models
        site_config.save(update_fields=["cached_available_models"])

        logger.info(f"Successfully cached {len(models)} Whisper.cpp models")

        return {"status": "success", "models_count": len(models), "models": models}

    except Exception as e:
        logger.exception("Failed to refresh available Whisper.cpp models")
        return {"status": "error", "error": str(e)}


@job("default", timeout="2h")
def run_backup(backup_log_id):
    """
    Run a backup operation and copy the result to the specified destination.

    Args:
        backup_log_id: ID of the BackupLog record to update
    """
    from ccc.models import BackupLog

    BACKUP_DIR = Path("/opt/cupcake/backups")

    try:
        log = BackupLog.objects.get(id=backup_log_id)
    except BackupLog.DoesNotExist:
        logger.error(f"BackupLog {backup_log_id} not found")
        return

    try:
        destination = Path(log.destination)
        destination.mkdir(parents=True, exist_ok=True)

        stdout = StringIO()

        if log.backup_type in ("database", "full"):
            call_command("dbbackup", "--clean", stdout=stdout)

        if log.backup_type in ("media", "full"):
            call_command("mediabackup", "--clean", stdout=stdout)

        latest_files = sorted(BACKUP_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if log.backup_type == "full":
            files_to_copy = latest_files[:2]
        else:
            files_to_copy = latest_files[:1]

        total_size = 0
        for src in files_to_copy:
            dest_file = destination / src.name
            shutil.copy2(src, dest_file)
            total_size += dest_file.stat().st_size

        log.status = "completed"
        log.size_bytes = total_size
        log.completed_at = timezone.now()
        log.save(update_fields=["status", "size_bytes", "completed_at"])

    except Exception as e:
        logger.exception(f"Backup {backup_log_id} failed")
        log.status = "failed"
        log.error_message = str(e)
        log.completed_at = timezone.now()
        log.save(update_fields=["status", "error_message", "completed_at"])
