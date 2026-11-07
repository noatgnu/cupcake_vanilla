"""Custom vocabularies: who manages them, importing their terms and editing them, and their use in job tables."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from ccc.models import AsyncTaskStatus, LabGroup, LabGroupPermission
from ccm.models import Instrument, InstrumentJob
from ccv.models import MetadataColumn, MetadataTable, Vocabulary, VocabularyTerm
from ccv.serializers import validate_vocabulary_key
from ccv.tasks.vocabulary_tasks import import_vocabulary_task
from tests.factories import UserFactory

MEDIA = tempfile.mkdtemp()

OBO = """format-version: 1.2
data-version: releases/2026-11-01

[Term]
id: LAB:0001
name: wild type strain
def: "Unmodified reference strain." []
synonym: "WT" EXACT []

[Term]
id: LAB:0002
name: knockout strain
is_a: LAB:0001 ! wild type strain

[Term]
id: LAB:0003
name: retired strain
is_obsolete: true
"""

OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:owl="http://www.w3.org/2002/07/owl#"
  xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#" xmlns:oboInOwl="http://www.geneontology.org/formats/oboInOwl#">
  <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/lab.owl"/>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/LAB_0001">
    <rdfs:label>wild type strain</rdfs:label>
    <oboInOwl:hasExactSynonym>WT</oboInOwl:hasExactSynonym>
  </owl:Class>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/LAB_0002">
    <rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/LAB_0001"/>
    <rdfs:label>knockout strain</rdfs:label>
  </owl:Class>
</rdf:RDF>
"""

CSV = "code,strain,notes,aka\nS1,Strain one,First,one|uno\nS2,Strain two,,\n,No code,,\n"


def run_now(**kwargs):
    """Run the import task in the test instead of queueing it."""
    import_vocabulary_task(**kwargs)


