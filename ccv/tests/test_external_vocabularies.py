"""Tests for external vocabulary sources, the local term cache and their registry integration."""

import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from choux import APIError, ProtocolsIO
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient

from ccc.notification_service import BaseNotificationService
from ccv.external_vocabularies import ExternalTermData, ExternalVocabularySource, refresh_from_platform, store_terms
from ccv.external_vocabularies.base import SourceRegistry
from ccv.external_vocabularies.protocols_io import reagent_term, reagents, unit_term, units
from ccv.external_vocabularies.tasks import refresh_external_vocabulary_task, request_refresh
from ccv.management.commands.export_mobile_snapshot import _dump_queryset
from ccv.management.commands.import_mobile_snapshot import Command as ImportCommand
from ccv.models import ExternalTerm
from ccv.ontology_registry import registry

LOCAL_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "external-vocab"}}

RIPA = {
    "id": 968629,
    "name": "RIPA Buffer",
    "sku": "R0278",
    "mol_weight": 0,
    "url": "https://www.sigmaaldrich.com/R0278",
    "vendor": {"name": "Merck MilliporeSigma (Sigma-Aldrich)", "link": "https://www.sigmaaldrich.com/"},
}
TRYPSIN = {"id": 1001, "name": "Trypsin Gold", "sku": "V5280", "vendor": {"name": "Promega"}}
MICROLITRE = {"id": 1, "type_id": 3, "name": "µL", "aliases": ["uL", "ul", "microliter"]}
CELSIUS = {"id": 10, "type_id": 24, "name": "°C", "aliases": ["Celsius"]}
REMOVED = {"id": 99, "type_id": 3, "name": "old", "aliases": [], "deleted": True}


def stored(platform="protocols_io", kind="reagent"):
    """Return the cached terms of one platform and kind."""
    return ExternalTerm.objects.filter(platform=platform, kind=kind)


@override_settings(CACHES=LOCAL_CACHE, PROTOCOLS_IO_ACCESS_TOKEN="token")
class StoreTermsTest(TestCase):
    def test_inserts_terms(self):
        self.assertEqual(store_terms(reagents, [reagent_term(RIPA), reagent_term(TRYPSIN)]), 2)
        term = stored().get(external_id="968629")
        self.assertEqual(term.name, "RIPA Buffer")
        self.assertEqual(term.description, "Merck MilliporeSigma (Sigma-Aldrich) Catalog #R0278")
        self.assertEqual(term.synonyms, "R0278")
        self.assertEqual(term.data["url"], "https://www.sigmaaldrich.com/R0278")

    def test_updates_existing_terms_without_duplicates(self):
        store_terms(reagents, [reagent_term(RIPA)])
        store_terms(reagents, [reagent_term({**RIPA, "name": "RIPA Buffer 1X"})])
        self.assertEqual(stored().count(), 1)
        self.assertEqual(stored().get().name, "RIPA Buffer 1X")

    def test_same_id_on_another_kind_is_a_separate_term(self):
        store_terms(reagents, [reagent_term({**RIPA, "id": 1})])
        store_terms(units, [unit_term(MICROLITRE)])
        self.assertEqual(ExternalTerm.objects.filter(external_id="1").count(), 2)

    def test_terms_without_id_or_name_are_skipped(self):
        self.assertEqual(store_terms(reagents, [ExternalTermData("", "x"), ExternalTermData("5", "")]), 0)
        self.assertFalse(ExternalTerm.objects.exists())


@override_settings(CACHES=LOCAL_CACHE, PROTOCOLS_IO_ACCESS_TOKEN="token")
class RefreshFromPlatformTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_searches_once_per_term(self):
        with patch.object(ProtocolsIO, "search_reagents", return_value={"items": [RIPA]}) as search:
            self.assertEqual(refresh_from_platform("protocols_io_reagent", "RIPA"), 1)
            self.assertEqual(refresh_from_platform("protocols_io_reagent", " ripa "), 0)
        search.assert_called_once_with("RIPA", page_size=25)
        self.assertTrue(stored().filter(external_id="968629").exists())

    def test_short_terms_are_not_sent(self):
        with patch.object(ProtocolsIO, "search_reagents") as search:
            self.assertEqual(refresh_from_platform("protocols_io_reagent", "ri"), 0)
        search.assert_not_called()

    @override_settings(PROTOCOLS_IO_ACCESS_TOKEN="")
    def test_unconfigured_instance_does_not_search(self):
        with patch.object(ProtocolsIO, "search_reagents") as search:
            self.assertEqual(refresh_from_platform("protocols_io_reagent", "RIPA"), 0)
        search.assert_not_called()

    def test_non_searchable_and_unknown_sources_are_ignored(self):
        self.assertEqual(refresh_from_platform("protocols_io_unit", "microliter"), 0)
        self.assertEqual(refresh_from_platform("nothing_here", "microliter"), 0)

    def test_platform_failure_is_logged_and_retried_later(self):
        with patch.object(ProtocolsIO, "search_reagents", side_effect=APIError("down")) as search:
            with self.assertLogs("ccv.external_vocabularies.cache", level="WARNING"):
                self.assertEqual(refresh_from_platform("protocols_io_reagent", "RIPA"), 0)
            self.assertEqual(refresh_from_platform("protocols_io_reagent", "RIPA"), 0)
        search.assert_called_once()
        self.assertFalse(ExternalTerm.objects.exists())


