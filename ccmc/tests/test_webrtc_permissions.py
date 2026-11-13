"""Read-only viewers and per-person permissions in WebRTC calls on experimental sessions."""

import json
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings

from asgiref.sync import async_to_sync
from asgiref.testing import ApplicationCommunicator
from rest_framework.test import APIClient

from ccmc.consumers import WebRTCSignalConsumer
from ccmc.models import WebRTCPeer, WebRTCPermission, WebRTCSession
from ccrv.models import Session

User = get_user_model()

IN_MEMORY_CHANNELS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


class Signalling:
    """One user's websocket to the signalling consumer of a call."""

    def __init__(self, call, user):
        """Prepare a connection as user to call."""
        scope = {
            "type": "websocket",
            "path": f"/ws/ccmc/webrtc/{call.id}/",
            "query_string": b"",
            "headers": [(b"host", b"cupcake.example.org")],
            "user": user,
            "url_route": {"kwargs": {"session_id": str(call.id)}},
        }
        self.communicator = ApplicationCommunicator(WebRTCSignalConsumer.as_asgi(), scope)

    async def connect(self):
        await self.communicator.send_input({"type": "websocket.connect"})
        accepted = await self.communicator.receive_output(timeout=5)
        return accepted["type"] == "websocket.accept"

    async def send_json_to(self, message):
        await self.communicator.send_input({"type": "websocket.receive", "text": json.dumps(message)})

    async def receive_json_from(self, timeout=5):
        output = await self.communicator.receive_output(timeout=timeout)
        return json.loads(output["text"])

    async def disconnect(self):
        await self.communicator.send_input({"type": "websocket.disconnect", "code": 1000})
        await self.communicator.wait(timeout=5)


def shared_session():
    """A session with its owner, an editor, a viewer and an outsider."""
    people = {
        role: User.objects.create_user(f"{role}-{uuid.uuid4().hex[:6]}", password="pw")
        for role in ("owner", "editor", "viewer", "outsider")
    }
    session = Session.objects.create(name="Digestion", owner=people["owner"], unique_id=uuid.uuid4())
    session.editors.add(people["editor"])
    session.viewers.add(people["viewer"])
    return session, people


def call_on(session, starter):
    """The default call on session, started by starter."""
    call = WebRTCSession.objects.create(session_type="video_call", initiated_by=starter, is_default=True)
    session.webrtc_sessions.add(call)
    return call


class CallRolesTest(TestCase):
    def setUp(self):
        self.session, self.people = shared_session()
        self.call = call_on(self.session, self.people["editor"])

    def test_owners_and_editors_take_part_and_viewers_only_watch(self):
        self.assertTrue(self.call.can_take_part(self.people["owner"]))
        self.assertTrue(self.call.can_take_part(self.people["editor"]))
        self.assertFalse(self.call.can_take_part(self.people["viewer"]))

    def test_only_the_session_owner_and_staff_moderate(self):
        staff = User.objects.create_user("staff-member", is_staff=True)
        self.assertTrue(self.call.can_moderate(self.people["owner"]))
        self.assertTrue(self.call.can_moderate(staff))
        self.assertFalse(self.call.can_moderate(self.people["editor"]))
        self.assertFalse(self.call.can_moderate(self.people["viewer"]))

    def test_the_starter_moderates_a_call_without_a_session(self):
        call = WebRTCSession.objects.create(session_type="video_call", initiated_by=self.people["outsider"])
        self.assertTrue(call.can_moderate(self.people["outsider"]))

    def test_permissions_follow_the_role_unless_the_moderator_changed_them(self):
        everything = {"audio": True, "video": True, "screen_share": True, "chat": True}
        nothing = {kind: False for kind in everything}
        self.assertEqual(self.call.permissions_for(self.people["editor"]), everything)
        self.assertEqual(self.call.permissions_for(self.people["viewer"]), nothing)
        WebRTCPermission.objects.create(session=self.call, user=self.people["viewer"], screen_share=True)
        WebRTCPermission.objects.create(session=self.call, user=self.people["editor"], audio=False)
        self.assertEqual(self.call.permissions_for(self.people["viewer"]), {**nothing, "screen_share": True})
        self.assertEqual(self.call.permissions_for(self.people["editor"]), {**everything, "audio": False})


class JoinDefaultCallTest(TestCase):
    def setUp(self):
        self.session, self.people = shared_session()
        self.url = f"/api/v1/sessions/{self.session.id}/join_default_webrtc/"

    def join(self, role):
        client = APIClient()
        client.force_authenticate(self.people[role])
        return client.post(self.url)

    def test_a_viewer_cannot_start_the_live_session(self):
        response = self.join("viewer")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.session.webrtc_sessions.exists())

    def test_a_viewer_joins_the_live_session_an_editor_started(self):
        started = self.join("editor")
        self.assertEqual(started.status_code, 200)
        joined = self.join("viewer")
        self.assertEqual(joined.status_code, 200)
        self.assertEqual(joined.data["id"], started.data["id"])

    def test_outsiders_cannot_join(self):
        self.join("owner")
        self.assertIn(self.join("outsider").status_code, (403, 404))


