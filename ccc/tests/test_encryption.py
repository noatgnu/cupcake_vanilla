"""Tests for encrypted storage of secrets."""

import importlib
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings

from cryptography.fernet import InvalidToken

from ccc.encryption import decrypt_secret, encrypt_secret, is_encrypted
from ccc.models import UserOrcidProfile

encrypt_orcid_tokens = importlib.import_module("ccc.migrations.0021_encrypt_orcid_tokens")


def stored_value(model, pk, column):
    """Return the raw database value of one column."""
    table = connection.ops.quote_name(model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {connection.ops.quote_name(column)} FROM {table} WHERE id = %s", [pk])
        return cursor.fetchone()[0]


@override_settings(SECRET_KEY="current-secret", SECRET_KEY_FALLBACKS=[])
class SecretCipherTest(SimpleTestCase):
    def test_round_trip(self):
        """Round trip."""
        encrypted = encrypt_secret("token-123")
        self.assertNotIn("token-123", encrypted)
        self.assertEqual(decrypt_secret(encrypted), "token-123")

    def test_each_encryption_is_different(self):
        """Each encryption is different."""
        self.assertNotEqual(encrypt_secret("token-123"), encrypt_secret("token-123"))

    def test_rotated_secret_key_still_decrypts_through_fallbacks(self):
        """Rotated secret key still decrypts through fallbacks."""
        encrypted = encrypt_secret("token-123")
        with override_settings(SECRET_KEY="new-secret", SECRET_KEY_FALLBACKS=["current-secret"]):
            self.assertEqual(decrypt_secret(encrypted), "token-123")
        with override_settings(SECRET_KEY="new-secret", SECRET_KEY_FALLBACKS=[]):
            with self.assertRaises(InvalidToken):
                decrypt_secret(encrypted)

    def test_is_encrypted(self):
        """Is encrypted."""
        self.assertTrue(is_encrypted(encrypt_secret("x")))
        self.assertFalse(is_encrypted("plain-token"))
        self.assertFalse(is_encrypted("töken"))


@override_settings(SECRET_KEY="current-secret", SECRET_KEY_FALLBACKS=[])
class EncryptedTextFieldTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("orcid-user", password="x")

    def test_values_are_stored_encrypted_and_read_back_plain(self):
        """Values are stored encrypted and read back plain."""
        profile = UserOrcidProfile.objects.create(
            user=self.user, orcid_id="0000-0002-1825-0097", access_token="orcid-access", refresh_token="orcid-refresh"
        )
        raw = stored_value(UserOrcidProfile, profile.pk, "access_token")
        self.assertNotIn("orcid-access", raw)
        self.assertEqual(decrypt_secret(raw), "orcid-access")
        profile.refresh_from_db()
        self.assertEqual((profile.access_token, profile.refresh_token), ("orcid-access", "orcid-refresh"))

    def test_empty_values_stay_empty(self):
        """Empty values stay empty."""
        profile = UserOrcidProfile.objects.create(user=self.user, orcid_id="0000-0002-1825-0098", access_token="")
        self.assertEqual(stored_value(UserOrcidProfile, profile.pk, "access_token"), "")
        self.assertIsNone(stored_value(UserOrcidProfile, profile.pk, "refresh_token"))

    def test_saving_after_rotation_reencrypts_with_the_new_key(self):
        """Saving after rotation reencrypts with the new key."""
        profile = UserOrcidProfile.objects.create(
            user=self.user, orcid_id="0000-0002-1825-0099", access_token="orcid-access"
        )
        with override_settings(SECRET_KEY="new-secret", SECRET_KEY_FALLBACKS=["current-secret"]):
            profile = UserOrcidProfile.objects.get(pk=profile.pk)
            self.assertEqual(profile.access_token, "orcid-access")
            profile.save()
        with override_settings(SECRET_KEY="new-secret", SECRET_KEY_FALLBACKS=[]):
            self.assertEqual(UserOrcidProfile.objects.get(pk=profile.pk).access_token, "orcid-access")

    def test_plain_values_from_before_encryption_are_read_unchanged(self):
        """Plain values from before encryption are read unchanged."""
        profile = UserOrcidProfile.objects.create(user=self.user, orcid_id="0000-0002-1825-0100")
        table = connection.ops.quote_name(UserOrcidProfile._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {table} SET access_token = %s WHERE id = %s", ["legacy-plain", profile.pk])
        self.assertEqual(UserOrcidProfile.objects.get(pk=profile.pk).access_token, "legacy-plain")

    def test_migration_encrypts_plain_tokens_once(self):
        """Migration encrypts plain tokens once."""
        profile = UserOrcidProfile.objects.create(user=self.user, orcid_id="0000-0002-1825-0101", refresh_token="kept")
        table = connection.ops.quote_name(UserOrcidProfile._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {table} SET access_token = %s WHERE id = %s", ["legacy-plain", profile.pk])
        already_encrypted = stored_value(UserOrcidProfile, profile.pk, "refresh_token")
        encrypt_orcid_tokens.encrypt_stored_tokens(apps, SimpleNamespace(connection=connection))
        self.assertEqual(decrypt_secret(stored_value(UserOrcidProfile, profile.pk, "access_token")), "legacy-plain")
        self.assertEqual(stored_value(UserOrcidProfile, profile.pk, "refresh_token"), already_encrypted)
