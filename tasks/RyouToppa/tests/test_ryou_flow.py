import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from tasks.RyouToppa.script_task import (
    AreaStatus,
    BattleEntryMode,
    ScriptTask,
    TeamLockValidationState,
    TicketStatus,
)
from tasks.RyouToppa.guild_selector import (
    GuildCandidate,
    GuildSortOrder,
    classify_guild_sort_order,
    choose_highest_medal_guild,
    compare_guild_sort_snapshots,
    compare_guild_observations,
    verify_final_descending_snapshot,
)
from tasks.RyouToppa.assets import RyouToppaAssets
from tasks.RealmRaid.assets import RealmRaidAssets


class AreaHarness:
    _area_status = ScriptTask._area_status
    check_area = ScriptTask.check_area

    def __init__(self, visible):
        self.visible = set(visible)

    def screenshot(self):
        return None

    def appear(self, target, **_kwargs):
        return target in self.visible


class BoardHarness:
    _run_ryou_board = ScriptTask._run_ryou_board
    _read_area_statuses = ScriptTask._read_area_statuses
    _area_status = ScriptTask._area_status
    _board_marker_visible = ScriptTask._board_marker_visible

    I_TOPPA_RECORD = object()
    I_RYOU_REWARD = object()
    I_RYOU_REWARD_90 = object()
    I_SUCCESS_PENETRATION = object()

    def __init__(self, visible):
        self.visible = set(visible)
        self.start_time = datetime.now()
        self.current_count = 0
        self.device = SimpleNamespace(stuck_record_add=lambda *_args: None)

    def screenshot(self):
        return None

    def appear(self, target, **_kwargs):
        return target in self.visible


class AttackButtonHarness:
    _click_ryou_attack_button = ScriptTask._click_ryou_attack_button

    def __init__(self, visible):
        self.visible = set(visible)
        self.clicked = []

    def appear_then_click(self, target, **_kwargs):
        if target not in self.visible:
            return False
        self.visible.remove(target)
        self.clicked.append(target)
        return True


class TeamLockHarness:
    _initialize_team_lock_validation = ScriptTask._initialize_team_lock_validation
    _observe_team_lock_entry = ScriptTask._observe_team_lock_entry
    _after_ryou_battle_return = ScriptTask._after_ryou_battle_return
    _ensure_ryou_team_locked = ScriptTask._ensure_ryou_team_locked

    I_TOPPA_LOCK_TEAM = RyouToppaAssets.I_TOPPA_LOCK_TEAM
    I_TOPPA_UNLOCK_TEAM = RyouToppaAssets.I_TOPPA_UNLOCK_TEAM

    def __init__(self, lock_state="locked"):
        self.clicks = []
        self.lock_state = lock_state

    def screenshot(self):
        return None

    def appear(self, target, **_kwargs):
        return (
            target is self.I_TOPPA_UNLOCK_TEAM and self.lock_state == "locked"
        ) or (
            target is self.I_TOPPA_LOCK_TEAM and self.lock_state == "unlocked"
        )

    def appear_then_click(self, target, **_kwargs):
        if target is not self.I_TOPPA_LOCK_TEAM or self.lock_state != "unlocked":
            return False
        self.clicks.append(target.name)
        self.lock_state = "locked"
        return True


class BattleEntryHarness:
    _wait_for_battle_entry = ScriptTask._wait_for_battle_entry

    I_WIN = object()
    I_FALSE = object()

    def __init__(
        self,
        *,
        prepare_visible=False,
        prepare_page=False,
        real_battle=False,
        frames=None,
    ):
        self.prepare_visible = prepare_visible
        self.prepare_page = prepare_page
        self.real_battle = real_battle
        self.frames = list(frames or ())
        self.frame_index = -1

    def screenshot(self):
        if self.frames:
            self.frame_index = min(self.frame_index + 1, len(self.frames) - 1)
            frame = self.frames[self.frame_index]
            self.prepare_visible = frame.get("prepare_visible", False)
            self.prepare_page = frame.get("prepare_page", False)
            self.real_battle = frame.get("real_battle", False)
        return None

    def _click_ryou_attack_button(self):
        return False

    def _prepare_button_visible(self):
        return self.prepare_visible

    def is_in_prepare(self, _screenshot):
        return self.prepare_page

    def is_in_real_battle(self, _screenshot):
        return self.real_battle

    def _battle_result_continue_visible(self):
        return False

    def appear(self, _target, **_kwargs):
        return False


