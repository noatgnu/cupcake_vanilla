"""Plugin vocabularies: declared in the manifest, filled by the plugin, approved by staff before users see them."""

from django.urls import reverse

from rest_framework import serializers, status
from rest_framework.test import APITestCase

from ccc.plugin.model import Plugin
from ccv.models import MetadataTable, Vocabulary
from ccv.serializers import validate_vocabulary_key
from tests.factories import UserFactory

MANIFEST = {
    "name": "strain-db",
    "vocabularies": [
        {"key": "strains", "label": "Strain database", "kind": "strain", "sdrfShortName": "SDB", "minTermLength": 2},
        {"key": "Bad Key", "label": "Invalid"},
        {"key": "nolabel"},
    ],
}
KEY = "plugin.strain-db.strains"


class PluginVocabularyTests(APITestCase):
    def setUp(self):
        self.plugin = Plugin.objects.create(
            name="strain-db", display_name="Strain DB", version="1.0", manifest_cache=MANIFEST
        )
        self.token = self.plugin._plain_token
        self.staff = UserFactory.create_user(username="staff", is_staff=True)
        self.user = UserFactory.create_user(username="user")

    def as_plugin(self, token=None):
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_PLUGIN_TOKEN=token or self.token)

    def as_user(self, user):
        self.client.credentials()
        self.client.force_authenticate(user=user)

    def push(self, terms, key="strains"):
        self.as_plugin()
        return self.client.post(reverse("ccv:pluginvocabulary-terms", args=[key]), {"terms": terms}, format="json")

    def finish(self, key="strains", **body):
        self.as_plugin()
        return self.client.post(reverse("ccv:pluginvocabulary-finish", args=[key]), body, format="json")

    def visible_keys(self, user):
        self.as_user(user)
        return [
            row["key"]
            for row in self.client.get(reverse("ccv:vocabulary-list"), {"search": "strain-db", "limit": 10}).data[
                "results"
            ]
        ]

    def approve(self, approved=True, user=None):
        self.as_user(user or self.staff)
        return self.client.post(reverse("ccv:vocabulary-approve", args=[KEY]), {"approved": approved}, format="json")

    def test_the_manifest_declares_vocabularies_that_wait_for_approval(self):
        vocabulary = Vocabulary.objects.get(plugin=self.plugin)
        self.assertEqual(vocabulary.key, KEY)
        self.assertEqual(vocabulary.provider, Vocabulary.PROVIDER_PLUGIN)
        self.assertEqual(vocabulary.storage, Vocabulary.STORAGE_TERMS)
        self.assertEqual(
            (vocabulary.label, vocabulary.kind, vocabulary.sdrf_short_name), ("Strain database", "strain", "SDB")
        )
        self.assertEqual(vocabulary.min_term_length, 2)
        self.assertFalse(vocabulary.approved)
        self.assertEqual(vocabulary.status, Vocabulary.STATUS_LOADING)

    def test_startup_updates_declared_vocabularies_and_keeps_approval(self):
        self.approve()
        self.as_plugin()
        manifest = {
            "vocabularies": [{"key": "strains", "label": "Strains v2"}, {"key": "lines", "label": "Cell lines"}]
        }
        response = self.client.post(reverse("ccc:plugin-startup"), {"manifest": manifest}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        strains = Vocabulary.objects.get(key=KEY)
        self.assertEqual(strains.label, "Strains v2")
        self.assertTrue(strains.approved)
        self.assertFalse(Vocabulary.objects.get(key="plugin.strain-db.lines").approved)

    def test_vocabularies_left_out_of_the_manifest_are_disabled_and_come_back(self):
        self.plugin.manifest_cache = {"vocabularies": []}
        self.plugin.save(update_fields=["manifest_cache"])
        self.assertEqual(Vocabulary.objects.get(key=KEY).status, Vocabulary.STATUS_DISABLED)
        self.assertEqual(self.push([{"id": "S1", "name": "strain one"}]).status_code, status.HTTP_404_NOT_FOUND)
        self.plugin.manifest_cache = MANIFEST
        self.plugin.save()
        self.assertEqual(Vocabulary.objects.get(key=KEY).status, Vocabulary.STATUS_LOADING)

    def test_saving_a_plugin_without_manifest_changes_leaves_its_vocabularies(self):
        Vocabulary.objects.filter(key=KEY).update(label="Renamed by hand")
        self.plugin.lifecycle_status = Plugin.LIFECYCLE_RUNNING
        self.plugin.save(update_fields=["lifecycle_status"])
        self.assertEqual(Vocabulary.objects.get(key=KEY).label, "Renamed by hand")

    def test_a_plugin_cannot_take_over_another_providers_key(self):
        other = Plugin.objects.create(name="other", display_name="Other", version="1.0")
        Vocabulary.objects.filter(key=KEY).update(plugin=other)
        self.plugin.save()
        self.assertEqual(Vocabulary.objects.get(key=KEY).plugin, other)

    def test_the_plugin_pushes_terms_in_batches_and_replaces_the_old_ones(self):
        first = self.push(
            [{"id": "S1", "name": "strain one", "synonyms": ["s1", " "]}, {"id": "S2", "name": "strain two"}]
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["stored"], 2)
        self.finish(version="2026-11")
        vocabulary = Vocabulary.objects.get(key=KEY)
        self.assertEqual((vocabulary.term_count, vocabulary.status), (2, Vocabulary.STATUS_ACTIVE))
        self.assertEqual(vocabulary.source_version.version, "2026-11")
        self.assertEqual(vocabulary.terms.get(external_id="S1").synonyms, "s1")

        started = self.push([{"id": "S2", "name": "strain two renamed"}]).data["received_at"]
        self.push([{"id": "S3", "name": "strain three", "obsolete": True}])
        finished = self.finish(replace_before=started)
        self.assertEqual(finished.data["removed"], 1)
        self.assertEqual(finished.data["term_count"], 2)
        self.assertEqual(finished.data["local_key"], "strains")
        self.assertEqual(
            sorted(vocabulary.terms.values_list("external_id", "name")),
            [("S2", "strain two renamed"), ("S3", "strain three")],
        )

    def test_term_batches_are_validated(self):
        self.assertEqual(self.push([]).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.push([{"name": "no id"}]).status_code, status.HTTP_400_BAD_REQUEST)
        too_many = [{"id": f"S{index}", "name": f"strain {index}"} for index in range(1001)]
        self.assertEqual(self.push(too_many).status_code, status.HTTP_400_BAD_REQUEST)

    def test_plugins_only_reach_their_own_vocabularies(self):
        other = Plugin.objects.create(
            name="other",
            display_name="Other",
            version="1.0",
            manifest_cache={"vocabularies": [{"key": "lines", "label": "Lines"}]},
        )
        self.as_plugin(other._plain_token)
        self.assertEqual(
            self.client.post(
                reverse("ccv:pluginvocabulary-terms", args=["strains"]),
                {"terms": [{"id": "S1", "name": "x"}]},
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            [row["key"] for row in self.client.get(reverse("ccv:pluginvocabulary-list")).data], ["plugin.other.lines"]
        )

    def test_plugin_endpoints_need_the_plugin_token(self):
        self.as_user(self.staff)
        self.assertIn(
            self.client.get(reverse("ccv:pluginvocabulary-list")).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
        self.as_plugin("not-a-token")
        self.assertEqual(
            self.client.get(reverse("ccv:pluginvocabulary-list")).status_code, status.HTTP_401_UNAUTHORIZED
        )

    def test_users_see_and_use_plugin_vocabularies_only_after_approval(self):
        self.push([{"id": "S1", "name": "strain one"}])
        self.finish()
        table = MetadataTable.objects.create(name="table", sample_count=1, owner=self.user)
        self.assertNotIn(KEY, self.visible_keys(self.user))
        self.as_user(self.user)
        suggest = self.client.get(reverse("ccv:ontologysearch-suggest"), {"q": "strain", "type": KEY})
        self.assertEqual(suggest.data["count"], 0)
        with self.assertRaises(serializers.ValidationError):
            validate_vocabulary_key(KEY, self.user, table)

        self.assertEqual(self.approve().status_code, status.HTTP_200_OK)
        self.assertIn(KEY, self.visible_keys(self.user))
        self.as_user(self.user)
        self.assertEqual(
            self.client.get(reverse("ccv:ontologysearch-suggest"), {"q": "strain", "type": KEY}).data["count"], 1
        )
        self.assertEqual(validate_vocabulary_key(KEY, self.user, table), KEY)

    def test_staff_see_pending_vocabularies_when_asked(self):
        self.as_user(self.staff)
        url = reverse("ccv:vocabulary-list")
        self.assertNotIn(KEY, [row["key"] for row in self.client.get(url, {"provider": "plugin"}).data["results"]])
        pending = self.client.get(url, {"provider": "plugin", "include_unapproved": "true"}).data["results"]
        self.assertEqual(
            [(row["key"], row["approved"], row["plugin_name"]) for row in pending], [(KEY, False, "strain-db")]
        )

    def test_only_staff_approve_and_only_plugin_vocabularies(self):
        self.assertEqual(self.approve(user=self.user).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.approve(False).status_code, status.HTTP_200_OK)
        Vocabulary.objects.create(
            key="custom.mine", label="Mine", provider=Vocabulary.PROVIDER_CUSTOM, storage=Vocabulary.STORAGE_TERMS
        )
        self.as_user(self.staff)
        response = self.client.post(
            reverse("ccv:vocabulary-approve", args=["custom.mine"]), {"approved": False}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_vocabularies_of_an_inactive_plugin_are_hidden(self):
        self.approve()
        self.assertIn(KEY, self.visible_keys(self.user))
        Plugin.objects.filter(pk=self.plugin.pk).update(is_active=False)
        self.assertNotIn(KEY, self.visible_keys(self.user))

    def test_plugin_vocabularies_are_not_edited_by_users(self):
        self.as_user(self.staff)
        response = self.client.patch(reverse("ccv:vocabulary-detail", args=[KEY]), {"label": "x"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_deleting_the_plugin_removes_its_vocabularies(self):
        self.push([{"id": "S1", "name": "strain one"}])
        self.plugin.delete()
        self.assertFalse(Vocabulary.objects.filter(key=KEY).exists())
