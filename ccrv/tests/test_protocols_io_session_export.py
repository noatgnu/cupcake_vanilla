"""Tests for exporting Cupcake sessions into protocols.io runs."""

import json
import shutil
import struct
import tempfile
import uuid
import zlib
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from choux import APIError, UploadedFile, image_dimensions
from rest_framework.test import APIClient

from ccc.models import Annotation, AsyncTaskStatus
from ccm.models import Instrument, InstrumentUsage
from ccrv.models import (
    InstrumentUsageStepAnnotation,
    ProtocolModel,
    ProtocolSection,
    ProtocolsIOAccount,
    ProtocolsIOExport,
    ProtocolsIORun,
    ProtocolStep,
    Session,
    StepAnnotation,
    StepVariation,
)
from ccrv.protocols_io import ExportResult, export_step_guid, ordered_steps
from ccrv.protocols_io.annotations import (
    annotation_comment,
    annotation_digest,
    calculator_lines,
    molarity_lines,
    sketch_png,
    structured_lines,
    vtt_lines,
)
from ccrv.protocols_io.session_export import SessionExportError, export_session_protocols, session_title
from ccrv.tasks.protocols_io_tasks import export_session_to_protocols_io_task

MEDIA_ROOT = tempfile.mkdtemp()


class FakeProtocolsIO:
    """In-memory protocols.io holding protocols, runs and run comments."""

    def __init__(self):
        """Start with no protocols and no runs."""
        self.protocol_steps = {}
        self.runs = {}
        self.discussions = {}
        self.uploads = []
        self.trashed = []
        self.copies = []
        self.copy_guids = {}
        self.next_id = 1000

    def new_id(self):
        """Return a fresh numeric id."""
        self.next_id += 1
        return self.next_id

    def get_steps(self, protocol):
        """Return the steps of a protocol."""
        return [{"guid": guid} for guid in self.protocol_steps[protocol]]

    def get_protocol(self, protocol):
        """Return a protocol, or fail when it does not exist."""
        if protocol not in self.protocol_steps:
            raise APIError("protocol does not exist", http_status=404)
        return {"uri": protocol}

    def create_protocol(self, guid, *, type_id=1):
        """Create an empty protocol."""
        uri = f"copy-{self.new_id()}"
        self.protocol_steps[uri] = []
        return {"uri": uri, "id": self.next_id}

    def export_protocol(
        self, protocol, client, target, *, variations=None, title=None, description=None, progress=None
    ):
        """Stand in for the protocol exporter, recording what was written."""
        guid = self.copy_guids.setdefault(target, uuid.uuid4().hex.upper())
        step_ids = [step.pk for step in ordered_steps(protocol)]
        self.protocol_steps[target] = [export_step_guid(guid, step_id) for step_id in step_ids]
        self.copies.append(
            {
                "target": target,
                "title": title,
                "description": description,
                "variations": {key: value.variation_description for key, value in (variations or {}).items()},
            }
        )
        return ExportResult(
            protocol_uri=target,
            protocol_url=f"https://www.protocols.io/view/{target}",
            protocol_guid=guid,
            protocol_id=self.new_id(),
            step_ids=step_ids,
        )

    def create_record(self, protocol_uri, *, folder_guid=None):
        """Create a run copying the steps of a protocol."""
        guid = uuid.uuid4().hex.upper()
        steps = [{"id": self.new_id(), "guid": uuid.uuid4().hex.upper()} for _ in self.protocol_steps[protocol_uri]]
        self.runs[guid] = {"protocol": protocol_uri, "folder": folder_guid, "title": "", "steps": steps}
        return {"id": self.new_id(), "guid": guid, "item_id": self.new_id(), "steps": steps}

    def save_record(self, guid, changes):
        """Apply title changes to a run."""
        for change in changes:
            self.runs[guid]["title"] = change["data"]["title"]

    def trash(self, item_ids):
        """Record trashed items."""
        self.trashed.extend(item_ids)
        return list(item_ids)

    def add_record_comment(self, guid, body, *, private=False, validate=True):
        """Comment on a whole run."""
        discussion = self.new_id()
        self.discussions[discussion] = {"run": guid, "step": 0, "body": body.to_dict()}
        return {"discussion_id": discussion}

    def add_step_comment(self, record_guid, step_id, body, *, validate=True):
        """Comment on a run step."""
        discussion = self.new_id()
        self.discussions[discussion] = {"run": record_guid, "step": step_id, "body": body.to_dict()}
        return {"discussion_id": discussion}

    def edit_discussion(self, discussion_id, body, *, validate=True):
        """Replace a comment."""
        self.discussions[discussion_id]["body"] = body.to_dict()

    def delete_discussion(self, discussion_id):
        """Delete a comment."""
        self.discussions.pop(discussion_id)

    def upload_file(self, filename, content, *, mime_type=None, width=None, height=None):
        """Store a file."""
        self.uploads.append((filename, mime_type, width, height))
        return UploadedFile(
            id=self.new_id(),
            key=f"files/{filename}",
            source=f"https://content.protocols.io/files/{filename}",
            raw_source="",
            original_name=filename,
            mime_type=mime_type or "application/octet-stream",
            size=len(content),
            file_type=0,
            thumb_url="",
            width=width,
            height=height,
        )

    def texts(self, discussion_id):
        """Return the paragraph texts of a comment."""
        return [block["text"] for block in self.discussions[discussion_id]["body"]["blocks"]]

    def step_comments(self, run_guid):
        """Return the comments on the steps of a run, by step id."""
        found = {}
        for discussion_id, discussion in self.discussions.items():
            if discussion["run"] == run_guid and discussion["step"]:
                found.setdefault(discussion["step"], []).append(discussion_id)
        return found


