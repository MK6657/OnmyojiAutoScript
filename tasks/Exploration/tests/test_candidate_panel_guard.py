import unittest

from tasks.Exploration.base import BaseExploration


class FakeRule:
    def __init__(self, name):
        self.name = name


class CandidatePanelHarness:
    I_E_SURE_BUTTON = FakeRule('e_sure_button')
    I_E_RATATE_EXSIT = FakeRule('e_ratate_exsit')

    def __init__(self, sure_visible=False, rotate_visible=False):
        self.sure_visible = sure_visible
        self.rotate_visible = rotate_visible

    def appear(self, rule):
        if rule is self.I_E_SURE_BUTTON:
            return self.sure_visible
        if rule is self.I_E_RATATE_EXSIT:
            return self.rotate_visible
        return False


class CandidatePanelGuardTest(unittest.TestCase):
    def test_candidate_panel_uses_modal_controls(self):
        harness = CandidatePanelHarness(sure_visible=True)

        self.assertTrue(BaseExploration._candidate_panel_visible(harness))

    def test_settings_button_is_not_required_inside_modal(self):
        harness = CandidatePanelHarness(rotate_visible=True)

        self.assertTrue(BaseExploration._candidate_panel_visible(harness))

    def test_missing_modal_is_rejected(self):
        harness = CandidatePanelHarness()

        self.assertFalse(BaseExploration._candidate_panel_visible(harness))


if __name__ == '__main__':
    unittest.main()
