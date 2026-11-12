"""cupcake-plugin-dev: manifest checks, package checks, templates, packaging, docs and the command line."""

import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from cupcake_plugin_dev.checks import PackageError, check_package
from cupcake_plugin_dev.cli import main
from cupcake_plugin_dev.docs import END, START, render_docs, update_readme
from cupcake_plugin_dev.manifest import manifest_problems
from cupcake_plugin_dev.packaging import build_package, plugin_problems
from cupcake_plugin_dev.scaffold import ScaffoldError, create_plugin

MANIFEST = {
    "name": "device-temperature",
    "displayName": "Device temperature",
    "version": "1.0.0",
    "port": 8102,
    "nav": [{"label": "Device temperature", "icon": "bi bi-thermometer-half", "path": "temperature"}],
    "pages": [
        {
            "path": "temperature",
            "title": "Device temperature",
            "widgets": [
                {"id": "current", "type": "card", "title": "Now", "endpoint": "/api/current"},
                {"id": "history", "type": "chart", "endpoint": "/api/history", "refreshInterval": 5000},
                {"id": "threshold", "type": "form", "endpoint": "/api/threshold", "fields": ["celsius"]},
            ],
        }
    ],
    "vocabularies": [{"key": "sensors", "label": "Sensors", "liveSearch": True}],
    "settings": [{"name": "ALERT_CELSIUS", "default": "75", "description": "Temperature that raises an alert"}],
}


def changed(**updates):
    """MANIFEST with top-level fields replaced."""
    return {**json.loads(json.dumps(MANIFEST)), **updates}


