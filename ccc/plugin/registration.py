"""Registering a plugin with the backend and issuing its startup token."""

from __future__ import annotations

from ccc.plugin.model import Plugin


def register_plugin(name: str, base_url: str, version: str, manifest: dict | None = None) -> tuple[Plugin, str]:
    """
    Register the plugin, or update the one with the same name, and issue a new startup token.

    Returns:
        The plugin and its plain startup token; any earlier token stops working.
    """
    manifest = manifest or {"name": name, "displayName": name, "version": version}
    plugin, _ = Plugin.objects.update_or_create(
        name=name,
        defaults={
            "display_name": str(manifest.get("displayName") or name)[:200],
            "version": version,
            "description": str(manifest.get("description") or ""),
            "manifest_cache": manifest,
            "base_url": base_url,
            "is_active": True,
            "lifecycle_status": Plugin.LIFECYCLE_INSTALLING,
            "progress_message": "Installing",
            "connection_verified_at": None,
        },
    )
    plugin.token = ""
    plugin.save()
    return plugin, plugin._plain_token
