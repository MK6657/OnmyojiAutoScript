import unittest
from types import SimpleNamespace

import numpy as np

from module.exception import GameStuckError
from tasks.Component.GeneralBattle.general_battle import GeneralBattle


class ResultContinueHarness:
    I_BATTLE_INFO = object()
    I_FRIENDS = object()
    I_WIN = object()
    I_FALSE = object()
    I_REWARD = object()
    O_BATTLE_RESULT_CONTINUE = object()
    I_DE_WIN = object()
    I_REWARD_GOLD = object()
    _dismiss_battle_result_continue = GeneralBattle._dismiss_battle_result_continue
    _battle_result_continue_visible = GeneralBattle._battle_result_continue_visible
    _click_result_continue_center = GeneralBattle._click_result_continue_center

    def __init__(self, result_visible=False):
        self.result_visible = result_visible

    def appear(self, _rule, **_kwargs):
        return False

    def ocr_appear(self, rule, **_kwargs):
        return rule is self.O_BATTLE_RESULT_CONTINUE and self.result_visible

    def _prepare_button_visible(self):
        return False


class StrictResultOcr:
    def __init__(self, text):
        self.text = text

    def ocr_single(self, _image):
        return self.text


class StrictResultHarness:
    O_BATTLE_RESULT_CONTINUE = StrictResultOcr('')
    _battle_result_continue_visible = GeneralBattle._battle_result_continue_visible
    _battle_result_visual_heuristic = staticmethod(GeneralBattle._battle_result_visual_heuristic)

    def __init__(self, text):
        self.O_BATTLE_RESULT_CONTINUE = StrictResultOcr(text)
        self.device = SimpleNamespace(image=object())

    def ocr_appear(self, _rule, **_kwargs):
        return True


class BattleWaitHarness(ResultContinueHarness):
    class Device:
        def __init__(self):
            self.cleared = False

        def stuck_record_add(self, _name):
            return None

        def click_record_clear(self):
            self.cleared = True

    def __init__(self):
        super().__init__(result_visible=True)
        self.device = self.Device()
        self.clicks = 0

    def screenshot(self):
        return None

    def ocr_appear_click(self, rule, **_kwargs):
        if rule is self.O_BATTLE_RESULT_CONTINUE:
            self.clicks += 1
            self.result_visible = False
            return True
        return False

    def appear_then_click(self, _rule, **_kwargs):
        return False

    def wait_until_appear(self, *_args, **_kwargs):
        raise AssertionError('legacy reward wait should be skipped')


class FalsePositiveRewardHarness(BattleWaitHarness):
    def __init__(self):
        super().__init__()
        self.result_visible = False
        self.reward_clicks = 0

    def appear(self, rule, **_kwargs):
        if rule in (self.I_REWARD, self.I_REWARD_GOLD):
            return True
        return False

    def appear_then_click(self, rule, **_kwargs):
        if rule in (self.I_REWARD, self.I_REWARD_GOLD):
            self.reward_clicks += 1
            return True
        return False


class PendingResultHarness:
    O_BATTLE_RESULT_CONTINUE = object()
    _dismiss_battle_result_continue = GeneralBattle._dismiss_battle_result_continue
    _battle_result_continue_visible = GeneralBattle._battle_result_continue_visible

    def __init__(self):
        self.result_visible = True
        self.clicks = 0

    def screenshot(self):
        return None

    def ocr_appear(self, rule, **_kwargs):
        return rule is self.O_BATTLE_RESULT_CONTINUE and self.result_visible

    def ocr_appear_click(self, rule, **_kwargs):
        if rule is self.O_BATTLE_RESULT_CONTINUE and self.result_visible:
            self.clicks += 1
            self.result_visible = False
            return True
        return False


class PreflightContextHarness:
    def __init__(self):
        self.calls = []

    def _dismiss_battle_result_continue(self, **kwargs):
        self.calls.append(kwargs)
        return True


class PreparationResultHarness(ResultContinueHarness):
    def screenshot(self):
        return None

    def is_in_real_battle(self, _is_screenshot=False):
        return False


class MultiPageResultHarness(ResultContinueHarness):
    def __init__(self, pages=2):
        super().__init__(result_visible=True)
        self.pages = pages
        self.clicks = 0

    def screenshot(self):
        return None

    def ocr_appear_click(self, rule, **_kwargs):
        if rule is self.O_BATTLE_RESULT_CONTINUE and self.pages:
            self.clicks += 1
            self.pages -= 1
            self.result_visible = self.pages > 0
            return True
        return False


