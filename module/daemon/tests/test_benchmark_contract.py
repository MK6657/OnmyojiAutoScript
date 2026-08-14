import unittest
from types import SimpleNamespace

import numpy as np

from module.daemon.benchmark import Benchmark


class BenchmarkContractTest(unittest.TestCase):
    def test_generic_run_reads_screenshot_method_from_config(self):
        benchmark = object.__new__(Benchmark)

        class Config:
            Benchmark_DeviceType = 'emulator'
            Benchmark_TestScene = 'all'

            def __init__(self):
                self.script = SimpleNamespace(
                    device=SimpleNamespace(screenshot_method='ADB')
                )
                self.override_value = None

            def override(self, value):
                self.override_value = value

        class Device:
            def __init__(self):
                self.uninstalled = False

            def uninstall_minicap(self):
                self.uninstalled = True

        benchmark.config = Config()
        benchmark.device = Device()
        benchmark.get_test_methods = lambda: ((), ())
        benchmark.benchmark = lambda *_args, **_kwargs: None

        benchmark.run()

        self.assertTrue(benchmark.config.override_value)
        self.assertTrue(benchmark.device.uninstalled)

    def test_benchmark_reports_p50_and_p95_after_warmup(self):
        benchmark = object.__new__(Benchmark)
        counter = {'value': 0}

        def sample():
            counter['value'] += 1
            return counter['value']

        result = benchmark.benchmark_test(sample, label='sample')

        self.assertIsInstance(result, float)
        self.assertEqual(counter['value'], Benchmark.WARMUP_TOTAL + Benchmark.TEST_TOTAL)
        self.assertEqual(benchmark.last_metrics['sample']['warmup'], 5)
        self.assertEqual(benchmark.last_metrics['sample']['samples'], 30)
        self.assertLessEqual(
            benchmark.last_metrics['sample']['p50'],
            benchmark.last_metrics['sample']['p95'],
        )

    def test_wrong_resolution_cannot_pass_screenshot_contract(self):
        benchmark = object.__new__(Benchmark)
        benchmark.device = type(
            'Device',
            (), {'_handle_orientated_image': staticmethod(lambda image: image)},
        )()

        wrong = np.zeros((502, 892, 3), dtype=np.uint8)
        correct = np.zeros((720, 1280, 3), dtype=np.uint8)

        self.assertFalse(benchmark._valid_screenshot_frame(wrong, 'window_background'))
        self.assertTrue(benchmark._valid_screenshot_frame(correct, 'adb'))


if __name__ == '__main__':
    unittest.main()
