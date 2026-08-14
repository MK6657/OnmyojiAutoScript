import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from module.server.script_process import ProcessStopError, ScriptState
from module.server.script_router import config_delete, config_rename, script_stop


class FakeProcess:
    def __init__(self):
        self.state = ScriptState.WARNING
        self._run_id = "run-stuck"
        self._process = object()
        self.stop = AsyncMock(side_effect=ProcessStopError("process_still_alive"))


class FakeManager:
    def __init__(self):
        self.process = FakeProcess()
        self.removed = []
        self.renamed = []
        self.deleted = []

    def get_script_process(self, _name, create=False):
        return self.process

    def remove_script_process(self, name):
        self.removed.append(name)

    def rename(self, old_name, new_name):
        self.renamed.append((old_name, new_name))
        return True

    def delete(self, name):
        self.deleted.append(name)
        return True


class AccountMutationGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_rest_stop_reports_still_alive_as_conflict(self):
        manager = FakeManager()
        with patch("module.server.script_router.mm", manager):
            with self.assertRaises(HTTPException) as caught:
                await script_stop("oas1")
        self.assertEqual(caught.exception.status_code, 409)

    async def test_rename_does_not_remove_or_rename_after_stop_failure(self):
        manager = FakeManager()
        with patch("module.server.script_router.mm", manager):
            with self.assertRaises(HTTPException) as caught:
                await config_rename("oas1", "oas2")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(manager.removed, [])
        self.assertEqual(manager.renamed, [])

    async def test_delete_does_not_remove_or_delete_after_stop_failure(self):
        manager = FakeManager()
        with patch("module.server.script_router.mm", manager):
            with self.assertRaises(HTTPException) as caught:
                await config_delete("oas1")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(manager.removed, [])
        self.assertEqual(manager.deleted, [])


if __name__ == "__main__":
    unittest.main()
