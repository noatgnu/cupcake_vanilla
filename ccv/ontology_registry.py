from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Callable

from django.db import models as django_models
from django.db.models import Case, IntegerField, Value, When


def _parse_unimod_additional_data(additional_data: list) -> tuple[dict, dict]:
    """Unpack Unimod additional_data into general properties and spec-grouped dicts."""
    general: dict = {}
    specs: dict = {}
    for item in additional_data:
        key = item.get("id", "")
        value = item.get("description", "")
        if key.startswith("spec_") and "_" in key[5:]:
            parts = key.split("_", 2)
            if len(parts) >= 3:
                specs.setdefault(parts[1], {})[parts[2]] = value
        else:
            general[key] = value
    return general, specs


def _serialize_unimod(data: dict, type_key: str) -> dict:
    """Serializer for Unimod entries with additional_data unpacking."""
    additional_data = data.get("additional_data", [])
    general, specs = _parse_unimod_additional_data(additional_data)
    return {
        "id": data.get("accession", ""),
        "value": data.get("accession", ""),
        "display_name": data.get("name", ""),
        "description": data.get("definition", "") or "",
        "ontology_type": type_key,
        "full_data": {
            "accession": data.get("accession", ""),
            "name": data.get("name", ""),
            "definition": data.get("definition", ""),
            "additional_data": additional_data,
            "general_properties": general,
            "specifications": specs,
            "delta_mono_mass": general.get("delta_mono_mass", ""),
            "delta_avge_mass": general.get("delta_avge_mass", ""),
            "delta_composition": general.get("delta_composition", ""),
            "record_id": general.get("record_id", ""),
            "date_posted": general.get("date_time_posted", ""),
            "date_modified": general.get("date_time_modified", ""),
            "approved": general.get("approved", ""),
        },
    }


@dataclass
class OntologyDescriptor:
    """Describes a single ontology type: model, search fields, and serialization mapping."""

    type_key: str
    label: str
    model_label: str
    search_fields: list[str]
    id_field: str
    value_field: str
    display_field: str
    description_field: str
    full_data_fields: list[str]
    description_fallback_field: str | None = None
    id_fallback_field: str | None = None
    id_as_str: bool = False
    value_fallback_field: str | None = None
    display_fallback_field: str | None = None
    priority_fields: list[str] | None = None
    sort_field: str | None = None
    obsolete_filter: bool = False
    custom_serializer: Callable[[dict, str], dict] | None = None

    @cached_property
    def model(self):
        """Lazy model class resolution to avoid circular imports."""
        from django.apps import apps

        return apps.get_model(self.model_label)

    @property
    def choices_tuple(self) -> tuple[str, str]:
        return (self.type_key, self.label)

    def _get_field(self, data: dict, field: str, fallback_field: str | None = None, as_str: bool = False) -> str:
        raw = data.get(field)
        if not raw and fallback_field:
            raw = data.get(fallback_field, "")
        raw = raw or ""
        return str(raw) if as_str else raw

    def serialize(self, data: dict) -> dict:
        """Convert raw ontology model data dict to the standard suggestion format."""
        if self.custom_serializer:
            return self.custom_serializer(data, self.type_key)
        return {
            "id": self._get_field(data, self.id_field, self.id_fallback_field, self.id_as_str),
            "value": self._get_field(data, self.value_field, self.value_fallback_field),
            "display_name": self._get_field(data, self.display_field, self.display_fallback_field),
            "description": self._get_field(data, self.description_field, self.description_fallback_field),
            "ontology_type": self.type_key,
            "full_data": {f: data.get(f, "") for f in self.full_data_fields},
        }

    def build_search_queryset(
        self,
        search_term: str = "",
        search_type: str = "icontains",
        custom_filters: dict | None = None,
    ):
        """Build a filtered, optionally annotated queryset for this ontology type."""
        queryset = self.model.objects.all()

        if self.obsolete_filter:
            queryset = queryset.filter(obsolete=False)

        if custom_filters:
            actual = custom_filters.get(self.type_key, custom_filters)
            for fld, filter_val in actual.items():
                if fld == self.type_key:
                    continue
                if isinstance(filter_val, dict):
                    for lookup, val in filter_val.items():
                        queryset = queryset.filter(**{f"{fld}__{lookup}": val})
                else:
                    queryset = queryset.filter(**{fld: filter_val})

        if search_term:
            combined = django_models.Q(**{f"{self.search_fields[0]}__{search_type}": search_term})
            for sf in self.search_fields[1:]:
                combined |= django_models.Q(**{f"{sf}__{search_type}": search_term})
            queryset = queryset.filter(combined)

        if search_term and search_type in ("icontains", "istartswith") and self.priority_fields:
            pf = self.priority_fields
            whens = [When(**{f"{pf[0]}__iexact": search_term}, then=Value(0))]
            for i, f in enumerate(pf):
                whens.append(When(**{f"{f}__{search_type}": search_term}, then=Value(i + 1)))
            queryset = queryset.annotate(
                priority=Case(*whens, default=Value(len(pf) + 1), output_field=IntegerField())
            ).order_by("priority", self.sort_field or pf[0])

        return queryset

    def get_suggestions(
        self,
        search_term: str = "",
        limit: int = 20,
        search_type: str = "icontains",
        custom_filters: dict | None = None,
    ) -> list[dict]:
        """Return ontology suggestions as a list of raw value dicts."""
        return list(self.build_search_queryset(search_term, search_type, custom_filters)[:limit].values())


