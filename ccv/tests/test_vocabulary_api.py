"""The vocabulary list and who can see and use each vocabulary."""

from django.urls import reverse
from django.utils import timezone

from rest_framework import serializers, status
from rest_framework.test import APITestCase

from ccc.models import LabGroup
from ccv.models import Vocabulary, VocabularyTerm
from ccv.serializers import validate_vocabulary_key
from tests.factories import UserFactory


class VocabularyApiTests(APITestCase):
    def setUp(self):
        self.member = UserFactory.create_user(username="member")
        self.outsider = UserFactory.create_user(username="outsider")
        self.staff = UserFactory.create_user(username="staff", is_staff=True)
        self.lab = LabGroup.objects.create(name="Strain lab", creator=self.member)
        self.lab.members.add(self.member)
        self.lab_vocabulary = Vocabulary.objects.create(
            key="custom.lab_strains",
            label="Lab strains",
            provider=Vocabulary.PROVIDER_CUSTOM,
            storage=Vocabulary.STORAGE_TERMS,
            lab_group=self.lab,
        )
        VocabularyTerm.objects.create(
            vocabulary=self.lab_vocabulary, external_id="S1", name="Strain one", fetched_at=timezone.now()
        )
        self.pending = Vocabulary.objects.create(
            key="plugin.tool.parts",
            label="Parts",
            provider=Vocabulary.PROVIDER_PLUGIN,
            storage=Vocabulary.STORAGE_TERMS,
            approved=False,
        )

    def keys(self, user, **params):
        self.client.force_authenticate(user=user)
        response = self.client.get(reverse("ccv:vocabulary-list"), {"limit": 100, **params})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return [row["key"] for row in response.data["results"]]

    def test_built_in_vocabularies_are_listed_with_their_labels_and_presets(self):
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(reverse("ccv:vocabulary-list"), {"provider": "builtin", "limit": 100})
        rows = {row["key"]: row for row in response.data["results"]}
        self.assertEqual(len(rows), 14)
        self.assertEqual(rows["species"]["label"], "Species (UniProt)")
        presets = rows["ms_unique_vocabularies"]["filter_presets"]
        self.assertEqual(len(presets), 14)
        self.assertIn({"label": "Instrument (MS)", "filters": {"term_type": "instrument"}}, presets)
        self.assertEqual(rows["mondo"]["filter_presets"], [])

    def test_lab_group_vocabularies_are_seen_by_members_and_staff_only(self):
        self.assertIn("custom.lab_strains", self.keys(self.member))
        self.assertIn("custom.lab_strains", self.keys(self.staff))
        self.assertNotIn("custom.lab_strains", self.keys(self.outsider))

    def test_vocabularies_waiting_for_approval_are_listed_for_staff_who_ask(self):
        self.assertNotIn("plugin.tool.parts", self.keys(self.staff))
        self.assertIn("plugin.tool.parts", self.keys(self.staff, include_unapproved="true"))
        self.assertNotIn("plugin.tool.parts", self.keys(self.member, include_unapproved="true"))

    def test_disabled_vocabularies_are_never_listed(self):
        self.lab_vocabulary.status = Vocabulary.STATUS_DISABLED
        self.lab_vocabulary.save()
        self.assertNotIn("custom.lab_strains", self.keys(self.staff, include_unapproved="true"))

    def test_a_vocabulary_is_found_by_its_dotted_key(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.get(reverse("ccv:vocabulary-detail", kwargs={"key": "custom.lab_strains"}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["lab_group_name"], "Strain lab")
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(reverse("ccv:vocabulary-detail", kwargs={"key": "custom.lab_strains"}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_filters_and_paging(self):
        self.assertEqual(self.keys(self.member, search="strain"), ["custom.lab_strains"])
        self.assertEqual(self.keys(self.member, provider="custom"), ["custom.lab_strains"])
        self.client.force_authenticate(user=self.member)
        first = self.client.get(reverse("ccv:vocabulary-list"), {"limit": 5, "offset": 0}).data
        second = self.client.get(reverse("ccv:vocabulary-list"), {"limit": 5, "offset": 5}).data
        self.assertEqual(len(first["results"]), 5)
        self.assertFalse({r["key"] for r in first["results"]} & {r["key"] for r in second["results"]})

    def test_columns_only_take_vocabularies_their_user_can_use(self):
        self.assertEqual(validate_vocabulary_key("custom.lab_strains", self.member), "custom.lab_strains")
        self.assertEqual(validate_vocabulary_key("", self.outsider), "")
        for key, user in (("custom.lab_strains", self.outsider), ("plugin.tool.parts", self.staff)):
            with self.assertRaises(serializers.ValidationError):
                validate_vocabulary_key(key, user)

    def test_search_returns_nothing_from_a_vocabulary_the_user_cannot_see(self):
        url = reverse("ccv:ontologysearch-suggest")
        params = {"q": "strain", "type": "custom.lab_strains"}
        self.client.force_authenticate(user=self.member)
        self.assertEqual(self.client.get(url, params).data["count"], 1)
        self.client.force_authenticate(user=self.outsider)
        self.assertEqual(self.client.get(url, params).data["count"], 0)
