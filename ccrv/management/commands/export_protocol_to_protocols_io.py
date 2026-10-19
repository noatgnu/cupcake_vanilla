"""
Management command to export a Cupcake protocol into an existing protocols.io protocol.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from choux import ChouxError, ProtocolsIO

from ccrv.models import ProtocolModel
from ccrv.protocols_io import export_protocol


class Command(BaseCommand):
    help = "Export a Cupcake protocol into an existing protocols.io protocol, replacing its content."

    def add_arguments(self, parser):
        parser.add_argument("protocol_id", type=int, help="Id of the Cupcake protocol")
        parser.add_argument("--target", required=True, help="Id, URI or GUID of the protocols.io protocol")
        parser.add_argument("--scaling-factor", type=float, default=1.0, help="Factor for scalable reagents")

    def handle(self, *args, **options):
        if not settings.PROTOCOLS_IO_ACCESS_TOKEN:
            raise CommandError("PROTOCOLS_IO_ACCESS_TOKEN is not set")
        try:
            protocol = ProtocolModel.objects.get(pk=options["protocol_id"])
        except ProtocolModel.DoesNotExist as error:
            raise CommandError(f"Protocol {options['protocol_id']} does not exist") from error
        with ProtocolsIO(settings.PROTOCOLS_IO_ACCESS_TOKEN) as client:
            try:
                result = export_protocol(protocol, client, options["target"], scaling_factor=options["scaling_factor"])
            except ChouxError as error:
                raise CommandError(f"Export failed: {error}") from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {result.steps_saved} step(s) to {result.protocol_url or result.protocol_uri}; "
                f"deleted {len(result.steps_deleted)}, uploaded {result.images_uploaded} image(s)"
            )
        )
        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(warning))
