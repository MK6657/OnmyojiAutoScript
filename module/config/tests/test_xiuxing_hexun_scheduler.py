import unittest
from unittest.mock import patch

from module.config.config import Config, Function
from module.config.scheduler import TaskScheduler


class XiuxingHexunSchedulerTest(unittest.TestCase):
    def test_activity_task_survives_priority_filter(self):
        config = Config("oas1")
        task = Function(
            "xiuxing_hexun",
            config.model.xiuxing_hexun.model_dump(),
        )
        task.next_run = task.next_run.replace(year=2023)
        scheduled = TaskScheduler.schedule(
            config.model.script.optimization.schedule_rule,
            [task],
        )
        self.assertEqual([item.command for item in scheduled], ["XiuxingHexun"])

    def test_account_activity_switch_removes_task_from_scheduler(self):
        config = Config("oas1")
        config.model.xiuxing_hexun.activity_enabled = False
        config.model.xiuxing_hexun.scheduler.enable = True

        config.update_scheduler()

        scheduled = config.pending_task + config.waiting_task
        self.assertNotIn("XiuxingHexun", [item.command for item in scheduled])

    def test_global_activity_switch_removes_task_from_scheduler(self):
        config = Config("oas1")
        config.model.xiuxing_hexun.activity_enabled = True
        config.model.xiuxing_hexun.scheduler.enable = True

        with patch.dict("os.environ", {"OAS_XIUXING_HEXUN_ENABLED": "0"}):
            config.update_scheduler()

        scheduled = config.pending_task + config.waiting_task
        self.assertNotIn("XiuxingHexun", [item.command for item in scheduled])


if __name__ == "__main__":
    unittest.main()
