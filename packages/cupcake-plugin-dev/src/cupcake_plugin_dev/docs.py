"""The README section generated from a plugin's manifest."""

from __future__ import annotations

from pathlib import Path

START = "<!-- cupcake-plugin-dev:docs -->"
END = "<!-- /cupcake-plugin-dev:docs -->"
MANAGED_SETTINGS = ("PLUGIN_TOKEN", "CUPCAKE_BACKEND", "PLUGIN_BASE_URL", "PLUGIN_HOST", "PLUGIN_PORT")


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ") if value not in (None, "") else "—"


def render_docs(manifest: dict) -> str:
    """Markdown describing the plugin's pages, vocabularies and settings, from its manifest."""
    name = manifest["name"]
    lines = ["## Reference", "", f"Name `{name}`, version {manifest['version']}."]
    if manifest.get("port"):
        lines[-1] += f" Asks for local port {manifest['port']}."
    pages = manifest.get("pages", [])
    if pages:
        lines += ["", "### Pages", "", "| Page | Widgets |", "|---|---|"]
        for page in pages:
            widgets = ", ".join(
                f"{widget.get('title') or widget['id']} ({widget['type']})" for widget in page.get("widgets", [])
            )
            lines.append(f"| {_cell(page['title'])} (`{page['path']}`) | {_cell(widgets)} |")
    vocabularies = manifest.get("vocabularies", [])
    if vocabularies:
        lines += ["", "### Vocabularies", "", "| Ontology type | Label | Search |", "|---|---|---|"]
        for vocabulary in vocabularies:
            live = vocabulary.get("liveSearch", vocabulary.get("live_search")) is True
            lines.append(
                f"| `plugin.{name}.{vocabulary['key']}` | {_cell(vocabulary['label'])} "
                f"| {'Searched at the plugin' if live else 'Terms sent to CUPCAKE'} |"
            )
        lines += ["", "Users see these vocabularies once staff approve them on the Vocabularies page."]
    settings = manifest.get("settings", [])
    lines += ["", "### Settings", "", f"In `/etc/cupcake/plugins/{name}.env`:", ""]
    lines += ["| Setting | Default | Meaning |", "|---|---|---|"]
    for setting in settings:
        lines.append(f"| `{setting['name']}` | {_cell(setting.get('default'))} | {_cell(setting['description'])} |")
    lines.append(
        f"| {', '.join(f'`{key}`' for key in MANAGED_SETTINGS)} | | Written by CUPCAKE when it installs the plugin |"
    )
    return "\n".join(lines) + "\n"


def update_readme(readme: Path, manifest: dict) -> bool:
    """
    Replace the generated section of readme with the docs of the manifest, adding it at the end when it is missing.

    Returns:
        Whether the file changed.
    """
    readme = Path(readme)
    text = readme.read_text() if readme.exists() else f"# {manifest.get('displayName') or manifest['name']}\n"
    block = f"{START}\n{render_docs(manifest)}{END}"
    if START in text and END in text:
        before, rest = text.split(START, 1)
        updated = before + block + rest.split(END, 1)[1]
    else:
        updated = text.rstrip("\n") + "\n\n" + block + "\n"
    if updated == text:
        return False
    readme.write_text(updated)
    return True
