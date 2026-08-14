import unittest
from unittest.mock import patch

from tasks.Component.GeneralBattle.general_battle import GeneralBattle


class AntiDetectHarness:
    C_RANDOM_CLICK = object()

    def __init__(self):
        self.actions = []
        self.terminal = False

    def _battle_terminal_visible(self):
        return self.terminal

    def click(self, rule, interval=None):
        self.actions.append(('click', rule, interval))

    def swipe(self, rule, interval=None):
        self.actions.append(('swipe', rule, interval))


class AntiDetectSchedulerTest(unittest.TestCase):
    def test_scheduler_does_not_sleep_or_repeat_before_next_slot(self):
        harness = AntiDetectHarness()
        clock = iter((0.0, 0.1, 0.7))

        with patch('tasks.Component.GeneralBattle.general_battle.time.monotonic', side_effect=clock):
            with patch(
                'tasks.Component.GeneralBattle.general_battle.random.randint',
                side_effect=(500, 0, 0),
            ):
                self.assertFalse(GeneralBattle.random_click_swipt_nonblocking(harness))
                self.assertFalse(GeneralBattle.random_click_swipt_nonblocking(harness))
                self.assertTrue(GeneralBattle.random_click_swipt_nonblocking(harness))

        self.assertEqual(len(harness.actions), 1)

    def test_terminal_state_blocks_anti_detect_action(self):
        harness = AntiDetectHarness()
        harness.terminal = True

        with patch('tasks.Component.GeneralBattle.general_battle.random.randint') as randint:
            self.assertFalse(GeneralBattle.random_click_swipt(harness))
            randint.assert_not_called()


if __name__ == '__main__':
    unittest.main()
