"""
Test cases for load_ontologies management command, specifically BTO and DOID loading.

Tests cover OBO parsing, term processing, database persistence, update logic,
and error handling for the BTO and DOID ontology loaders.
"""

from io import StringIO
from unittest.mock import MagicMock, patch

from django.test import TestCase

from ccv.management.commands.load_ontologies import Command, OBOParser
from ccv.models import BTOTerm, DiseaseOntologyTerm

BTO_OBO_SAMPLE = """\
format-version: 1.2
data-version: releases/2024-01-01
ontology: bto

[Term]
id: BTO:0000000
name: tissues, cell types and enzyme sources
def: "The root of the BTO ontology." [BTO:curators]

[Term]
id: BTO:0000567
name: liver
def: "The liver is a large, reddish-brown, glandular organ." [Wikipedia:Liver]
synonym: "hepar" EXACT []
synonym: "hepatic tissue" RELATED []
xref: Wikipedia:Liver
is_a: BTO:0000000 ! tissues, cell types and enzyme sources

[Term]
id: BTO:0000970
name: lung
def: "The lung is the essential respiration organ." [Wikipedia:Lung]
synonym: "pulmonary tissue" RELATED []
is_a: BTO:0000000 ! tissues, cell types and enzyme sources

[Term]
id: BTO:9999999
name: obsolete term
is_obsolete: true
replaced_by: BTO:0000567
"""

DOID_OBO_SAMPLE = """\
format-version: 1.2
data-version: releases/2024-01-01
ontology: doid

[Term]
id: DOID:4
name: disease
def: "A disease is a disposition to undergo pathological processes." [url:http://ontology.buffalo.edu/medo/Disease_and_Diagnosis.pdf]

[Term]
id: DOID:9351
name: diabetes mellitus
def: "A metabolic disorder characterized by hyperglycemia." [url:http://en.wikipedia.org/wiki/Diabetes_mellitus]
synonym: "DM" EXACT []
synonym: "diabetes" RELATED []
xref: MeSH:D003920
xref: ICD10CM:E11
is_a: DOID:4 ! disease

[Term]
id: DOID:1612
name: breast cancer
def: "A thoracic cancer that originates in the mammary gland." [url:http://en.wikipedia.org/wiki/Breast_cancer]
synonym: "breast carcinoma" EXACT []
is_a: DOID:4 ! disease

[Term]
id: DOID:0000001
name: obsolete disease term
is_obsolete: true
replaced_by: DOID:4
"""


def _make_mock_response(text):
    """Create a mock requests.Response with the given text content."""
    mock_resp = MagicMock()
    mock_resp.text = text
    mock_resp.raise_for_status.return_value = None
    return mock_resp


class OBOParserTest(TestCase):
    """Unit tests for the OBOParser helper class."""

    def _parse(self, content):
        return OBOParser().parse_obo_content(content)

    def test_parses_bto_id_and_name(self):
        terms = self._parse(BTO_OBO_SAMPLE)
        bto_terms = [t for t in terms if t.get("id", "").startswith("BTO:")]
        self.assertEqual(len(bto_terms), 4)
        ids = {t["id"] for t in bto_terms}
        self.assertIn("BTO:0000567", ids)
        self.assertIn("BTO:0000970", ids)

    def test_parses_bto_definition(self):
        terms = self._parse(BTO_OBO_SAMPLE)
        liver = next(t for t in terms if t.get("id") == "BTO:0000567")
        self.assertIn("reddish-brown", liver["definition"])

    def test_parses_bto_synonyms(self):
        terms = self._parse(BTO_OBO_SAMPLE)
        liver = next(t for t in terms if t.get("id") == "BTO:0000567")
        self.assertIn("hepar", liver["synonyms"])
        self.assertIn("hepatic tissue", liver["synonyms"])

    def test_parses_bto_xrefs(self):
        terms = self._parse(BTO_OBO_SAMPLE)
        liver = next(t for t in terms if t.get("id") == "BTO:0000567")
        self.assertTrue(any("Wikipedia" in x for x in liver["xrefs"]))

    def test_parses_bto_parent(self):
        terms = self._parse(BTO_OBO_SAMPLE)
        liver = next(t for t in terms if t.get("id") == "BTO:0000567")
        self.assertIn("BTO:0000000", liver["is_a"])

    def test_parses_bto_obsolete_flag(self):
        terms = self._parse(BTO_OBO_SAMPLE)
        obsolete = next(t for t in terms if t.get("id") == "BTO:9999999")
        self.assertTrue(obsolete["obsolete"])
        self.assertEqual(obsolete.get("replaced_by"), "BTO:0000567")

    def test_parses_doid_id_and_name(self):
        terms = self._parse(DOID_OBO_SAMPLE)
        doid_terms = [t for t in terms if t.get("id", "").startswith("DOID:")]
        self.assertEqual(len(doid_terms), 4)
        ids = {t["id"] for t in doid_terms}
        self.assertIn("DOID:9351", ids)
        self.assertIn("DOID:1612", ids)

    def test_parses_doid_synonyms(self):
        terms = self._parse(DOID_OBO_SAMPLE)
        diabetes = next(t for t in terms if t.get("id") == "DOID:9351")
        self.assertIn("DM", diabetes["synonyms"])
        self.assertIn("diabetes", diabetes["synonyms"])

    def test_parses_doid_xrefs(self):
        terms = self._parse(DOID_OBO_SAMPLE)
        diabetes = next(t for t in terms if t.get("id") == "DOID:9351")
        self.assertIn("MeSH:D003920", diabetes["xrefs"])
        self.assertIn("ICD10CM:E11", diabetes["xrefs"])

    def test_parses_doid_obsolete_flag(self):
        terms = self._parse(DOID_OBO_SAMPLE)
        obsolete = next(t for t in terms if t.get("id") == "DOID:0000001")
        self.assertTrue(obsolete["obsolete"])