class AnnotationTextTest(SimpleTestCase):
    def test_calculator_history_becomes_one_line_per_calculation(self):
        """Calculator history becomes one line per calculation."""
        history = [
            {"inputPromptFirstValue": 2, "inputPromptSecondValue": 3, "operation": "+", "result": 5},
            {"inputPromptFirstValue": 9, "inputPromptSecondValue": None, "operation": "sqrt", "result": 3.0},
            {"inputPromptFirstValue": 1, "inputPromptSecondValue": 1, "operation": "+", "result": 2, "scratched": True},
        ]
        self.assertEqual(calculator_lines(json.dumps(history)), ["2 + 3 = 5", "sqrt(9) = 3"])

    def test_molarity_history_names_the_result_and_its_inputs(self):
        """Molarity history names the result and its inputs."""
        history = [
            {
                "data": {
                    "concentration": 10,
                    "concentrationUnit": "mM",
                    "volume": 5,
                    "volumeUnit": "mL",
                    "molecularWeight": 58.44,
                    "weight": None,
                },
                "operationType": "dynamic",
                "calculatedField": "weight",
                "result": 0.002922,
            }
        ]
        self.assertEqual(
            molarity_lines(json.dumps(history)),
            ["Weight = 0.002922 (from Concentration 10 mM, Volume 5 mL, Molecular weight 58.44 g/mol)"],
        )

    def test_text_that_is_not_json_is_kept(self):
        """Text that is not json is kept."""
        self.assertEqual(calculator_lines("2 + 2\n= 4"), ["2 + 2", "= 4"])
        self.assertEqual(structured_lines("plain"), ["plain"])

    def test_structured_content_is_described(self):
        """Structured content is described."""
        checklist = {"name": "Before lysis", "checkList": [{"content": "Ice ready", "completed": True}]}
        self.assertEqual(
            structured_lines(json.dumps(checklist)),
            ["Name: Before lysis", "Check list:", "  Content: Ice ready; Completed: yes"],
        )

    def test_vtt_cues_become_lines_with_their_start_time(self):
        """Vtt cues become lines with their start time."""
        vtt = (
            "WEBVTT\n\nNOTE generated\nby whisper\n\n1\n00:00:00.000 --> 00:00:02.000\nAdd the buffer.\n\n"
            "2\n00:01:02.500 --> 00:01:04.000 align:start\nMix well\nand wait.\n\n01:00:05.000 --> 01:00:06.000\nDone."
        )
        self.assertEqual(vtt_lines(vtt), ["0:00 Add the buffer.", "1:02 Mix well and wait.", "1:00:05 Done."])
        self.assertEqual(vtt_lines("Just text\n\nmore"), ["Just text", "more"])

    def test_sketch_strokes_are_drawn_with_erasers_in_the_background_colour(self):
        """Sketch strokes are drawn with erasers in the background colour."""
        sketch = {
            "width": 20,
            "height": 10,
            "strokes": [
                {"points": [{"x": 0, "y": 5}, {"x": 19, "y": 5}], "color": "#ff0000", "width": 2},
                {"points": [{"x": 10, "y": 0}, {"x": 10, "y": 9}], "color": "eraser", "width": 2},
                {"points": [{"x": 1, "y": 1}], "color": "#000000", "width": 1},
            ],
        }
        content, width, height = sketch_png(json.dumps(sketch))
        self.assertEqual((width, height), (20, 10))
        self.assertEqual(image_dimensions(content), (20, 10))
        pixels = decode_png(content, width, height)
        self.assertEqual(pixels[5][2], (255, 0, 0))
        self.assertEqual(pixels[5][10], (255, 255, 255))
        self.assertEqual(pixels[0][0], (255, 255, 255))
        self.assertEqual(pixels[1][1], (255, 255, 255))

    def test_large_sketches_are_scaled_down(self):
        """Large sketches are scaled down."""
        _, width, height = sketch_png(json.dumps({"width": 4000, "height": 1000, "strokes": []}))
        self.assertEqual((width, height), (2000, 500))

    def test_unreadable_sketches_are_refused(self):
        """Unreadable sketches are refused."""
        self.assertIsNone(sketch_png("not json"))
        self.assertIsNone(sketch_png(json.dumps({"width": 0, "height": 5})))


