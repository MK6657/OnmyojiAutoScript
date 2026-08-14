# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey


from tasks.base_task import BaseTask
from tasks.Script.config_device import ScreenshotMethod, ControlMethod

class FastDevice(BaseTask):

    def fast_screenshot(self):
        if self.config.model.script.device.screenshot_method != ScreenshotMethod.WINDOW_BACKGROUND:
            raise

        def capture_fast_frame():
            self.device.image = self.device.screenshot_window_background()
            publish_frame = getattr(self.device, 'publish_frame', None)
            if callable(publish_frame):
                publish_frame()
            return self.device.image

        return self.protected_screenshot(
            capture=capture_fast_frame,
            capture_deadline_capable=False,
        )
