import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

from tasks.RealmRaid.script_task import ScriptTask


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class RewardWaitHarness:
    I_SOUL_RAID = 'reward'
    I_BACK_RED = 'back'

    def __init__(self, reward_frames, heuristic_frames=None, in_real_battle=False):
        self.reward_frames = list(reward_frames)
        self.heuristic_frames = list(heuristic_frames or [])
        self.frame = -1
        self.click_attempts = 0
        self.clicks = 0
        self.fallback_clicks = 0
        self.in_real_battle = in_real_battle
        self.device = SimpleNamespace(
            image=np.zeros((720, 1280, 3), dtype=np.uint8),
            click=self._fallback_click,
        )

    def screenshot(self):
        self.frame += 1

    def is_in_real_battle(self, _is_screenshot=False):
        return self.in_real_battle

    def reward_visible(self):
        if not self.reward_frames:
            return False
        index = min(self.frame, len(self.reward_frames) - 1)
        return self.reward_frames[index]

    def level_reward_overlay_visible(self):
        if self.reward_visible():
            return True
        if not self.heuristic_frames:
            return False
        index = min(self.frame, len(self.heuristic_frames) - 1)
        return self.heuristic_frames[index]

    def appear(self, target, interval=None, threshold=None):
        if target == self.I_SOUL_RAID:
            return self.reward_visible()
        if target == self.I_BACK_RED:
            return True
        return False

    def appear_then_click(self, target, interval=None, threshold=None):
        self.click_attempts += 1
        # Simulate a stale interval timer from the preceding battle flow. The
        # reward must still be dismissible without that timer.
        if interval is not None:
            return False
        if target == self.I_SOUL_RAID and self.reward_visible() and self.click_attempts == 1:
            self.clicks += 1
            return True
        return False

    def _fallback_click(self, *_args, **_kwargs):
        self.fallback_clicks += 1

    def dismiss_level_reward_overlay(self):
        if self.appear_then_click(self.I_SOUL_RAID, threshold=0.65):
            return
        self._fallback_click()


class RewardDismissHarness(ScriptTask):
    I_SOUL_RAID = object()

    def __init__(self, template_click=True):
        self.template_click = template_click
        self.overlay_visible = True
        self.clicks = []
        self.device = SimpleNamespace(
            image=np.zeros((720, 1280, 3), dtype=np.uint8),
            click=self._click,
        )

    def appear_then_click(self, _target, **_kwargs):
        return self.template_click

    def level_reward_overlay_visible(self):
        return self.overlay_visible

    def screenshot(self):
        return None

    def _click(self, x, y, **_kwargs):
        self.clicks.append((x, y))
        if y >= 650:
            self.overlay_visible = False


class RewardWaitTest(unittest.TestCase):
    def test_reward_dismiss_uses_bottom_fallback_when_template_tap_stalls(self):
        harness = RewardDismissHarness(template_click=True)

        harness.dismiss_level_reward_overlay()

        self.assertEqual(harness.clicks, [(640, 675)])
        self.assertFalse(harness.overlay_visible)

    def run_wait(self, harness, timeout=5):
        clock = FakeClock()
        with (
            patch('tasks.RealmRaid.script_task.time.time', clock.time),
            patch('tasks.RealmRaid.script_task.time.sleep', clock.sleep),
        ):
            result = ScriptTask.wait_level_board(harness, timeout=timeout)
        return result, clock

    def test_board_without_reward_is_ready_immediately(self):
        harness = RewardWaitHarness([False])

        result, clock = self.run_wait(harness)

        self.assertTrue(result)
        self.assertEqual(harness.frame + 1, 1)
        self.assertEqual(clock.now, 0)

    def test_visible_reward_blocks_back_button_until_overlay_is_stably_clear(self):
        harness = RewardWaitHarness([True, True, False, False, False])

        result, clock = self.run_wait(harness)

        self.assertTrue(result)
        self.assertEqual(harness.clicks, 1)
        self.assertGreaterEqual(harness.click_attempts, 1)
        self.assertGreaterEqual(harness.frame + 1, 5)
        self.assertGreaterEqual(clock.now, 2.0)

    def test_persistent_reward_times_out_instead_of_accepting_back_button(self):
        harness = RewardWaitHarness([True])

        result, _clock = self.run_wait(harness, timeout=3)

        self.assertFalse(result)
        self.assertGreater(harness.click_attempts, 1)
        self.assertLessEqual(harness.click_attempts, 3)

    def test_real_battle_is_not_clicked_as_a_reward_overlay(self):
        harness = RewardWaitHarness([True], in_real_battle=True)

        result, _clock = self.run_wait(harness)

        self.assertFalse(result)
        self.assertEqual(harness.click_attempts, 0)
        self.assertEqual(harness.fallback_clicks, 0)

    def test_full_reward_overlay_fallback_blocks_board_until_clear(self):
        harness = RewardWaitHarness(
            [False],
            heuristic_frames=[True, True, False, False, False],
        )

        result, clock = self.run_wait(harness)

        self.assertTrue(result)
        self.assertEqual(harness.fallback_clicks, 1)
        self.assertGreaterEqual(clock.now, 2.0)

    def test_reward_overlay_heuristic_distinguishes_dimmed_modal(self):
        normal = np.full((720, 1280, 3), 180, dtype=np.uint8)
        overlay = normal.copy()
        overlay[370:670, 450:830] = 70
        overlay[430:610, 520:760] = (210, 90, 30)

        self.assertFalse(ScriptTask._level_reward_overlay_heuristic(normal))
        self.assertTrue(ScriptTask._level_reward_overlay_heuristic(overlay))

    def test_reward_overlay_heuristic_accepts_current_blue_modal(self):
        normal = np.full((720, 1280, 3), 180, dtype=np.uint8)
        overlay = normal.copy()
        overlay[370:670, 450:830] = 70
        overlay[430:610, 520:760] = (30, 90, 210)

        self.assertTrue(ScriptTask._level_reward_overlay_heuristic(overlay))


if __name__ == '__main__':
    unittest.main()
