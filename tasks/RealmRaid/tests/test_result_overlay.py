import unittest
from unittest.mock import patch

import numpy as np

from module.exception import GameStuckError
from tasks.RealmRaid.script_task import ScriptTask


class RewardOverlayHarness(ScriptTask):
    O_BATTLE_RESULT_CONTINUE = object()
    I_BACK_RED = object()

    def __init__(self, back_visible=True, overlay_shape_visible=False, prompt_visible=True,
                 prepare_visible=False, real_battle=False):
        self.prompt_visible = prompt_visible
        self.back_visible = back_visible
        self.overlay_shape_visible = overlay_shape_visible
        self.prepare_visible = prepare_visible
        self.real_battle = real_battle
        self.dismisses = 0
        self.generic_clicks = 0

    def ocr_appear(self, rule, **_kwargs):
        return rule is self.O_BATTLE_RESULT_CONTINUE and self.prompt_visible

    def appear(self, rule, **_kwargs):
        return rule is self.I_BACK_RED and self.back_visible

    def level_reward_overlay_visible(self):
        return self.overlay_shape_visible

    def dismiss_level_reward_overlay(self):
        self.dismisses += 1
        self.overlay_shape_visible = False
        self.prompt_visible = False

    def ocr_appear_click(self, _rule, **_kwargs):
        self.generic_clicks += 1
        self.prompt_visible = False
        return True

    def is_in_prepare(self, _is_screenshot=False):
        return self.prepare_visible

    def is_in_real_battle(self, _is_screenshot=False):
        return self.real_battle

    def screenshot(self):
        return None


class RewardOverlayTest(unittest.TestCase):
    def test_visual_guard_accepts_dimmed_result_prompt(self):
        result = np.full((720, 1280, 3), 20, dtype=np.uint8)
        result[360:650, 450:830] = 60
        result[650:715, 520:780] = 100

        self.assertTrue(ScriptTask._battle_result_visual_heuristic(result))

    def test_visual_guard_rejects_battle_prepare_page(self):
        battle = np.full((720, 1280, 3), 100, dtype=np.uint8)
        battle[360:650, 450:830] = 125
        battle[650:715, 520:780] = 100

        self.assertFalse(ScriptTask._battle_result_visual_heuristic(battle))

    def test_normal_result_uses_generic_prompt_click(self):
        harness = RewardOverlayHarness()

        self.assertTrue(harness._dismiss_battle_result_continue())
        self.assertEqual(harness.dismisses, 0)
        self.assertEqual(harness.generic_clicks, 1)

    def test_milestone_reward_overlay_uses_board_reward_fallback(self):
        harness = RewardOverlayHarness(
            back_visible=True,
            overlay_shape_visible=True,
            prompt_visible=False,
        )

        self.assertTrue(harness._dismiss_battle_result_continue())
        self.assertEqual(harness.dismisses, 1)
        self.assertEqual(harness.generic_clicks, 0)

    def test_milestone_reward_overlay_is_rejected_without_board_context(self):
        harness = RewardOverlayHarness(
            back_visible=False,
            overlay_shape_visible=True,
            prompt_visible=False,
        )

        self.assertFalse(harness._dismiss_battle_result_continue())
        self.assertEqual(harness.dismisses, 0)
        self.assertEqual(harness.generic_clicks, 0)

    def test_board_reward_overlay_has_priority_over_generic_prompt(self):
        harness = RewardOverlayHarness(
            back_visible=True,
            overlay_shape_visible=True,
            prompt_visible=True,
        )

        self.assertTrue(harness._dismiss_battle_result_continue())
        self.assertEqual(harness.dismisses, 1)
        self.assertEqual(harness.generic_clicks, 0)

    def test_generic_result_prompt_without_board_context_uses_generic_path(self):
        harness = RewardOverlayHarness(
            back_visible=False,
            overlay_shape_visible=True,
            prompt_visible=True,
        )

        self.assertTrue(harness._dismiss_battle_result_continue())
        self.assertEqual(harness.dismisses, 0)
        self.assertEqual(harness.generic_clicks, 1)

    def test_board_reward_overlay_is_not_used_during_real_battle(self):
        harness = RewardOverlayHarness(
            back_visible=True,
            overlay_shape_visible=True,
            prompt_visible=False,
            real_battle=True,
        )

        self.assertFalse(harness._dismiss_battle_result_continue())
        self.assertEqual(harness.dismisses, 0)
        self.assertEqual(harness.generic_clicks, 0)

    def test_board_reward_overlay_is_rechecked_after_generic_limit(self):
        harness = RewardOverlayHarness(
            back_visible=True,
            overlay_shape_visible=True,
            prompt_visible=False,
        )

        with patch.object(
            ScriptTask.__mro__[1],
            '_dismiss_battle_result_continue',
            side_effect=GameStuckError('generic result limit'),
        ):
            self.assertTrue(harness._dismiss_battle_result_continue())

        self.assertEqual(harness.dismisses, 1)
        self.assertEqual(harness.generic_clicks, 0)

    def test_prepare_page_never_uses_reward_fallback(self):
        harness = RewardOverlayHarness(
            back_visible=False,
            overlay_shape_visible=True,
            prompt_visible=False,
            prepare_visible=True,
        )

        self.assertFalse(harness._dismiss_battle_result_continue())
        self.assertEqual(harness.dismisses, 0)
        self.assertEqual(harness.generic_clicks, 0)

    def test_preflight_never_uses_reward_fallback_before_prepare_is_detected(self):
        # During the first transition frame the prepare OCR may still be empty.
        # The explicit preflight context must remain safe even in that frame.
        harness = RewardOverlayHarness(
            back_visible=False,
            overlay_shape_visible=True,
            prompt_visible=False,
            prepare_visible=False,
        )

        self.assertFalse(
            harness._dismiss_battle_result_continue(allow_task_reward=False)
        )
        self.assertEqual(harness.dismisses, 0)
        self.assertEqual(harness.generic_clicks, 0)


if __name__ == '__main__':
    unittest.main()
