"""
Test cases for load_ontologies management command, covering BTO, DOID, and ChEBI loading.

Tests cover OBO parsing, term processing, database persistence, update logic,
and error handling for the BTO, DOID, and ChEBI ontology loaders.
"""

import sqlite3
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase

from ccv.management.commands.export_mobile_snapshot import _dump_queryset
from ccv.management.commands.load_ontologies import Command, OBOParser
from ccv.models import BTOTerm, ChEBICompound, DiseaseOntologyTerm

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


CHEBI_OBO_SAMPLE = """\
format-version: 1.2
data-version: releases/2024-01-01
ontology: chebi

[Term]
id: CHEBI:15422
name: ATP
def: "A purine nucleoside triphosphate." [ChEBI:curator]
synonym: "adenosine 5'-triphosphate" EXACT []
synonym: "adenosine triphosphate" RELATED []
property_value: chemrof:generalized_empirical_formula "C10H16N5O13P3" xsd:string
property_value: chemrof:mass "507.18" xsd:decimal
property_value: chemrof:charge "-4" xsd:integer
property_value: chemrof:inchi_string "InChI=1S/C10H16N5O13P3" xsd:string
property_value: chemrof:smiles "Nc1ncnc2c1ncn2[C@@H]1O" xsd:string
is_a: CHEBI:25372 ! purine ribonucleoside triphosphate
relationship: has_role CHEBI:25212 ! biological role

[Term]
id: CHEBI:17234
name: glucose
def: "A monosaccharide." [ChEBI:curator]
property_value: chemrof:generalized_empirical_formula "C6H12O6" xsd:string
property_value: chemrof:mass "180.16" xsd:decimal
is_a: CHEBI:25372 ! monosaccharide

[Term]
id: CHEBI:99999
name: obsolete compound
is_obsolete: true
replaced_by: CHEBI:15422
"""


class ParseChEBIPropertyTest(TestCase):
    """Unit tests for Command._parse_chebi_property covering both legacy and current ChEBI OBO formats."""

    def setUp(self):
        self.cmd = Command()
        self.cmd.stdout = StringIO()
        self.cmd.style = MagicMock()

    def test_chemrof_mass(self):
        props = {}
        self.cmd._parse_chebi_property(props, 'chemrof:mass "507.18" xsd:decimal')
        self.assertAlmostEqual(props["mass"], 507.18)

    def test_chemrof_formula(self):
        props = {}
        self.cmd._parse_chebi_property(props, 'chemrof:generalized_empirical_formula "C10H16N5O13P3" xsd:string')
        self.assertEqual(props["formula"], "C10H16N5O13P3")

    def test_chemrof_charge(self):
        props = {}
        self.cmd._parse_chebi_property(props, 'chemrof:charge "0" xsd:integer')
        self.assertEqual(props["charge"], 0)

    def test_chemrof_negative_charge(self):
        props = {}
        self.cmd._parse_chebi_property(props, 'chemrof:charge "-4" xsd:integer')
        self.assertEqual(props["charge"], -4)

    def test_chemrof_inchi(self):
        props = {}
        self.cmd._parse_chebi_property(props, 'chemrof:inchi_string "InChI=1S/C10H16N5O13P3" xsd:string')
        self.assertEqual(props["inchi"], "InChI=1S/C10H16N5O13P3")

    def test_chemrof_smiles(self):
        props = {}
        self.cmd._parse_chebi_property(props, 'chemrof:smiles "Nc1ncnc2c1ncn2[C@@H]1O" xsd:string')
        self.assertEqual(props["smiles"], "Nc1ncnc2c1ncn2[C@@H]1O")

    def test_legacy_mass(self):
        props = {}
        self.cmd._parse_chebi_property(props, 'http://purl.obolibrary.org/obo/chebi/mass "507.18" xsd:string')
        self.assertAlmostEqual(props["mass"], 507.18)

    def test_legacy_formula(self):
        props = {}
        self.cmd._parse_chebi_property(props, 'http://purl.obolibrary.org/obo/chebi/formula "C10H16N5O13P3" xsd:string')
        self.assertEqual(props["formula"], "C10H16N5O13P3")

    def test_legacy_charge(self):
        props = {}
        self.cmd._parse_chebi_property(props, 'http://purl.obolibrary.org/obo/chebi/charge "-4" xsd:string')
        self.assertEqual(props["charge"], -4)

    def test_legacy_inchi(self):
        props = {}
        self.cmd._parse_chebi_property(
            props, 'http://purl.obolibrary.org/obo/chebi/inchi "InChI=1S/C10H16N5O13P3" xsd:string'
        )
        self.assertEqual(props["inchi"], "InChI=1S/C10H16N5O13P3")

    def test_legacy_smiles(self):
        props = {}
        self.cmd._parse_chebi_property(
            props, 'http://purl.obolibrary.org/obo/chebi/smiles "Nc1ncnc2c1ncn2[C@@H]1O" xsd:string'
        )
        self.assertEqual(props["smiles"], "Nc1ncnc2c1ncn2[C@@H]1O")

    def test_legacy_monoisotopic_mass_used_when_no_regular_mass(self):
        props = {}
        self.cmd._parse_chebi_property(
            props, 'http://purl.obolibrary.org/obo/chebi/monoisotopicmass "506.99577" xsd:string'
        )
        self.assertAlmostEqual(props["mass"], 506.99577)

    def test_legacy_regular_mass_takes_priority_over_monoisotopic(self):
        props = {"mass": 507.18}
        self.cmd._parse_chebi_property(
            props, 'http://purl.obolibrary.org/obo/chebi/monoisotopicmass "506.99577" xsd:string'
        )
        self.assertAlmostEqual(props["mass"], 507.18)

    def test_ignores_non_chebi_property(self):
        props = {}
        self.cmd._parse_chebi_property(props, 'foaf:homepage "https://www.ebi.ac.uk/chebi" xsd:anyURI')
        self.assertNotIn("mass", props)

    def test_handles_invalid_mass_value(self):
        props = {}
        self.cmd._parse_chebi_property(props, 'chemrof:mass "not_a_number" xsd:decimal')
        self.assertNotIn("mass", props)

    def test_handles_invalid_charge_value(self):
        props = {}
        self.cmd._parse_chebi_property(props, 'chemrof:charge "unknown" xsd:integer')
        self.assertNotIn("charge", props)

    def test_handles_missing_quoted_value(self):
        props = {}
        self.cmd._parse_chebi_property(props, "chemrof:mass 507.18 xsd:decimal")
        self.assertNotIn("mass", props)