def decode_png(content, width, height):
    """Return the pixel rows of an unfiltered RGB PNG made by sketch_png."""
    start = content.index(b"IDAT") + 4
    length = struct.unpack(">I", content[start - 8 : start - 4])[0]
    raw = zlib.decompress(content[start : start + length])
    row = width * 3 + 1
    return [[tuple(raw[y * row + 1 + x * 3 : y * row + 4 + x * 3]) for x in range(width)] for y in range(height)]


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class SessionExportTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = get_user_model().objects.create_user("run-user", password="x", first_name="Ada", last_name="L")
        self.fake = FakeProtocolsIO()
        self.lysis, self.lysis_steps = self.make_protocol("Lysis", 2)
        self.digest, self.digest_steps = self.make_protocol("Digest", 1)
        self.session = Session.objects.create(name="Run 7", owner=self.user, unique_id=uuid.uuid4())
        self.session.protocols.add(self.lysis)

    def make_protocol(self, title, count):
        """Create a protocol with one section and export it to the fake protocols.io."""
        protocol = ProtocolModel.objects.create(protocol_title=title, owner=self.user)
        section = ProtocolSection.objects.create(protocol=protocol, section_description="Main", order=0)
        steps = [
            ProtocolStep.objects.create(
                protocol=protocol, step_section=section, step_description=f"{title} {index}", order=index
            )
            for index in range(count)
        ]
        guid = uuid.uuid4().hex.upper()
        ProtocolsIOExport.objects.create(
            protocol=protocol,
            exported_by=self.user,
            protocols_io_id=1,
            protocols_io_guid=guid,
            protocols_io_uri=title.lower(),
            protocols_io_url=f"https://www.protocols.io/view/{title.lower()}",
            step_ids=[step.pk for step in steps],
        )
        expected = [export_step_guid(guid, step.pk) for step in steps]
        self.fake.protocol_steps[title.lower()] = expected
        return protocol, steps

    def annotate(self, step, text="", kind="text", **fields):
        """Attach an annotation to a step of the session."""
        annotation = Annotation.objects.create(annotation=text, annotation_type=kind, owner=self.user, **fields)
        return StepAnnotation.objects.create(session=self.session, step=step, annotation=annotation)

    def export(self, protocols=None, **options):
        """Export the session to the fake protocols.io."""
        with patch("ccrv.protocols_io.session_export.export_protocol", side_effect=self.fake.export_protocol):
            return export_session_protocols(
                self.session, protocols or [self.lysis], self.fake, user=self.user, **options
            )

    def vary(self, step, text="Used 300 uL", duration=1200):
        """Record a variation of a step in the session."""
        return StepVariation.objects.create(
            step=step, session=self.session, variation_description=text, variation_duration=duration
        )


