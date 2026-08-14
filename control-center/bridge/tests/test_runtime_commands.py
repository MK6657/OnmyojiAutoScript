import asyncio
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import (  # noqa: E402
    AccountRuntime,
    CommandExecutionError,
    CommandInProgress,
    CommandNotAccepted,
)


class FakeEvents:
    async def emit(self, *_args, **_kwargs):
        return None


class FakeWebSocket:
    def __init__(self, runtime, *, reply=True, success=True,
                 ack_delay=0.0, result_delay=0.0, send_ack=True, send_result=True):
        self.runtime = runtime
        self.reply = reply
        self.success = success
        self.ack_delay = ack_delay
        self.result_delay = result_delay
        self.send_ack = send_ack
        self.send_result = send_result
        self.sent = []

    async def send(self, message):
        self.sent.append(message)
        if not self.reply:
            return
        import json

        request = json.loads(message)

        async def deliver(delay, payload):
            if delay:
                await asyncio.sleep(delay)
            await self.runtime._handle_message(json.dumps(payload))

        # DeepSeek-14 B1: real sockets return immediately; deliveries arrive
        # asynchronously, so schedule them as background tasks.
        loop = asyncio.get_running_loop()
        if self.send_ack:
            loop.create_task(deliver(self.ack_delay, {
                "type": "command_ack",
                "command_id": request["command_id"],
                "command": request["command"],
                "status": "accepted",
            }))
        if self.send_result:
            loop.create_task(deliver(self.result_delay, {
                "type": "command_result",
                "command_id": request["command_id"],
                "command": request["command"],
                "status": "completed" if self.success else "failed",
                "success": self.success,
                "changed": True,
                "reason": None if self.success else "process_still_alive",
            }))


class RuntimeCommandTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = AccountRuntime("oas1", "ws://fake", FakeEvents())
        self.runtime.connected = True
        self.runtime.wait_connected = self._connected

    async def _connected(self, timeout=2.0):
        return True

    async def test_command_waits_for_core_completion(self):
        websocket = FakeWebSocket(self.runtime)
        self.runtime._websocket = websocket

        result = await self.runtime.command("start", timeout=0.2)

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["success"])
        self.assertEqual(len(websocket.sent), 1)
        self.assertIn("command_id", websocket.sent[0])

    async def test_send_without_result_times_out(self):
        self.runtime._websocket = FakeWebSocket(self.runtime, reply=False)

        # DeepSeek-14 B1: no ack and no receipt -> CommandNotAccepted, which
        # authorizes the same-command_id REST fallback (Core-side ledger).
        with self.assertRaises(CommandNotAccepted):
            await self.runtime.command("start", timeout=0.01)
        self.assertEqual(len(self.runtime._pending_commands), 1)
        self.assertIn(self.runtime._last_command_id, self.runtime._pending_commands)

    async def test_ack_without_result_is_in_progress(self):
        self.runtime._websocket = FakeWebSocket(
            self.runtime, send_result=False)

        with self.assertRaises(CommandInProgress) as ctx:
            await self.runtime.command("start", timeout=0.01)
        self.assertEqual(
            ctx.exception.command_id, self.runtime._last_command_id)
        # never a failure, never re-issuable: pending survives for the grace window
        self.assertIn(self.runtime._last_command_id, self.runtime._pending_commands)

    async def test_receipt_without_ack_is_adopted(self):
        # ack lost, but the command executed and the receipt arrives within the
        # wait window: shielded future must adopt it, no fallback needed.
        self.runtime._websocket = FakeWebSocket(
            self.runtime, send_ack=False, result_delay=0.05)

        result = await self.runtime.command("start", timeout=0.01)
        self.assertTrue(result["success"])
        self.assertIn(self.runtime._last_command_id, self.runtime._late_results)

    async def test_receipt_after_request_ends_lands_in_query_channel(self):
        # receipt arrives only after the HTTP-side wait ended; the query
        # channel must be able to serve it.
        self.runtime._websocket = FakeWebSocket(
            self.runtime, send_ack=True, result_delay=0.35)

        with self.assertRaises(CommandInProgress):
            await self.runtime.command("start", timeout=0.01)
        cid = self.runtime._last_command_id
        await asyncio.sleep(0.5)  # receipt lands after the request window
        future = self.runtime._pending_commands.get(cid)
        done = future is not None and future.done() and not future.cancelled()
        self.assertTrue(done)
        if done:
            self.assertTrue(future.result().get("success"))

    async def test_execution_failure_is_not_downgraded_to_transport_fallback(self):
        self.runtime._websocket = FakeWebSocket(self.runtime, success=False)

        with self.assertRaisesRegex(CommandExecutionError, "process_still_alive"):
            await self.runtime.try_command("stop")


if __name__ == "__main__":
    unittest.main()
