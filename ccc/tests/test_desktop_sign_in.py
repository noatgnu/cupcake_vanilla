"""Automatic sign-in for the desktop app and its signing key."""

import os
import stat
import tempfile

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from cupcake_vanilla.desktop_secret import load_secret_key

SIGN_IN = "/api/v1/auth/desktop-sign-in/"
SECRET = "launcher-secret-for-tests"


@override_settings(WAILS_LAUNCHER_SECRET=SECRET)
class DesktopSignInTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("bench-owner", "owner@test.com", "pw")

    def sign_in(self, username="bench-owner", secret=SECRET, remote_addr="127.0.0.1"):
        return self.client.post(
            SIGN_IN,
            {"username": username},
            content_type="application/json",
            headers={"X-Cupcake-Launcher": secret},
            REMOTE_ADDR=remote_addr,
        )

    def test_the_launcher_signs_in_the_chosen_account(self):
        response = self.sign_in()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user"]["username"], "bench-owner")
        self.assertTrue(body["access_token"] and body["refresh_token"])
        profile = self.client.get("/api/v1/auth/profile/", headers={"Authorization": f"Bearer {body['access_token']}"})
        self.assertEqual(profile.status_code, 200)

    def test_signing_in_over_ipv6_loopback_works(self):
        self.assertEqual(self.sign_in(remote_addr="::1").status_code, 200)

    def test_a_wrong_or_missing_secret_is_refused(self):
        self.assertEqual(self.sign_in(secret="guess").status_code, 403)
        self.assertEqual(self.sign_in(secret="").status_code, 403)

    def test_requests_from_other_computers_are_refused(self):
        self.assertEqual(self.sign_in(remote_addr="192.168.1.20").status_code, 403)

    def test_unknown_and_deactivated_accounts_are_not_signed_in(self):
        self.assertEqual(self.sign_in(username="nobody").status_code, 404)
        self.owner.is_active = False
        self.owner.save()
        self.assertEqual(self.sign_in().status_code, 404)

    def test_a_username_is_required(self):
        response = self.client.post(
            SIGN_IN, {}, content_type="application/json", headers={"X-Cupcake-Launcher": SECRET}
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(WAILS_LAUNCHER_SECRET="")
    def test_the_endpoint_does_not_exist_outside_the_desktop_app(self):
        self.assertEqual(self.sign_in(secret="").status_code, 404)


class DesktopSecretKeyTest(TestCase):
    def test_the_key_is_created_once_and_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "secret_key")
            first = load_secret_key(path)
            self.assertGreaterEqual(len(first), 64)
            self.assertEqual(load_secret_key(path), first)

    def test_the_key_file_is_readable_only_by_its_owner(self):
        if os.name == "nt":
            self.skipTest("Windows has no POSIX file modes")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "secret_key")
            load_secret_key(path)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_an_existing_key_is_read_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "secret_key")
            with open(path, "w") as handle:
                handle.write("kept-key\n")
            self.assertEqual(load_secret_key(path), "kept-key")
