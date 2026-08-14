import unittest

import cv2
import numpy as np

from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.GeneralBattle.config_general_battle import GreenMarkType
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralBattle.green_mark_detector import (
    classify_marker_frame,
    resolve_stable_marker_frames,
)


class RealBattleHarness:
    I_BATTLE_INFO = object()
    I_FRIENDS = object()
    I_WIN = object()
    I_FALSE = object()
    I_REWARD = object()
    O_BATTLE_RESULT_CONTINUE = object()

    is_in_real_battle = GeneralBattle.is_in_real_battle
    _battle_result_continue_visible = GeneralBattle._battle_result_continue_visible

    def __init__(self, prepare=False, friends=True):
        self.prepare = prepare
        self.friends = friends

    def screenshot(self):
        return None

    def _prepare_button_visible(self):
        return self.prepare

    def ocr_appear(self, _target, **_kwargs):
        return False

    def appear(self, target, **_kwargs):
        if target is self.I_FRIENDS:
            return self.friends
        return False


class GreenTerminalHarness:
    I_WIN = object()
    I_FALSE = object()
    I_REWARD = object()
    I_REWARD_GOLD = object()
    I_DE_WIN = object()
    _battle_terminal_visible = GeneralBattle._battle_terminal_visible

    def __init__(self, terminal):
        self.terminal = terminal

    def appear(self, target, **_kwargs):
        return target is self.I_WIN and self.terminal


class GreenMarkMappingTest(unittest.TestCase):
    @staticmethod
    def slot_rois():
        return {
            f'green_left{index}': getattr(
                GeneralBattleAssets,
                f'C_GREEN_LEFT_{index}',
            ).roi_front
            for index in range(1, 6)
        }

    @staticmethod
    def arrow_frame(x: int, bottom: int):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        top = bottom - 32
        points = np.array(
            [
                (x - 10, top),
                (x + 10, top),
                (x + 10, top + 12),
                (x + 18, top + 12),
                (x, bottom),
                (x - 18, top + 12),
                (x - 10, top + 12),
            ],
            dtype=np.int32,
        )
        cv2.fillPoly(frame, [points], (20, 245, 40))
        return frame

    def test_left_three_uses_battlefield_frontline_area(self):
        self.assertEqual(GeneralBattleAssets.C_GREEN_LEFT_3.roi_front, (586, 328, 100, 76))

    def test_current_prepare_page_is_not_real_battle(self):
        self.assertFalse(RealBattleHarness(prepare=True).is_in_real_battle(False))

    def test_friends_icon_is_real_battle_fallback_after_prepare_left(self):
        self.assertTrue(RealBattleHarness(prepare=False).is_in_real_battle(False))

    def test_green_marker_confirmation_requires_target_roi(self):
        first = classify_marker_frame(
            self.arrow_frame(636, 350),
            expected_slot='green_left3',
            slot_rois=self.slot_rois(),
        )
        second = classify_marker_frame(
            self.arrow_frame(637, 350),
            expected_slot='green_left3',
            slot_rois=self.slot_rois(),
        )
        result = resolve_stable_marker_frames(
            [first, second], expected_slot='green_left3'
        )
        self.assertEqual(result.status, 'confirmed')

    def test_green_marker_outside_target_is_rejected(self):
        first = classify_marker_frame(
            self.arrow_frame(173, 350),
            expected_slot='green_left3',
            slot_rois=self.slot_rois(),
        )
        second = classify_marker_frame(
            self.arrow_frame(174, 350),
            expected_slot='green_left3',
            slot_rois=self.slot_rois(),
        )
        result = resolve_stable_marker_frames(
            [first, second], expected_slot='green_left3'
        )
        self.assertEqual(result.status, 'wrong_target')

    def test_green_left_two_accepts_marker_above_shikigami_body(self):
        first = classify_marker_frame(
            self.arrow_frame(411, 257),
            expected_slot='green_left2',
            slot_rois=self.slot_rois(),
        )
        second = classify_marker_frame(
            self.arrow_frame(412, 257),
            expected_slot='green_left2',
            slot_rois=self.slot_rois(),
        )
        result = resolve_stable_marker_frames(
            [first, second], expected_slot='green_left2'
        )
        self.assertEqual(result.status, 'confirmed')

    def test_terminal_state_is_available_for_green_wait_short_circuit(self):
        self.assertTrue(GreenTerminalHarness(True)._battle_terminal_visible())
        self.assertFalse(GreenTerminalHarness(False)._battle_terminal_visible())


if __name__ == '__main__':
    unittest.main()
