from django.core.management.base import BaseCommand

from ccc.plugin.model import Plugin


class Command(BaseCommand):
    """Regenerate startup tokens for all active plugins.

    Use this after rotating SECRET_KEY.  All existing plugin token hashes
    become invalid when the key changes; this command issues new tokens so
    each plugin env file can be updated and the service restarted.

    Output format (one line per plugin):
        <name>  <new-plain-token>

    Redirect to a file, update /etc/cupcake/plugins/<name>.env for each
    plugin, then restart the services.
    """

    help = "Regenerate startup tokens for all active plugins (use after SECRET_KEY rotation)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Include inactive plugins (default: active only)",
        )

    def handle(self, *args, **options):
        qs = Plugin.objects.all() if options["all"] else Plugin.objects.filter(is_active=True)
        plugins = list(qs.order_by("name"))

        if not plugins:
            self.stdout.write("No plugins found.")
            return

        self.stderr.write(
            self.style.WARNING(
                f"Rotating tokens for {len(plugins)} plugin(s). "
                "Update each /etc/cupcake/plugins/<name>.env and restart the service."
            )
        )

        for plugin in plugins:
            plugin.token = ""
            plugin.save(update_fields=["token", "updated_at"])
            self.stdout.write(f"{plugin.name}\t{plugin._plain_token}")
