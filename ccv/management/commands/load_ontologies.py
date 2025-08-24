"""
Comprehensive ontology loading system for SDRF-proteomics metadata.

This command downloads and loads multiple authoritative ontology resources:
- MONDO Disease Ontology (diseases)
- UBERON Anatomy (tissues/organs)
- NCBI Taxonomy (organisms)
- ChEBI (chemical compounds)
- PSI-MS Ontology (mass spectrometry terms)
- Cell Ontology (cell types and cell lines)

Usage:
    python manage.py load_ontologies [--ontology ONTOLOGY] [--update-existing] [--limit N]

Ontologies:
    - all: Load all ontologies (default)
    - mondo: MONDO Disease Ontology
    - uberon: UBERON Anatomy
    - ncbi: NCBI Taxonomy
    - chebi: ChEBI Compounds
    - psims: PSI-MS Ontology
    - cell: Cell Ontology (CL)
"""

import re
import tarfile
import tempfile
import time
from pathlib import Path

from django.core.management.base import BaseCommand

import requests
from tqdm import tqdm

from ccv.models import CellOntology, MondoDisease, PSIMSOntology, UberonAnatomy


class OBOParser:
    """Generic OBO format parser for ontology files."""

    def __init__(self):
        """Initialize the OBO parser with empty term storage."""
        self.current_term = {}
        self.terms = []

    def parse_obo_content(self, content):
        """Parse OBO format content and return list of terms."""
        self.terms = []
        self.current_term = {}
        in_term = False

        for line in content.split("\n"):
            line = line.strip()

            if line == "[Term]":
                if self.current_term:
                    self.terms.append(self.current_term.copy())
                self.current_term = {}
                in_term = True

            elif line.startswith("[") and line.endswith("]"):
                if self.current_term:
                    self.terms.append(self.current_term.copy())
                in_term = False

            elif in_term and ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()

                if key == "id":
                    self.current_term["id"] = value
                elif key == "name":
                    self.current_term["name"] = value
                elif key == "def":
                    # Extract definition from quotes
                    match = re.search(r'"([^"]*)"', value)
                    if match:
                        self.current_term["definition"] = match.group(1)
                elif key == "synonym":
                    if "synonyms" not in self.current_term:
                        self.current_term["synonyms"] = []
                    # Extract synonym from quotes
                    match = re.search(r'"([^"]*)"', value)
                    if match:
                        self.current_term["synonyms"].append(match.group(1))
                elif key == "is_a":
                    if "is_a" not in self.current_term:
                        self.current_term["is_a"] = []
                    # Extract just the ID (before any comments)
                    parent_id = value.split("!")[0].strip()
                    self.current_term["is_a"].append(parent_id)
                elif key == "part_of":
                    if "part_of" not in self.current_term:
                        self.current_term["part_of"] = []
                    parent_id = value.split("!")[0].strip()
                    self.current_term["part_of"].append(parent_id)
                elif key == "xref":
                    if "xrefs" not in self.current_term:
                        self.current_term["xrefs"] = []
                    self.current_term["xrefs"].append(value)
                elif key == "is_obsolete":
                    self.current_term["obsolete"] = value.lower() == "true"
                elif key == "replaced_by":
                    self.current_term["replaced_by"] = value

        # Add last term
        if self.current_term:
            self.terms.append(self.current_term.copy())

        return self.terms


