"""Restarting the backend, rebooting and shutting down the appliance through its power manager."""

from unittest.mock import patch

from django.contrib.auth.models import User

from rest_framework.test import APIClient, APITestCase

POWER = "/api/v1/appliance/power/"
SEND = "ccc.viewsets.ApplianceViewSet._send_power_command"


class AppliancePowerTest(APITestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser("root-admin", "root@test.com", "pw")
        self.staff = User.objects.create_user("staff-admin", "staff@test.com", "pw", is_staff=True)
        self.regular = User.objects.create_user("bench-user", "bench@test.com", "pw")
        self.client = APIClient()

    def post_as(self, user, action):
        self.client.force_authenticate(user=user)
        return self.client.post(POWER, {"action": action}, format="json")

    def test_superusers_restart_the_backend_reboot_and_shut_down(self):
        for action in ("restart-backend", "reboot", "shutdown"):
            with patch(SEND, return_value={"ok": True, "output": "scheduled"}) as sent:
                response = self.post_as(self.superuser, action)
            self.assertEqual(response.status_code, 202, action)
            self.assertTrue(response.data["message"], action)
            sent.assert_called_once_with({"command": action})

    def test_staff_who_are_not_superusers_are_refused(self):
        with patch(SEND) as sent:
            response = self.post_as(self.staff, "reboot")
        self.assertEqual(response.status_code, 403)
        sent.assert_not_called()

    def test_regular_users_are_refused(self):
        with patch(SEND) as sent:
            response = self.post_as(self.regular, "shutdown")
        self.assertEqual(response.status_code, 403)
        sent.assert_not_called()

    def test_unknown_actions_are_rejected(self):
        with patch(SEND) as sent:
            response = self.post_as(self.superuser, "format-disk")
        self.assertEqual(response.status_code, 400)
        sent.assert_not_called()

    def test_a_missing_power_manager_is_reported(self):
        with patch(SEND, side_effect=OSError("no socket")):
            response = self.post_as(self.superuser, "reboot")
        self.assertEqual(response.status_code, 500)
        self.assertIn("power manager is not available", response.data["error"])

    def test_a_failed_action_is_reported(self):
        with patch(SEND, return_value={"ok": False, "error": "systemd-run failed"}):
            response = self.post_as(self.superuser, "shutdown")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["error"], "systemd-run failed")
