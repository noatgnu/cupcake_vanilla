"""
Keeps the OpenAPI schema complete: every custom viewset action must describe its request and
response with @extend_schema, so clients and generated TypeScript types match what the action
really accepts and returns.

Actions still to be documented are listed in openapi_undocumented_actions.txt. The list may only
shrink: a new undocumented action fails, and so does a listed action that has been documented
since, until its line is removed. Actions of modules that are not enabled are not checked.
"""

from pathlib import Path

from django.test import SimpleTestCase
from django.urls import URLPattern, URLResolver, get_resolver

from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator

UNDOCUMENTED_FILE = Path(__file__).with_name("openapi_undocumented_actions.txt")


def _viewsets(patterns=None):
    """Return every viewset class reachable from the project's URL configuration."""
    found = set()
    for pattern in patterns if patterns is not None else get_resolver().url_patterns:
        if isinstance(pattern, URLResolver):
            found |= _viewsets(pattern.url_patterns)
        elif isinstance(pattern, URLPattern):
            view_class = getattr(pattern.callback, "cls", None)
            if view_class is not None and hasattr(view_class, "get_extra_actions"):
                found.add(view_class)
    return found


def custom_actions():
    """Map "module.ViewSet.action" to whether the action carries an @extend_schema annotation."""
    actions = {}
    for viewset in _viewsets():
        for action in viewset.get_extra_actions():
            name = f"{viewset.__module__}.{viewset.__name__}.{action.__name__}"
            actions[name] = "schema" in getattr(action, "kwargs", {})
    return actions


def undocumented_allowance():
    """Return the actions listed in openapi_undocumented_actions.txt."""
    lines = UNDOCUMENTED_FILE.read_text().splitlines() if UNDOCUMENTED_FILE.exists() else []
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


class CustomActionSchemaTests(SimpleTestCase):
    def test_every_custom_action_is_documented(self):
        allowed = undocumented_allowance()
        missing = sorted(
            name for name, documented in custom_actions().items() if not documented and name not in allowed
        )
        self.assertEqual(
            missing,
            [],
            "Describe these actions with @extend_schema(request=..., responses=...):\n" + "\n".join(missing),
        )

    def test_documented_actions_are_removed_from_the_allowance(self):
        actions = custom_actions()
        stale = sorted(name for name in undocumented_allowance() if actions.get(name) is True)
        self.assertEqual(
            stale,
            [],
            "These actions are documented now; remove them from " f"{UNDOCUMENTED_FILE.name}:\n" + "\n".join(stale),
        )

    def test_schema_generates(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        self.assertIn("/api/v1/auth/token/", schema["paths"])

    def test_schema_generates_without_warnings_or_errors(self):
        GENERATOR_STATS.reset()
        with GENERATOR_STATS.silence():
            SchemaGenerator().get_schema(request=None, public=True)
        problems = sorted(GENERATOR_STATS._warn_cache) + sorted(GENERATOR_STATS._error_cache)
        self.assertEqual(problems, [], "Fix these OpenAPI schema warnings and errors:\n" + "\n".join(problems))
