import unittest

from tasks.Component.GeneralBattle.general_battle import GeneralBattle


class EntryProbe(RuntimeError):
    pass


class NamedSoulPresetEntryHarness:
    _switch_preset_soul_by_name = GeneralBattle._switch_preset_soul_by_name

    def __init__(self):
        self.calls = []

    def _open_records_preset_page(self):
        self.calls.append('records')
        raise EntryProbe('records entry selected')

    def _open_current_preset_page(self):
        self.calls.append('battle_prepare')
        raise AssertionError('named soul preset must not use battle preparation entry')

    def _scan_preset_names(self, *_args, **_kwargs):
        raise EntryProbe('navigation skipped')


class NamedSoulPresetEntryTest(unittest.TestCase):
    def test_named_soul_preset_uses_records_entry(self):
        harness = NamedSoulPresetEntryHarness()

        with self.assertRaises(EntryProbe):
            harness._switch_preset_soul_by_name('日常', '困28')

        self.assertEqual(harness.calls, ['records'])

    def test_already_open_preset_page_skips_navigation(self):
        harness = NamedSoulPresetEntryHarness()

        with self.assertRaises(EntryProbe):
            harness._switch_preset_soul_by_name('日常', '困28', page_already_open=True)

        self.assertEqual(harness.calls, [])


if __name__ == '__main__':
    unittest.main()
