import unittest
from types import SimpleNamespace
from unittest.mock import patch

from module.exception import GameStuckError, TaskEnd
from tasks.Exploration.base import (
    BaseExploration,
    ExplorationBudgetExceeded,
    ExplorationSearchBudget,
)
from tasks.Exploration.solo import ScriptTask, SoloExploration


class LevelSelectionHarness:
    open_expect_level = BaseExploration.open_expect_level
    LEVEL_SEARCH_MAX_SWIPES = 2
    LEVEL_SEARCH_TIMEOUT = 30
    LEVEL_SELECTION_MAX_ATTEMPTS = 2
    LEVEL_SELECTION_TIMEOUT = 30

    I_E_EXPLORATION_CLICK = object()
    I_UI_CONFIRM = object()
    I_UI_CONFIRM_SAMLL = object()
    S_SWIPE_LEVEL_UP = object()

    def __init__(self):
        self.appear_calls = 0
        self.device = SimpleNamespace(image=None, click_record_clear=lambda: None)
        self.config = SimpleNamespace(
            exploration=SimpleNamespace(
                exploration_config=SimpleNamespace(exploration_level='28')
            )
        )
        self.O_E_EXPLORATION_LEVEL_NUMBER = SimpleNamespace(
            keyword='', detect_and_ocr=lambda _image: []
        )

    def screenshot(self):
        return None

    def appear(self, target, **_kwargs):
        if target is self.I_E_EXPLORATION_CLICK:
            self.appear_calls += 1
            return self.appear_calls == 1
        return False

    def appear_then_click(self, *_args, **_kwargs):
        return False

    def ocr_appear_click(self, *_args, **_kwargs):
        return False

    def wait_until_appear(self, *_args, **_kwargs):
        return False

    def is_in_room(self):
        return False

    def swipe(self, *_args, **_kwargs):
        return True


class BuffRestoreHarness:
    _restore_exploration_buff_states = BaseExploration._restore_exploration_buff_states

    def __init__(self):
        self._exploration_buff_snapshot = {'gold_50': True, 'exp_50': False}
        self.calls = []

    def open_buff(self):
        self.calls.append(('open',))
        return True

    def close_buff(self):
        self.calls.append(('close',))
        return True

    def gold_50(self, is_open=True):
        self.calls.append(('gold_50', is_open))
        return True

    def exp_50(self, is_open=True):
        self.calls.append(('exp_50', is_open))
        return True


class BudgetAbortHarness:
    run = ScriptTask.run

    def __init__(self):
        self.calls = []

    def _prepare_startup(self):
        raise ExplorationBudgetExceeded(
            'swipe_budget_exhausted',
            recognitions=20,
            swipes=8,
            elapsed=30,
        )

    def quit_explore(self, *, reason):
        self.calls.append(('quit', reason.value))
        return True

    def _restore_buffs_after_error(self):
        self.calls.append(('restore',))

    def set_next_run(self, **kwargs):
        self.calls.append(('schedule', kwargs))
        return SimpleNamespace(when='tomorrow')


class ExplorationHardBoundaryTest(unittest.TestCase):
    def test_search_budget_reports_recognition_limit(self):
        budget = ExplorationSearchBudget(
            timeout_seconds=60,
            max_recognitions=2,
            max_swipes=1,
        )
        budget.record_recognition()
        budget.record_recognition()

        with self.assertRaises(ExplorationBudgetExceeded) as raised:
            budget.record_recognition()

        self.assertEqual(raised.exception.reason, 'recognition_budget_exhausted')

    def test_search_budget_reports_swipe_limit(self):
        budget = ExplorationSearchBudget(
            timeout_seconds=60,
            max_recognitions=5,
            max_swipes=1,
        )
        budget.record_swipe()

        with self.assertRaises(ExplorationBudgetExceeded) as raised:
            budget.record_swipe()

        self.assertEqual(raised.exception.reason, 'swipe_budget_exhausted')

    def test_level_selection_has_attempt_boundary(self):
        harness = LevelSelectionHarness()

        with patch('tasks.Exploration.base.time.sleep'):
            with self.assertRaises(GameStuckError) as raised:
                harness.open_expect_level()

        self.assertIn('selection_budget_exhausted', str(raised.exception))

    def test_configured_buff_state_is_restored_exactly(self):
        harness = BuffRestoreHarness()

        self.assertTrue(harness._restore_exploration_buff_states())

        self.assertEqual(
            harness.calls,
            [('open',), ('gold_50', True), ('exp_50', False), ('close',)],
        )
        self.assertIsNone(harness._exploration_buff_snapshot)

    def test_unavailable_buff_is_left_untouched_and_snapshot_is_cleared(self):
        harness = BuffRestoreHarness()
        harness._exploration_buff_snapshot = {
            'gold_50': BaseExploration.BUFF_UNAVAILABLE,
            'exp_50': False,
        }

        self.assertTrue(harness._restore_exploration_buff_states())

        self.assertEqual(
            harness.calls,
            [('open',), ('exp_50', False), ('close',)],
        )
        self.assertIsNone(harness._exploration_buff_snapshot)

    def test_skipped_swipe_does_not_consume_map_budget(self):
        budget = ExplorationSearchBudget(60, 20, 2)
        harness = SimpleNamespace(_exploration_last_swipe_failure='skipped')

        SoloExploration._record_exploration_swipe_attempt(harness, budget)

        self.assertEqual(budget.swipes, 0)

    def test_executed_swipe_consumes_map_budget(self):
        budget = ExplorationSearchBudget(60, 20, 2)
        harness = SimpleNamespace(_exploration_last_swipe_failure=None)

        SoloExploration._record_exploration_swipe_attempt(harness, budget)

        self.assertEqual(budget.swipes, 1)

    def test_budget_exhaustion_schedules_failure_without_game_restart(self):
        harness = BudgetAbortHarness()

        with self.assertRaises(TaskEnd) as raised:
            harness.run()

        self.assertFalse(raised.exception.success)
        self.assertEqual(raised.exception.statistics['reason'], 'swipe_budget_exhausted')
        self.assertEqual(
            [call[0] for call in harness.calls],
            ['quit', 'restore', 'schedule'],
        )


if __name__ == '__main__':
    unittest.main()
