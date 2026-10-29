from django.core.management.base import BaseCommand

from ccc.plugin.model import Plugin


class Command(BaseCommand):
    """Register a plugin, or update the one registered under the same name, and print a new startup token.

    Used by the appliance plugin manager, which runs as root on the backend host and so needs no
    admin credentials. Only the token is written to stdout, for the caller to store in the
    plugin's env file; any earlier token of the plugin stops working.
    """

    help = "Register or update a plugin and print a new startup token"

    def add_arguments(self, parser):
        parser.add_argument("name", help="Plugin name, unique per appliance")
        parser.add_argument("base_url", help="URL the browser uses to reach the plugin server")
        parser.add_argument("--plugin-version", default="1.0.0", help="Version of the plugin being registered")

    def handle(self, *args, **options):
        name = options["name"]
        base_url = options["base_url"]
        version = options["plugin_version"]

        plugin, _ = Plugin.objects.update_or_create(
            name=name,
            defaults={
                "display_name": name,
                "version": version,
                "manifest_cache": {"name": name, "displayName": name, "version": version, "baseUrl": base_url},
                "base_url": base_url,
                "is_active": True,
                "lifecycle_status": Plugin.LIFECYCLE_INSTALLING,
                "progress_message": "Installing",
            },
        )
        plugin.token = ""
        plugin.save()
        self.stdout.write(plugin._plain_token)
