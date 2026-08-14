import unittest

from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.GameUi.page import page_battle


class BattlePageRegistrationTest(unittest.TestCase):
    def test_battle_page_has_runtime_and_result_markers(self):
        checks = page_battle.check_button

        self.assertIn(GeneralBattleAssets.I_BATTLE_INFO, checks)
        self.assertIn(GeneralBattleAssets.I_FRIENDS, checks)
        self.assertIn(GeneralBattleAssets.O_BATTLE_RESULT_CONTINUE, checks)

    def test_battle_page_has_no_generic_automatic_action(self):
        self.assertIsNone(page_battle.additional)
        self.assertEqual(page_battle.links, {})


if __name__ == '__main__':
    unittest.main()
