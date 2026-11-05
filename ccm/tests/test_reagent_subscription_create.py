"""Reagent subscriptions created for the requesting user."""

from django.contrib.auth.models import User
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from ccm.models import Reagent, ReagentSubscription, StoredReagent


class ReagentSubscriptionCreateTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="subscriber")
        self.other = User.objects.create_user(username="other")
        reagent = Reagent.objects.create(name="Trypsin", unit="ug")
        self.stored = StoredReagent.objects.create(reagent=reagent, quantity=5, user=self.user)
        self.client.force_authenticate(user=self.user)

    def test_subscription_is_created_without_a_user_in_the_request(self):
        response = self.client.post(
            reverse("ccm:reagentsubscription-list"),
            {"stored_reagent": self.stored.id, "notify_on_low_stock": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertEqual(ReagentSubscription.objects.get().user, self.user)

    def test_a_user_in_the_request_is_ignored(self):
        response = self.client.post(
            reverse("ccm:reagentsubscription-list"),
            {"stored_reagent": self.stored.id, "user": self.other.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertEqual(ReagentSubscription.objects.get().user, self.user)
