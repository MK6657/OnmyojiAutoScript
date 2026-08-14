import unittest

import numpy as np

from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.GeneralBattle.green_mark_detector import (
    diagnose_green_marker,
    frame_sha256,
)


class GreenMarkDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    def test_exact_template_reports_score_and_position(self):
        template = GeneralBattleAssets.I_GREEN_MARKER_LEFT_TOP.image
        x, y = 615, 260
        h, w = template.shape[:2]
        self.frame[y:y + h, x:x + w] = template

        result = diagnose_green_marker(
            self.frame,
            target_name='green_left3',
            target_roi=GeneralBattleAssets.C_GREEN_LEFT_3.roi_front,
            template_assets=(GeneralBattleAssets.I_GREEN_MARKER_LEFT_TOP,),
        )

        self.assertGreaterEqual(result.templates[0].max_score, 0.999)
        self.assertEqual(result.templates[0].top_left, (x, y))
        self.assertEqual(result.templates[0].center, (x + w // 2, y + h // 2))
        self.assertTrue(result.template_confirmed)

    def test_negative_frame_stays_below_template_threshold(self):
        rng = np.random.default_rng(20260809)
        frame = rng.integers(0, 256, size=self.frame.shape, dtype=np.uint8)

        result = diagnose_green_marker(
            frame,
            target_name='green_left3',
            target_roi=GeneralBattleAssets.C_GREEN_LEFT_3.roi_front,
            template_assets=(GeneralBattleAssets.I_GREEN_MARKER_LEFT_TOP,),
        )

        self.assertLess(result.templates[0].max_score, 0.8)
        self.assertFalse(result.template_confirmed)

    def test_hsv_candidate_does_not_change_template_confirmation(self):
        self.frame[250:270, 610:635] = (90, 230, 90)

        result = diagnose_green_marker(
            self.frame,
            target_name='green_left3',
            target_roi=GeneralBattleAssets.C_GREEN_LEFT_3.roi_front,
            template_assets=(GeneralBattleAssets.I_GREEN_MARKER_LEFT_TOP,),
        )

        self.assertTrue(result.hsv_candidates)
        self.assertFalse(result.template_confirmed)

    def test_frame_hash_includes_shape_and_pixels(self):
        digest = frame_sha256(self.frame)
        changed = self.frame.copy()
        changed[0, 0] = (1, 2, 3)

        self.assertEqual(len(digest), 64)
        self.assertNotEqual(digest, frame_sha256(changed))
        self.assertNotEqual(digest, frame_sha256(self.frame[:, :1279]))

    def test_diagnostic_records_target_and_confirmation_band(self):
        result = diagnose_green_marker(
            self.frame,
            target_name='green_left3',
            target_roi=GeneralBattleAssets.C_GREEN_LEFT_3.roi_front,
            template_assets=(GeneralBattleAssets.I_GREEN_MARKER_LEFT_TOP,),
        )

        self.assertEqual(result.target_name, 'green_left3')
        self.assertEqual(result.target_roi, (586, 328, 100, 76))
        self.assertEqual(result.confirmation_band, (541, 148, 190, 356))


if __name__ == '__main__':
    unittest.main()
