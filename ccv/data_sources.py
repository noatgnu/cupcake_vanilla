"""
Records which upstream release each loaded reference dataset came from, so snapshot exports and
release notes can state the source version and the date it was published.

Keys follow the mobile snapshot manifest as "<dataset>:<name>", for example ontology:mondo,
schema:sdrf or column-template:system.
"""

import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

from django.utils import timezone

import requests

from ccv.models import DataSourceVersion

OBO_HEADER_BYTES = 65536
OLS_ONTOLOGY_URL = "https://www.ebi.ac.uk/ols4/api/ontologies/{}"
ISO_DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")
DOTTED_VERSION_PATTERN = re.compile(r"/v?(\d+(?:\.\d+)+)/")
UNIPROT_RELEASE_PATTERN = re.compile(r"^Release:\s+(\S+)\s+of\s+(\d{2}-[A-Za-z]{3}-\d{4})", re.MULTILINE)


def obo_release(content):
    """
    Return (version, release date) from the header of an OBO file.

    data-version values such as "releases/2026-09-30/doid.obo" are reduced to the release
    ("2026-09-30"); numbered releases such as ChEBI's "256" are kept. The release date is the
    date inside data-version when there is one, otherwise the date: header, which records the
    last edit and can predate a dated release.
    """
    if isinstance(content, bytes):
        content = content[:OBO_HEADER_BYTES].decode("utf-8", errors="replace")
    data_version = ""
    released = None
    for line in content[:OBO_HEADER_BYTES].splitlines():
        if line.startswith("["):
            break
        if line.startswith("data-version:"):
            data_version = line.split(":", 1)[1].strip()
        elif line.startswith("date:"):
            try:
                released = datetime.strptime(line.split(":", 1)[1].strip(), "%d:%m:%Y %H:%M").date()
            except ValueError:
                pass

    embedded_date = ISO_DATE_PATTERN.search(data_version)
    if embedded_date:
        released = date.fromisoformat(embedded_date.group(1))
    version = embedded_date.group(1) if embedded_date else data_version
    if not version and released:
        version = released.isoformat()
    return version, released


def uniprot_release(content):
    """Return (version, release date) from the "Release: 2026_03 of 02-Sep-2026" line of a UniProt list."""
    match = UNIPROT_RELEASE_PATTERN.search(content[:OBO_HEADER_BYTES])
    if not match:
        return "", None
    return match.group(1), datetime.strptime(match.group(2), "%d-%b-%Y").date()


def last_modified_release(response):
    """Return (version, release date) from the Last-Modified header of a download."""
    header = response.headers.get("Last-Modified")
    if not header:
        return "", None
    released = parsedate_to_datetime(header).date()
    return released.isoformat(), released


def ols_release(ontology_id):
    """Return (version, release date) of the ontology build currently served by OLS."""
    response = requests.get(OLS_ONTOLOGY_URL.format(ontology_id), timeout=30)
    response.raise_for_status()
    config = response.json().get("config", {})
    version_iri = config.get("versionIri") or ""
    embedded_date = ISO_DATE_PATTERN.search(version_iri)
    dotted = DOTTED_VERSION_PATTERN.search(version_iri)
    version = (
        config.get("version")
        or (embedded_date.group(1) if embedded_date else "")
        or (dotted.group(1) if dotted else "")
    )
    released = date.fromisoformat(embedded_date.group(1)) if embedded_date else None
    return version, released


def sdrf_pipelines_version():
    """Return the installed sdrf-pipelines version that builtin schemas are read from."""
    try:
        return package_version("sdrf-pipelines")
    except PackageNotFoundError:
        return ""


def record_sdrf_pipelines_source(key):
    """Record that key was built from the installed sdrf-pipelines release."""
    version = sdrf_pipelines_version()
    return record_source(key, f"https://pypi.org/project/sdrf-pipelines/{version}/", version)


def record_source(key, source_url, version="", released=None):
    """Store the upstream release just loaded for key, replacing any earlier record."""
    record, _ = DataSourceVersion.objects.update_or_create(
        key=key,
        defaults={
            "source_url": source_url,
            "version": version or "",
            "released": released,
            "retrieved_at": timezone.now(),
        },
    )
    return record


def source_entry(key):
    """Return the recorded source of key as a manifest-ready dict, or None when it was never recorded."""
    record = DataSourceVersion.objects.filter(key=key).first()
    if record is None:
        return None
    return {
        "url": record.source_url,
        "version": record.version,
        "released": record.released.isoformat() if record.released else None,
        "retrieved_at": record.retrieved_at.isoformat(),
    }
