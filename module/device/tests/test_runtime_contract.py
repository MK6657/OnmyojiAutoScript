import unittest
from types import SimpleNamespace
from unittest.mock import patch

from module.device.control import Control
from module.device.device import Device
from module.device.handle import resolve_root_handle


class RuntimeDeviceContractTest(unittest.TestCase):
    @staticmethod
    def new_device():
        device = object.__new__(Device)
        device.frame_id = 0
        device._image = None
        device._last_frame_published_at = None
        device._recognition_cache = {}
        device._recognition_cache_generation = 0
        return device

    def test_frame_id_increments_and_cache_is_cleared_for_new_frames(self):
        device = self.new_device()
        device.recognition_cache_set(('rule',), 'old')

        device.publish_frame()

        self.assertEqual(device.frame_id, 1)
        self.assertEqual(device.recognition_cache_get(('rule',)), (False, None))

        device.publish_frame()
        self.assertEqual(device.frame_id, 2)

    def test_replacing_image_invalidates_cache(self):
        device = self.new_device()
        device.recognition_cache_set(('rule',), 'old')

        device.image = object()

        self.assertEqual(device.recognition_cache_get(('rule',)), (False, None))

    def test_release_during_wait_uses_current_device_field(self):
        device = self.new_device()
        device.config = SimpleNamespace(
            script=SimpleNamespace(
                device=SimpleNamespace(screenshot_method='nemu_ipc')
            )
        )
        released = []
        device.nemu_ipc_release = lambda: released.append(True)

        Device.release_during_wait(device)

        self.assertEqual(released, [True])


class ControlContractHarness(Control):
    def __init__(self):
        self.config = SimpleNamespace(
            script=SimpleNamespace(
                device=SimpleNamespace(control_method='adb')
            )
        )
        self.drag_calls = []

    def handle_control_check(self, _name):
        return None

    def invalidate_recognition_cache(self, _reason):
        return None

    def swipe_adb(self, p1, p2, duration=0.1):
        self.drag_calls.append((p1, p2, duration))


class ControlContractTest(unittest.TestCase):
    def test_click_dispatch_accepts_lowercase_and_legacy_uppercase_adb(self):
        harness = ControlContractHarness()

        self.assertEqual(harness.click_methods['adb'], harness.click_methods['ADB'])
        self.assertEqual(harness.long_click_methods['adb'], harness.long_click_methods['ADB'])

    def test_drag_reads_device_control_method(self):
        harness = ControlContractHarness()

        Control.drag(harness, (10, 10), (100, 100))

        self.assertEqual(len(harness.drag_calls), 1)


class WindowHandleResolutionTest(unittest.TestCase):
    @patch('module.device.handle.handle_num2title', return_value='window-by-hwnd')
    @patch('module.device.handle.handle_title2num', return_value=1442486)
    @patch('module.device.handle.is_handle_valid', return_value=False)
    def test_invalid_numeric_hwnd_falls_back_to_exact_title(
        self,
        _valid,
        title_to_num,
        num_to_title,
    ):
        title, hwnd, source = resolve_root_handle('2301')

        self.assertEqual((title, hwnd, source), ('2301', 1442486, 'title'))
        title_to_num.assert_called_once_with('2301')
        num_to_title.assert_not_called()

    @patch('module.device.handle.handle_num2title', return_value='window-by-hwnd')
    @patch('module.device.handle.handle_title2num')
    @patch('module.device.handle.is_handle_valid', return_value=True)
    def test_valid_numeric_hwnd_remains_supported(
        self,
        _valid,
        title_to_num,
        _num_to_title,
    ):
        title, hwnd, source = resolve_root_handle('2301')

        self.assertEqual((title, hwnd, source), ('window-by-hwnd', 2301, 'hwnd'))
        title_to_num.assert_not_called()


if __name__ == '__main__':
    unittest.main()