@dataclass
class SdrfMapping:
    """Maps one SDRF ontology short-name to an internal type_key with an optional term_type filter.

    column_name_hints maps a column-name keyword to the filter that should be applied when that
    keyword appears in the column name (used for context-dependent types like `ms` and `efo`).
    When no keyword matches, custom_filter is used as the fallback (may be None for no filter).
    is_primary controls whether this mapping sets ontology_type (True) or only adds to
    ontology_options (False).
    """

    sdrf_name: str
    type_key: str
    custom_filter: dict | None = None
    is_primary: bool = True
    column_name_hints: dict[str, dict] | None = None

    def resolve_filter(self, column_name: str) -> dict | None:
        """Return the applicable term_type filter for the given column name."""
        if self.column_name_hints:
            for keyword, hint_filter in self.column_name_hints.items():
                if keyword in column_name.lower():
                    return hint_filter
        return self.custom_filter


class OntologyRegistry:
    """Single source of truth for all ontology type mappings."""

    def __init__(self) -> None:
        """Initialise empty descriptor and SDRF-mapping stores."""
        self._descriptors: dict[str, OntologyDescriptor] = {}
        self._sdrf_mappings: dict[str, list[SdrfMapping]] = {}

    def register(self, descriptor: OntologyDescriptor) -> None:
        self._descriptors[descriptor.type_key] = descriptor

    def register_sdrf_mapping(self, mapping: SdrfMapping) -> None:
        self._sdrf_mappings.setdefault(mapping.sdrf_name, []).append(mapping)

    def get(self, type_key: str) -> OntologyDescriptor | None:
        return self._descriptors.get(type_key)

    def choices(self) -> list[tuple[str, str]]:
        return [d.choices_tuple for d in self._descriptors.values()]

    def get_model(self, type_key: str):
        desc = self.get(type_key)
        return desc.model if desc else None

    def get_sdrf_mappings(self, sdrf_name: str) -> list[SdrfMapping]:
        """Return all SdrfMappings registered for the given SDRF ontology short-name."""
        return self._sdrf_mappings.get(sdrf_name, [])

    def get_suggestions(
        self,
        type_key: str,
        search_term: str = "",
        limit: int = 20,
        search_type: str = "icontains",
        custom_filters: dict | None = None,
    ) -> list[dict]:
        desc = self.get(type_key)
        if not desc:
            return []
        return desc.get_suggestions(search_term, limit, search_type, custom_filters)

    def serialize(self, type_key: str, data: dict) -> dict:
        desc = self.get(type_key)
        if not desc:
            return {
                "id": str(data.get("accession") or data.get("identifier") or data.get("id", "")),
                "value": data.get("accession") or data.get("identifier") or data.get("name", ""),
                "display_name": data.get("name") or data.get("identifier") or data.get("accession", ""),
                "description": data.get("definition", "") or data.get("description", "") or "",
                "ontology_type": type_key,
                "full_data": data,
            }
        return desc.serialize(data)


