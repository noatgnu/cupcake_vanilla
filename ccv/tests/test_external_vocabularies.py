"""Vocabularies kept in the vocabulary terms table and searched live on their platform, with a source that needs no platform."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from ccv.external_vocabularies import (
    ExternalTermData,
    ExternalVocabularyError,
    ExternalVocabularySource,
    live_search_source,
    refresh_from_platform,
    store_terms,
)
from ccv.models import Vocabulary, VocabularyTerm
from ccv.ontology_registry import registry

LOCAL_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "external-vocab"}}
COLOUR_SOURCE = "ccv.tests.test_external_vocabularies.ColourSource"


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


def colour_vocabulary(**fields):
    """The test colour vocabulary row, searched live through ColourSource."""
    values = {
        "key": "test_colour",
        "label": "Test colour",
        "kind": "colour",
        "provider": Vocabulary.PROVIDER_ADDON,
        "storage": Vocabulary.STORAGE_TERMS,
        "live_search_adapter": COLOUR_SOURCE,
    }
    values.update(fields)
    return Vocabulary.objects.create(**values)


class LiveSearchSourceTest(TestCase):
    def test_the_class_named_by_the_vocabulary_is_loaded(self):
        colour_vocabulary()
        self.assertIsInstance(live_search_source("test_colour"), ColourSource)

    def test_vocabularies_without_a_live_search_class_have_no_source(self):
        colour_vocabulary(live_search_adapter="")
        self.assertIsNone(live_search_source("test_colour"))
        self.assertIsNone(live_search_source("not_a_vocabulary"))

    def test_a_class_that_cannot_be_loaded_gives_no_source(self):
        colour_vocabulary(live_search_adapter="ccv.tests.missing_module.Source")
        with self.assertLogs("ccv.external_vocabularies.base", level="WARNING"):
            self.assertIsNone(live_search_source("test_colour"))

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


@override_settings(CACHES=LOCAL_CACHE)
class ColourCacheTest(TestCase):
    def setUp(self):
        cache.clear()
        self.vocabulary = colour_vocabulary()

    def test_store_terms_inserts_then_updates_and_counts(self):
        source = ColourSource()
        self.assertEqual(store_terms(source, source.search("red", 5)), 2)
        store_terms(source, [ExternalTermData("1", "Crimson red")])
        terms = VocabularyTerm.objects.filter(vocabulary=self.vocabulary).order_by("external_id")
        self.assertEqual([term.name for term in terms], ["Crimson red", "Scarlet"])
        self.vocabulary.refresh_from_db()
        self.assertEqual(self.vocabulary.term_count, 2)
        self.assertIsNotNone(self.vocabulary.last_loaded_at)

    def test_terms_of_a_missing_vocabulary_are_not_stored(self):
        self.vocabulary.delete()
        with self.assertLogs("ccv.external_vocabularies.cache", level="WARNING"):
            self.assertEqual(store_terms(ColourSource(), [ExternalTermData("1", "Crimson")]), 0)

    def test_refresh_searches_once_and_survives_platform_failures(self):
        working = ColourSource()
        failing = ColourSource(failing=True)
        with patch("ccv.external_vocabularies.cache.live_search_source", return_value=working):
            self.assertEqual(refresh_from_platform("test_colour", "red"), 2)
            self.assertEqual(refresh_from_platform("test_colour", " RED "), 0)
        with patch("ccv.external_vocabularies.cache.live_search_source", return_value=failing):
            with self.assertLogs("ccv.external_vocabularies.cache", level="WARNING"):
                self.assertEqual(refresh_from_platform("test_colour", "blue"), 0)
            self.assertEqual(refresh_from_platform("test_colour", "blue"), 0)
        self.assertEqual(working.searched, ["red"])
        self.assertEqual(failing.searched, ["blue"])


class OntologyRegistryTest(TestCase):
    def test_vocabulary_rows_become_ontology_types(self):
        vocabulary = colour_vocabulary(label="Test shade")
        descriptor = registry.get("test_colour")
        self.assertEqual(descriptor.label, "Test shade")
        self.assertEqual(descriptor.base_filter, {"vocabulary_id": vocabulary.pk})
        self.assertEqual(descriptor.remote_source, "test_colour")

    def test_terms_are_suggested_from_the_vocabulary_terms_table(self):
        vocabulary = colour_vocabulary(live_search_adapter="")
        store_terms(ColourSource(), [ExternalTermData("1", "Crimson", "A deep red", ("dark red",))])
        suggestions = [
            registry.serialize("test_colour", row) for row in registry.get_suggestions("test_colour", "crim", limit=10)
        ]
        self.assertEqual([item["display_name"] for item in suggestions], ["Crimson"])
        self.assertEqual(suggestions[0]["full_data"]["vocabulary"], vocabulary.key)
        self.assertIsNone(registry.get("test_colour").remote_source)

    def test_disabled_and_unapproved_vocabularies_are_left_out(self):
        colour_vocabulary(status=Vocabulary.STATUS_DISABLED)
        self.assertIsNone(registry.get("test_colour"))
        colour_vocabulary(key="test_hidden", approved=False)
        keys = [key for key, _ in registry.choices()]
        self.assertNotIn("test_colour", keys)
        self.assertNotIn("test_hidden", keys)

    def test_built_in_ontologies_are_listed_from_their_rows(self):
        keys = [key for key, _ in registry.choices()]
        for key in ("species", "mondo", "ncbi_taxonomy", "psi_ms", "doid"):
            self.assertIn(key, keys)
        self.assertEqual(registry.get("mondo").model_label, "ccv.MondoDisease")
