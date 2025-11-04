"""
Test cases for Advanced Autofill functionality.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from rest_framework import status
from rest_framework.test import APITestCase

from ccc.models import LabGroup
from ccv.models import MetadataColumn, MetadataTable
from ccv.utils import AutofillSpecValidator, SampleVariationGenerator

User = get_user_model()


class AutofillSpecValidatorTest(TestCase):
    """Test cases for AutofillSpecValidator."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.lab_group = LabGroup.objects.create(name="Test Lab", description="Test laboratory group")
        self.table = MetadataTable.objects.create(
            name="Test Table", sample_count=100, owner=self.user, lab_group=self.lab_group
        )
        self.column1 = MetadataColumn.objects.create(
            metadata_table=self.table, name="fraction_identifier", type="text", column_position=1
        )
        self.column2 = MetadataColumn.objects.create(
            metadata_table=self.table, name="label", type="text", column_position=2
        )

    def test_valid_spec(self):
        """Test validation with valid specification."""
        spec = {
            "templateSamples": [1, 2],
            "targetSampleCount": 50,
            "variations": [
                {"columnId": self.column1.id, "type": "range", "start": 1, "end": 10},
                {"columnId": self.column2.id, "type": "list", "values": ["TMT126", "TMT127"]},
            ],
            "fillStrategy": "cartesian_product",
        }

        validator = AutofillSpecValidator(spec, self.table)
        self.assertTrue(validator.is_valid())
        self.assertEqual(len(validator.errors), 0)

    def test_missing_template_samples(self):
        """Test validation fails when templateSamples is missing."""
        spec = {
            "templateSamples": [],
            "targetSampleCount": 50,
            "variations": [{"columnId": self.column1.id, "type": "range"}],
            "fillStrategy": "cartesian_product",
        }

        validator = AutofillSpecValidator(spec, self.table)
        self.assertFalse(validator.is_valid())
        self.assertIn("templateSamples is required", validator.errors)

    def test_invalid_target_count(self):
        """Test validation fails when targetSampleCount is invalid."""
        spec = {
            "templateSamples": [1],
            "targetSampleCount": 0,
            "variations": [{"columnId": self.column1.id, "type": "range"}],
            "fillStrategy": "cartesian_product",
        }

        validator = AutofillSpecValidator(spec, self.table)
        self.assertFalse(validator.is_valid())
        self.assertIn("targetSampleCount must be a positive integer", validator.errors)

    def test_target_count_exceeds_sample_count(self):
        """Test validation fails when targetSampleCount exceeds table sample_count."""
        spec = {
            "templateSamples": [1],
            "targetSampleCount": 150,
            "variations": [{"columnId": self.column1.id, "type": "range"}],
            "fillStrategy": "cartesian_product",
        }

        validator = AutofillSpecValidator(spec, self.table)
        self.assertFalse(validator.is_valid())
        self.assertTrue(any("cannot exceed table sample_count" in error for error in validator.errors))

    def test_missing_variations(self):
        """Test validation fails when variations is empty."""
        spec = {
            "templateSamples": [1],
            "targetSampleCount": 50,
            "variations": [],
            "fillStrategy": "cartesian_product",
        }

        validator = AutofillSpecValidator(spec, self.table)
        self.assertFalse(validator.is_valid())
        self.assertIn("variations is required and must not be empty", validator.errors)

    def test_invalid_column_id(self):
        """Test validation fails when column doesn't exist."""
        spec = {
            "templateSamples": [1],
            "targetSampleCount": 50,
            "variations": [{"columnId": 99999, "type": "range"}],
            "fillStrategy": "cartesian_product",
        }

        validator = AutofillSpecValidator(spec, self.table)
        self.assertFalse(validator.is_valid())
        self.assertTrue(any("not found in table" in error for error in validator.errors))


