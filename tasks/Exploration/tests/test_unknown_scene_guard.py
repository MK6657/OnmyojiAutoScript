import unittest
from unittest.mock import patch

from module.exception import GamePageUnknownError, GameStuckError
from tasks.Exploration.base import BaseExploration, Scene
from tasks.Exploration.solo import ScriptTask


class UnknownSceneHarness:
    _handle_unknown_scene = BaseExploration._handle_unknown_scene
    _abort_unknown_scene = BaseExploration._abort_unknown_scene
    UNKNOWN_SCENE_LIMIT = 2
    UNKNOWN_SCENE_RETRY_DELAY = 0

    def __init__(self):
        self.clicks = []

    def _click_exploration_exit_confirmation(self):
        return False

    def _home_scene_visible(self):
        return False

    def click(self, *args, **kwargs):
        self.clicks.append((args, kwargs))


class StartupSceneHarness:
    _prepare_startup = ScriptTask._prepare_startup
    UNKNOWN_SCENE_LIMIT = 2
    UNKNOWN_SCENE_RETRY_DELAY = 0

    def __init__(self, home_visible, candidate_visible=False):
        self.home_visible = home_visible
        self.candidate_visible = candidate_visible
        self.pre_process_calls = 0
        self.candidate_confirm_calls = 0
        self.clicks = []

    def screenshot(self):
        return None

    def _click_exploration_exit_confirmation(self):
        return False

    def get_current_scene(self):
        return Scene.UNKNOWN

    def _home_scene_visible(self):
        return self.home_visible

    def _candidate_panel_visible(self):
        return self.candidate_visible

    def _confirm_candidate_panel(self):
        self.candidate_confirm_calls += 1
        self.candidate_visible = False
        self.home_visible = True
        return True

    def pre_process(self):
        self.pre_process_calls += 1

    def click(self, *args, **kwargs):
        self.clicks.append((args, kwargs))

    def _abort_unknown_scene(self, context, attempts):
        return BaseExploration._abort_unknown_scene(self, context, attempts)


class PersistentCandidateHarness(StartupSceneHarness):
    def __init__(self):
        super().__init__(home_visible=False, candidate_visible=True)

    def _confirm_candidate_panel(self):
        self.candidate_confirm_calls += 1
        return True


class UnknownSceneGuardTest(unittest.TestCase):
    def test_unknown_scene_waits_without_click_then_aborts(self):
        harness = UnknownSceneHarness()

        with patch('tasks.Exploration.base.time.sleep'):
            self.assertEqual(harness._handle_unknown_scene('test', 0), 1)
            with self.assertRaises(GamePageUnknownError):
                harness._handle_unknown_scene('test', 1)

        self.assertEqual(harness.clicks, [])

    def test_startup_home_routes_to_existing_pre_process_without_click(self):
        harness = StartupSceneHarness(home_visible=True)

        harness._prepare_startup()

        self.assertEqual(harness.pre_process_calls, 1)
        self.assertEqual(harness.clicks, [])

    def test_startup_unknown_aborts_without_click(self):
        harness = StartupSceneHarness(home_visible=False)

        with patch('tasks.Exploration.solo.sleep'):
            with self.assertRaises(GamePageUnknownError):
                harness._prepare_startup()

        self.assertEqual(harness.pre_process_calls, 0)
        self.assertEqual(harness.clicks, [])

    def test_startup_recovers_interrupted_candidate_panel_before_scene_detection(self):
        harness = StartupSceneHarness(home_visible=False, candidate_visible=True)

        harness._prepare_startup()

        self.assertEqual(harness.candidate_confirm_calls, 1)
        self.assertEqual(harness.pre_process_calls, 1)
        self.assertEqual(harness.clicks, [])

    def test_startup_candidate_panel_has_action_boundary(self):
        harness = PersistentCandidateHarness()

        with self.assertRaises(GameStuckError) as raised:
            harness._prepare_startup()

        self.assertIn('operation=prepare_startup', str(raised.exception))
        self.assertIn('reason=action_budget_exhausted', str(raised.exception))
        self.assertEqual(harness.candidate_confirm_calls, 4)


if __name__ == '__main__':
    unittest.main()
