import unittest

from module.exception import FailureAction, TaskEnd
from tasks.RyouToppa.script_task import ScriptTask


class RyouOutcomeHarness:
    _end_ryou_task = ScriptTask._end_ryou_task

    def __init__(self):
        self.schedules = []
        self.tomorrow_planned = False

    def plan_tomorrow_ryoutoppa(self):
        self.tomorrow_planned = True

    def set_next_run(self, **kwargs):
        self.schedules.append(kwargs)


class RyouTaskOutcomeTest(unittest.TestCase):
    def test_completed_board_resets_failure_counter(self):
        harness = RyouOutcomeHarness()

        with self.assertRaises(TaskEnd) as caught:
            harness._end_ryou_task(True, 'completed')

        self.assertTrue(harness.tomorrow_planned)
        self.assertEqual(caught.exception.outcome, 'returned')
        self.assertEqual(caught.exception.failure_action, FailureAction.RESET)

    def test_no_ticket_is_deferred_without_counting_failure(self):
        harness = RyouOutcomeHarness()

        with self.assertRaises(TaskEnd) as caught:
            harness._end_ryou_task(False, 'no_ticket')

        self.assertEqual(caught.exception.outcome, 'deferred')
        self.assertEqual(caught.exception.failure_action, FailureAction.PRESERVE)

    def test_battle_failure_increments_failure_counter(self):
        harness = RyouOutcomeHarness()

        with self.assertRaises(TaskEnd) as caught:
            harness._end_ryou_task(False, 'battle_failed')

        self.assertEqual(caught.exception.outcome, 'failed')
        self.assertEqual(caught.exception.failure_action, FailureAction.INCREMENT)


if __name__ == '__main__':
    unittest.main()
