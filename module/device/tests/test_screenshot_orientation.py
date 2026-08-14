import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from module.device.screenshot import Screenshot


class ScreenshotOrientationTest(unittest.TestCase):
    def test_portrait_frame_uses_mumu_fallback_and_preserves_landscape_shape(self):
        device = SimpleNamespace(orientation=0)
        image = np.zeros((1280, 720, 3), dtype=np.uint8)

        result = Screenshot._handle_orientated_image(device, image)

        self.assertEqual(result.shape, (720, 1280, 3))
        self.assertEqual(device.orientation, 1)
        np.testing.assert_array_equal(
            result,
            cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE),
        )

    def test_known_landscape_frame_is_not_rotated(self):
        device = SimpleNamespace(orientation=0)
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[123, 456] = (1, 2, 3)

        result = Screenshot._handle_orientated_image(device, image)

        self.assertIs(result, image)
        self.assertEqual(device.orientation, 0)


if __name__ == '__main__':
    unittest.main()
