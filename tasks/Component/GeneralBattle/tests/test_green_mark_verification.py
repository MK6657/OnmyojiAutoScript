import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralBattle.green_mark_detector import (
    GreenMarkerFrameObservation,
    GreenMarkResult,
)


class VerificationHarness:
    _wait_green_marker_confirmation_result = (
        GeneralBattle._wait_green_marker_confirmation_result
    )
    C_GREEN_LEFT_1 = GeneralBattleAssets.C_GREEN_LEFT_1
    C_GREEN_LEFT_2 = GeneralBattleAssets.C_GREEN_LEFT_2
    C_GREEN_LEFT_3 = GeneralBattleAssets.C_GREEN_LEFT_3
    C_GREEN_LEFT_4 = GeneralBattleAssets.C_GREEN_LEFT_4
    C_GREEN_LEFT_5 = GeneralBattleAssets.C_GREEN_LEFT_5
    I_GREEN_MARKER_LEFT_TOP = object()
    I_GREEN_MARKER_BOTTOM = object()
    I_GREEN_MARKER = object()

    def __init__(self):
        self.interval_changes = []
        self.device = SimpleNamespace(
            image=np.zeros((720, 1280, 3), dtype=np.uint8),
            _screenshot_interval=SimpleNamespace(limit=0.3),
        )
        self.device.screenshot_interval_set = self._set_interval

    def _set_interval(self, value):
        self.interval_changes.append(value)
        self.device._screenshot_interval.limit = value

    def screenshot(self):
        return None

    def _battle_terminal_visible(self):
        return False

    def is_in_real_battle(self, _screenshot=False):
        return False

    def _read_battle_mode(self):
        return None


class GreenMarkVerificationTest(unittest.TestCase):
    def test_transient_cinematic_unknown_is_bounded_not_immediate_skip(self):
        harness = VerificationHarness()
        diagnostic = SimpleNamespace(frame_sha256='a' * 64, templates=())
        with (
            patch.object(
                GeneralBattle,
                '_green_mark_diagnostic',
                return_value=diagnostic,
            ),
            patch.object(GeneralBattle, '_green_mark_max_score', return_value=0.0),
            patch.object(GeneralBattle, '_log_green_mark_diagnostic'),
            patch(
                'tasks.Component.GeneralBattle.general_battle.time.sleep',
                return_value=None,
            ),
        ):
            result = harness._wait_green_marker_confirmation_result(
                harness.C_GREEN_LEFT_3,
                timeout=0.01,
            )

        self.assertEqual(result.status, 'unconfirmed')
        self.assertNotIn('manual', result.reason)

    def test_preconfirmed_auto_uses_fast_protected_frames_and_restores_interval(self):
        harness = VerificationHarness()
        harness.is_in_real_battle = lambda _screenshot=False: True
        mode_reads = []
        harness._read_battle_mode = lambda: mode_reads.append(True) or 'auto'
        diagnostic = SimpleNamespace(frame_sha256='a' * 64, templates=())
        observations = [
            GreenMarkerFrameObservation(
                frame_sha256='1' * 64,
                expected_slot='green_left3',
                observation='expected_candidate',
                color='green',
                assigned_slot='green_left3',
                marker_tip=(626, 258),
                confidence=0.8,
            ),
            GreenMarkerFrameObservation(
                frame_sha256='2' * 64,
                expected_slot='green_left3',
                observation='expected_candidate',
                color='green',
                assigned_slot='green_left3',
                marker_tip=(626, 258),
                confidence=0.8,
            ),
        ]
        results = [
            GreenMarkResult(
                status='unconfirmed',
                target='green_left3',
                expected_slot='green_left3',
            ),
            GreenMarkResult(
                status='confirmed',
                target='green_left3',
                expected_slot='green_left3',
                assigned_slot='green_left3',
                color='green',
                marker_tip=(626, 258),
                stable_frames=2,
            ),
        ]
        with (
            patch.object(
                GeneralBattle,
                '_green_mark_diagnostic',
                return_value=diagnostic,
            ),
            patch.object(GeneralBattle, '_green_mark_max_score', return_value=0.0),
            patch.object(GeneralBattle, '_log_green_mark_diagnostic'),
            patch(
                'tasks.Component.GeneralBattle.general_battle.classify_marker_frame',
                side_effect=observations,
            ),
            patch(
                'tasks.Component.GeneralBattle.general_battle.resolve_stable_marker_frames',
                side_effect=results,
            ),
            patch(
                'tasks.Component.GeneralBattle.general_battle.time.sleep',
                return_value=None,
            ),
            patch.dict(os.environ, {'OAS_GREEN_MARK_COLOR_SLOT_MODE': 'enforce'}),
        ):
            result = harness._wait_green_marker_confirmation_result(
                harness.C_GREEN_LEFT_3,
                timeout=0.5,
                auto_mode_preconfirmed=True,
            )

        self.assertEqual(result.status, 'confirmed')
        self.assertEqual(mode_reads, [])
        self.assertEqual(harness.interval_changes, [0.1, 0.3])


if __name__ == '__main__':
    unittest.main()
