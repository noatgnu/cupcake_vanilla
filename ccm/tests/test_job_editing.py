"""Who may edit an instrument job's details after it is submitted."""

from django.contrib.auth.models import User

from rest_framework.test import APITestCase

from ccc.models import LabGroup, LabGroupPermission
from ccm.models import InstrumentJob
from ccv.models import MetadataTable


class JobEditingTests(APITestCase):
    def setUp(self):
        self.submitter = User.objects.create_user("submitter", password="pw")
        self.member = User.objects.create_user("core-member", password="pw")
        self.outsider = User.objects.create_user("outsider", password="pw")
        self.site_staff = User.objects.create_user("site-staff", password="pw", is_staff=True)
        self.core = LabGroup.objects.create(name="Proteomics core", creator=self.submitter)
        self.core.members.add(self.submitter, self.member)
        table = MetadataTable.objects.create(name="Samples", owner=self.submitter, sample_count=2)
        self.job = InstrumentJob.objects.create(
            user=self.submitter,
            job_name="HEp-3 dormancy",
            lab_group=self.core,
            metadata_table=table,
            status="submitted",
        )

    def edit(self, user):
        self.client.force_authenticate(user)
        return self.client.patch(f"/api/v1/instrument-jobs/{self.job.id}/", {"method": "label free"}, format="json")

    def test_a_submitter_who_runs_the_groups_jobs_can_edit_after_submission(self):
        self.assertEqual(self.edit(self.submitter).status_code, 200)

    def test_the_groups_members_can_edit_when_no_staff_are_assigned(self):
        self.assertEqual(self.edit(self.member).status_code, 200)

    def test_only_the_assigned_staff_can_edit_once_staff_are_assigned(self):
        LabGroupPermission.objects.create(lab_group=self.core, user=self.member, can_process_jobs=True)
        self.job.staff.add(self.member)
        self.assertEqual(self.edit(self.submitter).status_code, 403)
        response = self.edit(self.member)
        self.assertEqual(response.status_code, 200, response.data)

    def test_people_outside_the_job_cannot_edit_it(self):
        self.assertIn(self.edit(self.outsider).status_code, (403, 404))

    def test_site_staff_can_edit_and_are_told_so(self):
        self.assertEqual(self.edit(self.site_staff).status_code, 200)
        job = self.client.get(f"/api/v1/instrument-jobs/{self.job.id}/").data
        self.assertTrue(job["can_edit"])
        self.assertTrue(job["can_edit_staff_only_columns"])

    def test_the_app_is_told_who_can_edit(self):
        self.client.force_authenticate(self.submitter)
        job = self.client.get(f"/api/v1/instrument-jobs/{self.job.id}/").data
        self.assertTrue(job["can_edit"])
        self.assertTrue(job["can_edit_staff_only_columns"])
