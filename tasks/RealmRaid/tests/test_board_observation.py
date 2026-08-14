import unittest
from datetime import datetime

from tasks.RealmRaid.level_mode import BoardSnapshot
from tasks.RealmRaid.script_task import ScriptTask


def snapshot(levels):
    return BoardSnapshot(
        levels=levels,
        challenge_level=57,
        challenge_level_votes=6,
        broken=frozenset((2, 3, 5, 6, 8, 9)),
        attack_record=6,
        tickets_current=8,
        tickets_total=30,
        refresh_available=False,
        layout_signature='board-a',
        captured_at=datetime(2026, 8, 5, 15, 49, 45),
    )


class SequenceObserveHarness:
    _same_level_evidence = staticmethod(ScriptTask._same_level_evidence)

    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.calls = 0
        self.dumped = []

    def wait_level_board(self, timeout=20):
        return True

    def build_level_board_snapshot(self, **kwargs):
        self.calls += 1
        return self.snapshots[min(self.calls - 1, len(self.snapshots) - 1)]

    def dump_board(self, label):
        self.dumped.append(label)


class BoardObservationTest(unittest.TestCase):
    def test_transient_ocr_frame_gets_stable_confirmation_tail(self):
        unsafe = snapshot((57, 56, 57, 57, 57, 57, 56, 0, 57))
        safe = snapshot((57, 56, 57, 57, 57, 57, 56, 60, 57))
        harness = SequenceObserveHarness([unsafe, unsafe, safe, safe])

        observed = ScriptTask.observe_level_board(
            harness,
            retries=3,
            stable_reads=2,
        )

        self.assertIs(observed, safe)
        self.assertEqual(harness.calls, 4)
        self.assertEqual(harness.dumped, [])


if __name__ == '__main__':
    unittest.main()
