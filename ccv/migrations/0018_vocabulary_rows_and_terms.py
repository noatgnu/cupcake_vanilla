"""Vocabulary rows for the built-in ontologies, and the cached external terms moved into VocabularyTerm."""

from django.db import migrations

BUILTIN_VOCABULARIES = [
    ("species", "Species"),
    ("tissue", "Tissue"),
    ("human_disease", "Human Disease"),
    ("subcellular_location", "Subcellular Location"),
    ("unimod", "Unimod Modifications"),
    ("ms_unique_vocabularies", "MS Unique Vocabularies"),
    ("ncbi_taxonomy", "NCBI Taxonomy"),
    ("chebi", "ChEBI"),
    ("mondo", "MONDO Disease"),
    ("uberon", "UBERON Anatomy"),
    ("cell_ontology", "Cell Ontology"),
    ("psi_ms", "PSI-MS Controlled Vocabulary"),
    ("bto", "BTO"),
    ("doid", "Disease Ontology"),
]
BATCH_SIZE = 2000


def create_rows_and_move_terms(apps, schema_editor):
    """Create the built-in vocabulary rows and move cached external terms into VocabularyTerm."""
    Vocabulary = apps.get_model("ccv", "Vocabulary")
    VocabularyTerm = apps.get_model("ccv", "VocabularyTerm")
    ExternalTerm = apps.get_model("ccv", "ExternalTerm")

    for key, label in BUILTIN_VOCABULARIES:
        Vocabulary.objects.update_or_create(
            key=key, defaults={"label": label, "provider": "builtin", "storage": "builtin"}
        )

    groups = ExternalTerm.objects.values_list("platform", "kind").distinct()
    for platform, kind in groups:
        vocabulary, _ = Vocabulary.objects.get_or_create(
            key=f"{platform}_{kind}",
            defaults={"label": f"{platform} {kind}", "kind": kind, "provider": "addon", "storage": "terms"},
        )
        batch = []
        for term in ExternalTerm.objects.filter(platform=platform, kind=kind).iterator(chunk_size=BATCH_SIZE):
            batch.append(
                VocabularyTerm(
                    vocabulary=vocabulary,
                    external_id=term.external_id,
                    name=term.name,
                    description=term.description,
                    synonyms=term.synonyms,
                    data=term.data,
                    fetched_at=term.fetched_at,
                )
            )
            if len(batch) >= BATCH_SIZE:
                VocabularyTerm.objects.bulk_create(batch, ignore_conflicts=True)
                batch = []
        if batch:
            VocabularyTerm.objects.bulk_create(batch, ignore_conflicts=True)
        vocabulary.term_count = VocabularyTerm.objects.filter(vocabulary=vocabulary).count()
        vocabulary.save(update_fields=["term_count"])


def move_terms_back(apps, schema_editor):
    """Move vocabulary terms back into ExternalTerm."""
    VocabularyTerm = apps.get_model("ccv", "VocabularyTerm")
    ExternalTerm = apps.get_model("ccv", "ExternalTerm")
    batch = []
    for term in VocabularyTerm.objects.select_related("vocabulary").iterator(chunk_size=BATCH_SIZE):
        platform, _, kind = term.vocabulary.key.rpartition("_")
        batch.append(
            ExternalTerm(
                platform=platform,
                kind=kind,
                external_id=term.external_id,
                name=term.name,
                description=term.description,
                synonyms=term.synonyms,
                data=term.data,
                fetched_at=term.fetched_at,
            )
        )
        if len(batch) >= BATCH_SIZE:
            ExternalTerm.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        ExternalTerm.objects.bulk_create(batch, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("ccv", "0017_vocabulary"),
    ]

    operations = [
        migrations.RunPython(create_rows_and_move_terms, move_terms_back),
    ]
