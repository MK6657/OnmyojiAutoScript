import unittest

import numpy as np

from tasks.Component.GeneralBattle.preset_name_selector import (
    PresetNameDuplicateError,
    PresetNameNotFoundError,
    boxed_results_to_lines,
    forget_preset_validation,
    merge_ordered_pages,
    normalize_preset_name,
    preset_validation_is_recent,
    remember_preset_validation,
    require_unique_name,
)


class FakeOcrResult:
    def __init__(self, text, left, top, right, bottom):
        self.ocr_text = text
        self.box = np.array(
            [[left, top], [right, top], [right, bottom], [left, bottom]],
            dtype=np.int32,
        )


class PresetNameSelectorTest(unittest.TestCase):
    def test_normalize_keeps_exact_name_but_ignores_width_and_whitespace(self):
        self.assertEqual(normalize_preset_name(' 队 伍Ａ '), normalize_preset_name('队伍A'))

    def test_merge_overlapping_pages(self):
        merged = merge_ordered_pages(
            ['队伍1', '队伍2', '队伍3'],
            ['队伍2', '队伍3', '队伍4'],
        )
        self.assertEqual(merged, ['队伍1', '队伍2', '队伍3', '队伍4'])

    def test_merge_preserves_real_adjacent_duplicate(self):
        merged = merge_ordered_pages(
            ['队伍1', '队伍2', '队伍2', '队伍3'],
            ['队伍2', '队伍3', '队伍4'],
        )
        self.assertEqual(merged, ['队伍1', '队伍2', '队伍2', '队伍3', '队伍4'])

    def test_merge_tolerates_one_ocr_variant_in_page_overlap(self):
        merged = merge_ordered_pages(
            ['御魂', '逢魔', '秘闻', '日常', '活动', '挂机', '侵尸寮', '契灵'],
            ['逢魔', '秘闻', '日常', '活动', '挂机', '僵尸寮', '契灵', '地域鬼王'],
        )
        self.assertEqual(
            merged,
            ['御魂', '逢魔', '秘闻', '日常', '活动', '挂机', '侵尸寮', '契灵', '地域鬼王'],
        )

    def test_unique_name_rejects_duplicate_team(self):
        with self.assertRaisesRegex(PresetNameDuplicateError, '请在游戏内重命名'):
            require_unique_name(['队伍1', '队伍2', '队伍2'], '队伍2', '预设队伍')

    def test_unique_name_rejects_missing_team(self):
        with self.assertRaisesRegex(PresetNameNotFoundError, '没有识别到'):
            require_unique_name(['队伍1'], '队伍2', '预设队伍')

    def test_ocr_fragments_on_same_row_are_joined(self):
        results = [
            FakeOcrResult('不相狐禅', 0, 5, 70, 25),
            FakeOcrResult('(25秒)', 75, 7, 130, 26),
            FakeOcrResult('队伍2', 0, 100, 60, 122),
        ]
        lines = boxed_results_to_lines(results)
        self.assertEqual([line.text for line in lines], ['不相狐禅(25秒)', '队伍2'])

    def test_team_title_filter_drops_empty_team_hint_and_plus_icon(self):
        results = [
            FakeOcrResult('队伍2', 4, 20, 60, 42),
            FakeOcrResult('请点击左侧式神头像', 76, 75, 270, 96),
            FakeOcrResult('+', 132, 120, 173, 150),
        ]
        lines = boxed_results_to_lines(results, max_left=35)
        self.assertEqual([line.text for line in lines], ['队伍2'])

    def test_recent_validation_cache_expires_without_sliding(self):
        account, group, team = 'cache-test', 'daily', 'realm-raid'
        forget_preset_validation(account, group, team)
        remember_preset_validation(account, group, team, now=100)

        self.assertTrue(
            preset_validation_is_recent(account, group, team, now=399)
        )
        self.assertFalse(
            preset_validation_is_recent(account, group, team, now=401)
        )

    def test_recent_validation_cache_is_account_scoped(self):
        remember_preset_validation('account-a', 'daily', 'realm-raid', now=100)

        self.assertTrue(
            preset_validation_is_recent('account-a', 'daily', 'realm-raid', now=101)
        )
        self.assertFalse(
            preset_validation_is_recent('account-b', 'daily', 'realm-raid', now=101)
        )


if __name__ == '__main__':
    unittest.main()
