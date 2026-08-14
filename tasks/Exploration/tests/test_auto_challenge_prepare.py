import unittest
from types import SimpleNamespace

from tasks.Exploration.base import BaseExploration, Scene


class FakeOcrRule:
    def __init__(self, text=''):
        self.text = text

    def ocr(self, _image):
        return self.text


class AutoChallengeHarness:
    O_E_AUTO_CHALLENGE = FakeOcrRule()
    I_MAIN_PROTECTION_BACK = object()
    I_CHECK_MAIN = object()
    I_MAIN_GOTO_EXPLORATION = object()
    _home_scene_visible = BaseExploration._home_scene_visible

    def __init__(self, visible=True, main_page=False, ocr_text=''):
        self.visible = visible
        self.main_page = main_page
        self.O_E_AUTO_CHALLENGE.text = ocr_text
        self.device = SimpleNamespace(image=object())
        self.clicks = 0

    def appear(self, rule, **_kwargs):
        return self.main_page and rule in (self.I_CHECK_MAIN, self.I_MAIN_GOTO_EXPLORATION)

    def ocr_appear(self, rule, **_kwargs):
        return rule is self.O_E_AUTO_CHALLENGE and self.visible

    def ocr_appear_click(self, rule, **_kwargs):
        if rule is self.O_E_AUTO_CHALLENGE and self.visible:
            self.clicks += 1
            return True
        return False


class AutoChallengePrepareTest(unittest.TestCase):
    def test_current_exploration_button_is_detected(self):
        harness = AutoChallengeHarness()

        self.assertTrue(BaseExploration._extra_prepare_button_visible(harness))

    def test_current_exploration_button_is_clickable(self):
        harness = AutoChallengeHarness()

        self.assertTrue(BaseExploration._click_extra_prepare_button(harness))
        self.assertEqual(harness.clicks, 1)

    def test_main_page_text_in_same_roi_is_not_a_prepare_button(self):
        harness = AutoChallengeHarness(visible=False, main_page=True, ocr_text='式神录')

        self.assertFalse(BaseExploration._extra_prepare_button_visible(harness))

    def test_known_near_miss_is_still_supported(self):
        harness = AutoChallengeHarness(visible=False, ocr_text='鲁攻')

        self.assertTrue(BaseExploration._extra_prepare_button_visible(harness))

    def test_battle_attack_text_is_not_a_prepare_button(self):
        harness = AutoChallengeHarness(visible=False, ocr_text='普攻')

        self.assertFalse(BaseExploration._extra_prepare_button_visible(harness))

    def test_home_scene_wins_over_generic_prepare_detection(self):
        class SceneHarness:
            I_E_SETTINGS_BUTTON = object()
            I_CHECK_EXPLORATION = object()
            I_EXP_ARROW_LEFT = object()
            I_EXP_ARROW_RIGHT = object()
            I_E_EXPLORATION_CLICK = object()
            I_MAIN_PROTECTION_BACK = object()
            I_CHECK_MAIN = object()
            I_MAIN_GOTO_EXPLORATION = object()

            def is_exploration_world(self):
                return False

            _home_scene_visible = BaseExploration._home_scene_visible

            def appear(self, rule, **_kwargs):
                return rule in (self.I_MAIN_PROTECTION_BACK, self.I_CHECK_MAIN)

        self.assertEqual(BaseExploration.get_current_scene(SceneHarness()), Scene.UNKNOWN)


if __name__ == '__main__':
    unittest.main()
