"""Background refresh of external vocabularies and notification of the user who searched."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache

from django_rq import job
from redis.exceptions import RedisError

from ccc.notification_service import BaseNotificationService
from ccv.external_vocabularies.base import sources
from ccv.external_vocabularies.cache import (
    add_waiting_user,
    pending_cache_key,
    pop_waiting_users,
    recently_searched,
    refresh_from_platform,
)
from ccv.ontology_registry import registry

logger = logging.getLogger(__name__)

UPDATE_MESSAGE_TYPE = "external_vocabulary.updated"


@job("high", timeout=120)
def refresh_external_vocabulary_task(source_key: str, term: str) -> int:
    """
    Search the platform for ``term``, store the results and tell every user waiting for them.

    Args:
        source_key: Key of the source, which is also its ontology type.
        term: Search text from the user.

    Returns:
        Number of terms stored.
    """
    stored = refresh_from_platform(source_key, term)
    source = sources.get(source_key)
    if source is None:
        return stored
    notifier = BaseNotificationService()
    for user_id in pop_waiting_users(source, term):
        notifier.notify_user(
            user_id,
            UPDATE_MESSAGE_TYPE,
            f"{stored} new result(s) for {term!r}",
            ontology_type=source_key,
            search_term=term,
            stored=stored,
        )
    return stored


def request_refresh(ontology_type: str | None, term: str, *, user_id: int | None = None) -> bool:
    """
    Queue a platform search for an ontology type backed by a searchable external platform.

    At most one search per source and term is queued at a time, and a term searched within
    ``EXTERNAL_VOCABULARY_SEARCH_TTL`` is not searched again.

    Args:
        ontology_type: Ontology type the user is searching.
        term: Search text from the user.
        user_id: User to notify when the results are stored.

    Returns:
        Whether results from the platform are still to come for this search.
    """
    descriptor = registry.get(ontology_type) if ontology_type else None
    if descriptor is None or not descriptor.remote_source:
        return False
    source = sources.get(descriptor.remote_source)
    text = (term or "").strip()
    if source is None or not source.searchable or not source.is_configured() or len(text) < source.min_term_length:
        return False
    if recently_searched(source, text):
        return False
    if user_id is not None:
        add_waiting_user(source, text, user_id)
    pending_key = pending_cache_key(source, text)
    if not cache.add(pending_key, True, settings.EXTERNAL_VOCABULARY_PENDING_TTL):
        return True
    try:
        refresh_external_vocabulary_task.delay(source.key, text)
    except RedisError as error:
        cache.delete(pending_key)
        pop_waiting_users(source, text)
        logger.warning("Could not queue external vocabulary search %s for %r: %s", source.key, text, error)
        return False
    return True
