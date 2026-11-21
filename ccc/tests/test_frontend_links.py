"""Links in emails point at the frontend the user is on."""

from django.test import RequestFactory, SimpleTestCase, override_settings

from ccc.frontend_links import frontend_base_url, frontend_link

ORIGINS = ["https://lab.example.org", "https://vanilla.lab.example.org"]


@override_settings(CORS_ORIGIN_WHITELIST=ORIGINS, FRONTEND_URL="")
class FrontendLinkTest(SimpleTestCase):
    def request(self, origin=None):
        headers = {"HTTP_ORIGIN": origin} if origin else {}
        return RequestFactory().post("/api/v1/", **headers)

    def test_the_link_uses_the_frontend_the_request_came_from(self):
        link = frontend_link(self.request("https://vanilla.lab.example.org"), "lab-groups/invitations/4/accept")
        self.assertEqual(link, "https://vanilla.lab.example.org/#/lab-groups/invitations/4/accept")

    def test_an_origin_that_is_not_allowed_is_ignored(self):
        self.assertEqual(frontend_base_url(self.request("https://attacker.example.com")), "https://lab.example.org")

    @override_settings(FRONTEND_URL="https://main.example.org/")
    def test_without_an_allowed_origin_the_configured_frontend_is_used(self):
        self.assertEqual(
            frontend_link(self.request(), "/reset-password?uid=a&token=b"),
            "https://main.example.org/#/reset-password?uid=a&token=b",
        )

    def test_without_a_request_the_first_allowed_origin_is_used(self):
        self.assertEqual(frontend_base_url(None), "https://lab.example.org")

    @override_settings(CORS_ORIGIN_WHITELIST=[])
    def test_with_nothing_configured_the_development_server_is_used(self):
        self.assertEqual(frontend_base_url(None), "http://localhost:4200")
