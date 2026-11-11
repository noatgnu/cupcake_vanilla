"""
Management command to load UniProt species controlled vocabulary data.
"""

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from ccv.data_sources import download, record_source, uniprot_release
from ccv.models import Species


def save_species(species: dict) -> None:
    """Store one parsed species, skipping the list's header row."""
    if not species or species["synonym"] == "Synonym":
        return
    try:
        Species.objects.create(**species)
    except Exception as e:
        print(f"Warning: Failed to create species {species.get('code', 'unknown')}: {str(e)}")


def parse_uniprot_species(file_path: str = None):
    """Parse UniProt species list and populate the database."""
    species = {}

    if not file_path:
        url = "https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete/docs/speclist.txt"
        response = download(url)
        response.raise_for_status()
        file = response.text.split("\n")
    else:
        file = open(file_path, "rt")

    Species.objects.all().delete()

    for line in file:
        match = re.match(r"^(\w+)\s+[VABEO]\s+(\d+):\s+N=(.*)$", line)
        if match:
            save_species(species)
            species = {
                "code": match.group(1),
                "taxon": int(match.group(2)),
                "official_name": match.group(3),
                "common_name": None,
                "synonym": None,
            }
        else:
            # Match the continuation line for common name or synonym
            match = re.match(r"^\s+C=(.*)$", line)
            if match:
                species["common_name"] = match.group(1)
            match = re.match(r"^\s+S=(.*)$", line)
            if match:
                species["synonym"] = match.group(1)

    save_species(species)

    if isinstance(file, list):
        record_source("ontology:species", url, *uniprot_release("\n".join(file)))
    else:
        file.close()
        with open(file_path, "rt") as header:
            record_source("ontology:species", file_path, *uniprot_release(header.read()))


class Command(BaseCommand):
    help = "Load UniProt controlled vocabulary species data into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "file",
            type=str,
            nargs="?",
            help="The path to the species data file. If not provided, data will be downloaded from UniProt.",
        )

    def handle(self, *args, **options):
        file_path = options["file"]

        self.stdout.write("Loading UniProt species data...")
        try:
            with transaction.atomic():
                parse_uniprot_species(file_path)
            count = Species.objects.count()
            self.stdout.write(self.style.SUCCESS(f"Successfully loaded {count} species records."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error loading species data: {str(e)}"))