class CenterFallbackHarness(ResultContinueHarness):
    class Device:
        def __init__(self, owner):
            self.owner = owner
            self.fallback_clicks = 0

        def click(self, **_kwargs):
            self.fallback_clicks += 1
            self.owner.result_visible = False

    def __init__(self):
        super().__init__(result_visible=True)
        self.roi_clicks = 0
        self.device = self.Device(self)

    def ocr_appear_click(self, rule, **_kwargs):
        if rule is self.O_BATTLE_RESULT_CONTINUE and self.result_visible:
            self.roi_clicks += 1
            return True
        return False


class BottomFallbackHarness(ResultContinueHarness):
    class Device:
        def __init__(self, owner):
            self.owner = owner
            self.clicks = []
            self.image = None

        def click(self, **kwargs):
            self.clicks.append(kwargs)
            self.owner.result_visible = False

    _click_result_continue_bottom = GeneralBattle._click_result_continue_bottom

    def __init__(self):
        super().__init__(result_visible=True)
        self.device = self.Device(self)


class EmptyOcrVisualHarness:
    class Prompt:
        def ocr_single(self, _image):
            return ''

    class Device:
        def __init__(self, owner):
            self.owner = owner
            self.image = owner._result_image()
            self.clicks = 0

        def click(self, **_kwargs):
            self.clicks += 1
            self.image = np.zeros((720, 1280, 3), dtype=np.uint8)

    _battle_result_continue_visible = GeneralBattle._battle_result_continue_visible
    _battle_result_visual_heuristic = staticmethod(GeneralBattle._battle_result_visual_heuristic)
    _dismiss_battle_result_continue = GeneralBattle._dismiss_battle_result_continue
    _click_result_continue_bottom = GeneralBattle._click_result_continue_bottom

    def __init__(self, prepare=False):
        self.prepare = prepare
        self.O_BATTLE_RESULT_CONTINUE = self.Prompt()
        self.device = self.Device(self)
        self._allow_empty_result_visual = True

    @staticmethod
    def _result_image():
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[650:715, 520:780] = 100
        return image

    def ocr_appear(self, _rule, **_kwargs):
        return False

    def ocr_appear_click(self, _rule, **_kwargs):
        return False

    def _prepare_button_visible(self):
        return self.prepare

    def screenshot(self):
        return self.device.image

    def appear(self, _rule, **_kwargs):
        return False


class OcrMismatchFallbackHarness:
    class Prompt:
        def __init__(self, owner):
            self.owner = owner

        def ocr_single(self, _image):
            return self.owner.prompt_text

    class Device:
        def __init__(self, owner):
            self.owner = owner
            self.image = np.zeros((720, 1280, 3), dtype=np.uint8)
            self.clicks = 0

        def click(self, **_kwargs):
            self.clicks += 1
            self.owner.prompt_text = ''

    _battle_result_continue_visible = GeneralBattle._battle_result_continue_visible
    _dismiss_battle_result_continue = GeneralBattle._dismiss_battle_result_continue
    _click_result_continue_bottom = GeneralBattle._click_result_continue_bottom

    def __init__(self):
        self.prompt_text = '\u5360\u51fb\u5c4f\u5e55\u7ee7\u7eed'
        self.O_BATTLE_RESULT_CONTINUE = self.Prompt(self)
        self.device = self.Device(self)

    def ocr_appear_click(self, _rule, **_kwargs):
        return False

    def _prepare_button_visible(self):
        return False