class SessionExportTest(SessionExportTestCase):
    def test_first_export_creates_a_titled_run_with_a_reference_and_step_comments(self):
        """First export creates a titled run with a reference and step comments."""
        self.annotate(self.lysis_steps[1], "Lysate looked cloudy")
        [result] = self.export(folder_guid="F" * 32, session_url="https://cupcake.example/sessions/7")
        run = ProtocolsIORun.objects.get()
        stored = self.fake.runs[run.record_guid]
        self.assertTrue(result.created)
        self.assertEqual(result.record_url, f"https://www.protocols.io/run/{run.record_guid}")
        self.assertEqual((stored["title"], stored["folder"]), ("Run 7", "F" * 32))
        self.assertEqual([entry["step"] for entry in run.step_map], [step.pk for step in self.lysis_steps])
        reference = self.fake.texts(run.reference_comment_id)
        self.assertIn(f"Cupcake session id: {self.session.unique_id}", reference)
        self.assertIn("Open the session in Cupcake", reference)
        comments = self.fake.step_comments(run.record_guid)
        self.assertEqual(list(comments), [run.step_map[1]["id"]])
        texts = self.fake.texts(comments[run.step_map[1]["id"]][0])
        self.assertTrue(texts[0].startswith("Note from Cupcake by Ada L"))
        self.assertEqual(texts[1], "Lysate looked cloudy")
        self.assertEqual(result.comments_added, 1)

    def test_export_again_updates_the_same_run(self):
        """Export again updates the same run."""
        kept = self.annotate(self.lysis_steps[0], "kept")
        changed = self.annotate(self.lysis_steps[0], "before")
        removed = self.annotate(self.lysis_steps[1], "removed")
        scratched = self.annotate(self.lysis_steps[1], "scratched later")
        self.export()
        run = ProtocolsIORun.objects.get()
        changed_comment = run.comments.get(step_annotation=changed)
        changed.annotation.annotation = "after"
        changed.annotation.save()
        removed.delete()
        scratched.annotation.scratched = True
        scratched.annotation.save()
        self.annotate(self.lysis_steps[1], "new")
        [result] = self.export()
        self.assertEqual(ProtocolsIORun.objects.count(), 1)
        self.assertEqual(
            (result.created, result.comments_added, result.comments_updated, result.comments_deleted),
            (False, 1, 1, 2),
        )
        self.assertEqual(result.comments_unchanged, 1)
        self.assertEqual(self.fake.texts(changed_comment.discussion_id)[1], "after")
        self.assertEqual(
            sorted(comment.step_annotation_id for comment in run.comments.all()),
            sorted([kept.pk, changed.pk, StepAnnotation.objects.get(annotation__annotation="new").pk]),
        )
        self.assertEqual(sum(len(ids) for ids in self.fake.step_comments(run.record_guid).values()), 3)

    def test_session_variations_replace_their_steps_in_a_protocol_copy(self):
        """Session variations replace their steps in a protocol copy."""
        step = self.lysis_steps[1]
        self.annotate(step, "note on the varied step")
        self.vary(step)
        StepVariation.objects.create(step=step, variation_description="Unused alternative", variation_duration=5)
        [result] = self.export()
        [copy] = self.fake.copies
        self.assertEqual(copy["title"], "Lysis - Run 7")
        self.assertEqual(copy["variations"], {step.pk: "Used 300 uL"})
        self.assertIn("Steps as performed in the Cupcake session Run 7.", copy["description"])
        self.assertIn("Based on https://www.protocols.io/view/lysis", copy["description"])
        run = ProtocolsIORun.objects.get()
        self.assertEqual(self.fake.runs[run.record_guid]["protocol"], copy["target"])
        self.assertEqual(run.protocol_export.session, self.session)
        self.assertEqual(
            (result.variations_used, result.protocol_copy_url), (1, f"https://www.protocols.io/view/{copy['target']}")
        )
        self.assertIn(
            "1 step(s) follow the variations used in this session.", self.fake.texts(run.reference_comment_id)
        )
        [comment_ids] = self.fake.step_comments(run.record_guid).values()
        self.assertEqual(self.fake.texts(comment_ids[0])[1], "note on the varied step")

    def test_unchanged_variations_keep_the_run_and_the_copy(self):
        """Unchanged variations keep the run and the copy."""
        self.vary(self.lysis_steps[0])
        self.export()
        self.annotate(self.lysis_steps[0], "later note")
        [result] = self.export()
        self.assertEqual((ProtocolsIORun.objects.count(), len(self.fake.copies)), (1, 1))
        self.assertEqual((result.created, result.comments_added), (False, 1))

    def test_changed_variations_make_a_new_copy_and_a_new_run(self):
        """Changed variations make a new copy and a new run."""
        variation = self.vary(self.lysis_steps[0])
        self.export()
        first_run = ProtocolsIORun.objects.get()
        variation.variation_description = "Used 400 uL"
        variation.save()
        [result] = self.export()
        self.assertEqual(ProtocolsIORun.objects.count(), 2)
        self.assertTrue(result.created)
        self.assertIn("so a new run was created", result.warnings[0])
        first_copy, second_copy = self.fake.copies
        self.assertNotEqual(first_copy["target"], second_copy["target"])
        self.assertEqual(second_copy["variations"], {self.lysis_steps[0].pk: "Used 400 uL"})
        self.assertEqual(ProtocolsIOExport.objects.filter(session=self.session).count(), 2)
        self.assertEqual(self.fake.runs[first_run.record_guid]["protocol"], first_copy["target"])

    def test_a_copy_changed_on_protocols_io_is_not_reused(self):
        """A copy changed on protocols io is not reused."""
        self.vary(self.lysis_steps[0])
        self.export(new_runs=True)
        self.fake.protocol_steps[self.fake.copies[0]["target"]] = ["EDITED"]
        self.export(new_runs=True)
        self.assertNotEqual(self.fake.copies[1]["target"], self.fake.copies[0]["target"])

    def test_returning_to_earlier_variations_reuses_their_copy(self):
        """Returning to earlier variations reuses their copy."""
        variation = self.vary(self.lysis_steps[0])
        self.export()
        variation.variation_duration = 60
        variation.save()
        self.export()
        variation.variation_duration = 1200
        variation.save()
        self.export()
        self.assertEqual(len(self.fake.copies), 2)
        self.assertEqual(ProtocolsIORun.objects.count(), 3)

    def test_varied_protocols_need_no_earlier_export(self):
        """Varied protocols need no earlier export."""
        self.lysis.protocols_io_exports.all().delete()
        self.vary(self.lysis_steps[0])
        [result] = self.export()
        self.assertTrue(result.created)
        self.assertNotIn("Based on", self.fake.copies[0]["description"])

    def test_dropping_all_variations_moves_back_to_the_exported_protocol(self):
        """Dropping all variations moves back to the exported protocol."""
        variation = self.vary(self.lysis_steps[0])
        self.export()
        variation.delete()
        [result] = self.export()
        newest = ProtocolsIORun.objects.first()
        self.assertTrue(result.created)
        self.assertEqual(self.fake.runs[newest.record_guid]["protocol"], "lysis")
        self.assertEqual(result.protocol_copy_url, "")

    def test_new_runs_leaves_earlier_runs_alone(self):
        """New runs leaves earlier runs alone."""
        self.export()
        self.export(new_runs=True)
        self.assertEqual(ProtocolsIORun.objects.count(), 2)
        self.assertEqual(len(self.fake.runs), 2)

    def test_runs_of_other_users_are_not_updated(self):
        """Runs of other users are not updated."""
        self.export()
        other = get_user_model().objects.create_user("run-other", password="x")
        export_session_protocols(self.session, [self.lysis], self.fake, user=other)
        self.assertEqual(ProtocolsIORun.objects.filter(exported_by=other).count(), 1)
        self.assertEqual(ProtocolsIORun.objects.count(), 2)

    def test_each_protocol_gets_its_own_run(self):
        """Each protocol gets its own run."""
        self.session.protocols.add(self.digest)
        self.annotate(self.lysis_steps[0], "lysis note")
        self.annotate(self.digest_steps[0], "digest note")
        results = self.export(protocols=[self.lysis, self.digest])
        self.assertEqual([result.protocol_id for result in results], [self.lysis.pk, self.digest.pk])
        titles = sorted(run["title"] for run in self.fake.runs.values())
        self.assertEqual(titles, ["Run 7 - Digest", "Run 7 - Lysis"])
        digest_run = ProtocolsIORun.objects.get(protocol=self.digest)
        self.assertIn("Part 2 of 2: protocol Digest.", self.fake.texts(digest_run.reference_comment_id))
        self.assertEqual(digest_run.comments.count(), 1)
        self.assertEqual(session_title(self.session), "Run 7")

    def test_protocols_are_checked_before_any_run_is_created(self):
        """Protocols are checked before any run is created."""
        self.session.protocols.add(self.digest)
        ProtocolStep.objects.create(protocol=self.digest, step_section=self.digest_steps[0].step_section, order=5)
        with self.assertRaisesMessage(SessionExportError, "changed in Cupcake"):
            self.export(protocols=[self.lysis, self.digest])
        self.assertEqual(self.fake.runs, {})

    def test_protocol_changed_on_protocols_io_stops_the_export(self):
        """Protocol changed on protocols io stops the export."""
        self.fake.protocol_steps["lysis"] = ["OTHER"]
        with self.assertRaisesMessage(SessionExportError, "protocols.io protocol changed"):
            self.export()

    def test_protocol_never_exported_stops_the_export(self):
        """Protocol never exported stops the export."""
        self.lysis.protocols_io_exports.all().delete()
        with self.assertRaisesMessage(SessionExportError, "Export the protocol"):
            self.export()

    def test_annotations_on_steps_outside_the_run_are_reported(self):
        """Annotations on steps outside the run are reported."""
        loose = ProtocolStep.objects.create(protocol=self.lysis, step_description="loose", order=9)
        self.annotate(loose, "outside")
        ProtocolsIOExport.objects.filter(protocol=self.lysis).update(step_ids=[s.pk for s in self.lysis_steps])
        [result] = self.export()
        self.assertIn("1 annotation(s) on steps that are not in the protocols.io run were left out", result.warnings)


