import unittest

from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralBattle.preset_name_selector import InvalidPresetConfigError
from tasks.Component.SwitchSoul.assets import SwitchSoulAssets


class RecordsEntryHarness:
    _open_records_preset_page = GeneralBattle._open_records_preset_page
    preapply_preset_team_from_records = GeneralBattle.preapply_preset_team_from_records

    def __init__(self, opens=True):
        self.opens = opens
        self.opened = False
        self.clicks = []
        self.switches = []

    def screenshot(self):
        return None

    def _is_current_preset_page(self):
        return self.opened

    def appear_then_click(self, target, **_kwargs):
        self.clicks.append(target)
        if self.opens and target is SwitchSoulAssets.I_SOUL_PRESET:
            self.opened = True
            return True
        return False

    def _switch_preset_team_by_name(
        self,
        group_name,
        team_name,
        page_already_open=False,
    ):
        self.switches.append((group_name, team_name, page_already_open))
        return True


class PresetRecordsEntryTest(unittest.TestCase):
    def test_records_entry_opens_current_preset_page(self):
        harness = RecordsEntryHarness()

        GeneralBattle._open_records_preset_page(harness, timeout=0.7)

        self.assertTrue(harness.opened)
        self.assertEqual(harness.clicks, [SwitchSoulAssets.I_SOUL_PRESET])

    def test_preapply_sets_task_reuse_flag_only_after_success(self):
        harness = RecordsEntryHarness()

        result = GeneralBattle.preapply_preset_team_from_records(
            harness,
            '日常',
            '结界突破',
        )

        self.assertTrue(result)
        self.assertTrue(harness._battle_preset_preapplied)
        self.assertEqual(harness.switches, [('日常', '结界突破', True)])

    def test_preapply_reuses_page_already_verified_by_caller(self):
        harness = RecordsEntryHarness(opens=False)
        harness.opened = True

        result = GeneralBattle.preapply_preset_team_from_records(
            harness,
            '日常',
            '结界突破',
            page_already_open=True,
        )

        self.assertTrue(result)
        self.assertEqual(harness.clicks, [])
        self.assertEqual(harness.switches, [('日常', '结界突破', True)])

    def test_preapply_rejects_incomplete_names_before_clicking(self):
        harness = RecordsEntryHarness()

        with self.assertRaisesRegex(InvalidPresetConfigError, '必须同时填写'):
            GeneralBattle.preapply_preset_team_from_records(
                harness,
                '日常',
                '',
            )

        self.assertEqual(harness.clicks, [])


if __name__ == '__main__':
    unittest.main()
