"""Tests for exporting Cupcake protocols to protocols.io."""

import base64
import json
import struct
import uuid
import zlib
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from choux import DraftValidationError, ProtocolsIO, UploadedFile

from ccm.models import Reagent
from ccrv.models import (
    ProtocolModel,
    ProtocolReagent,
    ProtocolSection,
    ProtocolsIOExport,
    ProtocolStep,
    Session,
    StepReagent,
    StepVariation,
)
from ccrv.protocols_io import ExportResult, export_protocol, export_step_guid, ordered_steps
from ccrv.protocols_io.exporter import materials_text, plain_text

TARGET_GUID = "B5A1B28296954BDF8F34C4C693D95643"
UNITS = [
    {"id": 1, "type_id": 3, "name": "µL", "aliases": ["uL", "ul"]},
    {"id": 10, "type_id": 24, "name": "°C", "aliases": ["C"]},
]


def png_data_url(width, height):
    """Return a PNG of the given size as a data URL."""

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = (b"\x00" + b"\x10\x20\x30" * width) * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    content = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(content).decode()


class FakeProtocolsIO:
    """In-memory protocols.io that answers the requests the exporter sends and records them."""

    def __init__(self, existing_steps=None):
        """Start with an empty target protocol, or the given steps."""
        self.steps = {step["guid"]: dict(step) for step in existing_steps or []}
        self.order = [step["guid"] for step in existing_steps or []]
        self.calls = []
        self.fields = {}
        self.actions = []

    def request(self, method, path, *, params=None, json=None, data=None):
        """Answer one API request."""
        self.calls.append((method, path))
        if method == "GET" and path == "/v4/protocols/cupcake-export-test":
            return {
                "payload": {
                    "id": 340067,
                    "guid": TARGET_GUID,
                    "uri": "cupcake-export-test",
                    "url": "https://p/x",
                    "units": UNITS,
                }
            }
        if method == "GET" and path == "/v4/protocols/340067":
            uri = "renamed-export" if "title" in self.fields else "cupcake-export-test"
            return {"payload": {"id": 340067, "guid": TARGET_GUID, "uri": uri, "url": f"https://p/{uri}"}}
        if method == "GET" and path == "/v4/protocols/cupcake-export-test/steps":
            return {"payload": [self.steps[guid] for guid in self.order]}
        if method == "DELETE" and path == "/v4/protocols/cupcake-export-test/steps":
            for guid in json["steps"]:
                self.steps.pop(guid)
                self.order.remove(guid)
            return {"status_code": 0}
        if method == "POST" and path == "/v4/protocols/cupcake-export-test/steps":
            for step in json["steps"]:
                if step["guid"] not in self.steps:
                    self.order.append(step["guid"])
                self.steps[step["guid"]] = {**step, "duration": 0, "section_duration": 0}
            return {"status_code": 0}
        if method == "PUT" and path == "/v4/protocols/cupcake-export-test":
            self.fields.update(json)
            return {"status_code": 0}
        if method == "PUT" and path == f"/v3/protocols/{TARGET_GUID}":
            self.actions.extend(json["actions"])
            return {"status_code": 0, "actions": []}
        raise AssertionError(f"unexpected request {method} {path}")


class ExportTestCase(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("export-owner", password="x")
        self.protocol = ProtocolModel.objects.create(
            protocol_title="Cell lysis", protocol_description="Lyse cells.\nKeep cold.", owner=self.owner
        )
        self.prep = ProtocolSection.objects.create(protocol=self.protocol, section_description="Preparation", order=0)
        self.lysis = ProtocolSection.objects.create(protocol=self.protocol, section_description="Lysis", order=1)
        self.ripa = Reagent.objects.create(name="RIPA buffer", unit="uL")
        self.intro = ProtocolStep.objects.create(protocol=self.protocol, step_description="<p>Read first.</p>", order=0)
        self.wash = ProtocolStep.objects.create(
            protocol=self.protocol,
            step_section=self.prep,
            step_description="<p>Wash plates.</p>",
            order=0,
            step_duration=300,
        )
        self.lyse = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.lysis, step_description="placeholder", order=0, step_duration=600
        )
        self.lyse_reagent = StepReagent.objects.create(step=self.lyse, reagent=self.ripa, quantity=200)
        self.lyse.step_description = f"<p>Add %{self.lyse_reagent.id}.quantity% %{self.lyse_reagent.id}.unit%.</p>"
        self.lyse.save()
        self.fake = FakeProtocolsIO()
        self.client = ProtocolsIO("token")

    def tearDown(self):
        self.client.close()

    def export(self, **options):
        with patch.object(ProtocolsIO, "request", side_effect=self.fake.request):
            return export_protocol(self.protocol, self.client, "cupcake-export-test", **options)