registry = OntologyRegistry()

registry.register(
    OntologyDescriptor(
        type_key="species",
        label="Species",
        model_label="ccv.Species",
        search_fields=["official_name", "common_name", "code"],
        id_field="taxon",
        id_fallback_field="code",
        id_as_str=True,
        value_field="official_name",
        display_field="official_name",
        description_field="official_name",
        full_data_fields=["code", "taxon", "official_name", "common_name", "synonym"],
        priority_fields=["official_name", "common_name", "code"],
        sort_field="official_name",
    )
)

registry.register(
    OntologyDescriptor(
        type_key="tissue",
        label="Tissue",
        model_label="ccv.Tissue",
        search_fields=["identifier", "accession", "synonyms"],
        id_field="accession",
        value_field="identifier",
        display_field="identifier",
        description_field="synonyms",
        full_data_fields=["identifier", "accession", "synonyms", "cross_references"],
        priority_fields=["identifier"],
        sort_field="identifier",
    )
)

registry.register(
    OntologyDescriptor(
        type_key="human_disease",
        label="Human Disease",
        model_label="ccv.HumanDisease",
        search_fields=["identifier", "acronym", "accession", "definition", "synonyms", "keywords"],
        id_field="accession",
        value_field="identifier",
        display_field="identifier",
        description_field="definition",
        description_fallback_field="synonyms",
        full_data_fields=[
            "identifier",
            "acronym",
            "accession",
            "definition",
            "synonyms",
            "cross_references",
            "keywords",
        ],
        priority_fields=["identifier"],
        sort_field="identifier",
    )
)

registry.register(
    OntologyDescriptor(
        type_key="subcellular_location",
        label="Subcellular Location",
        model_label="ccv.SubcellularLocation",
        search_fields=["accession", "location_identifier", "definition", "synonyms", "content"],
        id_field="accession",
        value_field="location_identifier",
        value_fallback_field="accession",
        display_field="location_identifier",
        display_fallback_field="accession",
        description_field="definition",
        description_fallback_field="synonyms",
        full_data_fields=[
            "location_identifier",
            "topology_identifier",
            "orientation_identifier",
            "accession",
            "definition",
            "synonyms",
        ],
    )
)

registry.register(
    OntologyDescriptor(
        type_key="unimod",
        label="Unimod Modifications",
        model_label="ccv.Unimod",
        search_fields=["accession", "name", "definition"],
        id_field="accession",
        value_field="accession",
        display_field="name",
        description_field="definition",
        full_data_fields=["accession", "name", "definition"],
        priority_fields=["name"],
        sort_field="name",
        custom_serializer=_serialize_unimod,
    )
)

registry.register(
    OntologyDescriptor(
        type_key="ms_unique_vocabularies",
        label="MS Unique Vocabularies",
        model_label="ccv.MSUniqueVocabularies",
        search_fields=["accession", "name", "definition"],
        id_field="accession",
        value_field="accession",
        display_field="name",
        description_field="definition",
        full_data_fields=["accession", "name", "definition", "term_type"],
        priority_fields=["name"],
        sort_field="name",
    )
)

registry.register(
    OntologyDescriptor(
        type_key="ncbi_taxonomy",
        label="NCBI Taxonomy",
        model_label="ccv.NCBITaxonomy",
        search_fields=["scientific_name", "common_name", "synonyms"],
        id_field="tax_id",
        id_as_str=True,
        value_field="scientific_name",
        display_field="scientific_name",
        description_field="common_name",
        description_fallback_field="synonyms",
        full_data_fields=["tax_id", "scientific_name", "common_name", "synonyms", "rank"],
        priority_fields=["scientific_name", "common_name", "synonyms"],
        sort_field="scientific_name",
    )
)

