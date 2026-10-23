"""Browsing a user's protocols.io workspaces, folders and protocols."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from choux import ProtocolsIO

PAGE_SIZE = 10
FOLDER_CONTENT_TYPE = 10
PROTOCOL_CONTENT_TYPE = 1
PROTOCOL_TYPES = {1: "protocol", 3: "collection", 4: "document"}
TRASH_ICON = "Trash"


def page_info(pagination: Mapping[str, Any] | None) -> dict[str, Any]:
    """
    Return the paging details of a protocols.io list.

    Args:
        pagination: The ``pagination`` object of a protocols.io list response.
    """
    pagination = pagination or {}
    return {
        "page": pagination.get("current_page") or 1,
        "total_pages": pagination.get("total_pages") or 0,
        "total_results": pagination.get("total_results") or 0,
        "has_next": bool(pagination.get("next_page")),
    }


def _workspace_of(item: Mapping[str, Any]) -> dict[str, Any]:
    space = item.get("space") or {}
    return {"id": space.get("id"), "title": space.get("title") or ""}


def browse_item(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """
    Return a file manager item as a folder or protocol entry, or ``None`` for anything else.

    Records, files, the trash folder and items in the trash are left out.

    Args:
        item: Item from a protocols.io file manager search.
    """
    if item.get("in_trash"):
        return None
    content_type = item.get("content_type_id")
    if content_type == FOLDER_CONTENT_TYPE:
        if (item.get("icon") or {}).get("code") == TRASH_ICON:
            return None
        return {
            "kind": "folder",
            "title": item.get("title") or "",
            "guid": item.get("guid") or "",
            "parent_guid": item.get("parent_guid"),
            "has_subfolders": bool(item.get("has_subfolders")),
            "workspace": _workspace_of(item),
        }
    if content_type == PROTOCOL_CONTENT_TYPE:
        protocol_type = PROTOCOL_TYPES.get(item.get("type_id"), "protocol")
        return {
            "kind": "protocol",
            "title": item.get("title") or "",
            "id": item.get("id") or item.get("content_id"),
            "uri": item.get("uri") or "",
            "protocol_type": protocol_type,
            "importable": protocol_type == "protocol",
            "last_modified": item.get("last_modified") or item.get("changed_on") or item.get("created_on"),
            "workspace": _workspace_of(item),
        }
    return None


def _entries(payload: Mapping[str, Any], *, top_level_only: bool = False) -> dict[str, Any]:
    items = []
    for raw in payload.get("items") or []:
        if top_level_only and raw.get("parent_guid"):
            continue
        entry = browse_item(raw)
        if entry is not None:
            items.append(entry)
    return {"items": items, **page_info(payload.get("pagination"))}


def list_workspaces(client: ProtocolsIO, page: int = 1) -> dict[str, Any]:
    """
    Return the workspaces the user is a member of.

    Args:
        client: Client acting as the user.
        page: Page number, starting at 1.
    """
    payload = client.list_workspaces(filter="my_groups", page_size=PAGE_SIZE, page_id=page)
    items = [
        {
            "uri": workspace.get("uri") or "",
            "title": workspace.get("title") or "",
            "description": workspace.get("description") or "",
        }
        for workspace in payload.get("items") or []
    ]
    return {"items": items, **page_info(payload.get("pagination"))}


def workspace_folders(client: ProtocolsIO, workspace_uri: str, page: int = 1) -> dict[str, Any]:
    """
    Return the top-level folders of a workspace.

    Args:
        client: Client acting as the user.
        workspace_uri: URI of the workspace.
        page: Page number, starting at 1.
    """
    query = {"content_types[]": [FOLDER_CONTENT_TYPE], "page_size": PAGE_SIZE, "page_id": page}
    return _entries(client.search_workspace(workspace_uri, **query), top_level_only=True)


def folder_items(client: ProtocolsIO, folder_guid: str, page: int = 1) -> dict[str, Any]:
    """
    Return the folders and protocols in a folder.

    Args:
        client: Client acting as the user.
        folder_guid: GUID of the folder.
        page: Page number, starting at 1.
    """
    query = {
        "content_types[]": [FOLDER_CONTENT_TYPE, PROTOCOL_CONTENT_TYPE],
        "page_size": PAGE_SIZE,
        "page_id": page,
    }
    return _entries(client.search_folder(folder_guid, **query))


def search_protocols(client: ProtocolsIO, text: str, page: int = 1) -> dict[str, Any]:
    """
    Search protocols in every workspace the user can see.

    Args:
        client: Client acting as the user.
        text: Search text.
        page: Page number, starting at 1.
    """
    query = {"content_types[]": [PROTOCOL_CONTENT_TYPE], "page_size": PAGE_SIZE, "page_id": page}
    return _entries(client.search_all(text, **query))
