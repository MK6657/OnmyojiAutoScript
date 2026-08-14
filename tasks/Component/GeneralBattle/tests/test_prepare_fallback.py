import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from tasks.Component.GeneralBattle.general_battle import (
    GeneralBattle,
    O_BATTLE_PREPARE_WIDE as GENERAL_WIDE_RULE,
)


class PrepareFallbackHarness:
    I_PREPARE_HIGHLIGHT = object()
    I_PREPARE_DARK = object()
    O_BATTLE_PREPARE = object()
    O_BATTLE_PREPARE_WIDE = object()

    class PrepareClick:
        def coord(self):
            return 1178, 586

    I_PREPARE_HIGHLIGHT = PrepareClick()
    WIDE_RULE = GENERAL_WIDE_RULE

    def _extra_prepare_button_visible(self):
        return False

    def _click_extra_prepare_button(self, interval=None):
        return False

    _prepare_button_visible = GeneralBattle._prepare_button_visible
    _new_prepare_button_visible = staticmethod(GeneralBattle._new_prepare_button_visible)
    _click_prepare_button = GeneralBattle._click_prepare_button
    _click_prepare_safe = GeneralBattle._click_prepare_safe

    def __init__(self, ocr_visible=True, wide_ocr_visible=False):
        self.ocr_visible = ocr_visible
        self.wide_ocr_visible = wide_ocr_visible
        self.ocr_clicks = 0
        self.wide_ocr_clicks = 0
        self.visual_clicks = 0
        self.safe_clicks = []
        self.device = SimpleNamespace(
            click=lambda x, y, **kwargs: self.safe_clicks.append(
                {'x': x, 'y': y, **kwargs}
            )
        )

    def appear(self, _rule, **_kwargs):
        return False

    def appear_then_click(self, _rule, **_kwargs):
        return False

    def ocr_appear(self, rule, **_kwargs):
        return (
            rule is self.O_BATTLE_PREPARE and self.ocr_visible
        ) or (
            getattr(rule, 'name', '') == 'BATTLE_PREPARE_WIDE'
            and self.wide_ocr_visible
        )

    def ocr_appear_click(self, rule, **_kwargs):
        if rule is self.O_BATTLE_PREPARE and self.ocr_visible:
            self.ocr_clicks += 1
            return True
        if (
            getattr(rule, 'name', '') == 'BATTLE_PREPARE_WIDE'
            and self.wide_ocr_visible
        ):
            self.wide_ocr_clicks += 1
            return True
        return False

    def _visual_click(self, _x, _y, **_kwargs):
        self.visual_clicks += 1


class BattleBeforePrepareHarness:
    I_BATTLE_INFO = object()
    I_DISABLE_7DAYS_DIFF_SOUL = object()
    I_CONFIRM_CLOSE_DIFF_SOUL = object()

    battle_before = GeneralBattle.battle_before
    LOCKED_AUTO_START_GRACE = 0.04

    def __init__(
        self,
        auto_start_after_screenshots=None,
        transient_prepare_after_auto_start=False,
    ):
        self.prepare_visible = True
        self.real_battle = False
        self.prepare_clicks = 0
        self.screenshot_count = 0
        self.auto_start_after_screenshots = auto_start_after_screenshots
        self.transient_prepare_after_auto_start = transient_prepare_after_auto_start
        self.current_count = 1
        self.device = SimpleNamespace(image=None)

    def screenshot(self):
        self.screenshot_count += 1
        if (
            self.auto_start_after_screenshots is not None
            and self.screenshot_count >= self.auto_start_after_screenshots
        ):
            self.prepare_visible = False
            self.real_battle = True
            if (
                self.transient_prepare_after_auto_start
                and self.screenshot_count == self.auto_start_after_screenshots + 1
            ):
                self.prepare_visible = True
        return None

    def _battle_result_continue_visible(self):
        return False

    def _prepare_button_visible(self):
        return self.prepare_visible

    def is_in_prepare(self, _is_screenshot=False):
        return False

    def is_in_real_battle(self, _is_screenshot=False):
        return self.real_battle

    def appear(self, rule, **_kwargs):
        if rule is not self.I_BATTLE_INFO or not self.real_battle:
            return False
        if self.transient_prepare_after_auto_start:
            return self.screenshot_count >= self.auto_start_after_screenshots + 2
        return True

    def appear_then_click(self, _rule, **_kwargs):
        return False

    def _click_prepare_button(self, **_kwargs):
        self.prepare_clicks += 1
        self.prepare_visible = False
        self.real_battle = True
        return True

    def check_and_open_buff(self, _buff):
        return True

    def switch_preset_team(self, *_args, **_kwargs):
        return True


