# DeepSeek-14 O14-6: EventHub heartbeat task must never cancel itself, and
# external disconnects must reap the heartbeat cleanly.
import asyncio
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.events import EventHub  # noqa: E402


class FakeWebSocket:
    def __init__(self, *, fail_send=False):
        self.accepted = False
        self.sent = []
        self.fail_send = fail_send

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(("json", payload))

    async def send_text(self, text):
        self.sent.append(("text", text))
        if self.fail_send:
            raise ConnectionError("pipe gone")


class HeartbeatRaceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hub = EventHub()
        self.hub.HEARTBEAT_INTERVAL = 0.01  # fast loop for tests

    async def test_send_failure_ends_task_cleanly_not_cancelled(self):
        ws = FakeWebSocket(fail_send=True)
        await self.hub.connect(ws)
        task = self.hub._heartbeats.get(id(ws))
        self.assertIsNotNone(task)
        await asyncio.wait_for(task, timeout=1.0)
        # self-initiated exit: the task finished (not cancelled) and cleaned up
        self.assertFalse(task.cancelled())
        self.assertNotIn(id(ws), self.hub._heartbeats)
        self.assertNotIn(ws, self.hub._connections)

    async def test_external_disconnect_cancels_heartbeat_without_self_cancel(self):
        ws = FakeWebSocket()
        await self.hub.connect(ws)
        task = self.hub._heartbeats.get(id(ws))
        await self.hub.disconnect(ws)
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertNotIn(id(ws), self.hub._heartbeats)
        self.assertNotIn(ws, self.hub._connections)
        # disconnect after the fact stays idempotent
        await self.hub.disconnect(ws)

    async def test_heartbeat_sends_ping_frames(self):
        ws = FakeWebSocket()
        await self.hub.connect(ws)
        await asyncio.sleep(0.1)
        pings = [payload for kind, payload in ws.sent if kind == "text"]
        self.assertGreaterEqual(len(pings), 1)
        self.assertEqual(json.loads(pings[0])["type"], "bridge.ping")
        await self.hub.disconnect(ws)


if __name__ == "__main__":
    unittest.main()
