import unittest
from types import SimpleNamespace

from tasks.Exploration.base import BaseExploration


class ExplorationCountLimitTest(unittest.TestCase):
    def test_count_limit_is_reached_at_configured_battle_count(self):
        task = SimpleNamespace(
            minions_cnt=30,
            _config=SimpleNamespace(
                exploration_config=SimpleNamespace(minions_cnt=30),
            ),
        )

        self.assertTrue(BaseExploration.battle_limit_reached(task))

    def test_count_limit_is_not_reached_before_configured_battle_count(self):
        task = SimpleNamespace(
            minions_cnt=29,
            _config=SimpleNamespace(
                exploration_config=SimpleNamespace(minions_cnt=30),
            ),
        )

        self.assertFalse(BaseExploration.battle_limit_reached(task))


if __name__ == '__main__':
    unittest.main()