@override_settings(MEDIA_ROOT=MEDIA)
class CustomVocabularyTestCase(APITestCase):
    def setUp(self):
        self.staff = UserFactory.create_user(username="staff", is_staff=True)
        self.manager = UserFactory.create_user(username="manager")
        self.member = UserFactory.create_user(username="member")
        self.outsider = UserFactory.create_user(username="outsider")
        self.lab = LabGroup.objects.create(name="Strain lab", creator=self.staff)
        self.lab.members.add(self.manager, self.member)
        LabGroupPermission.objects.create(user=self.manager, lab_group=self.lab, can_view=True, can_manage=True)

    def as_user(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    def create(self, user, **body):
        return self.as_user(user).post(reverse("ccv:vocabulary-list"), body, format="json")

    def lab_vocabulary(self):
        response = self.create(self.manager, label="Lab strains", lab_group=self.lab.pk)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return Vocabulary.objects.get(key=response.data["key"])

    def import_file(self, user, vocabulary, name, content, **fields):
        url = reverse("ccv:vocabulary-import-terms", kwargs={"key": vocabulary.key})
        body = {"file": SimpleUploadedFile(name, content.encode()), **fields}
        with patch("ccv.viewsets.import_vocabulary_task.delay", side_effect=run_now):
            return self.as_user(user).post(url, body, format="multipart")


class ManagementTests(CustomVocabularyTestCase):
    def test_lab_group_managers_create_their_group_vocabularies(self):
        vocabulary = self.lab_vocabulary()
        self.assertEqual(vocabulary.key, "custom.lab_strains")
        self.assertEqual(vocabulary.provider, Vocabulary.PROVIDER_CUSTOM)
        self.assertEqual(vocabulary.owner, self.manager)
        detail = reverse("ccv:vocabulary-detail", kwargs={"key": vocabulary.key})
        self.assertTrue(self.as_user(self.manager).get(detail).data["can_manage"])
        self.assertFalse(self.as_user(self.member).get(detail).data["can_manage"])
        self.assertEqual(self.create(self.member, label="Other", lab_group=self.lab.pk).status_code, 403)

    def test_global_vocabularies_are_created_by_staff_only(self):
        self.assertEqual(self.create(self.manager, label="Everyone").status_code, status.HTTP_403_FORBIDDEN)
        response = self.create(self.staff, label="Everyone", slug="shared_units")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["key"], "custom.shared_units")

    def test_keys_are_unique(self):
        self.lab_vocabulary()
        response = self.create(self.manager, label="Lab strains", lab_group=self.lab.pk)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_managers_change_details_and_availability(self):
        vocabulary = self.lab_vocabulary()
        url = reverse("ccv:vocabulary-detail", kwargs={"key": vocabulary.key})
        response = self.as_user(self.manager).patch(url, {"label": "Strains", "status": "unavailable"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "unavailable")
        self.assertEqual(self.as_user(self.member).patch(url, {"label": "x"}, format="json").status_code, 403)

    def test_built_in_vocabularies_are_not_changed_here(self):
        url = reverse("ccv:vocabulary-detail", kwargs={"key": "mondo"})
        self.assertEqual(self.as_user(self.staff).patch(url, {"label": "x"}, format="json").status_code, 404)

    def test_vocabularies_in_use_are_not_deleted(self):
        vocabulary = self.lab_vocabulary()
        url = reverse("ccv:vocabulary-detail", kwargs={"key": vocabulary.key})
        table = MetadataTable.objects.create(name="Table", sample_count=1, owner=self.manager)
        column = MetadataColumn.objects.create(
            metadata_table=table, name="characteristics[strain]", ontology_type=vocabulary.key
        )
        response = self.as_user(self.manager).delete(url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["columns"], 1)
        column.delete()
        self.assertEqual(self.as_user(self.manager).delete(url).status_code, status.HTTP_204_NO_CONTENT)


class ImportTests(CustomVocabularyTestCase):
    def test_obo_files_are_imported_with_parents_obsolete_terms_and_version(self):
        vocabulary = self.lab_vocabulary()
        response = self.import_file(self.manager, vocabulary, "strains.obo", OBO)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        terms = {term.external_id: term for term in vocabulary.terms.all()}
        self.assertEqual(set(terms), {"LAB:0001", "LAB:0002", "LAB:0003"})
        self.assertEqual(terms["LAB:0001"].synonyms, "WT")
        self.assertEqual(terms["LAB:0001"].description, "Unmodified reference strain.")
        self.assertEqual(terms["LAB:0002"].data["parents"], ["LAB:0001"])
        self.assertTrue(terms["LAB:0003"].obsolete)
        vocabulary.refresh_from_db()
        self.assertEqual(vocabulary.term_count, 3)
        self.assertEqual(vocabulary.status, Vocabulary.STATUS_ACTIVE)
        self.assertEqual(vocabulary.source_version.version, "releases/2026-11-01")
        task = AsyncTaskStatus.objects.get(id=response.data["task_id"])
        self.assertEqual(task.status, "SUCCESS")
        self.assertFalse(any((Path(MEDIA) / "vocabulary_imports").glob("*")))

    def test_owl_files_are_imported(self):
        vocabulary = self.lab_vocabulary()
        self.import_file(self.manager, vocabulary, "strains.owl", OWL)
        self.assertEqual(
            sorted(vocabulary.terms.values_list("name", flat=True)), ["knockout strain", "wild type strain"]
        )

    def test_csv_columns_are_mapped_and_replace_removes_missing_terms(self):
        vocabulary = self.lab_vocabulary()
        VocabularyTerm.objects.create(
            vocabulary=vocabulary, external_id="OLD", name="Old", fetched_at="2026-01-01T00:00Z"
        )
        mapping = {
            "name_column": "strain",
            "id_column": "code",
            "description_column": "notes",
            "synonyms_column": "aka",
            "synonym_separator": "|",
        }
        self.import_file(self.manager, vocabulary, "strains.csv", CSV, mode="replace", **mapping)
        terms = {term.external_id: term for term in vocabulary.terms.all()}
        self.assertEqual(set(terms), {"S1", "S2"})
        self.assertEqual(terms["S1"].synonyms, "one;uno")
        self.assertEqual(terms["S1"].description, "First")

    def test_csv_needs_a_name_column(self):
        vocabulary = self.lab_vocabulary()
        response = self.import_file(self.manager, vocabulary, "strains.csv", CSV)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unreadable_files_are_reported_on_the_vocabulary_and_task(self):
        vocabulary = self.lab_vocabulary()
        response = self.import_file(self.manager, vocabulary, "strains.csv", CSV, name_column="missing")
        vocabulary.refresh_from_db()
        self.assertIn("missing", vocabulary.last_error)
        self.assertEqual(vocabulary.status, Vocabulary.STATUS_ACTIVE)
        self.assertEqual(AsyncTaskStatus.objects.get(id=response.data["task_id"]).status, "FAILURE")

    def test_only_managers_import(self):
        vocabulary = self.lab_vocabulary()
        self.assertEqual(self.import_file(self.member, vocabulary, "strains.obo", OBO).status_code, 403)

    def test_csv_files_are_previewed(self):
        vocabulary = self.lab_vocabulary()
        url = reverse("ccv:vocabulary-import-preview", kwargs={"key": vocabulary.key})
        body = {"file": SimpleUploadedFile("strains.csv", CSV.encode())}
        response = self.as_user(self.manager).post(url, body, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["columns"], ["code", "strain", "notes", "aka"])
        self.assertEqual(response.data["rows"][0], ["S1", "Strain one", "First", "one|uno"])


class TermTests(CustomVocabularyTestCase):
    def setUp(self):
        super().setUp()
        self.vocabulary = self.lab_vocabulary()
        self.import_file(self.manager, self.vocabulary, "strains.obo", OBO)

    def names(self, user, **params):
        response = self.as_user(user).get(
            reverse("ccv:vocabularyterm-list"), {"vocabulary": self.vocabulary.key, "limit": 10, **params}
        )
        return [row["name"] for row in response.data["results"]]

    def test_members_browse_and_search_terms_and_outsiders_see_none(self):
        self.assertEqual(self.names(self.member), ["knockout strain", "wild type strain"])
        self.assertEqual(self.names(self.member, search="WT"), ["wild type strain"])
        self.assertIn("retired strain", self.names(self.member, include_obsolete="true"))
        self.assertEqual(self.names(self.outsider), [])

    def test_managers_add_change_and_remove_terms(self):
        client = self.as_user(self.manager)
        body = {
            "vocabulary": self.vocabulary.key,
            "external_id": "LAB:0004",
            "name": "reporter strain",
            "synonyms": ["GFP"],
        }
        created = client.post(reverse("ccv:vocabularyterm-list"), body, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        self.assertEqual(created.data["synonyms"], ["GFP"])
        self.assertEqual(client.post(reverse("ccv:vocabularyterm-list"), body, format="json").status_code, 400)
        url = reverse("ccv:vocabularyterm-detail", kwargs={"pk": created.data["id"]})
        self.assertEqual(client.patch(url, {"name": "GFP reporter strain"}, format="json").status_code, 200)
        self.assertEqual(client.delete(url).status_code, status.HTTP_204_NO_CONTENT)
        self.vocabulary.refresh_from_db()
        self.assertEqual(self.vocabulary.term_count, 3)

    def test_members_cannot_change_terms(self):
        term = self.vocabulary.terms.get(external_id="LAB:0001")
        url = reverse("ccv:vocabularyterm-detail", kwargs={"pk": term.pk})
        self.assertEqual(self.as_user(self.member).patch(url, {"name": "x"}, format="json").status_code, 403)
        self.assertEqual(self.as_user(self.outsider).get(url).status_code, status.HTTP_404_NOT_FOUND)


class JobTableTests(CustomVocabularyTestCase):
    def setUp(self):
        super().setUp()
        self.vocabulary = self.lab_vocabulary()
        self.import_file(self.manager, self.vocabulary, "strains.obo", OBO)
        self.submitter = self.outsider
        self.table = MetadataTable.objects.create(name="Job table", sample_count=2, owner=self.submitter)
        instrument = Instrument.objects.create(instrument_name="LC-MS", user=self.staff)
        InstrumentJob.objects.create(
            instrument=instrument,
            user=self.submitter,
            job_name="Strain run",
            job_type="analysis",
            lab_group=self.lab,
            metadata_table=self.table,
        )

    def test_submitters_use_the_facility_vocabularies_in_their_job_table(self):
        url = reverse("ccv:vocabulary-list")
        self.as_user(self.submitter)
        keys = [
            row["key"] for row in self.client.get(url, {"metadata_table": self.table.pk, "limit": 100}).data["results"]
        ]
        self.assertIn(self.vocabulary.key, keys)
        keys = [row["key"] for row in self.client.get(url, {"limit": 100}).data["results"]]
        self.assertNotIn(self.vocabulary.key, keys)

    def test_submitters_search_and_validate_with_the_facility_vocabularies_only_in_the_job_table(self):
        suggest = reverse("ccv:ontologysearch-suggest")
        params = {"q": "strain", "type": self.vocabulary.key}
        self.as_user(self.submitter)
        self.assertEqual(self.client.get(suggest, {**params, "metadata_table": self.table.pk}).data["count"], 2)
        self.assertEqual(self.client.get(suggest, params).data["count"], 0)
        self.assertEqual(validate_vocabulary_key(self.vocabulary.key, self.submitter, self.table), self.vocabulary.key)

    def test_users_who_cannot_open_the_table_gain_nothing(self):
        stranger = UserFactory.create_user(username="stranger")
        keys = [
            row["key"]
            for row in self.as_user(stranger)
            .get(reverse("ccv:vocabulary-list"), {"metadata_table": self.table.pk, "limit": 100})
            .data["results"]
        ]
        self.assertNotIn(self.vocabulary.key, keys)
