"""
Management command to load mass spectrometry controlled vocabulary data.
"""

from django.core.management.base import BaseCommand

import requests

from ccv.models import MSUniqueVocabularies


def load_ms_ontology_data():
    """Load MS ontology data from various sources."""
    try:
        import pronto
    except ImportError:
        raise ImportError(
            "The 'pronto' package is required for loading MS ontology data. " "Install it with: pip install pronto"
        )

    created_count = 0

    # Load MS ontology from OBO library
    try:
        ms = pronto.Ontology.from_obo_library("ms.obo")

        # Get only leaf nodes that are subclasses of MS:1000031 (instrument)
        sub_1000031 = ms["MS:1000031"].subclasses().to_set()
        for term in sub_1000031:
            if term.is_leaf():
                try:
                    MSUniqueVocabularies.objects.create(
                        accession=term.id,
                        name=term.name,
                        definition=term.definition,
                        term_type="instrument",
                    )
                    created_count += 1
                except Exception as e:
                    print(f"Warning: Failed to create instrument term {term.id} - {term.name}: {str(e)}")

        # Get cleavage agent terms (MS:1001045)
        sub_1001045 = ms["MS:1001045"].subclasses().to_set()
        for term in sub_1001045:
            if term.is_leaf():
                try:
                    MSUniqueVocabularies.objects.create(
                        accession=term.id,
                        name=term.name,
                        definition=term.definition,
                        term_type="cleavage agent",
                    )
                    created_count += 1
                except Exception as e:
                    print(f"Warning: Failed to create cleavage agent term {term.id} - {term.name}: {str(e)}")

        # Get dissociation method terms (MS:1000133)
        sub_1000133 = ms["MS:1000133"].subclasses().to_set()
        for term in sub_1000133:
            try:
                MSUniqueVocabularies.objects.create(
                    accession=term.id,
                    name=term.name,
                    definition=term.definition,
                    term_type="dissociation method",
                )
                created_count += 1
            except Exception as e:
                print(f"Warning: Failed to create dissociation method term {term.id} - {term.name}: {str(e)}")
    except Exception as e:
        print(f"Warning: Failed to load MS ontology from OBO library: {str(e)}")

    # Load additional terms from EBI OLS API
    created_count += load_ebi_resource(
        "https://www.ebi.ac.uk/ols4/api/ontologies/pride/terms/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPRIDE_0000514/hierarchicalDescendants",
        term_type="sample attribute",
    )

    created_count += load_ebi_resource(
        "https://www.ebi.ac.uk/ols4/api/ontologies/efo/terms/http%253A%252F%252Fwww.ebi.ac.uk%252Fefo%252FEFO_0000324/hierarchicalDescendants",
        size=1000,
        term_type="cell line",
    )

    created_count += load_ebi_resource(
        "https://www.ebi.ac.uk/ols4/api/ontologies/efo/terms/http%253A%252F%252Fwww.ebi.ac.uk%252Fefo%252FEFO_0009090/hierarchicalDescendants",
        size=1000,
        term_type="enrichment process",
    )

    created_count += load_ebi_resource(
        "https://www.ebi.ac.uk/ols4/api/ontologies/pride/terms/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPRIDE_0000550/hierarchicalDescendants",
        size=1000,
        term_type="fractionation method",
    )

    created_count += load_ebi_resource(
        "https://www.ebi.ac.uk/ols4/api/ontologies/pride/terms/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPRIDE_0000659/hierarchicalDescendants",
        size=1000,
        term_type="proteomics data acquisition method",
    )

    created_count += load_ebi_resource(
        "https://www.ebi.ac.uk/ols4/api/ontologies/pride/terms/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPRIDE_0000607/hierarchicalDescendants",
        size=1000,
        term_type="reduction reagent",
    )

    created_count += load_ebi_resource(
        "https://www.ebi.ac.uk/ols4/api/ontologies/pride/terms/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPRIDE_0000598/hierarchicalDescendants",
        size=1000,
        term_type="alkylation reagent",
    )

    created_count += load_ebi_resource(
        "https://www.ebi.ac.uk/ols4/api/ontologies/ms/terms/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FMS_1000443/hierarchicalDescendants",
        size=1000,
        term_type="mass analyzer type",
    )

    created_count += load_ebi_resource(
        "https://www.ebi.ac.uk/ols4/api/ontologies/efo/terms/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FHANCESTRO_0004/hierarchicalDescendants",
        size=1000,
        term_type="ancestral category",
    )

    created_count += load_ebi_resource(
        "https://www.ebi.ac.uk/ols4/api/ontologies/efo/terms/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPATO_0001894/hierarchicalDescendants",
        size=1000,
        term_type="sex",
    )

    created_count += load_ebi_resource(
        "http://www.ebi.ac.uk/ols4/api/ontologies/efo/terms/http%253A%252F%252Fwww.ebi.ac.uk%252Fefo%252FEFO_0000399/hierarchicalDescendants",
        size=1000,
        term_type="developmental stage",
    )

    return created_count


def load_ebi_resource(base_url: str, size: int = 20, term_type: str = "sample attribute"):
    """Load terms from EBI OLS API."""
    created_count = 0

    try:
        response = requests.get(f"{base_url}?page=0&size={size}", timeout=30)
        response.raise_for_status()
        data = response.json()

        if "_embedded" in data and "terms" in data["_embedded"]:
            for term in data["_embedded"]["terms"]:
                # Check if term has required fields
                if "obo_id" in term and "label" in term:
                    try:
                        MSUniqueVocabularies.objects.create(
                            accession=term["obo_id"],
                            name=term["label"],
                            definition=term.get("description", ""),
                            term_type=term_type,
                        )
                        created_count += 1
                    except Exception as e:
                        print(f"Warning: Failed to create term {term['obo_id']} - {term['label']}: {str(e)}")

            # Process additional pages if they exist
            if "page" in data and data["page"].get("totalPages", 0) > 1:
                for i in range(1, data["page"]["totalPages"]):
                    response = requests.get(f"{base_url}?page={i}&size={size}", timeout=30)
                    response.raise_for_status()
                    data2 = response.json()

                    if "_embedded" in data2 and "terms" in data2["_embedded"]:
                        for term in data2["_embedded"]["terms"]:
                            if "obo_id" in term and "label" in term:
                                try:
                                    MSUniqueVocabularies.objects.create(
                                        accession=term["obo_id"],
                                        name=term["label"],
                                        definition=term.get("description", ""),
                                        term_type=term_type,
                                    )
                                    created_count += 1
                                except Exception as e:
                                    print(
                                        f"Warning: Failed to create term {term['obo_id']} - {term['label']}: {str(e)}"
                                    )
    except Exception as e:
        print(f"Warning: Failed to load from {base_url}: {str(e)}")

    return created_count


class Command(BaseCommand):
    help = "Load mass spectrometry controlled vocabulary data into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear-existing",
            action="store_true",
            help="Clear existing MS vocabulary data before loading new data.",
        )

    def handle(self, *args, **options):
        self.stdout.write("Loading MS controlled vocabulary data...")

        try:
            if options["clear_existing"]:
                deleted_count = MSUniqueVocabularies.objects.count()
                MSUniqueVocabularies.objects.all().delete()
                self.stdout.write(f"Cleared {deleted_count} existing MS vocabulary records.")

            created_count = load_ms_ontology_data()
            self.stdout.write(self.style.SUCCESS(f"Successfully loaded {created_count} MS vocabulary records."))
        except ImportError as e:
            self.stdout.write(self.style.ERROR(str(e)))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error loading MS vocabulary data: {str(e)}"))
