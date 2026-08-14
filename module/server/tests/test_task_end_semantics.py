import unittest

from module.exception import TaskEnd


class TaskEndSemanticsTest(unittest.TestCase):
    def test_default_task_end_is_not_success(self):
        error = TaskEnd()

        self.assertEqual(error.outcome, "aborted")
        self.assertFalse(error.success)
        self.assertEqual(error.statistics, {})

    def test_completed_task_end_is_explicit_success(self):
        error = TaskEnd.completed(
            "scheduled normally",
            statistics={"battles": 3},
            next_run="2026-08-10T09:00:00",
        )

        self.assertEqual(error.outcome, "returned")
        self.assertTrue(error.success)
        self.assertEqual(error.reason, "scheduled normally")
        self.assertEqual(error.statistics, {"battles": 3})
        self.assertEqual(error.next_run, "2026-08-10T09:00:00")


if __name__ == "__main__":
    unittest.main()
