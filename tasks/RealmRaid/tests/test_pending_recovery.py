import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from tasks.RealmRaid.level_mode import (
    BoardSnapshot,
    LevelAction,
    LevelMode,
    PendingAction,
    create_checkpoint,
)
from tasks.RealmRaid.config import RealmRaid
from tasks.RealmRaid.script_task import ScriptTask


def board(broken=(), failed=(), tickets=15, record=2, signature='board-a'):
    return BoardSnapshot(
        levels=(58,) * 9,
        challenge_level=58,
        challenge_level_votes=9,
        broken=frozenset(broken),
        failure_marked=frozenset(failed),
        attack_record=record,
        tickets_current=tickets,
        tickets_total=30,
        refresh_available=True,
        layout_signature=signature,
        captured_at=datetime(2026, 8, 1, 21, 0, 0),
    )


class FakeStore:
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint
        self.cleared = False

    def save(self, checkpoint):
        self.checkpoint = checkpoint
        self.cleared = False

    def load(self):
        return None if self.cleared else self.checkpoint

    def clear(self):
        self.cleared = True
        self.checkpoint = None


class ObserveHarness:
    pending_snapshot_confirms_same_board = staticmethod(
        ScriptTask.pending_snapshot_confirms_same_board
    )

    def __init__(self, strict_snapshot, trusted_snapshot):
        self.strict_snapshot = strict_snapshot
        self.trusted_snapshot = trusted_snapshot
        self.trust_flags = []
        self.dumped = []

    def wait_level_board(self, timeout=20):
        return True

    def build_level_board_snapshot(
        self,
        screenshot=True,
        expected_level=0,
        expected_board_signature='',
        trust_expected_level=False,
        level_cache=None,
    ):
        self.trust_flags.append(trust_expected_level)
        return self.trusted_snapshot if trust_expected_level else self.strict_snapshot

    def dump_board(self, label):
        self.dumped.append(label)


class AutoRefreshHarness:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.dumped = []

    def wait_level_generation_change(
        self,
        before,
        timeout=25,
        level_cache=None,
    ):
        self.calls.append((before, timeout, level_cache))
        return self.result

    def dump_board(self, label):
        self.dumped.append(label)


class FinishHarness:
    level_action_limit = staticmethod(ScriptTask.level_action_limit)

    def __init__(self):
        self.finishes = []

    def finish_level_mode(self, success, target=None, reason=''):
        self.finishes.append((success, target, reason))


class LevelModeFinished(Exception):
    pass


class RunLoopHarness:
    level_action_limit = staticmethod(ScriptTask.level_action_limit)
    level_transaction_safety_cap = staticmethod(
        ScriptTask.level_transaction_safety_cap
    )
    level_ticket_stop_reason = staticmethod(ScriptTask.level_ticket_stop_reason)

    def __init__(self, initial):
        self.config = SimpleNamespace(config_name='oas1')
        self.initial = initial
        self.actions = []
        self.finishes = []
        self.generation = 1

    def observe_level_board(self, **kwargs):
        return self.initial

    def recover_pending_level_action(self, checkpoint, snapshot, store):
        return None

    def execute_level_surrender(self, snapshot, checkpoint, store, battle_config):
        self.actions.append(LevelAction.SURRENDER)
        checkpoint.failure_count += 1
        after = board(
            broken=snapshot.broken,
            failed=(1,),
            tickets=snapshot.tickets_current,
            record=snapshot.success_count,
            signature=snapshot.layout_signature,
        )
        checkpoint.remember_board(after)
        checkpoint.finish_action()
        store.save(checkpoint)
        return after

    def execute_level_attack(self, snapshot, checkpoint, store, battle_config):
        self.actions.append(LevelAction.ATTACK)
        success_count = snapshot.success_count + 1
        after = board(
            broken=range(1, success_count + 1),
            failed=snapshot.failure_marked,
            tickets=snapshot.tickets_current - 1,
            record=success_count,
            signature=snapshot.layout_signature,
        )
        checkpoint.success_count = success_count
        checkpoint.remember_board(after)
        checkpoint.finish_action()
        store.save(checkpoint)
        return after

    def confirm_level_auto_refresh(self, snapshot, checkpoint, store):
        self.actions.append(LevelAction.WAIT_AUTO_REFRESH)
        self.generation += 1
        after = board(
            broken=(),
            failed=(),
            tickets=snapshot.tickets_current,
            record=0,
            signature=f'board-{self.generation}',
        )
        store.clear()
        return after

    def finish_level_test_step(self, config, action, transaction_count, store):
        return None

    def finish_level_mode(self, success, target=None, reason=''):
        self.finishes.append((success, target, reason))
        raise LevelModeFinished

    def dump_board(self, label):
        raise AssertionError(f'unexpected unsafe board: {label}')