class ProcessBTOTermTest(TestCase):
    """Unit tests for Command._process_bto_term."""

    def setUp(self):
        self.cmd = Command()
        self.cmd.stdout = StringIO()
        self.cmd.style = MagicMock()
        self.cmd.style.ERROR = lambda x: x

    def test_creates_new_bto_term(self):
        term_data = {
            "id": "BTO:0000567",
            "name": "liver",
            "definition": "The liver is a large organ.",
            "synonyms": ["hepar"],
            "xrefs": ["Wikipedia:Liver"],
            "is_a": ["BTO:0000000"],
            "part_of": [],
        }
        created, updated = self.cmd._process_bto_term(term_data, update_existing=False)
        self.assertTrue(created)
        self.assertFalse(updated)
        obj = BTOTerm.objects.get(identifier="BTO:0000567")
        self.assertEqual(obj.name, "liver")
        self.assertIn("hepar", obj.synonyms)
        self.assertIn("BTO:0000000", obj.parent_terms)

    def test_skips_obsolete_bto_term(self):
        term_data = {"id": "BTO:9999999", "name": "obsolete", "obsolete": True}
        created, updated = self.cmd._process_bto_term(term_data, update_existing=False)
        self.assertFalse(created)
        self.assertFalse(updated)
        self.assertFalse(BTOTerm.objects.filter(identifier="BTO:9999999").exists())

    def test_skips_bto_term_with_missing_name(self):
        term_data = {"id": "BTO:0000567"}
        created, updated = self.cmd._process_bto_term(term_data, update_existing=False)
        self.assertFalse(created)
        self.assertFalse(updated)

    def test_does_not_update_existing_without_flag(self):
        BTOTerm.objects.create(identifier="BTO:0000567", name="old name")
        term_data = {"id": "BTO:0000567", "name": "liver", "synonyms": [], "xrefs": [], "is_a": [], "part_of": []}
        created, updated = self.cmd._process_bto_term(term_data, update_existing=False)
        self.assertFalse(created)
        self.assertFalse(updated)
        self.assertEqual(BTOTerm.objects.get(identifier="BTO:0000567").name, "old name")

    def test_updates_existing_bto_term_with_flag(self):
        BTOTerm.objects.create(identifier="BTO:0000567", name="old name")
        term_data = {"id": "BTO:0000567", "name": "liver", "synonyms": [], "xrefs": [], "is_a": [], "part_of": []}
        created, updated = self.cmd._process_bto_term(term_data, update_existing=True)
        self.assertFalse(created)
        self.assertTrue(updated)
        self.assertEqual(BTOTerm.objects.get(identifier="BTO:0000567").name, "liver")


