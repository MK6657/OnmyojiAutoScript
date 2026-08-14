import unittest

from tasks.GameUi.page import page_battle, page_main


class PageBattleRouteTest(unittest.TestCase):
    def test_battle_page_is_not_owned_by_generic_page_graph(self):
        self.assertNotIn(page_main, page_battle.links)

    def test_battle_page_has_no_generic_additional_action(self):
        self.assertIsNone(page_battle.additional)


if __name__ == '__main__':
    unittest.main()