class ExportProtocolTest(ExportTestCase):
    def test_steps_are_written_in_order_with_sections_and_stable_guids(self):
        """Steps are written in order with sections and stable guids."""
        result = self.export()
        self.assertEqual(result.steps_saved, 2)
        expected = [export_step_guid(TARGET_GUID, step.pk) for step in (self.wash, self.lyse)]
        self.assertEqual(self.fake.order, expected)
        saved = [self.fake.steps[guid] for guid in expected]
        self.assertEqual([step["section"] for step in saved], ["Preparation", "Lysis"])
        self.assertEqual([step["previous_guid"] for step in saved], [None, expected[0]])
        self.assertEqual(json.loads(saved[0]["step"])["blocks"][0]["text"], "Wash plates.")

    def test_variations_are_left_out_of_the_protocol(self):
        """Variations are left out of the protocol."""
        StepVariation.objects.create(step=self.lyse, variation_description="Unused alternative", variation_duration=900)
        session = Session.objects.create(name="Run", owner=self.owner, unique_id=uuid.uuid4())
        StepVariation.objects.create(
            step=self.lyse, session=session, variation_description="Session only", variation_duration=1
        )
        self.export()
        saved = self.fake.steps[export_step_guid(TARGET_GUID, self.lyse.pk)]["step"]
        self.assertNotIn("Unused alternative", saved)
        self.assertNotIn("Session only", saved)

    def test_variations_replace_the_text_and_time_of_their_steps(self):
        """Variations replace the text and time of their steps."""
        session = Session.objects.create(name="Run", owner=self.owner, unique_id=uuid.uuid4())
        variation = StepVariation.objects.create(
            step=self.lyse,
            session=session,
            variation_description=f"<p>Add %{self.lyse_reagent.id}.quantity% %{self.lyse_reagent.id}.unit% twice.</p>",
            variation_duration=1200,
        )
        self.export(variations={self.lyse.pk: variation}, title="Cell lysis - Run", description="As performed")
        saved = json.loads(self.fake.steps[export_step_guid(TARGET_GUID, self.lyse.pk)]["step"])
        self.assertEqual(saved["blocks"][0]["text"], "Add   twice.")
        self.assertEqual(next(iter(saved["entityMap"].values()))["data"]["amount"], "200")
        durations = {
            action["up"][0]["path"][1]: action["up"][0]["value"]
            for action in self.fake.actions
            if action["marker"] == "step:set-duration"
        }
        self.assertEqual(durations[export_step_guid(TARGET_GUID, self.lyse.pk)], 1200)
        self.assertEqual(durations[export_step_guid(TARGET_GUID, self.wash.pk)], 300)
        self.assertEqual(
            (self.fake.fields["title"], self.fake.fields["description"]), ("Cell lysis - Run", "As performed")
        )

    def test_result_names_the_target_and_the_exported_steps_in_order(self):
        """Result names the target and the exported steps in order."""
        result = self.export()
        self.assertEqual((result.protocol_guid, result.protocol_id), (TARGET_GUID, 340067))
        self.assertEqual(result.step_ids, [self.wash.pk, self.lyse.pk])

    def test_result_has_the_address_after_the_title_is_saved(self):
        """Result has the address the protocol has after its title is saved."""
        result = self.export()
        self.assertEqual((result.protocol_uri, result.protocol_url), ("renamed-export", "https://p/renamed-export"))

    def test_steps_outside_sections_are_skipped_with_a_warning(self):
        """Steps outside sections are skipped with a warning."""
        result = self.export()
        self.assertNotIn(export_step_guid(TARGET_GUID, self.intro.pk), self.fake.steps)
        self.assertIn("1 step(s) outside any section were not exported", result.warnings)

    def test_reagent_templates_become_amounts(self):
        """Reagent templates become amounts."""
        self.export()
        content = json.loads(self.fake.steps[export_step_guid(TARGET_GUID, self.lyse.pk)]["step"])
        [entity] = content["entityMap"].values()
        self.assertEqual((entity["type"], entity["data"]["amount"], entity["data"]["unit"]), ("amount", "200", 1))
        self.assertEqual(entity["data"]["label"], "RIPA buffer")

    def test_protocol_fields_are_plain_text(self):
        """Protocol fields are plain text."""
        ProtocolReagent.objects.create(
            protocol=self.protocol, reagent=Reagent.objects.create(name="PBS", unit="mL"), quantity=50
        )
        self.export()
        self.assertEqual(
            self.fake.fields,
            {
                "title": "Cell lysis",
                "description": "Lyse cells.\nKeep cold.",
                "materials_text": "PBS - 50 mL\nRIPA buffer",
            },
        )

    def test_step_times_and_section_totals_are_set(self):
        """Step times and section totals are set."""
        self.export()
        changes = {
            (action["marker"], action["up"][0]["path"][1], action["up"][0]["value"]) for action in self.fake.actions
        }
        wash_guid = export_step_guid(TARGET_GUID, self.wash.pk)
        lyse_guid = export_step_guid(TARGET_GUID, self.lyse.pk)
        self.assertEqual(
            changes,
            {
                ("step:set-duration", wash_guid, 300),
                ("step:set-duration", lyse_guid, 600),
                ("step:set-section-duration", wash_guid, 300),
                ("step:set-section-duration", lyse_guid, 600),
            },
        )

    def test_reexport_reuses_guids_and_deletes_steps_not_in_cupcake(self):
        """Reexport reuses guids and deletes steps not in cupcake."""
        self.export()
        stray = {"guid": "F" * 32, "previous_guid": None, "step": "{}", "section": None, "duration": 0}
        self.fake.steps[stray["guid"]] = stray
        self.fake.order.insert(0, stray["guid"])
        wash_guid = export_step_guid(TARGET_GUID, self.wash.pk)
        self.wash.delete()
        result = self.export()
        self.assertEqual(sorted(result.steps_deleted), sorted(["F" * 32, wash_guid]))
        self.assertEqual(self.fake.order, [export_step_guid(TARGET_GUID, self.lyse.pk)])

    def test_invalid_content_changes_nothing_on_protocols_io(self):
        """Invalid content changes nothing on protocols io."""
        broken = {"blocks": [], "entityMap": {}}
        with patch("ccrv.protocols_io.exporter.step_to_draft", return_value=(broken, [])):
            with self.assertRaises(DraftValidationError):
                self.export()
        self.assertEqual({method for method, _ in self.fake.calls}, {"GET"})

    def test_unresolved_templates_are_reported(self):
        """Unresolved templates are reported."""
        self.wash.step_description = "<p>Add %999.quantity%</p>"
        self.wash.save()
        result = self.export()
        self.assertEqual(result.unresolved_templates, ["%999.quantity%"])
        self.assertIn("Reagent template %999.quantity% names a reagent that is not on its step", result.warnings)