class ProcessDOIDTermTest(TestCase):
    """Unit tests for Command._process_doid_term."""

    def setUp(self):
        self.cmd = Command()
        self.cmd.stdout = StringIO()
        self.cmd.style = MagicMock()
        self.cmd.style.ERROR = lambda x: x

    def test_creates_new_doid_term(self):
        term_data = {
            "id": "DOID:9351",
            "name": "diabetes mellitus",
            "definition": "A metabolic disorder.",
            "synonyms": ["DM", "diabetes"],
            "xrefs": ["MeSH:D003920"],
            "is_a": ["DOID:4"],
        }
        created, updated = self.cmd._process_doid_term(term_data, update_existing=False)
        self.assertTrue(created)
        self.assertFalse(updated)
        obj = DiseaseOntologyTerm.objects.get(identifier="DOID:9351")
        self.assertEqual(obj.name, "diabetes mellitus")
        self.assertIn("DM", obj.synonyms)
        self.assertIn("DOID:4", obj.parent_terms)

    def test_skips_obsolete_doid_term(self):
        term_data = {"id": "DOID:0000001", "name": "obsolete disease", "obsolete": True}
        created, updated = self.cmd._process_doid_term(term_data, update_existing=False)
        self.assertFalse(created)
        self.assertFalse(updated)
        self.assertFalse(DiseaseOntologyTerm.objects.filter(identifier="DOID:0000001").exists())

    def test_skips_doid_term_with_missing_name(self):
        term_data = {"id": "DOID:9351"}
        created, updated = self.cmd._process_doid_term(term_data, update_existing=False)
        self.assertFalse(created)
        self.assertFalse(updated)

    def test_does_not_update_existing_without_flag(self):
        DiseaseOntologyTerm.objects.create(identifier="DOID:9351", name="old name")
        term_data = {"id": "DOID:9351", "name": "diabetes mellitus", "synonyms": [], "xrefs": [], "is_a": []}
        created, updated = self.cmd._process_doid_term(term_data, update_existing=False)
        self.assertFalse(created)
        self.assertFalse(updated)
        self.assertEqual(DiseaseOntologyTerm.objects.get(identifier="DOID:9351").name, "old name")

    def test_updates_existing_doid_term_with_flag(self):
        DiseaseOntologyTerm.objects.create(identifier="DOID:9351", name="old name")
        term_data = {"id": "DOID:9351", "name": "diabetes mellitus", "synonyms": [], "xrefs": [], "is_a": []}
        created, updated = self.cmd._process_doid_term(term_data, update_existing=True)
        self.assertFalse(created)
        self.assertTrue(updated)
        self.assertEqual(DiseaseOntologyTerm.objects.get(identifier="DOID:9351").name, "diabetes mellitus")


class LoadBTOCommandTest(TestCase):
    """Integration tests for Command.load_bto using mocked HTTP."""

    def setUp(self):
        self.cmd = Command()
        self.cmd.stdout = StringIO()
        self.cmd.style = MagicMock()
        self.cmd.style.ERROR = lambda x: x

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_bto_creates_terms(self, mock_get):
        mock_get.return_value = _make_mock_response(BTO_OBO_SAMPLE)

        created, updated = self.cmd.load_bto(update_existing=False)

        self.assertEqual(created, 3)
        self.assertEqual(updated, 0)
        self.assertTrue(BTOTerm.objects.filter(identifier="BTO:0000567").exists())
        self.assertTrue(BTOTerm.objects.filter(identifier="BTO:0000970").exists())

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_bto_skips_obsolete(self, mock_get):
        mock_get.return_value = _make_mock_response(BTO_OBO_SAMPLE)

        self.cmd.load_bto(update_existing=False)

        self.assertFalse(BTOTerm.objects.filter(identifier="BTO:9999999").exists())

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_bto_respects_limit(self, mock_get):
        mock_get.return_value = _make_mock_response(BTO_OBO_SAMPLE)

        created, _ = self.cmd.load_bto(update_existing=False, limit=1)

        self.assertEqual(created, 1)
        self.assertEqual(BTOTerm.objects.count(), 1)

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_bto_update_existing(self, mock_get):
        BTOTerm.objects.create(identifier="BTO:0000567", name="old name")
        mock_get.return_value = _make_mock_response(BTO_OBO_SAMPLE)

        created, updated = self.cmd.load_bto(update_existing=True)

        self.assertEqual(created, 2)
        self.assertEqual(updated, 1)
        self.assertEqual(BTOTerm.objects.get(identifier="BTO:0000567").name, "liver")

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_bto_handles_network_error(self, mock_get):
        import requests as req_lib

        mock_get.side_effect = req_lib.RequestException("connection error")

        created, updated = self.cmd.load_bto(update_existing=False)

        self.assertEqual(created, 0)
        self.assertEqual(updated, 0)
        self.assertEqual(BTOTerm.objects.count(), 0)

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_bto_stores_synonyms_and_xrefs(self, mock_get):
        mock_get.return_value = _make_mock_response(BTO_OBO_SAMPLE)

        self.cmd.load_bto(update_existing=False)

        liver = BTOTerm.objects.get(identifier="BTO:0000567")
        self.assertIn("hepar", liver.synonyms)
        self.assertIn("hepatic tissue", liver.synonyms)
        self.assertIn("Wikipedia", liver.xrefs)

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_bto_stores_parent_terms(self, mock_get):
        mock_get.return_value = _make_mock_response(BTO_OBO_SAMPLE)

        self.cmd.load_bto(update_existing=False)

        liver = BTOTerm.objects.get(identifier="BTO:0000567")
        self.assertIn("BTO:0000000", liver.parent_terms)


