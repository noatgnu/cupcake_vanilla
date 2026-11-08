"""Storing imported terms in the vocabulary terms table."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from ccv.models import DataSourceVersion, Vocabulary, VocabularyTerm
from ccv.vocabularies.importers import ImportedTerm

BATCH_SIZE = 1000
UPDATED_FIELDS = ["name", "description", "synonyms", "data", "obsolete", "fetched_at"]


def store_term_batch(vocabulary: Vocabulary, terms: Iterable[ImportedTerm], fetched_at: datetime) -> int:
    """
    Insert or update one batch of terms of a vocabulary in its own transaction.

    Args:
        vocabulary: The vocabulary the terms belong to.
        terms: Terms to store; later duplicates of an id replace earlier ones.
        fetched_at: Time recorded on every stored term.

    Returns:
        The number of distinct terms stored.
    """
    batch: dict[str, VocabularyTerm] = {}
    for term in terms:
        external_id = term.external_id[:255]
        batch[external_id] = VocabularyTerm(
            vocabulary=vocabulary,
            external_id=external_id,
            name=term.name,
            description=term.description,
            synonyms=";".join(term.synonyms),
            data=term.data,
            obsolete=term.obsolete,
            fetched_at=fetched_at,
        )
    if batch:
        with transaction.atomic():
            VocabularyTerm.objects.bulk_create(
                list(batch.values()),
                update_conflicts=True,
                unique_fields=["vocabulary", "external_id"],
                update_fields=UPDATED_FIELDS,
            )
    return len(batch)


def finish_load(
    vocabulary: Vocabulary, *, replace_before: datetime | None = None, version: str = "", source: str = ""
) -> int:
    """
    Record a finished load on the vocabulary and make it active.

    Args:
        vocabulary: The vocabulary that was loaded.
        replace_before: Remove the terms last stored before this time.
        version: Data version of the source.
        source: Name of the file or source the terms came from.

    Returns:
        The number of removed terms.
    """
    now = timezone.now()
    with transaction.atomic():
        removed = 0
        if replace_before is not None:
            removed, _ = vocabulary.terms.filter(fetched_at__lt=replace_before).delete()
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
    return removed


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
    batch: list[ImportedTerm] = []

    def flush():
        nonlocal stored
        if not batch:
            return
        stored += store_term_batch(vocabulary, batch, now)
        batch.clear()
        if on_progress:
            on_progress(stored)

    for term in terms:
        batch.append(term)
        if len(batch) >= BATCH_SIZE:
            flush()
    flush()

    removed = finish_load(vocabulary, replace_before=now if replace else None, version=version, source=source)
    return {"stored": stored, "removed": removed, "term_count": vocabulary.term_count}