class AnnotationCommentTest(SessionExportTestCase):
    def comment(self, step_annotation):
        """Build the comment for a step annotation."""
        return annotation_comment(step_annotation, self.fake)

    def test_image_is_uploaded_with_its_size_and_shown_at_most_600_wide(self):
        """Image is uploaded with its size and shown at most 600 wide."""
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1200).to_bytes(4, "big") + (300).to_bytes(4, "big")
        step_annotation = self.annotate(self.lysis_steps[0], "gel", kind="image")
        step_annotation.annotation.file.save("gel.png", ContentFile(png + b"\x00" * 20))
        content = self.comment(step_annotation)
        self.assertEqual(self.fake.uploads, [("gel.png", None, 1200, 300)])
        entity = next(iter(content.draft.to_dict()["entityMap"].values()))
        self.assertEqual((entity["type"], entity["data"]["width"], entity["data"]["height"]), ("image", 600, 150))

    def test_sketch_is_uploaded_as_png_image(self):
        """Sketch is uploaded as png image."""
        sketch = {"width": 40, "height": 30, "strokes": [{"points": [{"x": 0, "y": 0}, {"x": 5, "y": 5}]}]}
        step_annotation = self.annotate(self.lysis_steps[0], kind="sketch")
        step_annotation.annotation.file.save("sketch_1.json", ContentFile(json.dumps(sketch).encode()))
        self.comment(step_annotation)
        self.assertEqual(self.fake.uploads, [("sketch_1.png", "image/png", 40, 30)])

    def test_audio_is_attached_with_its_transcript_translation_and_subtitle_files(self):
        """Audio is attached with its transcript translation and subtitle files."""
        step_annotation = self.annotate(
            self.lysis_steps[0],
            kind="audio",
            language="fr",
            transcription="WEBVTT\n\n00:00.000 --> 00:01.000\nCentrifuger.",
            translation="WEBVTT\n\n00:00.000 --> 00:01.000\nSpin it down.",
        )
        step_annotation.annotation.file.save("note.webm", ContentFile(b"audio"))
        content = self.comment(step_annotation)
        draft = content.draft.to_dict()
        texts = [block["text"] for block in draft["blocks"] if block["text"].strip()]
        self.assertEqual(texts[1:], ["Transcription (fr)", "0:00 Centrifuger.", "Translation", "0:00 Spin it down."])
        names = [entity["data"]["original_name"] for entity in draft["entityMap"].values()]
        self.assertEqual(names, ["note.webm", "note.transcription.vtt", "note.translation.vtt"])
        self.assertEqual([upload[1] for upload in self.fake.uploads], [None, "text/vtt", "text/vtt"])
        self.assertEqual(content.files_uploaded, 3)

    def test_translation_stored_as_both_fields_is_exported_once(self):
        """Translation stored as both fields is exported once."""
        vtt = "WEBVTT\n\n00:00.000 --> 00:01.000\nSpin it down."
        step_annotation = self.annotate(
            self.lysis_steps[0], kind="audio", language="fr", transcription=vtt, translation=vtt
        )
        content = self.comment(step_annotation)
        texts = [block["text"] for block in content.draft.to_dict()["blocks"] if block["text"].strip()]
        self.assertEqual(texts[1:], ["Translation", "0:00 Spin it down."])
        self.assertEqual(
            [upload[0] for upload in self.fake.uploads], [f"annotation-{step_annotation.annotation.pk}.translation.vtt"]
        )

    def test_plain_text_transcripts_are_not_attached(self):
        """Plain text transcripts are not attached."""
        step_annotation = self.annotate(self.lysis_steps[0], kind="video", transcription="Typed notes")
        content = self.comment(step_annotation)
        texts = [block["text"] for block in content.draft.to_dict()["blocks"]]
        self.assertEqual(texts[-2:], ["Transcription", "Typed notes"])
        self.assertEqual(self.fake.uploads, [])

    @override_settings(PROTOCOLS_IO_MAX_UPLOAD_BYTES=3)
    def test_large_files_are_left_out_with_a_warning(self):
        """Large files are left out with a warning."""
        step_annotation = self.annotate(self.lysis_steps[0], kind="video")
        step_annotation.annotation.file.save("run.mp4", ContentFile(b"too large"))
        content = self.comment(step_annotation)
        self.assertEqual(self.fake.uploads, [])
        self.assertEqual(len(content.warnings), 1)
        self.assertIn("larger than the upload limit", content.warnings[0])

    def test_booking_lists_the_instrument_usage(self):
        """Booking lists the instrument usage."""
        instrument = Instrument.objects.create(instrument_name="Orbitrap")
        usage = InstrumentUsage.objects.create(
            instrument=instrument,
            user=self.user,
            time_started=datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc),
            time_ended=datetime(2026, 10, 19, 11, 0, tzinfo=timezone.utc),
        )
        step_annotation = self.annotate(self.lysis_steps[0], "Instrument booking: Orbitrap", kind="booking")
        InstrumentUsageStepAnnotation.objects.create(step_annotation=step_annotation, instrument_usage=usage)
        texts = [block["text"] for block in self.comment(step_annotation).draft.to_dict()["blocks"]]
        self.assertTrue(texts[0].startswith("Instrument booking from Cupcake"))
        self.assertTrue(texts[2].startswith("Orbitrap: 2026-10-19"))

    def test_digest_changes_with_the_content(self):
        """Digest changes with the content."""
        step_annotation = self.annotate(self.lysis_steps[0], "first")
        before = annotation_digest(step_annotation)
        step_annotation.annotation.annotation = "second"
        self.assertNotEqual(annotation_digest(step_annotation), before)
        step_annotation.annotation.annotation = "first"
        self.assertEqual(annotation_digest(step_annotation), before)


