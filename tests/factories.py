"""
Test data factories for consistent test data generation.

Provides factory classes to create realistic test data based on SDRF patterns
and scientific metadata conventions.
"""

import os
import random
from typing import Dict, List

from django.contrib.auth import get_user_model

from ccc.models import LabGroup
from ccv.models import (
    FavouriteMetadataOption,
    HumanDisease,
    MetadataColumn,
    MetadataTable,
    MSUniqueVocabularies,
    SamplePool,
    Species,
    SubcellularLocation,
    Tissue,
    Unimod,
)

User = get_user_model()


def get_fixture_path(filename):
    """Get absolute path to test fixture file."""
    project_root = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(project_root, "tests", "fixtures", filename)


def fixture_exists(filename):
    """Check if a fixture file exists."""
    return os.path.exists(get_fixture_path(filename))


def read_fixture_content(filename):
    """Read fixture file content."""
    filepath = get_fixture_path(filename)
    if not os.path.exists(filepath):
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


class SDRFDataPatterns:
    """Real SDRF data patterns from fixtures for realistic test data generation."""

    # From PDC000126 and PXD002137 fixtures
    ORGANISMS = ["homo sapiens", "mus musculus", "rattus norvegicus", "danio rerio"]

    ORGANISM_PARTS = [
        "endometrium",
        "colon",
        "head and neck",
        "liver",
        "lung",
        "breast",
        "kidney",
        "brain",
        "heart",
        "muscle",
    ]

    DISEASES = [
        "normal",
        "cervical endometrioid adenocarcinoma",
        "colorectal cancer",
        "squamous cell carcinoma",
        "breast carcinoma",
        "hepatocellular carcinoma",
        "not reported",
    ]

    CELL_TYPES = ["not available", "squamous epitheliel cells", "hepatocyte", "fibroblast", "epithelial cell"]

    CELL_LINES = ["not applicable", "HEp-3 cell", "HeLa", "MCF-7", "HepG2"]

    INSTRUMENTS = [
        "orbitrap fusion lumos",
        "ltq orbitrap velos",
        "q exactive",
        "timstof pro",
        "q exactive plus",
        "orbitrap eclipse",
    ]

    MS_INSTRUMENTS_AC = [
        "MS:1002732",  # Orbitrap Fusion Lumos
        "MS:1001742",  # LTQ Orbitrap Velos
        "MS:1001911",  # Q Exactive
        "MS:1002877",  # timsTOF Pro
    ]

    CLEAVAGE_AGENTS = ["trypsin", "lys-c", "chymotrypsin", "pepsin", "glu-c"]

    CLEAVAGE_AGENTS_AC = [
        "MS:1001251",  # Trypsin
        "MS:1001309",  # Lys-C
        "MS:1001306",  # Chymotrypsin
        "MS:1001305",  # Pepsin
    ]

    MODIFICATION_PARAMETERS = [
        "carbamidomethyl",
        "oxidation",
        "acetyl",
        "deamidated",
        "phospho",
        "tmt6plex",
        "itraq4plex",
    ]

    MOD_PARAMS_AC = [
        "UNIMOD:4",  # Carbamidomethyl
        "UNIMOD:35",  # Oxidation
        "UNIMOD:1",  # Acetyl
        "UNIMOD:7",  # Deamidated
        "UNIMOD:21",  # Phospho
        "UNIMOD:737",  # TMT6plex
        "UNIMOD:214",  # iTRAQ4plex
    ]

    LABEL_TYPES = [
        "label free sample",
        "tmt126",
        "tmt127n",
        "tmt127c",
        "tmt128n",
        "tmt128c",
        "itraq114",
        "itraq115",
        "silac heavy",
        "silac light",
    ]

    POOLED_SAMPLE_VALUES = ["pooled", "not pooled", "SN=", "pool"]  # Indicates pooled sample names

    PHENOTYPES = [
        "normal",
        "adenoma",
        "carcinoma",
        "proliferating cells",
        "cell cycle arrest in mitotic G1 phase",
        "apoptotic cells",
    ]

    AGES = ["42Y", "53Y", "62Y", "65Y", "71Y", "76Y", "25Y", "30Y", "45Y", "55Y", "67Y", "72Y"]

    SEX_VALUES = ["female", "male", "not available", "not applicable"]


