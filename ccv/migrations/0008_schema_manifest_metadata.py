"""
Add manifest metadata fields to Schema model for sdrf-pipelines integration.

New fields:
- version: Schema version string
- extends: Parent template reference
- usable_alone: Whether template can be used standalone
- layer: Template layer (technology/sample/experiment)
- requires: Required template layers (JSON)
- excludes: Excluded templates when combining (JSON)
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ccv", "0007_migrate_schema_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="schema",
            name="version",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Schema version string",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="schema",
            name="extends",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Parent template this schema extends",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="schema",
            name="usable_alone",
            field=models.BooleanField(
                default=True,
                help_text="Whether this schema can be used standalone without combining with others",
            ),
        ),
        migrations.AddField(
            model_name="schema",
            name="layer",
            field=models.CharField(
                blank=True,
                choices=[
                    ("technology", "Technology"),
                    ("sample", "Sample"),
                    ("experiment", "Experiment"),
                ],
                default="",
                help_text="Template layer type",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="schema",
            name="requires",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Required template layers when using this schema",
            ),
        ),
        migrations.AddField(
            model_name="schema",
            name="excludes",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Templates to exclude when combining with this schema",
            ),
        ),
    ]
