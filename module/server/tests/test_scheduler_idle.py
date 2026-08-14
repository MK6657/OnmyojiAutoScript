import unittest
from types import SimpleNamespace

from module.config.config import Config
from script import Script


def empty_config():
    config = Config.__new__(Config)
    config.pending_task = []
    config.waiting_task = []
    config.task = SimpleNamespace(command='OldTask')
    config.scheduler_update_dt = None
    config.update_scheduler = lambda: None
    return config


class SchedulerIdleTest(unittest.TestCase):
    def test_empty_queue_returns_none_instead_of_human_takeover(self):
        config = empty_config()

        self.assertIsNone(Config.get_next(config))

    def test_empty_queue_clears_stale_current_task(self):
        config = empty_config()

        Config.get_next(config)

        self.assertIsNone(config.task)

    def test_empty_queue_publishes_empty_schedule(self):
        config = empty_config()

        Config.get_next(config)

        self.assertEqual(
            config.get_schedule_data(),
            {'running': {}, 'pending': [], 'waiting': []},
        )

    def test_script_scheduler_propagates_clean_idle_boundary(self):
        script = Script.__new__(Script)
        script.config = empty_config()
        script.state_queue = None

        self.assertIsNone(Script.get_next_task(script))


if __name__ == '__main__':
    unittest.main()