class UserFactory:
    """Factory for creating test users."""

    @staticmethod
    def create_user(username: str = None, email: str = None, **kwargs) -> User:
        """Create a test user with realistic data."""
        if not username:
            import uuid

            username = f"testuser_{uuid.uuid4().hex[:8]}"
        if not email:
            email = f"{username}@example.com"

        user = User.objects.create_user(
            username=username,
            email=email,
            password=kwargs.get("password", "testpass123"),
            first_name=kwargs.get("first_name", "Test"),
            last_name=kwargs.get("last_name", "User"),
        )

        # Set additional attributes like is_staff, is_superuser
        for key, value in kwargs.items():
            if key not in ["password", "first_name", "last_name"] and hasattr(user, key):
                setattr(user, key, value)

        if any(key in kwargs for key in ["is_staff", "is_superuser", "is_active"]):
            user.save()

        return user

    @staticmethod
    def create_lab_group_user(lab_name: str = None) -> tuple:
        """Create a user with associated lab group."""
        user = UserFactory.create_user()
        lab_group = LabGroupFactory.create_lab_group(name=lab_name or f"Lab Group {random.randint(100, 999)}")
        return user, lab_group


class LabGroupFactory:
    """Factory for creating lab groups."""

    @staticmethod
    def create_lab_group(name: str = None, **kwargs) -> LabGroup:
        """Create a lab group with realistic data."""
        if not name:
            name = f"Laboratory {random.randint(100, 999)}"

        return LabGroup.objects.create(
            name=name,
            description=kwargs.get("description", f"Research laboratory for {name.lower()}"),
            **{k: v for k, v in kwargs.items() if k != "description"},
        )


