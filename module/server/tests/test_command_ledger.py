# DeepSeek-14 B1/A1 v2: claim-based command ledger tests.
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("OAS_TEST_LOGDIR", tempfile.mkdtemp(prefix="oas-test-logs-"))

from module.server import script_router as sr  # noqa: E402


class CommandLedgerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        sr._COMMAND_LEDGER.clear()

    def test_first_claim_wins_and_duplicate_is_in_progress(self):
        first = sr._ledger_claim("cmd-x", "start", "oas1")
        self.assertTrue(first["ok"])
        second = sr._ledger_claim("cmd-x", "start", "oas1")
        self.assertFalse(second["ok"])
        self.assertEqual(second["status"], "in_progress")

    def test_same_id_different_command_is_conflict(self):
        sr._ledger_claim("cmd-x", "start", "oas1")
        conflict = sr._ledger_claim("cmd-x", "stop", "oas1")
        self.assertEqual(conflict["status"], "conflict")

    def test_same_id_different_account_is_conflict(self):
        sr._ledger_claim("cmd-x", "start", "oas1")
        conflict = sr._ledger_claim("cmd-x", "start", "oas2")
        self.assertEqual(conflict["status"], "conflict")

    def test_completed_replay_returns_stored_result(self):
        sr._ledger_claim("cmd-x", "start", "oas1")
        payload = {"status": "completed", "success": True, "changed": True,
                   "state": 1, "run_id": "run-x"}
        sr._ledger_complete("cmd-x", payload)
        replay = sr._ledger_claim("cmd-x", "start", "oas1")
        self.assertFalse(replay["ok"])
        self.assertEqual(replay["status"], "completed")
        self.assertEqual(replay["result"], payload)

    def test_ttl_reaps_terminal_but_never_in_progress(self):
        # DeepSeek-14 B1 v3: an active in_progress entry must survive any TTL.
        sr._ledger_claim("cmd-live", "start", "oas1")
        sr._COMMAND_LEDGER["cmd-live"]["stamp"] = 0.0
        with patch.object(sr.time, "monotonic", return_value=301.0):
            still_active = sr._ledger_claim("cmd-live", "start", "oas1")
        self.assertFalse(still_active["ok"])
        self.assertEqual(still_active["status"], "in_progress")

        # a completed entry is reaped after TTL
        sr._ledger_claim("cmd-done", "start", "oas1")
        sr._ledger_complete("cmd-done", {"status": "completed", "success": True})
        sr._COMMAND_LEDGER["cmd-done"]["stamp"] = 0.0
        with patch.object(sr.time, "monotonic", return_value=301.0):
            fresh = sr._ledger_claim("cmd-done", "start", "oas1")
        self.assertTrue(fresh["ok"])

    async def test_rest_start_in_progress_does_not_execute(self):
        # WS already claimed and is executing; REST with the same id must NOT
        # execute again and must report in_progress.
        sr._ledger_claim("cmd-live", "start", "oas1")

        class FakeProcess:
            start_calls = 0

            async def start(self, source):
                FakeProcess.start_calls += 1
                return True

        with patch.object(sr.mm, "get_script_process", return_value=FakeProcess()):
            result = await sr.script_start("oas1", command_id="cmd-live")
        self.assertEqual(result, {"status": "in_progress", "command_id": "cmd-live"})
        self.assertEqual(FakeProcess.start_calls, 0)

    async def test_rest_start_conflict_raises_409(self):
        sr._ledger_claim("cmd-x", "stop", "oas1")  # different fingerprint
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            await sr.script_start("oas1", command_id="cmd-x")
        self.assertEqual(caught.exception.status_code, 409)

    async def test_rest_start_fresh_claim_executes_and_completes(self):
        class FakeProcess:
            def __init__(self):
                self._run_id = "run-live"
                self.state = 1

            async def start(self, source):
                return True

        with patch.object(sr.mm, "get_script_process", return_value=FakeProcess()):
            result = await sr.script_start("oas1", command_id="cmd-new")
        self.assertTrue(result["success"])
        entry = sr._COMMAND_LEDGER["cmd-new"]
        self.assertEqual(entry["state"], "completed")
        self.assertEqual(entry["result"]["run_id"], "run-live")


if __name__ == "__main__":
    unittest.main()