def tarball(path, files, links=()):
    """Write a gzipped tar holding the given files and links."""
    with tarfile.open(path, "w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        for name, target in links:
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            archive.addfile(info)
    return path


class TemporaryFolder(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)


class ManifestTests(unittest.TestCase):
    def test_a_full_manifest_is_valid(self):
        self.assertEqual(manifest_problems(MANIFEST), [])

    def test_name_and_version_are_required_and_checked(self):
        self.assertTrue(any("name" in problem for problem in manifest_problems(changed(name="Device Temperature"))))
        self.assertTrue(any("version" in problem for problem in manifest_problems(changed(version="  "))))
        self.assertIn("manifest: 'version' is a required property", manifest_problems({"name": "x"}))

    def test_the_port_must_be_unprivileged(self):
        self.assertTrue(any(problem.startswith("port:") for problem in manifest_problems(changed(port=80))))

    def test_typos_in_widgets_are_caught(self):
        manifest = changed()
        manifest["pages"][0]["widgets"][0]["endpiont"] = "/api/x"
        self.assertTrue(any("endpiont" in problem for problem in manifest_problems(manifest)))

    def test_unknown_widget_types_are_refused(self):
        manifest = changed()
        manifest["pages"][0]["widgets"][0]["type"] = "iframe"
        self.assertTrue(any("pages[0].widgets[0].type" in problem for problem in manifest_problems(manifest)))

    def test_nav_must_point_at_a_page(self):
        manifest = changed(nav=[{"label": "Missing", "path": "missing"}])
        self.assertEqual(manifest_problems(manifest), ["nav[0].path: no page has the path 'missing'"])

    def test_widgets_need_unique_ids_and_endpoints_and_forms_need_fields(self):
        manifest = changed()
        widgets = manifest["pages"][0]["widgets"]
        widgets[1]["id"] = "current"
        del widgets[1]["endpoint"]
        del widgets[2]["fields"]
        self.assertEqual(
            manifest_problems(manifest),
            [
                "pages[0].widgets[1].id: 'current' is used twice on this page",
                "pages[0].widgets[1]: a chart widget needs an endpoint",
                "pages[0].widgets[2]: a form widget needs fields",
            ],
        )

    def test_vocabulary_keys_and_setting_names_are_unique_and_checked(self):
        manifest = changed(
            vocabularies=[{"key": "sensors", "label": "A"}, {"key": "sensors", "label": "B"}],
            settings=[{"name": "A", "description": "x"}, {"name": "A", "description": "y"}],
        )
        self.assertEqual(
            manifest_problems(manifest),
            ["vocabularies[1].key: 'sensors' is declared twice", "settings[1].name: 'A' is declared twice"],
        )
        self.assertTrue(manifest_problems(changed(vocabularies=[{"key": "Bad Key", "label": "x"}])))

    def test_a_manifest_must_be_an_object(self):
        self.assertEqual(manifest_problems([]), ["manifest: must be a JSON object"])


class PackageCheckTests(TemporaryFolder):
    def package(self, files=None, links=(), manifest=MANIFEST):
        contents = {"run.sh": b"#!/bin/sh\n", **({"manifest.json": json.dumps(manifest).encode()} if manifest else {})}
        contents.update(files or {})
        return tarball(self.root / "plugin.tar.gz", contents, links)

    def test_a_valid_package_gives_its_manifest(self):
        self.assertEqual(check_package(self.package({"lib/util.py": b"x = 1\n"}))["name"], "device-temperature")

    def test_files_other_than_gzipped_tars_are_refused(self):
        path = self.root / "plain.tar.gz"
        path.write_text("plain text")
        with self.assertRaisesRegex(PackageError, "not a .tar.gz"):
            check_package(path)

    def test_links_and_paths_outside_the_plugin_are_refused(self):
        with self.assertRaisesRegex(PackageError, "link or special file"):
            check_package(self.package(links=[("secret", "/etc/shadow")]))
        with self.assertRaisesRegex(PackageError, "outside the plugin"):
            check_package(self.package({"../escape.sh": b"x"}))

    def test_run_sh_and_the_manifest_are_required(self):
        with self.assertRaisesRegex(PackageError, "manifest.json at the top level"):
            check_package(self.package(manifest=None))

    def test_an_invalid_manifest_is_refused_with_its_problems(self):
        with self.assertRaisesRegex(PackageError, "port"):
            check_package(self.package(manifest=changed(port=80)))

    def test_packages_too_large_unpacked_are_refused(self):
        with self.assertRaisesRegex(PackageError, "too large unpacked"):
            check_package(self.package({"data.bin": b"x" * 200}), max_unpacked_bytes=100)


class ScaffoldTests(TemporaryFolder):
    def run_tests(self, plugin_dir):
        return subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            cwd=plugin_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )

    def test_every_template_creates_a_plugin_whose_tests_pass(self):
        for kind in ("service", "vocabulary"):
            with self.subTest(kind=kind):
                plugin_dir = create_plugin(f"demo-{kind}", kind, self.root)
                self.assertEqual(plugin_problems(plugin_dir), [])
                result = self.run_tests(plugin_dir)
                self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_the_plugin_carries_its_name_title_and_port(self):
        plugin_dir = create_plugin("lab-clock", "service", self.root, 'Lab "clock"', 8155, "Shows the time")
        manifest = json.loads((plugin_dir / "manifest.json").read_text())
        self.assertEqual(
            (manifest["name"], manifest["displayName"], manifest["port"], manifest["description"]),
            ("lab-clock", 'Lab "clock"', 8155, "Shows the time"),
        )
        self.assertIn('"8155"', (plugin_dir / "plugin.py").read_text())
        self.assertTrue((plugin_dir / ".gitignore").exists() and (plugin_dir / "README.md").exists())
        self.assertTrue((plugin_dir / "run.sh").stat().st_mode & 0o111)

    def test_invalid_requests_are_refused(self):
        for name, kind, port in (("Bad Name", "service", None), ("ok", "unknown", None), ("ok", "service", 80)):
            with self.subTest(name=name, kind=kind), self.assertRaises(ScaffoldError):
                create_plugin(name, kind, self.root, port=port)
        create_plugin("taken", "service", self.root)
        with self.assertRaisesRegex(ScaffoldError, "already exists"):
            create_plugin("taken", "service", self.root)


