import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from tasks.Hyakkiyakou.config import ScreenshotMethod
from tasks.Hyakkiyakou.slave.hya_device import HyaDevice
from tasks.Hyakkiyakou.utils.fast_device import FastDevice
from tasks.Component.CommonPopup.dispatcher import CommonPopupDispatcher
from tasks.base_task import BaseTask


class _ReadyTimer:
    def wait(self):
        return None

    def reset(self):
        return None

    def reached(self):
        return False


class _Device:
    def __init__(self):
        self.image = None
        self.frame_id = 0
        self.screenshot_deque = []
        self.window_calls = 0

    def screenshot_window_background(self):
        self.window_calls += 1
        return np.full((720, 1280, 3), 32, dtype=np.uint8)

    def publish_frame(self, started_at=None):
        self.frame_id += 1


class HyaProtectedScreenshotTest(unittest.TestCase):
    def test_fast_screenshot_uses_the_shared_protected_entry(self):
        task = object.__new__(HyaDevice)
        task.device = _Device()
        task.config = SimpleNamespace(
            script=SimpleNamespace(error=SimpleNamespace(save_error=False))
        )
        task.hya_screenshot_interval = _ReadyTimer()
        task.hya_fs_check_timer = _ReadyTimer()
        expected = np.full((720, 1280, 3), 64, dtype=np.uint8)

        with patch.object(
            BaseTask,
            'protected_screenshot',
            create=True,
            return_value=expected,
        ) as protected:
            result = task.fast_screenshot(ScreenshotMethod.WINDOW_BACKGROUND)

        self.assertIs(result, expected)
        protected.assert_called_once()
        self.assertEqual(task.device.window_calls, 0)

    def test_clean_fast_frame_is_captured_once_and_published_once(self):
        task = object.__new__(HyaDevice)
        task.device = _Device()
        task.device.serial = '127.0.0.1:16384'
        task.config = SimpleNamespace(
            config_name='test',
            script=SimpleNamespace(
                error=SimpleNamespace(save_error=False),
                device=SimpleNamespace(
                    serial='127.0.0.1:16384',
                    screenshot_method='window_background',
                ),
            ),
        )
        task.hya_screenshot_interval = _ReadyTimer()
        task.hya_fs_check_timer = _ReadyTimer()
        task._common_popup_dispatcher = CommonPopupDispatcher(
            (),
            poll_interval=0,
            evidence_enabled=False,
        )

        result = task.fast_screenshot(ScreenshotMethod.WINDOW_BACKGROUND)

        self.assertIs(result, task.device.image)
        self.assertEqual(task.device.window_calls, 1)
        self.assertEqual(task.device.frame_id, 1)

    def test_utility_fast_device_uses_the_shared_protected_entry(self):
        task = object.__new__(FastDevice)
        task.device = _Device()
        task.config = SimpleNamespace(
            model=SimpleNamespace(
                script=SimpleNamespace(
                    device=SimpleNamespace(
                        screenshot_method=ScreenshotMethod.WINDOW_BACKGROUND,
                    )
                )
            )
        )
        expected = np.full((720, 1280, 3), 96, dtype=np.uint8)

        with patch.object(
            BaseTask,
            'protected_screenshot',
            return_value=expected,
        ) as protected:
            result = task.fast_screenshot()

        self.assertIs(result, expected)
        protected.assert_called_once()
        self.assertEqual(task.device.window_calls, 0)


if __name__ == '__main__':
    unittest.main()
