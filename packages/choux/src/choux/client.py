"""HTTP client for the protocols.io API."""

from __future__ import annotations

import logging
import mimetypes
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import httpx
from choux.draft.builder import Draft
from choux.draft.validation import Issue, Units, raise_for_issues, validate_draft, validate_step_fields
from choux.exceptions import APIError, RateLimitError, UploadError
from choux.models import UploadedFile
from choux.ratelimit import RateLimiter
from choux.steps import Step

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.protocols.io/api"
CONTENT_HOST = "https://content.protocols.io"
STORAGE_PREFIX = "files/"
CACHE_CONTROL = "max-age=31536000"
RETRY_STATUSES = frozenset({429, 502, 503, 504})
DRAFT_PROTOCOL_FIELDS = frozenset({"description", "before_start", "guidelines", "warning"})


class ProtocolsIO:
    """
    Client for the protocols.io API.

    Every request goes through a :class:`RateLimiter`. Responses with HTTP 429, 502, 503 or 504 and
    connection failures are retried with exponential backoff. Use the client as a context manager,
    or call :meth:`close`, to release connections.

    Args:
        token: OAuth or client access token.
        base_url: API root, without a trailing slash.
        http_client: HTTP client to send requests with. It is not closed by :meth:`close`.
        rate_limiter: Limiter to share between clients of the same account.
        max_retries: Retries for each request after the first attempt.
        backoff: Seconds to wait before the first retry; doubled for each further retry.
        timeout: Seconds before a request is abandoned.
        sleep: Sleep function, replaceable in tests.
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        http_client: httpx.Client | None = None,
        rate_limiter: RateLimiter | None = None,
        max_retries: int = 3,
        backoff: float = 2.0,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        """Set up the HTTP client, rate limiter and retry policy."""
        if not token:
            raise ValueError("a protocols.io access token is required")
        self.base_url = base_url.rstrip("/")
        self._owns_client = http_client is None
        self.http = http_client or httpx.Client(timeout=timeout)
        self._auth = {"Authorization": f"Bearer {token}"}
        self.rate_limiter = rate_limiter or RateLimiter()
        self.max_retries = max_retries
        self.backoff = backoff
        self.timeout = timeout
        self._sleep = sleep

    def __enter__(self) -> ProtocolsIO:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Release connections of the HTTP client created by this instance."""
        if self._owns_client:
            self.http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Send a request to the API.

        Args:
            method: HTTP method.
            path: Path below the API root, such as ``/v3/session/profile``.
            params: Query parameters.
            json: JSON body.
            data: Form body.

        Returns:
            The decoded response body.

        Raises:
            RateLimitError: When the API still answers HTTP 429 after every retry.
            APIError: For any other HTTP error, a non-zero ``status_code`` in the body, or when the
                API cannot be reached after every retry.
        """
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            self.rate_limiter.acquire()
            try:
                response = self.http.request(
                    method, url, params=params, json=json, data=data, headers=self._auth, timeout=self.timeout
                )
            except httpx.TransportError as error:
                if attempt >= self.max_retries:
                    raise APIError(f"{method} {path} could not reach protocols.io: {error}") from error
                delay = self.backoff * (2**attempt)
                logger.warning("%s %s failed with %s, retrying in %.1fs", method, path, error, delay)
                self._sleep(delay)
                attempt += 1
                continue
            if response.status_code in RETRY_STATUSES and attempt < self.max_retries:
                delay = self._retry_delay(response, attempt)
                logger.warning("%s %s returned %s, retrying in %.1fs", method, path, response.status_code, delay)
                self._sleep(delay)
                attempt += 1
                continue
            return self._decode(method, path, response)

    def get_profile(self) -> dict[str, Any]:
        """Return the profile of the account that owns the token."""
        return self.request("GET", "/v3/session/profile")["user"]

    def list_workspaces(self, *, filter: str = "my_groups", page_size: int = 10, page_id: int = 1) -> dict[str, Any]:
        """
        List workspaces.

        Args:
            filter: ``my_groups``, ``user_public``, ``all_public`` or ``all_public_request``.
            page_size: Items per page, between 1 and 100.
            page_id: Page number, starting at 1.

        Returns:
            A dictionary with ``items`` and ``pagination``.
        """
        return self.request(
            "GET", "/v3/workspaces", params={"filter": filter, "page_size": page_size, "page_id": page_id}
        )

    def search_workspace(self, workspace_uri: str, **query: Any) -> dict[str, Any]:
        """
        Search the file manager of one workspace.

        Args:
            workspace_uri: Workspace URI, for example ``my-lab``.
            query: File manager search parameters such as ``search_key``, ``page_size`` or ``content_types[]``.

        Returns:
            A dictionary with ``items`` and ``pagination``.
        """
        return self.request("GET", f"/v4/filemanager/workspaces/{workspace_uri}/search", params=query)["payload"]

    def search_folder(self, folder_guid: str, **query: Any) -> dict[str, Any]:
        """
        Search one file manager folder.

        Args:
            folder_guid: Folder GUID.
            query: File manager search parameters.

        Returns:
            A dictionary with ``items`` and ``pagination``.
        """
        return self.request("GET", f"/v4/filemanager/folders/{folder_guid}/search", params=query)["payload"]

    def get_protocol(self, protocol: int | str, *, content_format: str = "json") -> dict[str, Any]:
        """
        Return a protocol with its steps, materials and units.

        Args:
            protocol: Protocol id, URI or GUID.
            content_format: ``json``, ``html`` or ``markdown`` for rich text fields.
        """
        return self.request("GET", f"/v4/protocols/{protocol}", params={"content_format": content_format})["payload"]

    def get_units(self, protocol: int | str) -> list[dict[str, Any]]:
        """
        Return the units available for amounts, temperatures and concentrations in a protocol.

        Args:
            protocol: Protocol id, URI or GUID.
        """
        return self.get_protocol(protocol).get("units") or []

    def search_reagents(
        self, key: str, *, citeab: bool | None = None, page_size: int = 10, page_id: int = 1
    ) -> dict[str, Any]:
        """
        Search the protocols.io reagent catalogue by name, catalogue number or vendor.

        Args:
            key: Search text.
            citeab: ``True`` for CiteAB reagents only, ``False`` to leave them out, ``None`` for all.
            page_size: Items per page, between 1 and 100.
            page_id: Page number, starting at 1.

        Returns:
            A dictionary with ``items``, each usable with :func:`choux.draft.entities.reagent`, and
            ``pagination``.

        Raises:
            ValueError: When ``key`` is blank.
        """
        if not key or not key.strip():
            raise ValueError("a search key is required")
        params: dict[str, Any] = {"key": key.strip(), "page_size": page_size, "page_id": page_id}
        if citeab is not None:
            params["is_citeab"] = "true" if citeab else "false"
        payload = self.request("GET", "/v3/reagents", params=params)
        return {"items": payload.get("items") or [], "pagination": payload.get("pagination") or {}}

    def get_materials(self, protocol: int | str) -> list[dict[str, Any]]:
        """
        Return the reagents listed as materials of a protocol.

        Args:
            protocol: Protocol id or URI.
        """
        return self.request("GET", f"/v3/protocols/{protocol}/materials").get("materials") or []

    def create_protocol(self, guid: str, *, type_id: int = 1) -> dict[str, Any]:
        """
        Create an empty private protocol.

        The protocol is created in the active workspace of the account, which cannot be chosen
        through the API.

        Args:
            guid: GUID for the new protocol, 32 hex characters without dashes.
            type_id: ``1`` for a protocol, ``3`` for a collection, ``4`` for a document.
        """
        return self.request("POST", f"/v3/protocols/{guid}", data={"type_id": type_id})["protocol"]

    def update_protocol(
        self,
        protocol: int | str,
        *,
        validate: bool = True,
        units: Units | None = None,
        **fields: Any,
    ) -> list[Issue]:
        """
        Update protocol fields.

        ``description``, ``before_start``, ``guidelines`` and ``warning`` accept a :class:`Draft`.

        Args:
            protocol: Protocol id, URI or GUID.
            validate: Check rich text fields before sending; pass ``False`` to send them unchecked.
            units: Unit ids or units of the protocol, used to check units in rich text fields.
            fields: Fields to change, for example ``title`` or ``keywords``.

        Returns:
            Validation warnings.

        Raises:
            DraftValidationError: When ``validate`` is on and a rich text field has errors.
        """
        body: dict[str, Any] = {}
        issues: list[Issue] = []
        for name, value in fields.items():
            if name in DRAFT_PROTOCOL_FIELDS and isinstance(value, Draft):
                if validate:
                    issues.extend(validate_draft(value, units=units, path=name))
                value = value.to_json()
            body[name] = value
        if validate:
            raise_for_issues(issues)
        self.request("PUT", f"/v4/protocols/{protocol}", json=body)
        return issues

    def get_steps(self, protocol: int | str, *, content_format: str = "json") -> list[dict[str, Any]]:
        """
        Return the steps of a protocol in order.

        Args:
            protocol: Protocol id, URI or GUID.
            content_format: ``json``, ``html`` or ``markdown`` for step text.
        """
        payload = self.request("GET", f"/v4/protocols/{protocol}/steps", params={"content_format": content_format})
        return payload.get("payload") or []

    def validate_steps(self, steps: Iterable[Step], *, units: Units | None = None) -> list[Issue]:
        """
        Check steps without sending them.

        Args:
            steps: Steps to check.
            units: Unit ids or units of the protocol.

        Returns:
            Every issue found.
        """
        issues: list[Issue] = []
        for index, step in enumerate(steps):
            path = f"steps[{index}]"
            issues.extend(validate_step_fields(step.guid, step.previous_guid, step.section_color, path=path))
            issues.extend(validate_draft(step.draft(), units=units, path=f"{path}.step"))
        return issues

    def save_steps(
        self,
        protocol: int | str,
        steps: Iterable[Step],
        *,
        validate: bool = True,
        units: Units | None = None,
    ) -> list[Issue]:
        """
        Add or update steps of a private protocol.

        Only steps that are new or changed need to be sent, together with any step whose
        ``previous_guid`` changes as a result. Steps with cases cannot be updated.

        Args:
            protocol: Protocol id, URI or GUID.
            steps: Steps to add or update.
            validate: Check steps before sending; pass ``False`` to send them unchecked.
            units: Unit ids or units of the protocol, used to check units in step text.

        Returns:
            Validation warnings.

        Raises:
            DraftValidationError: When ``validate`` is on and a step has errors.
        """
        ordered = list(steps)
        issues = self.validate_steps(ordered, units=units) if validate else []
        raise_for_issues(issues)
        for issue in issues:
            logger.warning("%s: %s", issue.path, issue.message)
        self.request("POST", f"/v4/protocols/{protocol}/steps", json={"steps": [step.to_api() for step in ordered]})
        return issues

    def delete_steps(self, protocol: int | str, guids: Iterable[str]) -> None:
        """
        Delete steps of a private protocol. Update the ``previous_guid`` of the steps that followed them.

        Args:
            protocol: Protocol id, URI or GUID.
            guids: GUIDs of the steps to delete.
        """
        self.request("DELETE", f"/v4/protocols/{protocol}/steps", json={"steps": list(guids)})

    def upload_file(
        self,
        filename: str,
        content: bytes,
        *,
        mime_type: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> UploadedFile:
        """
        Store a file in protocols.io file storage.

        Uploaded files can be downloaded by anyone who has their URL.

        Args:
            filename: File name shown to readers.
            content: File content.
            mime_type: Content type; guessed from ``filename`` when omitted.
            width: Image width in pixels.
            height: Image height in pixels.

        Returns:
            The stored file, ready for :func:`choux.draft.entities.image` or
            :func:`choux.draft.entities.file_attachment`.

        Raises:
            UploadError: When storage rejects the file or cannot be reached.
        """
        body: dict[str, Any] = {"filename": filename}
        if width is not None:
            body["width"] = width
        if height is not None:
            body["height"] = height
        prepared = self.request("POST", "/v3/files", json=body)
        form = dict(prepared["formData"])
        meta = prepared["metaData"]
        bucket = form.pop("s3_bucket")
        stored_type = form.pop("ContentType", None) or mime_type or _guess_type(filename)
        key = f"{STORAGE_PREFIX}{form['key']}"
        fields = {**form, "key": key, "Content-Type": stored_type, "Cache-Control": CACHE_CONTROL}
        storage_url = f"https://{bucket}.s3.amazonaws.com/"
        self.rate_limiter.acquire()
        try:
            stored = self.http.post(
                storage_url,
                data=fields,
                files={"file": (filename, content, stored_type)},
                timeout=self.timeout,
            )
        except httpx.TransportError as error:
            raise UploadError(f"storage could not be reached for {filename}: {error}") from error
        if stored.status_code not in (200, 201, 204):
            raise UploadError(f"storage rejected {filename} with HTTP {stored.status_code}: {stored.text[:300]}")
        self.request("PUT", f"/v3/files/{meta['file_id']}")
        return UploadedFile(
            id=int(meta["file_id"]),
            key=key,
            source=f"{CONTENT_HOST}/{key}",
            raw_source=f"{storage_url}{key}",
            original_name=filename,
            mime_type=stored_type,
            size=len(content),
            file_type=int(meta.get("file_type") or 0),
            thumb_url=meta.get("thumb_url") or "",
            width=width,
            height=height,
        )

    def create_record(self, protocol_uri: str, *, folder_guid: str | None = None) -> dict[str, Any]:
        """
        Start an experiment record from a protocol.

        Args:
            protocol_uri: URI of the protocol the record runs.
            folder_guid: File manager folder for the record; the personal folder of the active
                workspace when omitted.

        Returns:
            The new record, including its steps.
        """
        data = {"protocol_uri": protocol_uri}
        if folder_guid:
            data["folder_data.guid"] = folder_guid
        return self.request("POST", "/v3/records", data=data)["record"]

    def get_record(self, guid: str, *, content_format: str = "json", with_protocol: bool = False) -> dict[str, Any]:
        """
        Return an experiment record.

        Args:
            guid: Record GUID.
            content_format: ``json``, ``html`` or ``markdown`` for rich text fields.
            with_protocol: Include the protocol the record runs.
        """
        params = {"content_format": content_format}
        if with_protocol:
            params["with_protocol"] = 1
        return self.request("GET", f"/v4/records/{guid}", params=params)["payload"]["record"]

    def save_record(self, guid: str, changes: Iterable[dict[str, Any]]) -> None:
        """
        Apply changes built with :mod:`choux.records` to an experiment record.

        Args:
            guid: Record GUID.
            changes: Change entries in the order they should be applied.
        """
        self.request("PUT", f"/v3/records/{guid}", json={"stack": list(changes)})

    def trash(self, item_ids: Iterable[int]) -> list[int]:
        """
        Move file manager items to the trash.

        Args:
            item_ids: File manager item ids, not protocol or record ids.

        Returns:
            Ids that were moved.
        """
        return self.request("PUT", "/v3/filemanager/trash", json={"ids": list(item_ids)}).get("deleted") or []

    def restore(self, item_ids: Iterable[int]) -> list[int]:
        """
        Restore file manager items from the trash.

        Args:
            item_ids: File manager item ids.

        Returns:
            Ids that were restored.
        """
        return self.request("DELETE", "/v3/filemanager/trash", json={"ids": list(item_ids)}).get("restored") or []

    def publish(self, protocol_uri: str, *, title: str | None = None, doi_only: bool = False) -> None:
        """
        Issue a DOI for a protocol. The published version can no longer be edited.

        Args:
            protocol_uri: Protocol URI.
            title: New title to publish under.
            doi_only: Issue the DOI without making the protocol public.
        """
        params: dict[str, Any] = {}
        if title:
            params["title"] = title
        if doi_only:
            params["prepublish"] = 1
        self.request("POST", f"/v3/protocols/{protocol_uri}/publish", params=params or None)

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return self.backoff * (2**attempt)

    @staticmethod
    def _decode(method: str, path: str, response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            body = None
        status_code = body.get("status_code") if isinstance(body, dict) else None
        if response.status_code == 429:
            raise RateLimitError(
                f"{method} {path} is rate limited", http_status=429, status_code=status_code, payload=body
            )
        if response.status_code >= 400 or (status_code not in (None, 0)):
            message = ""
            if isinstance(body, dict):
                message = body.get("error_message") or body.get("status_text") or ""
            if not message:
                message = response.text[:300]
            raise APIError(
                f"{method} {path} failed with HTTP {response.status_code}: {message}",
                http_status=response.status_code,
                status_code=status_code,
                payload=body if body is not None else response.text,
            )
        if not isinstance(body, dict):
            raise APIError(
                f"{method} {path} returned a body that is not a JSON object",
                http_status=response.status_code,
                payload=response.text,
            )
        return body


def _guess_type(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"
