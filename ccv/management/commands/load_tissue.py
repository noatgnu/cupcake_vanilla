"""
Management command to load UniProt tissue controlled vocabulary data.
"""

from django.core.management.base import BaseCommand

import requests

from ccv.data_sources import record_source, uniprot_release
from ccv.models import Tissue


def parse_tissue_file(filename=None):
    """Parse UniProt tissue list and populate the database."""
    entries = []
    entry = None

    if not filename:
        url = "https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete/docs/tisslist.txt"
        response = requests.get(url, timeout=30)
        file = response.text.split("\n")
    else:
        file = open(filename, "rt")

    for line in file:
        if line.startswith("//"):
            if entry:
                entry.save()
                entry = None

        elif line.startswith("ID"):
            entry = Tissue()
            entry.identifier = line[5:].strip()
            if entry.identifier.endswith("."):
                entry.identifier = entry.identifier[:-1]
        elif line.startswith("AC") and entry:
            entry.accession = line[5:].strip()
        elif line.startswith("SY") and entry:
            if not entry.synonyms:
                entry.synonyms = ""
            entry.synonyms += line[5:].strip() + "; "
        elif line.startswith("DR") and entry:
            if not entry.cross_references:
                entry.cross_references = ""
            entry.cross_references += line[5:].strip() + "; "

    if isinstance(file, list):
        record_source("ontology:tissue", url, *uniprot_release("\n".join(file)))
    else:
        file.close()
        with open(filename, "rt") as header:
            record_source("ontology:tissue", filename, *uniprot_release(header.read()))

    return entries


class Command(BaseCommand):
    help = "Load UniProt controlled vocabulary tissue data into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "file",
            type=str,
            nargs="?",
            help="The path to the tissue data file. If not provided, data will be downloaded from UniProt.",
        )

    def handle(self, *args, **options):
        file_path = options.get("file")

        self.stdout.write("Loading UniProt tissue data...")
        try:
            Tissue.objects.all().delete()
            parse_tissue_file(file_path)
            count = Tissue.objects.count()
            self.stdout.write(self.style.SUCCESS(f"Successfully loaded {count} tissue records."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error loading tissue data: {str(e)}"))