class PrepareFallbackTest(unittest.TestCase):
    def test_ocr_detects_prepare_when_image_templates_miss(self):
        harness = PrepareFallbackHarness()

        self.assertTrue(harness._prepare_button_visible())

    def test_ocr_clicks_prepare_when_image_templates_miss(self):
        harness = PrepareFallbackHarness()

        self.assertTrue(harness._click_prepare_button())
        self.assertEqual(len(harness.safe_clicks), 1)

    def test_missing_prepare_is_not_reported_as_visible(self):
        harness = PrepareFallbackHarness(ocr_visible=False)

        self.assertFalse(harness._prepare_button_visible())
        self.assertFalse(harness._click_prepare_button())

    def test_current_blue_prepare_control_is_detected_when_ocr_misses(self):
        harness = PrepareFallbackHarness(ocr_visible=False)
        harness.device = type('Device', (), {})()
        harness.device.image = np.full((720, 1280, 3), 90, dtype=np.uint8)
        harness.device.image[500:680, 1080:1280] = (120, 180, 235)

        self.assertTrue(harness._prepare_button_visible())

    def test_wide_ocr_clicks_current_prepare_control(self):
        harness = PrepareFallbackHarness(ocr_visible=False, wide_ocr_visible=True)

        self.assertTrue(harness._click_prepare_button())
        self.assertEqual(len(harness.safe_clicks), 1)

    def test_visual_fallback_clicks_after_detection(self):
        harness = PrepareFallbackHarness(ocr_visible=False)
        harness.device = type('Device', (), {})()
        harness.device.image = np.full((720, 1280, 3), 90, dtype=np.uint8)
        harness.device.image[500:680, 1080:1280] = (120, 180, 235)
        harness.device.click = harness._visual_click

        self.assertTrue(harness._click_prepare_button())
        self.assertEqual(harness.visual_clicks, 1)

    def test_active_battle_colours_are_not_treated_as_prepare(self):
        harness = PrepareFallbackHarness(ocr_visible=False)
        harness.device = type('Device', (), {})()
        harness.device.image = np.full((720, 1280, 3), 90, dtype=np.uint8)
        harness.device.image[500:680, 1080:1280] = (80, 80, 80)

        self.assertFalse(harness._prepare_button_visible())

    def test_blue_background_outside_button_does_not_trigger_prepare(self):
        harness = PrepareFallbackHarness(ocr_visible=False)
        harness.device = type('Device', (), {})()
        harness.device.image = np.full((720, 1280, 3), 90, dtype=np.uint8)
        harness.device.image[500:680, 1080:1280] = (120, 180, 235)
        harness.device.image[536:636, 1128:1228] = (80, 80, 80)

        self.assertFalse(harness._prepare_button_visible())

    def test_template_prepare_uses_safe_center_click_zone(self):
        harness = PrepareFallbackHarness(ocr_visible=False)
        harness.template_visible = True

        def appear(rule, **_kwargs):
            return rule is harness.I_PREPARE_HIGHLIGHT and harness.template_visible

        harness.appear = appear

        self.assertTrue(harness._click_prepare_button())
        self.assertEqual(len(harness.safe_clicks), 1)
        click = harness.safe_clicks[0]
        self.assertGreaterEqual(click['x'], 1160)
        self.assertLess(click['x'], 1215)
        self.assertGreaterEqual(click['y'], 585)
        self.assertLess(click['y'], 640)

    def test_battle_before_clicks_prepare_before_weak_friends_signal(self):
        harness = BattleBeforePrepareHarness()
        config = SimpleNamespace(
            lock_team_enable=False,
            preset_enable=False,
            preset_group=0,
            preset_team=0,
            preset_group_name='',
            preset_team_name='',
        )

        self.assertTrue(harness.battle_before(None, config, timeout=1))
        self.assertEqual(harness.prepare_clicks, 1)

    def test_locked_team_auto_start_does_not_click_prepare(self):
        harness = BattleBeforePrepareHarness(auto_start_after_screenshots=2)
        harness._battle_lock_expected_active = True
        config = SimpleNamespace(lock_team_enable=True)

        self.assertTrue(harness.battle_before(None, config, timeout=1))
        self.assertEqual(harness.prepare_clicks, 0)
        self.assertTrue(harness._battle_lock_expected_active)

    def test_locked_auto_start_ignores_transient_prepare_and_logs_once(self):
        harness = BattleBeforePrepareHarness(
            auto_start_after_screenshots=2,
            transient_prepare_after_auto_start=True,
        )
        harness._battle_lock_expected_active = True
        config = SimpleNamespace(lock_team_enable=True)

        with patch(
            'tasks.Component.GeneralBattle.general_battle.logger.info'
        ) as info:
            self.assertTrue(harness.battle_before(None, config, timeout=1))

        verified = [
            str(call.args[0])
            for call in info.call_args_list
            if call.args and 'LOCK_VALIDATION state=verified' in str(call.args[0])
        ]
        self.assertEqual(verified, [
            'LOCK_VALIDATION state=verified '
            'reason=battle_entered_without_prepare_click'
        ])
        self.assertEqual(harness.prepare_clicks, 0)

    def test_stale_lock_indicator_falls_back_to_bounded_prepare_click(self):
        harness = BattleBeforePrepareHarness()
        harness._battle_lock_expected_active = True
        config = SimpleNamespace(lock_team_enable=True)

        self.assertTrue(harness.battle_before(None, config, timeout=1))
        self.assertEqual(harness.prepare_clicks, 1)
        self.assertFalse(harness._battle_lock_expected_active)


if __name__ == '__main__':
    unittest.main()
