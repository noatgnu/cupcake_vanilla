"""
Test settings for Cupcake Vanilla.

Inherits from settings_wails (SQLite) with all optional apps enabled
so the full migration graph is available during test runs.
"""

import os

os.environ["ENABLE_CUPCAKE_MACARON"] = "True"
os.environ["ENABLE_CUPCAKE_MINT_CHOCOLATE"] = "True"
os.environ["ENABLE_CUPCAKE_SALTED_CARAMEL"] = "True"
os.environ["ENABLE_CUPCAKE_RED_VELVET"] = "True"

from .settings_wails import *  # noqa: F401, F403, E402

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
