import unittest

import numpy as np

from module.atom.animate import RuleAnimate
from module.atom.image import RuleImage


class RuleAnimateStableTest(unittest.TestCase):
    def _rule(self):
        source = RuleImage(
            roi_front=(1, 1, 6, 6),
            roi_back=(0, 0, 10, 10),
            method='Template matching',
            threshold=0.9,
            file='',
        )
        return RuleAnimate(source, threshold=0.9)

    def _image(self, value):
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        image[1:7, 1:7] = value
        return image

    def test_identical_roi_is_stable(self):
        rule = self._rule()
        image = self._image(80)

        self.assertFalse(rule.stable(image))
        self.assertTrue(rule.stable(image))

    def test_changed_roi_is_not_stable(self):
        rule = self._rule()

        self.assertFalse(rule.stable(self._image(80)))
        self.assertFalse(rule.stable(self._image(160)))


if __name__ == '__main__':
    unittest.main()
