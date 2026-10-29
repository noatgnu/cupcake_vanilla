"""
Tests for the register_plugin and deregister_plugin management commands used by the appliance
plugin manager.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from ccc.plugin.model import Plugin


def run(*args):
    """Run a management command and return its stripped stdout."""
    out = StringIO()
    call_command(*args, stdout=out)
    return out.getvalue().strip()


class RegisterPluginCommandTests(TestCase):
    def test_new_plugin_gets_a_working_token(self):
        token = run("register_plugin", "demo", "http://cupcake.local:8001", "--plugin-version", "2.1.0")

        plugin = Plugin.objects.get(name="demo")
        self.assertEqual(len(token), 64)
        self.assertEqual(plugin.token, Plugin.hash_token(token))
        self.assertEqual(plugin.version, "2.1.0")
        self.assertEqual(plugin.base_url, "http://cupcake.local:8001")
        self.assertEqual(plugin.manifest_cache["baseUrl"], "http://cupcake.local:8001")
        self.assertEqual(plugin.lifecycle_status, Plugin.LIFECYCLE_INSTALLING)
        self.assertTrue(plugin.is_active)

    def test_registering_again_updates_the_plugin_and_replaces_its_token(self):
        first = run("register_plugin", "demo", "http://cupcake.local:8001")
        second = run("register_plugin", "demo", "http://cupcake.local:8002", "--plugin-version", "1.1.0")

        self.assertEqual(Plugin.objects.filter(name="demo").count(), 1)
        plugin = Plugin.objects.get(name="demo")
        self.assertNotEqual(first, second)
        self.assertEqual(plugin.token, Plugin.hash_token(second))
        self.assertEqual(plugin.base_url, "http://cupcake.local:8002")
        self.assertEqual(plugin.version, "1.1.0")


class DeregisterPluginCommandTests(TestCase):
    def test_removes_the_plugin(self):
        run("register_plugin", "demo", "http://cupcake.local:8001")

        output = run("deregister_plugin", "demo")

        self.assertIn("deregistered", output)
        self.assertFalse(Plugin.objects.filter(name="demo").exists())

    def test_unknown_plugin_is_reported_not_an_error(self):
        self.assertIn("is not registered", run("deregister_plugin", "missing"))