registry.register(
    OntologyDescriptor(
        type_key="chebi",
        label="ChEBI",
        model_label="ccv.ChEBICompound",
        search_fields=["identifier", "name", "definition", "synonyms", "formula"],
        id_field="identifier",
        value_field="identifier",
        display_field="name",
        description_field="definition",
        full_data_fields=[
            "identifier",
            "name",
            "definition",
            "synonyms",
            "formula",
            "mass",
            "charge",
            "inchi",
            "smiles",
            "parent_terms",
            "roles",
        ],
        priority_fields=["name"],
        sort_field="name",
    )
)

registry.register(
    OntologyDescriptor(
        type_key="mondo",
        label="MONDO Disease",
        model_label="ccv.MondoDisease",
        search_fields=["identifier", "name", "definition", "synonyms"],
        id_field="identifier",
        value_field="identifier",
        display_field="name",
        description_field="definition",
        full_data_fields=[
            "identifier",
            "name",
            "definition",
            "synonyms",
            "xrefs",
            "parent_terms",
            "obsolete",
            "replacement_term",
        ],
        priority_fields=["name"],
        sort_field="name",
        obsolete_filter=True,
    )
)

registry.register(
    OntologyDescriptor(
        type_key="uberon",
        label="UBERON Anatomy",
        model_label="ccv.UberonAnatomy",
        search_fields=["identifier", "name", "definition", "synonyms"],
        id_field="identifier",
        value_field="identifier",
        display_field="name",
        description_field="definition",
        full_data_fields=[
            "identifier",
            "name",
            "definition",
            "synonyms",
            "xrefs",
            "parent_terms",
            "part_of",
            "develops_from",
            "obsolete",
            "replacement_term",
        ],
        priority_fields=["name"],
        sort_field="name",
    )
)

registry.register(
    OntologyDescriptor(
        type_key="cell_ontology",
        label="Cell Ontology",
        model_label="ccv.CellOntology",
        search_fields=["identifier", "name", "definition", "synonyms", "organism", "tissue_origin"],
        id_field="identifier",
        value_field="identifier",
        display_field="name",
        description_field="definition",
        description_fallback_field="organism",
        full_data_fields=[
            "identifier",
            "name",
            "definition",
            "synonyms",
            "organism",
            "tissue_origin",
            "cell_line",
            "parent_terms",
            "obsolete",
            "replacement_term",
        ],
        priority_fields=["name"],
        sort_field="name",
    )
)

registry.register(
    OntologyDescriptor(
        type_key="psi_ms",
        label="PSI-MS Controlled Vocabulary",
        model_label="ccv.PSIMSOntology",
        search_fields=["identifier", "name", "definition", "synonyms"],
        id_field="identifier",
        value_field="identifier",
        display_field="name",
        description_field="definition",
        full_data_fields=[
            "identifier",
            "name",
            "definition",
            "synonyms",
            "parent_terms",
            "category",
            "obsolete",
            "replacement_term",
        ],
        priority_fields=["name"],
        sort_field="name",
    )
)