class Command(BaseCommand):
    help = "Load comprehensive ontologies for SDRF proteomics metadata"

    def add_arguments(self, parser):
        parser.add_argument(
            "--ontology",
            type=str,
            default="all",
            choices=["all", "mondo", "uberon", "ncbi", "chebi", "psims", "cell"],
            help="Ontology to load",
        )
        parser.add_argument(
            "--chebi-filter",
            type=str,
            default="all",
            choices=["all", "proteomics", "metabolomics", "lipidomics"],
            help="Filter ChEBI compounds by research area",
        )
        parser.add_argument("--update-existing", action="store_true", help="Update existing records")
        parser.add_argument("--limit", type=int, default=None, help="Limit number of records to process")
        parser.add_argument(
            "--no-limit", action="store_true", help="Remove all limits and load complete ontologies (overrides --limit)"
        )
        parser.add_argument("--skip-large", action="store_true", help="Skip large ontologies (NCBI, ChEBI) for testing")

    def handle(self, *args, **options):
        ontology = options["ontology"]
        update_existing = options["update_existing"]
        limit = options["limit"]
        no_limit = options["no_limit"]
        skip_large = options["skip_large"]
        chebi_filter = options["chebi_filter"]

        # Apply no-limit override
        if no_limit:
            limit = None
            self.stdout.write(self.style.WARNING("--no-limit specified: Loading complete ontologies without limits"))

        self.stdout.write(f"Loading ontology: {ontology}")
        if ontology in ["all", "chebi"] and chebi_filter != "all":
            self.stdout.write(f"ChEBI filter: {chebi_filter}")

        total_created = 0
        total_updated = 0

        if ontology in ["all", "mondo"]:
            created, updated = self.load_mondo_disease(update_existing, limit)
            total_created += created
            total_updated += updated

        if ontology in ["all", "uberon"]:
            created, updated = self.load_uberon_anatomy(update_existing, limit)
            total_created += created
            total_updated += updated

        if ontology in ["all", "ncbi"] and not skip_large:
            created, updated = self.load_ncbi_taxonomy(update_existing, limit)
            total_created += created
            total_updated += updated

        if ontology in ["all", "chebi"] and not skip_large:
            created, updated = self.load_chebi_compounds(update_existing, limit, chebi_filter)
            total_created += created
            total_updated += updated

        if ontology in ["all", "psims"]:
            created, updated = self.load_psims_ontology(update_existing, limit)
            total_created += created
            total_updated += updated

        if ontology in ["all", "cell"]:
            created, updated = self.load_cell_ontology(update_existing, limit)
            total_created += created
            total_updated += updated

        self.stdout.write(
            self.style.SUCCESS(f"Successfully loaded {total_created} new and updated {total_updated} existing terms.")
        )

    def load_mondo_disease(self, update_existing=False, limit=10000):
        """Load MONDO Disease Ontology."""
        self.stdout.write("Loading MONDO Disease Ontology...")

        mondo_url = "http://purl.obolibrary.org/obo/mondo.obo"

        try:
            response = requests.get(mondo_url, timeout=120)
            response.raise_for_status()

            parser = OBOParser()
            terms = parser.parse_obo_content(response.text)

            # Filter terms to only MONDO terms
            mondo_terms = [term for term in terms if term.get("id", "").startswith("MONDO:")]
            if limit is not None:
                mondo_terms = mondo_terms[:limit]

            created_count = 0
            updated_count = 0

            # Use tqdm for progress bar
            with tqdm(total=len(mondo_terms), desc="Loading MONDO terms", unit="terms") as pbar:
                for term_data in mondo_terms:
                    created, updated = self._process_mondo_term(term_data, update_existing)
                    if created:
                        created_count += 1
                    if updated:
                        updated_count += 1

                    pbar.update(1)
                    pbar.set_postfix({"created": created_count, "updated": updated_count})

            self.stdout.write(f"MONDO: {created_count} created, {updated_count} updated")
            return created_count, updated_count

        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Error downloading MONDO: {e}"))
            return 0, 0

    def _process_mondo_term(self, term_data, update_existing):
        """Process a single MONDO term."""
        if term_data.get("obsolete", False):
            return False, False

        identifier = term_data.get("id", "")
        name = term_data.get("name", "")
        definition = term_data.get("definition", "")
        synonyms = term_data.get("synonyms", [])
        xrefs = term_data.get("xrefs", [])
        parent_terms = term_data.get("is_a", [])
        replacement = term_data.get("replaced_by", "")

        if not name or not identifier:
            return False, False

        disease_data = {
            "identifier": identifier,
            "name": name,
            "definition": definition,
            "synonyms": ";".join(synonyms) if synonyms else "",
            "xrefs": ";".join(xrefs) if xrefs else "",
            "parent_terms": ";".join(parent_terms) if parent_terms else "",
            "replacement_term": replacement,
        }

        try:
            disease, created = MondoDisease.objects.get_or_create(identifier=identifier, defaults=disease_data)

            if not created and update_existing:
                for key, value in disease_data.items():
                    setattr(disease, key, value)
                disease.save()
                return False, True

            return created, False

        except Exception as e:
            self.stdout.write(f"Error processing {name}: {e}")
            return False, False

    def load_uberon_anatomy(self, update_existing=False, limit=10000):
        """Load UBERON Anatomy Ontology."""
        self.stdout.write("Loading UBERON Anatomy Ontology...")

        uberon_url = "http://purl.obolibrary.org/obo/uberon.obo"

        try:
            response = requests.get(uberon_url, timeout=120)
            response.raise_for_status()

            parser = OBOParser()
            terms = parser.parse_obo_content(response.text)

            # Filter terms to only UBERON terms
            uberon_terms = [term for term in terms if term.get("id", "").startswith("UBERON:")]
            if limit is not None:
                uberon_terms = uberon_terms[:limit]

            created_count = 0
            updated_count = 0

            # Use tqdm for progress bar
            with tqdm(total=len(uberon_terms), desc="Loading UBERON terms", unit="terms") as pbar:
                for term_data in uberon_terms:
                    created, updated = self._process_uberon_term(term_data, update_existing)
                    if created:
                        created_count += 1
                    if updated:
                        updated_count += 1

                    pbar.update(1)
                    pbar.set_postfix({"created": created_count, "updated": updated_count})

            self.stdout.write(f"UBERON: {created_count} created, {updated_count} updated")
            return created_count, updated_count

        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Error downloading UBERON: {e}"))
            return 0, 0

    def _process_uberon_term(self, term_data, update_existing):
        """Process a single UBERON term."""
        if term_data.get("obsolete", False):
            return False, False

        identifier = term_data.get("id", "")
        name = term_data.get("name", "")
        definition = term_data.get("definition", "")
        synonyms = term_data.get("synonyms", [])
        xrefs = term_data.get("xrefs", [])
        parent_terms = term_data.get("is_a", [])
        part_of = term_data.get("part_of", [])
        replacement = term_data.get("replaced_by", "")

        if not name or not identifier:
            return False, False

        anatomy_data = {
            "identifier": identifier,
            "name": name,
            "definition": definition,
            "synonyms": ";".join(synonyms) if synonyms else "",
            "xrefs": ";".join(xrefs) if xrefs else "",
            "parent_terms": ";".join(parent_terms) if parent_terms else "",
            "part_of": ";".join(part_of) if part_of else "",
            "replacement_term": replacement,
        }

        try:
            anatomy, created = UberonAnatomy.objects.get_or_create(identifier=identifier, defaults=anatomy_data)

            if not created and update_existing:
                for key, value in anatomy_data.items():
                    setattr(anatomy, key, value)
                anatomy.save()
                return False, True

            return created, False

        except Exception as e:
            self.stdout.write(f"Error processing {name}: {e}")
            return False, False

    def load_ncbi_taxonomy(self, update_existing=False, limit=10000):
        """Load NCBI Taxonomy data."""
        self.stdout.write("Loading NCBI Taxonomy...")

        # NCBI taxonomy files
        names_url = "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz"

        try:
            self.stdout.write("Downloading NCBI taxonomy data (this may take a while)...")
            response = requests.get(names_url, timeout=300)
            response.raise_for_status()

            # Create temporary directory for extraction
            with tempfile.TemporaryDirectory() as temp_dir:
                # Save and extract the tar.gz file
                tar_path = Path(temp_dir) / "taxdump.tar.gz"
                with open(tar_path, "wb") as f:
                    f.write(response.content)

                with tarfile.open(tar_path, "r:gz") as tar:
                    tar.extractall(temp_dir)

                # Process names.dmp and nodes.dmp
                names_file = Path(temp_dir) / "names.dmp"
                nodes_file = Path(temp_dir) / "nodes.dmp"

                created_count, updated_count = self._process_ncbi_files(names_file, nodes_file, update_existing, limit)

            self.stdout.write(f"NCBI Taxonomy: {created_count} created, {updated_count} updated")
            return created_count, updated_count

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error processing NCBI Taxonomy: {e}"))
            return 0, 0

    def _process_ncbi_files(self, names_file, nodes_file, update_existing, limit):
        """Process NCBI taxonomy names and nodes files."""
        # First, load nodes data for taxonomy hierarchy
        nodes_data = {}
        with open(nodes_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.split("\t|\t")]
                if len(parts) >= 3:
                    tax_id = int(parts[0])
                    parent_tax_id = int(parts[1])
                    rank = parts[2]
                    nodes_data[tax_id] = {
                        "parent_tax_id": parent_tax_id if parent_tax_id != tax_id else None,
                        "rank": rank,
                    }

        # Then process names
        taxa_data = {}
        with open(names_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.split("\t|\t")]
                if len(parts) >= 4:
                    tax_id = int(parts[0])
                    name = parts[1]
                    name_class = parts[3].rstrip("\t|")

                    if tax_id not in taxa_data:
                        taxa_data[tax_id] = {"scientific_name": "", "common_name": "", "synonyms": []}

                    if name_class == "scientific name":
                        taxa_data[tax_id]["scientific_name"] = name
                    elif name_class == "genbank common name":
                        taxa_data[tax_id]["common_name"] = name
                    elif name_class in ["synonym", "common name"]:
                        taxa_data[tax_id]["synonyms"].append(name)

        # Create taxonomy records with bulk operations
        created_count = 0
        updated_count = 0
        processed = 0

        # Process in batches for better performance
        batch_size = 5000
        batch_records = []
        total_taxa = len(taxa_data)
        if limit is not None:
            total_taxa = min(total_taxa, limit)

        # Use tqdm for progress bar
        with tqdm(total=total_taxa, desc="Loading NCBI Taxonomy", unit="taxa") as pbar:
            for tax_id, data in taxa_data.items():
                if limit is not None and processed >= limit:
                    break

                if not data["scientific_name"]:
                    continue

                node_info = nodes_data.get(tax_id, {})

                taxonomy_data = {
                    "tax_id": tax_id,
                    "scientific_name": data["scientific_name"],
                    "common_name": data["common_name"] or None,
                    "synonyms": ";".join(data["synonyms"]) if data["synonyms"] else "",
                    "rank": node_info.get("rank", ""),
                    "parent_tax_id": node_info.get("parent_tax_id"),
                }

                batch_records.append(taxonomy_data)
                processed += 1
                pbar.update(1)

                # Process batch when full or at end
                if (
                    len(batch_records) >= batch_size
                    or processed == total_taxa
                    or (limit is not None and processed >= limit)
                ):
                    batch_created, batch_updated = self._bulk_process_ncbi_taxonomy(batch_records, update_existing)
                    created_count += batch_created
                    updated_count += batch_updated

                    # Clear batch and update progress display
                    batch_records = []
                    pbar.set_postfix({"created": created_count, "updated": updated_count})

                if limit is not None and processed >= limit:
                    break

        return created_count, updated_count

    def _bulk_process_ncbi_taxonomy(self, batch_records, update_existing):
        """Process a batch of NCBI taxonomy records with bulk operations."""
        from django.db import transaction

        from ccv.models import NCBITaxonomy

        created_count = 0
        updated_count = 0

        try:
            with transaction.atomic():
                if update_existing:
                    # For updates, we need individual processing
                    for record in batch_records:
                        taxonomy, created = NCBITaxonomy.objects.get_or_create(tax_id=record["tax_id"], defaults=record)
                        if created:
                            created_count += 1
                        else:
                            # Update existing record
                            for key, value in record.items():
                                setattr(taxonomy, key, value)
                            taxonomy.save()
                            updated_count += 1
                else:
                    # For new records, use bulk_create (much faster)
                    # First filter out existing records
                    existing_tax_ids = set(
                        NCBITaxonomy.objects.filter(tax_id__in=[r["tax_id"] for r in batch_records]).values_list(
                            "tax_id", flat=True
                        )
                    )

                    new_records = [
                        NCBITaxonomy(**record) for record in batch_records if record["tax_id"] not in existing_tax_ids
                    ]

                    if new_records:
                        NCBITaxonomy.objects.bulk_create(new_records, ignore_conflicts=True)
                        created_count = len(new_records)

        except Exception as e:
            self.stdout.write(f"Error in bulk processing: {e}")
            # Fallback to individual processing
            for record in batch_records:
                try:
                    taxonomy, created = NCBITaxonomy.objects.get_or_create(tax_id=record["tax_id"], defaults=record)
                    if created:
                        created_count += 1
                    elif update_existing:
                        for key, value in record.items():
                            setattr(taxonomy, key, value)
                        taxonomy.save()
                        updated_count += 1
                except Exception as individual_error:
                    self.stdout.write(f'Error processing tax_id {record["tax_id"]}: {individual_error}')

        return created_count, updated_count

    def load_chebi_compounds(self, update_existing=False, limit=10000, chebi_filter="all"):
        """Load ChEBI compound ontology."""
        self.stdout.write("Loading ChEBI compounds...")

        chebi_url = "http://purl.obolibrary.org/obo/chebi.obo"

        try:
            # Download with streaming and robust progress tracking
            self.stdout.write("Downloading ChEBI database (250MB, this may take 5-10 minutes)...")
            self.stdout.write("Starting download...")

            # Configure requests with retry-friendly settings
            session = requests.Session()
            session.headers.update({"User-Agent": "CUPCAKE-Vanilla/1.0 (Ontology Loader; Python-requests)"})

            # Use longer timeout and better error handling
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        self.stdout.write(f"Download attempt {attempt + 1}/{max_retries}...")

                    response = session.get(chebi_url, timeout=1200, stream=True)
                    response.raise_for_status()
                    break
                except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
                    if attempt == max_retries - 1:
                        raise Exception(f"Failed to download ChEBI after {max_retries} attempts: {e}")
                    else:
                        self.stdout.write(f"Download attempt {attempt + 1} failed: {e}. Retrying...")
                        time.sleep(5)  # Wait 5 seconds before retry

            # Track download progress while accumulating content
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            content_chunks = []
            last_mb_reported = 0

            # Start download with smaller chunks for better responsiveness
            chunk_size = 512 * 1024  # 512KB chunks

            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    content_chunks.append(chunk)
                    downloaded += len(chunk)

                    # Report progress every 10MB to show activity
                    mb_downloaded = downloaded // (1024 * 1024)
                    if mb_downloaded > last_mb_reported and mb_downloaded % 10 == 0:
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            total_mb = total_size // (1024 * 1024)
                            self.stdout.write(f"Downloaded {mb_downloaded}MB/{total_mb}MB ({progress:.1f}%)")
                        else:
                            self.stdout.write(f"Downloaded {mb_downloaded}MB (size unknown)")
                        last_mb_reported = mb_downloaded
                    elif mb_downloaded == 1 and last_mb_reported == 0:
                        # Show initial progress to confirm download started
                        self.stdout.write("Download started - received first 1MB...")
                        last_mb_reported = 1

                    # Add a small delay every 50MB to be gentle on the server
                    if mb_downloaded > 0 and mb_downloaded % 50 == 0 and mb_downloaded != last_mb_reported:
                        time.sleep(0.1)  # 100ms pause every 50MB

            if downloaded == 0:
                raise Exception("No data received from ChEBI server")
            elif downloaded < 1024 * 1024:  # Less than 1MB suggests incomplete download
                raise Exception(f"Download appears incomplete: only {downloaded} bytes received")

            # Safely combine all chunks and decode as complete content
            final_mb = downloaded // (1024 * 1024)
            self.stdout.write(f"Download complete: {final_mb}MB received. Decoding content...")

            try:
                content = b"".join(content_chunks).decode("utf-8")
            except UnicodeDecodeError:
                self.stdout.write("UTF-8 decoding failed, trying latin-1...")
                # Fallback to latin-1 if UTF-8 fails
                content = b"".join(content_chunks).decode("latin-1")

            self.stdout.write(f"Content decoded successfully ({len(content):,} characters)")

            # Parse the complete content (not using the old OBOParser to avoid confusion)
            terms = self._parse_chebi_with_progress(content)

            created_count = 0
            updated_count = 0
            processed = 0
            total_examined = 0

            # Process terms with batch database operations
            self.stdout.write(f"Processing {len(terms):,} ChEBI terms with proteomics filter...")

            # Process in batches for better performance
            batch_size = 1000
            batch_compounds = []

            # Use tqdm for progress bar
            with tqdm(total=len(terms), desc="Loading ChEBI compounds", unit="terms") as pbar:
                for term_data in terms:
                    total_examined += 1

                    if not term_data.get("id", "").startswith("CHEBI:"):
                        pbar.update(1)
                        continue

                    # Pre-filter before database operations
                    compound_data = self._prepare_chebi_compound(term_data, chebi_filter)
                    if compound_data:
                        batch_compounds.append(compound_data)
                        processed += 1

                    # Process batch when full or at end
                    if len(batch_compounds) >= batch_size or total_examined == len(terms):
                        if batch_compounds:
                            batch_created, batch_updated = self._batch_process_chebi_compounds(
                                batch_compounds, update_existing
                            )
                            created_count += batch_created
                            updated_count += batch_updated
                            batch_compounds = []

                    pbar.update(1)
                    pbar.set_postfix({"found": processed, "created": created_count, "updated": updated_count})

                    if limit is not None and processed >= limit:
                        break

            self.stdout.write(f"ChEBI: {created_count} created, {updated_count} updated")
            return created_count, updated_count

        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Error downloading ChEBI: {e}"))
            return 0, 0

    def _matches_chebi_filter(self, name, definition, synonyms, chebi_filter):
        """Check if a ChEBI term matches the specified research area filter."""
        search_text = f"{name.lower()} {definition.lower()} {' '.join(synonyms).lower()}"

        if chebi_filter == "proteomics":
            proteomics_keywords = [
                "protein",
                "peptide",
                "amino acid",
                "trypsin",
                "enzyme",
                "protease",
                "buffer",
                "tris",
                "bicine",
                "hepes",
                "bis-tris",
                "tricine",
                "urea",
                "thiourea",
                "guanidine",
                "dtt",
                "tcep",
                "iodoacetamide",
                "acetonitrile",
                "formic acid",
                "trifluoroacetic acid",
                "acetic acid",
                "methanol",
                "water",
                "ammonium",
                "bicarbonate",
                "phosphate",
                "detergent",
                "sds",
                "triton",
                "tween",
                "chaps",
                "deoxycholate",
                "reagent",
                "modifier",
                "labeling",
                "tag",
                "dye",
                "fluorophore",
                "crosslink",
                "digest",
                "reduction",
                "alkylation",
                "derivatization",
            ]
            return any(keyword in search_text for keyword in proteomics_keywords)

        elif chebi_filter == "metabolomics":
            metabolomics_keywords = [
                "metabolite",
                "lipid",
                "fatty acid",
                "steroid",
                "hormone",
                "nucleotide",
                "nucleoside",
                "sugar",
                "carbohydrate",
                "glucose",
                "amino acid",
                "organic acid",
                "carboxylic acid",
                "phenolic",
                "alkaloid",
                "flavonoid",
                "terpenoid",
                "polyketide",
                "vitamin",
                "cofactor",
                "coenzyme",
                "prostaglandin",
                "neurotransmitter",
                "bile acid",
                "sphingolipid",
                "phospholipid",
                "glycerolipid",
                "cholesterol",
                "ceramide",
            ]
            return any(keyword in search_text for keyword in metabolomics_keywords)

        elif chebi_filter == "lipidomics":
            lipidomics_keywords = [
                "lipid",
                "fatty acid",
                "phospholipid",
                "sphingolipid",
                "glycerolipid",
                "sterol",
                "cholesterol",
                "ceramide",
                "phosphatidyl",
                "lyso",
                "plasmalogen",
                "cardiolipin",
                "triglyceride",
                "diglyceride",
                "monoglyceride",
                "sphingomyelin",
                "glucosylceramide",
                "galactosylceramide",
                "phosphatidic acid",
                "phosphatidylcholine",
                "phosphatidylethanolamine",
                "phosphatidylserine",
                "phosphatidylinositol",
                "phosphatidylglycerol",
                "arachidonic acid",
                "oleic acid",
                "palmitic acid",
                "stearic acid",
                "linoleic acid",
                "docosahexaenoic acid",
                "eicosapentaenoic acid",
            ]
            return any(keyword in search_text for keyword in lipidomics_keywords)

        return True  # Default case, shouldn't reach here

    def _parse_chebi_with_progress(self, content):
        """Parse ChEBI content with progress reporting."""
        import re

        self.stdout.write("Parsing ChEBI OBO format...")

        # Split content into lines for processing
        lines = content.split("\n")
        total_lines = len(lines)
        self.stdout.write(f"Processing {total_lines:,} lines of ChEBI data...")

        # For now, use single-threaded parsing but with better progress
        terms = []
        current_term = {}
        in_term = False
        processed_lines = 0

        for line in lines:
            processed_lines += 1
            line = line.strip()

            if line == "[Term]":
                if current_term:
                    terms.append(current_term.copy())
                current_term = {}
                in_term = True

            elif line.startswith("[") and line.endswith("]"):
                if current_term:
                    terms.append(current_term.copy())
                in_term = False

            elif in_term and ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()

                if key == "id":
                    current_term["id"] = value
                elif key == "name":
                    current_term["name"] = value
                elif key == "def":
                    # Extract definition from quotes
                    match = re.search(r'"([^"]*)"', value)
                    if match:
                        current_term["definition"] = match.group(1)
                elif key == "synonym":
                    if "synonyms" not in current_term:
                        current_term["synonyms"] = []
                    # Extract synonym from quotes
                    match = re.search(r'"([^"]*)"', value)
                    if match:
                        current_term["synonyms"].append(match.group(1))
                elif key == "is_a":
                    if "is_a" not in current_term:
                        current_term["is_a"] = []
                    # Extract just the ID (before any comments)
                    parent_id = value.split("!")[0].strip()
                    current_term["is_a"].append(parent_id)
                elif key == "is_obsolete":
                    current_term["obsolete"] = value.lower() == "true"
                elif key == "replaced_by":
                    current_term["replaced_by"] = value
                elif key == "property_value":
                    # Parse ChEBI-specific chemical properties
                    if "properties" not in current_term:
                        current_term["properties"] = {}
                    self._parse_chebi_property(current_term["properties"], value)
                elif key == "relationship":
                    # Handle relationships like "has_role CHEBI:xxxxx ! role_name"
                    if "relationships" not in current_term:
                        current_term["relationships"] = []
                    current_term["relationships"].append(value)

            # Progress reporting every 50k lines
            if processed_lines % 50000 == 0:
                progress = (processed_lines / total_lines) * 100
                self.stdout.write(f"Parsed {progress:.1f}% of ChEBI data ({len(terms):,} terms found)...")

        # Add last term
        if current_term:
            terms.append(current_term.copy())

        self.stdout.write(f"ChEBI parsing complete: {len(terms):,} terms extracted")
        return terms

    def _looks_like_smiles(self, text):
        """Check if text looks like a SMILES string."""
        # SMILES typically contain certain characters and patterns
        if not text or len(text) < 3:
            return False

        # Look for common SMILES characters
        smiles_chars = set("CNOPSFBrClI()[]=-#@+")
        text_chars = set(text.upper())

        # If more than 50% of characters are SMILES-like, consider it SMILES
        common_chars = len(text_chars & smiles_chars)
        return common_chars / len(text_chars) > 0.3 and any(c in text for c in "()[]=-#")

    def _looks_like_formula(self, text):
        """Check if text looks like a chemical formula."""
        if not text:
            return False

        # Chemical formulas typically have elements (capital letter + optional lowercase) + numbers
        import re

        # Pattern for chemical formula: Element symbols followed by optional numbers
        formula_pattern = r"^[A-Z][a-z]?(\d+)?([A-Z][a-z]?(\d+)?)*$"
        return bool(re.match(formula_pattern, text)) and len(text) <= 50

    def _parse_chebi_property(self, properties, property_value):
        """Parse ChEBI property_value fields for chemical properties."""
        import re

        # ChEBI property format: http://purl.obolibrary.org/obo/chebi/PROPERTY "VALUE" xsd:string
        # Examples:
        # property_value: http://purl.obolibrary.org/obo/chebi/mass "18.99840" xsd:string
        # property_value: http://purl.obolibrary.org/obo/chebi/formula "F" xsd:string

        if "http://purl.obolibrary.org/obo/chebi/" in property_value:
            # Extract the property name and value
            parts = property_value.split()
            if len(parts) >= 2:
                property_url = parts[0]
                # Extract value from quotes
                match = re.search(r'"([^"]*)"', property_value)
                if match:
                    value = match.group(1)

                    # Map ChEBI property URLs to our model fields
                    if property_url.endswith("/formula"):
                        properties["formula"] = value
                    elif property_url.endswith("/mass"):
                        try:
                            properties["mass"] = float(value)
                        except ValueError:
                            pass
                    elif property_url.endswith("/charge"):
                        try:
                            properties["charge"] = int(value)
                        except ValueError:
                            pass
                    elif property_url.endswith("/inchi"):
                        properties["inchi"] = value
                    elif property_url.endswith("/smiles"):
                        properties["smiles"] = value
                    elif property_url.endswith("/monoisotopicmass"):
                        try:
                            # Use monoisotopic mass if regular mass not available
                            if "mass" not in properties:
                                properties["mass"] = float(value)
                        except ValueError:
                            pass
                    elif property_url.endswith("/inchikey"):
                        # Store InChI key as additional info (not in our model but useful for debugging)
                        properties["inchikey"] = value

    def _prepare_chebi_compound(self, term_data, chebi_filter):
        """Prepare ChEBI compound data if it passes the filter."""
        if term_data.get("obsolete", False):
            return None

        identifier = term_data.get("id", "")
        name = term_data.get("name", "")
        definition = term_data.get("definition", "")
        synonyms = term_data.get("synonyms", [])
        parent_terms = term_data.get("is_a", [])
        replacement = term_data.get("replaced_by", "")
        relationships = term_data.get("relationships", [])

        if not name or not identifier:
            return None

        # Apply ChEBI filtering
        if chebi_filter != "all":
            if not self._matches_chebi_filter(name, definition, synonyms, chebi_filter):
                return None

        # Extract chemical properties
        properties = term_data.get("properties", {})

        # Extract roles from relationships
        roles = []
        for rel in relationships:
            if rel.startswith("has_role"):
                # Extract role name from "has_role CHEBI:xxxxx ! role_name"
                if "!" in rel:
                    role_name = rel.split("!")[-1].strip()
                    roles.append(role_name)

        return {
            "identifier": identifier,
            "name": name,
            "definition": definition,
            "synonyms": ";".join(synonyms) if synonyms else "",
            "formula": properties.get("formula"),
            "mass": properties.get("mass"),
            "charge": properties.get("charge"),
            "inchi": properties.get("inchi"),
            "smiles": properties.get("smiles"),
            "parent_terms": ";".join(parent_terms) if parent_terms else "",
            "roles": ";".join(roles) if roles else "",
            "replacement_term": replacement,
        }

    def _batch_process_chebi_compounds(self, batch_compounds, update_existing):
        """Process a batch of ChEBI compounds with database operations."""
        from django.db import transaction

        from ccv.models import ChEBICompound

        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for compound_data in batch_compounds:
                try:
                    # Always update or create - don't use get_or_create
                    try:
                        compound = ChEBICompound.objects.get(identifier=compound_data["identifier"])
                        # Update all fields
                        for key, value in compound_data.items():
                            setattr(compound, key, value)
                        compound.save()
                        updated_count += 1
                    except ChEBICompound.DoesNotExist:
                        # Create new compound
                        compound = ChEBICompound.objects.create(**compound_data)
                        created_count += 1

                except Exception as e:
                    self.stdout.write(f'Error processing {compound_data["name"]}: {e}')

        return created_count, updated_count

    def load_psims_ontology(self, update_existing=False, limit=10000):
        """Load PSI-MS Ontology."""
        self.stdout.write("Loading PSI-MS Ontology...")

        psims_url = "http://purl.obolibrary.org/obo/ms.obo"

        try:
            response = requests.get(psims_url, timeout=120)
            response.raise_for_status()

            parser = OBOParser()
            terms = parser.parse_obo_content(response.text)

            # Filter terms to only PSI-MS terms
            psims_terms = [term for term in terms if term.get("id", "").startswith("MS:")]
            if limit is not None:
                psims_terms = psims_terms[:limit]

            created_count = 0
            updated_count = 0

            # Use tqdm for progress bar
            with tqdm(total=len(psims_terms), desc="Loading PSI-MS terms", unit="terms") as pbar:
                for term_data in psims_terms:
                    created, updated = self._process_psims_term(term_data, update_existing)
                    if created:
                        created_count += 1
                    if updated:
                        updated_count += 1

                    pbar.update(1)
                    pbar.set_postfix({"created": created_count, "updated": updated_count})

            self.stdout.write(f"PSI-MS: {created_count} created, {updated_count} updated")
            return created_count, updated_count

        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Error downloading PSI-MS: {e}"))
            return 0, 0

    def _process_psims_term(self, term_data, update_existing):
        """Process a single PSI-MS term."""
        if term_data.get("obsolete", False):
            return False, False

        identifier = term_data.get("id", "")
        name = term_data.get("name", "")
        definition = term_data.get("definition", "")
        synonyms = term_data.get("synonyms", [])
        parent_terms = term_data.get("is_a", [])
        replacement = term_data.get("replaced_by", "")

        if not name or not identifier:
            return False, False

        # Determine category based on parent terms or name
        category = "other"
        if any("instrument" in parent.lower() for parent in parent_terms):
            category = "instrument"
        elif any("method" in parent.lower() or "technique" in parent.lower() for parent in parent_terms):
            category = "method"
        elif "instrument" in name.lower():
            category = "instrument"
        elif any(keyword in name.lower() for keyword in ["method", "technique", "mode"]):
            category = "method"

        ontology_data = {
            "identifier": identifier,
            "name": name,
            "definition": definition,
            "synonyms": ";".join(synonyms) if synonyms else "",
            "parent_terms": ";".join(parent_terms) if parent_terms else "",
            "category": category,
            "replacement_term": replacement,
        }

        try:
            ontology_term, created = PSIMSOntology.objects.get_or_create(identifier=identifier, defaults=ontology_data)

            if not created and update_existing:
                for key, value in ontology_data.items():
                    setattr(ontology_term, key, value)
                ontology_term.save()
                return False, True

            return created, False

        except Exception as e:
            self.stdout.write(f"Error processing {name}: {e}")
            return False, False

    def load_cell_ontology(self, update_existing=False, limit=10000):
        """Load Cell Ontology (CL) and Cellosaurus cell lines."""
        self.stdout.write("Loading Cell Ontology...")

        cl_url = "http://purl.obolibrary.org/obo/cl.obo"

        try:
            response = requests.get(cl_url, timeout=120)
            response.raise_for_status()

            parser = OBOParser()
            terms = parser.parse_obo_content(response.text)

            # Filter terms to only Cell Ontology terms
            cl_terms = [term for term in terms if term.get("id", "").startswith("CL:")]
            if limit is not None:
                cl_terms = cl_terms[:limit]

            created_count = 0
            updated_count = 0

            # Use tqdm for progress bar
            with tqdm(total=len(cl_terms), desc="Loading Cell Ontology terms", unit="cells") as pbar:
                for term_data in cl_terms:
                    created, updated = self._process_cell_term(term_data, update_existing)
                    if created:
                        created_count += 1
                    if updated:
                        updated_count += 1

                    pbar.update(1)
                    pbar.set_postfix({"created": created_count, "updated": updated_count})

            self.stdout.write(f"Cell Ontology: {created_count} created, {updated_count} updated")
            return created_count, updated_count

        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Error downloading Cell Ontology: {e}"))
            return 0, 0

    def _process_cell_term(self, term_data, update_existing):
        """Process a single Cell Ontology term."""
        if term_data.get("obsolete", False):
            return False, False

        identifier = term_data.get("id", "")
        name = term_data.get("name", "")
        definition = term_data.get("definition", "")
        synonyms = term_data.get("synonyms", [])
        parent_terms = term_data.get("is_a", [])
        part_of = term_data.get("part_of", [])
        develops_from = term_data.get("develops_from", [])
        replacement = term_data.get("replaced_by", "")

        if not name or not identifier:
            return False, False

        # Determine if this is a cell line based on name/definition
        cell_line = any(keyword in name.lower() for keyword in ["cell line", "cell culture", "cultured"])

        cell_data = {
            "identifier": identifier,
            "name": name,
            "definition": definition,
            "synonyms": ";".join(synonyms) if synonyms else "",
            "accession": identifier,  # Use CL: identifier as accession
            "cell_line": cell_line,
            "source": "cl",
            "parent_terms": ";".join(parent_terms) if parent_terms else "",
            "part_of": ";".join(part_of) if part_of else "",
            "develops_from": ";".join(develops_from) if develops_from else "",
            "replacement_term": replacement,
        }

        try:
            cell_ontology, created = CellOntology.objects.get_or_create(identifier=identifier, defaults=cell_data)

            if not created and update_existing:
                for key, value in cell_data.items():
                    setattr(cell_ontology, key, value)
                cell_ontology.save()
                return False, True

            return created, False

        except Exception as e:
            self.stdout.write(f"Error processing {name}: {e}")
            return False, False
