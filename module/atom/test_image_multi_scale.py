import unittest

import cv2
import numpy as np

from module.atom.image import RuleImage


class MultiScaleRoiTest(unittest.TestCase):
    def test_roi_size_comes_from_winning_scale(self):
        rng = np.random.default_rng(42)
        template = rng.integers(0, 255, (20, 20, 3), dtype=np.uint8)
        scaled = cv2.resize(template, (10, 10))
        source = np.zeros((60, 60, 3), dtype=np.uint8)
        source[25:35, 30:40] = scaled

        rule = RuleImage(
            roi_front=(0, 0, 20, 20),
            roi_back=(0, 0, 60, 60),
            method='Template matching',
            threshold=0.99,
            file='',
        )
        rule._image = template
        rule._images = [template]

        self.assertTrue(rule.match_multi_scale(source, scales=[0.5, 1.0]))
        self.assertEqual(rule.roi_front[2:4], [10, 10])


if __name__ == '__main__':
    unittest.main()
