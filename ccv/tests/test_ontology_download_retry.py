"""Ontology downloads retry connection errors, timeouts and temporary server errors."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import requests

from ccv.data_sources import DOWNLOAD_ATTEMPTS, download


def response_with(status_code):
    """A mocked HTTP response with the given status code."""
    response = MagicMock()
    response.status_code = status_code
    return response


@patch("ccv.data_sources.time.sleep")
@patch("ccv.data_sources.requests.get")
class OntologyDownloadRetryTests(SimpleTestCase):
    def test_a_gateway_timeout_is_retried(self, get, sleep):
        get.side_effect = [response_with(504), response_with(200)]
        self.assertEqual(download("https://example.org/psi-ms.obo", timeout=120).status_code, 200)
        self.assertEqual(get.call_count, 2)

    def test_connection_errors_are_retried(self, get, sleep):
        get.side_effect = [requests.ConnectionError("reset"), response_with(200)]
        self.assertEqual(download("https://example.org/bto.obo", timeout=120).status_code, 200)

    def test_the_last_temporary_error_is_returned_after_every_attempt(self, get, sleep):
        get.return_value = response_with(503)
        self.assertEqual(download("https://example.org/cl.obo", timeout=120).status_code, 503)
        self.assertEqual(get.call_count, DOWNLOAD_ATTEMPTS)

    def test_client_errors_are_not_retried(self, get, sleep):
        get.return_value = response_with(404)
        self.assertEqual(download("https://example.org/missing.obo", timeout=120).status_code, 404)
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()
