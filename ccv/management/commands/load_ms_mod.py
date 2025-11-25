"""
Management command to load Unimod protein modification controlled vocabulary data.
"""

from io import BytesIO

from django.core.management.base import BaseCommand

import requests

from ccv.models import Unimod


def load_unimod_data():
    """Load Unimod modification data from the Unimod OBO file."""
    try:
        import pronto
    except ImportError:
        raise ImportError(
            "The 'pronto' package is required for loading Unimod data. " "Install it with: pip install pronto"
        )

    response = requests.get("https://www.unimod.org/obo/unimod.obo", timeout=30)
    raw_data = response.text

    # Manually parse the xrefs section
    xrefs_data = {}
    current_term = None
    for line in raw_data.splitlines():
        if line.startswith("[Term]"):
            current_term = None
        elif line.startswith("id: "):
            current_term = line.split("id: ")[1]
            xrefs_data[current_term] = []
        elif line.startswith("xref: ") and current_term:
            xref = line.split("xref: ")[1]
            xrefs_data[current_term].append(xref.replace('"', ""))

    ms = pronto.Ontology(BytesIO(response.content))
    sub_0 = ms["UNIMOD:0"].subclasses().to_set()

    created_count = 0
    for term in sub_0:
        if term.is_leaf():
            existed_dict = {}
            for xref in xrefs_data.get(term.id, []):
                if " " in xref:
                    xref_id, xref_desc = xref.split(" ", 1)
                    c = {"id": xref_id, "description": xref_desc}
                    if xref_id not in existed_dict:
                        existed_dict[xref_id] = c
                    else:
                        existed_dict[xref_id]["description"] = (
                            existed_dict[xref_id]["description"] + "," + c["description"]
                        )
            result = list(existed_dict.values())

            try:
                Unimod.objects.create(
                    accession=term.id,
                    name=term.name,
                    definition=term.definition,
                    additional_data=result,
                )
                created_count += 1
            except Exception as e:
                print(f"Warning: Failed to create Unimod term {term.id} - {term.name}: {str(e)}")

    return created_count


class Command(BaseCommand):
    help = "Load Unimod protein modification data into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear-existing",
            action="store_true",
            help="Clear existing Unimod data before loading new data.",
        )

    def handle(self, *args, **options):
        self.stdout.write("Loading Unimod modification data...")

        try:
            if options["clear_existing"]:
                deleted_count = Unimod.objects.count()
                Unimod.objects.all().delete()
                self.stdout.write(f"Cleared {deleted_count} existing Unimod records.")

            created_count = load_unimod_data()
            self.stdout.write(self.style.SUCCESS(f"Successfully loaded {created_count} Unimod modification records."))
        except ImportError as e:
            self.stdout.write(self.style.ERROR(str(e)))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error loading Unimod data: {str(e)}"))
