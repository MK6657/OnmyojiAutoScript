import unittest
from types import SimpleNamespace

from tasks.Exploration.base import BaseExploration


class FireHarness:
    I_E_SETTINGS_BUTTON = object()
    I_E_AUTO_ROTATE_ON = object()
    I_E_AUTO_ROTATE_OFF = object()

    def __init__(self, battle_success):
        self.minions_cnt = 0
        self.battle_success = battle_success
        self._config = SimpleNamespace(general_battle_config=object())

    def ui_click_until_disappear(self, _button, **_kwargs):
        return True

    def screenshot(self):
        return None

    def appear(self, _rule, **_kwargs):
        return False

    def run_general_battle(self, _config):
        return self.battle_success


class FireTimeoutHarness(FireHarness):
    def ui_click_until_disappear(self, _button, **_kwargs):
        return False


class FireCountTest(unittest.TestCase):
    def test_successful_battle_increments_count(self):
        harness = FireHarness(battle_success=True)

        self.assertTrue(BaseExploration.fire(harness, object()))
        self.assertEqual(harness.minions_cnt, 1)

    def test_failed_battle_does_not_increment_count(self):
        harness = FireHarness(battle_success=False)

        self.assertFalse(BaseExploration.fire(harness, object()))
        self.assertEqual(harness.minions_cnt, 0)

    def test_button_timeout_does_not_enter_battle(self):
        harness = FireTimeoutHarness(battle_success=True)

        self.assertFalse(BaseExploration.fire(harness, object()))
        self.assertEqual(harness.minions_cnt, 0)


if __name__ == '__main__':
    unittest.main()
