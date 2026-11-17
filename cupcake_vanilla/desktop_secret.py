"""The signing key of the desktop app, kept in its data folder."""

import os
import secrets
import time


def load_secret_key(path):
    """
    Return the signing key stored at path, creating it with a new random key, readable only by its owner, when it
    does not exist yet.
    """
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        for _ in range(50):
            with open(path) as handle:
                key = handle.read().strip()
            if key:
                return key
            time.sleep(0.02)
        raise RuntimeError(f"The signing key file {path} is empty")
    key = secrets.token_urlsafe(64)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(key)
    return key
