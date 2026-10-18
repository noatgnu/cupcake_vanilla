"""Tests for the HTML export of protocols and sessions."""

import uuid

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from ccc.models import Annotation
from ccm.models import Reagent
from ccrv.export_utils import reagent_scaled_quantity, sanitize_html
from ccrv.models import (
    ProtocolModel,
    ProtocolSection,
    ProtocolStep,
    Session,
    SessionAnnotation,
    StepAnnotation,
    StepReagent,
)


class SanitizeHtmlTest(SimpleTestCase):
    def test_keeps_editor_formatting(self):
        html = '<p class="ql-align-center"><strong>Add</strong> <em>slowly</em><sup>2</sup></p><ul><li>a</li></ul>'
        self.assertEqual(sanitize_html(html), html)

    def test_removes_scripts_handlers_and_unsafe_links(self):
        cleaned = sanitize_html(
            '<p onclick="steal()">x<script>alert(1)</script></p>'
            '<a href="javascript:alert(1)">bad</a><a href="https://example.org">good</a>'
            '<img src="x" onerror="alert(1)">'
        )
        self.assertNotIn("script", cleaned)
        self.assertNotIn("onclick", cleaned)
        self.assertNotIn("onerror", cleaned)
        self.assertNotIn("javascript:", cleaned)
        self.assertIn('href="https://example.org"', cleaned)

    def test_empty_content(self):
        self.assertEqual(sanitize_html(None), "")


class HtmlExportTest(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("export-owner", password="x", first_name="<i>Ada</i>")
        self.protocol = ProtocolModel.objects.create(protocol_title="Lysis", owner=self.owner)
        self.section = ProtocolSection.objects.create(protocol=self.protocol, section_description="Preparation")
        self.step = ProtocolStep.objects.create(
            protocol=self.protocol, step_section=self.section, step_description="<p><strong>Add</strong> buffer</p>"
        )
        self.session = Session.objects.create(name="Run 1", owner=self.owner, unique_id=uuid.uuid4())
        self.session.protocols.add(self.protocol)

    def add_reagent(self, name="RIPA <b>buffer</b>", unit="uL", quantity=200, scalable=True, factor=2):
        reagent = Reagent.objects.create(name=name, unit=unit)
        return StepReagent.objects.create(
            step=self.step, reagent=reagent, quantity=quantity, scalable=scalable, scalable_factor=factor
        )

    def exports(self):
        return {
            "generate_html": self.protocol.generate_html(),
            "generate_html_for_session": self.protocol.generate_html_for_session(self.session),
            "export_html": self.protocol.export_html(),
            "export_html_session": self.protocol.export_html(session=self.session),
            "session_export": self.session.export_protocols_html(),
        }

    def test_exports_keep_step_formatting_without_reagents(self):
        for name, html in self.exports().items():
            with self.subTest(name):
                self.assertIn("<strong>Add</strong> buffer", html)
                self.assertNotIn("&lt;strong&gt;", html)

    def test_exports_fill_reagent_templates(self):
        step_reagent = self.add_reagent()
        reagent_id = step_reagent.id
        self.step.step_description = (
            f"<p>Add %{reagent_id}.quantity% %{reagent_id}.unit% of %{reagent_id}.name%, "
            f"scaled %{reagent_id}.scaled_quantity%</p>"
        )
        self.step.save()
        for name, html in self.exports().items():
            with self.subTest(name):
                self.assertIn('title="Reagent quantity: RIPA &lt;b&gt;buffer&lt;/b&gt;">200</span>', html)
                self.assertIn('title="Reagent unit: RIPA &lt;b&gt;buffer&lt;/b&gt;">uL</span>', html)
                self.assertIn('title="Reagent name">RIPA &lt;b&gt;buffer&lt;/b&gt;</span>', html)
                self.assertIn(
                    'template-value-scaled" title="Scaled quantity: RIPA &lt;b&gt;buffer&lt;/b&gt;">400</span>', html
                )
                self.assertIn("<li>RIPA &lt;b&gt;buffer&lt;/b&gt; - 200 uL (scalable)</li>", html)
                self.assertNotIn("<b>buffer</b>", html)

    def test_unknown_templates_stay_as_written(self):
        self.step.step_description = "<p>Add %999.quantity%</p>"
        self.step.save()
        self.assertIn("Add %999.quantity%", self.protocol.generate_html())

    def test_step_html_cannot_inject_scripts(self):
        self.step.step_description = '<p onclick="steal()">Add<script>alert(1)</script></p>'
        self.step.save()
        for name, html in self.exports().items():
            with self.subTest(name):
                self.assertNotIn("alert(1)", html)
                self.assertNotIn("onclick", html)

    def test_session_export_with_step_annotations(self):
        self.add_reagent()
        annotation = Annotation.objects.create(
            annotation="Lysate <b>cloudy</b>", annotation_type="text", owner=self.owner
        )
        StepAnnotation.objects.create(session=self.session, step=self.step, annotation=annotation)
        session_note = Annotation.objects.create(annotation="Started late", annotation_type="text", owner=self.owner)
        SessionAnnotation.objects.create(session=self.session, annotation=session_note)
        for html in (self.protocol.generate_html_for_session(self.session), self.session.export_protocols_html()):
            self.assertIn("Lysate &lt;b&gt;cloudy&lt;/b&gt;", html)
            self.assertIn("&lt;i&gt;Ada&lt;/i&gt;", html)
            self.assertNotIn("<i>Ada</i>", html)
        self.assertIn("Started late", self.session.export_protocols_html())


class ReagentScaledQuantityTest(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user("scale-owner", password="x")
        protocol = ProtocolModel.objects.create(protocol_title="Scale", owner=owner)
        step = ProtocolStep.objects.create(protocol=protocol, step_description="x")
        self.step_reagent = StepReagent.objects.create(
            step=step,
            reagent=Reagent.objects.create(name="Water", unit="mL"),
            quantity=5,
            scalable=True,
            scalable_factor=3,
        )

    def test_scalable_reagent_uses_its_factor(self):
        self.assertEqual(reagent_scaled_quantity(self.step_reagent), 15)

    def test_reagent_that_is_not_scalable_keeps_its_quantity(self):
        self.step_reagent.scalable = False
        self.assertEqual(reagent_scaled_quantity(self.step_reagent), 5)
