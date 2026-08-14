import unittest

from script import Script


class FakeConfig:
    def __init__(self):
        self.calls = []

    def task_delay(self, **kwargs):
        self.calls.append(kwargs)
        return object()


class ScriptFailureScheduleTest(unittest.TestCase):
    def test_recoverable_failure_is_delayed_before_returning_to_scheduler(self):
        script = object.__new__(Script)
        script.config = FakeConfig()

        self.assertTrue(
            script._schedule_failure_retry('Exploration', 'unknown startup scene')
        )

        self.assertEqual(len(script.config.calls), 1)
        call = script.config.calls[0]
        self.assertEqual(call['task'], 'Exploration')
        self.assertFalse(call['success'])
        self.assertFalse(call['server'])
        self.assertIn('unknown startup scene', call['reason'])


if __name__ == '__main__':
    unittest.main()