class SessionExportEndpointTest(SessionExportTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("ccrv:session-export-to-protocols-io", args=[self.session.pk])
        ProtocolsIOAccount.objects.create(user=self.user, access_token="personal-token", username="toan-phung")

    def test_queues_every_session_protocol_by_default(self):
        """Queues every session protocol by default."""
        self.session.protocols.add(self.digest)
        with patch.object(export_session_to_protocols_io_task, "delay", return_value=Mock(id="job-2")) as delay:
            response = self.client.post(
                self.url, {"folder": "F" * 32, "session_url": "https://cupcake.example/s/7"}, format="json"
            )
        self.assertEqual(response.status_code, 202)
        task = AsyncTaskStatus.objects.get(id=response.data["task_id"])
        self.assertEqual((task.task_type, task.rq_job_id), ("EXPORT_RUN_PROTOCOLS_IO", "job-2"))
        args = delay.call_args.args
        self.assertEqual(sorted(args[1]), sorted([self.lysis.pk, self.digest.pk]))
        self.assertEqual(args[4:], (False, "F" * 32, "https://cupcake.example/s/7"))

    def test_rejects_protocols_outside_the_session_and_bad_addresses(self):
        """Rejects protocols outside the session and bad addresses."""
        with patch.object(export_session_to_protocols_io_task, "delay") as delay:
            outside = self.client.post(self.url, {"protocols": [self.digest.pk]}, format="json")
            address = self.client.post(self.url, {"session_url": "javascript:alert(1)"}, format="json")
        self.assertEqual((outside.status_code, address.status_code), (400, 400))
        delay.assert_not_called()

    def test_names_protocols_that_were_never_exported(self):
        """Names protocols that were never exported."""
        self.lysis.protocols_io_exports.all().delete()
        with patch.object(export_session_to_protocols_io_task, "delay") as delay:
            response = self.client.post(self.url, {}, format="json")
        self.assertEqual((response.status_code, response.data["protocols_not_exported"]), (400, ["Lysis"]))
        delay.assert_not_called()

    def test_varied_protocols_can_be_exported_without_an_earlier_export(self):
        """Varied protocols can be exported without an earlier export."""
        self.lysis.protocols_io_exports.all().delete()
        self.vary(self.lysis_steps[0])
        with patch.object(export_session_to_protocols_io_task, "delay", return_value=Mock(id="job-3")):
            response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, 202)

    def test_status_describes_each_protocol(self):
        """Status describes each protocol."""
        self.session.protocols.add(self.digest)
        self.vary(self.lysis_steps[0])
        self.export(protocols=[self.lysis])
        response = self.client.get(reverse("ccrv:session-protocols-io-status", args=[self.session.pk]))
        self.assertEqual(response.status_code, 200)
        entries = {entry["protocol_title"]: entry for entry in response.data}
        self.assertEqual((entries["Lysis"]["varied_steps"], entries["Lysis"]["run_is_current"]), (1, True))
        self.assertEqual(entries["Lysis"]["protocol_export"]["protocols_io_uri"], "lysis")
        self.assertEqual((entries["Digest"]["varied_steps"], entries["Digest"]["run"]), (0, None))
        StepVariation.objects.filter(session=self.session).update(variation_duration=1)
        response = self.client.get(reverse("ccrv:session-protocols-io-status", args=[self.session.pk]))
        self.assertFalse({entry["protocol_title"]: entry for entry in response.data}["Lysis"]["run_is_current"])

    def test_viewers_cannot_export(self):
        """Viewers cannot export."""
        viewer = get_user_model().objects.create_user("run-viewer", password="x")
        self.session.viewers.add(viewer)
        client = APIClient()
        client.force_authenticate(user=viewer)
        with patch.object(export_session_to_protocols_io_task, "delay") as delay:
            response = client.post(self.url, {}, format="json")
        self.assertIn(response.status_code, (403, 404))
        delay.assert_not_called()

    def test_lists_runs_with_their_comment_count(self):
        """Lists runs with their comment count."""
        self.annotate(self.lysis_steps[0], "note")
        self.export()
        response = self.client.get(reverse("ccrv:session-protocols-io-runs", args=[self.session.pk]))
        self.assertEqual(response.status_code, 200)
        [entry] = response.data
        self.assertEqual((entry["protocol_title"], entry["comment_count"], entry["title"]), ("Lysis", 1, "Run 7"))
        self.assertEqual(entry["record_url"], f"https://www.protocols.io/run/{entry['record_guid']}")


