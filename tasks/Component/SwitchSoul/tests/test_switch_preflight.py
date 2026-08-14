import unittest

from tasks.Component.GeneralBattle.preset_name_selector import InvalidPresetConfigError
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul, switch_parser


class SwitchSoulHarness:
    run_switch_soul = SwitchSoul.run_switch_soul

    def __init__(self):
        self.calls = []

    def validate_switch_config(self, enabled, target):
        return SwitchSoul.validate_switch_config(enabled, target)

    def click_preset(self):
        self.calls.append('click_preset')

    def switch_souls(self, target):
        self.calls.append(('switch_souls', target))


class SwitchSoulOneHarness:
    switch_soul_one = SwitchSoul.switch_soul_one
    _validate_switch_pair = staticmethod(SwitchSoul._validate_switch_pair)


class SwitchSoulPreflightTest(unittest.TestCase):
    def test_disabled_default_is_allowed(self):
        self.assertIsNone(SwitchSoul.validate_switch_config(False, '-1,-1'))

    def test_enabled_default_is_rejected_before_click(self):
        harness = SwitchSoulHarness()

        with self.assertRaisesRegex(InvalidPresetConfigError, '-1,-1'):
            harness.run_switch_soul('-1,-1')

        self.assertEqual(harness.calls, [])

    def test_invalid_pair_is_rejected_before_group_navigation(self):
        with self.assertRaisesRegex(InvalidPresetConfigError, '-1,-1'):
            SwitchSoulOneHarness().switch_soul_one(-1, -1)

    def test_valid_pair_reaches_switch_action(self):
        harness = SwitchSoulHarness()

        harness.run_switch_soul('2,3')

        self.assertEqual(harness.calls, ['click_preset', ('switch_souls', (2, 3))])

    def test_parser_converts_whitespace_and_rejects_malformed_input(self):
        self.assertEqual(switch_parser(' 2, 3 '), (2, 3))
        with self.assertRaises(InvalidPresetConfigError):
            switch_parser('invalid')


if __name__ == '__main__':
    unittest.main()