class ParseChEBIOBOTest(TestCase):
    """Unit tests for ChEBI OBO parsing via _parse_chebi_with_progress."""

    def setUp(self):
        self.cmd = Command()
        self.cmd.stdout = StringIO()
        self.cmd.style = MagicMock()

    def _parse(self):
        return self.cmd._parse_chebi_with_progress(CHEBI_OBO_SAMPLE)

    def test_parses_term_count(self):
        terms = self._parse()
        chebi_terms = [t for t in terms if t.get("id", "").startswith("CHEBI:")]
        self.assertEqual(len(chebi_terms), 3)

    def test_parses_id_and_name(self):
        terms = self._parse()
        atp = next(t for t in terms if t.get("id") == "CHEBI:15422")
        self.assertEqual(atp["name"], "ATP")

    def test_parses_synonyms(self):
        terms = self._parse()
        atp = next(t for t in terms if t.get("id") == "CHEBI:15422")
        self.assertIn("adenosine triphosphate", atp["synonyms"])

    def test_parses_mass_property(self):
        terms = self._parse()
        atp = next(t for t in terms if t.get("id") == "CHEBI:15422")
        self.assertAlmostEqual(atp["properties"]["mass"], 507.18)

    def test_parses_formula_property(self):
        terms = self._parse()
        atp = next(t for t in terms if t.get("id") == "CHEBI:15422")
        self.assertEqual(atp["properties"]["formula"], "C10H16N5O13P3")

    def test_parses_charge_property(self):
        terms = self._parse()
        atp = next(t for t in terms if t.get("id") == "CHEBI:15422")
        self.assertEqual(atp["properties"]["charge"], -4)

    def test_parses_inchi_property(self):
        terms = self._parse()
        atp = next(t for t in terms if t.get("id") == "CHEBI:15422")
        self.assertEqual(atp["properties"]["inchi"], "InChI=1S/C10H16N5O13P3")

    def test_parses_smiles_property(self):
        terms = self._parse()
        atp = next(t for t in terms if t.get("id") == "CHEBI:15422")
        self.assertEqual(atp["properties"]["smiles"], "Nc1ncnc2c1ncn2[C@@H]1O")

    def test_mass_parsed_for_glucose(self):
        terms = self._parse()
        glucose = next(t for t in terms if t.get("id") == "CHEBI:17234")
        self.assertAlmostEqual(glucose["properties"]["mass"], 180.16)

    def test_parses_obsolete_flag(self):
        terms = self._parse()
        obsolete = next(t for t in terms if t.get("id") == "CHEBI:99999")
        self.assertTrue(obsolete["obsolete"])

    def test_parses_parent_terms(self):
        terms = self._parse()
        atp = next(t for t in terms if t.get("id") == "CHEBI:15422")
        self.assertIn("CHEBI:25372", atp["is_a"])

    def test_parses_roles_relationship(self):
        terms = self._parse()
        atp = next(t for t in terms if t.get("id") == "CHEBI:15422")
        role_rels = [r for r in atp.get("relationships", []) if r.startswith("has_role")]
        self.assertTrue(len(role_rels) > 0)


