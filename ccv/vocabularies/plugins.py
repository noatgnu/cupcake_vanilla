"""Vocabularies declared by plugins in their manifest."""

from __future__ import annotations

import logging
import re

from ccc.plugin.model import Plugin
from ccv.models import Vocabulary

logger = logging.getLogger(__name__)

LOCAL_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,59}$")
KEY_MAX_LENGTH = Vocabulary._meta.get_field("key").max_length


def plugin_vocabulary_key(plugin: Plugin, local_key: str) -> str:
    """The ontology type key of a plugin's vocabulary: ``plugin.<plugin name>.<local key>``."""
    return f"plugin.{plugin.name}.{local_key}"


def declared_vocabularies(plugin: Plugin) -> dict[str, dict]:
    """
    The valid vocabulary entries of the plugin's manifest by local key.

    Each entry needs a ``key`` of lower-case letters, digits and underscores and a ``label``; entries that do not
    are logged and left out.
    """
    entries = (plugin.manifest_cache or {}).get("vocabularies") or []
    declared: dict[str, dict] = {}
    if not isinstance(entries, list):
        logger.warning("Plugin %s declares vocabularies that are not a list", plugin.name)
        return declared
    for entry in entries:
        local_key = entry.get("key", "") if isinstance(entry, dict) else ""
        if not LOCAL_KEY_PATTERN.match(str(local_key)) or not str(entry.get("label", "")).strip():
            logger.warning("Plugin %s declares an invalid vocabulary: %r", plugin.name, entry)
            continue
        if len(plugin_vocabulary_key(plugin, local_key)) > KEY_MAX_LENGTH:
            logger.warning("Plugin %s vocabulary key %s is too long", plugin.name, local_key)
            continue
        declared[local_key] = entry
    return declared


def sync_plugin_vocabularies(plugin: Plugin) -> None:
    """
    Create or update the plugin's vocabularies from its manifest and disable the ones it no longer declares.

    New vocabularies wait for staff approval; approval is kept when the manifest changes.
    """
    declared = declared_vocabularies(plugin)
    keys = set()
    for local_key, entry in declared.items():
        key = plugin_vocabulary_key(plugin, local_key)
        keys.add(key)
        details = {
            "label": str(entry["label"]).strip()[:255],
            "kind": str(entry.get("kind", "")).strip()[:50],
            "description": str(entry.get("description", "")).strip(),
            "sdrf_short_name": str(entry.get("sdrfShortName", entry.get("sdrf_short_name", ""))).strip()[:50],
        }
        min_term_length = entry.get("minTermLength", entry.get("min_term_length"))
        if isinstance(min_term_length, int) and 1 <= min_term_length <= 20:
            details["min_term_length"] = min_term_length
        vocabulary = Vocabulary.objects.filter(key=key).first()
        if vocabulary is None:
            Vocabulary.objects.create(
                key=key,
                provider=Vocabulary.PROVIDER_PLUGIN,
                storage=Vocabulary.STORAGE_TERMS,
                plugin=plugin,
                approved=False,
                status=Vocabulary.STATUS_LOADING,
                **details,
            )
            continue
        if vocabulary.plugin_id != plugin.id:
            logger.warning("Plugin %s declares vocabulary %s that belongs to another provider", plugin.name, key)
            continue
        for field, value in details.items():
            setattr(vocabulary, field, value)
        if vocabulary.status == Vocabulary.STATUS_DISABLED:
            vocabulary.status = Vocabulary.STATUS_ACTIVE if vocabulary.last_loaded_at else Vocabulary.STATUS_LOADING
        vocabulary.save()
    Vocabulary.objects.filter(plugin=plugin).exclude(key__in=keys).update(status=Vocabulary.STATUS_DISABLED)
