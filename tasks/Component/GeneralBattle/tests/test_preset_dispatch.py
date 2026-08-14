import unittest

from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralBattle.preset_name_selector import InvalidPresetConfigError


class DispatchHarness:
    def __init__(self):
        self.calls = []

    def _switch_preset_team_by_name(self, group_name, team_name):
        self.calls.append(('name', group_name, team_name))
        return True

    def _switch_preset_team_legacy(self, group, team):
        self.calls.append(('legacy', group, team))
        return True


class PresetDispatchTest(unittest.TestCase):
    def test_disabled_preset_does_nothing(self):
        harness = DispatchHarness()
        result = GeneralBattle.switch_preset_team(harness, enable=False)
        self.assertIsNone(result)
        self.assertEqual(harness.calls, [])

    def test_both_names_use_current_selector(self):
        harness = DispatchHarness()
        result = GeneralBattle.switch_preset_team(
            harness,
            enable=True,
            preset_group_name='活动',
            preset_team_name='卡级队伍',
        )
        self.assertTrue(result)
        self.assertEqual(harness.calls, [('name', '活动', '卡级队伍')])

    def test_one_missing_name_stops_before_legacy_fallback(self):
        harness = DispatchHarness()
        with self.assertRaisesRegex(InvalidPresetConfigError, '必须同时填写'):
            GeneralBattle.switch_preset_team(
                harness,
                enable=True,
                preset_group_name='活动',
                preset_team_name='',
            )
        self.assertEqual(harness.calls, [])

    def test_empty_names_keep_legacy_configs_working(self):
        harness = DispatchHarness()
        result = GeneralBattle.switch_preset_team(
            harness,
            enable=True,
            preset_group=3,
            preset_team=2,
        )
        self.assertTrue(result)
        self.assertEqual(harness.calls, [('legacy', 3, 2)])


if __name__ == '__main__':
    unittest.main()
