import unittest

from tasks.Component.GeneralBattle.general_battle import GeneralBattle, O_PRESET_CONFIRM
from tasks.Component.SwitchSoul.assets import SwitchSoulAssets


class PresetConfirmHarness:
    _preset_confirm_visible = GeneralBattle._preset_confirm_visible
    _click_current_preset_confirm = GeneralBattle._click_current_preset_confirm

    def __init__(self, template_match=False, ocr_match=False):
        self.template_match = template_match
        self.ocr_match = ocr_match
        self.ocr_calls = 0
        self.clicks = []

    def appear(self, _asset):
        return self.template_match

    def ocr_appear(self, _asset):
        self.ocr_calls += 1
        return self.ocr_match

    def click(self, asset):
        self.clicks.append(asset)


class PresetConfirmDetectionTest(unittest.TestCase):
    def test_legacy_template_remains_fast_path(self):
        harness = PresetConfirmHarness(template_match=True)

        self.assertTrue(harness._click_current_preset_confirm())
        self.assertEqual(harness.clicks, [SwitchSoulAssets.I_SOU_SWITCH_SURE])
        self.assertEqual(harness.ocr_calls, 0)

    def test_current_confirm_uses_ocr_fallback(self):
        harness = PresetConfirmHarness(ocr_match=True)

        self.assertTrue(harness._click_current_preset_confirm())
        self.assertEqual([str(click) for click in harness.clicks], [str(O_PRESET_CONFIRM)])
        self.assertEqual(harness.ocr_calls, 1)

    def test_missing_confirm_does_not_click(self):
        harness = PresetConfirmHarness()

        self.assertFalse(harness._click_current_preset_confirm())
        self.assertEqual(harness.clicks, [])

    def test_visibility_uses_ocr_when_template_is_stale(self):
        harness = PresetConfirmHarness(ocr_match=True)

        self.assertTrue(harness._preset_confirm_visible())


if __name__ == '__main__':
    unittest.main()
