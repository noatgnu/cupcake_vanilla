"""The appliance's remote access status: Tailscale and the Cloudflare tunnel, read from their commands."""

import datetime
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import override_settings

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from rest_framework import status
from rest_framework.test import APITestCase

from ccc.remote_access import cloudflare_status, tailscale_status

URL = "/api/v1/appliance/remote-access-status/"

RUNNING = {
    "BackendState": "Running",
    "Self": {"DNSName": "cupcake.tail1e420d.ts.net.", "TailscaleIPs": ["100.66.187.101", "fd7a::1"], "Online": True},
    "Health": [],
}


def completed(stdout="", stderr=""):
    """A finished command with the given output."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def installed(*names):
    """A shutil.which that finds only the given commands."""
    return lambda name: f"/usr/bin/{name}" if name in names else None


def systemctl(enabled="enabled", active="active"):
    """A subprocess.run answering systemctl is-enabled and is-active."""

    def run(command, **kwargs):
        return completed({"is-enabled": enabled, "is-active": active}[command[1]] + "\n")

    return run


def certificate_file(directory, name, expires):
    """A self-signed certificate for name, valid until expires, written as PEM into directory."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(expires - datetime.timedelta(days=90))
        .not_valid_after(expires)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    path = Path(directory) / "tailscale.crt"
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return path


def ready(connections, code=200):
    """A response of the tunnel's ready endpoint."""
    response = MagicMock(status_code=code)
    response.json.return_value = {"status": code, "readyConnections": connections}
    return response


@patch("ccc.remote_access.shutil.which", installed("tailscale"))
class TailscaleStatusTests(APITestCase):
    def status(self, report=None, stdout=None, stderr=""):
        output = json.dumps(report) if stdout is None else stdout
        with patch("ccc.remote_access.subprocess.run", return_value=completed(output, stderr)):
            return tailscale_status()

    def test_a_connected_appliance_reports_its_name_and_addresses(self):
        found = self.status(RUNNING)
        self.assertTrue(found["configured"] and found["connected"] and found["online"])
        self.assertEqual(found["dns_name"], "cupcake.tail1e420d.ts.net")
        self.assertEqual(found["addresses"], ["100.66.187.101", "fd7a::1"])

    def test_an_appliance_that_never_logged_in_is_not_set_up(self):
        found = self.status({"BackendState": "NeedsLogin", "Self": {}})
        self.assertEqual((found["installed"], found["configured"], found["connected"]), (True, False, False))

    def test_a_stopped_tailscale_is_set_up_but_not_connected(self):
        found = self.status({**RUNNING, "BackendState": "Stopped"})
        self.assertEqual((found["configured"], found["connected"], found["state"]), (True, False, "Stopped"))

    def test_a_tailnet_that_issues_certificates_offers_https(self):
        self.assertTrue(self.status({**RUNNING, "CertDomains": ["cupcake.tail1e420d.ts.net"]})["https_available"])
        self.assertFalse(self.status(RUNNING)["https_available"])

    def test_the_certificate_of_the_tailscale_name_is_reported(self):
        expires = datetime.datetime(2027, 2, 1, tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            path = certificate_file(directory, "cupcake.tail1e420d.ts.net", expires)
            with override_settings(TAILSCALE_CERT_FILE=str(path)):
                found = self.status(RUNNING)
        self.assertEqual(
            found["certificate"], {"name": "cupcake.tail1e420d.ts.net", "expires_at": "2027-02-01T00:00:00+00:00"}
        )

    @override_settings(TAILSCALE_CERT_FILE="/nonexistent/tailscale.crt")
    def test_without_a_certificate_none_is_reported(self):
        self.assertIsNone(self.status(RUNNING)["certificate"])

    def test_health_warnings_are_reported(self):
        self.assertEqual(self.status({**RUNNING, "Health": ["no DERP home"]})["health"], ["no DERP home"])

    def test_a_tailscale_that_does_not_answer_reports_the_error(self):
        found = self.status(stdout="", stderr="failed to connect to local tailscaled")
        self.assertEqual(found["error"], "failed to connect to local tailscaled")
        self.assertFalse(found["configured"])

    def test_a_command_that_hangs_is_given_up(self):
        with patch("ccc.remote_access.subprocess.run", side_effect=subprocess.TimeoutExpired("tailscale", 5)):
            self.assertEqual(tailscale_status()["error"], "tailscale did not answer")

    def test_without_tailscale_nothing_is_run(self):
        with patch("ccc.remote_access.shutil.which", installed()), patch("ccc.remote_access.subprocess.run") as run:
            self.assertFalse(tailscale_status()["installed"])
        run.assert_not_called()


@patch("ccc.remote_access.shutil.which", installed("cloudflared"))
class CloudflareStatusTests(APITestCase):
    def test_a_connected_tunnel_reports_its_connections(self):
        with patch("ccc.remote_access.subprocess.run", systemctl()), patch(
            "ccc.remote_access.requests.get", return_value=ready(4)
        ) as get:
            found = cloudflare_status()
        self.assertEqual(get.call_args.args[0], "http://127.0.0.1:20241/ready")
        self.assertEqual(
            (found["configured"], found["active"], found["connected"], found["connections"]), (True, True, True, 4)
        )

    def test_a_running_tunnel_without_connections_is_not_connected(self):
        with patch("ccc.remote_access.subprocess.run", systemctl()), patch(
            "ccc.remote_access.requests.get", return_value=ready(0, 503)
        ):
            found = cloudflare_status()
        self.assertEqual((found["active"], found["connected"], found["connections"]), (True, False, 0))

    def test_a_tunnel_that_is_not_set_up_is_not_asked(self):
        with patch("ccc.remote_access.subprocess.run", systemctl("disabled", "inactive")), patch(
            "ccc.remote_access.requests.get"
        ) as get:
            found = cloudflare_status()
        self.assertEqual((found["installed"], found["configured"], found["active"]), (True, False, False))
        get.assert_not_called()

    def test_an_unreachable_ready_endpoint_is_reported(self):
        with patch("ccc.remote_access.subprocess.run", systemctl()), patch(
            "ccc.remote_access.requests.get", side_effect=requests.ConnectionError("refused")
        ):
            found = cloudflare_status()
        self.assertTrue(found["error"].startswith("Tunnel state unavailable"))
        self.assertFalse(found["connected"])


@patch("ccc.remote_access.shutil.which", installed())
class RemoteAccessStatusEndpointTests(APITestCase):
    def test_staff_see_both_services(self):
        self.client.force_authenticate(User.objects.create_user("staff", is_staff=True))
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data), {"tailscale", "cloudflare"})
        self.assertFalse(response.data["tailscale"]["installed"])
        self.assertFalse(response.data["cloudflare"]["installed"])

    def test_other_users_are_refused(self):
        self.client.force_authenticate(User.objects.create_user("user"))
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_403_FORBIDDEN)
