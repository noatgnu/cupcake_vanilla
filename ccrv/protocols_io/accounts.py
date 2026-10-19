"""Users' own protocols.io accounts."""

from __future__ import annotations

import threading
from typing import Any

from django.utils import timezone

from choux import ProtocolsIO, RateLimiter

_limiters: dict[int, RateLimiter] = {}
_limiters_lock = threading.Lock()


class ProtocolsIOAccountMissing(Exception):
    """Raised when a user has not connected a protocols.io account."""


def rate_limiter_for(user_id: int) -> RateLimiter:
    """Return the request pacing shared by every client of one user in this process."""
    with _limiters_lock:
        if user_id not in _limiters:
            _limiters[user_id] = RateLimiter()
        return _limiters[user_id]


def connect_account(user: Any, token: str) -> Any:
    """
    Check a protocols.io access token and save it as the user's account.

    Args:
        user: The Cupcake user.
        token: protocols.io access token.

    Returns:
        The saved :class:`ccrv.models.ProtocolsIOAccount`.

    Raises:
        ValueError: When the token is blank.
        choux.APIError: When protocols.io does not accept the token.
    """
    token = (token or "").strip()
    if not token:
        raise ValueError("a protocols.io access token is required")
    with ProtocolsIO(token, rate_limiter=rate_limiter_for(user.pk)) as client:
        profile = client.get_profile()
    account_model = user._meta.apps.get_model("ccrv", "ProtocolsIOAccount")
    account, _ = account_model.objects.update_or_create(
        user=user,
        defaults={"access_token": token, "username": profile.get("username") or "", "name": profile.get("name") or ""},
    )
    return account


def disconnect_account(user: Any) -> bool:
    """
    Remove the user's saved protocols.io account.

    Returns:
        Whether an account was removed.
    """
    account_model = user._meta.apps.get_model("ccrv", "ProtocolsIOAccount")
    deleted, _ = account_model.objects.filter(user=user).delete()
    return deleted > 0


def client_for(user: Any) -> ProtocolsIO:
    """
    Return a protocols.io client that acts as the user.

    Args:
        user: The Cupcake user.

    Raises:
        ProtocolsIOAccountMissing: When the user has not connected an account.
    """
    account_model = user._meta.apps.get_model("ccrv", "ProtocolsIOAccount")
    account = account_model.objects.filter(user=user).first()
    if account is None or not account.access_token:
        raise ProtocolsIOAccountMissing("connect a protocols.io account first")
    account_model.objects.filter(pk=account.pk).update(last_used_at=timezone.now())
    return ProtocolsIO(account.access_token, rate_limiter=rate_limiter_for(user.pk))
