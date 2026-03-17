# Generated migration for MetadataColumnTemplate validators

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ccv", "0008_schema_manifest_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="metadatacolumntemplate",
            name="validators",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="List of validators from sdrf-pipelines schema with their configurations",
            ),
        ),
        migrations.AddField(
            model_name="metadatacolumntemplate",
            name="input_type",
            field=models.CharField(
                blank=True,
                default="text",
                max_length=50,
                help_text="Input type hint for frontend rendering (text, select, number_with_unit, pattern, ontology)",
            ),
        ),
        migrations.AddField(
            model_name="metadatacolumntemplate",
            name="units",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="List of valid units for number_with_unit input type",
            ),
        ),
    ]