class SessionExportTaskTest(SessionExportTestCase):
    def test_task_stores_one_result_per_run(self):
        """Task stores one result per run."""
        task = AsyncTaskStatus.objects.create(task_type="EXPORT_RUN_PROTOCOLS_IO", user=self.user)
        with patch("ccrv.tasks.protocols_io_tasks.client_for", return_value=_context(self.fake)):
            outcome = export_session_to_protocols_io_task(self.session.pk, [self.lysis.pk], self.user.pk, str(task.id))
        task.refresh_from_db()
        self.assertEqual(task.status, "SUCCESS")
        self.assertTrue(outcome["success"])
        self.assertEqual(task.result["runs"][0]["title"], "Run 7")

    def test_task_reports_export_errors(self):
        """Task reports export errors."""
        self.lysis.protocols_io_exports.all().delete()
        task = AsyncTaskStatus.objects.create(task_type="EXPORT_RUN_PROTOCOLS_IO", user=self.user)
        with patch("ccrv.tasks.protocols_io_tasks.client_for", return_value=_context(self.fake)):
            export_session_to_protocols_io_task(self.session.pk, [self.lysis.pk], self.user.pk, str(task.id))
        task.refresh_from_db()
        self.assertEqual(task.status, "FAILURE")
        self.assertIn("Export the protocol", task.error_message)

    def test_task_explains_the_run_limit(self):
        """Task explains the run limit."""
        task = AsyncTaskStatus.objects.create(task_type="EXPORT_RUN_PROTOCOLS_IO", user=self.user)
        self.fake.create_record = Mock(
            side_effect=APIError("POST /v3/records failed with HTTP 400: SUBSCRIPTION_LIMIT")
        )
        with patch("ccrv.tasks.protocols_io_tasks.client_for", return_value=_context(self.fake)):
            export_session_to_protocols_io_task(self.session.pk, [self.lysis.pk], self.user.pk, str(task.id))
        task.refresh_from_db()
        self.assertIn("run limit of its plan", task.error_message)


def _context(value):
    """Return a context manager that yields ``value``."""
    manager = Mock()
    manager.__enter__ = Mock(return_value=value)
    manager.__exit__ = Mock(return_value=False)
    return manager
