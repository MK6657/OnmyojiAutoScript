import unittest

from tasks.Component.GeneralBattle.general_battle import GeneralBattle


class AutoModeHarness:
    _ensure_auto_battle_mode = GeneralBattle._ensure_auto_battle_mode
    _click_battle_mode_safe = GeneralBattle._click_battle_mode_safe
    _click_battle_mode_adb_fallback = GeneralBattle._click_battle_mode_adb_fallback
    _auto_mode_capture_interval = GeneralBattle._auto_mode_capture_interval
    _capture_auto_mode_frame = GeneralBattle._capture_auto_mode_frame
    _observe_stable_battle_mode = GeneralBattle._observe_stable_battle_mode
    AUTO_MODE_SETTLE_DELAY = 0.0
    AUTO_MODE_LOCKED_SETTLE_DELAY = 0.0
    AUTO_MODE_VERIFY_SETTLE_DELAY = 0.0
    AUTO_MODE_SAMPLE_INTERVAL = 0.001
    AUTO_MODE_STABLE_SAMPLES = 2

    class Device:
        def __init__(self, control_method='minitouch', adb_fallback=False):
            self.image = None
            self.clicks = []
            self.adb_clicks = []
            self.config = type(
                'Config',
                (),
                {
                    'script': type(
                        'Script',
                        (),
                        {
                            'device': type(
                                'DeviceConfig',
                                (),
                                {'control_method': control_method},
                            )(),
                        },
                    )(),
                },
            )()
            self.adb_fallback = adb_fallback

        def click(self, **kwargs):
            self.clicks.append(kwargs)

        def click_adb(self, x, y):
            self.adb_clicks.append((x, y))

    def __init__(self, states, control_method='minitouch', adb_fallback=False):
        self.states = list(states)
        self.device = self.Device(control_method, adb_fallback)
        self.screenshot_count = 0

    def _read_battle_mode(self):
        if self.states:
            return self.states.pop(0)
        return None

    def screenshot(self):
        self.screenshot_count += 1
        if self.device.adb_fallback and self.device.adb_clicks:
            self.states.append('auto')


class AutoModeTest(unittest.TestCase):
    def test_auto_mode_does_not_click(self):
        harness = AutoModeHarness(['auto', 'auto'])

        self.assertTrue(harness._ensure_auto_battle_mode())
        self.assertEqual(harness.device.clicks, [])

    def test_manual_mode_toggles_once_and_confirms_auto(self):
        harness = AutoModeHarness(['manual', 'manual', 'auto', 'auto'])

        self.assertTrue(harness._ensure_auto_battle_mode())
        self.assertEqual(len(harness.device.clicks), 1)
        click = harness.device.clicks[0]
        self.assertEqual(click['control_name'], 'GB_AUTO_MODE_TOGGLE')
        self.assertGreaterEqual(click['x'], 40)
        self.assertLess(click['x'], 82)
        self.assertGreaterEqual(click['y'], 642)
        self.assertLess(click['y'], 678)

    def test_failed_toggle_is_bounded_and_does_not_repeat_click(self):
        harness = AutoModeHarness(['manual', 'manual', 'manual', 'manual'])

        self.assertFalse(
            harness._ensure_auto_battle_mode(
                detect_timeout=0.5,
                verify_timeout=0.2,
            )
        )
        self.assertEqual(len(harness.device.clicks), 1)

    def test_minitouch_failure_uses_one_adb_fallback(self):
        harness = AutoModeHarness(
            ['manual', 'manual', 'manual', 'manual'],
            control_method='minitouch',
            adb_fallback=True,
        )

        self.assertTrue(
            harness._ensure_auto_battle_mode(
                detect_timeout=0.5,
                verify_timeout=0.2,
            )
        )
        self.assertEqual(len(harness.device.clicks), 1)
        self.assertEqual(len(harness.device.adb_clicks), 1)

    def test_adb_mode_does_not_double_click_after_failed_verification(self):
        harness = AutoModeHarness(
            ['manual', 'manual', 'manual', 'manual'],
            control_method='adb',
            adb_fallback=True,
        )

        self.assertFalse(
            harness._ensure_auto_battle_mode(
                detect_timeout=0.5,
                verify_timeout=0.2,
            )
        )
        self.assertEqual(len(harness.device.clicks), 1)
        self.assertEqual(harness.device.adb_clicks, [])

    def test_unknown_mode_is_bounded_without_blind_click(self):
        harness = AutoModeHarness([])

        self.assertFalse(
            harness._ensure_auto_battle_mode(
                detect_timeout=0,
                verify_timeout=0,
            )
        )
        self.assertEqual(harness.device.clicks, [])

    def test_stale_first_manual_frame_is_not_clicked(self):
        harness = AutoModeHarness(['manual', 'auto', 'auto'])

        self.assertTrue(harness._ensure_auto_battle_mode())
        self.assertEqual(harness.device.clicks, [])

    def test_locked_auto_start_transition_is_not_clicked(self):
        harness = AutoModeHarness(['manual', 'auto', 'auto'])
        harness._battle_lock_expected_active = True

        self.assertTrue(harness._ensure_auto_battle_mode())
        self.assertEqual(harness.device.clicks, [])

    def test_manual_requires_two_fresh_frames_before_click(self):
        harness = AutoModeHarness(['manual', 'manual', 'auto', 'auto'])

        self.assertTrue(harness._ensure_auto_battle_mode())
        self.assertEqual(len(harness.device.clicks), 1)

    def test_stale_manual_after_click_does_not_trigger_adb_fallback(self):
        harness = AutoModeHarness(
            ['manual', 'manual', 'manual', 'auto', 'auto'],
            control_method='minitouch',
            adb_fallback=True,
        )

        self.assertTrue(harness._ensure_auto_battle_mode())
        self.assertEqual(len(harness.device.clicks), 1)
        self.assertEqual(harness.device.adb_clicks, [])


if __name__ == '__main__':
    unittest.main()
