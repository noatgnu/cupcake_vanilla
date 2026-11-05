"""The single timer of each session step, shared by the session's participants."""

import uuid

from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from ccrv.models import ProtocolModel, ProtocolSection, ProtocolStep, Session, TimeKeeper
from ccrv.signals import timekeeper_recipients
from tests.factories import UserFactory


class SessionTimerTestCase(APITestCase):
    def setUp(self):
        self.owner = UserFactory.create_user(username="owner")
        self.editor = UserFactory.create_user(username="editor")
        self.viewer = UserFactory.create_user(username="viewer")
        self.stranger = UserFactory.create_user(username="stranger")
        protocol = ProtocolModel.objects.create(protocol_title="Protocol", owner=self.owner, enabled=True)
        section = ProtocolSection.objects.create(protocol=protocol, section_description="Section")
        self.step = ProtocolStep.objects.create(
            protocol=protocol, step_section=section, step_description="Step", step_duration=60
        )
        self.session = Session.objects.create(name="Session", owner=self.owner, unique_id=uuid.uuid4())
        self.session.editors.add(self.editor)
        self.session.viewers.add(self.viewer)
        self.session.protocols.add(protocol)
        self.timer = TimeKeeper.objects.create(
            session=self.session, step=self.step, user=self.owner, current_duration=60, original_duration=60
        )

    def as_user(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    def action_url(self, name):
        return reverse(f"ccrv:timekeeper-{name}", kwargs={"pk": self.timer.pk})


class SessionTimerListTests(SessionTimerTestCase):
    def test_session_participants_list_the_session_timer(self):
        for user in (self.owner, self.editor, self.viewer):
            response = self.as_user(user).get(reverse("ccrv:timekeeper-list"), {"session": self.session.pk})
            self.assertEqual([t["id"] for t in response.data["results"]], [self.timer.pk], user.username)

    def test_others_do_not_list_the_session_timer(self):
        response = self.as_user(self.stranger).get(reverse("ccrv:timekeeper-list"), {"session": self.session.pk})
        self.assertEqual(response.data["results"], [])

    def test_unfiltered_list_holds_only_own_timers(self):
        response = self.as_user(self.editor).get(reverse("ccrv:timekeeper-list"))
        self.assertEqual(response.data["results"], [])
        response = self.as_user(self.owner).get(reverse("ccrv:timekeeper-list"))
        self.assertEqual([t["id"] for t in response.data["results"]], [self.timer.pk])


class SessionTimerAccessTests(SessionTimerTestCase):
    def test_viewers_can_open_but_not_run_the_timer(self):
        self.assertEqual(self.as_user(self.viewer).get(self.action_url("detail")).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.as_user(self.viewer).post(self.action_url("start-timer")).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_editors_can_start_stop_and_reset_the_timer(self):
        client = self.as_user(self.editor)
        self.assertEqual(client.post(self.action_url("start-timer")).status_code, status.HTTP_200_OK)
        self.assertEqual(client.post(self.action_url("stop-timer")).status_code, status.HTTP_200_OK)
        self.assertEqual(client.post(self.action_url("reset")).status_code, status.HTTP_200_OK)

    def test_staff_can_run_the_timer(self):
        staff = UserFactory.create_user(username="staff", is_staff=True)
        response = self.as_user(staff).post(self.action_url("start-timer"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_others_cannot_open_the_timer(self):
        response = self.as_user(self.stranger).get(self.action_url("detail"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_creating_a_session_timer_needs_edit_access(self):
        body = {"session": self.session.pk, "step": self.step.pk, "current_duration": 30}
        url = reverse("ccrv:timekeeper-list")
        self.assertEqual(self.as_user(self.viewer).post(url, body, format="json").status_code, 403)
        self.assertEqual(self.as_user(self.editor).post(url, body, format="json").status_code, 201)
        self.assertEqual(TimeKeeper.objects.filter(session=self.session, step=self.step).count(), 1)

    def test_creator_removed_from_the_session_loses_the_session_timer(self):
        timer = TimeKeeper.objects.create(session=self.session, step=self.step, user=self.editor, current_duration=5)
        self.session.editors.remove(self.editor)
        client = self.as_user(self.editor)
        detail = reverse("ccrv:timekeeper-detail", kwargs={"pk": timer.pk})
        self.assertEqual(client.get(detail).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(client.delete(detail).status_code, status.HTTP_404_NOT_FOUND)
        listed = [t["id"] for t in client.get(reverse("ccrv:timekeeper-list")).data["results"]]
        self.assertNotIn(timer.pk, listed)

    def test_only_the_creator_runs_a_timer_outside_a_session(self):
        own = TimeKeeper.objects.create(user=self.editor, current_duration=10)
        url = reverse("ccrv:timekeeper-start-timer", kwargs={"pk": own.pk})
        self.assertEqual(self.as_user(self.owner).post(url).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.as_user(self.editor).post(url).status_code, status.HTTP_200_OK)


class SessionTimerNotificationTests(SessionTimerTestCase):
    def test_session_timer_updates_go_to_the_session_owner_editors_and_viewers(self):
        self.timer.user = self.stranger
        self.assertEqual(timekeeper_recipients(self.timer), {self.owner.pk, self.editor.pk, self.viewer.pk})

    def test_updates_for_timers_outside_a_session_go_to_the_creator(self):
        own = TimeKeeper.objects.create(user=self.editor, current_duration=10)
        self.assertEqual(timekeeper_recipients(own), {self.editor.pk})
