"""Tests for browsing and importing from a user's own protocols.io account."""

from contextlib import nullcontext
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from choux import APIError
from rest_framework.test import APIClient

from ccrv.models import ProtocolModel
from ccrv.protocols_io.accounts import ProtocolsIOAccountMissing
from ccrv.protocols_io.browser import (
    browse_item,
    folder_items,
    list_workspaces,
    page_info,
    search_protocols,
    workspace_folders,
)

LRRK2 = {"id": 59673, "title": "lrrk2"}
TOAN_FOLDER = {
    "content_type_id": 10,
    "title": "Toan Phung",
    "guid": "C5463D4BF23D11ECA31A0A58A9FEAC02",
    "parent_guid": None,
    "has_subfolders": 0,
    "icon": {"code": "MyFiles"},
    "in_trash": False,
    "space": LRRK2,
}
TRASH_FOLDER = {**TOAN_FOLDER, "title": "Trash", "guid": "C543C726F23D11ECA31A0A58A9FEAC02", "icon": {"code": "Trash"}}
NESTED_FOLDER = {**TOAN_FOLDER, "title": "Gels", "guid": "A" * 32, "parent_guid": TOAN_FOLDER["guid"]}
PROTOCOL = {
    "content_type_id": 1,
    "type_id": 1,
    "id": 340067,
    "uri": "cupcake-export-test-kqcbcvssp",
    "title": "Cupcake export test",
    "last_modified": 1792352685,
    "created_on": 1792341267,
    "in_trash": False,
    "space": LRRK2,
}
COLLECTION = {**PROTOCOL, "type_id": 3, "id": 5, "uri": "lysis-collection", "title": "Lysis collection"}
RECORD = {"content_type_id": 11, "title": "Run", "in_trash": False, "space": LRRK2}
PAGINATION = {"current_page": 1, "total_pages": 2, "total_results": 12, "next_page": "https://next"}


def fake_client(**payloads):
    """Return a client whose list methods return the given payloads."""
    client = Mock()
    for name, payload in payloads.items():
        getattr(client, name).return_value = payload
    return client


class BrowseItemTest(SimpleTestCase):
    def test_folder(self):
        """Folder."""
        self.assertEqual(
            browse_item(TOAN_FOLDER),
            {
                "kind": "folder",
                "title": "Toan Phung",
                "guid": "C5463D4BF23D11ECA31A0A58A9FEAC02",
                "parent_guid": None,
                "has_subfolders": False,
                "workspace": {"id": 59673, "title": "lrrk2"},
            },
        )

    def test_protocol_is_importable(self):
        """Protocol is importable."""
        entry = browse_item(PROTOCOL)
        self.assertEqual(
            (entry["kind"], entry["uri"], entry["protocol_type"]), ("protocol", PROTOCOL["uri"], "protocol")
        )
        self.assertTrue(entry["importable"])
        self.assertEqual(entry["last_modified"], 1792352685)

    def test_collections_are_listed_but_not_importable(self):
        """Collections are listed but not importable."""
        entry = browse_item(COLLECTION)
        self.assertEqual(entry["protocol_type"], "collection")
        self.assertFalse(entry["importable"])

    def test_trash_records_and_trashed_items_are_left_out(self):
        """Trash records and trashed items are left out."""
        self.assertIsNone(browse_item(TRASH_FOLDER))
        self.assertIsNone(browse_item(RECORD))
        self.assertIsNone(browse_item({**PROTOCOL, "in_trash": True}))

    def test_page_info(self):
        """Page info."""
        self.assertEqual(page_info(PAGINATION), {"page": 1, "total_pages": 2, "total_results": 12, "has_next": True})
        self.assertEqual(page_info(None), {"page": 1, "total_pages": 0, "total_results": 0, "has_next": False})


