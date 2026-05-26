"""
Creates the CI admin user used by the plugin integration tests.
Run once after migrate, before starting the plugin server.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cupcake_vanilla.settings")
django.setup()

from django.contrib.auth.models import User  # noqa: E402

username = os.environ.get("ADMIN_USERNAME", "admin")
password = os.environ.get("ADMIN_PASSWORD", "password")

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, f"{username}@ci.local", password)
    print(f"[setup] created superuser '{username}'")
else:
    print(f"[setup] superuser '{username}' already exists")