class ResultContinueTest(unittest.TestCase):
    def test_preparation_text_is_not_a_result_prompt(self):
        harness = StrictResultHarness('点击式神区域进行配置')

        self.assertFalse(harness._battle_result_continue_visible())

    def test_real_tap_to_continue_text_is_a_result_prompt(self):
        harness = StrictResultHarness('点击屏幕继续')

        self.assertTrue(harness._battle_result_continue_visible())

    def test_unrelated_nonempty_ocr_does_not_use_visual_fallback(self):
        harness = StrictResultHarness('\u961f\u4f0d\u9884\u8bbe')
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[650:715, 520:780] = 100
        harness.device.image = image
        harness._allow_empty_result_visual = True

        self.assertFalse(harness._battle_result_continue_visible())

    def test_result_continue_is_treated_as_battle_state(self):
        harness = ResultContinueHarness(result_visible=True)

        self.assertTrue(GeneralBattle.is_in_battle(harness, is_screenshot=False))
        self.assertFalse(GeneralBattle.is_in_real_battle(harness, is_screenshot=False))

    def test_unrelated_board_is_not_treated_as_result(self):
        harness = ResultContinueHarness(result_visible=False)

        self.assertFalse(GeneralBattle.is_in_battle(harness, is_screenshot=False))

    def test_tap_to_continue_skips_legacy_reward_wait(self):
        harness = BattleWaitHarness()

        self.assertTrue(GeneralBattle.battle_wait(harness, random_click_swipt_enable=False))
        self.assertEqual(harness.clicks, 1)

    def test_reward_template_is_ignored_without_result_context(self):
        harness = FalsePositiveRewardHarness()

        with self.assertRaises(GameStuckError):
            GeneralBattle.battle_wait(
                harness,
                random_click_swipt_enable=False,
                timeout=0.01,
            )

        self.assertEqual(harness.reward_clicks, 0)

    def test_pending_result_is_consumed_before_prepare(self):
        harness = PendingResultHarness()

        self.assertTrue(GeneralBattle.run_general_battle(harness))
        self.assertEqual(harness.clicks, 1)

    def test_preflight_disables_task_specific_reward_fallback(self):
        harness = PreflightContextHarness()

        self.assertTrue(GeneralBattle.run_general_battle(harness))
        self.assertEqual(harness.calls, [{'allow_task_reward': False}])

    def test_result_continue_after_prepare_is_a_completed_transition(self):
        harness = PreparationResultHarness(result_visible=True)

        self.assertTrue(GeneralBattle.battle_before(harness, None, None))

    def test_result_continue_sequence_stays_in_one_battle(self):
        harness = MultiPageResultHarness(pages=2)

        self.assertTrue(GeneralBattle._dismiss_battle_result_continue(harness))
        self.assertEqual(harness.clicks, 2)

    def test_result_continue_uses_one_center_fallback_after_roi_click_stalls(self):
        harness = CenterFallbackHarness()

        self.assertTrue(
            GeneralBattle._dismiss_battle_result_continue(
                harness,
                timeout=0,
                max_clicks=3,
            )
        )
        self.assertEqual(harness.roi_clicks, 1)
        self.assertEqual(harness.device.fallback_clicks, 1)

    def test_result_continue_bottom_fallback_uses_screen_bottom(self):
        harness = BottomFallbackHarness()

        self.assertTrue(harness._click_result_continue_bottom())
        self.assertEqual(
            harness.device.clicks[0]['control_name'],
            'BATTLE_RESULT_CONTINUE_BOTTOM',
        )
        self.assertEqual(
            (harness.device.clicks[0]['x'], harness.device.clicks[0]['y']),
            (640, 675),
        )

    def test_result_continue_limit_is_not_reported_as_success(self):
        harness = MultiPageResultHarness(pages=4)

        with self.assertRaises(GameStuckError):
            GeneralBattle._dismiss_battle_result_continue(harness, timeout=0, max_clicks=3)

        self.assertEqual(harness.clicks, 3)

    def test_empty_ocr_uses_visual_result_and_safe_click(self):
        harness = EmptyOcrVisualHarness()

        self.assertTrue(harness._battle_result_continue_visible())
        self.assertTrue(
            harness._dismiss_battle_result_continue(timeout=0, max_clicks=1)
        )
        self.assertEqual(harness.device.clicks, 1)

    def test_empty_ocr_visual_result_is_rejected_on_prepare_page(self):
        harness = EmptyOcrVisualHarness(prepare=True)

        self.assertFalse(harness._battle_result_continue_visible())
        self.assertEqual(harness.device.clicks, 0)

    def test_ocr_substitution_uses_bottom_safe_click(self):
        harness = OcrMismatchFallbackHarness()

        self.assertTrue(
            GeneralBattle._dismiss_battle_result_continue(
                harness, timeout=0, max_clicks=1
            )
        )
        self.assertEqual(harness.device.clicks, 1)


if __name__ == '__main__':
    unittest.main()
