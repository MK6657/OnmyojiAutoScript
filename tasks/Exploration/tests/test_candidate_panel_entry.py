import unittest

from tasks.Exploration.base import BaseExploration


class FakeRule:
    def __init__(self, name):
        self.name = name

    def front_center(self):
        return 1152, 443


class CandidateEntryHarness:
    _candidate_panel_visible = BaseExploration._candidate_panel_visible
    _confirm_candidate_panel = BaseExploration._confirm_candidate_panel
    enter_settings_and_do_operations = BaseExploration.enter_settings_and_do_operations

    I_E_SURE_BUTTON = FakeRule('sure')
    I_E_RATATE_EXSIT = FakeRule('rotate')
    I_E_OPEN_SETTINGS = FakeRule('open_settings')
    I_E_SETTINGS_BUTTON = FakeRule('settings_button')

    class NumberRule:
        def ocr(self, _image):
            return 44, 6, 50

    O_E_ALTERNATE_NUMBER = NumberRule()

    def __init__(self):
        self.sure_visible = True
        self.settings_clicks = 0
        self.confirm_clicks = 0
        self.device = type('Device', (), {'image': object()})()
        self.device.click = self._confirm_click

    def _confirm_click(self, *_args, **_kwargs):
        self.confirm_clicks += 1
        self.sure_visible = False

    def screenshot(self):
        return None

    def _discovery_panel_visible(self):
        return False

    def appear(self, rule, *args, **kwargs):
        if rule is self.I_E_SURE_BUTTON:
            return self.sure_visible
        if rule is self.I_E_RATATE_EXSIT:
            return False
        if rule is self.I_E_OPEN_SETTINGS:
            return False
        return False

    def appear_then_click(self, rule, *args, **kwargs):
        if rule is self.I_E_SETTINGS_BUTTON:
            self.settings_clicks += 1
        return False


class CandidatePanelEntryTest(unittest.TestCase):
    def test_existing_candidate_panel_is_confirmed_without_settings_click(self):
        harness = CandidateEntryHarness()

        self.assertIsNone(harness.enter_settings_and_do_operations())
        self.assertEqual(harness.settings_clicks, 0)
        self.assertEqual(harness.confirm_clicks, 1)


if __name__ == '__main__':
    unittest.main()
