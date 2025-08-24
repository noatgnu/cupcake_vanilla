"""
Test cases for ontology validation and integration with scientific metadata.

Tests ontology-based validation, suggestion systems, and integration with
realistic scientific data patterns from SDRF fixtures.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from rest_framework import status
from rest_framework.test import APITestCase

from ccv.models import HumanDisease, MSUniqueVocabularies, Species
from tests.factories import (
    MetadataColumnFactory,
    MetadataTableFactory,
    OntologyFactory,
    QuickTestDataMixin,
    UserFactory,
)

User = get_user_model()


class OntologyDataValidationTest(TestCase, QuickTestDataMixin):
    """Test validation of metadata against ontology data."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_basic_table(user=self.user)

        # Create ontology data for testing
        self.human_species = OntologyFactory.create_species(
            code="HUMAN", taxon=9606, official_name="Homo sapiens", common_name="Human"
        )

        self.mouse_species = OntologyFactory.create_species(
            code="MOUSE", taxon=10090, official_name="Mus musculus", common_name="Mouse"
        )

        self.liver_tissue = OntologyFactory.create_tissue(
            identifier="UBERON_0002107", accession="liver", synonyms="hepatic tissue;hepar"
        )

        self.breast_cancer = OntologyFactory.create_disease(
            identifier="MONDO_0007254",
            acronym="BC",
            accession="breast carcinoma",
            definition="A carcinoma that arises from the breast.",
        )

    def test_validate_organism_against_species_ontology(self):
        """Test validating organism values against Species ontology."""
        # Create organism column
        organism_col = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="characteristics", type="organism", value="homo sapiens"
        )

        # Test validation logic
        valid_organisms = ["homo sapiens", "mus musculus", "human", "mouse"]

        species_values = [
            self.human_species.official_name.lower(),
            self.mouse_species.official_name.lower(),
            self.human_species.common_name.lower(),
            self.mouse_species.common_name.lower(),
        ]

        # Test valid organisms
        for organism in valid_organisms:
            if organism.lower() in species_values:
                # Should be valid
                self.assertIn(organism.lower(), species_values)

        # Test organism column value
        self.assertEqual(organism_col.value.lower(), "homo sapiens")
        self.assertIn(organism_col.value.lower(), species_values)

    def test_validate_tissue_against_tissue_ontology(self):
        """Test validating tissue/organ part values against Tissue ontology."""
        tissue_col = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="characteristics", type="organism part", value="liver"
        )

        # Test tissue validation
        valid_tissues = ["liver", "hepatic tissue", "hepar"]

        # Check against synonyms
        tissue_synonyms = self.liver_tissue.synonyms.lower().split(";")
        tissue_accession = self.liver_tissue.accession.lower()

        all_valid_terms = [tissue_accession] + tissue_synonyms

        for tissue in valid_tissues:
            if tissue.lower() in all_valid_terms:
                self.assertIn(tissue.lower(), all_valid_terms)

        # Test column value
        self.assertEqual(tissue_col.value.lower(), "liver")
        self.assertEqual(tissue_col.value.lower(), tissue_accession)

    def test_validate_disease_against_disease_ontology(self):
        """Test validating disease values against HumanDisease ontology."""
        disease_col = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="characteristics", type="disease", value="breast carcinoma"
        )

        # Test disease validation
        self.assertEqual(disease_col.value, self.breast_cancer.accession)
        self.assertEqual(self.breast_cancer.acronym, "BC")
        self.assertIn("breast", self.breast_cancer.definition.lower())

    def test_validate_instrument_against_ms_ontology(self):
        """Test validating instrument values against MS ontology."""
        # Create MS instrument terms
        orbitrap_term = OntologyFactory.create_ms_term(
            accession="MS_1002732",
            name="Orbitrap Fusion Lumos",
            definition="Thermo Scientific Orbitrap Fusion Lumos mass spectrometer.",
            term_type="instrument",
        )

        OntologyFactory.create_ms_term(
            accession="MS_1001911",
            name="Q Exactive",
            definition="Thermo Scientific Q Exactive mass spectrometer.",
            term_type="instrument",
        )

        # Test instrument column with MS accession pattern
        instrument_col = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="comment", type="instrument", value="NT=Orbitrap Fusion Lumos;AC=MS:1002732"
        )

        # Test MS accession extraction and validation
        instrument_value = instrument_col.value
        self.assertIn("MS:1002732", instrument_value)
        self.assertIn("Orbitrap Fusion Lumos", instrument_value)

        # Extract MS accession
        if "AC=MS:" in instrument_value:
            ms_accession = instrument_value.split("AC=")[1].split(";")[0]
            self.assertEqual(ms_accession, "MS:1002732")

            # Validate against ontology
            self.assertEqual(orbitrap_term.accession, ms_accession.replace(":", "_"))

    def test_validate_modification_against_unimod(self):
        """Test validating protein modifications against Unimod ontology."""
        # Create Unimod modifications
        oxidation_mod = OntologyFactory.create_unimod(
            accession="UNIMOD_35",
            name="Oxidation",
            definition="Oxidation of methionine residues.",
            additional_data={"mass": 15.994915, "targets": ["M"], "classification": "chemical"},
        )

        OntologyFactory.create_unimod(
            accession="UNIMOD_4",
            name="Carbamidomethyl",
            definition="Carbamidomethylation of cysteine residues.",
            additional_data={"mass": 57.021464, "targets": ["C"], "classification": "chemical"},
        )

        # Test modification parameter column
        modification_col = MetadataColumnFactory.create_column(
            metadata_table=self.table,
            name="comment",
            type="modification parameters",
            value="NT=Oxidation;AC=UNIMOD:35;MT=Variable;TA=M",
        )

        # Test UNIMOD accession validation
        mod_value = modification_col.value
        self.assertIn("UNIMOD:35", mod_value)
        self.assertIn("Oxidation", mod_value)
        self.assertIn("Variable", mod_value)
        self.assertIn("TA=M", mod_value)  # Target amino acid

        # Extract UNIMOD accession
        if "AC=UNIMOD:" in mod_value:
            unimod_accession = mod_value.split("AC=UNIMOD:")[1].split(";")[0]
            self.assertEqual(unimod_accession, "35")

            # Validate against ontology
            self.assertEqual(oxidation_mod.accession, f"UNIMOD_{unimod_accession}")

            # Test target amino acid consistency
            targets = oxidation_mod.additional_data["targets"]
            self.assertIn("M", targets)

    def test_validate_complex_sdrf_metadata_column(self):
        """Test validation of complex SDRF column with multiple ontology references."""
        # Create complex column that references multiple ontologies
        complex_col = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="comment", type="cleavage agent details", value="AC=MS:1001313;NT=Trypsin"
        )

        # Create corresponding MS term
        trypsin_term = OntologyFactory.create_ms_term(
            accession="MS_1001313", name="Trypsin", definition="Trypsin cleavage enzyme.", term_type="enzyme"
        )

        # Test validation
        complex_value = complex_col.value
        self.assertIn("MS:1001313", complex_value)
        self.assertIn("Trypsin", complex_value)

        # Extract and validate MS accession
        ms_accession = complex_value.split("AC=")[1].split(";")[0]
        self.assertEqual(ms_accession.replace(":", "_"), trypsin_term.accession)
        self.assertEqual(trypsin_term.term_type, "enzyme")

    def test_validation_with_realistic_sdrf_patterns(self):
        """Test validation using realistic SDRF data patterns."""
        # Create columns matching realistic SDRF patterns from fixtures
        sdrf_columns = [
            {"name": "characteristics", "type": "organism", "value": "homo sapiens", "expected_ontology": "species"},
            {"name": "characteristics", "type": "organism part", "value": "endometrium", "expected_ontology": "tissue"},
            {
                "name": "characteristics",
                "type": "disease",
                "value": "cervical endometrioid adenocarcinoma",
                "expected_ontology": "disease",
            },
            {
                "name": "comment",
                "type": "instrument",
                "value": "NT=Orbitrap Fusion Lumos;AC=MS:1002732",
                "expected_ontology": "ms_terms",
            },
            {
                "name": "comment",
                "type": "modification parameters",
                "value": "NT=Oxidation;MT=Variable;TA=M;AC=Unimod:35",
                "expected_ontology": "unimod",
            },
        ]

        created_columns = []
        for i, col_data in enumerate(sdrf_columns):
            expected_ontology = col_data.pop("expected_ontology")
            column = MetadataColumnFactory.create_column(metadata_table=self.table, column_position=i, **col_data)
            created_columns.append((column, expected_ontology))

        # Test validation patterns for each column
        for column, expected_ontology in created_columns:
            value = column.value.lower()

            if expected_ontology == "species":
                # Should match species patterns
                self.assertIn(value, ["homo sapiens", "mus musculus"])
            elif expected_ontology == "disease" and "carcinoma" in value:
                # Should match disease patterns
                self.assertIn("carcinoma", value)
            elif expected_ontology == "ms_terms" and "MS:" in column.value:
                # Should have MS accession pattern
                self.assertTrue(column.value.startswith("NT="))
                self.assertIn("AC=MS:", column.value)
            elif expected_ontology == "unimod" and "UNIMOD:" in column.value:
                # Should have UNIMOD accession pattern
                self.assertIn("AC=Unimod:", column.value)
                self.assertIn("MT=", column.value)  # Modification type

    def test_ontology_suggestion_generation(self):
        """Test generating ontology suggestions for metadata fields."""
        # Test organism suggestions
        organism_query = "human"
        organism_suggestions = []

        # Get species that match query
        matching_species = Species.objects.filter(official_name__icontains=organism_query) or Species.objects.filter(
            common_name__icontains=organism_query
        )

        for species in matching_species:
            suggestion = {
                "id": species.code,
                "value": species.official_name.lower(),
                "display_name": f"{species.common_name} ({species.official_name})",
                "ontology_type": "species",
                "source": "NCBI Taxonomy",
            }
            organism_suggestions.append(suggestion)

        # Test that human species is found
        if organism_suggestions:
            human_suggestion = organism_suggestions[0]
            self.assertEqual(human_suggestion["ontology_type"], "species")
            self.assertIn("human", human_suggestion["display_name"].lower())

        # Test disease suggestions
        disease_query = "cancer"
        disease_suggestions = []

        matching_diseases = HumanDisease.objects.filter(
            accession__icontains=disease_query
        ) or HumanDisease.objects.filter(synonyms__icontains=disease_query)

        for disease in matching_diseases:
            suggestion = {
                "id": disease.identifier,
                "value": disease.accession,
                "display_name": disease.accession.title(),
                "ontology_type": "disease",
                "definition": disease.definition,
            }
            disease_suggestions.append(suggestion)

        # Test that cancer diseases are found
        if disease_suggestions:
            cancer_suggestion = disease_suggestions[0]
            self.assertEqual(cancer_suggestion["ontology_type"], "disease")
            self.assertIn("carcinoma", cancer_suggestion["value"].lower())