class ProtocolsIOTermTest(TestCase):
    def test_reagent_without_vendor_or_sku(self):
        term = reagent_term({"id": 5, "name": "Water"})
        self.assertEqual((term.external_id, term.description, term.synonyms), ("5", "", ()))

    def test_unit_term_keeps_aliases_and_kind(self):
        term = unit_term(MICROLITRE)
        self.assertEqual((term.external_id, term.name, term.description), ("1", "µL", "amount"))
        self.assertEqual(term.synonyms, ("uL", "ul", "microliter"))

    @override_settings(PROTOCOLS_IO_ACCESS_TOKEN="token", PROTOCOLS_IO_UNITS_PROTOCOL="")
    def test_unit_loading_needs_a_protocol(self):
        with self.assertRaises(ValueError):
            list(units.load_all())

    @override_settings(PROTOCOLS_IO_ACCESS_TOKEN="token", PROTOCOLS_IO_UNITS_PROTOCOL="340067")
    def test_unit_loading_reads_the_configured_protocol_and_skips_deleted_units(self):
        with patch.object(ProtocolsIO, "get_units", return_value=[MICROLITRE, REMOVED]) as get_units:
            terms = list(units.load_all())
        get_units.assert_called_once_with("340067")
        self.assertEqual([term.external_id for term in terms], ["1"])


class SourceRegistryTest(TestCase):
    def test_duplicate_keys_are_refused(self):
        class Example(ExternalVocabularySource):
            key = "example"
            platform = "example"
            kind = "thing"
            label = "Example"

            def is_configured(self):
                return True

        registry_ = SourceRegistry()
        registry_.register(Example())
        with self.assertRaises(ValueError):
            registry_.register(Example())

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


@override_settings(CACHES=LOCAL_CACHE, PROTOCOLS_IO_ACCESS_TOKEN="token")
class RegistryIntegrationTest(TestCase):
    def setUp(self):
        cache.clear()
        store_terms(units, [unit_term(MICROLITRE), unit_term(CELSIUS)])

    def test_suggestions_never_contact_the_platform(self):
        store_terms(reagents, [reagent_term(RIPA), reagent_term(TRYPSIN)])
        with patch.object(ProtocolsIO, "search_reagents") as search:
            suggestions = registry.get_suggestions("protocols_io_reagent", "RIPA")
            exact = registry.get_suggestions("protocols_io_reagent", "Trypsin Gold", search_type="exact")
        search.assert_not_called()
        self.assertEqual([item["name"] for item in suggestions], ["RIPA Buffer"])
        self.assertEqual([item["name"] for item in exact], ["Trypsin Gold"])

    def test_reagents_are_found_by_catalogue_number(self):
        store_terms(reagents, [reagent_term(TRYPSIN)])
        self.assertEqual(
            [item["name"] for item in registry.get_suggestions("protocols_io_reagent", "V5280")], ["Trypsin Gold"]
        )

    def test_unit_suggestions_use_aliases(self):
        suggestions = registry.get_suggestions("protocols_io_unit", "microliter")
        self.assertEqual([item["external_id"] for item in suggestions], ["1"])

    def test_base_queryset_only_holds_its_kind(self):
        store_terms(reagents, [reagent_term(RIPA)])
        self.assertEqual(registry.get("protocols_io_unit").base_queryset().count(), 2)
        self.assertEqual(registry.get("protocols_io_reagent").base_queryset().count(), 1)

    def test_serialized_suggestion_shape(self):
        store_terms(reagents, [reagent_term(RIPA)])
        row = registry.get("protocols_io_reagent").base_queryset().values().get()
        result = registry.serialize("protocols_io_reagent", row)
        self.assertEqual(result["id"], "968629")
        self.assertEqual(result["value"], "RIPA Buffer")
        self.assertEqual(result["description"], "Merck MilliporeSigma (Sigma-Aldrich) Catalog #R0278")
        self.assertEqual(result["ontology_type"], "protocols_io_reagent")
        self.assertEqual(result["full_data"]["data"]["sku"], "R0278")


