from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ccv", "0011_add_bto_and_doid_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="metadatatable",
            name="share_token",
            field=models.UUIDField(
                blank=True,
                null=True,
                unique=True,
                help_text="Token for unauthenticated read-only access to this table",
            ),
        ),
        migrations.AddField(
            model_name="historicalmetadatatable",
            name="share_token",
            field=models.UUIDField(
                blank=True,
                null=True,
                help_text="Token for unauthenticated read-only access to this table",
            ),
        ),
    ]
