import unittest
from unittest.mock import patch

from tasks.Component.GeneralBattle.general_battle import GeneralBattle


class FakeRule:
    def __init__(self, name, roi_front=(700, 380, 80, 80)):
        self.name = name
        self.roi_front = roi_front


class FakeDevice:
    def __init__(self):
        self.clicks = []

    def click(self, x, y, control_name='Click'):
        self.clicks.append((x, y, control_name))


class ExitFlowHarness:
    I_EXIT = FakeRule('GB_EXIT')
    I_EXIT_ENSURE = FakeRule('GB_EXIT_ENSURE')
    I_FALSE = FakeRule('GB_FALSE')

    def __init__(self, confirmation_visible=True):
        self.device = FakeDevice()
        self.confirmation_visible = confirmation_visible
        self.exit_clicks = 0
        self.confirm_clicks = 0

    def screenshot(self):
        return None

    def appear(self, rule):
        if rule is self.I_EXIT_ENSURE:
            return self.confirmation_visible and self.exit_clicks == 1
        return False

    def appear_then_click(self, rule, interval=0):
        if rule is self.I_EXIT:
            self.exit_clicks += 1
            return True
        if rule is self.I_EXIT_ENSURE and self.appear(rule):
            self.confirm_clicks += 1
            return True
        return False


class BattleExitFlowTest(unittest.TestCase):
    @patch('tasks.Component.GeneralBattle.general_battle.time.sleep', return_value=None)
    def test_exit_button_is_clicked_once_before_confirmation(self, _sleep):
        harness = ExitFlowHarness(confirmation_visible=True)

        result = GeneralBattle._request_battle_exit(
            harness,
            timeout=0.1,
            confirm_timeout=0.1,
        )

        self.assertTrue(result)
        self.assertEqual(harness.exit_clicks, 1)
        self.assertEqual(harness.confirm_clicks, 1)
        self.assertEqual(harness.device.clicks, [])

    @patch('tasks.Component.GeneralBattle.general_battle.time.sleep', return_value=None)
    def test_missing_confirmation_uses_one_named_fallback_click(self, _sleep):
        harness = ExitFlowHarness(confirmation_visible=False)

        result = GeneralBattle._request_battle_exit(
            harness,
            timeout=0.1,
            confirm_timeout=0,
        )

        self.assertTrue(result)
        self.assertEqual(harness.exit_clicks, 1)
        self.assertEqual(harness.confirm_clicks, 0)
        self.assertEqual(len(harness.device.clicks), 1)
        self.assertEqual(harness.device.clicks[0][2], 'GB_EXIT_ENSURE_FALLBACK')


if __name__ == '__main__':
    unittest.main()
