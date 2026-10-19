"""Tests for users' own protocols.io accounts."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from choux import APIError, ProtocolsIO
from rest_framework.test import APIClient

from ccc.encryption import decrypt_secret
from ccrv.models import ProtocolsIOAccount
from ccrv.protocols_io.accounts import (
    ProtocolsIOAccountMissing,
    client_for,
    connect_account,
    disconnect_account,
    rate_limiter_for,
)

PROFILE = {"username": "toan-phung", "name": "Toan K Phung"}


def stored_token(account):
    """Return the raw database value of an account's token."""
    table = connection.ops.quote_name(ProtocolsIOAccount._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT access_token FROM {table} WHERE id = %s", [account.pk])
        return cursor.fetchone()[0]


class AccountServiceTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("account-user", password="x")

    def test_connect_checks_the_token_and_stores_it_encrypted(self):
        """Connect checks the token and stores it encrypted."""
        with patch.object(ProtocolsIO, "get_profile", return_value=PROFILE) as profile:
            account = connect_account(self.user, "  personal-token  ")
        profile.assert_called_once()
        self.assertEqual((account.username, account.name), ("toan-phung", "Toan K Phung"))
        self.assertNotIn("personal-token", stored_token(account))
        self.assertEqual(decrypt_secret(stored_token(account)), "personal-token")

    def test_connect_again_replaces_the_account(self):
        """Connect again replaces the account."""
        with patch.object(ProtocolsIO, "get_profile", return_value=PROFILE):
            connect_account(self.user, "first")
        with patch.object(ProtocolsIO, "get_profile", return_value={"username": "other", "name": ""}):
            connect_account(self.user, "second")
        account = ProtocolsIOAccount.objects.get(user=self.user)
        self.assertEqual((account.username, account.access_token), ("other", "second"))

    def test_rejected_tokens_are_not_saved(self):
        """Rejected tokens are not saved."""
        with patch.object(ProtocolsIO, "get_profile", side_effect=APIError("bad token", http_status=401)):
            with self.assertRaises(APIError):
                connect_account(self.user, "wrong")
        self.assertFalse(ProtocolsIOAccount.objects.exists())

    def test_blank_tokens_are_refused(self):
        """Blank tokens are refused."""
        with self.assertRaises(ValueError):
            connect_account(self.user, "   ")

    def test_client_acts_with_the_users_token_and_records_use(self):
        """Client acts with the users token and records use."""
        with patch.object(ProtocolsIO, "get_profile", return_value=PROFILE):
            connect_account(self.user, "personal-token")
        with client_for(self.user) as client:
            self.assertEqual(client._auth, {"Authorization": "Bearer personal-token"})
            self.assertIs(client.rate_limiter, rate_limiter_for(self.user.pk))
        self.assertIsNotNone(ProtocolsIOAccount.objects.get(user=self.user).last_used_at)

    def test_client_needs_a_connected_account(self):
        """Client needs a connected account."""
        with self.assertRaises(ProtocolsIOAccountMissing):
            client_for(self.user)

    def test_disconnect(self):
        """Disconnect."""
        with patch.object(ProtocolsIO, "get_profile", return_value=PROFILE):
            connect_account(self.user, "personal-token")
        self.assertTrue(disconnect_account(self.user))
        self.assertFalse(disconnect_account(self.user))

    def test_each_user_has_their_own_rate_limiter(self):
        """Each user has their own rate limiter."""
        other = get_user_model().objects.create_user("other-user", password="x")
        self.assertIsNot(rate_limiter_for(self.user.pk), rate_limiter_for(other.pk))


class AccountEndpointTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("endpoint-user", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("ccrv:protocolsioaccount-list")

    def test_status_before_connecting(self):
        """Status before connecting."""
        self.assertEqual(self.client.get(self.url).data, {"connected": False})

    def test_connect_shows_the_account_but_never_the_token(self):
        """Connect shows the account but never the token."""
        with patch.object(ProtocolsIO, "get_profile", return_value=PROFILE):
            created = self.client.post(self.url, {"access_token": "personal-token"}, format="json")
        status = self.client.get(self.url)
        self.assertEqual(created.status_code, 201)
        for response in (created, status):
            self.assertTrue(response.data["connected"])
            self.assertEqual(response.data["username"], "toan-phung")
            self.assertNotIn("personal-token", response.content.decode())
            self.assertNotIn("access_token", response.data)

    def test_rejected_token(self):
        """Rejected token."""
        with patch.object(ProtocolsIO, "get_profile", side_effect=APIError("bad token", http_status=401)):
            response = self.client.post(self.url, {"access_token": "wrong"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "protocols.io did not accept this token")

    def test_missing_token(self):
        """Missing token."""
        self.assertEqual(self.client.post(self.url, {}, format="json").status_code, 400)

    def test_disconnect(self):
        """Disconnect."""
        with patch.object(ProtocolsIO, "get_profile", return_value=PROFILE):
            self.client.post(self.url, {"access_token": "personal-token"}, format="json")
        response = self.client.delete(reverse("ccrv:protocolsioaccount-disconnect"))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get(self.url).data, {"connected": False})

    def test_requires_login(self):
        """Requires login."""
        self.assertIn(APIClient().get(self.url).status_code, (401, 403))

    def test_accounts_are_per_user(self):
        """Accounts are per user."""
        with patch.object(ProtocolsIO, "get_profile", return_value=PROFILE):
            self.client.post(self.url, {"access_token": "personal-token"}, format="json")
        other = APIClient()
        other.force_authenticate(user=get_user_model().objects.create_user("someone-else", password="x"))
        self.assertEqual(other.get(self.url).data, {"connected": False})
