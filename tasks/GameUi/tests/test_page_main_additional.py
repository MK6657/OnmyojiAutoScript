import unittest
from types import SimpleNamespace

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.Restart.assets import RestartAssets


class PageMainAdditionalHarness:
    run_additional = GameUi.run_additional

    def __init__(self, condition_visible):
        self.condition_visible = condition_visible
        self.operated = []

    def maybe_screenshot(self, _skip_first_screenshot):
        return None

    def appear(self, target):
        return target is RestartAssets.I_LOGIN_SCROOLL_CLOSE and self.condition_visible

    def appear_then_operate(self, target, **_kwargs):
        self.operated.append(target)
        return True


class PageMainAdditionalTest(unittest.TestCase):
    def test_scroll_close_is_guarded_by_scroll_close_marker(self):
        entry = next(
            item
            for item in page_main.additional
            if isinstance(item, list) and len(item) == 2
        )
        self.assertIs(entry[0], RestartAssets.I_LOGIN_SCROOLL_CLOSE)
        self.assertIs(entry[1], RestartAssets.C_LOGIN_SCROLL_CLOSE_AREA)

    def test_hidden_toolbar_does_not_click_scroll_close_coordinate(self):
        harness = PageMainAdditionalHarness(condition_visible=False)
        harness.run_additional(SimpleNamespace(additional=[
            [RestartAssets.I_LOGIN_SCROOLL_CLOSE, RestartAssets.C_LOGIN_SCROLL_CLOSE_AREA]
        ]), skip_first_screenshot=False)
        self.assertEqual(harness.operated, [])

    def test_visible_scroll_marker_allows_one_close_action(self):
        harness = PageMainAdditionalHarness(condition_visible=True)
        harness.run_additional(SimpleNamespace(additional=[
            [RestartAssets.I_LOGIN_SCROOLL_CLOSE, RestartAssets.C_LOGIN_SCROLL_CLOSE_AREA]
        ]), skip_first_screenshot=False)
        self.assertEqual(harness.operated, [RestartAssets.C_LOGIN_SCROLL_CLOSE_AREA])


if __name__ == '__main__':
    unittest.main()