class GuildSelectionHarness:
    _auto_select_highest_medal_ryou = ScriptTask._auto_select_highest_medal_ryou
    _wait_stable_guild_sort_snapshot = ScriptTask._wait_stable_guild_sort_snapshot
    _board_marker_visible = ScriptTask._board_marker_visible

    I_TOPPA_RECORD = object()
    I_RYOU_REWARD = object()
    I_RYOU_REWARD_90 = object()
    I_SUCCESS_PENETRATION = object()
    I_SELECT_RYOU_BUTTON = object()
    I_GUILD_ORDERS_REWARDS = object()
    I_START_TOPPA_BUTTON = object()

    C_GUILD_ORDERS_REWARDS = RyouToppaAssets.C_GUILD_ORDERS_REWARDS
    C_SELECT_FIRST_RYOU = RyouToppaAssets.C_SELECT_FIRST_RYOU

    def __init__(self):
        self.visible = {self.I_SELECT_RYOU_BUTTON}
        self.actions = []
        self.device = SimpleNamespace(click=self._device_click)
        self.config = SimpleNamespace(
            ryou_toppa=SimpleNamespace(
                raid_config=SimpleNamespace(auto_select_highest_guild=False),
            ),
        )

    def screenshot(self):
        return None

    def appear(self, target, **_kwargs):
        return target in self.visible

    def appear_then_click(self, target, **_kwargs):
        if target is self.I_SELECT_RYOU_BUTTON and target in self.visible:
            self.visible.remove(target)
            self.visible.add(self.I_GUILD_ORDERS_REWARDS)
            self.actions.append("open_list")
            return True
        if target is self.I_START_TOPPA_BUTTON and target in self.visible:
            self.visible.remove(target)
            self.actions.append("start")
            self.visible.add(self.I_TOPPA_RECORD)
            return True
        return False

    def _device_click(self, x, y, control_name):
        self.actions.append(control_name)
        if control_name == self.C_GUILD_ORDERS_REWARDS.name:
            self.visible.add(self.I_GUILD_ORDERS_REWARDS)
            self.visible.add(self.I_START_TOPPA_BUTTON)