class SampleVariationGeneratorTest(TestCase):
    """Test cases for SampleVariationGenerator."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.lab_group = LabGroup.objects.create(name="Test Lab", description="Test laboratory group")
        self.table = MetadataTable.objects.create(
            name="Test Table", sample_count=100, owner=self.user, lab_group=self.lab_group
        )
        self.column1 = MetadataColumn.objects.create(
            metadata_table=self.table, name="fraction_identifier", type="text", column_position=1
        )
        self.column2 = MetadataColumn.objects.create(
            metadata_table=self.table, name="label", type="text", column_position=2
        )

    def test_generate_range_variations(self):
        """Test generating range-based variations."""
        variations = [{"columnId": self.column1.id, "type": "range", "start": 1, "end": 5, "step": 1}]

        generator = SampleVariationGenerator(self.table, [1, 2], variations, 10)
        variations_data = generator.generate_variations()

        self.assertIn(self.column1.id, variations_data)
        self.assertEqual(variations_data[self.column1.id], [1, 2, 3, 4, 5])

    def test_generate_list_variations(self):
        """Test generating list-based variations."""
        variations = [{"columnId": self.column2.id, "type": "list", "values": ["TMT126", "TMT127", "TMT128"]}]

        generator = SampleVariationGenerator(self.table, [1], variations, 10)
        variations_data = generator.generate_variations()

        self.assertIn(self.column2.id, variations_data)
        self.assertEqual(variations_data[self.column2.id], ["TMT126", "TMT127", "TMT128"])

    def test_generate_pattern_variations(self):
        """Test generating pattern-based variations."""
        variations = [{"columnId": self.column1.id, "type": "pattern", "pattern": "sample_{i}", "count": 3}]

        generator = SampleVariationGenerator(self.table, [1], variations, 10)
        variations_data = generator.generate_variations()

        self.assertIn(self.column1.id, variations_data)
        self.assertEqual(variations_data[self.column1.id], ["sample_1", "sample_2", "sample_3"])

    def test_cartesian_product(self):
        """Test cartesian product fill strategy."""
        variations_data = {self.column1.id: [1, 2], self.column2.id: ["A", "B", "C"]}

        generator = SampleVariationGenerator(self.table, [1], [], 10)
        result = generator.cartesian_product(variations_data)

        self.assertEqual(len(result), 6)
        self.assertIn({self.column1.id: 1, self.column2.id: "A"}, result)
        self.assertIn({self.column1.id: 1, self.column2.id: "B"}, result)
        self.assertIn({self.column1.id: 2, self.column2.id: "C"}, result)

    def test_sequential_fill(self):
        """Test sequential fill strategy."""
        variations_data = {self.column1.id: [1, 2], self.column2.id: ["A", "B", "C"]}

        generator = SampleVariationGenerator(self.table, [1], [], 10)
        result = generator.sequential_fill(variations_data, 5)

        self.assertEqual(len(result), 5)
        self.assertEqual(result[0][self.column1.id], 1)
        self.assertEqual(result[1][self.column1.id], 2)
        self.assertEqual(result[2][self.column1.id], 1)

    def test_interleaved_fill(self):
        """Test interleaved fill strategy."""
        variations_data = {self.column1.id: [1, 2, 3], self.column2.id: ["A", "B"]}

        generator = SampleVariationGenerator(self.table, [1], [], 10)
        result = generator.interleaved_fill(variations_data, 5)

        self.assertEqual(len(result), 5)

    def test_apply_variations_to_samples(self):
        """Test applying variations to sample columns."""
        sample_variations = [
            {self.column1.id: 1, self.column2.id: "A"},
            {self.column1.id: 2, self.column2.id: "B"},
        ]

        generator = SampleVariationGenerator(self.table, [1], [], 4)
        columns_to_update = generator.apply_variations_to_samples(sample_variations, 4)

        self.assertGreater(len(columns_to_update), 0)

    def test_get_summary(self):
        """Test getting operation summary."""
        variations = [{"columnId": self.column1.id, "type": "range", "start": 1, "end": 5}]
        sample_variations = [{self.column1.id: 1}, {self.column1.id: 2}]

        generator = SampleVariationGenerator(self.table, [1, 2], variations, 10)
        summary = generator.get_summary(sample_variations, "cartesian_product")

        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["samplesModified"], 10)
        self.assertEqual(summary["columnsModified"], 1)
        self.assertEqual(summary["variationsCombinations"], 2)
        self.assertEqual(summary["strategy"], "cartesian_product")


class AdvancedAutofillAPITest(APITestCase):
    """Test cases for advanced autofill API endpoint."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.lab_group = LabGroup.objects.create(name="Test Lab", description="Test laboratory group")
        self.table = MetadataTable.objects.create(
            name="Test Table", sample_count=100, owner=self.user, lab_group=self.lab_group
        )
        self.column1 = MetadataColumn.objects.create(
            metadata_table=self.table, name="fraction_identifier", type="text", column_position=1
        )
        self.column2 = MetadataColumn.objects.create(
            metadata_table=self.table, name="label", type="text", column_position=2
        )
        self.client.force_authenticate(user=self.user)

    def test_advanced_autofill_cartesian_product(self):
        """Test advanced autofill with cartesian product strategy."""
        url = f"/api/v1/metadata-tables/{self.table.pk}/advanced_autofill/"
        data = {
            "templateSamples": [1, 2],
            "targetSampleCount": 20,
            "variations": [
                {"columnId": self.column1.id, "type": "range", "start": 1, "end": 5, "step": 1},
                {"columnId": self.column2.id, "type": "list", "values": ["TMT126", "TMT127"]},
            ],
            "fillStrategy": "cartesian_product",
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["samplesModified"], 20)
        self.assertEqual(response.data["columnsModified"], 2)
        self.assertEqual(response.data["strategy"], "cartesian_product")

    def test_advanced_autofill_sequential(self):
        """Test advanced autofill with sequential strategy."""
        url = f"/api/v1/metadata-tables/{self.table.pk}/advanced_autofill/"
        data = {
            "templateSamples": [1],
            "targetSampleCount": 10,
            "variations": [{"columnId": self.column1.id, "type": "range", "start": 1, "end": 3}],
            "fillStrategy": "sequential",
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["strategy"], "sequential")

    def test_advanced_autofill_locked_table(self):
        """Test advanced autofill fails on locked table."""
        self.table.is_locked = True
        self.table.save()

        url = f"/api/v1/metadata-tables/{self.table.pk}/advanced_autofill/"
        data = {
            "templateSamples": [1],
            "targetSampleCount": 10,
            "variations": [{"columnId": self.column1.id, "type": "range", "start": 1, "end": 5}],
            "fillStrategy": "cartesian_product",
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("locked", response.data["error"].lower())

    def test_advanced_autofill_invalid_spec(self):
        """Test advanced autofill with invalid specification."""
        url = f"/api/v1/metadata-tables/{self.table.pk}/advanced_autofill/"
        data = {
            "templateSamples": [],
            "targetSampleCount": 10,
            "variations": [],
            "fillStrategy": "cartesian_product",
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("errors", response.data)

    def test_advanced_autofill_permission_denied(self):
        """Test advanced autofill requires edit permission."""
        other_user = User.objects.create_user(username="otheruser", email="other@example.com", password="testpass123")
        self.client.force_authenticate(user=other_user)

        url = f"/api/v1/metadata-tables/{self.table.pk}/advanced_autofill/"
        data = {
            "templateSamples": [1],
            "targetSampleCount": 10,
            "variations": [{"columnId": self.column1.id, "type": "range", "start": 1, "end": 5}],
            "fillStrategy": "cartesian_product",
        }

        response = self.client.post(url, data, format="json")

        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_advanced_autofill_realistic_tmt_fractionation(self):
        """
        Test realistic scenario based on MSV000079033 fixture.
        Creates 50 samples: 5 fractions × 10 TMT labels (cartesian product).
        """
        fraction_col = MetadataColumn.objects.create(
            metadata_table=self.table, name="comment[fraction identifier]", type="text", column_position=3
        )
        label_col = MetadataColumn.objects.create(
            metadata_table=self.table, name="comment[label]", type="text", column_position=4
        )

        url = f"/api/v1/metadata-tables/{self.table.pk}/advanced_autofill/"
        data = {
            "templateSamples": [1],
            "targetSampleCount": 50,
            "variations": [
                {"columnId": fraction_col.id, "type": "range", "start": 1, "end": 5, "step": 1},
                {
                    "columnId": label_col.id,
                    "type": "list",
                    "values": [
                        "TMT126",
                        "TMT127N",
                        "TMT127C",
                        "TMT128N",
                        "TMT128C",
                        "TMT129N",
                        "TMT129C",
                        "TMT130N",
                        "TMT130C",
                        "TMT131",
                    ],
                },
            ],
            "fillStrategy": "cartesian_product",
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["samplesModified"], 50)
        self.assertEqual(response.data["columnsModified"], 2)
        self.assertEqual(response.data["variationsCombinations"], 50)
        self.assertEqual(response.data["strategy"], "cartesian_product")

        fraction_col.refresh_from_db()
        label_col.refresh_from_db()

        self.assertGreater(len(fraction_col.modifiers), 0)
        self.assertGreater(len(label_col.modifiers), 0)

        sample_1_fraction = next((m["value"] for m in fraction_col.modifiers if "1" in m.get("samples", "")), None)
        sample_1_label = next((m["value"] for m in label_col.modifiers if "1" in m.get("samples", "")), None)
        self.assertIsNotNone(sample_1_fraction)
        self.assertIsNotNone(sample_1_label)
