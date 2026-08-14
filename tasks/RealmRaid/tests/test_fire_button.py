import unittest

from tasks.RealmRaid.assets import RealmRaidAssets
from tasks.RealmRaid.script_task import ScriptTask


class FireButtonHarness:
    _click_realm_raid_fire = ScriptTask._click_realm_raid_fire

    I_FIRE = 'legacy-fire'
    I_FIRE_CURRENT = 'current-fire'

    def __init__(self, legacy=False, current=False):
        self.legacy = legacy
        self.current = current
        self.clicked = []

    def appear_then_click(self, asset, interval=1.0, threshold=None):
        self.clicked.append(asset)
        if asset == self.I_FIRE:
            return self.legacy
        return self.current


class FireButtonTest(unittest.TestCase):
    def test_current_detail_search_area_covers_left_and_center_layouts(self):
        x, y, width, height = RealmRaidAssets.I_FIRE_CURRENT.roi_back

        self.assertLessEqual(x, 318)
        self.assertLessEqual(x, 649)
        self.assertLessEqual(y, 359)
        self.assertGreaterEqual(x + width, 649 + 136)
        self.assertGreaterEqual(y + height, 493 + 63)
        self.assertGreaterEqual(y + height, 629 + 63)

    def test_current_detail_card_button_is_fallback(self):
        harness = FireButtonHarness(current=True)

        self.assertTrue(harness._click_realm_raid_fire())
        self.assertEqual(harness.clicked, ['legacy-fire', 'current-fire'])

    def test_legacy_button_keeps_priority(self):
        harness = FireButtonHarness(legacy=True, current=True)

        self.assertTrue(harness._click_realm_raid_fire())
        self.assertEqual(harness.clicked, ['legacy-fire'])


if __name__ == '__main__':
    unittest.main()
