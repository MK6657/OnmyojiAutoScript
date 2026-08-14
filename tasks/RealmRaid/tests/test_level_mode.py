import tempfile
import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from tasks.RealmRaid.config import LevelModeConfig
from tasks.RealmRaid.level_mode import (
    BoardSnapshot,
    CheckpointStore,
    CheckpointConflictError,
    CheckpointCorruptError,
    CheckpointLockTimeout,
    LevelAction,
    LevelMode,
    PendingAction,
    choose_level_mode,
    cached_board_levels,
    create_checkpoint,
    decide_next_action,
    generation_changed,
    checkpoint_matches,
    reconcile_checkpoint,
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
    def test_production_mode_is_the_default(self):
        self.assertFalse(LevelModeConfig().single_step)

    def test_current_level_uses_all_nine_cells(self):
        snapshot = BoardSnapshot(
            levels=(58, 58, 58, 58, 58, 58, 57, 58, 58),
            challenge_level=58,
            challenge_level_votes=8,
            broken=frozenset((1, 2, 3, 4, 6)),
            attack_record=5,
            tickets_current=30,
            tickets_total=30,
            refresh_available=True,
        )
        self.assertTrue(snapshot.is_safe())

    def test_missing_any_cell_level_is_unsafe(self):
        snapshot = BoardSnapshot(
            levels=(0, 58, 58, 58, 58, 58, 57, 58, 58),
            challenge_level=58,
            challenge_level_votes=7,
            broken=frozenset((1,)),
            attack_record=1,
            tickets_current=30,
            tickets_total=30,
            refresh_available=True,
        )
        self.assertFalse(snapshot.is_safe())

    def test_checkpoint_reuses_complete_levels_only_on_same_board(self):
        snapshot = board(level=58, signature='board-a')
        checkpoint = create_checkpoint('oas1', snapshot, 58, LevelMode.HOLD)

        self.assertEqual(
            cached_board_levels(checkpoint, 'board-a'),
            (58,) * 9,
        )
        self.assertEqual(cached_board_levels(checkpoint, 'board-b'), ())

    def test_checkpoint_cache_rejects_old_or_refreshing_evidence(self):
        snapshot = board(level=58, signature='board-a')
        checkpoint = create_checkpoint('oas1', snapshot, 58, LevelMode.HOLD)
        checkpoint.schema_version = 1
        self.assertEqual(cached_board_levels(checkpoint, 'board-a'), ())

        checkpoint.schema_version = 2
        checkpoint.pending_refresh = True
        self.assertEqual(cached_board_levels(checkpoint, 'board-a'), ())

    def test_checkpoint_cache_rejects_expired_evidence_when_time_is_supplied(self):
        snapshot = board(level=58, signature='board-a')
        checkpoint = create_checkpoint('oas1', snapshot, 58, LevelMode.HOLD)
        now = snapshot.captured_at + timedelta(seconds=901)

        self.assertEqual(
            cached_board_levels(checkpoint, 'board-a', now=now),
            (),
        )

    def test_checkpoint_match_rejects_mode_inconsistent_with_observed_level(self):
        previous = board(level=58, signature='board-a')
        snapshot = board(level=57, signature='board-a')
        checkpoint = create_checkpoint('oas1', previous, 58, LevelMode.HOLD)

        self.assertFalse(checkpoint_matches(checkpoint, snapshot, 58))

    def test_checkpoint_cache_rejects_likely_generation_reset(self):
        snapshot = board(
            level=58,
            broken=(1, 2),
            attack_record=2,
            signature='board-a',
        )
        checkpoint = create_checkpoint('oas1', snapshot, 58, LevelMode.HOLD)

        self.assertEqual(cached_board_levels(checkpoint, 'board-a', broken=()), ())
        self.assertEqual(
            cached_board_levels(checkpoint, 'board-a', broken=(1, 2)),
            (58,) * 9,
        )

    def test_checkpoint_cache_rejects_disappeared_failure_evidence(self):
        snapshot = board(level=58, signature='board-a')
        checkpoint = create_checkpoint('oas1', snapshot, 58, LevelMode.HOLD)
        checkpoint.failure_count = 1

        self.assertEqual(cached_board_levels(checkpoint, 'board-a'), ())
        self.assertEqual(
            cached_board_levels(
                checkpoint,
                'board-a',
                failure_marked=(1,),
            ),
            (58,) * 9,
        )

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

    def test_different_board_signature_does_not_reuse_failure_count(self):
        original = board(
            level=59,
            broken=(1, 2),
            attack_record=2,
            signature='board-a',
        )
        checkpoint = create_checkpoint('oas1', original, 59, LevelMode.HOLD)
        checkpoint.failure_count = 3
        changed = board(
            level=59,
            broken=(1, 2),
            attack_record=2,
            signature='board-b',
        )

        reconciled = reconcile_checkpoint('oas1', changed, 59, checkpoint)

        self.assertEqual(reconciled.level_mode, LevelMode.RECOVERY_HOLD)
        self.assertEqual(reconciled.failure_count, 0)
        self.assertTrue(reconciled.recovery_hold)

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
            self.assertEqual(loaded.schema_version, 3)
            self.assertEqual(loaded.observed_levels, (59,) * 9)
            self.assertEqual(loaded.observed_level_votes, 9)

    def test_revision_and_run_id_advance_on_each_committed_save(self):
        with tempfile.TemporaryDirectory() as folder:
            store = CheckpointStore('oas1', root=Path(folder))
            checkpoint = create_checkpoint('oas1', board(), 59, LevelMode.HOLD)

            store.save(checkpoint)
            self.assertEqual(checkpoint.schema_version, 3)
            self.assertEqual(checkpoint.revision, 1)
            self.assertEqual(checkpoint.run_id, store.run_id)

            checkpoint.failure_count = 1
            store.save(checkpoint)
            self.assertEqual(checkpoint.revision, 2)
            self.assertEqual(store.load().revision, 2)

    def test_stale_checkpoint_cannot_overwrite_newer_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            first = CheckpointStore('oas1', root=Path(folder))
            second = CheckpointStore('oas1', root=Path(folder))
            checkpoint = create_checkpoint('oas1', board(), 59, LevelMode.HOLD)
            first.save(checkpoint)

            stale = second.load()
            current = first.load()
            current.failure_count = 2
            first.save(current)

            stale.failure_count = 9
            with self.assertRaises(CheckpointConflictError):
                second.save(stale)
            self.assertEqual(first.load().failure_count, 2)

    def test_cleared_checkpoint_cannot_be_resurrected_by_stale_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            first = CheckpointStore('oas1', root=Path(folder))
            second = CheckpointStore('oas1', root=Path(folder))
            checkpoint = create_checkpoint('oas1', board(), 59, LevelMode.HOLD)
            first.save(checkpoint)
            stale = second.load()

            first.clear()

            with self.assertRaises(CheckpointConflictError):
                second.save(stale)
            self.assertIsNone(first.load())

    def test_corrupt_checkpoint_is_quarantined_and_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            store = CheckpointStore('oas1', root=Path(folder))
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text('{broken json', encoding='utf-8')

            with self.assertRaises(CheckpointCorruptError) as caught:
                store.load()

            self.assertFalse(store.path.exists())
            quarantine = Path(caught.exception.quarantine_path)
            self.assertTrue(quarantine.exists())
            self.assertIn('.corrupt.', quarantine.name)

    def test_unsupported_schema_is_quarantined_instead_of_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            store = CheckpointStore('oas1', root=Path(folder))
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                '{"schema_version": 999, "account": "oas1"}',
                encoding='utf-8',
            )

            with self.assertRaises(CheckpointCorruptError):
                store.load()

            self.assertFalse(store.path.exists())
            self.assertEqual(len(list(Path(folder).glob('*.corrupt.*.json'))), 1)

    def test_legacy_schema_two_loads_and_upgrades_on_save(self):
        with tempfile.TemporaryDirectory() as folder:
            store = CheckpointStore('oas1', root=Path(folder))
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                '{"schema_version": 2, "account": "oas1", "target_level": 59}',
                encoding='utf-8',
            )

            checkpoint = store.load()
            self.assertEqual(checkpoint.revision, 0)
            self.assertEqual(checkpoint.run_id, '')
            store.save(checkpoint)
            self.assertEqual(checkpoint.schema_version, 3)
            self.assertEqual(checkpoint.revision, 1)

    def test_cross_process_lock_has_bounded_timeout(self):
        with tempfile.TemporaryDirectory() as folder:
            code = (
                'import sys,time; '
                'from pathlib import Path; '
                'from tasks.RealmRaid.level_mode import CheckpointStore; '
                'store=CheckpointStore("oas1", root=Path(sys.argv[1])); '
                'ctx=store._locked(); ctx.__enter__(); '
                'print("locked", flush=True); time.sleep(2); ctx.__exit__(None,None,None)'
            )
            process = subprocess.Popen(
                [sys.executable, '-c', code, folder],
                cwd=Path(__file__).resolve().parents[3],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(process.stdout.readline().strip(), 'locked')
                store = CheckpointStore('oas1', root=Path(folder), lock_timeout=0.1)
                checkpoint = create_checkpoint('oas1', board(), 59, LevelMode.HOLD)
                with self.assertRaises(CheckpointLockTimeout):
                    store.save(checkpoint)
            finally:
                process.terminate()
                process.communicate(timeout=5)

    def test_unique_temporary_file_is_removed_after_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CheckpointStore('oas1', root=root)
            store.save(create_checkpoint('oas1', board(), 59, LevelMode.HOLD))

            self.assertEqual(list(root.glob('*.tmp.*')), [])

    def test_failed_atomic_replace_does_not_advance_in_memory_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CheckpointStore('oas1', root=root)
            checkpoint = create_checkpoint('oas1', board(), 59, LevelMode.HOLD)

            with patch(
                'tasks.RealmRaid.level_mode.os.replace',
                side_effect=OSError('simulated replace failure'),
            ):
                with self.assertRaises(OSError):
                    store.save(checkpoint)

            self.assertEqual(checkpoint.revision, 0)
            self.assertEqual(checkpoint.run_id, '')
            self.assertFalse(store.path.exists())
            self.assertEqual(list(root.glob('*.tmp.*')), [])


if __name__ == '__main__':
    unittest.main()
