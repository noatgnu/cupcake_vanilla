"""Per-sample values read from a column's modifiers for SDRF export."""

from django.test import SimpleTestCase

from ccv.utils import sample_modifier_values


class SampleModifierValuesTests(SimpleTestCase):
    def test_ranges_and_lists_map_to_their_values(self):
        values = sample_modifier_values([{"samples": "1-3", "value": "liver"}, {"samples": "5, 7", "value": "kidney"}])
        self.assertEqual(values, {1: "liver", 2: "liver", 3: "liver", 5: "kidney", 7: "kidney"})

    def test_the_first_modifier_wins_where_ranges_overlap(self):
        values = sample_modifier_values([{"samples": "2-4", "value": "first"}, {"samples": "3-5", "value": "second"}])
        self.assertEqual(values[3], "first")
        self.assertEqual(values[5], "second")

    def test_missing_or_malformed_modifiers_give_nothing(self):
        self.assertEqual(sample_modifier_values(None), {})
        self.assertEqual(sample_modifier_values([]), {})
        self.assertEqual(sample_modifier_values(["text", {"value": "no samples"}]), {})