@override_settings(CACHES=LOCAL_CACHE, PROTOCOLS_IO_ACCESS_TOKEN="token")
class RequestRefreshTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_queues_one_job_per_term_and_remembers_every_waiting_user(self):
        with patch.object(refresh_external_vocabulary_task, "delay") as delay:
            self.assertTrue(request_refresh("protocols_io_reagent", " RIPA ", user_id=1))
            self.assertTrue(request_refresh("protocols_io_reagent", "ripa", user_id=2))
        delay.assert_called_once_with("protocols_io_reagent", "RIPA")
        with patch.object(ProtocolsIO, "search_reagents", return_value={"items": [RIPA]}):
            with patch.object(BaseNotificationService, "notify_user") as notify:
                self.assertEqual(refresh_external_vocabulary_task("protocols_io_reagent", "RIPA"), 1)
        self.assertEqual([call.args[0] for call in notify.call_args_list], [1, 2])
        self.assertEqual(notify.call_args.args[1], "external_vocabulary.updated")
        self.assertEqual(
            notify.call_args.kwargs, {"ontology_type": "protocols_io_reagent", "search_term": "RIPA", "stored": 1}
        )

    def test_recent_search_is_not_queued_again(self):
        with patch.object(ProtocolsIO, "search_reagents", return_value={"items": [RIPA]}):
            refresh_from_platform("protocols_io_reagent", "RIPA")
        with patch.object(refresh_external_vocabulary_task, "delay") as delay:
            self.assertFalse(request_refresh("protocols_io_reagent", "RIPA", user_id=1))
        delay.assert_not_called()

    def test_failed_search_is_not_queued_again_until_the_failure_ttl(self):
        with patch.object(refresh_external_vocabulary_task, "delay"):
            request_refresh("protocols_io_reagent", "RIPA", user_id=1)
        with patch.object(ProtocolsIO, "search_reagents", side_effect=APIError("down")):
            with patch.object(BaseNotificationService, "notify_user") as notify:
                with self.assertLogs("ccv.external_vocabularies.cache", level="WARNING"):
                    refresh_external_vocabulary_task("protocols_io_reagent", "RIPA")
        self.assertEqual(notify.call_args.kwargs["stored"], 0)
        with patch.object(refresh_external_vocabulary_task, "delay") as delay:
            self.assertFalse(request_refresh("protocols_io_reagent", "RIPA", user_id=1))
        delay.assert_not_called()

    def test_notifies_even_when_nothing_was_found(self):
        with patch.object(refresh_external_vocabulary_task, "delay"):
            request_refresh("protocols_io_reagent", "nothing like it", user_id=3)
        with patch.object(ProtocolsIO, "search_reagents", return_value={"items": []}):
            with patch.object(BaseNotificationService, "notify_user") as notify:
                refresh_external_vocabulary_task("protocols_io_reagent", "nothing like it")
        self.assertEqual(notify.call_args.kwargs["stored"], 0)

    def test_queue_failure_is_not_pending(self):
        with patch.object(refresh_external_vocabulary_task, "delay", side_effect=RedisConnectionError("down")):
            with self.assertLogs("ccv.external_vocabularies.tasks", level="WARNING"):
                self.assertFalse(request_refresh("protocols_io_reagent", "RIPA", user_id=1))
        with patch.object(refresh_external_vocabulary_task, "delay") as delay:
            self.assertTrue(request_refresh("protocols_io_reagent", "RIPA", user_id=1))
        delay.assert_called_once()

    def test_types_without_a_searchable_platform_are_never_pending(self):
        with patch.object(refresh_external_vocabulary_task, "delay") as delay:
            self.assertFalse(request_refresh("protocols_io_unit", "microliter", user_id=1))
            self.assertFalse(request_refresh("species", "human", user_id=1))
            self.assertFalse(request_refresh(None, "human", user_id=1))
            self.assertFalse(request_refresh("protocols_io_reagent", "ri", user_id=1))
        delay.assert_not_called()

    @override_settings(PROTOCOLS_IO_ACCESS_TOKEN="")
    def test_unconfigured_instance_is_never_pending(self):
        with patch.object(refresh_external_vocabulary_task, "delay") as delay:
            self.assertFalse(request_refresh("protocols_io_reagent", "RIPA", user_id=1))
        delay.assert_not_called()


