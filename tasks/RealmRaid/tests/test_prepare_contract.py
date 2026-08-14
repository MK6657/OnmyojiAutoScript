import unittest
from types import SimpleNamespace

from tasks.GameUi.page import page_realm_raid, page_shikigami_records
from tasks.Component.GeneralBattle.preset_name_selector import InvalidPresetConfigError
from tasks.RealmRaid.script_task import ScriptTask


class PrepareHarness:
    prepare_realm_raid_battle = ScriptTask.prepare_realm_raid_battle
    retry_lock_after_battle = ScriptTask.retry_lock_after_battle

    def __init__(self, unlock_result=True):
        self.unlock_result = unlock_result
        self.calls = []
        self._battle_preset_preapplied = False

    def ensure_lock(self, enabled, timeout=12):
        self.calls.append(('ensure_lock', enabled, timeout))
        if not enabled:
            return self.unlock_result
        return True

    def ui_get_current_page(self):
        self.calls.append(('current_page',))

    def ui_goto(self, page):
        self.calls.append(('goto', page))

    def open_current_team_preset(self):
        self.calls.append(('open_team_preset',))

    def preapply_preset_team_from_records(self, group, team, page_already_open=False):
        self.calls.append(('team_preset', group, team, page_already_open))
        self._battle_preset_preapplied = True
        return True

    def run_switch_soul_by_name(self, group, team):
        self.calls.append(('soul_preset', group, team))
        return True

    def run_switch_soul(self, target):
        self.calls.append(('soul_preset_index', target))


def realm_config(lock=True):
    return SimpleNamespace(
        general_battle_config=SimpleNamespace(
            preset_enable=True,
            preset_group_name='日常',
            preset_team_name='结界突破',
            lock_team_enable=lock,
        ),
        switch_soul_config=SimpleNamespace(
            enable=False,
            switch_group_team='-1,-1',
            enable_switch_by_name=True,
            group_name='日常',
            team_name='结界突破',
        ),
    )


class PrepareContractTest(unittest.TestCase):
    def test_combined_named_preparation_keeps_both_business_intents(self):
        harness = PrepareHarness()

        ScriptTask.prepare_realm_raid_battle(harness, realm_config(lock=False))

        self.assertEqual(
            [call[0] for call in harness.calls],
            ['open_team_preset', 'team_preset'],
        )
        self.assertTrue(harness._team_preset_covers_soul)

    def test_locked_team_defers_relock_until_after_first_battle(self):
        harness = PrepareHarness(unlock_result=True)

        ScriptTask.prepare_realm_raid_battle(harness, realm_config(lock=True))

        self.assertTrue(harness._lock_after_first_battle_pending)
        self.assertFalse(harness._battle_lock_expected_active)
        self.assertTrue(harness._team_preset_covers_soul)
        self.assertIn(('ensure_lock', False, 12), harness.calls)
        self.assertNotIn(('soul_preset', '日常', '结界突破'), harness.calls)

    def test_post_battle_lock_indicator_waits_for_next_battle_validation(self):
        harness = PrepareHarness()
        battle_config = SimpleNamespace(lock_team_enable=True)

        self.assertTrue(harness.retry_lock_after_battle(battle_config))
        self.assertTrue(harness._battle_lock_expected_active)
        self.assertIn(('ensure_lock', True, 5.0), harness.calls)

    def test_unlock_failure_skips_team_but_keeps_soul_fallback(self):
        harness = PrepareHarness(unlock_result=False)

        ScriptTask.prepare_realm_raid_battle(harness, realm_config(lock=True))

        self.assertIn(('goto', page_realm_raid), harness.calls)
        self.assertIn(('ensure_lock', False, 12), harness.calls)
        self.assertNotIn(('open_team_preset',), harness.calls)
        self.assertIn(('soul_preset', '日常', '结界突破'), harness.calls)

    def test_partial_team_names_are_rejected_before_navigation(self):
        harness = PrepareHarness()
        config = realm_config(lock=False)
        config.general_battle_config.preset_team_name = ''

        with self.assertRaises(InvalidPresetConfigError):
            ScriptTask.prepare_realm_raid_battle(harness, config)

        self.assertEqual(harness.calls, [])


if __name__ == '__main__':
    unittest.main()
