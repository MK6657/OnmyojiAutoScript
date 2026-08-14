import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from module.exception import TaskEnd
from tasks.GameUi.page import page_battle, page_main, page_realm_raid
from tasks.RealmRaid.script_task import ScriptTask


class TicketRule:
    def ocr(self, _image):
        return 5, 0, 30


class SceneGuardHarness:
    _realm_raid_startup_scene_guard = ScriptTask._realm_raid_startup_scene_guard
    _confirm_realm_raid_board = ScriptTask._confirm_realm_raid_board
    _realm_raid_page_name = staticmethod(ScriptTask._realm_raid_page_name)
    _stop_realm_raid_for_scene = ScriptTask._stop_realm_raid_for_scene

    I_CHECK_REALM_RAID = object()
    O_NUMBER = TicketRule()

    def __init__(self, current_page):
        self.current_page = current_page
        self.calls = []
        self.dumps = []
        self.schedules = []
        self.device = SimpleNamespace(image=object())

    def ui_get_current_page(self):
        self.calls.append(('current_page',))
        return self.current_page

    def screenshot(self):
        self.calls.append(('screenshot',))

    def appear(self, target, **_kwargs):
        return target is self.I_CHECK_REALM_RAID

    def dump_board(self, label):
        self.dumps.append(label)

    def level_short_retry_target(self):
        return datetime.now() + timedelta(minutes=5)

    def set_next_run(self, **kwargs):
        self.schedules.append(kwargs)


class SceneGuardTest(unittest.TestCase):
    def test_active_battle_is_blocked_without_clicking_or_navigating(self):
        harness = SceneGuardHarness(page_battle)

        with self.assertRaises(TaskEnd):
            harness._realm_raid_startup_scene_guard()

        self.assertEqual(harness.schedules[0]['task'], 'RealmRaid')
        self.assertFalse(harness.schedules[0]['success'])
        self.assertEqual(harness.dumps, ['scene_guard_active_battle_page'])
        self.assertNotIn(('click',), harness.calls)
        self.assertEqual(
            [call for call in harness.calls if call[0] == 'current_page'],
            [('current_page',)],
        )

    def test_wrong_page_after_navigation_is_blocked(self):
        harness = SceneGuardHarness(page_main)
        config = SimpleNamespace(level_mode_config=SimpleNamespace(enable=True))

        with self.assertRaises(TaskEnd):
            harness._confirm_realm_raid_board(config)

        self.assertEqual(harness.dumps, ['scene_guard_expected_realm_raid_got_page_main'])
        self.assertFalse(harness.schedules[0]['success'])

    def test_realm_raid_board_marker_and_ticket_are_confirmed(self):
        harness = SceneGuardHarness(page_realm_raid)
        config = SimpleNamespace(level_mode_config=SimpleNamespace(enable=True))

        harness._confirm_realm_raid_board(config)

        self.assertEqual(harness.dumps, [])
        self.assertEqual(harness.schedules, [])


if __name__ == '__main__':
    unittest.main()