class PendingRecoveryTest(unittest.TestCase):
    def checkpoint(self, snapshot, target=9):
        checkpoint = create_checkpoint('oas1', snapshot, 58, LevelMode.HOLD)
        checkpoint.failure_count = 4
        checkpoint.begin_action(PendingAction.ATTACK, snapshot, target=target)
        checkpoint.pending_stage = 'battle'
        return checkpoint

    def test_single_step_is_explicit_and_production_has_no_batch_limit(self):
        config = RealmRaid()
        self.assertFalse(config.level_mode_config.single_step)

        config.level_mode_config.single_step = True
        self.assertEqual(ScriptTask.level_action_limit(config), 1)

        config.level_mode_config.single_step = False
        self.assertIsNone(ScriptTask.level_action_limit(config))

    def test_production_does_not_finish_at_the_old_thirteen_action_boundary(self):
        config = RealmRaid()
        config.level_mode_config.single_step = False
        harness = FinishHarness()

        ScriptTask.finish_level_test_step(
            harness,
            config,
            LevelAction.ATTACK,
            13,
            FakeStore(None),
        )

        self.assertEqual(harness.finishes, [])

    def test_single_step_still_pauses_after_one_committed_action(self):
        config = RealmRaid()
        config.level_mode_config.single_step = True
        harness = FinishHarness()

        ScriptTask.finish_level_test_step(
            harness,
            config,
            LevelAction.SURRENDER,
            1,
            FakeStore(None),
        )

        self.assertEqual(harness.finishes, [(False, None, 'test_paused')])

    def test_ticket_budget_uses_spent_tickets_not_battle_attempts(self):
        config = RealmRaid()
        config.raid_config.number_base = 0
        config.raid_config.number_attack = 2

        self.assertEqual(
            ScriptTask.level_ticket_stop_reason(board(tickets=15), config, 17),
            'ticket_spend_limit_reached',
        )
        self.assertEqual(
            ScriptTask.level_ticket_stop_reason(board(tickets=16), config, 17),
            '',
        )

    def test_ticket_reserve_is_the_normal_business_finish_boundary(self):
        config = RealmRaid()
        config.raid_config.number_base = 3

        self.assertEqual(
            ScriptTask.level_ticket_stop_reason(board(tickets=3), config, 17),
            'ticket_reserve_reached',
        )

    def test_transaction_watchdog_covers_full_thirty_ticket_hold_flow(self):
        config = RealmRaid()
        config.raid_config.number_attack = 30

        # Four hold boards can require 16 surrenders plus 30 wins.
        self.assertGreaterEqual(ScriptTask.level_transaction_safety_cap(config), 46)

    def test_recoverable_level_error_uses_short_retry_not_daily_schedule(self):
        before = datetime.now()
        due = ScriptTask.level_short_retry_target()
        delay = (due - before).total_seconds()

        self.assertGreaterEqual(delay, 299)
        self.assertLessEqual(delay, 301)
        self.assertEqual(due.date(), before.date())

    def test_run_level_mode_crosses_board_and_drains_remaining_tickets(self):
        config = RealmRaid()
        config.level_mode_config.target_level = 58
        config.level_mode_config.single_step = False
        config.raid_config.number_base = 0
        config.raid_config.number_attack = 30
        store = FakeStore(None)
        harness = RunLoopHarness(board(tickets=10, record=0, signature='board-1'))

        with patch('tasks.RealmRaid.script_task.CheckpointStore', return_value=store):
            with self.assertRaises(LevelModeFinished):
                ScriptTask.run_level_mode(harness, config)

        self.assertEqual(harness.actions.count(LevelAction.SURRENDER), 8)
        self.assertEqual(harness.actions.count(LevelAction.ATTACK), 10)
        self.assertEqual(
            harness.actions.count(LevelAction.WAIT_AUTO_REFRESH),
            1,
        )
        self.assertEqual(
            harness.finishes,
            [(True, None, 'ticket_reserve_reached')],
        )

    def test_attack_record_ocr_does_not_accept_low_confidence_digit_rescue(self):
        task = object.__new__(ScriptTask)
        rule = task.attack_record_ocr

        self.assertEqual(rule.min_score, rule.score)

    def test_attack_record_ocr_preserves_empty_as_unknown(self):
        task = object.__new__(ScriptTask)
        rule = task.attack_record_ocr

        with patch.object(rule, 'ocr_single', return_value=None):
            self.assertIsNone(rule.ocr(None))

    def test_attack_record_ocr_rejects_non_digit_garbage_as_unknown(self):
        task = object.__new__(ScriptTask)
        rule = task.attack_record_ocr

        self.assertIsNone(rule.after_process('z'))

    def test_committed_attack_is_recovered_before_signature_validation(self):
        before = board(broken=(3, 6), tickets=15, record=2, signature='board-a')
        checkpoint = self.checkpoint(before)
        store = FakeStore(checkpoint)
        after = board(broken=(3, 6, 9), tickets=14, record=3, signature='board-b')

        recovered = ScriptTask.recover_pending_level_action(
            object(), checkpoint, after, store
        )

        self.assertTrue(recovered)
        self.assertEqual(checkpoint.failure_count, 4)
        self.assertEqual(checkpoint.success_count, 3)
        self.assertEqual(checkpoint.board_signature, 'board-b')
        self.assertEqual(checkpoint.pending_action, PendingAction.NONE.value)

    def test_inconclusive_pending_attack_is_preserved(self):
        before = board(broken=(3, 6), tickets=15, record=2, signature='board-a')
        checkpoint = self.checkpoint(before)
        store = FakeStore(checkpoint)
        after = board(broken=(3, 6), tickets=15, record=2, signature='board-b')

        recovered = ScriptTask.recover_pending_level_action(
            object(), checkpoint, after, store
        )

        self.assertFalse(recovered)
        self.assertEqual(checkpoint.failure_count, 4)
        self.assertEqual(checkpoint.pending_action, PendingAction.ATTACK.value)
        self.assertFalse(store.cleared)

    def test_ambiguous_failed_attack_on_same_board_is_cleared_for_safe_replay(self):
        before = board(failed=(4,), tickets=5, record=0, signature='board-a')
        checkpoint = self.checkpoint(before, target=4)
        checkpoint.pending_failure_marked_before = True
        store = FakeStore(checkpoint)
        after = board(failed=(4,), tickets=5, record=0, signature='board-a')

        recovered = ScriptTask.recover_pending_level_action(
            object(), checkpoint, after, store
        )

        self.assertTrue(recovered)
        self.assertEqual(checkpoint.pending_action, PendingAction.NONE.value)
        self.assertEqual(checkpoint.pending_stage, 'none')
        self.assertEqual(checkpoint.failure_count, 4)
        self.assertFalse(store.cleared)

    def test_pre_battle_pending_attack_is_cleared_for_safe_replay(self):
        before = board(broken=(3, 6), tickets=15, record=2, signature='board-a')
        checkpoint = self.checkpoint(before)
        checkpoint.pending_stage = 'selection'
        store = FakeStore(checkpoint)
        after = board(broken=(3, 6), tickets=15, record=2, signature='board-a')

        recovered = ScriptTask.recover_pending_level_action(
            object(), checkpoint, after, store
        )

        self.assertTrue(recovered)
        self.assertEqual(checkpoint.pending_action, PendingAction.NONE.value)
        self.assertEqual(checkpoint.pending_stage, 'none')
        self.assertFalse(store.cleared)

    def test_pending_attack_with_broken_target_but_no_ticket_spend_is_ambiguous(self):
        before = board(broken=(3, 6), tickets=15, record=2, signature='board-a')
        checkpoint = self.checkpoint(before, target=9)
        store = FakeStore(checkpoint)
        after = board(broken=(3, 6, 9), tickets=15, record=3, signature='board-b')

        recovered = ScriptTask.recover_pending_level_action(
            object(), checkpoint, after, store
        )

        self.assertFalse(recovered)
        self.assertEqual(checkpoint.pending_action, PendingAction.ATTACK.value)
        self.assertFalse(store.cleared)

    def test_ticket_increase_discards_stale_pending_action(self):
        before = board(broken=(3, 6), tickets=4, record=2, signature='board-a')
        checkpoint = self.checkpoint(before)
        store = FakeStore(checkpoint)
        after = board(broken=(), tickets=13, record=0, signature='board-b')

        recovered = ScriptTask.recover_pending_level_action(
            object(), checkpoint, after, store
        )

        self.assertTrue(recovered)
        self.assertTrue(store.cleared)
        self.assertIsNone(store.load())

    def test_ambiguous_repeated_surrender_is_cleared_for_safe_replay(self):
        before = board(failed=(1,), tickets=15, record=0, signature='board-a')
        checkpoint = create_checkpoint('oas1', before, 58, LevelMode.HOLD)
        checkpoint.failure_count = 2
        checkpoint.begin_action(PendingAction.SURRENDER, before, target=1)
        store = FakeStore(checkpoint)
        after = board(failed=(1,), tickets=15, record=0, signature='board-b')

        recovered = ScriptTask.recover_pending_level_action(
            object(), checkpoint, after, store
        )

        self.assertTrue(recovered)
        self.assertEqual(checkpoint.failure_count, 2)
        self.assertEqual(checkpoint.pending_action, PendingAction.NONE.value)
        self.assertFalse(store.cleared)

    def test_confirmed_defeat_ignores_signature_only_generation_drift(self):
        before = board(tickets=15, record=0, signature='board-a')
        after = board(failed=(1,), tickets=15, record=0, signature='board-b')

        self.assertFalse(
            ScriptTask.level_attack_generation_changed(before, after, won=False)
        )
        self.assertTrue(
            ScriptTask.level_attack_generation_changed(
                board(
                    broken=range(1, 9),
                    tickets=7,
                    record=8,
                    signature='board-a',
                ),
                board(tickets=6, record=0, signature='board-new'),
                won=True,
            )
        )

    def test_ninth_win_auto_refresh_clears_old_generation(self):
        before = board(
            broken=range(1, 9),
            tickets=7,
            record=8,
            signature='board-a',
        )
        checkpoint = self.checkpoint(before, target=9)
        store = FakeStore(checkpoint)
        after = board(broken=(), tickets=6, record=0, signature='board-new')

        recovered = ScriptTask.recover_pending_level_action(
            object(), checkpoint, after, store
        )

        self.assertTrue(recovered)
        self.assertTrue(store.cleared)

    def test_sixth_win_confirms_same_board_despite_signature_drift(self):
        before = board(
            broken=(3, 5, 6, 8, 9),
            tickets=12,
            record=5,
            signature='board-a',
        )
        checkpoint = self.checkpoint(before, target=2)
        after = board(
            broken=(2, 3, 5, 6, 8, 9),
            tickets=11,
            record=6,
            signature='board-b',
        )

        self.assertTrue(
            ScriptTask.pending_snapshot_confirms_same_board(checkpoint, after)
        )

    def test_ninth_win_auto_refresh_is_not_treated_as_same_board(self):
        before = board(
            broken=range(1, 9),
            tickets=7,
            record=8,
            signature='board-a',
        )
        checkpoint = self.checkpoint(before, target=9)
        after = board(broken=(), tickets=6, record=0, signature='board-new')

        self.assertFalse(
            ScriptTask.pending_snapshot_confirms_same_board(checkpoint, after)
        )

    def test_confirmed_auto_refresh_clears_old_checkpoint(self):
        before = board(
            broken=range(1, 10),
            tickets=6,
            record=9,
            signature='board-a',
        )
        after = board(broken=(), tickets=6, record=0, signature='board-new')
        checkpoint = create_checkpoint('oas1', before, 58, LevelMode.HOLD)
        store = FakeStore(checkpoint)
        harness = AutoRefreshHarness(after)

        result = ScriptTask.confirm_level_auto_refresh(
            harness,
            before,
            checkpoint,
            store,
        )

        self.assertIs(result, after)
        self.assertTrue(store.cleared)
        self.assertEqual(harness.calls, [(before, 25, checkpoint)])

    def test_auto_refresh_timeout_preserves_checkpoint(self):
        before = board(
            broken=range(1, 10),
            tickets=6,
            record=9,
            signature='board-a',
        )
        checkpoint = create_checkpoint('oas1', before, 58, LevelMode.HOLD)
        store = FakeStore(checkpoint)
        harness = AutoRefreshHarness(None)

        result = ScriptTask.confirm_level_auto_refresh(
            harness,
            before,
            checkpoint,
            store,
        )

        self.assertIsNone(result)
        self.assertFalse(store.cleared)
        self.assertEqual(harness.dumped, ['auto_refresh_timeout'])

    def test_observer_never_imputes_missing_levels_from_checkpoint(self):
        before = board(
            broken=(3, 5, 6, 8, 9),
            tickets=12,
            record=5,
            signature='board-a',
        )
        checkpoint = self.checkpoint(before, target=2)
        broken = frozenset((2, 3, 5, 6, 8, 9))
        strict = BoardSnapshot(
            levels=(58, 0, 0, 58, 0, 0, 60, 0, 0),
            challenge_level=58,
            challenge_level_votes=2,
            broken=broken,
            attack_record=6,
            tickets_current=11,
            tickets_total=30,
            refresh_available=True,
            layout_signature='board-b',
        )
        trusted = BoardSnapshot(
            levels=(58, 58, 58, 58, 58, 58, 60, 58, 58),
            challenge_level=58,
            challenge_level_votes=8,
            broken=broken,
            attack_record=6,
            tickets_current=11,
            tickets_total=30,
            refresh_available=True,
            layout_signature='board-b',
            imputed=broken,
        )
        harness = ObserveHarness(strict, trusted)

        observed = ScriptTask.observe_level_board(
            harness,
            retries=1,
            expected_level=58,
            expected_board_signature='board-a',
            pending_checkpoint=checkpoint,
        )

        self.assertIs(observed, strict)
        self.assertEqual(harness.trust_flags, [False])
        self.assertEqual(harness.dumped, ['unsafe'])


if __name__ == '__main__':
    unittest.main()