class StepImageExportTest(ExportTestCase):
    def uploaded(self, name, content, **sizes):
        """Return a fake upload for a file."""
        return UploadedFile(
            id=7,
            key=f"files/{name}",
            source=f"https://content.protocols.io/files/{name}",
            raw_source=f"https://protocols-files.s3.amazonaws.com/files/{name}",
            original_name=name,
            mime_type="image/png",
            size=len(content),
            file_type=31,
            thumb_url="",
            width=sizes.get("width"),
            height=sizes.get("height"),
        )

    def test_embedded_images_are_uploaded_once_with_their_size(self):
        """Embedded images are uploaded once with their size."""
        data_url = png_data_url(40, 30)
        self.wash.step_description = f'<p>Gel</p><img src="{data_url}"><p>Again</p><img src="{data_url}">'
        self.wash.save()
        with patch.object(ProtocolsIO, "upload_file", side_effect=self.uploaded) as upload:
            result = self.export()
        upload.assert_called_once()
        self.assertEqual(upload.call_args.kwargs, {"width": 40, "height": 30})
        self.assertEqual(result.images_uploaded, 1)
        content = json.loads(self.fake.steps[export_step_guid(TARGET_GUID, self.wash.pk)]["step"])
        self.assertEqual(
            [block["type"] for block in content["blocks"]], ["unstyled", "atomic", "unstyled", "atomic", "unstyled"]
        )

    def test_images_outside_cupcake_are_left_out_with_a_warning(self):
        """Images outside cupcake are left out with a warning."""
        self.wash.step_description = '<p>Gel</p><img src="https://elsewhere.example/gel.png">'
        self.wash.save()
        with patch.object(ProtocolsIO, "upload_file") as upload:
            result = self.export()
        upload.assert_not_called()
        self.assertIn(
            "Image left out because it is not stored in Cupcake: https://elsewhere.example/gel.png", result.warnings
        )


