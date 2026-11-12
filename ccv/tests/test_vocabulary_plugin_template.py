"""A plugin created from cupcake-plugin-dev's vocabulary template, run against the backend's plugin endpoints."""

import copy
import importlib.util
import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from django.core.cache import cache
from django.test import override_settings

from rest_framework.test import APIClient, APITestCase

from ccc.plugin.connection import callback_key
from ccc.plugin.model import Plugin
from ccv.external_vocabularies import live_search_source, refresh_from_platform
from ccv.models import Vocabulary
from cupcake_plugin_dev.scaffold import create_plugin

SCAFFOLD = tempfile.TemporaryDirectory()
TEMPLATE = create_plugin("example-vocabulary", "vocabulary", Path(SCAFFOLD.name))
SPEC = importlib.util.spec_from_file_location("vocabulary_plugin_template", TEMPLATE / "plugin.py")
template = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = template
SPEC.loader.exec_module(template)


class ClientBackend(template.Backend):
    """The template's backend calls sent through the Django test client."""

    def __init__(self, token):
        """Authenticate the test client with the plugin token."""
        super().__init__("http://testserver", token)
        self.client = APIClient()
        self.client.credentials(HTTP_PLUGIN_TOKEN=token)

    def request(self, method, path, body=None):
        response = getattr(self.client, method.lower())(f"/api/v1/{path}", body, format="json")
        assert response.status_code < 300, f"{method} {path}: {response.status_code} {response.content[:300]!r}"
        return response.json()


@override_settings(ALLOWED_HOSTS=["testserver"])
class VocabularyPluginTemplateTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.manifest = template.read_manifest()
        self.plugin = Plugin.objects.create(name=self.manifest["name"], display_name="Example", version="1.0")
        self.backend = ClientBackend(self.plugin._plain_token)
        self.start(self.manifest)

    def start(self, manifest):
        """Serve the template on a free local port and announce it, as its main() does."""
        template.PluginHandler.callback_key = ""
        server, _ = template.serve(manifest, self.plugin._plain_token, 0, host="127.0.0.1")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.server = server
        self.base_url = f"http://127.0.0.1:{server.server_port}"
        return template.announce(self.backend, self.base_url, manifest)

    def live_manifest(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["vocabularies"][0]["liveSearch"] = True
        return manifest

    def get_plugin(self, path, key=None):
        request = urllib.request.Request(f"{self.base_url}/{path}", headers={"Cupcake-Key": key or ""})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read())

    def test_startup_completes_the_handshake_with_the_template(self):
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.lifecycle_status, Plugin.LIFECYCLE_RUNNING)
        self.assertIsNotNone(self.plugin.connection_verified_at)
        self.assertEqual(template.PluginHandler.callback_key, callback_key(self.plugin))
        self.assertEqual(self.get_plugin("cupcake/ping", callback_key(self.plugin))["name"], self.manifest["name"])

    def test_the_template_refuses_calls_without_the_callback_key(self):
        with self.assertRaises(urllib.error.HTTPError) as refused:
            self.get_plugin("cupcake/ping", "wrong")
        self.assertEqual(refused.exception.code, 401)

    def test_live_search_vocabularies_are_searched_at_the_plugin(self):
        self.start(self.live_manifest())
        key = f"plugin.{self.manifest['name']}.strains"
        Vocabulary.objects.filter(key=key).update(approved=True)
        self.plugin.refresh_from_db()
        source = live_search_source(key)
        self.assertTrue(source.is_configured())
        self.assertEqual([term.name for term in source.search("WT", 10)], ["wild type"])
        self.assertEqual(refresh_from_platform(key, "type"), 1)
        vocabulary = Vocabulary.objects.get(key=key)
        self.assertEqual(list(vocabulary.terms.values_list("external_id", flat=True)), ["EXS:0001"])
        self.assertEqual(vocabulary.status, Vocabulary.STATUS_ACTIVE)

    def test_obsolete_terms_are_not_returned_by_live_search(self):
        self.start(self.live_manifest())
        key = f"plugin.{self.manifest['name']}.strains"
        Vocabulary.objects.filter(key=key).update(approved=True)
        self.assertEqual(live_search_source(key).search("retired", 10), [])

    def test_live_search_waits_for_approval(self):
        self.start(self.live_manifest())
        self.assertFalse(live_search_source(f"plugin.{self.manifest['name']}.strains").is_configured())

    def test_a_plugin_that_stops_answering_makes_its_vocabulary_unavailable(self):
        self.start(self.live_manifest())
        key = f"plugin.{self.manifest['name']}.strains"
        Vocabulary.objects.filter(key=key).update(approved=True)
        self.server.shutdown()
        self.server.server_close()
        self.assertEqual(refresh_from_platform(key, "wild"), 0)
        vocabulary = Vocabulary.objects.get(key=key)
        self.assertEqual(vocabulary.status, Vocabulary.STATUS_UNAVAILABLE)
        self.assertTrue(vocabulary.last_error.startswith("Search failed"))

    def test_live_search_vocabularies_are_not_sent_in_full(self):
        manifest = self.live_manifest()
        self.start(manifest)
        template.sync_all(self.backend, manifest)
        self.assertEqual(Vocabulary.objects.get(key=f"plugin.{self.manifest['name']}.strains").term_count, 0)

    def test_the_manifest_declares_valid_vocabularies(self):
        keys = [entry["key"] for entry in self.manifest["vocabularies"]]
        self.assertEqual(
            sorted(Vocabulary.objects.filter(plugin=self.plugin).values_list("key", flat=True)),
            sorted(f"plugin.{self.manifest['name']}.{key}" for key in keys),
        )

    def test_the_example_terms_are_read_from_the_tsv_file(self):
        terms = list(template.load_terms("strains"))
        self.assertEqual([term["id"] for term in terms], ["EXS:0001", "EXS:0002", "EXS:0003"])
        self.assertEqual(terms[0]["synonyms"], ["WT", "wildtype"])
        self.assertTrue(terms[2]["obsolete"])

    def test_sync_all_loads_every_vocabulary_and_reports_running(self):
        template.sync_all(self.backend, self.manifest)
        vocabulary = Vocabulary.objects.get(key=f"plugin.{self.manifest['name']}.strains")
        self.assertEqual((vocabulary.term_count, vocabulary.status), (3, Vocabulary.STATUS_ACTIVE))
        self.assertFalse(vocabulary.approved)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.lifecycle_status, Plugin.LIFECYCLE_RUNNING)

    def test_a_reload_sends_terms_in_batches_and_drops_the_missing_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = "".join(f"EXS:{index:05d}\tstrain {index}\t\t\t\n" for index in range(2500))
            Path(directory, "strains.tsv").write_text("id\tname\tdescription\tsynonyms\tobsolete\n" + rows)
            first = template.sync_vocabulary(self.backend, "strains", template.load_terms("strains", Path(directory)))
            self.assertEqual(first["term_count"], 2500)
            Path(directory, "strains.tsv").write_text(
                "id\tname\tdescription\tsynonyms\tobsolete\nEXS:00001\tkept\t\t\t\n"
            )
            second = template.sync_vocabulary(self.backend, "strains", template.load_terms("strains", Path(directory)))
        self.assertEqual((second["term_count"], second["removed"]), (1, 2499))

    def test_terms_are_sent_at_most_a_thousand_at_a_time(self):
        sizes = [len(batch) for batch in template.batches(({"id": str(index)} for index in range(2001)))]
        self.assertEqual(sizes, [1000, 1000, 1])