class VerifiedGuildSelectionHarness(GuildSelectionHarness):
    GUILD_CANDIDATE_OCR_RULES = (object(),)

    def __init__(self):
        super().__init__()
        self.config.ryou_toppa.raid_config.auto_select_highest_guild = True
        self.observations = [
            (
                GuildCandidate("row_1", (1070, 96, 180, 138), (1160, 145), 241, 0.98, "f1", "1" * 64),
                GuildCandidate("row_2", (1070, 240, 180, 138), (1160, 289), 231, 0.98, "f1", "1" * 64),
                GuildCandidate("row_3", (1070, 384, 180, 138), (1160, 433), 219, 0.98, "f1", "1" * 64),
                GuildCandidate("row_4", (1070, 528, 180, 138), (1160, 577), 205, 0.98, "f1", "1" * 64),
            ),
            (
                GuildCandidate("row_1", (1070, 96, 180, 138), (1160, 145), 241, 0.97, "f2", "2" * 64),
                GuildCandidate("row_2", (1070, 240, 180, 138), (1160, 289), 231, 0.97, "f2", "2" * 64),
                GuildCandidate("row_3", (1070, 384, 180, 138), (1160, 433), 219, 0.97, "f2", "2" * 64),
                GuildCandidate("row_4", (1070, 528, 180, 138), (1160, 577), 205, 0.97, "f2", "2" * 64),
            ),
            (
                GuildCandidate("row_1", (1070, 96, 180, 138), (1160, 145), 57, 0.97, "f3", "3" * 64),
                GuildCandidate("row_2", (1070, 240, 180, 138), (1160, 289), 58, 0.97, "f3", "3" * 64),
                GuildCandidate("row_3", (1070, 384, 180, 138), (1160, 433), 60, 0.97, "f3", "3" * 64),
                GuildCandidate("row_4", (1070, 528, 180, 138), (1160, 577), 64, 0.97, "f3", "3" * 64),
            ),
            (
                GuildCandidate("row_1", (1070, 96, 180, 138), (1160, 145), 57, 0.97, "f4", "4" * 64),
                GuildCandidate("row_2", (1070, 240, 180, 138), (1160, 289), 58, 0.97, "f4", "4" * 64),
                GuildCandidate("row_3", (1070, 384, 180, 138), (1160, 433), 60, 0.97, "f4", "4" * 64),
                GuildCandidate("row_4", (1070, 528, 180, 138), (1160, 577), 64, 0.97, "f4", "4" * 64),
            ),
            (
                GuildCandidate("row_1", (1070, 96, 180, 138), (1160, 145), 241, 0.97, "f5", "5" * 64),
                GuildCandidate("row_2", (1070, 240, 180, 138), (1160, 289), 231, 0.97, "f5", "5" * 64),
                GuildCandidate("row_3", (1070, 384, 180, 138), (1160, 433), 219, 0.97, "f5", "5" * 64),
                GuildCandidate("row_4", (1070, 528, 180, 138), (1160, 577), 205, 0.97, "f5", "5" * 64),
            ),
            (
                GuildCandidate("row_1", (1070, 96, 180, 138), (1160, 145), 241, 0.97, "f6", "6" * 64),
                GuildCandidate("row_2", (1070, 240, 180, 138), (1160, 289), 231, 0.97, "f6", "6" * 64),
                GuildCandidate("row_3", (1070, 384, 180, 138), (1160, 433), 219, 0.97, "f6", "6" * 64),
                GuildCandidate("row_4", (1070, 528, 180, 138), (1160, 577), 205, 0.97, "f6", "6" * 64),
            ),
        ]

    def _observe_guild_candidates(self):
        if len(self.observations) > 1:
            return self.observations.pop(0)
        return self.observations[0]

    def _device_click(self, x, y, control_name):
        self.actions.append(control_name)
        if control_name == self.C_SELECT_FIRST_RYOU.name:
            self.visible.add(self.I_START_TOPPA_BUTTON)

    def click(self, target, **_kwargs):
        self.actions.append(target.name)
        if target is self.C_SELECT_FIRST_RYOU:
            self.visible.add(self.I_START_TOPPA_BUTTON)
        return True


class AscendingFirstGuildSelectionHarness(VerifiedGuildSelectionHarness):
    def __init__(self):
        super().__init__()
        ascending = self.observations[2:4]
        descending = self.observations[0:2]
        final_descending = self.observations[4:6]
        self.observations = ascending + descending + final_descending


class UnchangedSortGuildSelectionHarness(VerifiedGuildSelectionHarness):
    def __init__(self):
        super().__init__()
        self.observations = self.observations[0:2]


