import unittest
from types import SimpleNamespace

from module.server.script_router import handle_script_command


class FakeSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


class FakeScriptProcess:
    def __init__(self, *, fail=False):
        self.state = 0
        self._run_id = None
        self.fail = fail
        self.calls = []

    async def start(self, source):
        self.calls.append(("start", source))
        if self.fail:
            raise RuntimeError("spawn failed")
        self.state = 1
        self._run_id = "run-1"
        return True

    async def stop(self, source):
        self.calls.append(("stop", source))
        self.state = 0
        return True


class CommandProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def test_json_command_has_accepted_and_completed_receipts(self):
        websocket = FakeSocket()
        process = FakeScriptProcess()

        handled = await handle_script_command(
            process,
            websocket,
            {"command_id": "cmd-1", "command": "start"},
        )

        self.assertTrue(handled)
        self.assertEqual(process.calls, [("start", "ws:cmd-1")])
        self.assertEqual(
            [message["status"] for message in websocket.messages],
            ["accepted", "completed"],
        )
        self.assertEqual(websocket.messages[-1]["command_id"], "cmd-1")
        self.assertTrue(websocket.messages[-1]["success"])
        self.assertEqual(websocket.messages[-1]["run_id"], "run-1")

    async def test_execution_failure_is_returned_with_reason(self):
        websocket = FakeSocket()
        process = FakeScriptProcess(fail=True)

        handled = await handle_script_command(
            process,
            websocket,
            {"command_id": "cmd-2", "command": "start"},
        )

        self.assertTrue(handled)
        self.assertEqual(websocket.messages[-1]["status"], "failed")
        self.assertFalse(websocket.messages[-1]["success"])
        self.assertIn("spawn failed", websocket.messages[-1]["reason"])

    async def test_unknown_json_command_is_rejected_without_execution(self):
        websocket = FakeSocket()
        process = FakeScriptProcess()

        handled = await handle_script_command(
            process,
            websocket,
            {"command_id": "cmd-3", "command": "erase"},
        )

        self.assertTrue(handled)
        self.assertEqual(process.calls, [])
        self.assertEqual(websocket.messages, [{
            "type": "command_result",
            "command_id": "cmd-3",
            "command": "erase",
            "status": "failed",
            "success": False,
            "reason": "unsupported_command",
        }])


if __name__ == "__main__":
    unittest.main()
