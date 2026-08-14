import unittest

import numpy as np

from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralBattle.preset_name_selector import OcrNameLine
from tasks.Component.SwitchSoul.assets import SwitchSoulAssets


class PresetPageDetectionHarness:
    _is_current_preset_page = GeneralBattle._is_current_preset_page
    _preset_page_names = staticmethod(GeneralBattle._preset_page_names)

    def __init__(
        self,
        template_match=False,
        layout_visible=True,
        group_lines=None,
        team_lines=None,
    ):
        self.template_match = template_match
        self.layout_visible = layout_visible
        self.group_lines = group_lines or []
        self.team_lines = team_lines or []
        self.ocr_calls = 0

    def appear(self, _asset):
        return self.template_match

    def _preset_group_panel_layout_visible(self):
        return self.layout_visible

    def _preset_ocr_lines(self, rule):
        self.ocr_calls += 1
        if rule is SwitchSoulAssets.O_SS_TEAM_NAME:
            return self.team_lines
        return self.group_lines


def line(text, center_y):
    return OcrNameLine(text=text, center_x=20, center_y=center_y)


class PresetLayoutHarness:
    _preset_group_panel_layout_visible = GeneralBattle._preset_group_panel_layout_visible
    PRESET_GROUP_PANEL_ROI = (0, 0, 10, 10)
    PRESET_GROUP_PANEL_BRIGHT_THRESHOLD = 160
    PRESET_GROUP_PANEL_MIN_BRIGHT_RATIO = 0.65

    def __init__(self, bright_pixels):
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        image.reshape(-1, 3)[:bright_pixels] = 200
        self.device = type('Device', (), {'image': image})()


class PresetPageDetectionTest(unittest.TestCase):
    def test_light_group_panel_layout_threshold(self):
        self.assertTrue(PresetLayoutHarness(65)._preset_group_panel_layout_visible())
        self.assertFalse(PresetLayoutHarness(64)._preset_group_panel_layout_visible())

    def test_search_icon_alone_is_not_a_preset_page(self):
        harness = PresetPageDetectionHarness(
            template_match=True,
            layout_visible=False,
        )

        self.assertFalse(harness._is_current_preset_page())
        self.assertEqual(harness.ocr_calls, 0)

    def test_group_list_structure_recognizes_current_page(self):
        harness = PresetPageDetectionHarness(
            group_lines=[line('御魂', 33), line('逢魔', 102), line('日常', 171)],
            team_lines=[line('结界突破', 40)],
        )

        self.assertTrue(harness._is_current_preset_page())
        self.assertEqual(harness.ocr_calls, 2)

    def test_courtyard_side_menu_is_not_a_preset_page(self):
        harness = PresetPageDetectionHarness(
            layout_visible=False,
            group_lines=[line('召唤', 33), line('活动', 102), line('福利', 171)],
            team_lines=[],
        )

        self.assertFalse(harness._is_current_preset_page())
        self.assertEqual(harness.ocr_calls, 0)

    def test_realm_raid_text_in_both_rois_is_rejected_by_layout(self):
        harness = PresetPageDetectionHarness(
            layout_visible=False,
            group_lines=[line('阵容', 33), line('助手', 102), line('个人', 171)],
            team_lines=[line('玩家甲', 40), line('玩家乙', 160)],
        )

        self.assertFalse(harness._is_current_preset_page())
        self.assertEqual(harness.ocr_calls, 0)

    def test_two_group_lines_are_not_enough(self):
        harness = PresetPageDetectionHarness(
            group_lines=[line('御魂', 33), line('日常', 102)],
            team_lines=[line('结界突破', 40)],
        )

        self.assertFalse(harness._is_current_preset_page())

    def test_irregular_text_does_not_look_like_group_list(self):
        harness = PresetPageDetectionHarness(
            group_lines=[line('文本一', 10), line('文本二', 25), line('文本三', 190)],
            team_lines=[line('结界突破', 40)],
        )

        self.assertFalse(harness._is_current_preset_page())


if __name__ == '__main__':
    unittest.main()
