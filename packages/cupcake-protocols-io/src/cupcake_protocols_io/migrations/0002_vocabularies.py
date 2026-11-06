"""The protocols.io reagent and unit vocabularies, with the classes that search protocols.io for them."""

from django.db import migrations

VOCABULARIES = [
    {
        "key": "protocols_io_reagent",
        "label": "Reagent (protocols.io)",
        "kind": "reagent",
        "live_search_adapter": "cupcake_protocols_io.external_vocabularies.ProtocolsIOReagentSource",
        "min_term_length": 3,
    },
    {
        "key": "protocols_io_unit",
        "label": "Unit (protocols.io)",
        "kind": "unit",
        "live_search_adapter": "cupcake_protocols_io.external_vocabularies.ProtocolsIOUnitSource",
        "min_term_length": 3,
    },
]


def create_vocabularies(apps, schema_editor):
    """Create or update the protocols.io vocabulary rows."""
    Vocabulary = apps.get_model("ccv", "Vocabulary")
    for vocabulary in VOCABULARIES:
        Vocabulary.objects.update_or_create(
            key=vocabulary["key"],
            defaults={**vocabulary, "provider": "addon", "storage": "terms", "approved": True},
        )


def remove_vocabularies(apps, schema_editor):
    """Remove the protocols.io vocabulary rows."""
    Vocabulary = apps.get_model("ccv", "Vocabulary")
    Vocabulary.objects.filter(key__in=[vocabulary["key"] for vocabulary in VOCABULARIES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("protocols_io", "0001_initial"),
        ("ccv", "0018_vocabulary_rows_and_terms"),
    ]

    operations = [
        migrations.RunPython(create_vocabularies, remove_vocabularies),
    ]
