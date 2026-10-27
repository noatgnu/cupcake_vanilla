"""
Socket-level tests for the appliance helper clients.

The root helpers (cupcake-storage-manager, cupcake-network-manager) read a request until the
client closes its write side, then reply. These tests serve a real Unix socket the same way, so a
client that never signals the end of its request times out instead of receiving the reply.
"""

import json
import socket
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from ccc.viewsets import ApplianceViewSet


class _HelperServer:
    """One-shot Unix socket server that behaves like the appliance root helpers."""

    def __init__(self, path, reply):
        self.path = path
        self.reply = reply
        self.received = None
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(path)
        self._server.listen(1)
        self._server.settimeout(5)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        try:
            conn, _ = self._server.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(5)
            data = b""
            try:
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            except socket.timeout:
                return
            self.received = json.loads(data.decode())
            conn.sendall(json.dumps(self.reply).encode())
            conn.shutdown(socket.SHUT_WR)

    def close(self):
        self._thread.join(timeout=10)
        self._server.close()


class ApplianceHelperSocketTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _serve(self, name, reply):
        server = _HelperServer(str(Path(self._tmp.name) / name), reply)
        self.addCleanup(server.close)
        return server

    def test_storage_command_receives_helper_reply(self):
        server = self._serve("storage.sock", {"ok": True, "output": "mounted"})
        payload = {"command": "mount", "config": {"mountType": "usb", "label": "CUPCAKE-DATA"}}

        with patch("ccc.viewsets._STORAGE_SOCK", server.path):
            result = ApplianceViewSet()._send_storage_command(payload)

        self.assertEqual(result, {"ok": True, "output": "mounted"})
        self.assertEqual(server.received, payload)

    def test_network_command_receives_helper_reply(self):
        server = self._serve("network.sock", {"ok": True, "output": "applied"})
        payload = {"command": "apply"}

        with patch("ccc.viewsets._NETWORK_SOCK", server.path):
            result = ApplianceViewSet()._send_network_command(payload)

        self.assertEqual(result, {"ok": True, "output": "applied"})
        self.assertEqual(server.received, payload)
