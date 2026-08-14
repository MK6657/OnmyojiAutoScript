import unittest

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main


class PageCacheInvalidationTest(unittest.TestCase):
    def test_page_state_change_invalidates_device_recognition_cache(self):
        class Device:
            def __init__(self):
                self.reasons = []

            def invalidate_recognition_cache(self, reason):
                self.reasons.append(reason)

        game = object.__new__(GameUi)
        game._ui_current = None
        game.device = Device()

        GameUi.ui_current.fset(game, 'page_main')

        self.assertEqual(game.device.reasons, ['page_state_changed'])
        self.assertEqual(game.ui_current, 'page_main')

    def test_first_real_page_state_does_not_compare_against_none(self):
        class Device:
            def __init__(self):
                self.reasons = []

            def invalidate_recognition_cache(self, reason):
                self.reasons.append(reason)

        game = object.__new__(GameUi)
        game._ui_current = None
        game.device = Device()

        GameUi.ui_current.fset(game, page_main)

        self.assertIs(game.ui_current, page_main)
        self.assertEqual(game.device.reasons, ['page_state_changed'])


if __name__ == '__main__':
    unittest.main()
