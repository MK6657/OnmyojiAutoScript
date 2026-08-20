import asyncio
import unittest
from types import SimpleNamespace

from module.server.security import authorize_websocket
from server import _is_loopback_bind


class _FakeWebSocket:
    def __init__(self, *, remote_access, key=None, header_key=None):
        self.app = SimpleNamespace(
            state=SimpleNamespace(remote_access=remote_access, api_key=key)
        )
        self.headers = {}
        if header_key is not None:
            self.headers["x-oas-key"] = header_key
        self.closed = None

    async def close(self, **kwargs):
        self.closed = kwargs


class SecurityBoundaryTest(unittest.TestCase):
    def test_loopback_bind_detection(self):
        for host in ("localhost", "127.0.0.1", "::1", "[::1]"):
            with self.subTest(host=host):
                self.assertTrue(_is_loopback_bind(host))
        for host in ("0.0.0.0", "192.168.1.20", "example.invalid"):
            with self.subTest(host=host):
                self.assertFalse(_is_loopback_bind(host))

    def test_websocket_requires_key_only_when_remote_access_is_enabled(self):
        local = _FakeWebSocket(remote_access=False, key="secret")
        self.assertTrue(asyncio.run(authorize_websocket(local)))
        self.assertIsNone(local.closed)

        missing = _FakeWebSocket(remote_access=True, key="secret")
        self.assertFalse(asyncio.run(authorize_websocket(missing)))
        self.assertEqual(missing.closed["code"], 1008)

        valid = _FakeWebSocket(remote_access=True, key="secret", header_key="secret")
        self.assertTrue(asyncio.run(authorize_websocket(valid)))
        self.assertIsNone(valid.closed)


if __name__ == "__main__":
    unittest.main()
