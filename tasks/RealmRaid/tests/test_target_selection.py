import unittest
from types import SimpleNamespace

import numpy as np

from module.exception import GameStuckError
from tasks.RealmRaid.script_task import ScriptTask


class TargetSelectionHarness:
    fire = ScriptTask.fire
    _realm_raid_fire_visible = ScriptTask._realm_raid_fire_visible
    _click_realm_raid_fire = ScriptTask._click_realm_raid_fire
    _realm_raid_partition_targets = ScriptTask._realm_raid_partition_targets
    _realm_raid_partition_target = ScriptTask._realm_raid_partition_target

    I_FRESH_ENSURE = object()
    I_FIRE = object()
    I_FIRE_CURRENT = object()

    def __init__(self, fire_after_selection=True):
        self.fire_after_selection = fire_after_selection
        self.fire_visible = False
        self.selection_clicks = 0
        self.fire_clicks = 0
        self.dumps = []
        self.selection_rois = []
        self.device = SimpleNamespace(click=lambda **_kwargs: None)
        rois = [
            (233, 147, 229, 120), (566, 148, 237, 115), (900, 147, 222, 116),
            (236, 283, 229, 124), (564, 280, 237, 120), (900, 282, 222, 120),
            (233, 416, 236, 121), (567, 413, 230, 124), (900, 418, 222, 116),
        ]
        self.partition = [
            SimpleNamespace(name=f'partition_{index}', roi_front=roi, roi_back=roi)
            for index, roi in enumerate(rois, start=1)
        ]

    def screenshot(self):
        return None

    def appear(self, target, **_kwargs):
        if target is self.I_FRESH_ENSURE:
            return False
        if target in (self.I_FIRE, self.I_FIRE_CURRENT):
            return self.fire_visible
        # The old implementation used I_RR_PERSON here.  Keep all other image
        # rules visible so the harness proves that signal is no longer needed.
        return True

    def appear_then_click(self, target, **_kwargs):
        if target in (self.I_FIRE, self.I_FIRE_CURRENT) and self.fire_visible:
            self.fire_clicks += 1
            self.fire_visible = False
            return True
        return False

    def click(self, _click, interval=None):
        self.selection_clicks += 1
        self.selection_rois.append(_click.roi_front)
        if self.fire_after_selection:
            self.fire_visible = True
        return True

    def dump_board(self, label):
        self.dumps.append(label)


class TargetSelectionTest(unittest.TestCase):
    def test_medal_order_retries_a_valid_row_at_bounded_relaxed_threshold(self):
        class Candidate:
            name = 'RES_MEDAL_3'

            def __init__(self):
                self.roi_front = [572, 210, 193, 41]
                self.calls = []

            def match(self, _image, threshold=None):
                self.calls.append(threshold)
                return threshold == 0.75

            def front_center(self):
                return (668, 230)

        class MedalGrid:
            def __init__(self, candidate):
                self.images = [candidate]

            def find_anyone(self, _image):
                return None

        class ChooseHarness:
            choose_level_target = ScriptTask.choose_level_target
            MEDAL_RELAXED_THRESHOLD = 0.75

            def __init__(self, candidate):
                self.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
                self.order_medal = MedalGrid(candidate)
                self._level_target_image = None
                self.partition = [
                    SimpleNamespace(roi_front=(566, 148, 237, 115), roi_back=(566, 148, 237, 115))
                    for _ in range(9)
                ]

        candidate = Candidate()
        harness = ChooseHarness(candidate)
        snapshot = SimpleNamespace(attackable=frozenset({2}), broken=frozenset())

        self.assertEqual(harness.choose_level_target(snapshot), 2)
        self.assertIs(harness._level_target_image, candidate)
        self.assertEqual(candidate.calls, [0.75])

    def test_matched_medal_uses_bounded_semantic_candidates(self):
        harness = TargetSelectionHarness(fire_after_selection=True)
        harness._level_target_image = SimpleNamespace(
            roi_front=[238, 341, 199, 52],
            front_center=lambda: (337, 367),
        )

        candidates = harness._realm_raid_partition_targets(4)

        self.assertEqual(
            [candidate.name for candidate in candidates],
            ['partition_4:first_medal', 'partition_4:portrait'],
        )
        self.assertEqual(candidates[0].roi_front, (242, 356, 42, 32))

        result = harness.fire(4, timeout=2)

        self.assertTrue(result)
        self.assertEqual(harness.selection_clicks, 1)
        self.assertEqual(harness.fire_clicks, 1)
        self.assertEqual(harness.dumps, [])
        x, y, width, height = harness.selection_rois[0]
        self.assertEqual((x, y, width, height), (242, 356, 42, 32))

    def test_missing_attack_button_is_bounded_and_diagnostic(self):
        harness = TargetSelectionHarness(fire_after_selection=False)

        with self.assertRaises(GameStuckError):
            harness.fire(4, timeout=2)

        self.assertEqual(harness.selection_clicks, 2)
        self.assertEqual(harness.dumps, ['target_4_fire_not_found'])


if __name__ == '__main__':
    unittest.main()
