"""Reading vocabulary terms from OBO, OWL, CSV and TSV files."""

from __future__ import annotations

import csv
import warnings
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pronto

FORMATS = ("obo", "owl", "csv", "tsv")
PREVIEW_ROWS = 10


class VocabularyFileError(Exception):
    """Raised when a vocabulary file cannot be read."""


@dataclass(frozen=True)
class ImportedTerm:
    """One term read from a vocabulary file."""

    external_id: str
    name: str
    description: str = ""
    synonyms: tuple[str, ...] = ()
    obsolete: bool = False
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ColumnMapping:
    """Which columns of a CSV or TSV file hold each part of a term."""

    name_column: str
    id_column: str = ""
    description_column: str = ""
    synonyms_column: str = ""
    synonym_separator: str = ";"


def detect_format(file_name: str) -> str:
    """The format of a vocabulary file from its extension."""
    suffix = Path(file_name).suffix.lower().lstrip(".")
    if suffix == "txt":
        return "tsv"
    if suffix in FORMATS:
        return suffix
    raise VocabularyFileError(f"Cannot tell the format of {file_name!r}; use .obo, .owl, .csv or .tsv")


def delimiter(file_format: str) -> str:
    """The column separator of a CSV or TSV file."""
    return "," if file_format == "csv" else "\t"


def read_vocabulary_file(
    path: Path, file_format: str, mapping: ColumnMapping | None = None
) -> tuple[str, Iterator[ImportedTerm]]:
    """
    The data version a file declares and its terms; OBO and OWL files are parsed once.

    Args:
        path: The file.
        file_format: One of obo, owl, csv or tsv.
        mapping: Columns to read from CSV and TSV files.

    Raises:
        VocabularyFileError: When the file cannot be read.
    """
    if file_format in ("obo", "owl"):
        ontology = _load_ontology(path)
        return ontology.metadata.data_version or "", _ontology_terms(ontology)
    if file_format in ("csv", "tsv"):
        if mapping is None or not mapping.name_column:
            raise VocabularyFileError("Choose the column that holds the term names")
        return "", _table_terms(path, delimiter(file_format), mapping)
    raise VocabularyFileError(f"Unsupported format {file_format!r}")


def preview_table(path: Path, file_format: str) -> dict:
    """The columns and first rows of a CSV or TSV file."""
    if file_format not in ("csv", "tsv"):
        raise VocabularyFileError("Previews are only available for CSV and TSV files")
    with _open_text(path) as handle:
        reader = csv.reader(handle, delimiter=delimiter(file_format))
        columns = next(reader, [])
        rows = [row for _, row in zip(range(PREVIEW_ROWS), reader)]
    if not columns:
        raise VocabularyFileError("The file is empty")
    return {"columns": columns, "rows": rows}


def _load_ontology(path: Path) -> pronto.Ontology:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return pronto.Ontology(str(path))
    except Exception as error:
        raise VocabularyFileError(f"The ontology file could not be read: {error}") from error


def _ontology_terms(ontology: pronto.Ontology) -> Iterator[ImportedTerm]:
    for term in ontology.terms():
        if not term.name:
            continue
        yield ImportedTerm(
            external_id=term.id,
            name=term.name,
            description=str(term.definition or ""),
            synonyms=tuple(sorted(synonym.description for synonym in term.synonyms)),
            obsolete=bool(term.obsolete),
            data={"parents": sorted(parent.id for parent in term.superclasses(distance=1, with_self=False))},
        )


def _table_terms(path: Path, separator: str, mapping: ColumnMapping) -> Iterator[ImportedTerm]:
    with _open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter=separator)
        columns = reader.fieldnames or []
        for column in (mapping.name_column, mapping.id_column, mapping.description_column, mapping.synonyms_column):
            if column and column not in columns:
                raise VocabularyFileError(f"The file has no column {column!r}")
        for row in reader:
            name = (row.get(mapping.name_column) or "").strip()
            if not name:
                continue
            external_id = (row.get(mapping.id_column) or "").strip() if mapping.id_column else name
            if not external_id:
                continue
            synonyms = ()
            if mapping.synonyms_column:
                raw = row.get(mapping.synonyms_column) or ""
                synonyms = tuple(part.strip() for part in raw.split(mapping.synonym_separator or ";") if part.strip())
            yield ImportedTerm(
                external_id=external_id,
                name=name,
                description=(row.get(mapping.description_column) or "").strip() if mapping.description_column else "",
                synonyms=synonyms,
                data={key: value for key, value in row.items() if key},
            )


def _open_text(path: Path):
    try:
        return open(path, encoding="utf-8-sig", newline="")
    except OSError as error:
        raise VocabularyFileError(f"The file could not be opened: {error}") from error
