import unittest
from unittest.mock import patch

from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralBattle.preset_name_selector import OcrNameLine


class ScanHarness:
    _preset_page_names = staticmethod(GeneralBattle._preset_page_names)
    _preset_swipe_to_top = GeneralBattle._preset_swipe_to_top
    _scan_preset_names = GeneralBattle._scan_preset_names

    def __init__(self, pages, start_index=0):
        self.pages = pages
        self.index = start_index
        self.swipes = []

    def screenshot(self):
        return None

    def _preset_ocr_lines(self, _rule):
        return [
            OcrNameLine(text=name, center_x=20, center_y=20 + row * 50)
            for row, name in enumerate(self.pages[self.index])
        ]

    def swipe(self, rule):
        self.swipes.append(rule)
        if rule == 'to_top':
            self.index = max(0, self.index - 1)
        elif rule == 'forward':
            self.index = min(len(self.pages) - 1, self.index + 1)


class PresetScanFlowTest(unittest.TestCase):
    @patch('tasks.Component.GeneralBattle.general_battle.sleep', return_value=None)
    def test_scan_returns_to_top_and_preserves_duplicate_across_pages(self, _sleep):
        harness = ScanHarness(
            pages=[
                ['队伍1', '队伍2'],
                ['队伍2', '队伍2', '队伍3'],
                ['队伍3', '队伍4'],
            ],
            start_index=2,
        )

        names = harness._scan_preset_names(
            ocr_rule=object(),
            to_top_swipe='to_top',
            forward_swipe='forward',
            kind='预设队伍',
            max_swipes=10,
        )

        self.assertEqual(names, ['队伍1', '队伍2', '队伍2', '队伍3', '队伍4'])
        self.assertEqual(harness.index, 2)
        self.assertIn('to_top', harness.swipes)
        self.assertIn('forward', harness.swipes)


if __name__ == '__main__':
    unittest.main()

