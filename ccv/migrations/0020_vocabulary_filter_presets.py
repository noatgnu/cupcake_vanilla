"""Filter presets for vocabularies, the labels users see for the built-in ontologies, and the MS term type presets."""

from django.db import migrations, models

BUILTIN_LABELS = {
    "species": "Species (UniProt)",
    "ncbi_taxonomy": "NCBI Taxonomy",
    "tissue": "Tissue (UniProt)",
    "human_disease": "Human Disease (UniProt)",
    "mondo": "MONDO Disease",
    "unimod": "Modification (Unimod)",
    "uberon": "Uberon Anatomy",
    "subcellular_location": "Subcellular Location (UniProt)",
    "chebi": "ChEBI",
    "cell_ontology": "Cell Ontology",
    "psi_ms": "PSI-MS",
    "bto": "BTO Tissue (BRENDA)",
    "doid": "Disease Ontology (DOID)",
    "ms_unique_vocabularies": "MS Unique Vocabularies",
}
MS_TERM_TYPES = [
    ("Sample Attribute (MS)", "sample attribute"),
    ("Instrument (MS)", "instrument"),
    ("MS Analyzer Type (MS)", "mass analyzer type"),
    ("Cleavage Agent (MS)", "cleavage agent"),
    ("Dissociation Method (MS)", "dissociation method"),
    ("Cell Line (MS)", "cell line"),
    ("Enrichment Process (MS)", "enrichment process"),
    ("Fractionation Method (MS)", "fractionation method"),
    ("Data Acquisition Method (MS)", "proteomics data acquisition method"),
    ("Reduction Reagent (MS)", "reduction reagent"),
    ("Alkylation Reagent (MS)", "alkylation reagent"),
    ("Ancestral Category (MS)", "ancestral category"),
    ("Sex (MS)", "sex"),
    ("Developmental Stage (MS)", "developmental stage"),
]


def set_labels_and_presets(apps, schema_editor):
    """Give built-in vocabularies their user-facing labels and the MS vocabulary its term type presets."""
    Vocabulary = apps.get_model("ccv", "Vocabulary")
    for key, label in BUILTIN_LABELS.items():
        Vocabulary.objects.filter(key=key).update(label=label)
    Vocabulary.objects.filter(key="ms_unique_vocabularies").update(
        filter_presets=[{"label": label, "filters": {"term_type": term_type}} for label, term_type in MS_TERM_TYPES]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ccv", "0019_remove_external_term_and_ontology_type_choices"),
    ]

    operations = [
        migrations.AddField(
            model_name="vocabulary",
            name="filter_presets",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Named search filters offered as separate choices, for example [{"label": "Instrument (MS)", '
                '"filters": {"term_type": "instrument"}}]',
            ),
        ),
        migrations.RunPython(set_labels_and_presets, migrations.RunPython.noop),
    ]
