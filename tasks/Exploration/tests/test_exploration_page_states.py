from tasks.Exploration.assets import ExplorationAssets
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.page import page_exploration


def test_exploration_page_accepts_collapsed_and_expanded_panel_states():
    checks = page_exploration.check_button

    assert isinstance(checks, list)
    assert checks == [
        GameUiAssets.I_CHECK_EXPLORATION,
        ExplorationAssets.I_EXP_ARROW_LEFT,
        ExplorationAssets.I_EXP_ARROW_RIGHT,
    ]
