"""Errors raised by choux."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from choux.draft.validation import Issue


class ChouxError(Exception):
    """Base class for every error raised by choux."""


class APIError(ChouxError):
    """
    Raised when protocols.io answers with an HTTP error or a non-zero ``status_code`` in the body.

    Attributes:
        http_status: HTTP status code of the response.
        status_code: The ``status_code`` field from the response body, when present.
        payload: The decoded response body, or the raw text when it was not JSON.
    """

    def __init__(
        self, message: str, *, http_status: int | None = None, status_code: int | None = None, payload: Any = None
    ):
        """Store the error details."""
        super().__init__(message)
        self.http_status = http_status
        self.status_code = status_code
        self.payload = payload


class RateLimitError(APIError):
    """Raised when protocols.io still answers HTTP 429 after every retry has been used."""


class UploadError(ChouxError):
    """Raised when a file could not be stored in protocols.io file storage."""


class DraftValidationError(ChouxError):
    """
    Raised when content fails validation before it is sent.

    Attributes:
        issues: Every problem found, including warnings, so callers can show the full list at once.
    """

    def __init__(self, issues: list[Issue]):
        """Store every issue and summarise the errors in the message."""
        self.issues = issues
        errors = [issue for issue in issues if issue.is_error]
        summary = "; ".join(f"{issue.path}: {issue.message}" for issue in errors[:5])
        remaining = len(errors) - 5
        if remaining > 0:
            summary = f"{summary}; and {remaining} more"
        super().__init__(f"{len(errors)} validation error(s): {summary}")
