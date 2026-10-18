"""
Management command to load a complete external vocabulary into the local cache.
"""

from django.core.management.base import BaseCommand, CommandError

from choux import ChouxError

from ccv.external_vocabularies import sources, store_terms


class Command(BaseCommand):
    help = "Load every term of an external vocabulary, for example protocols_io_unit, into the local cache."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Key of the external vocabulary source")
        parser.add_argument(
            "--option",
            action="append",
            default=[],
            metavar="NAME=VALUE",
            help="Source specific option, for example protocol=cupcake-export-test-kqcbcvssp. Repeatable.",
        )

    def handle(self, *args, **options):
        source = sources.get(options["source"])
        if source is None:
            known = ", ".join(sorted(item.key for item in sources.all()))
            raise CommandError(f"Unknown source {options['source']!r}. Known sources: {known}")
        if not source.is_configured():
            raise CommandError(f"{source.key} is not configured on this instance")
        source_options = {}
        for option in options["option"]:
            name, separator, value = option.partition("=")
            if not separator or not name:
                raise CommandError(f"Options must look like NAME=VALUE, got {option!r}")
            source_options[name] = value
        try:
            terms = list(source.load_all(**source_options))
        except NotImplementedError as error:
            raise CommandError(str(error)) from error
        except (ValueError, ChouxError) as error:
            raise CommandError(f"Loading {source.key} failed: {error}") from error
        stored = store_terms(source, terms)
        self.stdout.write(self.style.SUCCESS(f"Stored {stored} {source.label} term(s)"))
