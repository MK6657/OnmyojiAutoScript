import unittest

from module.exception import GameStuckError
from tasks.Exploration.base import BaseExploration


class FakeRule:
    def __init__(self, name):
        self.name = name


class AutoRotateHarness:
    I_E_AUTO_ROTATE_ON = FakeRule('auto_rotate_on')
    I_E_AUTO_ROTATE_OFF = FakeRule('auto_rotate_off')
    I_E_SETTINGS_BUTTON = FakeRule('settings_button')

    def __init__(self, on=False, off=False, settings=True):
        self.on = on
        self.off = off
        self.settings = settings

    def screenshot(self):
        return None

    def appear(self, rule, *args, **kwargs):
        if rule is self.I_E_AUTO_ROTATE_ON:
            return self.on
        if rule is self.I_E_AUTO_ROTATE_OFF:
            return self.off
        if rule is self.I_E_SETTINGS_BUTTON:
            return self.settings
        return False

    def appear_then_click(self, _rule, interval=0):
        return False


class StuckAutoRotateHarness(AutoRotateHarness):
    def __init__(self):
        super().__init__(off=True, settings=False)

    def appear_then_click(self, _rule, interval=0):
        return True


class AutoRotateStateTest(unittest.TestCase):
    def test_current_skin_falls_back_after_settings_confirmation(self):
        harness = AutoRotateHarness(settings=True)

        self.assertTrue(BaseExploration._ensure_auto_rotate_on(harness, timeout=0.1))

    def test_legacy_on_template_is_still_used(self):
        harness = AutoRotateHarness(on=True, settings=False)

        self.assertTrue(BaseExploration._ensure_auto_rotate_on(harness, timeout=0.1))

    def test_persistent_off_state_stops_at_action_budget(self):
        harness = StuckAutoRotateHarness()

        with self.assertRaises(GameStuckError) as raised:
            BaseExploration._ensure_auto_rotate_on(harness, timeout=30)

        message = str(raised.exception)
        self.assertIn('operation=ensure_auto_rotate', message)
        self.assertIn('reason=action_budget_exhausted', message)
        self.assertIn('actions=3', message)


if __name__ == '__main__':
    unittest.main()
