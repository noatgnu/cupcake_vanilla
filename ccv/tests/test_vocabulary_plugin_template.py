"""The vocabulary plugin template in plugins/templates/vocabulary, run against the backend's plugin endpoints."""

import importlib.util
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import override_settings

from rest_framework.test import APIClient, APITestCase

from ccc.plugin.model import Plugin
from ccv.models import Vocabulary

TEMPLATE = Path(settings.BASE_DIR) / "plugins" / "templates" / "vocabulary"
SPEC = importlib.util.spec_from_file_location("vocabulary_plugin_template", TEMPLATE / "plugin.py")
template = importlib.util.module_from_spec(SPEC)
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
        self.manifest = template.read_manifest()
        self.plugin = Plugin.objects.create(name=self.manifest["name"], display_name="Example", version="1.0")
        self.backend = ClientBackend(self.plugin._plain_token)
        self.backend.post("plugins/startup/", {"base_url": "http://plugin.local:8101", "manifest": self.manifest})

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
