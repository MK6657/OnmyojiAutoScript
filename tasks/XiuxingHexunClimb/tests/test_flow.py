import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tasks.XiuxingHexunClimb.assets import XiuxingHexunClimbAssets
from tasks.XiuxingHexunClimb.config import XiuxingHexunClimb
from tasks.XiuxingHexunClimb.script_task import ScriptTask
from tasks.XiuxingHexun.script_task import ScriptTask as XiuxingHexunScriptTask
from tasks.Component.GeneralBattle.battle_outcome import BattleOutcome


class _FinishSignal(Exception):
    pass


class _FlowHarness(ScriptTask):
    def __init__(self):
        self.config = SimpleNamespace(xiuxing_hexun_climb=XiuxingHexunClimb())
        self.events = []
        self.last_battle_result = None

    def screenshot(self):
        return None

    def is_in_real_battle(self, _screenshot=False):
        return False

    def _recover_existing_result(self):
        return False

    def _ensure_courtyard_or_activity(self):
        self.events.append("ensure_entry")

    def _enter_daily_training(self):
        self.events.append("enter_daily")

    def _wait_for(self, *_args, **_kwargs):
        return True

    def _read_ticket_count(self):
        return 882

    def _start_daily_challenge(self):
        self.events.append("challenge_click")

    def _prepare_daily_preset(self, _config):
        self.events.append("preset")

    def run_general_battle(self, config):
        self.events.append(("battle", config.preset_team_name))
        self.last_battle_result = SimpleNamespace(outcome=BattleOutcome.VICTORY)
        return True

    def _continue_to_daily(self):
        self.events.append("continue")

    def _finish(self, reason, *, challenges):
        self.events.append(("finish", reason, challenges))
        raise _FinishSignal


class XiuxingHexunClimbFlowTest(unittest.TestCase):
    def test_safe_default_and_named_preset(self):
        config = XiuxingHexunClimb()
        self.assertEqual(config.max_challenges, 1)
        self.assertEqual(XiuxingHexunClimb(max_challenges=800).max_challenges, 800)
        self.assertTrue(config.activity_enabled)
        self.assertEqual(config.general_battle_config.preset_group_name, "每月活动")
        self.assertEqual(config.general_battle_config.preset_team_name, "爬塔222")

    def test_ticket_parser_uses_explicit_digits(self):
        self.assertEqual(ScriptTask._parse_ticket_text("882"), 882)
        self.assertEqual(ScriptTask._parse_ticket_text("票 30"), 30)
        self.assertIsNone(ScriptTask._parse_ticket_text("O", source_text="O"))
        self.assertIsNone(ScriptTask._parse_ticket_text("0", source_text="O"))
        self.assertEqual(ScriptTask._parse_ticket_text("0", source_text="0"), 0)
        self.assertIsNone(ScriptTask._parse_ticket_text(""))

    def test_reviewed_coordinates_are_1280_layout_safe(self):
        entry = XiuxingHexunClimbAssets.C_DAILY_ENTRY.roi_front
        challenge = XiuxingHexunClimbAssets.C_DAILY_CHALLENGE.roi_front
        self.assertEqual(XiuxingHexunClimbAssets.C_DAILY_ENTRY.center, (197, 272))
        self.assertEqual(XiuxingHexunClimbAssets.C_DAILY_CHALLENGE.center, (1190, 620))
        self.assertLess(entry[0] + entry[2], 1280)
        self.assertLess(challenge[1] + challenge[3], 720)

    def test_task_id_is_temporary_name(self):
        self.assertEqual(ScriptTask.TASK_ID, "XiuxingHexunClimb")
        self.assertEqual(ScriptTask.TASK_PREFIX, "XIUXING_HEXUN_CLIMB")

    def test_daily_reward_title_is_a_continuation_guard(self):
        harness = ScriptTask.__new__(ScriptTask)
        harness._daily_reward_visible = lambda: True
        with patch.object(
            XiuxingHexunScriptTask,
            "_battle_result_continue_visible",
            return_value=False,
        ):
            self.assertTrue(harness._battle_result_continue_visible())

    def test_one_ticket_runs_one_challenge_and_stops(self):
        harness = _FlowHarness()
        with self.assertRaises(_FinishSignal):
            harness.run()
        self.assertEqual(harness.events, [
            "ensure_entry",
            "enter_daily",
            "preset",
            "challenge_click",
            ("battle", "爬塔222"),
            "continue",
            ("finish", "challenge limit reached", 1),
        ])


if __name__ == "__main__":
    unittest.main()
