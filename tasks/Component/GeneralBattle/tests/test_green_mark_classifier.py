import unittest
from pathlib import Path

import cv2
import numpy as np

from tasks.Component.GeneralBattle.green_mark_detector import (
    classify_marker_frame,
    resolve_stable_marker_frames,
)


SLOT_ROIS = {
    'green_left1': (128, 433, 90, 150),
    'green_left2': (371, 385, 81, 145),
    'green_left3': (586, 328, 100, 76),
    'green_left4': (817, 379, 77, 133),
    'green_left5': (1059, 416, 85, 145),
}

FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'green_mark'


def arrow_frame(x: int, *, color: tuple[int, int, int]) -> np.ndarray:
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    points = np.array(
        [
            (x - 10, 220),
            (x + 10, 220),
            (x + 10, 232),
            (x + 18, 232),
            (x, 252),
            (x - 18, 232),
            (x - 10, 232),
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(frame, [points], color)
    return frame


def enemy_arrow_frame(x: int) -> np.ndarray:
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    points = np.array(
        [
            (x - 18, 220),
            (x + 18, 220),
            (x + 18, 230),
            (x + 31, 230),
            (x, 265),
            (x - 31, 230),
            (x - 18, 230),
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(frame, [points], (245, 25, 170))
    return frame


def load_fixture(name: str) -> np.ndarray:
    encoded = np.fromfile(str(FIXTURE_ROOT / name), dtype=np.uint8)
    bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if bgr is None:
        raise AssertionError(f'failed to decode fixture: {name}')
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


class GreenMarkClassifierTest(unittest.TestCase):
    def classify(self, frame, expected='green_left3'):
        return classify_marker_frame(
            frame,
            expected_slot=expected,
            slot_rois=SLOT_ROIS,
        )

    def test_green_arrow_is_assigned_by_tip_to_expected_slot(self):
        result = self.classify(arrow_frame(636, color=(20, 245, 40)))

        self.assertEqual(result.color, 'green')
        self.assertEqual(result.assigned_slot, 'green_left3')
        self.assertEqual(result.marker_tip, (636, 252))
        self.assertEqual(result.observation, 'expected_candidate')

    def test_green_arrow_in_other_slot_is_wrong_target(self):
        result = self.classify(arrow_frame(855, color=(20, 245, 40)))

        self.assertEqual(result.color, 'green')
        self.assertEqual(result.assigned_slot, 'green_left4')
        self.assertEqual(result.observation, 'wrong_target')

    def test_red_arrow_is_enemy_selection(self):
        result = self.classify(enemy_arrow_frame(636))

        self.assertEqual(result.color, 'red')
        self.assertEqual(result.assigned_slot, 'enemy')
        self.assertEqual(result.observation, 'enemy_selected')

    def test_expected_green_marker_wins_when_enemy_marker_coexists(self):
        frame = arrow_frame(636, color=(20, 245, 40))
        frame = np.maximum(frame, enemy_arrow_frame(900))

        result = self.classify(frame)

        self.assertEqual(result.color, 'green')
        self.assertEqual(result.assigned_slot, 'green_left3')
        self.assertEqual(result.observation, 'expected_candidate')

    def test_wrong_green_marker_wins_when_enemy_marker_coexists(self):
        frame = arrow_frame(855, color=(20, 245, 40))
        frame = np.maximum(frame, enemy_arrow_frame(636))

        result = self.classify(frame)

        self.assertEqual(result.color, 'green')
        self.assertEqual(result.assigned_slot, 'green_left4')
        self.assertEqual(result.observation, 'wrong_target')

    def test_real_battle_without_marker_is_rejected(self):
        result = self.classify(load_fixture('no_marker.jpg'))

        self.assertEqual(result.observation, 'not_found')
        self.assertIsNone(result.color)

    def test_real_friendly_markers_map_to_all_five_slots(self):
        for index in range(1, 6):
            expected = f'green_left{index}'
            with self.subTest(expected=expected):
                result = self.classify(
                    load_fixture(f'ally_left{index}.jpg'),
                    expected=expected,
                )
                self.assertEqual(result.observation, 'expected_candidate')
                self.assertEqual(result.color, 'green')
                self.assertEqual(result.assigned_slot, expected)

    def test_real_enemy_boss_and_assistants_are_enemy_selections(self):
        for name in ('enemy_boss.jpg', 'enemy_assistant2.jpg', 'enemy_assistant4.jpg'):
            with self.subTest(name=name):
                result = self.classify(load_fixture(name))
                self.assertEqual(result.observation, 'enemy_selected')
                self.assertEqual(result.color, 'red')
                self.assertEqual(result.assigned_slot, 'enemy')

    def test_real_coexisting_markers_use_friendly_slot_for_green_verification(self):
        frame = load_fixture('ally_left5_with_enemy_boss.png')

        expected = self.classify(frame, expected='green_left5')
        wrong = self.classify(frame, expected='green_left3')

        self.assertEqual(expected.observation, 'expected_candidate')
        self.assertEqual(expected.color, 'green')
        self.assertEqual(expected.assigned_slot, 'green_left5')
        self.assertEqual(wrong.observation, 'wrong_target')
        self.assertEqual(wrong.assigned_slot, 'green_left5')

    def test_non_arrow_green_rectangle_is_rejected(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[220:250, 620:650] = (20, 245, 40)

        result = self.classify(frame)

        self.assertEqual(result.observation, 'not_found')
        self.assertIsNone(result.marker_tip)

    def test_two_stable_expected_frames_confirm(self):
        frames = [
            self.classify(arrow_frame(635, color=(20, 245, 40))),
            self.classify(arrow_frame(637, color=(20, 245, 40))),
        ]

        result = resolve_stable_marker_frames(frames, expected_slot='green_left3')

        self.assertEqual(result.status, 'confirmed')
        self.assertEqual(result.color, 'green')
        self.assertEqual(result.assigned_slot, 'green_left3')
        self.assertEqual(result.stable_frames, 2)

    def test_two_of_three_wrong_slot_frames_return_wrong_target(self):
        frames = [
            self.classify(arrow_frame(855, color=(20, 245, 40))),
            self.classify(np.zeros((720, 1280, 3), dtype=np.uint8)),
            self.classify(arrow_frame(856, color=(20, 245, 40))),
        ]

        result = resolve_stable_marker_frames(frames, expected_slot='green_left3')

        self.assertEqual(result.status, 'wrong_target')
        self.assertEqual(result.assigned_slot, 'green_left4')
        self.assertEqual(result.stable_frames, 2)

    def test_single_frame_never_confirms(self):
        frame = self.classify(arrow_frame(636, color=(20, 245, 40)))

        result = resolve_stable_marker_frames([frame], expected_slot='green_left3')

        self.assertEqual(result.status, 'unconfirmed')
        self.assertEqual(result.stable_frames, 1)

    def test_same_decoded_frame_cannot_satisfy_stable_frame_count(self):
        frame = self.classify(arrow_frame(636, color=(20, 245, 40)))

        result = resolve_stable_marker_frames(
            [frame, frame],
            expected_slot='green_left3',
        )

        self.assertEqual(result.status, 'unconfirmed')
        self.assertEqual(result.stable_frames, 1)


if __name__ == '__main__':
    unittest.main()
