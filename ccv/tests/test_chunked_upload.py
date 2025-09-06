"""
Tests for CCV Metadata Chunked Upload functionality.
"""


from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from ccv.chunked_upload import MetadataFileUpload
from tests.factories import MetadataTableFactory, UserFactory, read_fixture_content


class MetadataChunkedUploadTestCase(APITestCase):
    """Test cases for metadata chunked upload API."""

    def setUp(self):
        self.user = UserFactory.create_user()
        self.metadata_table = MetadataTableFactory.create_basic_table(user=self.user, sample_count=0)
        self.client = APIClient()

    def test_upload_metadata_chunk(self):
        """Test uploading metadata file chunk via API."""
        self.client.force_authenticate(user=self.user)

        # Use real SDRF fixture content
        sdrf_content = read_fixture_content("PXD019185_PXD018883.sdrf.tsv")
        if not sdrf_content:
            self.skipTest("SDRF fixture file not found")

        # Take first 1000 bytes as chunk
        chunk_data = sdrf_content[:1000].encode("utf-8")
        total_size = len(chunk_data)

        chunk_file = SimpleUploadedFile("metadata.sdrf.tsv", chunk_data, content_type="text/tab-separated-values")

        data = {"filename": "metadata.sdrf.tsv", "file": chunk_file}
        url = reverse("ccv:chunked-upload")

        response = self.client.put(
            url, data, format="multipart", HTTP_CONTENT_RANGE=f"bytes 0-{total_size-1}/{total_size}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("id", response.data)
        upload_id = response.data["id"]

        # Verify upload was stored
        upload = MetadataFileUpload.objects.get(id=upload_id)
        self.assertEqual(upload.filename, "metadata.sdrf.tsv")
        self.assertEqual(upload.offset, total_size)
        self.assertTrue(upload.file)

    def test_complete_metadata_upload(self):
        """Test completing metadata upload with processing."""
        self.client.force_authenticate(user=self.user)

        # Use real SDRF fixture but take small portion for testing
        sdrf_content = read_fixture_content("PXD019185_PXD018883.sdrf.tsv")
        if not sdrf_content:
            self.skipTest("SDRF fixture file not found")

        # Take first 3 lines (header + 2 samples) for manageable test
        lines = sdrf_content.split("\n")[:3]
        test_content = "\n".join(lines)
        chunk_data = test_content.encode("utf-8")
        total_size = len(chunk_data)

        chunk_file = SimpleUploadedFile("complete.sdrf.tsv", chunk_data, content_type="text/tab-separated-values")

        data = {
            "filename": "complete.sdrf.tsv",
            "file": chunk_file,
            "metadata_table_id": self.metadata_table.id,
            "create_pools": "true",
            "replace_existing": "true",
        }
        url = reverse("ccv:chunked-upload")

        # Upload as complete file
        response = self.client.put(
            url, data, format="multipart", HTTP_CONTENT_RANGE=f"bytes 0-{total_size-1}/{total_size}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        upload_id = response.data["id"]

        # Complete the upload - get actual checksum from uploaded file
        upload = MetadataFileUpload.objects.get(id=upload_id)
        actual_checksum = upload.checksum  # drf-chunked-upload calculates this

        completion_data = {
            "sha256": actual_checksum,
            "metadata_table_id": self.metadata_table.id,
            "create_pools": True,
            "replace_existing": True,
        }

        completion_url = reverse("ccv:chunked-upload-detail", kwargs={"pk": upload_id})
        completion_response = self.client.post(completion_url, completion_data)

        # Should process successfully
        self.assertEqual(completion_response.status_code, status.HTTP_200_OK)

        # Verify metadata was processed
        self.metadata_table.refresh_from_db()
        self.assertEqual(self.metadata_table.sample_count, 2)  # Two rows of data

        # Verify columns were created from real SDRF headers
        columns = self.metadata_table.columns.all()
        self.assertTrue(columns.exists())
        column_names = [col.name for col in columns]
        self.assertIn("source name", column_names)
        # The SDRF parsing creates columns based on the header structure
        # Just verify we have some columns created
        self.assertGreater(len(columns), 10)  # SDRF has many columns

    def test_upload_without_metadata_table(self):
        """Test upload without specifying metadata table (should still work)."""
        self.client.force_authenticate(user=self.user)

        # Use minimal real SDRF content
        chunk_data = b"source name\tcharacteristics[organism]\nsample_1\thomo sapiens"
        chunk_file = SimpleUploadedFile("simple.sdrf.tsv", chunk_data, content_type="text/tab-separated-values")

        data = {"filename": "simple.sdrf.tsv", "file": chunk_file}
        url = reverse("ccv:chunked-upload")

        response = self.client.put(
            url, data, format="multipart", HTTP_CONTENT_RANGE=f"bytes 0-{len(chunk_data)-1}/{len(chunk_data)}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_invalid_file_type(self):
        """Test upload with invalid file type."""
        self.client.force_authenticate(user=self.user)

        chunk_data = b"invalid content"
        chunk_file = SimpleUploadedFile("test.exe", chunk_data, content_type="application/octet-stream")

        data = {"filename": "test.exe", "file": chunk_file, "metadata_table_id": self.metadata_table.id}
        url = reverse("ccv:chunked-upload")

        response = self.client.put(
            url, data, format="multipart", HTTP_CONTENT_RANGE=f"bytes 0-{len(chunk_data)-1}/{len(chunk_data)}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        upload_id = response.data["id"]

        # Get the actual checksum for completion
        upload = MetadataFileUpload.objects.get(id=upload_id)
        actual_checksum = upload.checksum  # drf-chunked-upload calculates this

        # Try to complete - should fail due to invalid file type
        completion_data = {"sha256": actual_checksum, "metadata_table_id": self.metadata_table.id}
        completion_url = reverse("ccv:chunked-upload-detail", kwargs={"pk": upload_id})
        completion_response = self.client.post(completion_url, completion_data)

        # Should return error about unsupported file type
        self.assertEqual(completion_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Unsupported file type", str(completion_response.data))
