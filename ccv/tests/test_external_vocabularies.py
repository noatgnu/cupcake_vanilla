"""Tests for the external vocabulary registry and local term cache, with a source that needs no platform."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from ccv.external_vocabularies import (
    ExternalTermData,
    ExternalVocabularyError,
    ExternalVocabularySource,
    refresh_from_platform,
    sources,
    store_terms,
)
from ccv.external_vocabularies.base import SourceRegistry
from ccv.models import ExternalTerm
from ccv.ontology_registry import registry

LOCAL_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "external-vocab"}}


class ColourSource(ExternalVocabularySource):
    """Colours from a platform that answers from a fixed list or fails on request."""

    key = "test_colour"
    platform = "test_platform"
    kind = "colour"
    label = "Test colour"

    def __init__(self, failing=False):
        """Answer searches, or raise when ``failing`` is set."""
        self.failing = failing
        self.searched = []

    def is_configured(self):
        return True

    def search(self, term, limit):
        self.searched.append(term)
        if self.failing:
            raise ExternalVocabularyError("platform down")
        return [ExternalTermData("1", "Crimson", "A deep red", ("dark red",)), ExternalTermData("2", "Scarlet")]


class SourceRegistryTest(TestCase):
    def test_duplicate_keys_are_refused(self):
        registry_ = SourceRegistry()
        registry_.register(ColourSource())
        with self.assertRaises(ValueError):
            registry_.register(ColourSource())

    def test_default_search_and_load_are_not_supported(self):
        class Bare(ExternalVocabularySource):
            key = "bare"
            platform = "bare"
            kind = "thing"
            label = "Bare"

            def is_configured(self):
                return True

        with self.assertRaises(NotImplementedError):
            Bare().search("x", 5)
        with self.assertRaises(NotImplementedError):
            list(Bare().load_all())

    def test_listeners_see_earlier_and_later_sources(self):
        registry_ = SourceRegistry()
        first = registry_.register(ColourSource())
        seen = []
        registry_.on_register(seen.append)
        second = registry_.register(type("Other", (ColourSource,), {"key": "test_other"})())
        self.assertEqual(seen, [first, second])


@override_settings(CACHES=LOCAL_CACHE)
class ColourCacheTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_store_terms_inserts_then_updates(self):
        source = ColourSource()
        self.assertEqual(store_terms(source, source.search("red", 5)), 2)
        store_terms(source, [ExternalTermData("1", "Crimson red")])
        terms = ExternalTerm.objects.filter(platform="test_platform", kind="colour").order_by("external_id")
        self.assertEqual([term.name for term in terms], ["Crimson red", "Scarlet"])

    def test_refresh_searches_once_and_survives_platform_failures(self):
        working = ColourSource()
        failing = ColourSource(failing=True)
        with patch.dict(sources._sources, {"test_colour": working}):
            self.assertEqual(refresh_from_platform("test_colour", "red"), 2)
            self.assertEqual(refresh_from_platform("test_colour", " RED "), 0)
        with patch.dict(sources._sources, {"test_colour": failing}):
            with self.assertLogs("ccv.external_vocabularies.cache", level="WARNING"):
                self.assertEqual(refresh_from_platform("test_colour", "blue"), 0)
            self.assertEqual(refresh_from_platform("test_colour", "blue"), 0)
        self.assertEqual(working.searched, ["red"])
        self.assertEqual(failing.searched, ["blue"])


class OntologyRegistryTest(TestCase):
    def test_registered_sources_become_ontology_types(self):
        source = type("Shade", (ColourSource,), {"key": "test_shade", "label": "Test shade"})()
        with patch.dict(sources._sources), patch.dict(registry._descriptors):
            sources.register(source)
            descriptor = registry.get("test_shade")
        self.assertEqual(descriptor.label, "Test shade")
        self.assertEqual(descriptor.base_filter, {"platform": "test_platform", "kind": "colour"})
