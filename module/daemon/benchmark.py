import time
import typing as t

import numpy as np
from rich.table import Table
from rich.text import Text

from module.base.utils import float2str as float2str_
from module.base.utils import random_rectangle_point
from module.daemon.daemon_base import DaemonBase
from module.config.config import Config
from module.device.device import Device
from module.exception import RequestHumanTakeover
from module.logger import logger


def float2str(n, decimal=3):
    if not isinstance(n, (float, int)):
        return str(n)
    else:
        return float2str_(n, decimal=decimal) + 's'


class Benchmark(DaemonBase):
    WARMUP_TOTAL = 5
    TEST_TOTAL = 30

    def benchmark_test(self, func, *args, validator=None, label=None, **kwargs):
        """
        Args:
            func: Function to test.
            *args: Passes to func.
            **kwargs: Passes to func.

        Returns:
            float: Time cost on average.
        """
        logger.hr(f'Benchmark test', level=2)
        label = label or getattr(func, '__name__', repr(func))
        logger.info(f'Testing function: {label}')
        record = []

        for n in range(1, self.WARMUP_TOTAL + 1):
            try:
                result = func(*args, **kwargs)
                if validator is not None and not validator(result):
                    logger.warning(
                        f'Benchmark warmup rejected contract: {label} warmup={n}'
                    )
                    return 'Failed'
            except RequestHumanTakeover:
                logger.critical('RequestHumanTakeover')
                logger.warning(f'Benchmark warmup failed on func: {label}')
                return 'Failed'
            except Exception as e:
                logger.exception(e)
                logger.warning(f'Benchmark warmup failed on func: {label}')
                return 'Failed'

        for n in range(1, self.TEST_TOTAL + 1):
            start = time.time()

            try:
                result = func(*args, **kwargs)
                if validator is not None and not validator(result):
                    logger.warning(
                        f'Benchmark sample rejected contract: {label} sample={n}'
                    )
                    return 'Failed'
            except RequestHumanTakeover:
                logger.critical('RequestHumanTakeover')
                logger.warning(f'Benchmark tests failed on func: {label}')
                return 'Failed'
            except Exception as e:
                logger.exception(e)
                logger.warning(f'Benchmark tests failed on func: {label}')
                return 'Failed'

            cost = time.time() - start
            logger.attr(
                f'{str(n).rjust(2, "0")}/{self.TEST_TOTAL}',
                f'{float2str(cost)}'
            )
            record.append(cost)

        logger.info('Benchmark tests done')
        p50 = float(np.percentile(record, 50))
        p95 = float(np.percentile(record, 95))
        average = float(np.mean(record))
        if not hasattr(self, 'last_metrics'):
            self.last_metrics = {}
        self.last_metrics[label] = {
            'warmup': self.WARMUP_TOTAL,
            'samples': len(record),
            'p50': p50,
            'p95': p95,
            'mean': average,
        }
        logger.info(
            f'Benchmark metrics label={label} samples={len(record)} '
            f'P50={float2str(p50)} P95={float2str(p95)} mean={float2str(average)}'
        )
        return average

    def _valid_screenshot_frame(self, image, method):
        """Only allow canonical RGB 1280x720 frames into recommendations."""
        if image is None or not isinstance(image, np.ndarray):
            return False
        try:
            image = self.device._handle_orientated_image(image)
        except Exception as error:
            logger.warning(f'Benchmark frame normalization failed method={method}: {error}')
            return False
        shape = getattr(image, 'shape', ())
        valid = (
            len(shape) == 3
            and shape[0] == 720
            and shape[1] == 1280
            and shape[2] == 3
            and image.dtype == np.uint8
        )
        if not valid:
            logger.warning(
                f'Benchmark screenshot contract rejected method={method} shape={shape} '
                f'dtype={getattr(image, "dtype", None)} expected=720x1280x3 uint8 '
                'color=RGB'
            )
        return valid

    @staticmethod
    def evaluate_screenshot(cost):
        if not isinstance(cost, (float, int)):
            return Text(cost, style="bold bright_red")

        if cost < 0.10:
            return Text('Ultra Fast', style="bold bright_green")
        if cost < 0.20:
            return Text('Very Fast', style="bright_green")
        if cost < 0.30:
            return Text('Fast', style="green")
        if cost < 0.50:
            return Text('Medium', style="yellow")
        if cost < 0.75:
            return Text('Slow', style="red")
        if cost < 1.00:
            return Text('Very Slow', style="bright_red")
        return Text('Ultra Slow', style="bold bright_red")

    @staticmethod
    def evaluate_click(cost):
        if not isinstance(cost, (float, int)):
            return Text(cost, style="bold bright_red")

        if cost < 0.1:
            return Text('Fast', style="bright_green")
        if cost < 0.2:
            return Text('Medium', style="yellow")
        if cost < 0.4:
            return Text('Slow', style="red")
        return Text('Very Slow', style="bright_red")

    @staticmethod
    def show(test, data, evaluate_func):
        """
        +--------------+--------+--------+
        |  Screenshot  |  time  | Speed  |
        +--------------+--------+--------+
        |     ADB      | 0.319s |  Fast  |
        | uiautomator2 | 0.476s | Medium |
        |  aScreenCap  | Failed | Failed |
        +--------------+--------+--------+
        """
        # table = PrettyTable()
        # table.field_names = [test, 'Time', 'Speed']
        # for row in data:
        #     table.add_row([row[0], f'{float2str(row[1])}', evaluate_func(row[1])])

        # for row in table.get_string().split('\n'):
        #     logger.info(row)
        table = Table(show_lines=True)
        table.add_column(
            test, header_style="bright_cyan", style="cyan", no_wrap=True
        )
        table.add_column("Time", style="magenta")
        table.add_column("Speed", style="green")
        for row in data:
            table.add_row(
                row[0],
                float2str(row[1]),
                evaluate_func(row[1]),
            )
        logger.print(table, justify='center')

    def benchmark(self, screenshot: t.Tuple[str] = (), click: t.Tuple[str] = ()):
        logger.hr('Benchmark', level=1)
        logger.info(f'Testing screenshot methods: {screenshot}')
        logger.info(f'Testing click methods: {click}')

        screenshot_result = []
        for method in screenshot:
            result = self.benchmark_test(
                self.device.screenshot_methods[method],
                validator=lambda image, method=method: self._valid_screenshot_frame(image, method),
                label=f'screenshot:{method}',
            )
            screenshot_result.append([method, result])

        area = (120, 20, 200, 50)  # Somewhere safe to click.
        click_result = []
        for method in click:
            x, y = random_rectangle_point(area)
            result = self.benchmark_test(
                self.device.click_methods[method],
                x,
                y,
                label=f'click:{method}',
            )
            click_result.append([method, result])

        def compare(res):
            res = res[1]
            if not isinstance(res, (int, float)):
                return 100
            else:
                return res

        logger.hr('Benchmark Results', level=1)
        fastest_screenshot = None
        fastest_click = 'minitouch'
        if screenshot_result:
            self.show(test='Screenshot', data=screenshot_result, evaluate_func=self.evaluate_screenshot)
            valid_screenshots = [item for item in screenshot_result if isinstance(item[1], (int, float))]
            if valid_screenshots:
                fastest = sorted(valid_screenshots, key=lambda item: compare(item))[0]
                logger.info(f'Recommend screenshot method: {fastest[0]} ({float2str(fastest[1])})')
                fastest_screenshot = fastest[0]
            else:
                logger.error(
                    'No screenshot method passed the 1280x720 RGB contract; '
                    'automatic recommendation disabled'
                )
        if click_result:
            self.show(test='Control', data=click_result, evaluate_func=self.evaluate_click)
            fastest = sorted(click_result, key=lambda item: compare(item))[0]
            logger.info(f'Recommend control method: {fastest[0]} ({float2str(fastest[1])})')
            fastest_click = fastest[0]

        return fastest_screenshot, fastest_click

    def get_test_methods(self) -> t.Tuple[t.Tuple[str], t.Tuple[str]]:
        device = self.config.Benchmark_DeviceType
        # device == 'emulator'
        screenshot = ['ADB', 'ADB_nc', 'uiautomator2', 'DroidCast_raw', 'DroidCast', 'window_background']
        click = ['ADB', 'uiautomator2', 'minitouch', 'window_message']

        def remove(*args):
            return [l for l in screenshot if l not in args]

        # No ascreencap on Android > 9
        if device in ['emulator_android_12', 'android_phone_12']:
            screenshot = remove('aScreenCap', 'aScreenCap_nc')
        # No nc loopback
        if device in ['plone_cloud_with_adb']:
            screenshot = remove('ADB_nc', 'aScreenCap_nc')
        # VMOS
        if device == 'android_phone_vmos':
            screenshot = ['ADB', 'aScreenCap', 'DroidCast', 'DroidCast_raw']
            click = ['ADB', 'Hermit', 'MaaTouch']

        # scene = self.config.Benchmark_TestScene
        # if 'screenshot' not in scene:
        #     screenshot = []
        # if 'click' not in scene:
        #     click = []

        return tuple(screenshot), tuple(click)

    def run(self):
        try:
            # The selected method belongs to the config model.  Device does
            # not expose a duplicate screenshot_method attribute, and using
            # one here breaks the generic benchmark path before any sample
            # can be collected.
            self.config.override(
                self.config.script.device.screenshot_method == 'ADB'
            )
            self.device.uninstall_minicap()

        except RequestHumanTakeover:
            logger.critical('Request human takeover')
            return

        logger.attr('DeviceType', self.config.Benchmark_DeviceType)
        logger.attr('TestScene', self.config.Benchmark_TestScene)
        screenshot, click = self.get_test_methods()
        self.benchmark(screenshot, click)

    def run_simple_screenshot_benchmark(self):
        """
        Returns:
            str: The fastest screenshot method on current device.
        """
        screenshot = ['ADB', 'ADB_nc', 'uiautomator2', 'DroidCast_raw', 'DroidCast', 'window_background', 'nemu_ipc']

        def remove(*args):
            return [l for l in screenshot if l not in args]

        sdk = self.device.sdk_ver
        logger.info(f'sdk_ver: {sdk}')
        if not (21 <= sdk <= 28):
            screenshot = remove('aScreenCap', 'aScreenCap_nc')
        if self.device.is_chinac_phone_cloud:
            screenshot = remove('ADB_nc', 'aScreenCap_nc')
        if self.config.script.device.handle == '':
            screenshot = remove('window_background')
        screenshot = tuple(screenshot)

        method, _ = self.benchmark(screenshot, tuple())

        return method


if __name__ == '__main__':
    config = Config('oas1')
    device = Device(config)
    b = Benchmark(config=config, device=device)
    print(b.run_simple_screenshot_benchmark())
    # screenshot, click = b.get_test_methods()
    # b.benchmark(set(), click)
