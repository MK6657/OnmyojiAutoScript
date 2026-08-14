import unittest
from types import SimpleNamespace

from tasks.Component.GeneralBattle.battle_outcome import BattleOutcome
from tasks.Component.GeneralBattle.general_battle import GeneralBattle


class RunBattleHarness:
    run_general_battle = GeneralBattle.run_general_battle

    def __init__(self, *, auto_confirmed: bool, wait_result: bool, green_result=None):
        self.current_count = 0
        self.auto_confirmed = auto_confirmed
        self.wait_result = wait_result
        self.wait_calls = 0
        self.green_calls = 0
        self.green_result = green_result
        self._battle_before_result_transition = False

    def _dismiss_battle_result_continue(self, **_kwargs):
        return False

    def battle_before(self, _buff, _config):
        return True

    def _ensure_auto_battle_mode(self):
        return self.auto_confirmed

    def is_in_real_battle(self, _screenshot):
        return True

    def green_mark(self, _enabled, _target):
        self.green_calls += 1
        return self.green_result

    def battle_wait(self, _random_click):
        self.wait_calls += 1
        return self.wait_result


class BattleOutcomeTest(unittest.TestCase):
    @staticmethod
    def config():
        return SimpleNamespace(
            green_enable=False,
            green_mark="left1",
            random_click_swipt_enable=False,
        )

    def test_auto_mode_unknown_does_not_abandon_active_battle(self):
        harness = RunBattleHarness(auto_confirmed=False, wait_result=True)

        self.assertTrue(harness.run_general_battle(self.config()))

        self.assertEqual(harness.wait_calls, 1)
        self.assertEqual(harness.green_calls, 0)
        self.assertEqual(harness.last_battle_result.outcome, BattleOutcome.VICTORY)
        self.assertIn("auto mode", harness.last_battle_result.reason)

    def test_defeat_has_distinct_structured_outcome(self):
        harness = RunBattleHarness(auto_confirmed=True, wait_result=False)

        self.assertFalse(harness.run_general_battle(self.config()))

        self.assertEqual(harness.last_battle_result.outcome, BattleOutcome.DEFEAT)
        self.assertFalse(harness.last_battle_result.success)

    def test_fast_victory_keeps_terminal_green_status_separate_from_battle_success(self):
        green_result = SimpleNamespace(status='terminal')
        harness = RunBattleHarness(
            auto_confirmed=True,
            wait_result=True,
            green_result=green_result,
        )
        config = self.config()
        config.green_enable = True

        self.assertTrue(harness.run_general_battle(config))

        self.assertEqual(harness.green_calls, 1)
        self.assertEqual(harness.wait_calls, 1)
        self.assertEqual(harness.last_battle_result.outcome, BattleOutcome.VICTORY)
        self.assertEqual(
            harness.last_battle_result.statistics['green_mark_status'],
            'terminal',
        )


if __name__ == "__main__":
    unittest.main()
