import asyncio
import multiprocessing
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from module.server.script_process import (
    AccountRunLease,
    ProcessStopError,
    ScriptProcess,
    ScriptState,
)


def _hold_account_lease(account_name, ready, release):
    lease = AccountRunLease(account_name)
    ready.put(lease.acquire())
    release.wait(10)
    lease.release()


class FakeProcess:
    next_pid = 4100
    start_hook = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.pid = None
        self.exitcode = None
        self.alive = False
        self.terminate_calls = 0
        self.kill_calls = 0
        self.ignore_terminate = False
        self.ignore_kill = False

    def start(self):
        if FakeProcess.start_hook is not None:
            FakeProcess.start_hook()
        self.pid = FakeProcess.next_pid
        FakeProcess.next_pid += 1
        self.alive = True

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.terminate_calls += 1
        if not self.ignore_terminate:
            self.alive = False
            self.exitcode = -15

    def kill(self):
        self.kill_calls += 1
        if not self.ignore_kill:
            self.alive = False
            self.exitcode = -9

    def join(self, timeout=None):
        return None


class ScriptProcessLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeProcess.start_hook = None
        with patch(
            'module.server.script_process.ConfigManager.all_script_files',
            return_value=['oas1', 'oas2'],
        ):
            self.process = ScriptProcess('oas1')
        self.owned_processes = [self.process]
        self.created = []

        def make_process(*args, **kwargs):
            process = FakeProcess(*args, **kwargs)
            self.created.append(process)
            return process

        self.process_factory = patch(
            'module.server.script_process.multiprocessing.Process',
            side_effect=make_process,
        )
        self.process_factory.start()
        self.addAsyncCleanup(self.process_factory.stop)

    async def asyncTearDown(self):
        FakeProcess.start_hook = None
        for process in self.owned_processes:
            child = process._process
            if child is not None:
                child.alive = False
                child.exitcode = child.exitcode if child.exitcode is not None else 0
                process._reap_dead_process()
            process._account_lease.release()

    async def test_concurrent_start_is_idempotent_per_account(self):
        results = await asyncio.gather(
            self.process.start(source='rest'),
            self.process.start(source='ws'),
        )

        self.assertEqual(len(self.created), 1)
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.process.state, ScriptState.RUNNING)
        self.assertEqual(self.created[0].terminate_calls, 0)

    async def test_repeated_start_does_not_stop_existing_child(self):
        self.assertTrue(await self.process.start(source='auto'))
        child = self.process._process

        self.assertFalse(await self.process.start(source='rest'))
        self.assertIs(self.process._process, child)
        self.assertEqual(child.terminate_calls, 0)
        self.assertEqual(len(self.created), 1)

    async def test_dead_child_is_reconciled_to_inactive(self):
        await self.process.start(source='auto')
        child = self.process._process
        child.alive = False
        child.exitcode = 1

        self.assertTrue(await self.process._sync_dead_process())
        self.assertIsNone(self.process._process)
        self.assertEqual(self.process.state, ScriptState.INACTIVE)

    async def test_stop_then_start_has_one_live_final_child(self):
        await self.process.start(source='auto')
        first = self.process._process

        await asyncio.gather(
            self.process.stop(source='rest'),
            self.process.start(source='ws'),
        )

        self.assertEqual(first.terminate_calls, 1)
        self.assertEqual(len(self.created), 2)
        self.assertTrue(self.process._process.is_alive())
        self.assertEqual(self.process.state, ScriptState.RUNNING)

    async def test_different_accounts_use_independent_lifecycle_locks(self):
        with patch(
            'module.server.script_process.ConfigManager.all_script_files',
            return_value=['oas1', 'oas2'],
        ):
            other = ScriptProcess('oas2')
        self.owned_processes.append(other)

        results = await asyncio.gather(
            self.process.start(source='rest'),
            other.start(source='auto'),
        )

        self.assertEqual(results, [True, True])
        self.assertEqual(len(self.created), 2)
        self.assertTrue(self.process._process.is_alive())
        self.assertTrue(other._process.is_alive())

    async def test_process_is_not_published_until_start_succeeds(self):
        reaper_results = []
        FakeProcess.start_hook = lambda: reaper_results.append(
            self.process._reap_dead_process()
        )

        self.assertTrue(await self.process.start(source='rest'))

        self.assertEqual(reaper_results, [None])
        self.assertIs(self.process._process, self.created[0])
        self.assertTrue(self.process._process.is_alive())

    async def test_each_run_uses_new_queue_and_pipe(self):
        self.assertTrue(await self.process.start(source='rest'))
        first_args = self.created[0].kwargs['args']
        self.assertTrue(await self.process.stop(source='rest'))
        self.assertTrue(await self.process.start(source='rest'))
        second_args = self.created[1].kwargs['args']

        self.assertIsNot(first_args[1], second_args[1])
        self.assertIsNot(first_args[2], second_args[2])

    async def test_failed_kill_keeps_process_ipc_and_account_ownership(self):
        self.assertTrue(await self.process.start(source='rest'))
        child = self.process._process
        queue = self.process.state_queue
        pipe = self.process.log_pipe_out
        lease = self.process._account_lease
        child.ignore_terminate = True
        child.ignore_kill = True

        with self.assertRaises(ProcessStopError):
            await self.process.stop(source='rest')

        self.assertIs(self.process._process, child)
        self.assertIs(self.process.state_queue, queue)
        self.assertIs(self.process.log_pipe_out, pipe)
        self.assertIs(self.process._account_lease, lease)
        self.assertTrue(lease.acquired)
        self.assertEqual(self.process.state, ScriptState.WARNING)
        self.assertEqual(child.terminate_calls, 1)
        self.assertEqual(child.kill_calls, 1)
        with self.assertRaises(ProcessStopError):
            await self.process.start(source='rest')

    async def test_repeated_start_stop_never_leaves_duplicate_live_children(self):
        for _index in range(25):
            results = await asyncio.gather(
                self.process.start(source='rest'),
                self.process.start(source='ws'),
            )
            self.assertEqual(sorted(results), [False, True])
            self.assertEqual(sum(child.is_alive() for child in self.created), 1)
            self.assertTrue(await self.process.stop(source='rest'))
            self.assertEqual(sum(child.is_alive() for child in self.created), 0)


class AccountRunLeaseTest(unittest.TestCase):
    def test_second_process_cannot_acquire_and_crash_releases_lease(self):
        account_name = f'test-{uuid4().hex}'
        context = multiprocessing.get_context('spawn')
        ready = context.Queue()
        release = context.Event()
        owner = context.Process(
            target=_hold_account_lease,
            args=(account_name, ready, release),
        )
        owner.start()
        self.addCleanup(lambda: owner.is_alive() and owner.kill())
        self.assertTrue(ready.get(timeout=5))

        contender = AccountRunLease(account_name)
        self.assertFalse(contender.acquire())

        owner.kill()
        owner.join(timeout=5)
        self.assertFalse(owner.is_alive())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not contender.acquire():
            time.sleep(0.05)
        self.assertTrue(contender.acquired)
        contender.release()


if __name__ == '__main__':
    unittest.main()
