"""
Tests for ccv/ontology_registry.py and its integration with configure_ontology_options.

Covers:
- Registry completeness: all 14 types and all SDRF names registered
- Descriptor field correctness against the actual DB schema
- SdrfMapping.resolve_filter() for all column-name-hint cases
- OntologyDescriptor.serialize() output shape and Unimod custom serializer
- configure_ontology_options template state for each SDRF ontology name
- DB-backed queryset filtering (custom_filters, obsolete_filter)
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from django.apps import apps
from django.test import TestCase

from ccv.models import (
    BTOTerm,
    CellOntology,
    ChEBICompound,
    DiseaseOntologyTerm,
    HumanDisease,
    MondoDisease,
    MSUniqueVocabularies,
    NCBITaxonomy,
    PSIMSOntology,
    Species,
    SubcellularLocation,
    Tissue,
    UberonAnatomy,
    Unimod,
)
from ccv.ontology_registry import _serialize_unimod, registry

EXPECTED_TYPE_KEYS = [
    "species",
    "tissue",
    "human_disease",
    "subcellular_location",
    "unimod",
    "ms_unique_vocabularies",
    "ncbi_taxonomy",
    "chebi",
    "mondo",
    "uberon",
    "cell_ontology",
    "psi_ms",
    "bto",
    "doid",
]

EXPECTED_SDRF_NAMES = [
    "ncbitaxon",
    "cl",
    "unimod",
    "uberon",
    "bto",
    "chebi",
    "doid",
    "mondo",
    "pride",
    "clo",
    "hancestro",
    "pato",
    "efo",
    "ms",
]

MODEL_LABEL_MAP = {
    "species": "ccv.Species",
    "tissue": "ccv.Tissue",
    "human_disease": "ccv.HumanDisease",
    "subcellular_location": "ccv.SubcellularLocation",
    "unimod": "ccv.Unimod",
    "ms_unique_vocabularies": "ccv.MSUniqueVocabularies",
    "ncbi_taxonomy": "ccv.NCBITaxonomy",
    "chebi": "ccv.ChEBICompound",
    "mondo": "ccv.MondoDisease",
    "uberon": "ccv.UberonAnatomy",
    "cell_ontology": "ccv.CellOntology",
    "psi_ms": "ccv.PSIMSOntology",
    "bto": "ccv.BTOTerm",
    "doid": "ccv.DiseaseOntologyTerm",
}

EXPECTED_MODEL_CLASSES = {
    "species": Species,
    "tissue": Tissue,
    "human_disease": HumanDisease,
    "subcellular_location": SubcellularLocation,
    "unimod": Unimod,
    "ms_unique_vocabularies": MSUniqueVocabularies,
    "ncbi_taxonomy": NCBITaxonomy,
    "chebi": ChEBICompound,
    "mondo": MondoDisease,
    "uberon": UberonAnatomy,
    "cell_ontology": CellOntology,
    "psi_ms": PSIMSOntology,
    "bto": BTOTerm,
    "doid": DiseaseOntologyTerm,
}


def _make_validator(ontologies, examples=None):
    """Build a mock SDRF ontology validator."""
    return SimpleNamespace(
        validator_name="ontology",
        params={"ontologies": ontologies, "examples": examples or []},
    )


def _make_column(validators):
    """Build a mock SDRF column with given validators."""
    return SimpleNamespace(validators=validators)


def _make_template(column_name="characteristics[organism]"):
    """Build a mock MetadataColumnTemplate with default fields."""
    tmpl = MagicMock()
    tmpl.column_name = column_name
    tmpl.enable_typeahead = False
    tmpl.ontology_options = []
    tmpl.ontology_type = None
    tmpl.possible_default_values = []
    tmpl.custom_ontology_filters = {}
    return tmpl


class RegistryCompletenessTest(TestCase):
    """Verify all required type_keys and SDRF names are registered."""

    def test_all_type_keys_registered(self):
        """All 14 ontology type_keys must be present in the registry."""
        registered = set(registry._descriptors.keys())
        for key in EXPECTED_TYPE_KEYS:
            self.assertIn(key, registered, f"Missing type_key: {key}")

    def test_no_unexpected_type_keys(self):
        """Registry must not contain undocumented type_keys."""
        registered = set(registry._descriptors.keys())
        self.assertEqual(registered, set(EXPECTED_TYPE_KEYS))

    def test_all_sdrf_names_registered(self):
        """All 14 SDRF short-names must have at least one mapping."""
        for name in EXPECTED_SDRF_NAMES:
            self.assertTrue(
                len(registry.get_sdrf_mappings(name)) > 0,
                f"No SdrfMapping for SDRF name: {name}",
            )

    def test_choices_returns_all_types(self):
        """choices() must return one (type_key, label) tuple per registered type."""
        choices = registry.choices()
        self.assertEqual(len(choices), len(EXPECTED_TYPE_KEYS))
        keys = [c[0] for c in choices]
        for key in EXPECTED_TYPE_KEYS:
            self.assertIn(key, keys)

    def test_get_returns_correct_descriptor(self):
        """get() must return the descriptor with the matching type_key."""
        for key in EXPECTED_TYPE_KEYS:
            desc = registry.get(key)
            self.assertIsNotNone(desc, f"registry.get({key!r}) returned None")
            self.assertEqual(desc.type_key, key)

    def test_get_unknown_returns_none(self):
        """get() must return None for an unregistered type_key."""
        self.assertIsNone(registry.get("nonexistent_type"))


class DescriptorFieldCorrectnessTest(TestCase):
    """Verify descriptor field names exist on the actual model."""

    def _assert_fields_exist(self, type_key, fields):
        desc = registry.get(type_key)
        model = apps.get_model(desc.model_label)
        model_field_names = {f.name for f in model._meta.get_fields()}
        for field in fields:
            self.assertIn(field, model_field_names, f"{type_key}: field {field!r} not on model")

    def test_model_labels_resolve(self):
        """Every model_label must resolve to the expected model class."""
        for key, expected_class in EXPECTED_MODEL_CLASSES.items():
            desc = registry.get(key)
            self.assertEqual(desc.model_label, MODEL_LABEL_MAP[key])
            self.assertIs(desc.model, expected_class)

    def test_species_fields_exist(self):
        self._assert_fields_exist(
            "species",
            ["code", "taxon", "official_name", "common_name", "synonym"],
        )

    def test_tissue_fields_exist(self):
        self._assert_fields_exist("tissue", ["identifier", "accession", "synonyms", "cross_references"])

    def test_human_disease_fields_exist(self):
        self._assert_fields_exist(
            "human_disease",
            ["identifier", "acronym", "accession", "definition", "synonyms", "cross_references", "keywords"],
        )

    def test_subcellular_location_fields_exist(self):
        self._assert_fields_exist(
            "subcellular_location",
            ["location_identifier", "accession", "definition", "synonyms", "content"],
        )

    def test_unimod_fields_exist(self):
        self._assert_fields_exist("unimod", ["accession", "name", "definition", "additional_data"])

    def test_ms_unique_vocabularies_fields_exist(self):
        self._assert_fields_exist(
            "ms_unique_vocabularies",
            ["accession", "name", "definition", "term_type"],
        )

    def test_ncbi_taxonomy_fields_exist(self):
        self._assert_fields_exist(
            "ncbi_taxonomy",
            ["tax_id", "scientific_name", "common_name", "synonyms", "rank"],
        )

    def test_chebi_fields_exist(self):
        self._assert_fields_exist(
            "chebi",
            ["identifier", "name", "definition", "synonyms", "formula", "mass", "charge"],
        )

    def test_mondo_fields_exist(self):
        self._assert_fields_exist(
            "mondo",
            ["identifier", "name", "definition", "synonyms", "xrefs", "parent_terms", "obsolete", "replacement_term"],
        )

    def test_uberon_fields_exist(self):
        self._assert_fields_exist(
            "uberon",
            ["identifier", "name", "definition", "synonyms", "xrefs", "parent_terms", "obsolete"],
        )

    def test_cell_ontology_fields_exist(self):
        self._assert_fields_exist(
            "cell_ontology",
            [
                "identifier",
                "name",
                "definition",
                "synonyms",
                "organism",
                "tissue_origin",
                "cell_line",
                "obsolete",
                "replacement_term",
            ],
        )

    def test_psi_ms_fields_exist(self):
        self._assert_fields_exist(
            "psi_ms",
            [
                "identifier",
                "name",
                "definition",
                "synonyms",
                "parent_terms",
                "category",
                "obsolete",
                "replacement_term",
            ],
        )

    def test_bto_fields_exist(self):
        self._assert_fields_exist(
            "bto",
            [
                "identifier",
                "name",
                "definition",
                "synonyms",
                "xrefs",
                "parent_terms",
                "part_of",
                "obsolete",
                "replacement_term",
            ],
        )

    def test_doid_fields_exist(self):
        self._assert_fields_exist(
            "doid",
            ["identifier", "name", "definition", "synonyms", "xrefs", "parent_terms", "obsolete", "replacement_term"],
        )

    def test_full_data_fields_exist_on_models(self):
        """Every field in full_data_fields must exist on the corresponding model."""
        for key in EXPECTED_TYPE_KEYS:
            desc = registry.get(key)
            model = apps.get_model(desc.model_label)
            model_field_names = {f.name for f in model._meta.get_fields()}
            for field in desc.full_data_fields:
                self.assertIn(
                    field,
                    model_field_names,
                    f"{key}: full_data_fields entry {field!r} not on model {desc.model_label}",
                )

    def test_search_fields_exist_on_models(self):
        """Every field in search_fields must exist on the corresponding model."""
        for key in EXPECTED_TYPE_KEYS:
            desc = registry.get(key)
            model = apps.get_model(desc.model_label)
            model_field_names = {f.name for f in model._meta.get_fields()}
            for field in desc.search_fields:
                self.assertIn(
                    field,
                    model_field_names,
                    f"{key}: search_fields entry {field!r} not on model {desc.model_label}",
                )

    def test_id_field_exists_on_models(self):
        """id_field and id_fallback_field must exist on each model."""
        for key in EXPECTED_TYPE_KEYS:
            desc = registry.get(key)
            model = apps.get_model(desc.model_label)
            model_field_names = {f.name for f in model._meta.get_fields()}
            self.assertIn(
                desc.id_field,
                model_field_names,
                f"{key}: id_field {desc.id_field!r} not on model",
            )
            if desc.id_fallback_field:
                self.assertIn(
                    desc.id_fallback_field,
                    model_field_names,
                    f"{key}: id_fallback_field {desc.id_fallback_field!r} not on model",
                )

    def test_value_field_exists_on_models(self):
        """value_field and value_fallback_field must exist on each model."""
        for key in EXPECTED_TYPE_KEYS:
            desc = registry.get(key)
            model = apps.get_model(desc.model_label)
            model_field_names = {f.name for f in model._meta.get_fields()}
            self.assertIn(
                desc.value_field,
                model_field_names,
                f"{key}: value_field {desc.value_field!r} not on model",
            )
            if desc.value_fallback_field:
                self.assertIn(
                    desc.value_fallback_field,
                    model_field_names,
                    f"{key}: value_fallback_field {desc.value_fallback_field!r} not on model",
                )

    def test_display_field_exists_on_models(self):
        """display_field and display_fallback_field must exist on each model."""
        for key in EXPECTED_TYPE_KEYS:
            desc = registry.get(key)
            model = apps.get_model(desc.model_label)
            model_field_names = {f.name for f in model._meta.get_fields()}
            self.assertIn(
                desc.display_field,
                model_field_names,
                f"{key}: display_field {desc.display_field!r} not on model",
            )
            if desc.display_fallback_field:
                self.assertIn(
                    desc.display_fallback_field,
                    model_field_names,
                    f"{key}: display_fallback_field {desc.display_fallback_field!r} not on model",
                )


class SdrfMappingPrimaryFlagsTest(TestCase):
    """Verify is_primary flags are correct for dual-mapped SDRF names."""

    def test_ncbitaxon_species_is_primary(self):
        mappings = registry.get_sdrf_mappings("ncbitaxon")
        primary = [m for m in mappings if m.is_primary]
        secondary = [m for m in mappings if not m.is_primary]
        self.assertEqual([m.type_key for m in primary], ["species"])
        self.assertEqual([m.type_key for m in secondary], ["ncbi_taxonomy"])

    def test_mondo_human_disease_is_primary(self):
        mappings = registry.get_sdrf_mappings("mondo")
        primary = [m for m in mappings if m.is_primary]
        secondary = [m for m in mappings if not m.is_primary]
        self.assertEqual([m.type_key for m in primary], ["human_disease"])
        self.assertEqual([m.type_key for m in secondary], ["mondo"])

    def test_single_mapped_sdrf_names_are_primary(self):
        single_sdrf = [
            "cl",
            "unimod",
            "uberon",
            "bto",
            "chebi",
            "doid",
            "pride",
            "clo",
            "hancestro",
            "pato",
            "efo",
            "ms",
        ]
        for name in single_sdrf:
            mappings = registry.get_sdrf_mappings(name)
            for m in mappings:
                self.assertTrue(m.is_primary, f"{name} mapping for {m.type_key} should be primary")


class SdrfMappingResolveFilterTest(TestCase):
    """Verify SdrfMapping.resolve_filter() for every column-name hint."""

    def _mapping(self, sdrf_name):
        mappings = registry.get_sdrf_mappings(sdrf_name)
        self.assertEqual(len(mappings), 1, f"Expected single mapping for {sdrf_name}")
        return mappings[0]

    def test_ms_instrument(self):
        m = self._mapping("ms")
        self.assertEqual(m.resolve_filter("comment[instrument]"), {"term_type": "instrument"})

    def test_ms_mass_analyzer(self):
        m = self._mapping("ms")
        self.assertEqual(m.resolve_filter("comment[mass analyzer type]"), {"term_type": "mass analyzer type"})

    def test_ms_analyzer_keyword(self):
        m = self._mapping("ms")
        self.assertEqual(m.resolve_filter("characteristics[analyzer]"), {"term_type": "mass analyzer type"})

    def test_ms_cleavage(self):
        m = self._mapping("ms")
        self.assertEqual(m.resolve_filter("comment[cleavage agent details]"), {"term_type": "cleavage agent"})

    def test_ms_dissociation(self):
        m = self._mapping("ms")
        self.assertEqual(m.resolve_filter("comment[dissociation method]"), {"term_type": "dissociation method"})

    def test_ms_reduction(self):
        m = self._mapping("ms")
        self.assertEqual(m.resolve_filter("comment[reduction reagent]"), {"term_type": "reduction reagent"})

    def test_ms_alkylation(self):
        m = self._mapping("ms")
        self.assertEqual(m.resolve_filter("comment[alkylation reagent]"), {"term_type": "alkylation reagent"})

    def test_ms_unrecognized_column_returns_none(self):
        m = self._mapping("ms")
        self.assertIsNone(m.resolve_filter("characteristics[organism]"))

    def test_efo_cell_line(self):
        m = self._mapping("efo")
        self.assertEqual(m.resolve_filter("characteristics[cell line]"), {"term_type": "cell line"})

    def test_efo_developmental_stage(self):
        m = self._mapping("efo")
        self.assertEqual(
            m.resolve_filter("characteristics[developmental stage]"),
            {"term_type": "developmental stage"},
        )

    def test_efo_enrichment(self):
        m = self._mapping("efo")
        self.assertEqual(
            m.resolve_filter("comment[enrichment process]"),
            {"term_type": "enrichment process"},
        )

    def test_efo_unrecognized_column_returns_none(self):
        m = self._mapping("efo")
        self.assertIsNone(m.resolve_filter("characteristics[disease]"))

    def test_pato_any_column(self):
        m = self._mapping("pato")
        self.assertEqual(m.resolve_filter("characteristics[sex]"), {"term_type": "sex"})
        self.assertEqual(m.resolve_filter("anything"), {"term_type": "sex"})

    def test_hancestro_any_column(self):
        m = self._mapping("hancestro")
        self.assertEqual(m.resolve_filter("characteristics[ancestry category]"), {"term_type": "ancestral category"})

    def test_pride_any_column(self):
        m = self._mapping("pride")
        self.assertEqual(m.resolve_filter("characteristics[label]"), {"term_type": "sample attribute"})

    def test_clo_any_column(self):
        m = self._mapping("clo")
        self.assertEqual(m.resolve_filter("characteristics[cell line]"), {"term_type": "cell line"})


class SerializerOutputShapeTest(TestCase):
    """Verify OntologyDescriptor.serialize() produces the expected output keys and values."""

    REQUIRED_KEYS = {"id", "value", "display_name", "description", "ontology_type", "full_data"}

    def _check_shape(self, type_key, data):
        desc = registry.get(type_key)
        result = desc.serialize(data)
        self.assertEqual(set(result.keys()), self.REQUIRED_KEYS, f"{type_key}: wrong output keys")
        self.assertEqual(result["ontology_type"], type_key)
        return result

    def test_species_serializer(self):
        result = self._check_shape(
            "species",
            {
                "code": "HUMAN",
                "taxon": 9606,
                "official_name": "Homo sapiens",
                "common_name": "Human",
                "synonym": "H. sapiens",
            },
        )
        self.assertEqual(result["id"], "9606")
        self.assertEqual(result["display_name"], "Homo sapiens")

    def test_tissue_serializer(self):
        result = self._check_shape(
            "tissue",
            {
                "identifier": "liver",
                "accession": "UBERON:0002107",
                "synonyms": "hepar",
                "cross_references": None,
            },
        )
        self.assertEqual(result["id"], "UBERON:0002107")
        self.assertEqual(result["value"], "liver")

    def test_ms_unique_vocabularies_serializer(self):
        result = self._check_shape(
            "ms_unique_vocabularies",
            {
                "accession": "MS:1000702",
                "name": "micrOTOF",
                "definition": "Bruker instrument.",
                "term_type": "instrument",
            },
        )
        self.assertEqual(result["id"], "MS:1000702")
        self.assertEqual(result["value"], "MS:1000702")
        self.assertEqual(result["display_name"], "micrOTOF")

    def test_human_disease_serializer(self):
        result = self._check_shape(
            "human_disease",
            {
                "identifier": "breast carcinoma",
                "acronym": "BC",
                "accession": "DI-04240",
                "definition": "A carcinoma.",
                "synonyms": "breast cancer",
                "cross_references": "",
                "keywords": "",
            },
        )
        self.assertEqual(result["id"], "DI-04240")
        self.assertEqual(result["display_name"], "breast carcinoma")

    def test_subcellular_location_serializer(self):
        result = self._check_shape(
            "subcellular_location",
            {
                "accession": "SL-0476",
                "location_identifier": "A band",
                "definition": "Sarcomere region.",
                "synonyms": "A-band",
                "content": "",
            },
        )
        self.assertEqual(result["id"], "SL-0476")
        self.assertEqual(result["value"], "A band")

    def test_ncbi_taxonomy_serializer(self):
        result = self._check_shape(
            "ncbi_taxonomy",
            {
                "tax_id": 9606,
                "scientific_name": "Homo sapiens",
                "common_name": "human",
                "synonyms": "",
                "rank": "species",
            },
        )
        self.assertEqual(result["id"], "9606")
        self.assertEqual(result["display_name"], "Homo sapiens")

    def test_unimod_uses_custom_serializer(self):
        data = {
            "accession": "UNIMOD:4",
            "name": "Carbamidomethyl",
            "definition": "Carbamidomethylation.",
            "additional_data": [
                {"id": "delta_mono_mass", "description": "57.021464"},
                {"id": "delta_composition", "description": "H(3) C(2) N O"},
                {"id": "spec_1_site", "description": "C"},
                {"id": "spec_1_position", "description": "Anywhere"},
            ],
        }
        result = self._check_shape("unimod", data)
        self.assertEqual(result["id"], "UNIMOD:4")
        self.assertIn("general_properties", result["full_data"])
        self.assertIn("specifications", result["full_data"])
        self.assertEqual(result["full_data"]["general_properties"]["delta_mono_mass"], "57.021464")
        self.assertIn("1", result["full_data"]["specifications"])

    def test_registry_serialize_fallback_for_unknown_type(self):
        """serialize() with unknown type_key must still return the five required keys."""
        result = registry.serialize("unknown_type", {"accession": "X:001", "name": "test"})
        self.assertIn("id", result)
        self.assertIn("ontology_type", result)
        self.assertEqual(result["ontology_type"], "unknown_type")


class UnimodCustomSerializerTest(TestCase):
    """Unit-test _serialize_unimod in isolation."""

    def test_general_properties_extracted(self):
        data = {
            "accession": "UNIMOD:1",
            "name": "Acetyl",
            "definition": "Acetylation.",
            "additional_data": [
                {"id": "delta_mono_mass", "description": "42.010565"},
                {"id": "delta_avge_mass", "description": "42.0373"},
                {"id": "approved", "description": "1"},
            ],
        }
        result = _serialize_unimod(data, "unimod")
        self.assertEqual(result["full_data"]["general_properties"]["delta_mono_mass"], "42.010565")
        self.assertEqual(result["full_data"]["delta_mono_mass"], "42.010565")
        self.assertEqual(result["full_data"]["approved"], "1")

    def test_spec_groups_parsed(self):
        data = {
            "accession": "UNIMOD:4",
            "name": "Carbamidomethyl",
            "definition": "Carbamidomethylation.",
            "additional_data": [
                {"id": "spec_1_site", "description": "C"},
                {"id": "spec_1_position", "description": "Anywhere"},
                {"id": "spec_1_classification", "description": "Chemical derivative"},
                {"id": "spec_2_site", "description": "U"},
                {"id": "spec_2_position", "description": "Anywhere"},
            ],
        }
        result = _serialize_unimod(data, "unimod")
        specs = result["full_data"]["specifications"]
        self.assertIn("1", specs)
        self.assertEqual(specs["1"]["site"], "C")
        self.assertIn("2", specs)
        self.assertEqual(specs["2"]["site"], "U")

    def test_missing_additional_data_does_not_raise(self):
        data = {"accession": "UNIMOD:0", "name": "Empty", "definition": "", "additional_data": []}
        result = _serialize_unimod(data, "unimod")
        self.assertEqual(result["full_data"]["general_properties"], {})
        self.assertEqual(result["full_data"]["specifications"], {})


class ConfigureOntologyOptionsTest(TestCase):
    """Verify configure_ontology_options template state for each SDRF ontology name."""

    def _run(self, column_name, ontologies, examples=None):
        from ccv.management.commands.load_column_templates import Command

        cmd = Command()
        tmpl = _make_template(column_name)
        validator = _make_validator(ontologies, examples)
        col = _make_column([validator])
        cmd.configure_ontology_options(tmpl, col)
        return tmpl

    def test_ncbitaxon_sets_species_as_primary_and_adds_ncbi(self):
        tmpl = self._run("characteristics[organism]", ["ncbitaxon"])
        self.assertEqual(tmpl.ontology_type, "species")
        self.assertIn("species", tmpl.ontology_options)
        self.assertIn("ncbi_taxonomy", tmpl.ontology_options)
        self.assertTrue(tmpl.enable_typeahead)

    def test_cl_sets_cell_ontology(self):
        tmpl = self._run("characteristics[cell type]", ["cl"])
        self.assertEqual(tmpl.ontology_type, "cell_ontology")
        self.assertIn("cell_ontology", tmpl.ontology_options)

    def test_unimod_sets_unimod(self):
        tmpl = self._run("comment[modification parameters]", ["unimod"])
        self.assertEqual(tmpl.ontology_type, "unimod")
        self.assertIn("unimod", tmpl.ontology_options)

    def test_uberon_sets_uberon(self):
        tmpl = self._run("characteristics[organism part]", ["uberon"])
        self.assertEqual(tmpl.ontology_type, "uberon")

    def test_mondo_sets_human_disease_primary_and_adds_mondo(self):
        tmpl = self._run("characteristics[disease]", ["mondo"])
        self.assertEqual(tmpl.ontology_type, "human_disease")
        self.assertIn("human_disease", tmpl.ontology_options)
        self.assertIn("mondo", tmpl.ontology_options)

    def test_pride_sets_ms_unique_vocabularies_with_sample_attribute_filter(self):
        tmpl = self._run("characteristics[label]", ["pride"])
        self.assertEqual(tmpl.ontology_type, "ms_unique_vocabularies")
        self.assertIn("ms_unique_vocabularies", tmpl.ontology_options)
        self.assertEqual(tmpl.custom_ontology_filters["ms_unique_vocabularies"], {"term_type": "sample attribute"})

    def test_clo_sets_cell_line_filter(self):
        tmpl = self._run("characteristics[cell line]", ["clo"])
        self.assertEqual(tmpl.custom_ontology_filters["ms_unique_vocabularies"], {"term_type": "cell line"})

    def test_hancestro_sets_ancestral_category_filter(self):
        tmpl = self._run("characteristics[ancestry category]", ["hancestro"])
        self.assertEqual(tmpl.custom_ontology_filters["ms_unique_vocabularies"], {"term_type": "ancestral category"})

    def test_pato_sets_sex_filter(self):
        tmpl = self._run("characteristics[sex]", ["pato"])
        self.assertEqual(tmpl.custom_ontology_filters["ms_unique_vocabularies"], {"term_type": "sex"})

    def test_ms_instrument_column_filter(self):
        tmpl = self._run("comment[instrument]", ["ms"])
        self.assertEqual(tmpl.custom_ontology_filters["ms_unique_vocabularies"], {"term_type": "instrument"})

    def test_ms_analyzer_column_filter(self):
        tmpl = self._run("comment[mass analyzer type]", ["ms"])
        self.assertEqual(tmpl.custom_ontology_filters["ms_unique_vocabularies"], {"term_type": "mass analyzer type"})

    def test_ms_cleavage_column_filter(self):
        tmpl = self._run("comment[cleavage agent details]", ["ms"])
        self.assertEqual(tmpl.custom_ontology_filters["ms_unique_vocabularies"], {"term_type": "cleavage agent"})

    def test_ms_dissociation_column_filter(self):
        tmpl = self._run("comment[dissociation method]", ["ms"])
        self.assertEqual(tmpl.custom_ontology_filters["ms_unique_vocabularies"], {"term_type": "dissociation method"})

    def test_ms_reduction_column_filter(self):
        tmpl = self._run("comment[reduction reagent]", ["ms"])
        self.assertEqual(tmpl.custom_ontology_filters["ms_unique_vocabularies"], {"term_type": "reduction reagent"})

    def test_ms_alkylation_column_filter(self):
        tmpl = self._run("comment[alkylation reagent]", ["ms"])
        self.assertEqual(tmpl.custom_ontology_filters["ms_unique_vocabularies"], {"term_type": "alkylation reagent"})

    def test_ms_unknown_column_sets_no_filter(self):
        tmpl = self._run("characteristics[organism]", ["ms"])
        self.assertNotIn("ms_unique_vocabularies", tmpl.custom_ontology_filters)

    def test_efo_cell_line_column(self):
        tmpl = self._run("characteristics[cell line]", ["efo"])
        self.assertEqual(tmpl.custom_ontology_filters["ms_unique_vocabularies"], {"term_type": "cell line"})

    def test_efo_developmental_stage_column(self):
        tmpl = self._run("characteristics[developmental stage]", ["efo"])
        self.assertEqual(
            tmpl.custom_ontology_filters["ms_unique_vocabularies"],
            {"term_type": "developmental stage"},
        )

    def test_efo_enrichment_column(self):
        tmpl = self._run("comment[enrichment process]", ["efo"])
        self.assertEqual(tmpl.custom_ontology_filters["ms_unique_vocabularies"], {"term_type": "enrichment process"})

    def test_efo_unrecognized_column_sets_no_filter(self):
        tmpl = self._run("characteristics[disease]", ["efo"])
        self.assertNotIn("ms_unique_vocabularies", tmpl.custom_ontology_filters)

    def test_organism_part_always_seeds_tissue_uberon(self):
        """'organism part' in column name must seed tissue+uberon regardless of validators."""
        from ccv.management.commands.load_column_templates import Command

        cmd = Command()
        tmpl = _make_template("characteristics[organism part]")
        col = _make_column([])
        cmd.configure_ontology_options(tmpl, col)
        self.assertIn("tissue", tmpl.ontology_options)
        self.assertIn("uberon", tmpl.ontology_options)
        self.assertEqual(tmpl.ontology_type, "tissue")

    def test_examples_become_possible_default_values(self):
        tmpl = self._run("characteristics[organism]", ["ncbitaxon"], examples=["homo sapiens", "mus musculus"])
        self.assertEqual(tmpl.possible_default_values, ["homo sapiens", "mus musculus"])

    def test_no_ontology_validator_leaves_typeahead_disabled(self):
        from ccv.management.commands.load_column_templates import Command

        cmd = Command()
        tmpl = _make_template("source name")
        col = _make_column([SimpleNamespace(validator_name="required", params={})])
        cmd.configure_ontology_options(tmpl, col)
        self.assertFalse(tmpl.enable_typeahead)

    def test_no_duplicate_type_keys_in_ontology_options(self):
        """When multiple SDRF names map to the same type_key, it appears only once."""
        tmpl = self._run("characteristics[cell line]", ["clo", "efo"])
        type_key_counts = {k: tmpl.ontology_options.count(k) for k in tmpl.ontology_options}
        for key, count in type_key_counts.items():
            self.assertEqual(count, 1, f"Duplicate type_key {key!r} in ontology_options")


class BuildSearchQuerysetTest(TestCase):
    """Verify build_search_queryset applies custom_filters and obsolete_filter correctly."""

    def setUp(self):
        MSUniqueVocabularies.objects.create(
            accession="MS:1000702", name="micrOTOF", definition="Bruker instrument.", term_type="instrument"
        )
        MSUniqueVocabularies.objects.create(
            accession="MS:1000484", name="orbitrap", definition="Thermo instrument.", term_type="mass analyzer type"
        )
        MSUniqueVocabularies.objects.create(
            accession="PRIDE:0000606",
            name="N-ethylmaleimide (NEM)",
            definition="Alkylation reagent.",
            term_type="alkylation reagent",
        )
        BTOTerm.objects.create(identifier="BTO:0000567", name="liver", definition="The liver.", obsolete=False)
        BTOTerm.objects.create(identifier="BTO:9999999", name="obsolete tissue", definition="Obsolete.", obsolete=True)
        MondoDisease.objects.create(
            identifier="MONDO:0000001", name="disease", definition="Root disease term.", obsolete=False
        )
        MondoDisease.objects.create(
            identifier="MONDO:9999999", name="obsolete disease", definition="Obsolete.", obsolete=True
        )

    def test_term_type_filter_instrument(self):
        desc = registry.get("ms_unique_vocabularies")
        qs = desc.build_search_queryset(custom_filters={"ms_unique_vocabularies": {"term_type": "instrument"}})
        accessions = list(qs.values_list("accession", flat=True))
        self.assertIn("MS:1000702", accessions)
        self.assertNotIn("MS:1000484", accessions)
        self.assertNotIn("PRIDE:0000606", accessions)

    def test_term_type_filter_analyzer(self):
        desc = registry.get("ms_unique_vocabularies")
        qs = desc.build_search_queryset(custom_filters={"ms_unique_vocabularies": {"term_type": "mass analyzer type"}})
        accessions = list(qs.values_list("accession", flat=True))
        self.assertIn("MS:1000484", accessions)
        self.assertNotIn("MS:1000702", accessions)

    def test_bto_obsolete_filter_excludes_obsolete_terms(self):
        desc = registry.get("bto")
        qs = desc.build_search_queryset()
        identifiers = list(qs.values_list("identifier", flat=True))
        self.assertIn("BTO:0000567", identifiers)
        self.assertNotIn("BTO:9999999", identifiers)

    def test_mondo_obsolete_filter_excludes_obsolete_terms(self):
        desc = registry.get("mondo")
        qs = desc.build_search_queryset()
        identifiers = list(qs.values_list("identifier", flat=True))
        self.assertIn("MONDO:0000001", identifiers)
        self.assertNotIn("MONDO:9999999", identifiers)

    def test_search_term_filters_results(self):
        desc = registry.get("ms_unique_vocabularies")
        qs = desc.build_search_queryset(search_term="orbitrap")
        accessions = list(qs.values_list("accession", flat=True))
        self.assertIn("MS:1000484", accessions)
        self.assertNotIn("MS:1000702", accessions)

    def test_empty_search_term_returns_all(self):
        desc = registry.get("ms_unique_vocabularies")
        qs = desc.build_search_queryset(search_term="")
        self.assertEqual(qs.count(), 3)

    def test_get_suggestions_returns_list_of_dicts(self):
        desc = registry.get("ms_unique_vocabularies")
        results = desc.get_suggestions(
            search_term="orbitrap",
            custom_filters={"ms_unique_vocabularies": {"term_type": "mass analyzer type"}},
        )
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["accession"], "MS:1000484")
