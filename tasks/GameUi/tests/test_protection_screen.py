import unittest

import cv2
import numpy as np

from tasks.GameUi.game_ui import GameUi


class ProtectionScreenTest(unittest.TestCase):
    def test_aligned_four_button_row_returns_leftmost_back_point(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        for x in (56, 128, 200, 272):
            cv2.circle(image, (x, 53), 25, (80, 120, 180), thickness=5)

        point = GameUi._main_protection_back_point(image)
        self.assertIsNotNone(point)
        self.assertLessEqual(abs(point[0] - 56), 1)
        self.assertLessEqual(abs(point[1] - 53), 1)

    def test_single_page_arrow_is_not_enough(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        cv2.circle(image, (56, 53), 25, (80, 120, 180), thickness=5)

        self.assertIsNone(GameUi._main_protection_back_point(image))


if __name__ == '__main__':
    unittest.main()