class PrepareChEBICompoundTest(TestCase):
    """Unit tests for Command._prepare_chebi_compound."""

    def setUp(self):
        self.cmd = Command()
        self.cmd.stdout = StringIO()
        self.cmd.style = MagicMock()

    def _atp_term_data(self):
        return {
            "id": "CHEBI:15422",
            "name": "ATP",
            "definition": "A purine nucleoside triphosphate.",
            "synonyms": ["adenosine 5'-triphosphate"],
            "is_a": ["CHEBI:25372"],
            "relationships": ["has_role CHEBI:25212 ! biological role"],
            "properties": {
                "formula": "C10H16N5O13P3",
                "mass": 507.18,
                "charge": -4,
                "inchi": "InChI=1S/C10H16N5O13P3",
                "smiles": "Nc1ncnc2c1ncn2[C@@H]1O",
            },
        }

    def test_maps_mass_to_compound_data(self):
        data = self.cmd._prepare_chebi_compound(self._atp_term_data(), "all")
        self.assertAlmostEqual(data["mass"], 507.18)

    def test_maps_formula_to_compound_data(self):
        data = self.cmd._prepare_chebi_compound(self._atp_term_data(), "all")
        self.assertEqual(data["formula"], "C10H16N5O13P3")

    def test_maps_charge_to_compound_data(self):
        data = self.cmd._prepare_chebi_compound(self._atp_term_data(), "all")
        self.assertEqual(data["charge"], -4)

    def test_maps_inchi_to_compound_data(self):
        data = self.cmd._prepare_chebi_compound(self._atp_term_data(), "all")
        self.assertEqual(data["inchi"], "InChI=1S/C10H16N5O13P3")

    def test_maps_smiles_to_compound_data(self):
        data = self.cmd._prepare_chebi_compound(self._atp_term_data(), "all")
        self.assertEqual(data["smiles"], "Nc1ncnc2c1ncn2[C@@H]1O")

    def test_mass_is_none_when_not_in_properties(self):
        term = self._atp_term_data()
        term["properties"] = {}
        data = self.cmd._prepare_chebi_compound(term, "all")
        self.assertIsNone(data["mass"])

    def test_skips_obsolete_term(self):
        term = self._atp_term_data()
        term["obsolete"] = True
        self.assertIsNone(self.cmd._prepare_chebi_compound(term, "all"))

    def test_skips_term_without_name(self):
        term = self._atp_term_data()
        term["name"] = ""
        self.assertIsNone(self.cmd._prepare_chebi_compound(term, "all"))

    def test_roles_extracted_from_relationships(self):
        data = self.cmd._prepare_chebi_compound(self._atp_term_data(), "all")
        self.assertIn("biological role", data["roles"])


