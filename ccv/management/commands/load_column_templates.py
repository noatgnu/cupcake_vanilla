"""
Management command to load standard metadata column templates.

This command creates predefined templates for common metadata columns
with appropriate ontology mappings and validation settings.
"""

import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import models

import yaml

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
            "--update-references",
            action="store_true",
            help="Update existing MetadataColumn references to point to newly created templates (use with --clear)",
        )
        parser.add_argument(
            "--schema",
            type=str,
            default=None,
            help="Specific schema to load (if not specified, loads all available schemas)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Load all available schemas (default behavior)",
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

        schema_name = options.get("schema")
        schema_file = options.get("schema_file")
        schema_dir = options.get("schema_dir")
        load_all = options.get("all", False)
        update_references = options.get("update_references", False)

        self.stdout.write(f"Using admin user: {admin_user.username}")

        # Determine which schemas to load
        schemas_to_load = []
        if schema_name:
            # Load specific schema
            schemas_to_load = [schema_name]
            self.stdout.write(f"Loading specific schema: {schema_name}")
        elif load_all or not schema_name:
            # Load all available schemas (default behavior)
            from ccv.utils import get_all_default_schema_names

            schemas_to_load = get_all_default_schema_names()
            self.stdout.write(f"Loading all available schemas: {', '.join(schemas_to_load)}")

        if update_references and not options["clear"]:
            self.stdout.write(
                self.style.WARNING(
                    "\n⚠️  --update-references flag requires --clear to be set. Ignoring --update-references.\n"
                )
            )
            update_references = False

        total_templates_created = 0
        total_references_updated = 0

        # Track old template mappings for reference updates
        old_template_mapping = {}  # Maps (schema_name, column_name) -> old_template_id

        # Process each schema
        for schema_name in schemas_to_load:
            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(f"Processing schema: {schema_name}")
            self.stdout.write(f"{'='*60}")

            # Clear existing templates for this schema if requested
            if options["clear"]:
                old_template_mapping.update(self.clear_schema_templates(schema_name, update_references))

            # Get or create Schema model instance
            schema_obj = self.get_or_create_schema_object(schema_name, admin_user)
            if not schema_obj:
                self.stdout.write(
                    self.style.WARNING(f"Skipping schema '{schema_name}' - could not get/create Schema object")
                )
                continue

            # Load the schema definition
            schema = self.load_schema(schema_name, schema_file, schema_dir)
            if not schema:
                self.stdout.write(
                    self.style.WARNING(f"Skipping schema '{schema_name}' - could not load schema definition")
                )
                continue

            # Process columns from schema
            new_templates = self.process_schema_columns(schema, admin_user, schema_name, schema_obj)
            total_templates_created += len(new_templates)

            # Update references if requested
            if update_references and old_template_mapping:
                updated_count = self.update_column_references(schema_name, old_template_mapping, new_templates)
                total_references_updated += updated_count

            self.stdout.write(self.style.SUCCESS(f"Loaded {len(new_templates)} templates from schema '{schema_name}'"))

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(
            self.style.SUCCESS(
                f"TOTAL: Loaded {total_templates_created} templates from {len(schemas_to_load)} schema(s)"
            )
        )

        if update_references:
            self.stdout.write(self.style.SUCCESS(f"TOTAL: Updated {total_references_updated} column references"))

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

    def clear_schema_templates(self, schema_name, track_for_update=False):
        """
        Clear existing templates for a specific schema.

        Args:
            schema_name: Name of the schema
            track_for_update: If True, returns mapping of old templates for reference updates

        Returns:
            dict: Mapping of (schema_name, column_name) -> template_id (if track_for_update)
        """
        from ccv.models import MetadataColumn

        old_template_mapping = {}

        # Find templates to delete
        templates_to_delete = MetadataColumnTemplate.objects.filter(
            models.Q(source_schema=schema_name) | models.Q(schema__name=schema_name), is_system_template=True
        )

        deleted_count = templates_to_delete.count()

        if deleted_count > 0:
            # Track old template info if needed for updates
            if track_for_update:
                for template in templates_to_delete:
                    key = (schema_name, template.column_name)
                    old_template_mapping[key] = template.id

            # Check if any templates are being used by existing MetadataColumns
            templates_in_use = []
            for template in templates_to_delete:
                usage_count = MetadataColumn.objects.filter(template=template).count()
                if usage_count > 0:
                    templates_in_use.append({"template": template, "usage_count": usage_count})

            if templates_in_use:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n⚠️  {len(templates_in_use)} template(s) are currently in use by existing metadata columns:"
                    )
                )
                for item in templates_in_use[:5]:  # Show first 5
                    self.stdout.write(f"   - '{item['template'].name}' used by {item['usage_count']} column(s)")
                if len(templates_in_use) > 5:
                    self.stdout.write(f"   ... and {len(templates_in_use) - 5} more")

                if track_for_update:
                    self.stdout.write(
                        self.style.WARNING(
                            "\n📝 Note: References will be updated to point to newly created templates.\n"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            "\n📝 Note: Existing MetadataColumn references will be preserved but set to NULL.\n"
                            "   The columns themselves will NOT be deleted - only the template link will be removed.\n"
                            "   New templates with matching names will be created and can be linked manually if needed.\n"
                            "   Use --update-references to automatically update column references to new templates.\n"
                        )
                    )

            # Delete the templates (existing columns will have template=NULL due to on_delete=SET_NULL)
            templates_to_delete.delete()
            self.stdout.write(self.style.WARNING(f"✓ Deleted {deleted_count} template(s) for schema '{schema_name}'"))
        else:
            self.stdout.write(f"No existing templates found for schema '{schema_name}'")

        return old_template_mapping

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
                with open(schema_file, encoding="utf-8") as f:
                    schema_data = yaml.safe_load(f)
                registry = SchemaRegistry(schema_dir=None)
                registry.add_schema(schema_name, schema_data)
                schema = registry.get_schema(schema_name)
                if schema:
                    self.stdout.write(f"Loaded schema from file: {schema_file}")
                    return schema
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error loading schema from file: {e}"))
                return None

        # Try schema directory if provided
        if schema_dir:
            try:
                registry = SchemaRegistry(schema_dir, use_versioned=False)
                schema = registry.get_schema(schema_name)
                if schema:
                    self.stdout.write(f"Loaded schema '{schema_name}' from directory: {schema_dir}")
                    return schema
            except Exception as e:
                self.stdout.write(f"Error loading from schema directory: {e}")

        self.stdout.write(self.style.ERROR(f"Could not load schema '{schema_name}' from any source"))
        return None

    def process_schema_columns(self, schema, admin_user, schema_name, schema_obj):
        """
        Process columns from schema and create templates.

        Returns:
            dict: Mapping of column_name -> template object for newly created templates
        """
        new_templates = {}

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

            allow_not_applicable = column.allow_not_applicable
            allow_not_available = column.allow_not_available

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
                not_available=allow_not_available,
                not_applicable=allow_not_applicable,
            )

            # Process validators for ontology configuration
            self.configure_ontology_options(template, column)

            template.save()
            new_templates[column_name] = template

            # Increment usage count on the schema
            if schema_obj:
                schema_obj.usage_count += 1
                schema_obj.save(update_fields=["usage_count"])

            self.stdout.write(f"Created template: {display_name} ({column_type})")

        return new_templates

    def update_column_references(self, schema_name, old_template_mapping, new_templates):
        """
        Update existing MetadataColumn references to point to newly created templates.

        Args:
            schema_name: Name of the schema
            old_template_mapping: Dict mapping (schema_name, column_name) -> old_template_id
            new_templates: Dict mapping column_name -> new_template object

        Returns:
            int: Number of column references updated
        """
        from ccv.models import MetadataColumn

        updated_count = 0

        self.stdout.write(f"\nUpdating column references for schema '{schema_name}'...")

        for column_name, new_template in new_templates.items():
            key = (schema_name, column_name)
            if key not in old_template_mapping:
                continue

            # Find columns that were linked to the old template (now NULL due to cascade)
            # We need to find columns that:
            # 1. Have template=NULL (was set by cascade delete)
            # 2. Have the same column name
            # This is a heuristic - we can only update columns where we're confident

            # Since template is now NULL, we look for columns with matching names
            # that belong to tables that might have used this schema
            null_template_columns = MetadataColumn.objects.filter(template__isnull=True, name=column_name)

            if null_template_columns.exists():
                # Update these columns to point to the new template
                update_count = null_template_columns.update(template=new_template)
                if update_count > 0:
                    updated_count += update_count
                    self.stdout.write(f"  ✓ Updated {update_count} column(s) named '{column_name}' to new template")

        if updated_count == 0:
            self.stdout.write("  No column references needed updating.")

        return updated_count

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
                template.possible_default_values = validator.params.get("examples", [])
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
