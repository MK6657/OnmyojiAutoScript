import unittest

import numpy as np

from module.device.method.nemu_ipc import NemuIpc, NemuIpcImpl


class NemuContractTest(unittest.TestCase):
    def test_resolution_is_reused_until_explicitly_invalidated(self):
        ipc = object.__new__(NemuIpcImpl)
        ipc.width = 1280
        ipc.height = 720
        ipc._resolution_valid = True
        ipc.connect_id = 1

        def unexpected_resolution_call(*_args, **_kwargs):
            raise AssertionError('cached resolution should not call IPC')

        ipc.ev_run_sync = unexpected_resolution_call

        self.assertEqual(ipc.get_resolution(), (1280, 720))
        ipc.invalidate_resolution('test')
        self.assertFalse(ipc._resolution_valid)
        self.assertEqual((ipc.width, ipc.height), (0, 0))

    def test_rgba_sentinel_is_published_as_rgb_after_vertical_flip(self):
        class FakeIpc:
            @staticmethod
            def screenshot():
                return np.array(
                    [
                        [[10, 20, 30, 255]],
                        [[40, 50, 60, 255]],
                    ],
                    dtype=np.uint8,
                )

        class Harness:
            nemu_ipc = FakeIpc()

        image = NemuIpc.screenshot_nemu_ipc(Harness())

        self.assertEqual(image.shape, (2, 1, 3))
        np.testing.assert_array_equal(image[0, 0], [40, 50, 60])
        np.testing.assert_array_equal(image[1, 0], [10, 20, 30])


if __name__ == '__main__':
    unittest.main()
