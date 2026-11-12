"""The cupcake-plugin-dev command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cupcake_plugin_dev import PROTOCOL_VERSION, __version__
from cupcake_plugin_dev.checks import PackageError
from cupcake_plugin_dev.docs import render_docs, update_readme
from cupcake_plugin_dev.packaging import build_package, plugin_problems, read_manifest
from cupcake_plugin_dev.scaffold import KINDS, ScaffoldError, create_plugin


def _new(args) -> int:
    try:
        target = create_plugin(
            args.name, args.kind, Path(args.directory), args.display_name, args.port, args.description
        )
    except ScaffoldError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Created {args.kind} plugin {args.name} in {target}")
    print(f"Next: cd {target} && python3 -m unittest discover -s tests")
    return 0


def _validate(args) -> int:
    problems = plugin_problems(Path(args.directory))
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("The plugin is valid")
    return 0


def _package(args) -> int:
    try:
        package = build_package(Path(args.directory), Path(args.output) if args.output else None)
    except PackageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {package}")
    return 0


def _docs(args) -> int:
    try:
        manifest = read_manifest(Path(args.directory))
    except PackageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if not args.write:
        print(render_docs(manifest), end="")
        return 0
    readme = Path(args.directory) / "README.md"
    print(f"{'Updated' if update_readme(readme, manifest) else 'No change to'} {readme}")
    return 0


def parser() -> argparse.ArgumentParser:
    """The command-line parser."""
    root = argparse.ArgumentParser(
        prog="cupcake-plugin-dev", description="Create, check, package and document CUPCAKE plugins"
    )
    root.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__} (plugin protocol {PROTOCOL_VERSION})"
    )
    commands = root.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", help="create a plugin from a template")
    new.add_argument("name", help="plugin name: lower-case letters, digits, '-' and '_'")
    new.add_argument(
        "--kind", choices=sorted(KINDS), default="service", help="template to start from (default service)"
    )
    new.add_argument("--directory", default=".", help="folder to create the plugin in (default .)")
    new.add_argument("--display-name", help="name shown in CUPCAKE")
    new.add_argument("--description", help="one-line description")
    new.add_argument("--port", type=int, help="local port the plugin asks for")
    new.set_defaults(handler=_new)

    for name, handler, text in (
        ("validate", _validate, "check the manifest and the files of a plugin"),
        ("package", _package, "build the plugin's .tar.gz and check it as CUPCAKE checks an upload"),
        ("docs", _docs, "print the reference generated from the manifest, or write it into README.md"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("directory", nargs="?", default=".", help="plugin folder (default .)")
        if name == "package":
            command.add_argument("--output", help="folder for the package (default <plugin>/dist)")
        if name == "docs":
            command.add_argument("--write", action="store_true", help="write the reference into README.md")
        command.set_defaults(handler=handler)
    return root


def main(argv: list[str] | None = None) -> int:
    """Run the command and return its exit status."""
    args = parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
