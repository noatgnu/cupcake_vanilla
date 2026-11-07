"""Storing imported terms in the vocabulary terms table."""

from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction
from django.utils import timezone

from ccv.models import DataSourceVersion, Vocabulary, VocabularyTerm
from ccv.vocabularies.importers import ImportedTerm

BATCH_SIZE = 1000
UPDATED_FIELDS = ["name", "description", "synonyms", "data", "obsolete", "fetched_at"]


def store_imported_terms(
    vocabulary: Vocabulary,
    terms: Iterable[ImportedTerm],
    *,
    replace: bool = False,
    version: str = "",
    source: str = "",
    on_progress=None,
) -> dict:
    """
    Insert or update terms of a vocabulary in batches, then record the load on the vocabulary.

    Each batch is committed on its own; the removal of terms missing from the file and the record of the
    load are committed together after the last batch.

    Args:
        vocabulary: The vocabulary the terms belong to.
        terms: Terms to store; later duplicates of an id replace earlier ones.
        replace: Remove the vocabulary's terms that are not in ``terms``.
        version: Data version the file declares.
        source: Name of the file the terms came from.
        on_progress: Called with the number of terms stored so far after each batch.

    Returns:
        Counts of stored and removed terms and the new total.
    """
    now = timezone.now()
    stored = 0
    batch: dict[str, VocabularyTerm] = {}

    def flush():
        nonlocal stored
        if not batch:
            return
        with transaction.atomic():
            VocabularyTerm.objects.bulk_create(
                list(batch.values()),
                update_conflicts=True,
                unique_fields=["vocabulary", "external_id"],
                update_fields=UPDATED_FIELDS,
            )
        stored += len(batch)
        batch.clear()
        if on_progress:
            on_progress(stored)

    for term in terms:
        batch[term.external_id] = VocabularyTerm(
            vocabulary=vocabulary,
            external_id=term.external_id[:255],
            name=term.name,
            description=term.description,
            synonyms=";".join(term.synonyms),
            data=term.data,
            obsolete=term.obsolete,
            fetched_at=now,
        )
        if len(batch) >= BATCH_SIZE:
            flush()
    flush()

    with transaction.atomic():
        removed = 0
        if replace:
            removed, _ = vocabulary.terms.filter(fetched_at__lt=now).delete()

        source_version, _ = DataSourceVersion.objects.update_or_create(
            key=f"vocabulary:{vocabulary.key}"[:100],
            defaults={"source_url": source, "version": version, "retrieved_at": now},
        )
        vocabulary.term_count = vocabulary.terms.count()
        vocabulary.last_loaded_at = now
        vocabulary.last_error = ""
        vocabulary.status = Vocabulary.STATUS_ACTIVE
        vocabulary.source_version = source_version
        vocabulary.save(
            update_fields=["term_count", "last_loaded_at", "last_error", "status", "source_version", "updated_at"]
        )
    return {"stored": stored, "removed": removed, "term_count": vocabulary.term_count}
