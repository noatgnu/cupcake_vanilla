"""TURN credentials in the form coturn's use-auth-secret mode checks."""

import base64
import hashlib
import hmac

from django.test import SimpleTestCase, override_settings

from ccmc.turn_credentials import client_host, generate_turn_credentials, get_ice_servers


@override_settings(
    COTURN_SECRET="test-secret", COTURN_HOST="turn.example.org", COTURN_PORT=3478, COTURN_TLS_PORT=None, COTURN_TTL=600
)
class TurnCredentialTests(SimpleTestCase):
    def test_the_password_is_the_base64_hmac_sha1_of_the_username(self):
        credentials = generate_turn_credentials("alice")
        expected = hmac.new(b"test-secret", credentials["username"].encode(), hashlib.sha1).digest()
        self.assertEqual(base64.b64decode(credentials["credential"]), expected)

    def test_the_username_carries_its_expiry_and_the_user(self):
        expiry, user = generate_turn_credentials("alice")["username"].split(":", 1)
        self.assertTrue(expiry.isdigit())
        self.assertEqual(user, "alice")

    def test_the_server_is_offered_over_udp_and_tcp(self):
        self.assertIn("turn:turn.example.org:3478", generate_turn_credentials("alice")["urls"])
        self.assertIn("turn:turn.example.org:3478?transport=tcp", generate_turn_credentials("alice")["urls"])

    def test_without_a_tls_port_no_turns_server_is_offered(self):
        self.assertFalse(any(url.startswith("turns:") for url in generate_turn_credentials("alice")["urls"]))

    @override_settings(COTURN_TLS_PORT=5349)
    def test_a_tls_port_adds_the_turns_server(self):
        self.assertIn("turns:turn.example.org:5349?transport=tcp", generate_turn_credentials("alice")["urls"])

    def test_a_configured_host_wins_over_the_request_host(self):
        urls = generate_turn_credentials("alice", request_host="appliance.example.ts.net")["urls"]
        self.assertTrue(all("turn.example.org" in url for url in urls))

    @override_settings(COTURN_HOST="")
    def test_without_a_configured_host_the_client_gets_the_host_it_reached(self):
        servers = get_ice_servers("alice", include_stun=False, request_host="appliance.example.ts.net")
        self.assertEqual(servers[0]["urls"][0], "turn:appliance.example.ts.net:3478")


class ClientHostTests(SimpleTestCase):
    def test_the_port_is_dropped(self):
        self.assertEqual(client_host("appliance.example.ts.net:8443"), "appliance.example.ts.net")
        self.assertEqual(client_host("192.0.2.10"), "192.0.2.10")

    def test_ipv6_addresses_keep_their_brackets(self):
        self.assertEqual(client_host("[fd7a:115c::1]:8443"), "[fd7a:115c::1]")

    def test_a_missing_header_gives_no_host(self):
        self.assertEqual(client_host(""), "")
