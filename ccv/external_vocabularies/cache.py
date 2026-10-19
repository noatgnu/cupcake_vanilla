"""Local cache of external vocabulary terms."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from choux import ChouxError

from ccv.external_vocabularies.base import ExternalTermData, ExternalVocabularySource, sources

logger = logging.getLogger(__name__)

UPDATED_FIELDS = ["name", "description", "synonyms", "data", "fetched_at"]


def _term_model():
    return apps.get_model("ccv", "ExternalTerm")


def _term_digest(term: str) -> str:
    return hashlib.sha1(term.strip().casefold().encode("utf-8")).hexdigest()


def _search_cache_key(source: ExternalVocabularySource, term: str) -> str:
    return f"ccv:external-vocabulary:{source.key}:{_term_digest(term)}"


def pending_cache_key(source: ExternalVocabularySource, term: str) -> str:
    """Return the cache key marking a queued platform search for ``term``."""
    return f"ccv:external-vocabulary-pending:{source.key}:{_term_digest(term)}"


def _waiting_cache_key(source: ExternalVocabularySource, term: str) -> str:
    return f"ccv:external-vocabulary-waiting:{source.key}:{_term_digest(term)}"


def recently_searched(source: ExternalVocabularySource, term: str) -> bool:
    """Return whether the platform was searched for ``term`` within the search TTL."""
    return bool(cache.get(_search_cache_key(source, term)))


def add_waiting_user(source: ExternalVocabularySource, term: str, user_id: int) -> None:
    """Remember a user to notify when the platform search for ``term`` finishes."""
    key = _waiting_cache_key(source, term)
    waiting = cache.get(key) or []
    if user_id not in waiting:
        waiting.append(user_id)
    cache.set(key, waiting, settings.EXTERNAL_VOCABULARY_PENDING_TTL)


def pop_waiting_users(source: ExternalVocabularySource, term: str) -> list[int]:
    """Return and forget the users waiting for the platform search for ``term``."""
    key = _waiting_cache_key(source, term)
    waiting = cache.get(key) or []
    cache.delete(key)
    return waiting


def store_terms(source: ExternalVocabularySource, terms: Iterable[ExternalTermData]) -> int:
    """
    Insert or update terms in the local cache.

    Args:
        source: Source the terms come from.
        terms: Terms to store.

    Returns:
        Number of terms stored.
    """
    model = _term_model()
    now = timezone.now()
    rows = {
        term.external_id: model(
            platform=source.platform,
            kind=source.kind,
            external_id=term.external_id,
            name=term.name,
            description=term.description,
            synonyms=";".join(term.synonyms),
            data=term.data,
            fetched_at=now,
        )
        for term in terms
        if term.external_id and term.name
    }
    if not rows:
        return 0
    model.objects.bulk_create(
        list(rows.values()),
        update_conflicts=True,
        unique_fields=["platform", "kind", "external_id"],
        update_fields=UPDATED_FIELDS,
    )
    return len(rows)


def refresh_from_platform(source_key: str, term: str) -> int:
    """
    Search the platform for ``term`` and store the results, unless that search ran recently.

    Failures are logged and leave the cache unchanged. The queued marker for ``term`` is cleared
    in every case.

    Args:
        source_key: Key of the source.
        term: Search text from the user.

    Returns:
        Number of terms stored by this call.
    """
    source = sources.get(source_key)
    if source is None or not source.searchable or not source.is_configured():
        return 0
    text = term.strip()
    if len(text) < source.min_term_length:
        return 0
    cache_key = _search_cache_key(source, text)
    try:
        if cache.get(cache_key):
            return 0
        try:
            found = source.search(text, source.page_size)
        except ChouxError as error:
            logger.warning("External vocabulary search %s for %r failed: %s", source.key, text, error)
            cache.set(cache_key, True, settings.EXTERNAL_VOCABULARY_FAILURE_TTL)
            return 0
        stored = store_terms(source, found)
        cache.set(cache_key, True, settings.EXTERNAL_VOCABULARY_SEARCH_TTL)
        return stored
    finally:
        cache.delete(pending_cache_key(source, text))
