"""Tests for converting step reagent templates into protocols.io Draft.js content."""

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from choux import html_to_draft, validate_draft

from ccm.models import Reagent
from ccrv.models import ProtocolModel, ProtocolStep, StepReagent
from cupcake_protocols_io.step_templates import StepTemplateResolver, TemplateReagent, step_to_draft

UNITS = [
    {"id": 1, "type_id": 3, "name": "µL", "aliases": ["uL", "ul", "microliter"]},
    {"id": 2, "type_id": 3, "name": "mL", "aliases": ["ml"]},
    {"id": 10, "type_id": 24, "name": "°C", "aliases": ["C"]},
]
RIPA = TemplateReagent(id=5, name="RIPA buffer", unit="uL", quantity=200, scaled_quantity=400)
BEADS = TemplateReagent(id=6, name="Magnetic beads", unit="units", quantity=20, scaled_quantity=20)


def convert(html, reagents=(RIPA, BEADS)):
    """Convert step HTML with the test reagents and return the Draft.js document and unresolved templates."""
    resolver = StepTemplateResolver.for_step(html, reagents, UNITS)
    draft = html_to_draft(html, text_resolver=resolver).to_dict()
    return draft, resolver.unresolved


def entities(draft):
    """Return the data of every entity in a Draft.js document, each with its type."""
    return [entity["data"] | {"type": entity["type"]} for entity in draft["entityMap"].values()]


class StepTemplateResolverTest(SimpleTestCase):
    def test_quantity_and_unit_become_one_amount_labelled_with_the_name(self):
        draft, unresolved = convert("<p>Add %5.quantity% %5.unit% to the cells.</p>")
        self.assertEqual(draft["blocks"][0]["text"], "Add   to the cells.")
        [entity] = entities(draft)
        self.assertEqual((entity["type"], entity["amount"], entity["unit"]), ("amount", "200", 1))
        self.assertEqual(entity["label"], "RIPA buffer")
        self.assertEqual(unresolved, [])
        self.assertEqual(validate_draft(draft, units=UNITS), [])

    def test_amount_is_unlabelled_when_the_step_shows_the_name(self):
        draft, _ = convert("<p>Add %5.quantity%%5.unit% of %5.name%.</p>")
        self.assertEqual(draft["blocks"][0]["text"], "Add   of RIPA buffer.")
        self.assertEqual(entities(draft)[0]["label"], "")

    def test_scaled_quantity_uses_the_scaled_value(self):
        draft, _ = convert("<p>%5.scaled_quantity% %5.unit%</p>")
        self.assertEqual(entities(draft)[0]["amount"], "400")

    def test_quantity_without_unit_template_is_plain_text(self):
        draft, _ = convert("<p>Use %5.quantity% aliquots.</p>")
        self.assertEqual(draft["blocks"][0]["text"], "Use 200 aliquots.")
        self.assertEqual(draft["entityMap"], {})

    def test_unit_unknown_to_protocols_io_stays_text(self):
        draft, _ = convert("<p>Add %6.quantity% %6.unit% of %6.name%.</p>")
        self.assertEqual(draft["blocks"][0]["text"], "Add 20 units of Magnetic beads.")
        self.assertEqual(draft["entityMap"], {})

    def test_unit_of_another_reagent_is_not_merged(self):
        draft, _ = convert("<p>%5.quantity% %6.unit%</p>")
        self.assertEqual(draft["blocks"][0]["text"], "200 units")

    def test_lone_unit_and_name_are_text(self):
        draft, _ = convert("<p>%5.name% is measured in %5.unit%.</p>")
        self.assertEqual(draft["blocks"][0]["text"], "RIPA buffer is measured in uL.")

    def test_unknown_reagent_templates_are_kept_and_reported(self):
        draft, unresolved = convert("<p>Add %9.quantity% %9.unit% and %5.name%.</p>")
        self.assertEqual(draft["blocks"][0]["text"], "Add %9.quantity% %9.unit% and RIPA buffer.")
        self.assertEqual(unresolved, ["%9.quantity%", "%9.unit%"])

    def test_styles_around_templates_are_kept(self):
        draft, _ = convert("<p><strong>%5.name%</strong> then %5.quantity% %5.unit%</p>")
        block = draft["blocks"][0]
        self.assertEqual(block["text"][:11], "RIPA buffer")
        self.assertEqual(block["inlineStyleRanges"], [{"offset": 0, "length": 11, "style": "bold"}])
        self.assertEqual(entities(draft)[0]["label"], "")

    def test_templates_split_across_markup_are_expanded_separately(self):
        draft, _ = convert("<p>%5.quantity% <em>%5.unit%</em></p>")
        self.assertEqual(draft["blocks"][0]["text"], "200 uL")
        self.assertEqual(draft["entityMap"], {})

    def test_text_without_templates_is_unchanged(self):
        draft, unresolved = convert("<p>Spin 5 min at 50% speed.</p>")
        self.assertEqual(draft["blocks"][0]["text"], "Spin 5 min at 50% speed.")
        self.assertEqual(unresolved, [])


class StepToDraftTest(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user("template-owner", password="x")
        protocol = ProtocolModel.objects.create(protocol_title="Lysis", owner=owner)
        self.step = ProtocolStep.objects.create(protocol=protocol, step_description="placeholder")
        ripa = Reagent.objects.create(name="RIPA buffer", unit="uL")
        self.step_reagent = StepReagent.objects.create(
            step=self.step, reagent=ripa, quantity=200, scalable=True, scalable_factor=1.5
        )

    def test_converts_a_stored_step(self):
        reagent_id = self.step_reagent.id
        self.step.step_description = (
            f"<p>Lyse in %{reagent_id}.scaled_quantity% %{reagent_id}.unit% for 10 min.</p><p>Keep on ice.</p>"
        )
        draft, unresolved = step_to_draft(self.step, UNITS, scaling_factor=2)
        content = draft.to_dict()
        self.assertEqual([block["text"] for block in content["blocks"]], ["Lyse in   for 10 min.", "Keep on ice."])
        self.assertEqual(entities(content)[0]["amount"], "600")
        self.assertEqual(entities(content)[0]["label"], "RIPA buffer")
        self.assertEqual(unresolved, [])
        self.assertEqual(validate_draft(content, units=UNITS), [])

    def test_scaling_does_not_apply_to_reagents_that_are_not_scalable(self):
        self.step_reagent.scalable = False
        self.step_reagent.save()
        self.assertEqual(TemplateReagent.from_step_reagent(self.step_reagent, scaling_factor=3).scaled_quantity, 200)

    def test_empty_step_text_gives_one_empty_block(self):
        self.step.step_description = ""
        draft, unresolved = step_to_draft(self.step, UNITS)
        self.assertEqual([block["text"] for block in draft.to_dict()["blocks"]], [""])
        self.assertEqual(unresolved, [])
