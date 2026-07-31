import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from tasks.RealmRaid.script_task import ScriptTask


PARTITIONS = (
    (233, 147, 229, 120),
    (566, 148, 237, 115),
    (900, 147, 222, 116),
    (236, 283, 229, 124),
    (564, 280, 237, 120),
    (900, 282, 222, 120),
    (233, 416, 236, 121),
    (567, 413, 230, 124),
    (900, 418, 222, 116),
)


def make_board(background, foreground, names):
    image = np.full((720, 1280, 3), background, dtype=np.uint8)
    for (x, y, _width, _height), name in zip(PARTITIONS, names):
        cv2.putText(
            image,
            name,
            (x + 8, y + 36),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (foreground, foreground, foreground),
            1,
            cv2.LINE_AA,
        )
    return image


class BoardSignatureTest(unittest.TestCase):
    def setUp(self):
        self.partitions = [SimpleNamespace(roi_back=value) for value in PARTITIONS]
        self.names = tuple(f'player-{index}' for index in range(1, 10))

    def test_signature_ignores_card_brightness(self):
        bright = make_board(220, 35, self.names)
        dimmed = make_board(135, 20, self.names)

        self.assertEqual(
            ScriptTask._layout_hash(bright, self.partitions),
            ScriptTask._layout_hash(dimmed, self.partitions),
        )

    def test_signature_changes_with_opponent_names(self):
        original = make_board(220, 35, self.names)
        changed_names = self.names[:-1] + ('different',)
        changed = make_board(220, 35, changed_names)

        self.assertNotEqual(
            ScriptTask._layout_hash(original, self.partitions),
            ScriptTask._layout_hash(changed, self.partitions),
        )


if __name__ == '__main__':
    unittest.main()