class RyouFlowTest(unittest.TestCase):
    def test_attack_confirmation_button_is_clicked_before_battle_wait(self):
        harness = AttackButtonHarness([RealmRaidAssets.I_FIRE_CURRENT])

        self.assertTrue(harness._click_ryou_attack_button())
        self.assertEqual(harness.clicked, [RealmRaidAssets.I_FIRE_CURRENT])

    def test_team_lock_search_roi_covers_observed_left_shift(self):
        """The board icon may appear at x=198 instead of nominal x=202."""
        for asset, template_size in (
            (RyouToppaAssets.I_TOPPA_LOCK_TEAM, (26, 32)),
            (RyouToppaAssets.I_TOPPA_UNLOCK_TEAM, (25, 31)),
        ):
            x, y, width, height = asset.roi_back
            template_width, template_height = template_size
            self.assertLessEqual(x, 198)
            self.assertLessEqual(y, 603)
            self.assertGreaterEqual(x + width, 198 + template_width)
            self.assertGreaterEqual(y + height, 603 + template_height)

    def test_team_lock_first_prepare_keeps_existing_lock_without_toggling(self):
        harness = TeamLockHarness(lock_state="locked")
        harness._initialize_team_lock_validation(True)

        harness._observe_team_lock_entry(BattleEntryMode.PREPARE_REQUIRED)
        self.assertEqual(
            harness._team_lock_validation_state,
            TeamLockValidationState.CLICK_AFTER_RETURN,
        )
        self.assertEqual(harness.clicks, [])

        harness._after_ryou_battle_return()

        self.assertEqual(
            harness._team_lock_validation_state,
            TeamLockValidationState.VERIFY_NEXT_BATTLE,
        )
        self.assertEqual(harness.clicks, [])

    def test_team_lock_first_prepare_clicks_verified_unlocked_icon_once(self):
        harness = TeamLockHarness(lock_state="unlocked")
        harness._initialize_team_lock_validation(True)
        harness._observe_team_lock_entry(BattleEntryMode.PREPARE_REQUIRED)

        harness._after_ryou_battle_return()

        self.assertEqual(
            harness._team_lock_validation_state,
            TeamLockValidationState.VERIFY_NEXT_BATTLE,
        )
        self.assertEqual(harness.clicks, [RyouToppaAssets.I_TOPPA_LOCK_TEAM.name])
        self.assertEqual(harness.lock_state, "locked")

    def test_team_lock_unknown_state_fails_closed_without_click(self):
        harness = TeamLockHarness(lock_state="unknown")

        locked, action = harness._ensure_ryou_team_locked(timeout=0)

        self.assertFalse(locked)
        self.assertEqual(action, "lock_state_unknown")
        self.assertEqual(harness.clicks, [])

    def test_team_lock_second_direct_battle_confirms_click_effect(self):
        harness = TeamLockHarness()
        harness._initialize_team_lock_validation(True)
        harness._observe_team_lock_entry(BattleEntryMode.PREPARE_REQUIRED)
        harness._after_ryou_battle_return()

        harness._observe_team_lock_entry(BattleEntryMode.DIRECT_BATTLE)

        self.assertEqual(
            harness._team_lock_validation_state,
            TeamLockValidationState.VERIFIED,
        )
        self.assertEqual(harness.clicks, [])

    def test_team_lock_second_prepare_records_supported_boundary_without_reclick(self):
        harness = TeamLockHarness()
        harness._initialize_team_lock_validation(True)
        harness._observe_team_lock_entry(BattleEntryMode.PREPARE_REQUIRED)
        harness._after_ryou_battle_return()

        harness._observe_team_lock_entry(BattleEntryMode.PREPARE_REQUIRED)
        harness._after_ryou_battle_return()

        self.assertEqual(
            harness._team_lock_validation_state,
            TeamLockValidationState.VERIFIED_PREPARE_REQUIRED,
        )
        self.assertEqual(harness.clicks, [])

    def test_team_lock_first_direct_battle_is_already_locked(self):
        harness = TeamLockHarness()
        harness._initialize_team_lock_validation(True)

        harness._observe_team_lock_entry(BattleEntryMode.DIRECT_BATTLE)
        harness._after_ryou_battle_return()

        self.assertEqual(
            harness._team_lock_validation_state,
            TeamLockValidationState.VERIFIED,
        )
        self.assertEqual(harness.clicks, [])

    def test_team_lock_disabled_never_clicks(self):
        harness = TeamLockHarness()
        harness._initialize_team_lock_validation(False)

        harness._observe_team_lock_entry(BattleEntryMode.PREPARE_REQUIRED)
        harness._after_ryou_battle_return()

        self.assertEqual(
            harness._team_lock_validation_state,
            TeamLockValidationState.DISABLED,
        )
        self.assertEqual(harness.clicks, [])

    def test_battle_entry_prepare_wins_over_weak_real_battle_signal(self):
        harness = BattleEntryHarness(prepare_visible=True, real_battle=True)

        self.assertIs(
            harness._wait_for_battle_entry(timeout=0.5),
            BattleEntryMode.PREPARE_REQUIRED,
        )

    def test_transient_loading_prepare_signal_does_not_hide_direct_battle(self):
        harness = BattleEntryHarness(
            frames=(
                {"prepare_visible": True},
                {"real_battle": True},
            )
        )

        self.assertIs(
            harness._wait_for_battle_entry(timeout=0.5),
            BattleEntryMode.DIRECT_BATTLE,
        )

    def test_battle_entry_without_prepare_is_direct(self):
        harness = BattleEntryHarness(real_battle=True)

        self.assertIs(
            harness._wait_for_battle_entry(timeout=0.1),
            BattleEntryMode.DIRECT_BATTLE,
        )

    def test_ticket_ocr_unknown_is_not_empty(self):
        self.assertIs(
            ScriptTask._ticket_status_from_ocr((0, 6, 6)),
            TicketStatus.AVAILABLE,
        )
        self.assertIs(
            ScriptTask._ticket_status_from_ocr((6, 0, 6)),
            TicketStatus.EMPTY,
        )
        self.assertIs(
            ScriptTask._ticket_status_from_ocr((0, 0, 0)),
            TicketStatus.UNKNOWN,
        )

    def test_finished_marker_wins_over_failure_marker(self):
        from tasks.RyouToppa.script_task import area_map

        finished = area_map[0]["finished_sign"][0]
        failed = area_map[0]["fail_sign"][0]
        harness = AreaHarness([finished, failed])

        self.assertIs(harness._area_status(0), AreaStatus.FINISHED)
        self.assertFalse(harness.check_area(0))

    def test_board_completes_only_after_all_area_finish_markers(self):
        from tasks.RyouToppa.script_task import area_map

        visible = [BoardHarness.I_TOPPA_RECORD]
        visible.extend(
            area["finished_sign"][0]
            for area in area_map
        )
        harness = BoardHarness(visible)
        config = SimpleNamespace(
            raid_config=SimpleNamespace(limit_count=50),
            general_battle_config=SimpleNamespace(),
        )

        result = harness._run_ryou_board(config, timedelta(seconds=5))

        self.assertEqual(result, "completed")

    def test_auto_select_is_disabled_by_default_and_never_clicks(self):
        harness = GuildSelectionHarness()

        self.assertFalse(harness._auto_select_highest_medal_ryou(timeout=2))
        self.assertEqual(harness.actions, [])

    def test_verified_auto_select_compares_orders_returns_descending_then_starts(self):
        harness = VerifiedGuildSelectionHarness()

        self.assertTrue(harness._auto_select_highest_medal_ryou(timeout=2))
        self.assertEqual(
            harness.actions,
            [
                "open_list",
                "guild_orders_rewards",
                "guild_orders_rewards",
                "select_first_ryou",
                "start",
            ],
        )

    def test_ascending_initial_page_needs_only_one_sort_click(self):
        harness = AscendingFirstGuildSelectionHarness()

        self.assertTrue(harness._auto_select_highest_medal_ryou(timeout=2))
        self.assertEqual(
            harness.actions,
            [
                "open_list",
                "guild_orders_rewards",
                "select_first_ryou",
                "start",
            ],
        )

    def test_unchanged_sort_never_selects_first_card(self):
        harness = UnchangedSortGuildSelectionHarness()

        self.assertFalse(harness._auto_select_highest_medal_ryou(timeout=1.2))
        self.assertEqual(harness.actions, ["open_list", "guild_orders_rewards"])

    def test_real_descending_values_are_classified(self):
        snapshot = classify_guild_sort_order(
            self._guild_rows((241, 231, 219, 205), frame_id="descending")
        )

        self.assertTrue(snapshot.verified)
        self.assertIs(snapshot.order, GuildSortOrder.DESCENDING)
        self.assertEqual(snapshot.values, (241, 231, 219, 205))

    def test_real_ascending_values_are_classified(self):
        snapshot = classify_guild_sort_order(
            self._guild_rows((57, 58, 60, 64), frame_id="ascending")
        )

        self.assertTrue(snapshot.verified)
        self.assertIs(snapshot.order, GuildSortOrder.ASCENDING)
        self.assertEqual(snapshot.values, (57, 58, 60, 64))

    def test_non_monotonic_sort_is_rejected(self):
        snapshot = classify_guild_sort_order(
            self._guild_rows((241, 205, 231, 219), frame_id="mixed")
        )

        self.assertFalse(snapshot.verified)
        self.assertIs(snapshot.order, GuildSortOrder.UNKNOWN)
        self.assertEqual(snapshot.reason, "not_monotonic")

    def test_sort_pair_records_global_extremes(self):
        descending = classify_guild_sort_order(
            self._guild_rows((241, 231, 219, 205), frame_id="descending")
        )
        ascending = classify_guild_sort_order(
            self._guild_rows((57, 58, 60, 64), frame_id="ascending")
        )

        result = compare_guild_sort_snapshots(descending, ascending)

        self.assertTrue(result.verified)
        self.assertEqual(result.highest_medal, 241)
        self.assertEqual(result.lowest_medal, 57)
        self.assertEqual(result.descending_values, (241, 231, 219, 205))
        self.assertEqual(result.ascending_values, (57, 58, 60, 64))

    def test_same_sort_order_pair_is_rejected(self):
        first = classify_guild_sort_order(
            self._guild_rows((241, 231, 219, 205), frame_id="first")
        )
        second = classify_guild_sort_order(
            self._guild_rows((241, 231, 219, 205), frame_id="second")
        )

        result = compare_guild_sort_snapshots(first, second)

        self.assertFalse(result.verified)
        self.assertEqual(result.reason, "sort_order_not_toggled")

    def test_final_descending_page_must_match_recorded_highest(self):
        expected = classify_guild_sort_order(
            self._guild_rows((241, 231, 219, 205), frame_id="expected")
        )
        wrong = classify_guild_sort_order(
            self._guild_rows((231, 219, 205, 199), frame_id="wrong")
        )

        result = verify_final_descending_snapshot(expected, wrong)

        self.assertFalse(result.verified)
        self.assertEqual(result.reason, "descending_values_changed")

    @staticmethod
    def _guild_rows(values, *, frame_id):
        frame_hash = (frame_id[0] if frame_id else "a") * 64
        return tuple(
            GuildCandidate(
                f"row_{index}",
                (1070, 96 + (index - 1) * 144, 180, 138),
                (1160, 145 + (index - 1) * 144),
                value,
                0.95,
                frame_id,
                frame_hash,
            )
            for index, value in enumerate(values, 1)
        )

    def test_highest_medal_candidate_is_selected_from_complete_observation(self):
        candidates = (
            GuildCandidate("guild_a", (900, 100, 200, 90), (1000, 145), 120, 0.98, "f1", "a" * 64),
            GuildCandidate("guild_b", (900, 210, 200, 90), (1000, 255), 360, 0.96, "f1", "a" * 64),
            GuildCandidate("guild_c", (900, 320, 200, 90), (1000, 365), 240, 0.97, "f1", "a" * 64),
        )

        result = choose_highest_medal_guild(candidates)

        self.assertTrue(result.verified)
        self.assertEqual(result.selected.candidate_id, "guild_b")
        self.assertEqual(result.max_medal, 360)

    def test_equal_highest_medals_use_top_then_left_order(self):
        candidates = (
            GuildCandidate("lower", (900, 210, 200, 90), (1000, 255), 360, 0.96, "f1", "b" * 64),
            GuildCandidate("top_right", (1020, 100, 200, 90), (1120, 145), 360, 0.96, "f1", "b" * 64),
            GuildCandidate("top_left", (800, 100, 200, 90), (900, 145), 360, 0.96, "f1", "b" * 64),
        )

        result = choose_highest_medal_guild(candidates)

        self.assertEqual(result.selected.candidate_id, "top_left")

    def test_missing_medal_rejects_whole_observation(self):
        candidates = (
            GuildCandidate("guild_a", (900, 100, 200, 90), (1000, 145), 120, 0.98, "f1", "c" * 64),
            GuildCandidate("guild_b", (900, 210, 200, 90), (1000, 255), None, 0.0, "f1", "c" * 64),
        )

        result = choose_highest_medal_guild(candidates)

        self.assertFalse(result.verified)
        self.assertEqual(result.reason, "incomplete_medal_ocr")
        self.assertIsNone(result.selected)

    def test_page_change_between_two_frames_is_rejected(self):
        first = (
            GuildCandidate("guild_a", (900, 100, 200, 90), (1000, 145), 120, 0.98, "f1", "d" * 64),
        )
        second = (
            GuildCandidate("guild_a", (900, 100, 200, 90), (1000, 145), 240, 0.98, "f2", "e" * 64),
        )

        result = compare_guild_observations(first, second)

        self.assertFalse(result.stable)
        self.assertEqual(result.reason, "candidate_values_changed")

    def test_two_stable_new_frames_are_accepted(self):
        first = (
            GuildCandidate("guild_a", (900, 100, 200, 90), (1000, 145), 120, 0.98, "f1", "f" * 64),
        )
        second = (
            GuildCandidate("guild_a", (900, 100, 200, 90), (1000, 145), 120, 0.99, "f2", "0" * 64),
        )

        result = compare_guild_observations(first, second)

        self.assertTrue(result.stable)
        self.assertEqual(result.reason, "stable")


if __name__ == "__main__":
    unittest.main()
