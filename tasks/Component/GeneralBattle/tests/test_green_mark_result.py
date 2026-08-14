import unittest

from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.GeneralBattle.config_general_battle import GreenMarkType
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralBattle.green_mark_detector import GreenMarkResult


class GreenResultHarness:
    green_mark = GeneralBattle.green_mark
    I_LOCAL = object()
    C_GREEN_LEFT_1 = GeneralBattleAssets.C_GREEN_LEFT_1
    C_GREEN_LEFT_2 = GeneralBattleAssets.C_GREEN_LEFT_2
    C_GREEN_LEFT_3 = GeneralBattleAssets.C_GREEN_LEFT_3
    C_GREEN_LEFT_4 = GeneralBattleAssets.C_GREEN_LEFT_4
    C_GREEN_LEFT_5 = GeneralBattleAssets.C_GREEN_LEFT_5
    C_GREEN_MAIN = GeneralBattleAssets.C_GREEN_MAIN

    class Device:
        def __init__(self):
            self.clicks = []

        def click(self, x, y, control_name):
            self.clicks.append((x, y, control_name))

    def __init__(self, results):
        self.device = self.Device()
        self.results = iter(results)
        self.observation_histories = []

    def screenshot(self):
        return None

    def _battle_terminal_visible(self):
        return False

    def _read_battle_mode(self):
        return 'auto'

    def is_in_real_battle(self, _screenshot):
        return True

    def appear_then_click(self, *_args, **_kwargs):
        return False

    def _wait_green_marker_confirmation_result(
        self,
        _target,
        timeout,
        observation_history=None,
        auto_mode_preconfirmed=False,
    ):
        self.observation_histories.append(
            (observation_history, auto_mode_preconfirmed)
        )
        return next(self.results)


class GreenMarkResultTest(unittest.TestCase):
    def test_disabled_green_mark_is_skipped(self):
        harness = GreenResultHarness([])

        result = harness.green_mark(False, GreenMarkType.GREEN_LEFT1)

        self.assertEqual(result.status, 'skipped')
        self.assertFalse(result)
        self.assertEqual(harness.device.clicks, [])

    def test_only_confirmed_result_is_truthy(self):
        harness = GreenResultHarness(
            [
                GreenMarkResult(
                    status='confirmed',
                    target='green_left1',
                    marker_point=(200, 250),
                    detector='template:I_GREEN_MARKER',
                    max_score=0.91,
                    frame_sha256='a' * 64,
                    reason='marker inside exclusive target region',
                )
            ]
        )

        result = harness.green_mark(True, GreenMarkType.GREEN_LEFT1)

        self.assertTrue(result)
        self.assertEqual(result.status, 'confirmed')
        self.assertEqual(result.attempts, 1)
        self.assertIsNotNone(result.click_point)
        self.assertEqual(len(harness.device.clicks), 1)

    def test_unconfirmed_clicks_do_not_claim_success(self):
        unconfirmed = GreenMarkResult(
            status='unconfirmed',
            target='green_left1',
            reason='no marker in target region',
        )
        harness = GreenResultHarness([unconfirmed, unconfirmed])

        result = harness.green_mark(True, GreenMarkType.GREEN_LEFT1)

        self.assertFalse(result)
        self.assertEqual(result.status, 'unconfirmed')
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(harness.device.clicks), 2)
        self.assertIs(
            harness.observation_histories[0][0],
            harness.observation_histories[1][0],
        )
        self.assertTrue(harness.observation_histories[0][1])
        self.assertTrue(harness.observation_histories[1][1])

    def test_terminal_result_stops_green_mark_retry_without_claiming_confirmation(self):
        terminal = GreenMarkResult(
            status='terminal',
            target='green_left1',
            reason='battle terminal appeared during green mark confirmation',
        )
        harness = GreenResultHarness([terminal])

        result = harness.green_mark(True, GreenMarkType.GREEN_LEFT1)

        self.assertFalse(result)
        self.assertEqual(result.status, 'terminal')
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(harness.device.clicks), 1)


if __name__ == '__main__':
    unittest.main()