registry.register(
    OntologyDescriptor(
        type_key="bto",
        label="BTO",
        model_label="ccv.BTOTerm",
        search_fields=["identifier", "name", "synonyms", "definition"],
        id_field="identifier",
        value_field="identifier",
        display_field="name",
        description_field="definition",
        description_fallback_field="synonyms",
        full_data_fields=[
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
        obsolete_filter=True,
    )
)

registry.register(
    OntologyDescriptor(
        type_key="doid",
        label="Disease Ontology",
        model_label="ccv.DiseaseOntologyTerm",
        search_fields=["identifier", "name", "synonyms", "definition"],
        id_field="identifier",
        value_field="identifier",
        display_field="name",
        description_field="definition",
        description_fallback_field="synonyms",
        full_data_fields=[
            "identifier",
            "name",
            "definition",
            "synonyms",
            "xrefs",
            "parent_terms",
            "obsolete",
            "replacement_term",
        ],
        obsolete_filter=True,
    )
)

# ---------------------------------------------------------------------------
# SDRF ontology short-name → internal type mappings
# ---------------------------------------------------------------------------

# ncbitaxon: species is the primary query target; ncbi_taxonomy is kept as an option
registry.register_sdrf_mapping(SdrfMapping(sdrf_name="ncbitaxon", type_key="species", is_primary=True))
registry.register_sdrf_mapping(SdrfMapping(sdrf_name="ncbitaxon", type_key="ncbi_taxonomy", is_primary=False))

# cl (Cell Ontology)
registry.register_sdrf_mapping(SdrfMapping(sdrf_name="cl", type_key="cell_ontology"))

# unimod
registry.register_sdrf_mapping(SdrfMapping(sdrf_name="unimod", type_key="unimod"))

# uberon
registry.register_sdrf_mapping(SdrfMapping(sdrf_name="uberon", type_key="uberon"))

# bto
registry.register_sdrf_mapping(SdrfMapping(sdrf_name="bto", type_key="bto"))

# chebi
registry.register_sdrf_mapping(SdrfMapping(sdrf_name="chebi", type_key="chebi"))

# doid
registry.register_sdrf_mapping(SdrfMapping(sdrf_name="doid", type_key="doid"))

# mondo: human_disease is primary; mondo kept as additional option
registry.register_sdrf_mapping(SdrfMapping(sdrf_name="mondo", type_key="human_disease", is_primary=True))
registry.register_sdrf_mapping(SdrfMapping(sdrf_name="mondo", type_key="mondo", is_primary=False))

# pride: broad sample-attribute catch-all from PRIDE vocabulary
registry.register_sdrf_mapping(
    SdrfMapping(
        sdrf_name="pride",
        type_key="ms_unique_vocabularies",
        custom_filter={"term_type": "sample attribute"},
    )
)

# clo (Cell Line Ontology) → stored in ms_unique_vocabularies as term_type=cell line
registry.register_sdrf_mapping(
    SdrfMapping(
        sdrf_name="clo",
        type_key="ms_unique_vocabularies",
        custom_filter={"term_type": "cell line"},
    )
)

# hancestro → stored in ms_unique_vocabularies as term_type=ancestral category
registry.register_sdrf_mapping(
    SdrfMapping(
        sdrf_name="hancestro",
        type_key="ms_unique_vocabularies",
        custom_filter={"term_type": "ancestral category"},
    )
)

# pato (sex terms) → stored in ms_unique_vocabularies as term_type=sex
registry.register_sdrf_mapping(
    SdrfMapping(
        sdrf_name="pato",
        type_key="ms_unique_vocabularies",
        custom_filter={"term_type": "sex"},
    )
)

# efo: context-dependent term_type based on column name
registry.register_sdrf_mapping(
    SdrfMapping(
        sdrf_name="efo",
        type_key="ms_unique_vocabularies",
        column_name_hints={
            "cell line": {"term_type": "cell line"},
            "developmental stage": {"term_type": "developmental stage"},
            "enrichment": {"term_type": "enrichment process"},
        },
    )
)

# ms (PSI-MS): context-dependent term_type based on column name
registry.register_sdrf_mapping(
    SdrfMapping(
        sdrf_name="ms",
        type_key="ms_unique_vocabularies",
        column_name_hints={
            "instrument": {"term_type": "instrument"},
            "analyzer": {"term_type": "mass analyzer type"},
            "cleavage": {"term_type": "cleavage agent"},
            "dissociation": {"term_type": "dissociation method"},
            "reduction": {"term_type": "reduction reagent"},
            "alkylation": {"term_type": "alkylation reagent"},
        },
    )
)
