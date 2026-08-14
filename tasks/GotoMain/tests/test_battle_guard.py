import unittest

from module.exception import TaskEnd
from tasks.GameUi.page import page_battle, page_main
from tasks.GotoMain.script_task import ScriptTask


class GotoMainHarness:
    run = ScriptTask.run

    def __init__(self, current_page):
        self.current_page = current_page
        self.calls = []

    def ui_get_current_page(self):
        self.calls.append(('current_page',))
        return self.current_page

    def ui_goto(self, page):
        self.calls.append(('goto', page))


class GotoMainBattleGuardTest(unittest.TestCase):
    def test_active_battle_page_is_left_untouched(self):
        harness = GotoMainHarness(page_battle)

        with self.assertRaises(TaskEnd) as raised:
            harness.run()

        self.assertEqual(harness.calls, [('current_page',)])
        self.assertEqual(raised.exception.outcome, 'active_unconfirmed')
        self.assertFalse(raised.exception.success)

    def test_non_battle_page_still_navigates_to_main(self):
        harness = GotoMainHarness(page_main)

        with self.assertRaises(TaskEnd) as raised:
            harness.run()

        self.assertEqual(harness.calls, [('current_page',), ('goto', page_main)])
        self.assertEqual(raised.exception.outcome, 'returned')
        self.assertTrue(raised.exception.success)


if __name__ == '__main__':
    unittest.main()