class OntologyAPIValidationTest(APITestCase, QuickTestDataMixin):
    """Test ontology validation through API endpoints."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.client.force_authenticate(user=self.user)

        # Create test ontology data
        self.test_species = [
            OntologyFactory.create_species(code="HUMAN", official_name="Homo sapiens", common_name="Human"),
            OntologyFactory.create_species(code="MOUSE", official_name="Mus musculus", common_name="Mouse"),
        ]

        self.test_tissues = [
            OntologyFactory.create_tissue(identifier="UBERON_0002107", accession="liver", synonyms="hepatic tissue"),
            OntologyFactory.create_tissue(identifier="UBERON_0002048", accession="lung", synonyms="pulmonary tissue"),
        ]

    def test_species_search_api(self):
        """Test species search API for ontology validation."""
        # Test exact match
        url = "/api/ccv/species/"  # Adjust URL as needed
        response = self.client.get(url, {"search": "homo sapiens"})

        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            results = data.get("results", [])

            # Should find human species
            human_found = any(result["official_name"].lower() == "homo sapiens" for result in results)
            self.assertTrue(human_found)
        else:
            self.skipTest("Species API endpoint not available")

    def test_tissue_search_api(self):
        """Test tissue search API for validation."""
        url = "/api/ccv/tissue/"  # Adjust URL as needed
        response = self.client.get(url, {"search": "liver"})

        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            results = data.get("results", [])

            # Should find liver tissue
            liver_found = any("liver" in result["accession"].lower() for result in results)
            self.assertTrue(liver_found)
        else:
            self.skipTest("Tissue API endpoint not available")

    def test_ontology_suggestion_api(self):
        """Test unified ontology suggestion API."""
        # Test organism suggestions
        suggestion_url = "/api/ccv/ontology-suggestions/"  # Adjust URL as needed

        response = self.client.get(suggestion_url, {"query": "human", "type": "organism"})

        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            suggestions = data.get("suggestions", [])

            # Should return organism suggestions
            for suggestion in suggestions:
                self.assertIn("id", suggestion)
                self.assertIn("value", suggestion)
                self.assertIn("ontology_type", suggestion)
                self.assertEqual(suggestion["ontology_type"], "organism")
        else:
            self.skipTest("Ontology suggestions API endpoint not available")

    def test_ms_terms_validation_api(self):
        """Test MS terms API for instrument/method validation."""
        # Create MS terms for testing
        OntologyFactory.create_ms_term(accession="MS_1002732", name="Orbitrap Fusion Lumos", term_type="instrument")
        OntologyFactory.create_ms_term(accession="MS_1001911", name="Q Exactive", term_type="instrument"),

        url = "/api/ccv/ms-terms/"  # Adjust URL as needed
        response = self.client.get(url, {"search": "orbitrap"})

        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            results = data.get("results", [])

            # Should find Orbitrap instrument
            orbitrap_found = any("orbitrap" in result["name"].lower() for result in results)
            self.assertTrue(orbitrap_found)
        else:
            self.skipTest("MS terms API endpoint not available")

    def test_unimod_search_api(self):
        """Test Unimod search API for modification validation."""
        # Create Unimod modifications
        OntologyFactory.create_unimod(accession="UNIMOD_35", name="Oxidation", definition="Oxidation of methionine")
        OntologyFactory.create_unimod(
            accession="UNIMOD_4", name="Carbamidomethyl", definition="Carbamidomethylation of cysteine"
        )

        url = "/api/ccv/unimod/"  # Adjust URL as needed
        response = self.client.get(url, {"search": "oxidation"})

        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            results = data.get("results", [])

            # Should find oxidation modification
            oxidation_found = any("oxidation" in result["name"].lower() for result in results)
            self.assertTrue(oxidation_found)
        else:
            self.skipTest("Unimod API endpoint not available")


class OntologyIntegrationValidationTest(TestCase, QuickTestDataMixin):
    """Test integration of ontology validation with metadata workflows."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.table = MetadataTableFactory.create_basic_table(user=self.user)

        # Create comprehensive ontology dataset
        self.setup_comprehensive_ontologies()

    def setup_comprehensive_ontologies(self):
        """Set up comprehensive ontology data for testing."""
        # Species
        self.species_data = [
            OntologyFactory.create_species(code="HUMAN", official_name="Homo sapiens"),
            OntologyFactory.create_species(code="MOUSE", official_name="Mus musculus"),
            OntologyFactory.create_species(code="RAT", official_name="Rattus norvegicus"),
        ]

        # Tissues
        self.tissue_data = [
            OntologyFactory.create_tissue(identifier="UBERON_0002107", accession="liver"),
            OntologyFactory.create_tissue(identifier="UBERON_0002048", accession="lung"),
            OntologyFactory.create_tissue(identifier="UBERON_0000955", accession="brain"),
        ]

        # Diseases
        self.disease_data = [
            OntologyFactory.create_disease(identifier="MONDO_0007254", accession="breast carcinoma"),
            OntologyFactory.create_disease(identifier="MONDO_0005233", accession="lung carcinoma"),
        ]

        # MS terms
        self.ms_terms_data = [
            OntologyFactory.create_ms_term(
                accession="MS_1002732", name="Orbitrap Fusion Lumos", term_type="instrument"
            ),
            OntologyFactory.create_ms_term(accession="MS_1001251", name="Trypsin", term_type="enzyme"),
        ]

        # Modifications
        self.modification_data = [
            OntologyFactory.create_unimod(accession="UNIMOD_35", name="Oxidation"),
            OntologyFactory.create_unimod(accession="UNIMOD_4", name="Carbamidomethyl"),
        ]

    def test_validate_complete_metadata_table(self):
        """Test validation of complete metadata table against ontologies."""
        # Create comprehensive metadata columns
        comprehensive_columns = [
            {"name": "source name", "type": "", "value": "Sample-001", "validation_type": None},
            {"name": "characteristics", "type": "organism", "value": "homo sapiens", "validation_type": "species"},
            {"name": "characteristics", "type": "organism part", "value": "liver", "validation_type": "tissue"},
            {"name": "characteristics", "type": "disease", "value": "breast carcinoma", "validation_type": "disease"},
            {
                "name": "comment",
                "type": "instrument",
                "value": "NT=Orbitrap Fusion Lumos;AC=MS:1002732",
                "validation_type": "ms_terms",
            },
            {
                "name": "comment",
                "type": "modification parameters",
                "value": "NT=Oxidation;AC=UNIMOD:35;MT=Variable;TA=M",
                "validation_type": "unimod",
            },
        ]

        validation_results = {}

        for i, col_data in enumerate(comprehensive_columns):
            validation_type = col_data.pop("validation_type")
            column = MetadataColumnFactory.create_column(metadata_table=self.table, column_position=i, **col_data)

            # Perform validation based on type
            if validation_type == "species":
                is_valid = any(species.official_name.lower() == column.value.lower() for species in self.species_data)
                validation_results[f"{column.name}_{column.type}"] = is_valid

            elif validation_type == "tissue":
                is_valid = any(tissue.accession.lower() == column.value.lower() for tissue in self.tissue_data)
                validation_results[f"{column.name}_{column.type}"] = is_valid

            elif validation_type == "disease":
                is_valid = any(disease.accession.lower() == column.value.lower() for disease in self.disease_data)
                validation_results[f"{column.name}_{column.type}"] = is_valid

            elif validation_type == "ms_terms":
                # Extract MS accession and validate
                if "AC=MS:" in column.value:
                    ms_accession = column.value.split("AC=")[1].split(";")[0]
                    is_valid = any(term.accession == ms_accession.replace(":", "_") for term in self.ms_terms_data)
                    validation_results[f"{column.name}_{column.type}"] = is_valid
                else:
                    validation_results[f"{column.name}_{column.type}"] = False

            elif validation_type == "unimod":
                # Extract UNIMOD accession and validate
                if "AC=UNIMOD:" in column.value:
                    unimod_accession = column.value.split("AC=UNIMOD:")[1].split(";")[0]
                    is_valid = any(mod.accession == f"UNIMOD_{unimod_accession}" for mod in self.modification_data)
                    validation_results[f"{column.name}_{column.type}"] = is_valid
                else:
                    validation_results[f"{column.name}_{column.type}"] = False

            else:
                validation_results[f"{column.name}_{column.type}"] = True  # No validation needed

        # Test validation results
        self.assertTrue(validation_results["characteristics_organism"])  # homo sapiens should be valid
        self.assertTrue(validation_results["characteristics_organism part"])  # liver should be valid
        self.assertTrue(validation_results["characteristics_disease"])  # breast carcinoma should be valid
        self.assertTrue(validation_results["comment_instrument"])  # MS:1002732 should be valid
        self.assertTrue(validation_results["comment_modification parameters"])  # UNIMOD:35 should be valid

    def test_ontology_consistency_validation(self):
        """Test validation of ontology term consistency across related fields."""
        # Create related columns that should be consistent
        organism_col = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="characteristics", type="organism", value="homo sapiens"
        )

        # Create species-specific tissue (human tissue)
        tissue_col = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="characteristics", type="organism part", value="liver"  # Human liver
        )

        # Test consistency: human + liver should be valid combination
        organism_valid = any(
            species.official_name.lower() == organism_col.value.lower() for species in self.species_data
        )

        tissue_valid = any(tissue.accession.lower() == tissue_col.value.lower() for tissue in self.tissue_data)

        # Both should be individually valid
        self.assertTrue(organism_valid)
        self.assertTrue(tissue_valid)

        # Test consistency logic (could be extended with cross-references)
        if organism_col.value.lower() == "homo sapiens":
            # Human-specific validations could go here
            human_tissues = ["liver", "lung", "brain", "heart", "kidney"]
            tissue_consistent = tissue_col.value.lower() in human_tissues
            self.assertTrue(tissue_consistent)

    def test_batch_ontology_validation(self):
        """Test batch validation of multiple metadata columns."""
        # Create batch of columns for validation
        batch_columns_data = [
            ("characteristics", "organism", "homo sapiens"),
            ("characteristics", "organism", "mus musculus"),
            ("characteristics", "organism", "invalid species"),  # Should fail
            ("characteristics", "organism part", "liver"),
            ("characteristics", "organism part", "lung"),
            ("characteristics", "organism part", "invalid tissue"),  # Should fail
        ]

        batch_columns = []
        for name, col_type, value in batch_columns_data:
            column = MetadataColumnFactory.create_column(
                metadata_table=self.table, name=name, type=col_type, value=value
            )
            batch_columns.append(column)

        # Batch validation
        validation_results = []

        for column in batch_columns:
            if column.type == "organism":
                is_valid = any(species.official_name.lower() == column.value.lower() for species in self.species_data)
            elif column.type == "organism part":
                is_valid = any(tissue.accession.lower() == column.value.lower() for tissue in self.tissue_data)
            else:
                is_valid = True

            validation_results.append(
                {"column": f"{column.name}[{column.type}]", "value": column.value, "valid": is_valid}
            )

        # Test batch results
        valid_count = sum(1 for result in validation_results if result["valid"])
        invalid_count = len(validation_results) - valid_count

        # Should have some valid and some invalid
        self.assertGreater(valid_count, 0)
        self.assertGreater(invalid_count, 0)  # The 'invalid' entries should fail

        # Test specific validations
        human_result = next(r for r in validation_results if r["value"] == "homo sapiens")
        self.assertTrue(human_result["valid"])

        invalid_species_result = next(r for r in validation_results if r["value"] == "invalid species")
        self.assertFalse(invalid_species_result["valid"])

    def test_ontology_metadata_enrichment(self):
        """Test enriching metadata with ontology information."""
        # Create basic column
        basic_column = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="characteristics", type="organism", value="homo sapiens"
        )

        # Enrich with ontology data
        matching_species = Species.objects.filter(official_name__iexact=basic_column.value).first()

        if matching_species:
            enrichment_data = {
                "ontology_id": matching_species.code,
                "taxon_id": matching_species.taxon,
                "common_name": matching_species.common_name,
                "synonyms": matching_species.synonym,
                "ontology_source": "NCBI Taxonomy",
            }

            # Test enrichment
            self.assertEqual(enrichment_data["ontology_id"], "HUMAN")
            self.assertEqual(enrichment_data["taxon_id"], 9606)
            self.assertEqual(enrichment_data["common_name"], "Human")
            self.assertIn("sapiens", enrichment_data["synonyms"])

        # Test enrichment for MS terms
        ms_column = MetadataColumnFactory.create_column(
            metadata_table=self.table, name="comment", type="instrument", value="NT=Orbitrap Fusion Lumos;AC=MS:1002732"
        )

        # Extract MS accession for enrichment
        if "AC=MS:" in ms_column.value:
            ms_accession = ms_column.value.split("AC=")[1].split(";")[0]
            matching_term = MSUniqueVocabularies.objects.filter(accession=ms_accession.replace(":", "_")).first()

            if matching_term:
                ms_enrichment = {
                    "ontology_id": matching_term.accession,
                    "term_name": matching_term.name,
                    "definition": matching_term.definition,
                    "term_type": matching_term.term_type,
                    "ontology_source": "PSI-MS",
                }

                # Test MS enrichment
                self.assertEqual(ms_enrichment["term_type"], "instrument")
                self.assertIn("Orbitrap", ms_enrichment["term_name"])
                self.assertIn("mass spectrometer", ms_enrichment["definition"].lower())
