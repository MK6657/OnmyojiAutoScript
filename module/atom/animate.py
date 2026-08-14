from pathlib import Path
from module.logger import logger

import cv2
import numpy as np

from module.atom.image import RuleImage
from module.atom.click import RuleClick
from module.atom.long_click import RuleLongClick
from module.atom.ocr import RuleOcr


class RuleAnimate(RuleImage):

    def __init__(self,
                 rule: RuleImage | RuleClick | RuleLongClick | RuleOcr,
                 threshold: float = 0.75,
                 name: str = None):
        if isinstance(rule, RuleImage):
            roi_front = rule.roi_front
            roi_back = rule.roi_back
            self._name = Path(rule.file).stem.upper()
            threshold = threshold
        elif isinstance(rule, RuleClick) or isinstance(rule, RuleLongClick):
            roi_front = rule.roi_front
            roi_back = rule.roi_back
            self._name = rule.name
        elif isinstance(rule, RuleOcr):
            roi_front = rule.roi
            roi_back = rule.area
            self._name = rule.name
        else:
            roi_front = None
            roi_back = None
            self._name = 'RuleAnimate'

        super().__init__(
            roi_front=list(roi_front),
            roi_back=list(roi_back),
            method='Template matching',
            threshold=threshold,
            file=''
        )

        if name is not None:
            self._name = name
        self._last_image = None

    @property
    def name(self) -> str:
        return self._name.upper()

    def stable(self, image, refresh_after_stable: bool = False) -> bool:
        """
        用于判断连续的两张截图，的目标区域是否一致
        @param image:
        @param refresh_after_stable:
        @return:
        """
        current = self.corp(image, self.roi_front)
        if current.size == 0:
            self._last_image = None
            return False

        if self._last_image is None:
            self._last_image = current.copy()
            return False

        previous = self._last_image
        matched = False
        if previous.shape == current.shape:
            score = cv2.matchTemplate(current, previous, cv2.TM_CCOEFF_NORMED)[0, 0]
            if np.isnan(score):
                score = 1.0 if np.array_equal(previous, current) else 0.0
            mean_difference = float(np.mean(cv2.absdiff(previous, current)))
            difference_limit = 255.0 * (1.0 - self.threshold)
            matched = score > self.threshold and mean_difference <= difference_limit
        self._last_image = current.copy()

        if matched:
            if refresh_after_stable:
                self.refresh()
            logger.info(f'Animation Stable @ {self.name}')
            return True
        return False

    def refresh(self):
        self._last_image = None


if __name__ == '__main__':
    from module.base.utils import load_image
    from tasks.SixRealms.assets import SixRealmsAssets
    ttt = RuleAnimate(SixRealmsAssets.C_MAIN_ANIMATE_KEEP, threshold=0.5)
    imga = r'C:\Users\Ryland\Desktop\Desktop\37.png'
    imgb = r'C:\Users\Ryland\Desktop\Desktop\38.png'
    imga = load_image(imga)
    imgb = load_image(imgb)

    print(ttt.stable(imga))
    print(ttt.stable(imgb))
    print(ttt.stable(imgb))
