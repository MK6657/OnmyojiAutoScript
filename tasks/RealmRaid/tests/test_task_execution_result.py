import unittest
from datetime import datetime
from unittest.mock import patch

from module.exception import FailureAction, TaskEnd, TaskExecutionResult
from script import Script
from tasks.RealmRaid.script_task import ScriptTask


class RealmRaidOutcomeHarness:
    finish_level_mode = ScriptTask.finish_level_mode
    I_BACK_RED = object()
    I_CHECK_EXPLORATION = object()

    def __init__(self):
        self.schedules = []

    def ui_click(self, *_args):
        return None

    def ui_get_current_page(self):
        return None

    def ui_goto(self, _page):
        return True

    def set_next_run(self, **kwargs):
        self.schedules.append(kwargs)


class TaskExecutionResultTest(unittest.TestCase):
    def test_task_end_factories_map_to_explicit_failure_actions(self):
        cases = (
            (TaskEnd.completed('done'), FailureAction.RESET),
            (TaskEnd.deferred('later'), FailureAction.PRESERVE),
            (TaskEnd.stopped('manual stop'), FailureAction.PRESERVE),
            (TaskEnd.failed('battle failed'), FailureAction.INCREMENT),
        )

        for error, expected in cases:
            with self.subTest(outcome=error.outcome):
                result = TaskExecutionResult.from_task_end(error)
                self.assertEqual(result.failure_action, expected)

    def test_failure_counter_only_changes_for_success_or_explicit_failure(self):
        self.assertEqual(TaskExecutionResult.completed('done').next_failure_count(2), 0)
        self.assertEqual(TaskExecutionResult.deferred('later').next_failure_count(2), 2)
        self.assertEqual(TaskExecutionResult.stopped('manual').next_failure_count(2), 2)
        self.assertEqual(TaskExecutionResult.failed('battle').next_failure_count(2), 3)

    def test_scheduler_records_structured_failure_action(self):
        scheduler = Script.__new__(Script)
        scheduler.config_name = 'oas-test'
        scheduler.failure_record = {'RealmRaid': 2}
        with patch.object(Script, '_save_failure_record', lambda self: None):
            self.assertEqual(
                scheduler._record_task_result(
                    'RealmRaid', TaskExecutionResult.deferred('later')
                ),
                2,
            )
            self.assertEqual(
                scheduler._record_task_result(
                    'RealmRaid', TaskExecutionResult.stopped('manual')
                ),
                2,
            )
            self.assertEqual(
                scheduler._record_task_result(
                    'RealmRaid', TaskExecutionResult.failed('battle')
                ),
                3,
            )
            self.assertEqual(
                scheduler._record_task_result(
                    'RealmRaid', TaskExecutionResult.completed('done')
                ),
                0,
            )

    def test_realm_raid_manual_pause_preserves_failure_counter(self):
        harness = RealmRaidOutcomeHarness()

        with self.assertRaises(TaskEnd) as caught:
            harness.finish_level_mode(success=False, reason='test_paused')

        self.assertEqual(caught.exception.outcome, 'stopped')
        self.assertEqual(caught.exception.failure_action, FailureAction.PRESERVE)

    def test_realm_raid_deferred_cooldown_preserves_failure_counter(self):
        harness = RealmRaidOutcomeHarness()
        retry_at = datetime(2026, 8, 10, 12, 0, 0)

        with self.assertRaises(TaskEnd) as caught:
            harness.finish_level_mode(
                success=False,
                target=retry_at,
                reason='refresh_cooldown',
            )

        self.assertEqual(caught.exception.outcome, 'deferred')
        self.assertEqual(caught.exception.failure_action, FailureAction.PRESERVE)

    def test_realm_raid_unconfirmed_battle_is_explicit_failure(self):
        harness = RealmRaidOutcomeHarness()
        retry_at = datetime(2026, 8, 10, 12, 0, 0)

        with self.assertRaises(TaskEnd) as caught:
            harness.finish_level_mode(
                success=False,
                target=retry_at,
                reason='attack_unconfirmed',
            )

        self.assertEqual(caught.exception.outcome, 'failed')
        self.assertEqual(caught.exception.failure_action, FailureAction.INCREMENT)


if __name__ == '__main__':
    unittest.main()
