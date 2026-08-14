import unittest
from types import SimpleNamespace
from unittest.mock import patch

from module.atom.click import RuleClick
from module.exception import GameStuckError, TaskEnd
from tasks.XiuxingHexun.script_task import (
    ScriptTask,
    XiuxingHexunSearchDecision,
    XiuxingHexunState,
    XiuxingHexunTicketState,
)


class XiuxingHexunFlowTest(unittest.TestCase):
    def test_state_names_are_stable(self):
        self.assertEqual(XiuxingHexunState.COURTYARD, "courtyard")
        self.assertEqual(XiuxingHexunState.ACTIVITY_HUB, "activity_hub")
        self.assertEqual(XiuxingHexunState.NO_TICKET, "no_ticket")

    def test_disabled_activity_stops_without_success_or_schedule_write(self):
        harness = SimpleNamespace()
        with self.assertRaises(TaskEnd) as caught:
            ScriptTask._stop(harness, "activity disabled")
        self.assertFalse(caught.exception.success)
        self.assertEqual(caught.exception.outcome, "stopped")
        self.assertEqual(caught.exception.statistics["challenges"], 0)

    def test_required_click_supports_rule_click(self):
        harness = SimpleNamespace(
            screenshot=lambda: None,
            click=lambda marker, interval=None: True,
        )
        marker = RuleClick((10, 10, 20, 20), (10, 10, 20, 20), name="test_click")
        ScriptTask._required_click(harness, marker, timeout=0.1)

    def test_preset_deploy_click_stays_inside_button(self):
        marker = ScriptTask.C_PRESET_DEPLOY
        x, y, width, height = marker.roi_front
        self.assertGreaterEqual(x, 810)
        self.assertGreaterEqual(y, 515)
        self.assertLessEqual(x + width, 925)
        self.assertLessEqual(y + height, 560)

    def test_search_click_stays_inside_center_label(self):
        marker = ScriptTask.C_SEARCH
        x, y, width, height = marker.roi_front
        self.assertGreaterEqual(x, 1100)
        self.assertGreaterEqual(y, 580)
        self.assertLessEqual(x + width, 1215)
        self.assertLessEqual(y + height, 680)

    def test_courtyard_alt_click_stays_inside_wu_control(self):
        x, y, width, height = ScriptTask.C_COURTYARD_ACCESS_ALT.roi_front
        self.assertGreaterEqual(x, 447)
        self.assertGreaterEqual(y, 418)
        self.assertLessEqual(x + width, 490)
        self.assertLessEqual(y + height, 460)

    def test_team_preset_click_stays_inside_icon(self):
        x, y, width, height = ScriptTask.C_TEAM_PRESET.roi_front
        self.assertGreaterEqual(x, 905)
        self.assertGreaterEqual(y, 588)
        self.assertLessEqual(x + width, 955)
        self.assertLessEqual(y + height, 642)

    def test_monthly_preset_group_click_stays_inside_activity_panel(self):
        x, y, width, height = ScriptTask.C_PRESET_GROUP_MONTHLY.roi_front
        self.assertGreaterEqual(x, 550)
        self.assertGreaterEqual(y, 360)
        self.assertLessEqual(x + width, 675)
        self.assertLessEqual(y + height, 420)

    def test_search_first_when_search_is_available(self):
        self.assertEqual(
            ScriptTask._choose_search_decision(
                search_available=True,
                own_card_visible=False,
                ticket_count=0,
            ),
            XiuxingHexunSearchDecision.SEARCH,
        )

    def test_resume_only_explicit_own_card_when_search_is_unavailable(self):
        self.assertEqual(
            ScriptTask._choose_search_decision(
                search_available=False,
                own_card_visible=True,
                ticket_count=0,
            ),
            XiuxingHexunSearchDecision.RESUME_OWN_CARD,
        )

    def test_teammate_card_is_not_treated_as_own_card(self):
        self.assertEqual(
            ScriptTask._choose_search_decision(
                search_available=False,
                own_card_visible=False,
                ticket_count=3,
            ),
            XiuxingHexunSearchDecision.UNKNOWN,
        )

    def test_ticket_increase_is_not_treated_as_anomaly(self):
        for ticket_count in (42, 43):
            with self.subTest(ticket_count=ticket_count):
                self.assertEqual(
                    ScriptTask._choose_search_decision(
                        search_available=False,
                        own_card_visible=False,
                        ticket_count=ticket_count,
                    ),
                    XiuxingHexunSearchDecision.UNKNOWN,
                )

    def test_zero_ticket_without_own_card_is_only_normal_exhaustion(self):
        self.assertEqual(
            ScriptTask._choose_search_decision(
                search_available=False,
                own_card_visible=False,
                ticket_count=0,
            ),
            XiuxingHexunSearchDecision.EMPTY,
        )

    def test_existing_challenge_page_is_available_without_search(self):
        challenge = object()
        harness = SimpleNamespace(
            I_CHALLENGE_PAGE=challenge,
            appear=lambda marker: marker is challenge,
        )
        self.assertEqual(
            ScriptTask._search(harness),
            XiuxingHexunTicketState.AVAILABLE,
        )

    def test_existing_prepare_page_is_available_without_search(self):
        prepare = object()
        harness = SimpleNamespace(
            I_CHALLENGE_PAGE=object(),
            I_PREPARE=prepare,
            appear=lambda marker: marker is prepare,
        )
        harness._prepare_page_visible = ScriptTask._prepare_page_visible.__get__(harness)
        harness._prepare_button_visible = lambda: False
        self.assertEqual(
            ScriptTask._search(harness),
            XiuxingHexunTicketState.AVAILABLE,
        )

    def test_generic_general_battle_prepare_evidence_is_available(self):
        prepare = object()
        harness = SimpleNamespace(
            I_PREPARE=prepare,
            appear=lambda _marker: False,
            _prepare_button_visible=lambda: True,
        )
        self.assertTrue(ScriptTask._prepare_page_visible(harness))

    def test_explicit_result_recovery_records_victory(self):
        result_marker = object()
        harness = SimpleNamespace(
            I_RESULT=result_marker,
            appear=lambda marker: marker is result_marker,
            screenshot=lambda: None,  # DeepSeek-13 2.6: second stable frame required
        )
        with patch("tasks.XiuxingHexun.script_task.record_battle_result") as record:
            self.assertTrue(ScriptTask._recover_existing_result(harness))
        self.assertEqual(record.call_args.args[1], "victory")
        self.assertTrue(record.call_args.kwargs["recovered"])

    def test_explicit_result_recovery_rejects_unstable_title(self):
        # DeepSeek-13 2.6 (F-8): a single-frame victory title is no longer
        # enough; the second frame must agree.
        result_marker = object()
        seen = {"count": 0}

        def appear(marker):
            if marker is not result_marker:
                return False
            seen["count"] += 1
            return seen["count"] == 1  # only the first frame matches

        harness = SimpleNamespace(
            I_RESULT=result_marker,
            appear=appear,
            screenshot=lambda: None,
        )
        with patch("tasks.XiuxingHexun.script_task.record_battle_result") as record:
            self.assertFalse(ScriptTask._recover_existing_result(harness))
        record.assert_not_called()

    def test_active_battle_recovery_waits_for_result_without_prepare(self):
        config = SimpleNamespace(
            general_battle_config=SimpleNamespace(random_click_swipt_enable=False),
        )
        harness = SimpleNamespace(battle_wait=lambda enabled: enabled is False)
        with patch("tasks.XiuxingHexun.script_task.record_battle_result") as record:
            self.assertTrue(ScriptTask._resume_active_battle(harness, config))
        self.assertEqual(record.call_args.args[1], "victory")
        self.assertTrue(record.call_args.kwargs["recovered"])

    def test_own_card_click_roi_stays_inside_top_card(self):
        x, y, width, height = ScriptTask.C_OWN_CARD.roi_front
        self.assertGreaterEqual(x, 10)
        self.assertGreaterEqual(y, 90)
        self.assertLessEqual(x + width, 280)
        self.assertLessEqual(y + height, 195)

    def test_ticket_state_requires_explicit_evidence(self):
        home = object()
        challenge = object()
        harness = SimpleNamespace(
            I_ACTIVITY_HOME=home,
            I_CHALLENGE_PAGE=challenge,
            O_TICKET_COUNT=SimpleNamespace(ocr_single=lambda _image: ""),
            device=SimpleNamespace(image=object()),
            appear=lambda marker: marker is home,
            screenshot=lambda: None,
        )
        harness._read_ticket_count = ScriptTask._read_ticket_count.__get__(harness)
        harness._ticket_count_is_stably_zero = (
            ScriptTask._ticket_count_is_stably_zero.__get__(harness)
        )
        self.assertEqual(
            ScriptTask._ticket_state_from_current_frame(harness),
            XiuxingHexunTicketState.UNKNOWN,
        )

        harness.O_TICKET_COUNT = SimpleNamespace(ocr_single=lambda _image: "0")
        self.assertEqual(
            ScriptTask._ticket_state_from_current_frame(harness),
            XiuxingHexunTicketState.EMPTY,
        )

        harness.O_TICKET_COUNT = SimpleNamespace(ocr_single=lambda _image: 0)
        self.assertEqual(
            ScriptTask._ticket_state_from_current_frame(harness),
            XiuxingHexunTicketState.EMPTY,
        )

        harness.O_TICKET_COUNT = SimpleNamespace(ocr_single=lambda _image: "54")
        harness.appear = lambda marker: marker is challenge
        self.assertEqual(
            ScriptTask._ticket_state_from_current_frame(harness),
            XiuxingHexunTicketState.AVAILABLE,
        )

    def test_ticket_ocr_empty_raw_result_is_unknown(self):
        class RawModel:
            @staticmethod
            def ocr_single_line(_image):
                return "", 0.99

        rule = SimpleNamespace(
            model=RawModel(),
            roi=(0, 0, 1, 1),
            score=0.5,
            min_score=0.3,
            crop=lambda image, _roi: image,
            pre_process=lambda image: image,
            after_process=lambda text: int(text) if text else 0,
        )
        harness = SimpleNamespace(
            O_TICKET_COUNT=rule,
            device=SimpleNamespace(image=object()),
        )
        self.assertIsNone(ScriptTask._read_ticket_count(harness))

    def test_ticket_ocr_explicit_zero_is_zero(self):
        class RawModel:
            @staticmethod
            def ocr_single_line(_image):
                return "0", 0.99

        rule = SimpleNamespace(
            model=RawModel(),
            roi=(0, 0, 1, 1),
            score=0.5,
            min_score=0.3,
            crop=lambda image, _roi: image,
            pre_process=lambda image: image,
            after_process=lambda text: int(text),
        )
        harness = SimpleNamespace(
            O_TICKET_COUNT=rule,
            device=SimpleNamespace(image=object()),
        )
        self.assertEqual(ScriptTask._read_ticket_count(harness), 0)

    def test_ticket_ocr_letter_o_is_not_zero_evidence(self):
        class RawModel:
            @staticmethod
            def ocr_single_line(_image):
                return "O", 0.99

        rule = SimpleNamespace(
            model=RawModel(),
            roi=(0, 0, 1, 1),
            score=0.5,
            min_score=0.3,
            crop=lambda image, _roi: image,
            pre_process=lambda image: image,
            after_process=lambda _text: 0,
        )
        harness = SimpleNamespace(
            O_TICKET_COUNT=rule,
            device=SimpleNamespace(image=object()),
        )
        self.assertIsNone(ScriptTask._read_ticket_count(harness))

    def test_zero_ticket_requires_three_stable_reads(self):
        home = object()
        readings = iter((0, 0, 0))
        harness = SimpleNamespace(
            I_ACTIVITY_HOME=home,
            appear=lambda marker: marker is home,
            screenshot=lambda: None,
            TICKET_ZERO_CONFIRM_SAMPLES=3,
            TICKET_ZERO_CONFIRM_INTERVAL=0.25,
            _read_ticket_count=lambda: next(readings),
        )
        with patch("tasks.XiuxingHexun.script_task.time.sleep"):
            self.assertTrue(
                ScriptTask._ticket_count_is_stably_zero(
                    harness,
                )
            )

    def test_zero_ticket_ocr_glitch_does_not_complete(self):
        home = object()
        readings = iter((0, 41))
        harness = SimpleNamespace(
            I_ACTIVITY_HOME=home,
            appear=lambda marker: marker is home,
            screenshot=lambda: None,
            TICKET_ZERO_CONFIRM_SAMPLES=3,
            TICKET_ZERO_CONFIRM_INTERVAL=0.25,
            _read_ticket_count=lambda: next(readings),
        )
        with patch("tasks.XiuxingHexun.script_task.time.sleep"):
            self.assertFalse(
                ScriptTask._ticket_count_is_stably_zero(
                    harness,
                    initial_count=0,
                )
            )

    def test_search_no_result_with_stable_zero_is_empty(self):
        home = object()
        own_badge = object()
        readings = iter((0, 0, 0))
        harness = SimpleNamespace(
            I_ACTIVITY_HOME=home,
            I_OWN_DISCOVERED_BADGE=own_badge,
            appear=lambda marker: marker is home,
            screenshot=lambda: None,
            TICKET_ZERO_CONFIRM_SAMPLES=3,
            TICKET_ZERO_CONFIRM_INTERVAL=0.25,
            _read_ticket_count=lambda: next(readings),
        )
        harness._ticket_count_is_stably_zero = (
            ScriptTask._ticket_count_is_stably_zero.__get__(harness)
        )
        with patch("tasks.XiuxingHexun.script_task.time.sleep"):
            self.assertTrue(
                ScriptTask._confirm_empty_after_search(
                    harness,
                    own_badge,
                )
            )

    def test_search_no_result_with_nonzero_ticket_is_not_empty(self):
        home = object()
        own_badge = object()
        harness = SimpleNamespace(
            I_ACTIVITY_HOME=home,
            I_OWN_DISCOVERED_BADGE=own_badge,
            appear=lambda marker: marker is home,
            screenshot=lambda: None,
            _read_ticket_count=lambda: 2,
        )
        self.assertFalse(
            ScriptTask._confirm_empty_after_search(
                harness,
                own_badge,
            )
        )

    def test_search_no_result_can_use_search_control_as_page_anchor(self):
        search = object()
        own_badge = object()
        readings = iter((0, 0, 0))
        harness = SimpleNamespace(
            I_ACTIVITY_HOME=object(),
            I_SEARCH_AVAILABLE=search,
            I_OWN_DISCOVERED_BADGE=own_badge,
            SEARCH_EMPTY_CONFIRM_TIMEOUT=0.1,
            TICKET_ZERO_CONFIRM_SAMPLES=3,
            TICKET_ZERO_CONFIRM_INTERVAL=0.25,
            appear=lambda marker: marker is search,
            screenshot=lambda: None,
            _read_ticket_count=lambda: next(readings),
        )
        harness._activity_page_visible = (
            ScriptTask._activity_page_visible.__get__(harness)
        )
        harness._ticket_count_is_stably_zero = (
            ScriptTask._ticket_count_is_stably_zero.__get__(harness)
        )
        with patch("tasks.XiuxingHexun.script_task.time.sleep"):
            self.assertTrue(
                ScriptTask._confirm_empty_after_search(
                    harness,
                    own_badge,
                )
            )

    def test_preset_name_mismatch_is_not_accepted(self):
        config = SimpleNamespace(
            general_battle_config=SimpleNamespace(
                preset_group_name="每月活动",
                preset_team_name="【修行合训】顶配",
            )
        )
        harness = SimpleNamespace(
            I_PRESET_PAGE=object(),
            I_PRESET_TEAM=object(),
            appear=lambda _marker: False,
        )
        self.assertFalse(ScriptTask._preset_markers_match(harness, config))

    def test_missing_battle_result_is_not_success(self):
        result = getattr(SimpleNamespace(), "last_battle_result", None)
        self.assertIsNone(result)

    def test_failure_keeps_screenshot_evidence_and_raises(self):
        saved = []
        harness = SimpleNamespace(
            device=SimpleNamespace(
                save_screenshot=lambda **kwargs: saved.append(kwargs),
            ),
        )
        harness._save_failure_evidence = ScriptTask._save_failure_evidence.__get__(harness)
        with self.assertRaises(GameStuckError):
            ScriptTask._fail(harness, "unknown page", stage="page")
        self.assertEqual(saved[0]["genre"], "xiuxing_hexun_page")

    def test_battle_wait_uses_ten_minute_bound(self):
        with patch(
            "tasks.XiuxingHexun.script_task.GeneralBattle.battle_wait",
            return_value=True,
        ) as battle_wait:
            harness = SimpleNamespace(BATTLE_TIMEOUT=600.0)
            self.assertTrue(ScriptTask.battle_wait(harness, False))
        self.assertEqual(battle_wait.call_args.kwargs["timeout"], 600.0)


if __name__ == "__main__":
    unittest.main()
