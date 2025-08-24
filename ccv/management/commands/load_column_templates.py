"""
Management command to load standard metadata column templates.

This command creates predefined templates for common metadata columns
with appropriate ontology mappings and validation settings.
"""

import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import models

from ccv.models import MetadataColumnTemplate, Schema
from ccv.utils import SchemaRegistry, get_specific_default_schema


class Command(BaseCommand):
    help = "Load standard metadata column templates with ontology mappings"

    def add_arguments(self, parser):
        parser.add_argument(
            "--admin-user",
            type=str,
            help="Username of admin user to create templates (defaults to first superuser)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing system templates before loading new ones",
        )
        parser.add_argument(
            "--schema",
            type=str,
            default="minimum",
            help="Specific schema to load (defaults to 'minimum')",
        )
        parser.add_argument(
            "--schema-file",
            type=str,
            help="Path to schema file if not found in system schemas",
        )
        parser.add_argument(
            "--schema-dir",
            type=str,
            help="Directory containing schema files",
        )

    def handle(self, *args, **options):
        # Get admin user
        admin_user = self.get_admin_user(options)
        if not admin_user:
            return

        schema_name = options.get("schema", "minimum")
        schema_file = options.get("schema_file")
        schema_dir = options.get("schema_dir")

        self.stdout.write(f"Using admin user: {admin_user.username}")
        self.stdout.write(f"Loading schema: {schema_name}")

        # Clear existing templates for this schema if requested
        if options["clear"]:
            self.clear_schema_templates(schema_name)

        # Get or create Schema model instance
        schema_obj = self.get_or_create_schema_object(schema_name, admin_user)
        if not schema_obj:
            return

        # Load the schema definition
        schema = self.load_schema(schema_name, schema_file, schema_dir)
        if not schema:
            return

        # Process columns from schema
        templates_created = self.process_schema_columns(schema, admin_user, schema_name, schema_obj)

        self.stdout.write(self.style.SUCCESS(f"\nLoaded {templates_created} templates from schema '{schema_name}'"))

    def get_admin_user(self, options):
        """Get the admin user for creating templates."""
        admin_username = options.get("admin_user")
        if admin_username:
            try:
                admin_user = User.objects.get(username=admin_username, is_staff=True)
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Admin user '{admin_username}' not found or not staff"))
                return None
        else:
            admin_user = User.objects.filter(is_superuser=True).first()
            if not admin_user:
                self.stdout.write(self.style.ERROR("No superuser found. Please create one first."))
                return None
        return admin_user

    def get_or_create_schema_object(self, schema_name, admin_user):
        """Get or create a Schema object for the given schema name."""
        try:
            schema_obj = Schema.objects.get(name=schema_name, is_builtin=True)
            self.stdout.write(f"Found existing Schema object: {schema_obj.display_name}")
            return schema_obj
        except Schema.DoesNotExist:
            # Try to sync schemas first
            self.stdout.write(f"Schema object '{schema_name}' not found, attempting to sync...")
            try:
                result = Schema.sync_builtin_schemas()
                if "error" in result:
                    self.stdout.write(self.style.ERROR(f"Error syncing schemas: {result['error']}"))
                    return None

                # Try to get the schema again after sync
                try:
                    schema_obj = Schema.objects.get(name=schema_name, is_builtin=True)
                    self.stdout.write(f"Created Schema object after sync: {schema_obj.display_name}")
                    return schema_obj
                except Schema.DoesNotExist:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Schema '{schema_name}' not found even after sync. "
                            f"This schema may not be available in sdrf-pipelines."
                        )
                    )
                    return None
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error during schema sync: {str(e)}"))
                return None

    def clear_schema_templates(self, schema_name):
        """Clear existing templates for a specific schema."""
        # Clear by both source_schema name and Schema object
        deleted_count = MetadataColumnTemplate.objects.filter(
            models.Q(source_schema=schema_name) | models.Q(schema__name=schema_name), is_system_template=True
        ).count()

        if deleted_count > 0:
            MetadataColumnTemplate.objects.filter(
                models.Q(source_schema=schema_name) | models.Q(schema__name=schema_name), is_system_template=True
            ).delete()
            self.stdout.write(
                self.style.WARNING(f"Deleted {deleted_count} existing templates for schema '{schema_name}'")
            )
        else:
            self.stdout.write(f"No existing templates found for schema '{schema_name}'")

    def load_schema(self, schema_name, schema_file, schema_dir):
        """Load schema from system or file."""
        # Try to get from system schemas first
        try:
            schema = get_specific_default_schema(schema_name)
            if schema:
                self.stdout.write(f"Loaded system schema: {schema_name}")
                return schema
        except Exception as e:
            self.stdout.write(f"System schema '{schema_name}' not found: {e}")

        # Fallback to file schema
        if schema_file:
            if not os.path.exists(schema_file):
                self.stdout.write(self.style.ERROR(f"Schema file not found: {schema_file}"))
                return None

            try:
                # Create a custom registry with the file
                registry = SchemaRegistry(schema_dir)
                schema = registry.load_schema_from_file(schema_file)
                if schema:
                    self.stdout.write(f"Loaded schema from file: {schema_file}")
                    return schema
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error loading schema from file: {e}"))
                return None

        # Try schema directory if provided
        if schema_dir:
            try:
                registry = SchemaRegistry(schema_dir)
                schema = registry.get_schema(schema_name)
                if schema:
                    self.stdout.write(f"Loaded schema '{schema_name}' from directory: {schema_dir}")
                    return schema
            except Exception as e:
                self.stdout.write(f"Error loading from schema directory: {e}")

        self.stdout.write(self.style.ERROR(f"Could not load schema '{schema_name}' from any source"))
        return None

    def process_schema_columns(self, schema, admin_user, schema_name, schema_obj):
        """Process columns from schema and create templates."""
        templates_created = 0

        for column in schema.columns:
            column_type = ""
            column_name = column.name
            display_name = column.name

            # Parse column type from name
            if column.name.startswith("characteristics"):
                column_type = "characteristics"
                display_name = column.name.split("[")[1].split("]")[0]
            elif column.name.startswith("comment"):
                column_type = "comment"
                display_name = column.name.split("[")[1].split("]")[0]
            elif column.name.startswith("factor value"):
                column_type = "factor value"
                display_name = column.name.split("[")[1].split("]")[0]
            elif column.name == "source name":
                column_type = "source_name"
            else:
                column_type = "special"

            # Create template
            template = MetadataColumnTemplate(
                name=display_name,
                description=column.description or f"Template for {display_name}",
                column_name=column_name,
                column_type=column_type,
                base_column=True,
                is_system_template=True,
                owner=admin_user,
                category=f"{schema_name.title()} Schema",
                source_schema=schema_name,
                schema=schema_obj,  # Link to Schema object
                visibility="public",
            )

            # Process validators for ontology configuration
            self.configure_ontology_options(template, column)

            template.save()
            templates_created += 1

            # Increment usage count on the schema
            if schema_obj:
                schema_obj.usage_count += 1
                schema_obj.save(update_fields=["usage_count"])

            self.stdout.write(f"Created template: {display_name} ({column_type})")

        return templates_created

    def configure_ontology_options(self, template, column):
        """Configure ontology options based on column validators."""
        if "organism part" in template.column_name.lower():
            template.ontology_options = ["tissue", "uberon"]
            template.ontology_type = "tissue"

        for validator in column.validators:
            if validator.validator_name == "ontology":
                custom_filter = {}
                template.enable_typeahead = True
                template.ontology_options = []

                for ontology in validator.params.get("ontologies", []):
                    if ontology == "ncbitaxon":
                        template.ontology_options.extend(["ncbi_taxonomy", "species"])
                        template.ontology_type = "species"
                    elif ontology == "cl":
                        template.ontology_options.append("cell_ontology")
                        template.ontology_type = "cell_ontology"
                    elif ontology == "pride":
                        template.ontology_options.append("ms_unique_vocabularies")
                        custom_filter["ms_unique_vocabularies"] = {"term_type": "sample attribute"}
                        template.ontology_type = "ms_unique_vocabularies"
                    elif ontology == "unimod":
                        template.ontology_options.append("unimod")
                        template.ontology_type = "unimod"
                    elif ontology == "ms":
                        template.ontology_options.append("ms_unique_vocabularies")
                        # Set specific filters based on column name
                        if "instrument" in template.column_name.lower():
                            custom_filter["ms_unique_vocabularies"] = {"term_type": "instrument"}
                        elif "analyzer" in template.column_name.lower():
                            custom_filter["ms_unique_vocabularies"] = {"term_type": "ms analyzer type"}
                        elif "cleavage" in template.column_name.lower():
                            custom_filter["ms_unique_vocabularies"] = {"term_type": "cleavage agent"}
                        template.ontology_type = "ms_unique_vocabularies"
                    elif ontology == "mondo":
                        template.ontology_options.extend(["human_disease", "mondo"])
                        template.ontology_type = "human_disease"
                    elif ontology == "clo":
                        template.ontology_options.append("ms_unique_vocabularies")
                        custom_filter["ms_unique_vocabularies"] = {"term_type": "cell line"}
                        template.ontology_type = "ms_unique_vocabularies"

                # Handle special column-specific configurations
                if "ancestry category" in template.column_name.lower():
                    template.ontology_options.append("ms_unique_vocabularies")
                    custom_filter["ms_unique_vocabularies"] = {"term_type": "ancestral category"}
                    template.ontology_type = "ms_unique_vocabularies"
                elif "sex" in template.column_name.lower():
                    template.ontology_options.append("ms_unique_vocabularies")
                    custom_filter["ms_unique_vocabularies"] = {"term_type": "sex"}
                    template.ontology_type = "ms_unique_vocabularies"
                elif "developmental stage" in template.column_name.lower():
                    template.ontology_options.append("ms_unique_vocabularies")
                    custom_filter["ms_unique_vocabularies"] = {"term_type": "developmental stage"}
                    template.ontology_type = "ms_unique_vocabularies"

                # Set custom filters if any were configured
                if custom_filter:
                    template.custom_ontology_filters = custom_filter
