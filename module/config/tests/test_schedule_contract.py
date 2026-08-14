import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from module.config.config import Config, _assert_schedule_authorized
from tasks.base_task import BaseTask


class ScheduleHarness:
    schedule = Config.schedule
    task_call = Config.task_call

    def __init__(self):
        self.config_name = "test-account"
        self.saved = 0
        self.model = ScheduleModel(
            running_task="Exploration",
            realm_raid=SimpleNamespace(
                scheduler=SimpleNamespace(
                    enable=True,
                    next_run=datetime(2026, 8, 9, 9, 0, 0),
                )
            ),
            souls_tidy=SimpleNamespace(
                scheduler=SimpleNamespace(
                    enable=True,
                    next_run=datetime(2026, 8, 9, 9, 0, 0),
                )
            ),
        )

    def reload(self):
        return None

    def save(self):
        self.saved += 1


class ScheduleModel(SimpleNamespace):
    @staticmethod
    def deep_get(data, keys):
        value = data
        for key in keys.split('.'):
            value = getattr(value, key, None)
            if value is None:
                break
        return value


class ScheduleContractTest(unittest.TestCase):
    def test_schedule_caller_uses_running_task_when_available(self):
        harness = object.__new__(BaseTask)
        harness.config = SimpleNamespace(model=SimpleNamespace(running_task="RyouToppa"))

        self.assertEqual(harness._schedule_caller_identity(), "RyouToppa")

    def test_schedule_caller_recovers_dynamic_task_name_from_source_path(self):
        dynamic_task = type("ScriptTask", (BaseTask,), {"__module__": "script_task"})
        harness = object.__new__(dynamic_task)
        harness.config = SimpleNamespace(model=SimpleNamespace(running_task=""))

        with mock.patch(
            "tasks.base_task.inspect.getfile",
            return_value=r"D:\OSAyys\tasks\RyouToppa\script_task.py",
        ):
            caller = harness._schedule_caller_identity()

        self.assertEqual(caller, "RyouToppa")

    def test_schedule_records_caller_reason_and_previous_value(self):
        harness = ScheduleHarness()
        target = datetime(2026, 8, 9, 10, 0, 0)

        decision = harness.schedule(
            task="RealmRaid",
            when=target,
            reason="scroll threshold reached",
            caller="Exploration",
        )

        self.assertEqual(decision.task, "realm_raid")
        self.assertEqual(decision.when, target)
        self.assertEqual(decision.previous, datetime(2026, 8, 9, 9, 0, 0))
        self.assertEqual(decision.reason, "scroll threshold reached")
        self.assertEqual(decision.caller, "Exploration")
        self.assertEqual(harness.saved, 1)

    def test_schedule_rejects_missing_provenance(self):
        harness = ScheduleHarness()

        with self.assertRaises(ValueError):
            harness.schedule(
                task="RealmRaid",
                when=datetime(2026, 8, 9, 10, 0, 0),
                reason="",
                caller="Exploration",
            )

    def test_schedule_rejects_undeclared_cross_task_write(self):
        harness = ScheduleHarness()

        with self.assertRaisesRegex(Exception, 'not authorized'):
            harness.schedule(
                task="RealmRaid",
                when=datetime(2026, 8, 9, 10, 0, 0),
                reason="unrelated task attempted to overwrite checkpoint",
                caller="Duel",
            )

        self.assertEqual(harness.saved, 0)

    def test_schedule_allows_declared_exploration_handoff(self):
        harness = ScheduleHarness()

        decision = harness.schedule(
            task="RealmRaid",
            when=datetime(2026, 8, 9, 10, 0, 0),
            reason="scroll threshold reached",
            caller="Exploration",
        )

        self.assertEqual(decision.task, "realm_raid")
        self.assertEqual(harness.saved, 1)

    def test_task_call_cannot_bypass_cross_task_authorization(self):
        harness = ScheduleHarness()

        with self.assertRaisesRegex(Exception, 'not authorized'):
            harness.task_call('RealmRaid')

        self.assertEqual(harness.saved, 0)

    def test_task_call_allows_declared_scheduler_target(self):
        harness = ScheduleHarness()

        self.assertTrue(harness.task_call('SoulsTidy'))
        self.assertEqual(harness.saved, 1)

    def test_declared_cross_task_matrix_matches_existing_workflows(self):
        allowed = (
            ('ActivityShikigami', 'SoulsTidy'),
            ('Duel', 'TalismanPass'),
            ('Exploration', 'MemoryScrolls'),
            ('GuildActivityMonitor', 'Dokan'),
            ('Restart', 'RealmRaid'),
            ('TeamFlowHost', 'EvoZone'),
            ('ControlCenter.sync_next_run', 'RealmRaid'),
            ('AnyTask', 'WantedQuests'),
        )

        for caller, task in allowed:
            with self.subTest(caller=caller, task=task):
                _assert_schedule_authorized(task, caller)


if __name__ == "__main__":
    unittest.main()
