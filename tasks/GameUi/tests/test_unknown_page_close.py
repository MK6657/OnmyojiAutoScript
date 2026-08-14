import unittest

from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
from tasks.Exploration.assets import ExplorationAssets
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.game_ui import GameUi


class UnknownPageCloseHarness:
    try_close_unknown_page = GameUi.try_close_unknown_page
    ui_close = GameUi.ui_close
    ui_current = None

    def __init__(self, close_target=ActivityShikigamiAssets.I_CONFIRM_SKIP):
        self.seen = []
        self.close_target = close_target

    def maybe_screenshot(self, _skip):
        return None

    def appear_then_click(self, target, interval=None):
        self.seen.append((target, interval))
        return target is self.close_target


class UnknownPageCloseTest(unittest.TestCase):
    def test_confirm_skip_modal_is_closed_before_top_right_skip(self):
        harness = UnknownPageCloseHarness()

        self.assertTrue(harness.try_close_unknown_page(skip_screenshot=False))
        seen_targets = [target for target, _interval in harness.seen]
        self.assertIs(seen_targets[-1], ActivityShikigamiAssets.I_CONFIRM_SKIP)
        self.assertNotIn(ActivityShikigamiAssets.I_SKIP_BUTTON, seen_targets)

        close_names = [target.name for target in harness.ui_close]
        self.assertLess(
            close_names.index(ActivityShikigamiAssets.I_CONFIRM_SKIP.name),
            close_names.index(ActivityShikigamiAssets.I_SKIP_BUTTON.name),
        )

    def test_exploration_exit_modal_is_closed_before_back_button(self):
        harness = UnknownPageCloseHarness(ExplorationAssets.O_E_EXIT_CONFIRM_TEXT)

        self.assertTrue(harness.try_close_unknown_page(skip_screenshot=False))
        seen_targets = [target for target, _interval in harness.seen]
        self.assertIs(seen_targets[-1], ExplorationAssets.O_E_EXIT_CONFIRM_TEXT)
        self.assertNotIn(GameUiAssets.I_MAIN_PROTECTION_BACK, seen_targets)
        self.assertNotIn(GameUi.I_UI_BACK_YELLOW, seen_targets)

        close_names = [target.name for target in harness.ui_close]
        self.assertLess(
            close_names.index(ExplorationAssets.O_E_EXIT_CONFIRM_TEXT.name),
            close_names.index(GameUi.I_UI_BACK_YELLOW.name),
        )


if __name__ == '__main__':
    unittest.main()
