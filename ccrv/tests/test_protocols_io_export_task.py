"""Tests for queuing and running protocols.io exports."""

from contextlib import nullcontext
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from choux import APIError, DraftValidationError
from choux.draft import Issue
from rest_framework.test import APIClient

from ccc.models import AsyncTaskStatus
from ccrv.models import ProtocolModel, ProtocolsIOAccount
from ccrv.protocols_io import ExportResult
from ccrv.protocols_io.accounts import ProtocolsIOAccountMissing
from ccrv.protocols_io.exporter import protocol_reference
from ccrv.tasks.protocols_io_tasks import export_protocol_to_protocols_io_task


class ProtocolReferenceTest(SimpleTestCase):
    def test_addresses_and_references(self):
        """Addresses and references."""
        cases = {
            "https://www.protocols.io/edit/cupcake-export-test-kqcbcvssp": "cupcake-export-test-kqcbcvssp",
            "https://www.protocols.io/view/cupcake-export-test-kqcbcvssp/v2": "cupcake-export-test-kqcbcvssp",
            "https://protocols.io/view/lysis-abc?step=3": "lysis-abc",
            "  cupcake-export-test-kqcbcvssp  ": "cupcake-export-test-kqcbcvssp",
            "340067": "340067",
            "https://example.org/view/other": "https://example.org/view/other",
            "": "",
        }
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertEqual(protocol_reference(text), expected)


class ExportEndpointTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("export-endpoint-user", password="x")
        self.protocol = ProtocolModel.objects.create(protocol_title="Lysis", owner=self.user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("ccrv:protocolmodel-export-to-protocols-io", args=[self.protocol.pk])

    def connect(self):
        """Give the user a protocols.io account."""
        ProtocolsIOAccount.objects.create(user=self.user, access_token="personal-token", username="toan-phung")

    def test_queues_an_export_with_the_target_uri(self):
        """Queues an export with the target uri."""
        self.connect()
        with patch.object(export_protocol_to_protocols_io_task, "delay", return_value=Mock(id="job-1")) as delay:
            response = self.client.post(
                self.url, {"target": "https://www.protocols.io/edit/lysis-abc", "scaling_factor": 2}, format="json"
            )
        self.assertEqual(response.status_code, 202)
        task = AsyncTaskStatus.objects.get(id=response.data["task_id"])
        self.assertEqual((task.task_type, task.user, task.rq_job_id), ("EXPORT_PROTOCOLS_IO", self.user, "job-1"))
        self.assertEqual(
            task.parameters, {"protocol_id": self.protocol.pk, "target": "lysis-abc", "scaling_factor": 2.0}
        )
        delay.assert_called_once_with(self.protocol.pk, self.user.pk, "lysis-abc", str(task.id), 2.0)

    def test_needs_a_connected_account(self):
        """Needs a connected account."""
        with patch.object(export_protocol_to_protocols_io_task, "delay") as delay:
            response = self.client.post(self.url, {"target": "lysis-abc"}, format="json")
        self.assertEqual((response.status_code, response.data["error"]), (400, "Connect a protocols.io account first"))
        delay.assert_not_called()

    def test_needs_a_target_and_a_numeric_scaling_factor(self):
        """Needs a target and a numeric scaling factor."""
        self.connect()
        with patch.object(export_protocol_to_protocols_io_task, "delay") as delay:
            missing = self.client.post(self.url, {"target": "  "}, format="json")
            bad_factor = self.client.post(self.url, {"target": "lysis-abc", "scaling_factor": "lots"}, format="json")
        self.assertEqual((missing.status_code, bad_factor.status_code), (400, 400))
        delay.assert_not_called()
        self.assertFalse(AsyncTaskStatus.objects.exists())

    def test_other_users_cannot_export_a_private_protocol(self):
        """Other users cannot export a private protocol."""
        other = get_user_model().objects.create_user("stranger", password="x")
        ProtocolsIOAccount.objects.create(user=other, access_token="their-token", username="stranger")
        client = APIClient()
        client.force_authenticate(user=other)
        with patch.object(export_protocol_to_protocols_io_task, "delay") as delay:
            response = client.post(self.url, {"target": "lysis-abc"}, format="json")
        self.assertIn(response.status_code, (403, 404))
        delay.assert_not_called()


class ExportTaskTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("export-task-user", password="x")
        self.protocol = ProtocolModel.objects.create(protocol_title="Lysis", owner=self.user)
        self.task = AsyncTaskStatus.objects.create(task_type="EXPORT_PROTOCOLS_IO", user=self.user)

    def run_task(self, **patches):
        """Run the export job synchronously with the given patches."""
        client = patches.pop("client", nullcontext(Mock()))
        with patch(
            "ccrv.tasks.protocols_io_tasks.client_for", **({"return_value": client} | patches.pop("client_for", {}))
        ):
            with patch("ccrv.tasks.protocols_io_tasks.export_protocol", **patches) as export:
                outcome = export_protocol_to_protocols_io_task(
                    self.protocol.pk, self.user.pk, "lysis-abc", str(self.task.id), 1.5
                )
        self.task.refresh_from_db()
        return outcome, export

    def test_success_stores_the_result(self):
        """Success stores the result."""
        result = ExportResult(
            protocol_uri="lysis-abc", protocol_url="https://p/lysis-abc", steps_saved=4, warnings=["note"]
        )

        def export(protocol, client, target, scaling_factor, progress):
            progress(3, 6, "Saving steps")
            return result

        outcome, mocked = self.run_task(side_effect=export)
        self.assertEqual(self.task.status, "SUCCESS")
        self.assertEqual(self.task.result["steps_saved"], 4)
        self.assertEqual(self.task.result["warnings"], ["note"])
        self.assertEqual(self.task.result["protocol_url"], "https://p/lysis-abc")
        self.assertTrue(outcome["success"])
        self.assertEqual(mocked.call_args.args[2], "lysis-abc")
        self.assertEqual(mocked.call_args.kwargs["scaling_factor"], 1.5)

    def test_validation_errors_are_reported(self):
        """Validation errors are reported."""
        error = DraftValidationError([Issue("steps[0].step.blocks", "must be a non-empty list")])
        outcome, _ = self.run_task(side_effect=error)
        self.assertEqual(self.task.status, "FAILURE")
        self.assertEqual(
            self.task.error_message,
            "Step content could not be converted: steps[0].step.blocks: must be a non-empty list",
        )
        self.assertFalse(outcome["success"])

    def test_protocols_io_errors_are_reported(self):
        """Protocols io errors are reported."""
        self.run_task(side_effect=APIError("protocol does not exist", http_status=404))
        self.assertEqual(
            (self.task.status, self.task.error_message),
            ("FAILURE", "protocols.io export failed: protocol does not exist"),
        )

    def test_missing_account_is_reported(self):
        """Missing account is reported."""
        self.run_task(client_for={"side_effect": ProtocolsIOAccountMissing("none")})
        self.assertEqual(
            (self.task.status, self.task.error_message), ("FAILURE", "Connect a protocols.io account before exporting")
        )

    def test_unexpected_errors_are_reported(self):
        """Unexpected errors are reported."""
        with self.assertLogs("ccrv.tasks.protocols_io_tasks", level="ERROR"):
            self.run_task(side_effect=RuntimeError("boom"))
        self.assertEqual((self.task.status, self.task.error_message), ("FAILURE", "protocols.io export failed: boom"))