class ExportHelpersTest(ExportTestCase):
    def test_ordered_steps_follow_sections_and_leave_out_unsectioned_steps(self):
        """Ordered steps follow sections and leave out unsectioned steps."""
        self.assertEqual(ordered_steps(self.protocol), [self.wash, self.lyse])

    def test_materials_list_reagents_once(self):
        """Materials list reagents once."""
        StepReagent.objects.create(step=self.wash, reagent=self.ripa, quantity=5)
        self.assertEqual(materials_text(self.protocol), "RIPA buffer")

    def test_plain_text_reduces_html(self):
        """Plain text reduces html."""
        self.assertEqual(plain_text("<p>Lyse <b>cells</b></p><p></p><p>Keep cold</p>"), "Lyse cells\nKeep cold")
        self.assertEqual(plain_text("  Plain  "), "Plain")
        self.assertEqual(plain_text(None), "")


class ExportCommandTest(ExportTestCase):
    @override_settings(PROTOCOLS_IO_ACCESS_TOKEN="token")
    def test_command_reports_the_result(self):
        """Command reports the result."""
        result = ExportResult(
            protocol_uri="cupcake-export-test",
            protocol_url="https://p/x",
            protocol_guid=TARGET_GUID,
            steps_saved=3,
            warnings=["note"],
        )
        out = StringIO()
        with patch("ccrv.management.commands.export_protocol_to_protocols_io.export_protocol", return_value=result):
            call_command(
                "export_protocol_to_protocols_io", str(self.protocol.pk), "--target", "cupcake-export-test", stdout=out
            )
        self.assertIn("Exported 3 step(s) to https://p/x", out.getvalue())
        self.assertIn("note", out.getvalue())
        export = ProtocolsIOExport.objects.get(protocol=self.protocol)
        self.assertEqual((export.protocols_io_guid, export.exported_by), (TARGET_GUID, None))

    @override_settings(PROTOCOLS_IO_ACCESS_TOKEN="")
    def test_command_needs_a_token(self):
        """Command needs a token."""
        with self.assertRaisesMessage(CommandError, "PROTOCOLS_IO_ACCESS_TOKEN is not set"):
            call_command("export_protocol_to_protocols_io", str(self.protocol.pk), "--target", "x")

    @override_settings(PROTOCOLS_IO_ACCESS_TOKEN="token")
    def test_command_rejects_unknown_protocols(self):
        """Command rejects unknown protocols."""
        with self.assertRaisesMessage(CommandError, "does not exist"):
            call_command("export_protocol_to_protocols_io", "999999", "--target", "x")
