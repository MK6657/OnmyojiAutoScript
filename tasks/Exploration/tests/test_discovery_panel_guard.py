import unittest

import numpy as np

from tasks.Exploration.base import BaseExploration


class FakeOcr:
    def __init__(self, result):
        self.result = result

    def ocr(self, _image):
        return self.result


class FakeClick:
    def coord(self):
        return 640, 590


class DiscoveryHarness:
    DISCOVERY_PANEL_ROI = BaseExploration.DISCOVERY_PANEL_ROI
    DISCOVERY_PANEL_BRIGHT_THRESHOLD = BaseExploration.DISCOVERY_PANEL_BRIGHT_THRESHOLD
    DISCOVERY_PANEL_MIN_BRIGHT_RATIO = BaseExploration.DISCOVERY_PANEL_MIN_BRIGHT_RATIO
    O_E_DISCOVERY_TITLE = FakeOcr((535, 187, 110, 29))
    C_DISCOVERY_DISMISS = FakeClick()

    def __init__(self, visible=True):
        self.visible = visible
        self.device = type('Device', (), {})()
        self.device.image = np.full((720, 1280, 3), 40, dtype=np.uint8)
        self.device.image[160:560, 150:1135] = 220
        self.clicks = []

    def screenshot(self):
        return None

    def _discovery_panel_visible(self):
        return self.visible and BaseExploration._discovery_panel_visible(self)

    def _discovery_panel_layout_visible(self):
        return BaseExploration._discovery_panel_layout_visible(self)

    def _dismiss_discovery_panel(self, timeout=3.0):
        if not self._discovery_panel_visible():
            return False
        x, y = self.C_DISCOVERY_DISMISS.coord()
        self.clicks.append((x, y))
        self.visible = False
        return True


class DiscoveryPanelGuardTest(unittest.TestCase):
    def test_bright_modal_layout_is_detected_before_settings(self):
        harness = DiscoveryHarness()

        self.assertTrue(harness._discovery_panel_layout_visible())
        self.assertTrue(harness._discovery_panel_visible())

    def test_popup_is_dismissed_once(self):
        harness = DiscoveryHarness()

        self.assertTrue(harness._dismiss_discovery_panel())
        self.assertEqual(harness.clicks, [(640, 590)])
        self.assertFalse(harness._discovery_panel_visible())

    def test_dark_exploration_frame_is_not_classified_as_modal(self):
        harness = DiscoveryHarness()
        harness.device.image[:] = 40

        self.assertFalse(harness._discovery_panel_layout_visible())
        self.assertFalse(harness._discovery_panel_visible())


if __name__ == '__main__':
    unittest.main()