class MetadataTableFactory:
    """Factory for creating metadata tables with SDRF-realistic data."""

    @staticmethod
    def create_basic_table(user: User = None, lab_group: LabGroup = None, **kwargs) -> MetadataTable:
        """Create a basic metadata table."""
        if not user:
            user = UserFactory.create_user()
        if not lab_group:
            lab_group = LabGroupFactory.create_lab_group()

        defaults = {
            "name": f"Study {random.randint(1000, 9999)}",
            "description": "Proteomics study generated for testing",
            "sample_count": random.randint(6, 50),
            "owner": user,
            "lab_group": lab_group,
        }
        defaults.update(kwargs)

        return MetadataTable.objects.create(**defaults)

    @staticmethod
    def create_proteomics_table(user: User = None, **kwargs) -> MetadataTable:
        """Create a proteomics-specific metadata table."""
        if not user:
            user = UserFactory.create_user()

        defaults = {
            "name": f"Proteomics Study PXD{random.randint(100000, 999999)}",
            "description": "Mass spectrometry-based proteomics study",
            "sample_count": random.randint(8, 30),
        }
        defaults.update(kwargs)

        return MetadataTableFactory.create_basic_table(user=user, **defaults)

    @staticmethod
    def create_with_columns(user: User = None, column_count: int = 10, **kwargs) -> MetadataTable:
        """Create a metadata table with predefined columns."""
        table = MetadataTableFactory.create_basic_table(user=user, **kwargs)

        # Create standard SDRF columns
        standard_columns = [
            ("source name", "", True),
            ("organism", "characteristics", True),
            ("organism part", "characteristics", True),
            ("disease", "characteristics", True),
            ("assay name", "", True),
            ("technology type", "comment", True),
            ("instrument", "comment", False),
            ("cleavage agent details", "comment", False),
            ("modification parameters", "comment", False),
            ("pooled sample", "characteristics", False),
            ("cell type", "characteristics", False),
            ("age", "characteristics", False),
            ("sex", "characteristics", False),
            ("individual", "characteristics", False),
            ("biological replicate", "characteristics", False),
        ]

        for i, (name, col_type, mandatory) in enumerate(standard_columns[:column_count]):
            MetadataColumnFactory.create_column(
                metadata_table=table,
                name=name,
                type=col_type,
                column_position=i,
                mandatory=mandatory,
                value=MetadataColumnFactory.get_realistic_value(name, col_type),
            )

        return table

    @staticmethod
    def from_sdrf_file(sdrf_file_path: str, created_by: User = None, **kwargs) -> MetadataTable:
        """Create a metadata table by importing from an actual SDRF fixture file."""
        import os

        from ccv.tasks.import_utils import import_sdrf_data

        if not created_by:
            created_by = UserFactory.create_user()

        # Read the actual SDRF file content
        with open(sdrf_file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract filename for table name
        filename = os.path.basename(sdrf_file_path).replace(".sdrf.tsv", "")

        # Create empty metadata table first
        table_name = kwargs.pop("table_name", f"SDRF_{filename}")
        metadata_table = MetadataTableFactory.create_basic_table(user=created_by, name=table_name, **kwargs)

        # Import SDRF data into the table
        import_result = import_sdrf_data(
            file_content=content,
            metadata_table=metadata_table,
            user=created_by,
            replace_existing=True,
            validate_ontologies=False,  # Skip validation for faster testing
            create_pools=True,
        )

        if not import_result.get("success"):
            raise ValueError(f"SDRF import failed: {import_result.get('error', 'Unknown error')}")

        # Refresh from database to get updated sample_count
        metadata_table.refresh_from_db()
        return metadata_table


class MetadataColumnFactory:
    """Factory for creating metadata columns with realistic SDRF data."""

    @staticmethod
    def create_column(metadata_table: MetadataTable, **kwargs) -> MetadataColumn:
        """Create a metadata column with realistic defaults."""
        defaults = {
            "name": "test column",
            "type": "characteristics",
            "column_position": 0,
            "value": "test value",
            "mandatory": False,
            "hidden": False,
            "auto_generated": False,
            "readonly": False,
        }
        defaults.update(kwargs)

        return MetadataColumn.objects.create(metadata_table=metadata_table, **defaults)

    @staticmethod
    def get_realistic_value(column_name: str, column_type: str) -> str:
        """Get realistic value based on column name and type."""
        name_lower = column_name.lower()

        if "organism" in name_lower and "part" not in name_lower:
            return random.choice(SDRFDataPatterns.ORGANISMS)
        elif "organism part" in name_lower or "tissue" in name_lower:
            return random.choice(SDRFDataPatterns.ORGANISM_PARTS)
        elif "disease" in name_lower:
            return random.choice(SDRFDataPatterns.DISEASES)
        elif "cell type" in name_lower:
            return random.choice(SDRFDataPatterns.CELL_TYPES)
        elif "cell line" in name_lower:
            return random.choice(SDRFDataPatterns.CELL_LINES)
        elif "instrument" in name_lower:
            return random.choice(SDRFDataPatterns.INSTRUMENTS)
        elif "cleavage" in name_lower:
            return random.choice(SDRFDataPatterns.CLEAVAGE_AGENTS)
        elif "modification" in name_lower:
            return random.choice(SDRFDataPatterns.MODIFICATION_PARAMETERS)
        elif "label" in name_lower:
            return random.choice(SDRFDataPatterns.LABEL_TYPES)
        elif "pooled" in name_lower:
            return random.choice(SDRFDataPatterns.POOLED_SAMPLE_VALUES)
        elif "phenotype" in name_lower:
            return random.choice(SDRFDataPatterns.PHENOTYPES)
        elif "age" in name_lower:
            return random.choice(SDRFDataPatterns.AGES)
        elif "sex" in name_lower:
            return random.choice(SDRFDataPatterns.SEX_VALUES)
        elif "source name" in name_lower:
            return f"Sample_{random.randint(1, 999)}"
        elif "assay name" in name_lower:
            return f"run {random.randint(1, 20)}"
        elif "technology type" in name_lower:
            return "proteomic profiling by mass spectrometry"
        else:
            return f"value_{random.randint(1, 100)}"

    @staticmethod
    def create_with_modifiers(metadata_table: MetadataTable, sample_count: int, **kwargs) -> MetadataColumn:
        """Create a column with sample-specific modifiers."""
        base_value = kwargs.pop("value", "base_value")

        # Create sample-specific modifiers
        modifiers = {
            "samples": [
                {"samples": [str(i)], "value": f"modified_value_{i}"}
                for i in range(1, min(4, sample_count + 1))  # First few samples
            ]
        }

        return MetadataColumnFactory.create_column(
            metadata_table=metadata_table, value=base_value, modifiers=modifiers, **kwargs
        )


class SamplePoolFactory:
    """Factory for creating sample pools based on SDRF patterns."""

    @staticmethod
    def create_pool(metadata_table: MetadataTable, **kwargs) -> SamplePool:
        """Create a sample pool with realistic data."""
        defaults = {
            "pool_name": f"Pool_{random.randint(1, 999)}",
            "pool_description": "Sample pool for testing",
            "pooled_only_samples": [1, 2],
            "pooled_and_independent_samples": [],
            "is_reference": True,
            "created_by": metadata_table.owner,
        }
        defaults.update(kwargs)

        return SamplePool.objects.create(metadata_table=metadata_table, **defaults)

    @staticmethod
    def create_from_sdrf_pattern(metadata_table: MetadataTable, sample_names: List[str]) -> SamplePool:
        """Create a pool based on SDRF SN= pattern."""
        pool_name = f"SN={','.join(sample_names[:3])}"  # Limit for readability

        return SamplePoolFactory.create_pool(
            metadata_table=metadata_table,
            pool_name=pool_name,
            pool_description=f"Pool created from samples: {', '.join(sample_names)}",
            pooled_only_samples=list(range(1, len(sample_names) + 1)),
            is_reference=True,
        )


class OntologyFactory:
    """Factory for creating ontology test data."""

    @staticmethod
    def create_species(**kwargs) -> Species:
        """Create a species record."""
        organism_data = {
            "HUMAN": (9606, "Homo sapiens", "Human"),
            "MOUSE": (10090, "Mus musculus", "Mouse"),
            "RAT": (10116, "Rattus norvegicus", "Rat"),
            "ZEBRAFISH": (7955, "Danio rerio", "Zebrafish"),
        }

        # If code is specified, use matching data; otherwise pick randomly
        if "code" in kwargs:
            code = kwargs["code"]
            if code in organism_data:
                taxon, official, common = organism_data[code]
            else:
                # Use provided code but random other data
                code_choice, (taxon, official, common) = random.choice(list(organism_data.items()))
        else:
            code, (taxon, official, common) = random.choice(list(organism_data.items()))

        defaults = {
            "code": code,
            "taxon": taxon,
            "official_name": official,
            "common_name": common,
            "synonym": f"{official.split()[0][0]}. {official.split()[1]}",
        }
        defaults.update(kwargs)

        species, created = Species.objects.get_or_create(code=defaults["code"], defaults=defaults)
        return species

    @staticmethod
    def create_tissue(**kwargs) -> Tissue:
        """Create a tissue record."""
        tissue_data = [
            ("UBERON_0002107", "liver", "hepatic tissue"),
            ("UBERON_0002048", "lung", "pulmonary tissue"),
            ("UBERON_0000955", "brain", "neural tissue"),
            ("UBERON_0000948", "heart", "cardiac tissue"),
        ]

        identifier, accession, synonyms = random.choice(tissue_data)

        defaults = {
            "identifier": identifier,
            "accession": accession,
            "synonyms": synonyms,
            "cross_references": f"FMA:{random.randint(1000, 9999)}",
        }
        defaults.update(kwargs)

        tissue, created = Tissue.objects.get_or_create(identifier=defaults["identifier"], defaults=defaults)
        return tissue

    @staticmethod
    def create_disease(**kwargs) -> HumanDisease:
        """Create a human disease record."""
        disease_data = [
            ("breast carcinoma", "BC", "MONDO:0007254", "A carcinoma that arises from the breast."),
            ("lung carcinoma", "LC", "MONDO:0005233", "A carcinoma that arises from the lung."),
            ("colon carcinoma", "CC", "MONDO:0007256", "A carcinoma that arises from the colon."),
        ]

        identifier, acronym, accession, definition = random.choice(disease_data)

        defaults = {
            "identifier": identifier,
            "acronym": acronym,
            "accession": accession,
            "definition": definition,
            "synonyms": f"{accession.replace(' carcinoma', ' cancer')}",
            "cross_references": f"DOID:{random.randint(1000, 9999)}",
        }
        defaults.update(kwargs)

        disease, created = HumanDisease.objects.get_or_create(identifier=defaults["identifier"], defaults=defaults)
        return disease

    @staticmethod
    def create_subcellular_location(**kwargs) -> SubcellularLocation:
        """Create a subcellular location record."""
        location_data = [
            ("GO_0005634", "nucleus", "The nucleus of a cell."),
            ("GO_0005737", "cytoplasm", "The cytoplasm of a cell."),
            ("GO_0005886", "plasma membrane", "The plasma membrane of a cell."),
        ]

        accession, location_id, definition = random.choice(location_data)

        defaults = {
            "accession": accession,
            "location_identifier": location_id,
            "definition": definition,
            "synonyms": f"cell {location_id}",
            "content": "Cellular components",
        }
        defaults.update(kwargs)

        location, created = SubcellularLocation.objects.get_or_create(
            accession=defaults["accession"], defaults=defaults
        )
        return location

    @staticmethod
    def create_ms_term(**kwargs) -> MSUniqueVocabularies:
        """Create an MS vocabulary term."""
        ms_data = [
            ("MS_1000031", "instrument model", "A descriptor for the instrument model.", "instrument"),
            ("MS_1000251", "trypsin", "Trypsin cleavage enzyme.", "enzyme"),
            ("MS_1000422", "HCD", "Higher-energy collisional dissociation.", "dissociation"),
        ]

        accession, name, definition, term_type = random.choice(ms_data)

        defaults = {"accession": accession, "name": name, "definition": definition, "term_type": term_type}
        defaults.update(kwargs)

        ms_term, created = MSUniqueVocabularies.objects.get_or_create(
            accession=defaults["accession"], defaults=defaults
        )
        return ms_term

    @staticmethod
    def create_unimod(**kwargs) -> Unimod:
        """Create a Unimod modification record."""
        mod_data = [
            ("UNIMOD_1", "Acetyl", "Acetylation of lysine residues."),
            ("UNIMOD_4", "Carbamidomethyl", "Carbamidomethylation of cysteine."),
            ("UNIMOD_35", "Oxidation", "Oxidation of methionine."),
        ]

        accession, name, definition = random.choice(mod_data)

        defaults = {
            "accession": accession,
            "name": name,
            "definition": definition,
            "additional_data": {
                "mass": round(random.uniform(10.0, 100.0), 6),
                "formula": f"C{random.randint(1, 5)}H{random.randint(1, 10)}O{random.randint(1, 3)}",
            },
        }
        defaults.update(kwargs)

        unimod, created = Unimod.objects.get_or_create(accession=defaults["accession"], defaults=defaults)
        return unimod


class FavouriteMetadataOptionFactory:
    """Factory for creating favourite metadata options."""

    @staticmethod
    def create_favourite(user: User = None, lab_group: LabGroup = None, **kwargs) -> FavouriteMetadataOption:
        """Create a favourite metadata option."""
        defaults = {
            "name": "organism",
            "type": "characteristics",
            "value": random.choice(SDRFDataPatterns.ORGANISMS),
            "display_value": None,
            "is_global": False,
        }
        defaults.update(kwargs)

        if not defaults["display_value"]:
            defaults["display_value"] = defaults["value"].title()

        if not defaults["is_global"]:
            if not user:
                user = UserFactory.create_user()
            if not lab_group:
                lab_group = LabGroupFactory.create_lab_group()
            defaults["user"] = user
            defaults["lab_group"] = lab_group

        return FavouriteMetadataOption.objects.create(**defaults)

    @staticmethod
    def create_global_favourite(**kwargs) -> FavouriteMetadataOption:
        """Create a global favourite metadata option."""
        return FavouriteMetadataOptionFactory.create_favourite(is_global=True, **kwargs)


class SDRFTestDataBuilder:
    """Builder for creating complete SDRF-like test datasets."""

    def __init__(self, user: User = None):
        """Initialize the builder with a user."""
        self.user = user or UserFactory.create_user()
        self.tables = []
        self.ontology_data = {}

    def create_complete_study(
        self,
        study_name: str = None,
        sample_count: int = 12,
        include_pools: bool = True,
        include_ontologies: bool = True,
    ) -> Dict:
        """Create a complete study with all components."""

        # Create main metadata table
        if not study_name:
            study_name = f"Complete Study PXD{random.randint(100000, 999999)}"

        table = MetadataTableFactory.create_with_columns(
            user=self.user, name=study_name, sample_count=sample_count, column_count=15
        )
        self.tables.append(table)

        result = {"table": table, "columns": list(table.columns.all()), "pools": [], "ontologies": {}}

        # Create sample pools if requested
        if include_pools:
            pool_count = random.randint(1, 3)
            for i in range(pool_count):
                pool = SamplePoolFactory.create_pool(
                    metadata_table=table,
                    pooled_only_samples=random.sample(
                        range(1, sample_count + 1), random.randint(2, min(5, sample_count))
                    ),
                )
                result["pools"].append(pool)

        # Create ontology data if requested
        if include_ontologies:
            result["ontologies"] = {
                "species": [OntologyFactory.create_species() for _ in range(3)],
                "tissues": [OntologyFactory.create_tissue() for _ in range(4)],
                "diseases": [OntologyFactory.create_disease() for _ in range(3)],
                "locations": [OntologyFactory.create_subcellular_location() for _ in range(3)],
                "ms_unique_vocabularies": [OntologyFactory.create_ms_term() for _ in range(5)],
                "modifications": [OntologyFactory.create_unimod() for _ in range(4)],
            }
            self.ontology_data.update(result["ontologies"])

        # Create favourite options
        result["favourites"] = [
            FavouriteMetadataOptionFactory.create_favourite(
                user=self.user, name="organism", value="homo sapiens", display_value="Human"
            ),
            FavouriteMetadataOptionFactory.create_global_favourite(
                name="disease", value="normal", display_value="Normal/Healthy"
            ),
        ]

        return result

    def create_multi_study_dataset(self, study_count: int = 3) -> List[Dict]:
        """Create multiple related studies."""
        studies = []

        for i in range(study_count):
            study = self.create_complete_study(
                study_name=f"Multi-Study {i+1} PXD{random.randint(100000, 999999)}",
                sample_count=random.randint(8, 20),
                include_pools=random.choice([True, False]),
                include_ontologies=(i == 0),  # Only first study creates ontologies
            )
            studies.append(study)

        return studies

    def cleanup(self):
        """Clean up created test data."""
        for table in self.tables:
            table.delete()

        for ontology_type, items in self.ontology_data.items():
            for item in items:
                if hasattr(item, "delete"):
                    item.delete()


class QuickTestDataMixin:
    """Mixin to provide quick test data creation methods."""

    def create_test_user(self, **kwargs):
        """Create a test user quickly."""
        return UserFactory.create_user(**kwargs)

    def create_test_table(self, user=None, **kwargs):
        """Create a test metadata table quickly."""
        return MetadataTableFactory.create_basic_table(user=user, **kwargs)

    def create_test_study(self, user=None, sample_count=10):
        """Create a complete test study quickly."""
        if not user:
            user = self.create_test_user()

        builder = SDRFTestDataBuilder(user)
        return builder.create_complete_study(sample_count=sample_count)
