import unittest
from datetime import datetime
from unittest.mock import patch

from script import PRESET_RETRY_DELAY_SECONDS, Script
from tasks.Component.GeneralBattle.preset_name_selector import PresetLookupError


class FakeConfig:
    def __init__(self):
        self.calls = []

    def task_delay(self, **kwargs):
        self.calls.append(kwargs)


class FakeDevice:
    def screenshot(self):
        return None


class PresetRetryTest(unittest.TestCase):
    def make_script(self):
        script = Script.__new__(Script)
        script.config_name = 'oas1'
        script.__dict__['config'] = FakeConfig()
        script.__dict__['device'] = FakeDevice()
        return script

    def test_preset_retry_is_delayed_without_game_restart(self):
        script = self.make_script()
        error = PresetLookupError('preset not found')
        before = datetime.now()

        with patch('script.load_module', side_effect=error):
            result = script.run('RealmRaid')

        self.assertFalse(result)
        self.assertEqual(len(script.config.calls), 1)
        call = script.config.calls[0]
        self.assertEqual(call['task'], 'RealmRaid')
        self.assertFalse(call['server'])
        self.assertGreaterEqual(
            (call['target'] - before).total_seconds(),
            PRESET_RETRY_DELAY_SECONDS - 2,
        )


if __name__ == '__main__':
    unittest.main()
