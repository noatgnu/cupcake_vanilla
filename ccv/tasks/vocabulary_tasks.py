"""Background import of vocabulary files."""

import logging
import traceback
from pathlib import Path

from django_rq import job

from ccc.models import AsyncTaskStatus
from ccv.models import Vocabulary
from ccv.vocabularies.importers import ColumnMapping, VocabularyFileError, read_vocabulary_file
from ccv.vocabularies.store import store_imported_terms

logger = logging.getLogger(__name__)


@job("default", timeout=3600)
def import_vocabulary_task(
    vocabulary_id: int,
    file_path: str,
    file_format: str,
    file_name: str,
    replace: bool = False,
    mapping: dict | None = None,
    task_id: str | None = None,
) -> dict:
    """
    Read a vocabulary file, store its terms and record the result on the vocabulary and its task.

    Args:
        vocabulary_id: The vocabulary the terms belong to.
        file_path: Uploaded file, deleted when the import ends.
        file_format: One of obo, owl, csv or tsv.
        file_name: Name the file was uploaded with.
        replace: Remove the vocabulary's terms that are not in the file.
        mapping: CSV and TSV column mapping.
        task_id: Task to report progress and the result on.

    Returns:
        Counts of stored and removed terms and the new total.
    """
    task = AsyncTaskStatus.objects.filter(id=task_id).first() if task_id else None
    vocabulary = Vocabulary.objects.get(id=vocabulary_id)
    path = Path(file_path)
    try:
        if task:
            task.mark_started()
        version, terms = read_vocabulary_file(path, file_format, ColumnMapping(**mapping) if mapping else None)

        def report(stored):
            if task:
                task.update_progress(stored, description=f"Stored {stored} terms")

        result = store_imported_terms(
            vocabulary, terms, replace=replace, version=version, source=file_name, on_progress=report
        )
        if task:
            task.mark_success(result)
        return result
    except Exception as error:
        message = str(error) if isinstance(error, VocabularyFileError) else f"Import failed: {error}"
        logger.warning("Importing %s into vocabulary %s failed: %s", file_name, vocabulary.key, error)
        Vocabulary.objects.filter(id=vocabulary_id).update(status=Vocabulary.STATUS_ACTIVE, last_error=message)
        if task:
            task.mark_failure(message, traceback.format_exc())
        return {"error": message}
    finally:
        path.unlink(missing_ok=True)
