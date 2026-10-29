from django.core.management.base import BaseCommand

from ccc.plugin.model import Plugin


class Command(BaseCommand):
    """Remove a plugin's registration, used by the appliance plugin manager when uninstalling it."""

    help = "Remove the registration of a plugin"

    def add_arguments(self, parser):
        parser.add_argument("name", help="Plugin name")

    def handle(self, *args, **options):
        name = options["name"]
        deleted, _ = Plugin.objects.filter(name=name).delete()
        if deleted:
            self.stdout.write(f"Plugin '{name}' deregistered")
        else:
            self.stdout.write(f"Plugin '{name}' is not registered")
