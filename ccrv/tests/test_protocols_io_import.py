"""Tests for importing protocols.io protocols into Cupcake sections."""

from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from ccrv.models import ProtocolModel, ProtocolStep
from ccrv.protocols_io.importer import UNTITLED_SECTION, group_into_sections, step_section_title, steps_in_order


def v3_step(step_id, previous_id, section=None, text="", duration=0, section_duration=0):
    """Return a step shaped like the protocols.io v3 protocol response."""
    components = [{"title": "description", "type_id": 1, "source": {"description": f"<p>{text}</p>"}}]
    if section:
        components.insert(0, {"title": "Section", "type_id": 6, "source": {"title": section}})
    return {
        "id": step_id,
        "previous_id": previous_id,
        "components": components,
        "duration": duration,
        "section_duration": section_duration,
    }


def titles(sections):
    """Return the title and step ids of each section."""
    return [(section.title, [step["id"] for step in section.steps]) for section in sections]


class GroupIntoSectionsTest(SimpleTestCase):
    def test_steps_without_a_section_form_untitled_sections_at_their_position(self):
        """Steps without a section form untitled sections at their position."""
        steps = [
            v3_step(1, 0),
            v3_step(2, 1),
            v3_step(3, 2, "Preparation"),
            v3_step(4, 3),
            v3_step(5, 4, "Lysis"),
            v3_step(6, 5, "Lysis"),
            v3_step(7, 6),
        ]
        self.assertEqual(
            titles(group_into_sections(steps)),
            [
                (UNTITLED_SECTION, [1, 2]),
                ("Preparation", [3]),
                (UNTITLED_SECTION, [4]),
                ("Lysis", [5, 6]),
                (UNTITLED_SECTION, [7]),
            ],
        )

    def test_sections_with_the_same_name_apart_stay_separate(self):
        """Sections with the same name apart stay separate."""
        steps = [v3_step(1, 0, "Wash"), v3_step(2, 1, "Spin"), v3_step(3, 2, "Wash")]
        self.assertEqual(titles(group_into_sections(steps)), [("Wash", [1]), ("Spin", [2]), ("Wash", [3])])

    def test_order_follows_the_previous_step_chain(self):
        """Order follows the previous step chain."""
        steps = [v3_step(3, 2, "B"), v3_step(1, 0, "A"), v3_step(2, 1, "A")]
        self.assertEqual([step["id"] for step in steps_in_order(steps)], [1, 2, 3])
        self.assertEqual(titles(group_into_sections(steps)), [("A", [1, 2]), ("B", [3])])

    def test_steps_outside_the_chain_come_last(self):
        """Steps outside the chain come last."""
        steps = [v3_step(1, 0), v3_step(9, 42)]
        self.assertEqual([step["id"] for step in steps_in_order(steps)], [1, 9])

    def test_section_name_falls_back_to_the_step_field(self):
        """Section name falls back to the step field."""
        self.assertEqual(step_section_title({"components": [], "section": " Lysis "}), "Lysis")
        self.assertEqual(step_section_title({"components": [{"title": "Section", "source": {"title": "  "}}]}), "")

    def test_untitled_sections_have_no_duration(self):
        """Untitled sections have no duration."""
        sections = group_into_sections([v3_step(1, 0, section_duration=99), v3_step(2, 1, "A", section_duration=600)])
        self.assertEqual([section.duration for section in sections], [0, 600])

    def test_no_steps(self):
        """No steps."""
        self.assertEqual(group_into_sections([]), [])


@override_settings(PROTOCOLS_IO_ACCESS_TOKEN="token")
class CreateProtocolFromUrlTest(TestCase):
    def import_protocol(self, steps):
        """Import a protocol with the given v3 steps through mocked protocols.io responses."""
        page = Mock(content=b'<meta property="og:url" content="https://www.protocols.io/view/lysis-abc123">')
        api = Mock(status_code=200)
        api.json.return_value = {
            "protocol": {
                "id": 340067,
                "created_on": 1792341267,
                "doi": None,
                "title": "Lysis",
                "description": "About",
                "version_uri": "",
                "steps": steps,
            }
        }
        with patch("ccrv.models.requests.get", side_effect=[page, api]):
            return ProtocolModel.create_protocol_from_url("https://www.protocols.io/view/lysis-abc123")

    def test_every_step_lands_in_an_ordered_section(self):
        """Every step lands in an ordered section."""
        protocol = self.import_protocol(
            [
                v3_step(11, 0, text="Intro"),
                v3_step(12, 11, "Preparation", "Wash", duration=300, section_duration=300),
                v3_step(13, 12, "Preparation", "Dry", duration=60, section_duration=300),
                v3_step(14, 13, text="Interlude"),
                v3_step(15, 14, "Lysis", "Lyse", duration=600, section_duration=600),
            ]
        )
        self.assertFalse(protocol.steps.filter(step_section__isnull=True).exists())
        sections = list(protocol.sections.order_by("order"))
        self.assertEqual(
            [(section.order, section.section_description, section.section_duration) for section in sections],
            [(0, UNTITLED_SECTION, 0), (1, "Preparation", 300), (2, UNTITLED_SECTION, 0), (3, "Lysis", 600)],
        )
        self.assertEqual(
            [[(step.order, step.step_description) for step in section.get_steps_by_order()] for section in sections],
            [
                [(0, "<p>Intro</p>")],
                [(0, "<p>Wash</p>"), (1, "<p>Dry</p>")],
                [(0, "<p>Interlude</p>")],
                [(0, "<p>Lyse</p>")],
            ],
        )
        lyse = protocol.steps.get(step_id=15)
        self.assertEqual((lyse.step_duration, lyse.previous_step.step_id), (600, 14))
        self.assertIsNone(protocol.steps.get(step_id=11).previous_step)

    def test_protocol_without_steps(self):
        """Protocol without steps."""
        protocol = self.import_protocol([])
        self.assertEqual(protocol.sections.count(), 0)
        self.assertEqual(ProtocolStep.objects.filter(protocol=protocol).count(), 0)