class LoadDOIDCommandTest(TestCase):
    """Integration tests for Command.load_doid using mocked HTTP."""

    def setUp(self):
        self.cmd = Command()
        self.cmd.stdout = StringIO()
        self.cmd.style = MagicMock()
        self.cmd.style.ERROR = lambda x: x

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_doid_creates_terms(self, mock_get):
        mock_get.return_value = _make_mock_response(DOID_OBO_SAMPLE)

        created, updated = self.cmd.load_doid(update_existing=False)

        self.assertEqual(created, 3)
        self.assertEqual(updated, 0)
        self.assertTrue(DiseaseOntologyTerm.objects.filter(identifier="DOID:9351").exists())
        self.assertTrue(DiseaseOntologyTerm.objects.filter(identifier="DOID:1612").exists())

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_doid_skips_obsolete(self, mock_get):
        mock_get.return_value = _make_mock_response(DOID_OBO_SAMPLE)

        self.cmd.load_doid(update_existing=False)

        self.assertFalse(DiseaseOntologyTerm.objects.filter(identifier="DOID:0000001").exists())

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_doid_respects_limit(self, mock_get):
        mock_get.return_value = _make_mock_response(DOID_OBO_SAMPLE)

        created, _ = self.cmd.load_doid(update_existing=False, limit=1)

        self.assertEqual(created, 1)
        self.assertEqual(DiseaseOntologyTerm.objects.count(), 1)

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_doid_update_existing(self, mock_get):
        DiseaseOntologyTerm.objects.create(identifier="DOID:9351", name="old name")
        mock_get.return_value = _make_mock_response(DOID_OBO_SAMPLE)

        created, updated = self.cmd.load_doid(update_existing=True)

        self.assertEqual(created, 2)
        self.assertEqual(updated, 1)
        self.assertEqual(DiseaseOntologyTerm.objects.get(identifier="DOID:9351").name, "diabetes mellitus")

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_doid_handles_network_error(self, mock_get):
        import requests as req_lib

        mock_get.side_effect = req_lib.RequestException("connection error")

        created, updated = self.cmd.load_doid(update_existing=False)

        self.assertEqual(created, 0)
        self.assertEqual(updated, 0)
        self.assertEqual(DiseaseOntologyTerm.objects.count(), 0)

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_doid_stores_synonyms_and_xrefs(self, mock_get):
        mock_get.return_value = _make_mock_response(DOID_OBO_SAMPLE)

        self.cmd.load_doid(update_existing=False)

        diabetes = DiseaseOntologyTerm.objects.get(identifier="DOID:9351")
        self.assertIn("DM", diabetes.synonyms)
        self.assertIn("MeSH:D003920", diabetes.xrefs)

    @patch("ccv.management.commands.load_ontologies.requests.get")
    def test_load_doid_stores_parent_terms(self, mock_get):
        mock_get.return_value = _make_mock_response(DOID_OBO_SAMPLE)

        self.cmd.load_doid(update_existing=False)

        diabetes = DiseaseOntologyTerm.objects.get(identifier="DOID:9351")
        self.assertIn("DOID:4", diabetes.parent_terms)
