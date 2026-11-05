"""Visibility of templates created from schemas through the API."""

from django.contrib.auth.models import User
from django.test import TestCase

from rest_framework.test import APIClient

from ccc.models import LabGroup
from ccv.models import MetadataTableTemplate, Schema

URL = "/api/v1/metadata-table-templates/create_from_schema/"


class CreateFromSchemaVisibilityTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        Schema.sync_builtin_schemas()

    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="pw")
        self.lab_group = LabGroup.objects.create(name="Lab", creator=self.user)
        self.lab_group.members.add(self.user)
        self.schema = Schema.objects.filter(is_builtin=True, is_active=True).first()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _create(self, **fields):
        return self.client.post(URL, {"name": "template", "schema_ids": [self.schema.id], **fields}, format="json")

    def test_group_visibility_is_kept(self):
        response = self._create(visibility="group", lab_group_id=self.lab_group.id)
        self.assertEqual(response.status_code, 201, response.content)
        template = MetadataTableTemplate.objects.get(id=response.json()["id"])
        self.assertEqual(template.visibility, "group")
        self.assertEqual(template.lab_group, self.lab_group)

    def test_public_visibility_is_kept(self):
        response = self._create(visibility="public")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(MetadataTableTemplate.objects.get(id=response.json()["id"]).visibility, "public")

    def test_private_when_nothing_is_given(self):
        response = self._create()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(MetadataTableTemplate.objects.get(id=response.json()["id"]).visibility, "private")

    def test_is_public_is_still_accepted(self):
        response = self._create(is_public=True)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(MetadataTableTemplate.objects.get(id=response.json()["id"]).visibility, "public")

    def test_lab_group_is_still_accepted(self):
        response = self._create(visibility="group", lab_group=self.lab_group.id)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(MetadataTableTemplate.objects.get(id=response.json()["id"]).lab_group, self.lab_group)

    def test_group_visibility_needs_a_lab_group(self):
        response = self._create(visibility="group")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(MetadataTableTemplate.objects.filter(name="template").exists())

    def test_unknown_visibility_is_rejected(self):
        response = self._create(visibility="everyone")
        self.assertEqual(response.status_code, 400)
