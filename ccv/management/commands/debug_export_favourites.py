"""
Diagnostic command: shows exactly what the export sees when building favourite dropdowns.
Usage: poetry run python manage.py debug_export_favourites --user <username> --table <table_id>
"""

import re

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from ccv.models import FavouriteMetadataOption, MetadataTable


class Command(BaseCommand):
    help = "Diagnose why favourite options are missing from Excel export dropdowns"

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username to check")
        parser.add_argument("--table", required=True, type=int, help="MetadataTable ID")

    def handle(self, *args, **options):
        username = options["user"]
        table_id = options["table"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stderr.write(f"User '{username}' not found")
            return

        try:
            table = MetadataTable.objects.get(id=table_id)
        except MetadataTable.DoesNotExist:
            self.stderr.write(f"MetadataTable id={table_id} not found")
            return

        self.stdout.write(f"\n=== User: {user.username} (id={user.id}) ===")
        self.stdout.write(f"=== Table: {table.name} (id={table.id}) ===\n")

        columns = list(table.columns.all().select_related("template"))
        self.stdout.write(f"Columns ({len(columns)}):")
        for col in columns:
            tmpl = getattr(col, "template", None)
            self.stdout.write(
                f"  id={col.id} name={col.name!r} hidden={col.hidden} "
                f"not_available={col.not_available} not_applicable={col.not_applicable} "
                f"template={tmpl.id if tmpl else None}"
            )
            if tmpl:
                self.stdout.write(
                    f"    template.not_available={tmpl.not_available} "
                    f"template.not_applicable={tmpl.not_applicable} "
                    f"template.possible_default_values={tmpl.possible_default_values}"
                )

        def _inner_name(raw):
            raw = raw.lower()
            if "[" in raw and raw.endswith("]"):
                return raw.split("[", 1)[1][:-1]
            return raw

        inner_column_names = {_inner_name(col.name) for col in columns}
        all_name_variants = inner_column_names | {col.name.lower() for col in columns}

        self.stdout.write(f"\nInner names: {sorted(inner_column_names)}")
        self.stdout.write(f"All name variants: {sorted(all_name_variants)}")

        def _build_regex(names):
            return r"^(" + "|".join(re.escape(n) for n in names) + ")$"

        regex = _build_regex(all_name_variants)
        self.stdout.write(f"\nRegex: {regex}")

        self.stdout.write(f"\n--- All FavouriteMetadataOption for user {user.username} ---")
        all_favs = FavouriteMetadataOption.objects.filter(user=user)
        if not all_favs.exists():
            self.stdout.write("  (none)")
        for fav in all_favs:
            matched = re.match(regex, fav.name, re.IGNORECASE)
            self.stdout.write(
                f"  id={fav.id} name={fav.name!r} lab_group={fav.lab_group_id} "
                f"is_global={fav.is_global} value={fav.value!r} "
                f"regex_match={'YES' if matched else 'NO'}"
            )

        self.stdout.write("\n--- Personal favourites query (lab_group__isnull=True) ---")
        personal = FavouriteMetadataOption.objects.filter(user=user, lab_group__isnull=True, name__iregex=regex)
        if not personal.exists():
            self.stdout.write("  (none matched)")
        for fav in personal:
            self.stdout.write(f"  id={fav.id} name={fav.name!r} value={fav.value!r}")

        self.stdout.write("\n--- Global favourites ---")
        globals_ = FavouriteMetadataOption.objects.filter(is_global=True, name__iregex=regex)
        if not globals_.exists():
            self.stdout.write("  (none)")
        for fav in globals_:
            self.stdout.write(f"  id={fav.id} name={fav.name!r} value={fav.value!r}")

        self.stdout.write("")
