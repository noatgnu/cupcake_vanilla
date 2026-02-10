"""
Data migration to update builtin schema names to new sdrf-pipelines naming convention.

Legacy names -> New names:
- minimum -> base
- default -> ms-proteomics
- cell_lines -> cell-lines
- nonvertebrates -> invertebrates
"""

from django.db import migrations

LEGACY_NAME_MAPPING = {
    "minimum": "base",
    "default": "ms-proteomics",
    "cell_lines": "cell-lines",
    "nonvertebrates": "invertebrates",
}


def migrate_schema_names_forward(apps, schema_editor):
    """Rename legacy schema names to new naming convention."""
    Schema = apps.get_model("ccv", "Schema")

    for old_name, new_name in LEGACY_NAME_MAPPING.items():
        try:
            schema = Schema.objects.filter(name=old_name, is_builtin=True).first()
            if schema:
                if Schema.objects.filter(name=new_name).exists():
                    Schema.objects.filter(name=new_name).delete()

                schema.name = new_name
                schema.display_name = new_name.replace("-", " ").replace("_", " ").title()
                schema.save()
                print(f"Renamed schema '{old_name}' to '{new_name}'")
        except Exception as e:
            print(f"Error migrating schema '{old_name}': {e}")


def migrate_schema_names_reverse(apps, schema_editor):
    """Revert schema names to legacy naming convention."""
    Schema = apps.get_model("ccv", "Schema")

    reverse_mapping = {v: k for k, v in LEGACY_NAME_MAPPING.items()}

    for new_name, old_name in reverse_mapping.items():
        try:
            schema = Schema.objects.filter(name=new_name, is_builtin=True).first()
            if schema:
                if Schema.objects.filter(name=old_name).exists():
                    Schema.objects.filter(name=old_name).delete()

                schema.name = old_name
                schema.display_name = old_name.replace("_", " ").title()
                schema.save()
                print(f"Reverted schema '{new_name}' to '{old_name}'")
        except Exception as e:
            print(f"Error reverting schema '{new_name}': {e}")


class Migration(migrations.Migration):
    dependencies = [
        ("ccv", "0006_move_asynctaskstatus_to_ccc"),
    ]

    operations = [
        migrations.RunPython(
            migrate_schema_names_forward,
            migrate_schema_names_reverse,
        ),
    ]