@override_settings(CACHES=LOCAL_CACHE, PROTOCOLS_IO_ACCESS_TOKEN="token")
class SuggestionEndpointsTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("vocab-user", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_search_answers_locally_then_queues_the_platform_search(self):
        store_terms(reagents, [reagent_term(TRYPSIN)])
        with patch.object(refresh_external_vocabulary_task, "delay") as delay:
            with patch.object(ProtocolsIO, "search_reagents") as search:
                response = self.client.get(
                    reverse("ccv:ontologysearch-suggest"), {"q": "trypsin", "type": "protocols_io_reagent", "limit": 10}
                )
        search.assert_not_called()
        delay.assert_called_once_with("protocols_io_reagent", "trypsin")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["remote_pending"])
        self.assertEqual([item["id"] for item in response.data["suggestions"]], ["1001"])

    def test_search_after_the_job_finds_platform_results(self):
        with patch.object(refresh_external_vocabulary_task, "delay"):
            self.client.get(reverse("ccv:ontologysearch-suggest"), {"q": "buffer", "type": "protocols_io_reagent"})
        with patch.object(ProtocolsIO, "search_reagents", return_value={"items": [RIPA]}):
            with patch.object(BaseNotificationService, "notify_user") as notify:
                refresh_external_vocabulary_task("protocols_io_reagent", "buffer")
        self.assertEqual(notify.call_args.args[0], self.user.id)
        response = self.client.get(
            reverse("ccv:ontologysearch-suggest"), {"q": "buffer", "type": "protocols_io_reagent"}
        )
        self.assertFalse(response.data["remote_pending"])
        self.assertEqual([item["id"] for item in response.data["suggestions"]], ["968629"])

    def test_local_vocabularies_report_nothing_pending(self):
        response = self.client.get(reverse("ccv:ontologysearch-suggest"), {"q": "human", "type": "species"})
        self.assertFalse(response.data["remote_pending"])


@override_settings(CACHES=LOCAL_CACHE)
class SnapshotIsolationTest(TestCase):
    def test_importing_one_external_vocabulary_keeps_the_others(self):
        store_terms(units, [unit_term(MICROLITRE)])
        store_terms(reagents, [reagent_term(RIPA)])
        descriptor = registry.get("protocols_io_unit")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "units.sqlite"
            _dump_queryset(descriptor.base_queryset(), "protocols_io_unit", path)
            imported = ImportCommand()._import_scalar_table(
                descriptor.model, "protocols_io_unit", path, replaced=descriptor.base_queryset()
            )
        self.assertEqual(imported, 1)
        self.assertEqual(stored(kind="unit").count(), 1)
        self.assertEqual(stored(kind="reagent").count(), 1)


@override_settings(CACHES=LOCAL_CACHE, PROTOCOLS_IO_ACCESS_TOKEN="token")
class LoadExternalVocabularyCommandTest(TestCase):
    def test_loads_units(self):
        out = StringIO()
        with patch.object(ProtocolsIO, "get_units", return_value=[MICROLITRE, CELSIUS]):
            call_command("load_external_vocabulary", "protocols_io_unit", "--option", "protocol=340067", stdout=out)
        self.assertIn("Stored 2 protocols.io Unit term(s)", out.getvalue())
        self.assertEqual(stored(kind="unit").count(), 2)

    def test_unknown_source(self):
        with self.assertRaisesMessage(CommandError, "Unknown source"):
            call_command("load_external_vocabulary", "labarchives_thing")

    def test_malformed_option(self):
        with self.assertRaisesMessage(CommandError, "NAME=VALUE"):
            call_command("load_external_vocabulary", "protocols_io_unit", "--option", "protocol")

    def test_source_that_cannot_be_listed(self):
        with self.assertRaisesMessage(CommandError, "cannot be loaded in full"):
            call_command("load_external_vocabulary", "protocols_io_reagent")

    def test_platform_failure(self):
        with patch.object(ProtocolsIO, "get_units", side_effect=APIError("down")):
            with self.assertRaisesMessage(CommandError, "Loading protocols_io_unit failed"):
                call_command("load_external_vocabulary", "protocols_io_unit", "--option", "protocol=1")

    @override_settings(PROTOCOLS_IO_ACCESS_TOKEN="")
    def test_unconfigured_instance(self):
        with self.assertRaisesMessage(CommandError, "not configured"):
            call_command("load_external_vocabulary", "protocols_io_unit")
