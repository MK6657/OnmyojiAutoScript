import unittest
from datetime import datetime
from types import SimpleNamespace

from module.exception import GameTooManyClickError, TaskEnd
from tasks.GameUi.page import page_main
from tasks.RealmRaid.script_task import ScriptTask


class PresetEntryHarness:
    I_MAIN_GOTO_SHIKIGAMI_RECORDS = object()

    def __init__(self, current=False, records_entry=False):
        self.current = current
        self.records_entry = records_entry
        self.open_calls = []
        self.ui_calls = []
        self.main_clicks = 0

    def screenshot(self):
        return None

    def _is_current_preset_page(self):
        return self.current

    def appear(self, _target, **_kwargs):
        return self.records_entry

    def _open_records_preset_page(self, timeout=15):
        self.open_calls.append(timeout)
        self.current = True

    def ui_get_current_page(self):
        self.ui_calls.append('current')

    def ui_goto(self, page):
        self.ui_calls.append(page)

    def appear_then_click(self, _target, **_kwargs):
        self.main_clicks += 1
        return True


class PresetEntryTest(unittest.TestCase):
    def test_reuses_current_preset_page_without_navigation(self):
        harness = PresetEntryHarness(current=True)

        ScriptTask.open_current_team_preset(harness)

        self.assertEqual(harness.open_calls, [])
        self.assertEqual(harness.ui_calls, [])

    def test_opens_preset_directly_from_current_records_page(self):
        harness = PresetEntryHarness(records_entry=True)

        ScriptTask.open_current_team_preset(harness, timeout=9)

        self.assertEqual(harness.open_calls, [9])
        self.assertEqual(harness.ui_calls, [])

    def test_enters_records_from_courtyard_without_records_page_check(self):
        harness = PresetEntryHarness()

        ScriptTask.open_current_team_preset(harness, timeout=11)

        self.assertEqual(harness.ui_calls, ['current', page_main])
        self.assertEqual(harness.main_clicks, 1)
        self.assertEqual(harness.open_calls, [11])


class RunSafetyHarness:
    run = ScriptTask.run

    def __init__(self, level_mode_enabled=True):
        self.config = SimpleNamespace(
            realm_raid=SimpleNamespace(
                level_mode_config=SimpleNamespace(enable=level_mode_enabled)
            )
        )
        self.dumps = []
        self.schedules = []

    def run_2(self):
        raise GameTooManyClickError('preset page drift')

    def dump_board(self, label):
        self.dumps.append(label)

    def set_next_run(self, **kwargs):
        self.schedules.append(kwargs)


class TargetLevelRunSafetyTest(unittest.TestCase):
    def test_preset_stage_click_error_stops_without_global_restart(self):
        harness = RunSafetyHarness(level_mode_enabled=True)

        with self.assertRaises(TaskEnd):
            harness.run()

        self.assertEqual(harness.dumps, ['level_mode_task_error'])
        self.assertEqual(len(harness.schedules), 1)
        schedule = harness.schedules[0]
        self.assertEqual(schedule['task'], 'RealmRaid')
        self.assertFalse(schedule['success'])
        self.assertTrue(schedule['finish'])
        self.assertFalse(schedule['server'])
        self.assertGreaterEqual((schedule['target'] - datetime.now()).total_seconds(), 299)
        self.assertLessEqual((schedule['target'] - datetime.now()).total_seconds(), 301)

    def test_legacy_mode_still_delegates_error_to_global_handler(self):
        harness = RunSafetyHarness(level_mode_enabled=False)

        with self.assertRaises(GameTooManyClickError):
            harness.run()


if __name__ == '__main__':
    unittest.main()
