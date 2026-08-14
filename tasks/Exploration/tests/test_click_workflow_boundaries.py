import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

from module.atom.click import RuleClick
from module.exception import GameStuckError, GameTooManyClickError
from tasks.Exploration.base import BaseExploration
from tasks.base_task import BaseTask


class PersistentButtonHarness:
    ui_click_until_disappear = BaseTask.ui_click_until_disappear

    def __init__(self):
        self.clicks = 0
        self._last_ui_click_failure = None

    def screenshot(self):
        return None

    def appear(self, _target):
        return True

    def appear_then_click(self, _target, interval=1):
        self.clicks += 1
        return True


class RejectedClickHarness:
    ui_click = BaseTask.ui_click

    def __init__(self):
        self._last_ui_click_failure = None

    def screenshot(self):
        return None

    def appear(self, _target):
        return False

    def click(self, _target, interval=1):
        raise GameTooManyClickError('control rejected')


class PersistentRewardHarness:
    ui_get_reward = BaseTask.ui_get_reward
    I_UI_REWARD = object()

    def __init__(self):
        self._last_ui_click_failure = None
        self.clicks = 0

    def screenshot(self):
        return None

    def appear(self, target, **_kwargs):
        return target is self.I_UI_REWARD

    def ui_reward_appear_click(self):
        self.clicks += 1
        return True


class ExplorationFailureHarness:
    _raise_click_workflow_failure = BaseExploration._raise_click_workflow_failure

    def __init__(self, failure):
        self._last_ui_click_failure = failure


class ClickWorkflowBoundaryTest(unittest.TestCase):
    def test_persistent_button_stops_at_action_budget(self):
        harness = PersistentButtonHarness()

        self.assertFalse(
            harness.ui_click_until_disappear(
                object(),
                timeout=30,
                max_actions=3,
            )
        )

        self.assertEqual(harness.clicks, 3)
        self.assertEqual(harness._last_ui_click_failure.reason, 'action_budget_exhausted')
        self.assertEqual(harness._last_ui_click_failure.actions, 3)

    def test_rejected_control_returns_structured_failure(self):
        harness = RejectedClickHarness()
        click = RuleClick((1, 1, 1, 1), (1, 1, 1, 1), name='test_click')

        self.assertFalse(
            harness.ui_click(
                click,
                stop=object(),
                timeout=30,
                max_actions=3,
            )
        )

        self.assertEqual(harness._last_ui_click_failure.reason, 'control_rejected')
        self.assertEqual(harness._last_ui_click_failure.actions, 0)

    def test_reward_overlay_cannot_bypass_outer_timeout_with_inner_loop(self):
        harness = PersistentRewardHarness()

        self.assertFalse(
            harness.ui_get_reward(
                object(),
                timeout=30,
                max_actions=3,
            )
        )

        self.assertEqual(harness.clicks, 3)
        self.assertEqual(harness._last_ui_click_failure.reason, 'action_budget_exhausted')

    def test_exploration_error_keeps_machine_readable_reason(self):
        failure = SimpleNamespace(
            reason='page_transition_timeout',
            actions=2,
            timeout=8.0,
            max_actions=4,
            target='chapter_entry',
            detail=None,
        )
        harness = ExplorationFailureHarness(failure)

        with self.assertRaises(GameStuckError) as raised:
            harness._raise_click_workflow_failure('open_chapter')

        message = str(raised.exception)
        self.assertIn('operation=open_chapter', message)
        self.assertIn('reason=page_transition_timeout', message)
        self.assertIn('actions=2', message)

    def test_exploration_click_helpers_always_set_both_boundaries(self):
        root = Path(__file__).resolve().parents[1]
        for path in (root / 'base.py', root / 'solo.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in {
                    'ui_click',
                    'ui_click_until_disappear',
                    'ui_get_reward',
                }:
                    continue
                keywords = {item.arg for item in node.keywords}
                self.assertIn('timeout', keywords, f'{path.name}:{node.lineno}')
                self.assertIn('max_actions', keywords, f'{path.name}:{node.lineno}')


if __name__ == '__main__':
    unittest.main()
