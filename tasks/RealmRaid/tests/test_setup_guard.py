import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from module.exception import TaskEnd
from tasks.GameUi.page import page_main, page_realm_raid
from tasks.RealmRaid.script_task import ScriptTask


class LockGuardHarness:
    I_BACK_RED = object()
    I_CHECK_EXPLORATION = object()
    I_CHECK_REALM_RAID = object()
    I_FROG_RAID = object()
    _realm_raid_startup_scene_guard = ScriptTask._realm_raid_startup_scene_guard
    _confirm_realm_raid_board = ScriptTask._confirm_realm_raid_board
    _realm_raid_page_name = staticmethod(ScriptTask._realm_raid_page_name)
    _stop_realm_raid_for_scene = ScriptTask._stop_realm_raid_for_scene

    run_2 = ScriptTask.run_2
    finish_level_mode = ScriptTask.finish_level_mode
    finish_realm_raid_retry = ScriptTask.finish_realm_raid_retry

    def __init__(self, level_mode_enabled):
        self.config = SimpleNamespace(
            realm_raid=SimpleNamespace(
                switch_soul_config=SimpleNamespace(
                    enable=False,
                    enable_switch_by_name=False,
                ),
                general_battle_config=SimpleNamespace(
                    preset_enable=False,
                    preset_group_name='',
                    preset_team_name='',
                    lock_team_enable=True,
                ),
                level_mode_config=SimpleNamespace(enable=level_mode_enabled),
            )
        )
        self.navigation = []
        self.schedules = []
        self.retry_at = None
        self.lock_timeouts = []
        self.current_page = page_main

    def screenshot(self):
        return None

    def appear(self, _target, **_kwargs):
        if _target is self.I_CHECK_REALM_RAID:
            return True
        return False

    def ensure_lock(self, *_args, **kwargs):
        self.lock_timeouts.append(kwargs.get('timeout'))
        return False

    def level_short_retry_target(self):
        return self.retry_at

    def ui_get_current_page(self):
        self.navigation.append('current')
        return self.current_page

    def ui_goto(self, page):
        self.navigation.append(page)
        self.current_page = page
        return True

    def ui_click(self, *_args):
        self.navigation.append('back')

    def set_next_run(self, **kwargs):
        self.schedules.append(kwargs)


class SetupGuardTest(unittest.TestCase):
    def test_normal_mode_lock_timeout_schedules_short_retry(self):
        harness = LockGuardHarness(level_mode_enabled=False)
        retry_at = datetime.now() + timedelta(minutes=5)
        harness.retry_at = retry_at

        with self.assertRaises(TaskEnd):
            harness.run_2()

        self.assertEqual(len(harness.schedules), 1)
        schedule = harness.schedules[0]
        self.assertFalse(schedule['success'])
        self.assertFalse(schedule['server'])
        self.assertEqual(schedule['target'], retry_at)
        self.assertEqual(harness.lock_timeouts, [12])

    def test_target_level_lock_timeout_uses_checkpoint_safe_exit(self):
        harness = LockGuardHarness(level_mode_enabled=True)
        retry_at = datetime.now() + timedelta(minutes=5)
        harness.retry_at = retry_at

        with self.assertRaises(TaskEnd):
            harness.run_2()

        self.assertEqual(len(harness.schedules), 1)
        schedule = harness.schedules[0]
        self.assertEqual(schedule['task'], 'RealmRaid')
        self.assertFalse(schedule['success'])
        self.assertFalse(schedule['server'])
        self.assertEqual(schedule['target'], retry_at)
        self.assertEqual(harness.lock_timeouts, [5])


if __name__ == '__main__':
    unittest.main()
