import unittest
from unittest.mock import patch

from module.exception import GameStuckError
from tasks.Exploration.base import BaseExploration, ExplorationExitReason


class FakeRule:
    def __init__(self, name):
        self.name = name


class FakeDevice:
    def __init__(self):
        self.clicks = []

    def click(self, x, y, control_name='Click'):
        self.clicks.append((x, y, control_name))


class ExitConfirmationHarness:
    I_E_EXIT_CONFIRM = FakeRule('e_exit_confirm')

    def __init__(self, template_visible=False, ocr_visible=True):
        self.device = FakeDevice()
        self.template_visible = template_visible
        self.ocr_visible = ocr_visible
        self.wait_calls = 0

    def appear_then_click(self, rule, interval=0):
        return rule is self.I_E_EXIT_CONFIRM and self.template_visible

    def ocr_appear(self, _rule):
        return self.ocr_visible

    def _exploration_exit_confirmation_ocr_visible(self):
        return self.ocr_visible

    def _wait_for_exploration_exit_transition(self):
        self.wait_calls += 1


class QuitExploreHarness:
    I_UI_BACK_YELLOW = FakeRule('ui_back_yellow')
    I_E_EXPLORATION_CLICK = FakeRule('exploration_click')
    I_BATTLE_REWARD = FakeRule('battle_reward')
    I_UI_BACK_BLUE = FakeRule('ui_back_blue')
    I_BACK_YOLLOW = FakeRule('back_yollow')
    I_EXPLORATION_TITLE = FakeRule('exploration_title')
    _consume_pending_battle_result_overlay = BaseExploration._consume_pending_battle_result_overlay

    def __init__(self, visible=(), world=False):
        self.visible = set(visible)
        self.world = world
        self.clicks = []

    def screenshot(self):
        return None

    def appear(self, rule, **_kwargs):
        return rule in self.visible

    def is_exploration_world(self):
        return self.world

    def appear_then_click(self, *_args, **_kwargs):
        return False

    def click(self, rule, **_kwargs):
        self.clicks.append(rule)

    def _click_exploration_exit_confirmation(self):
        return False


class PendingResultQuitHarness(QuitExploreHarness):
    def __init__(self):
        super().__init__()
        self.pending_result = True
        self.dismiss_calls = []

    def _battle_result_continue_visible(self):
        return self.pending_result

    def _dismiss_battle_result_continue(self, **kwargs):
        self.dismiss_calls.append(kwargs)
        self.pending_result = False
        self.world = True
        return True


class ExitConfirmationRecoveryTest(unittest.TestCase):
    def test_current_blue_confirmation_uses_ocr_once(self):
        harness = ExitConfirmationHarness(template_visible=False, ocr_visible=True)

        result = BaseExploration._click_exploration_exit_confirmation(harness)

        self.assertTrue(result)
        self.assertEqual(len(harness.device.clicks), 1)
        self.assertEqual(harness.device.clicks[0][2], 'EXPLORATION_EXIT_CONFIRM_TEXT')
        self.assertEqual(harness.wait_calls, 1)

    def test_legacy_template_still_has_priority(self):
        harness = ExitConfirmationHarness(template_visible=True, ocr_visible=True)

        result = BaseExploration._click_exploration_exit_confirmation(harness)

        self.assertTrue(result)
        self.assertEqual(harness.device.clicks, [])
        self.assertEqual(harness.wait_calls, 1)


class QuitExploreTest(unittest.TestCase):
    def test_pending_result_overlay_is_consumed_before_exit_confirmation(self):
        harness = PendingResultQuitHarness()
        with patch(
            'tasks.Exploration.base.time.monotonic',
            side_effect=(0.0, 0.1, 0.2),
        ):
            result = BaseExploration.quit_explore(
                harness,
                reason=ExplorationExitReason.BATTLE_LIMIT,
            )
        self.assertTrue(result)
        self.assertEqual(harness.dismiss_calls, [{'timeout': 1.5, 'max_clicks': 2}])
        self.assertEqual(harness._exploration_exit_endpoint_confirmed, 'world')

    def test_chapter_page_is_a_successful_exit(self):
        harness = QuitExploreHarness(
            visible=(
                QuitExploreHarness.I_UI_BACK_YELLOW,
                QuitExploreHarness.I_E_EXPLORATION_CLICK,
            )
        )
        with patch('tasks.Exploration.base.time.monotonic', side_effect=(0.0, 0.1)):
            result = BaseExploration.quit_explore(
                harness,
                reason=ExplorationExitReason.SEARCH_EXHAUSTED,
            )
        self.assertTrue(result)
        self.assertEqual(harness._exploration_exit_endpoint_confirmed, 'chapter_page')

    def test_exploration_world_is_a_successful_exit(self):
        harness = QuitExploreHarness(world=True)
        with patch('tasks.Exploration.base.time.monotonic', side_effect=(0.0, 0.1)):
            result = BaseExploration.quit_explore(
                harness,
                reason=ExplorationExitReason.TEAM_MEMBER_LEFT,
            )
        self.assertTrue(result)
        self.assertEqual(harness._exploration_exit_endpoint_confirmed, 'world')

    def test_exit_timeout_remains_a_game_stuck_error(self):
        harness = QuitExploreHarness()
        with patch('tasks.Exploration.base.time.monotonic', side_effect=(0.0, 31.0)):
            with self.assertRaisesRegex(GameStuckError, 'reason=unknown'):
                BaseExploration.quit_explore(harness)


if __name__ == '__main__':
    unittest.main()
