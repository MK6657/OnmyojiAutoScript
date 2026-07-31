import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tasks.RealmRaid.level_mode import (
    BoardSnapshot,
    CheckpointStore,
    LevelAction,
    LevelMode,
    PendingAction,
    choose_level_mode,
    create_checkpoint,
    decide_next_action,
    generation_changed,
    reconcile_checkpoint,
    resolve_broken_levels,
    schedule_after_cooldown,
)


def board(
    level=59,
    broken=(),
    failed=(),
    attack_record=0,
    tickets=30,
    refresh=True,
    cd=None,
    signature='board-a',
):
    return BoardSnapshot(
        levels=(level,) * 9,
        challenge_level=level,
        challenge_level_votes=9,
        broken=frozenset(broken),
        failure_marked=frozenset(failed),
        attack_record=attack_record,
        tickets_current=tickets,
        tickets_total=30,
        refresh_available=refresh,
        refresh_cd_seconds=cd,
        layout_signature=signature,
        captured_at=datetime(2026, 7, 31, 12, 0, 0),
    )


class LevelModeDecisionTest(unittest.TestCase):
    def test_broken_levels_are_imputed_from_four_visible_cards(self):
        levels, imputed, source = resolve_broken_levels(
            (0, 0, 0, 0, 0, 58, 58, 58, 58),
            broken=(1, 2, 3, 4, 5),
        )
        self.assertEqual(levels, (58,) * 9)
        self.assertEqual(imputed, frozenset((1, 2, 3, 4, 5)))
        self.assertEqual(source, 'visible-unbroken')

    def test_inconsistent_visible_levels_are_not_imputed(self):
        raw = (0, 0, 0, 0, 0, 58, 58, 57, 57)
        levels, imputed, source = resolve_broken_levels(
            raw,
            broken=(1, 2, 3, 4, 5),
        )
        self.assertEqual(levels, raw)
        self.assertFalse(imputed)
        self.assertEqual(source, '')

    def test_unknown_unbroken_level_prevents_imputation(self):
        raw = (0, 0, 0, 0, 0, 0, 58, 58, 58)
        levels, imputed, source = resolve_broken_levels(
            raw,
            broken=(1, 2, 3, 4, 5),
        )
        self.assertEqual(levels, raw)
        self.assertFalse(imputed)
        self.assertEqual(source, '')

    def test_checkpoint_level_can_continue_after_sixth_win(self):
        levels, imputed, source = resolve_broken_levels(
            (0, 0, 0, 0, 0, 0, 58, 58, 57),
            broken=(1, 2, 3, 4, 5, 6),
            expected_level=58,
        )
        self.assertEqual(levels, (58, 58, 58, 58, 58, 58, 58, 58, 57))
        self.assertEqual(imputed, frozenset((1, 2, 3, 4, 5, 6)))
        self.assertEqual(source, 'checkpoint')

    def test_choose_mode(self):
        self.assertEqual(choose_level_mode(60, 59), LevelMode.LOWER)
        self.assertEqual(choose_level_mode(59, 59), LevelMode.HOLD)
        self.assertEqual(choose_level_mode(58, 59), LevelMode.RAISE)

    def test_lower_requires_nine_failures_then_refresh(self):
        snapshot = board(level=60)
        checkpoint = create_checkpoint('oas1', snapshot, 59, LevelMode.LOWER)
        self.assertEqual(decide_next_action(snapshot, checkpoint).action, LevelAction.SURRENDER)
        checkpoint.failure_count = 9
        self.assertEqual(decide_next_action(snapshot, checkpoint).action, LevelAction.REFRESH)

    def test_hold_requires_four_failures_and_nine_wins(self):
        snapshot = board(level=59)
        checkpoint = create_checkpoint('oas1', snapshot, 59, LevelMode.HOLD)
        self.assertEqual(decide_next_action(snapshot, checkpoint).action, LevelAction.SURRENDER)
        checkpoint.failure_count = 4
        self.assertEqual(decide_next_action(snapshot, checkpoint).action, LevelAction.ATTACK)
        won = board(level=59, broken=range(1, 10), attack_record=9, tickets=21)
        checkpoint.success_count = 9
        self.assertEqual(decide_next_action(won, checkpoint).action, LevelAction.WAIT_AUTO_REFRESH)

    def test_raise_never_intentionally_surrenders(self):
        snapshot = board(level=58)
        checkpoint = create_checkpoint('oas1', snapshot, 59, LevelMode.RAISE)
        self.assertEqual(decide_next_action(snapshot, checkpoint).action, LevelAction.ATTACK)
        checkpoint.pending_refresh = True
        self.assertEqual(decide_next_action(snapshot, checkpoint).action, LevelAction.REFRESH)

    def test_missing_checkpoint_on_partial_board_uses_recovery_hold(self):
        snapshot = board(level=60, broken=(1, 2, 3, 4), attack_record=4)
        checkpoint = reconcile_checkpoint('oas1', snapshot, 59, None)
        self.assertEqual(checkpoint.level_mode, LevelMode.RECOVERY_HOLD)
        self.assertTrue(checkpoint.recovery_hold)
        self.assertEqual(decide_next_action(snapshot, checkpoint).action, LevelAction.SURRENDER)

    def test_no_ticket_stops(self):
        snapshot = board(level=59, tickets=0)
        checkpoint = create_checkpoint('oas1', snapshot, 59, LevelMode.HOLD)
        self.assertEqual(decide_next_action(snapshot, checkpoint).action, LevelAction.STOP)

    def test_conflicting_success_evidence_is_unsafe(self):
        snapshot = board(level=59, broken=(1,), attack_record=2)
        checkpoint = create_checkpoint('oas1', snapshot, 59, LevelMode.HOLD)
        self.assertEqual(decide_next_action(snapshot, checkpoint).action, LevelAction.UNSAFE)

    def test_generation_change_uses_success_reset(self):
        before = board(level=59, broken=range(1, 10), attack_record=9, signature='board-a')
        after = board(level=59, broken=(), attack_record=0, signature='board-b')
        self.assertTrue(generation_changed(before, after))

    def test_cooldown_schedule_has_safety_buffer(self):
        now = datetime(2026, 7, 31, 12, 0, 0)
        due = schedule_after_cooldown(240, now=now, safety_buffer_seconds=10)
        self.assertEqual(due, datetime(2026, 7, 31, 12, 4, 10))


class CheckpointStoreTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            store = CheckpointStore('MK 6657', root=Path(folder))
            checkpoint = create_checkpoint('MK 6657', board(), 59, LevelMode.HOLD)
            checkpoint.failure_count = 4
            checkpoint.begin_action(PendingAction.ATTACK, board(), target=3)
            store.save(checkpoint)

            loaded = store.load()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.failure_count, 4)
            self.assertEqual(loaded.pending_action, PendingAction.ATTACK.value)
            self.assertEqual(loaded.last_target, 3)
            self.assertEqual(loaded.pending_tickets_before, 30)
            self.assertEqual(store.path.name, 'MK_6657.json')


if __name__ == '__main__':
    unittest.main()