class PackagingTests(TemporaryFolder):
    def test_the_package_holds_the_plugin_without_development_files(self):
        plugin_dir = create_plugin("demo", "vocabulary", self.root)
        (plugin_dir / "__pycache__").mkdir()
        (plugin_dir / "__pycache__" / "plugin.cpython-312.pyc").write_bytes(b"x")
        package = build_package(plugin_dir)
        self.assertEqual(package.name, "demo-0.1.0.tar.gz")
        with tarfile.open(package) as archive:
            members = {member.name: member for member in archive.getmembers()}
        self.assertEqual(
            sorted(members), ["README.md", "manifest.json", "plugin.py", "run.sh", "terms", "terms/strains.tsv"]
        )
        self.assertEqual(members["run.sh"].mode, 0o755)
        self.assertEqual((members["plugin.py"].uid, members["plugin.py"].mode), (0, 0o644))

    def test_links_and_invalid_manifests_stop_the_package(self):
        plugin_dir = create_plugin("demo", "service", self.root)
        (plugin_dir / "secret").symlink_to("/etc/hostname")
        manifest = json.loads((plugin_dir / "manifest.json").read_text())
        manifest["port"] = 80
        (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
        problems = plugin_problems(plugin_dir)
        self.assertTrue(any("is a link" in problem for problem in problems))
        self.assertTrue(any(problem.startswith("port:") for problem in problems))
        with self.assertRaises(PackageError):
            build_package(plugin_dir)


class DocsTests(TemporaryFolder):
    def test_the_reference_lists_pages_vocabularies_and_settings(self):
        docs = render_docs(MANIFEST)
        self.assertIn("| Device temperature (`temperature`) | Now (card), history (chart), threshold (form) |", docs)
        self.assertIn("`plugin.device-temperature.sensors`", docs)
        self.assertIn("Searched at the plugin", docs)
        self.assertIn("| `ALERT_CELSIUS` | 75 | Temperature that raises an alert |", docs)

    def test_the_readme_section_is_replaced_and_added_once(self):
        readme = self.root / "README.md"
        readme.write_text(f"# Title\n\nIntro\n\n{START}\nstale section\n{END}\n\nAfter\n")
        self.assertTrue(update_readme(readme, MANIFEST))
        text = readme.read_text()
        self.assertTrue(text.startswith("# Title\n\nIntro\n\n") and text.endswith("\n\nAfter\n"))
        self.assertNotIn("stale section", text)
        self.assertFalse(update_readme(readme, MANIFEST))
        plain = self.root / "PLAIN.md"
        plain.write_text("# Plain\n")
        update_readme(plain, MANIFEST)
        self.assertEqual(plain.read_text().count(START), 1)


class CommandLineTests(TemporaryFolder):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = main(list(argv))
        return status, out.getvalue(), err.getvalue()

    def test_new_validate_docs_and_package(self):
        self.assertEqual(self.run_main("new", "demo", "--directory", str(self.root))[0], 0)
        plugin_dir = str(self.root / "demo")
        self.assertEqual(self.run_main("validate", plugin_dir)[:2], (0, "The plugin is valid\n"))
        self.assertIn("## Reference", self.run_main("docs", plugin_dir)[1])
        self.assertEqual(self.run_main("docs", "--write", plugin_dir)[0], 0)
        status, out, _ = self.run_main("package", plugin_dir)
        self.assertEqual(status, 0)
        self.assertTrue(out.strip().endswith("demo-0.1.0.tar.gz"))

    def test_problems_are_reported_with_a_failing_status(self):
        (self.root / "manifest.json").write_text(json.dumps(changed(port=80)))
        status, _, err = self.run_main("validate", str(self.root))
        self.assertEqual(status, 1)
        self.assertIn("error: port:", err)
        self.assertIn("error: run.sh is missing", err)


if __name__ == "__main__":
    unittest.main()