class BatchProcessChEBICompoundsTest(TestCase):
    """Unit tests for Command._batch_process_chebi_compounds (DB persistence)."""

    def setUp(self):
        self.cmd = Command()
        self.cmd.stdout = StringIO()
        self.cmd.style = MagicMock()

    def _atp_compound_data(self):
        return {
            "identifier": "CHEBI:15422",
            "name": "ATP",
            "definition": "A purine nucleoside triphosphate.",
            "synonyms": "adenosine 5'-triphosphate",
            "formula": "C10H16N5O13P3",
            "mass": 507.18,
            "charge": -4,
            "inchi": "InChI=1S/C10H16N5O13P3",
            "smiles": "Nc1ncnc2c1ncn2[C@@H]1O",
            "parent_terms": "CHEBI:25372",
            "roles": "biological role",
            "replacement_term": "",
        }

    def test_creates_compound_with_mass(self):
        self.cmd._batch_process_chebi_compounds([self._atp_compound_data()], update_existing=False)
        compound = ChEBICompound.objects.get(identifier="CHEBI:15422")
        self.assertAlmostEqual(compound.mass, 507.18)

    def test_creates_compound_with_formula(self):
        self.cmd._batch_process_chebi_compounds([self._atp_compound_data()], update_existing=False)
        compound = ChEBICompound.objects.get(identifier="CHEBI:15422")
        self.assertEqual(compound.formula, "C10H16N5O13P3")

    def test_creates_compound_with_charge(self):
        self.cmd._batch_process_chebi_compounds([self._atp_compound_data()], update_existing=False)
        compound = ChEBICompound.objects.get(identifier="CHEBI:15422")
        self.assertEqual(compound.charge, -4)

    def test_creates_compound_with_inchi(self):
        self.cmd._batch_process_chebi_compounds([self._atp_compound_data()], update_existing=False)
        compound = ChEBICompound.objects.get(identifier="CHEBI:15422")
        self.assertEqual(compound.inchi, "InChI=1S/C10H16N5O13P3")

    def test_creates_compound_with_smiles(self):
        self.cmd._batch_process_chebi_compounds([self._atp_compound_data()], update_existing=False)
        compound = ChEBICompound.objects.get(identifier="CHEBI:15422")
        self.assertEqual(compound.smiles, "Nc1ncnc2c1ncn2[C@@H]1O")

    def test_null_mass_stored_correctly(self):
        data = self._atp_compound_data()
        data["mass"] = None
        self.cmd._batch_process_chebi_compounds([data], update_existing=False)
        compound = ChEBICompound.objects.get(identifier="CHEBI:15422")
        self.assertIsNone(compound.mass)

    def test_updates_existing_compound(self):
        ChEBICompound.objects.create(identifier="CHEBI:15422", name="old", mass=None)
        self.cmd._batch_process_chebi_compounds([self._atp_compound_data()], update_existing=True)
        compound = ChEBICompound.objects.get(identifier="CHEBI:15422")
        self.assertAlmostEqual(compound.mass, 507.18)
        self.assertEqual(compound.name, "ATP")


class ChEBIExportSnapshotTest(TestCase):
    """Integration tests verifying that mass and other chemical fields survive the SQLite export."""

    def setUp(self):
        ChEBICompound.objects.create(
            identifier="CHEBI:15422",
            name="ATP",
            formula="C10H16N5O13P3",
            mass=507.18,
            charge=-4,
            inchi="InChI=1S/C10H16N5O13P3",
            smiles="Nc1ncnc2c1ncn2[C@@H]1O",
        )
        ChEBICompound.objects.create(
            identifier="CHEBI:17234",
            name="glucose",
            formula="C6H12O6",
            mass=None,
        )

    def _export_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            sqlite_path = Path(tmp) / "chebi.sqlite"
            _dump_queryset(ChEBICompound.objects.all().order_by("identifier"), "chebi", sqlite_path)
            conn = sqlite3.connect(sqlite_path)
            conn.row_factory = sqlite3.Row
            rows = {row["identifier"]: dict(row) for row in conn.execute("SELECT * FROM chebi")}
            conn.close()
        return rows

    def test_mass_exported_for_compound_with_value(self):
        rows = self._export_and_read()
        self.assertAlmostEqual(rows["CHEBI:15422"]["mass"], 507.18)

    def test_mass_exported_as_null_when_not_set(self):
        rows = self._export_and_read()
        self.assertIsNone(rows["CHEBI:17234"]["mass"])

    def test_formula_exported(self):
        rows = self._export_and_read()
        self.assertEqual(rows["CHEBI:15422"]["formula"], "C10H16N5O13P3")

    def test_charge_exported(self):
        rows = self._export_and_read()
        self.assertEqual(rows["CHEBI:15422"]["charge"], -4)

    def test_inchi_exported(self):
        rows = self._export_and_read()
        self.assertEqual(rows["CHEBI:15422"]["inchi"], "InChI=1S/C10H16N5O13P3")

    def test_smiles_exported(self):
        rows = self._export_and_read()
        self.assertEqual(rows["CHEBI:15422"]["smiles"], "Nc1ncnc2c1ncn2[C@@H]1O")

    def test_both_compounds_exported(self):
        rows = self._export_and_read()
        self.assertIn("CHEBI:15422", rows)
        self.assertIn("CHEBI:17234", rows)