@override_settings(CHANNEL_LAYERS=IN_MEMORY_CHANNELS)
class SignallingPermissionsTest(TransactionTestCase):
    def setUp(self):
        self.session, self.people = shared_session()
        self.call = call_on(self.session, self.people["owner"])

    async def connect(self, role):
        communicator = Signalling(self.call, self.people[role])
        assert await communicator.connect(), f"{role} could not connect"
        return communicator, await communicator.receive_json_from(timeout=5)

    async def next_of(self, communicator, message_type):
        while True:
            message = await communicator.receive_json_from(timeout=5)
            if message["type"] == message_type:
                return message

    def test_a_viewer_joins_read_only_and_cannot_claim_media_or_another_role(self):
        async def scenario():
            owner, _ = await self.connect("owner")
            viewer, hello = await self.connect("viewer")
            self.assertTrue(hello["read_only"])
            self.assertFalse(hello["can_moderate"])
            await viewer.send_json_to({"type": "check", "peer_role": "host"})
            await self.next_of(viewer, "check.response")
            self.assertEqual((await self.next_of(owner, "peer.check"))["peer_role"], "viewer")
            await viewer.send_json_to(
                {"type": "peer_state", "has_video": True, "has_audio": True, "has_screen_share": True}
            )
            update = await self.next_of(owner, "peer.state_update")
            self.assertEqual(
                (update["has_video"], update["has_audio"], update["has_screen_share"]), (False, False, False)
            )
            for communicator in (owner, viewer):
                await communicator.disconnect()

        async_to_sync(scenario)()
        peer = WebRTCPeer.objects.get(session=self.call, user=self.people["viewer"])
        self.assertEqual(peer.peer_role, "viewer")
        self.assertEqual(peer.connection_state, "disconnected")
        self.assertFalse(peer.has_video or peer.has_audio or peer.has_screen_share)

    def test_the_owner_lets_a_viewer_share_their_screen_and_mutes_an_editor(self):
        async def scenario():
            owner, hello = await self.connect("owner")
            self.assertTrue(hello["can_moderate"])
            editor, _ = await self.connect("editor")
            viewer, _ = await self.connect("viewer")
            await owner.send_json_to(
                {"type": "set_permissions", "user_id": self.people["viewer"].id, "screen_share": True}
            )
            for communicator in (owner, editor, viewer):
                granted = await self.next_of(communicator, "peer.permissions")
                self.assertEqual(
                    granted["permissions"], {"audio": False, "video": False, "screen_share": True, "chat": False}
                )
                self.assertEqual(granted["overrides"]["screen_share"], True)
            await viewer.send_json_to({"type": "peer_state", "has_screen_share": True, "has_video": True})
            update = await self.next_of(owner, "peer.state_update")
            self.assertEqual((update["has_screen_share"], update["has_video"]), (True, False))

            await owner.send_json_to({"type": "set_permissions", "user_id": self.people["editor"].id, "audio": False})
            muted = await self.next_of(editor, "peer.permissions")
            self.assertEqual(muted["permissions"]["audio"], False)
            self.assertEqual(muted["permissions"]["video"], True)
            await editor.send_json_to({"type": "peer_state", "has_audio": True})
            self.assertFalse((await self.next_of(owner, "peer.state_update"))["has_audio"])

            await owner.send_json_to({"type": "set_permissions", "user_id": self.people["editor"].id, "audio": None})
            self.assertTrue((await self.next_of(editor, "peer.permissions"))["permissions"]["audio"])

            reconnected, hello = await self.connect("viewer")
            self.assertTrue(hello["permissions"][str(self.people["viewer"].id)]["screen_share"])
            for communicator in (owner, editor, viewer, reconnected):
                await communicator.disconnect()

        async_to_sync(scenario)()

    def test_only_the_session_owner_changes_permissions(self):
        async def scenario():
            editor, _ = await self.connect("editor")
            viewer, _ = await self.connect("viewer")
            await editor.send_json_to({"type": "set_permissions", "user_id": self.people["viewer"].id, "video": True})
            self.assertEqual(
                (await self.next_of(editor, "error"))["message"],
                "Only the session owner can change what people may send",
            )
            for communicator in (editor, viewer):
                await communicator.disconnect()

        async_to_sync(scenario)()
        self.assertFalse(WebRTCPermission.objects.exists())

    def test_permissions_are_refused_for_people_who_never_joined(self):
        async def scenario():
            owner, _ = await self.connect("owner")
            await owner.send_json_to({"type": "set_permissions", "user_id": self.people["outsider"].id, "video": True})
            self.assertEqual((await self.next_of(owner, "error"))["message"], "That user is not in this call")
            await owner.disconnect()

        async_to_sync(scenario)()
