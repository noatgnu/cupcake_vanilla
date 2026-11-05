"""SDRF export with validation requested through the API."""

from django.contrib.auth.models import User
from django.test import TestCase

from rest_framework.test import APIClient

from ccv.models import MetadataColumn, MetadataTable

URL = "/api/v1/metadata-management/export_sdrf_file/"


class ExportSdrfValidationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="pw")
        self.table = MetadataTable.objects.create(name="export", owner=self.user, sample_count=2)
        MetadataColumn.objects.create(
            metadata_table=self.table, name="source name", type="", value="s", column_position=0
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _export(self, **fields):
        body = {"metadata_table_id": self.table.id, "metadata_column_ids": [], "sample_number": 2, **fields}
        return self.client.post(URL, body, format="json")

    def test_validation_results_are_reported_in_headers(self):
        response = self._export(validate_sdrf=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("X-SDRF-Validation-Errors", response)
        self.assertIn("X-SDRF-Validation-Warnings", response)

    def test_no_validation_headers_unless_requested(self):
        response = self._export()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn("X-SDRF-Validation-Errors", response)