class BrowseListTest(SimpleTestCase):
    def test_workspaces(self):
        """Workspaces."""
        client = fake_client(
            list_workspaces={"items": [{"uri": "lrrk2", "title": "LRRK2", "id": 1}], "pagination": PAGINATION}
        )
        result = list_workspaces(client, 2)
        client.list_workspaces.assert_called_once_with(filter="my_groups", page_size=10, page_id=2)
        self.assertEqual(result["items"], [{"uri": "lrrk2", "title": "LRRK2", "description": ""}])
        self.assertTrue(result["has_next"])

    def test_workspace_lists_only_top_level_folders(self):
        """Workspace lists only top level folders."""
        client = fake_client(
            search_workspace={"items": [TRASH_FOLDER, TOAN_FOLDER, NESTED_FOLDER], "pagination": PAGINATION}
        )
        result = workspace_folders(client, "lrrk2")
        client.search_workspace.assert_called_once_with(
            "lrrk2", **{"content_types[]": [10], "page_size": 10, "page_id": 1}
        )
        self.assertEqual([item["title"] for item in result["items"]], ["Toan Phung"])

    def test_folder_lists_folders_and_protocols(self):
        """Folder lists folders and protocols."""
        client = fake_client(search_folder={"items": [NESTED_FOLDER, PROTOCOL, RECORD], "pagination": PAGINATION})
        result = folder_items(client, TOAN_FOLDER["guid"], 3)
        client.search_folder.assert_called_once_with(
            TOAN_FOLDER["guid"], **{"content_types[]": [10, 1], "page_size": 10, "page_id": 3}
        )
        self.assertEqual([item["kind"] for item in result["items"]], ["folder", "protocol"])

    def test_search(self):
        """Search."""
        client = fake_client(search_all={"items": [PROTOCOL], "pagination": PAGINATION})
        result = search_protocols(client, "cupcake")
        client.search_all.assert_called_once_with("cupcake", **{"content_types[]": [1], "page_size": 10, "page_id": 1})
        self.assertEqual(result["items"][0]["workspace"], {"id": 59673, "title": "lrrk2"})


class BrowseEndpointTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("browse-user", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def get(self, name, client=None, side_effect=None, **params):
        """Call a browse endpoint with a fake protocols.io client."""
        patch_options = {"side_effect": side_effect} if side_effect else {"return_value": nullcontext(client or Mock())}
        with patch("ccrv.viewsets.client_for", **patch_options):
            return self.client.get(reverse(f"ccrv:protocolsiobrowse-{name}"), params)

    def test_workspaces(self):
        """Workspaces."""
        client = fake_client(list_workspaces={"items": [{"uri": "lrrk2", "title": "LRRK2"}], "pagination": PAGINATION})
        response = self.get("workspaces", client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["items"][0]["uri"], "lrrk2")

    def test_folder_items_with_page(self):
        """Folder items with page."""
        client = fake_client(search_folder={"items": [PROTOCOL], "pagination": PAGINATION})
        response = self.get("folder-items", client, folder=TOAN_FOLDER["guid"], page="2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.search_folder.call_args.kwargs["page_id"], 2)

    def test_workspace_items_and_search(self):
        """Workspace items and search."""
        client = fake_client(
            search_workspace={"items": [TOAN_FOLDER], "pagination": PAGINATION},
            search_all={"items": [PROTOCOL], "pagination": PAGINATION},
        )
        self.assertEqual(self.get("workspace-items", client, workspace="lrrk2").data["items"][0]["title"], "Toan Phung")
        self.assertEqual(self.get("search", client, q="cupcake").data["items"][0]["uri"], PROTOCOL["uri"])

    def test_required_parameters(self):
        """Required parameters."""
        for name in ("workspace-items", "folder-items", "search"):
            with self.subTest(name):
                self.assertEqual(self.get(name).status_code, 400)

    def test_invalid_page(self):
        """Invalid page."""
        self.assertEqual(self.get("workspaces", page="two").status_code, 400)
        self.assertEqual(self.get("workspaces", page="0").status_code, 400)

    def test_needs_the_users_own_account(self):
        """Needs the users own account."""
        response = self.get("workspaces", side_effect=ProtocolsIOAccountMissing("none"))
        self.assertEqual((response.status_code, response.data["error"]), (400, "Connect a protocols.io account first"))

    def test_protocols_io_failure(self):
        """Protocols io failure."""
        client = Mock()
        client.list_workspaces.side_effect = APIError("down", http_status=503)
        response = self.get("workspaces", client)
        self.assertEqual((response.status_code, response.data["error"]), (502, "protocols.io request failed"))

    def test_without_an_account_nothing_uses_the_server_token(self):
        """Without an account nothing uses the server token."""
        with patch("choux.ProtocolsIO.request") as request:
            response = self.client.get(reverse("ccrv:protocolsiobrowse-workspaces"))
        self.assertEqual(response.status_code, 400)
        request.assert_not_called()


class ImportFromAccountTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("import-user", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("ccrv:protocolmodel-import-from-protocols-io-account")
        self.data = {
            "id": 340067,
            "uri": "cupcake-export-test-kqcbcvssp",
            "url": "https://www.protocols.io/view/cupcake-export-test-kqcbcvssp",
            "type_id": 1,
            "created_on": 1792341267,
            "doi": None,
            "title": "Cupcake export test",
            "description": "About",
            "version_uri": "",
            "steps": [
                {
                    "id": 1,
                    "previous_id": 0,
                    "duration": 0,
                    "components": [{"title": "description", "source": {"description": "<p>Intro</p>"}}],
                },
                {
                    "id": 2,
                    "previous_id": 1,
                    "duration": 300,
                    "section_duration": 300,
                    "components": [
                        {"title": "Section", "source": {"title": "Preparation"}},
                        {"title": "description", "source": {"description": "<p>Wash</p>"}},
                    ],
                },
            ],
        }

    def post(self, body, data=None, side_effect=None):
        """Call the import endpoint with a fake protocols.io client."""
        client = Mock()
        if side_effect:
            client.get_protocol_v3.side_effect = side_effect
        else:
            client.get_protocol_v3.return_value = data or self.data
        with patch("ccrv.viewsets.client_for", return_value=nullcontext(client)):
            return self.client.post(self.url, body, format="json"), client

    def test_imports_a_private_protocol_into_sections(self):
        """Imports a private protocol into sections."""
        response, client = self.post({"protocol": "https://www.protocols.io/edit/cupcake-export-test-kqcbcvssp"})
        self.assertEqual(response.status_code, 201)
        client.get_protocol_v3.assert_called_once_with("cupcake-export-test-kqcbcvssp")
        protocol = ProtocolModel.objects.get(pk=response.data["id"])
        self.assertEqual((protocol.owner, protocol.protocol_url), (self.user, self.data["url"]))
        self.assertEqual(
            [section.section_description for section in protocol.sections.order_by("order")],
            ["Untitled section", "Preparation"],
        )
        self.assertFalse(protocol.steps.filter(step_section__isnull=True).exists())

    def test_collections_and_documents_are_refused(self):
        """Collections and documents are refused."""
        response, _ = self.post({"protocol": "lysis-collection"}, data={**self.data, "type_id": 3})
        self.assertEqual((response.status_code, response.data["error"]), (400, "Only protocols can be imported"))
        self.assertFalse(ProtocolModel.objects.exists())

    def test_protocol_is_required(self):
        """Protocol is required."""
        response, client = self.post({"protocol": "  "})
        self.assertEqual(response.status_code, 400)
        client.get_protocol_v3.assert_not_called()

    def test_protocols_io_failure(self):
        """Protocols io failure."""
        response, _ = self.post(
            {"protocol": "missing"}, side_effect=APIError("protocol does not exist", http_status=404)
        )
        self.assertEqual(response.status_code, 502)

    def test_needs_the_users_own_account(self):
        """Needs the users own account."""
        with patch("choux.ProtocolsIO.request") as request:
            response = self.client.post(self.url, {"protocol": "cupcake-export-test-kqcbcvssp"}, format="json")
        self.assertEqual((response.status_code, response.data["error"]), (400, "Connect a protocols.io account first"))
        request.assert_not_called()
