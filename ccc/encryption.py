"""Encryption of stored secrets with keys derived from Django's ``SECRET_KEY``."""

from __future__ import annotations

import base64
import hashlib

from django.conf import settings
from django.db import models

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

KEY_CONTEXT = b"cupcake-field-encryption"


def _fernet_for(secret: str) -> Fernet:
    digest = hashlib.sha256(KEY_CONTEXT + secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def secret_cipher() -> MultiFernet:
    """
    Return the cipher for stored secrets.

    Values are encrypted with a key from ``SECRET_KEY`` and can be decrypted with keys from
    ``SECRET_KEY`` or any entry of ``SECRET_KEY_FALLBACKS``.
    """
    secrets = [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", [])]
    return MultiFernet([_fernet_for(secret) for secret in secrets if secret])


def encrypt_secret(value: str) -> str:
    """
    Encrypt a secret for storage.

    Args:
        value: Plain secret.

    Returns:
        Encrypted text.
    """
    return secret_cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    """
    Decrypt a stored secret.

    Args:
        value: Encrypted text from :func:`encrypt_secret`.

    Raises:
        cryptography.fernet.InvalidToken: When no current or fallback key decrypts the value.
    """
    return secret_cipher().decrypt(value.encode("ascii")).decode("utf-8")


def is_encrypted(value: str) -> bool:
    """Return whether ``value`` decrypts with the current or a fallback key."""
    try:
        decrypt_secret(value)
    except (InvalidToken, ValueError, UnicodeEncodeError):
        return False
    return True


class EncryptedTextField(models.TextField):
    """
    Text field stored encrypted and read back as plain text.

    Values written before the field was encrypted are read back unchanged and are encrypted the
    next time they are saved. Saving re-encrypts with the key from the current ``SECRET_KEY``.
    """

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            return decrypt_secret(value)
        except (InvalidToken, ValueError, UnicodeEncodeError):
            return value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return encrypt_secret(value)
