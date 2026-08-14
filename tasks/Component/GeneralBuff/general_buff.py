# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import copy
import cv2
import numpy as np
import time

from tasks.Component.GeneralBuff.assets import GeneralBuffAssets
from module.atom.ocr import RuleOcr
from module.atom.image import RuleImage
from tasks.base_task import BaseTask
from module.logger import logger


class GeneralBuff(BaseTask, GeneralBuffAssets):

    def open_buff(self, timeout: float = 15):
        """
        打开buff的总界面
        :return:
        """
        logger.info('Open buff')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(self.I_CLOUD):
                break
            if self.appear_then_click(self.I_BUFF_1, interval=2):
                continue
        else:
            logger.warning(f'Open buff timed out after {timeout}s')
            return False

        check_image = self.I_AWAKE
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(check_image):
                return True

            self.swipe(self.S_BUFF_UP, interval=2)
        logger.warning(f'Buff list did not stabilize after {timeout}s')
        return False

    def close_buff(self, timeout: float = 15):
        """
        关闭buff的总界面, 但是要确保buff界面已经打开了
        :return:
        """
        logger.info('Close buff')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.screenshot()
            if not self.appear(self.I_CLOUD):
                return True
            if self.appear_then_click(self.I_BUFF_1, interval=2):
                continue
        logger.warning(f'Close buff timed out after {timeout}s')
        return False

    def get_area(self, buff: RuleOcr) -> tuple:
        """
        获取要点击的开关buff的区域
        :param cls:
        :param image:
        :param buff:
        :return:  如果没有就返回None
        """
        # 防止邀请框挡住BUFF框架
        self.reject_invite()
        self.screenshot()

        # RuleOcr 的字符兜底会把“经验增加50%”等相似文本误当成目标，
        # 特别是账号没有某一档加成时，可能返回第一行无关材料的坐标。
        # 先要求完整关键词出现在当前弹窗文本中，再计算开关坐标。
        if buff.keyword not in buff.detect_text(self.device.image):
            logger.info(f'No {buff.name} buff')
            return None

        area = buff.ocr(self.device.image)
        if not area or area[2] <= 0 or area[3] <= 0:
            logger.info(f'No {buff.name} buff')
            return None

        # 开始的x坐标就是文字的右边
        start_x = area[0] + area[2] + 10  # 10是文字和开关之间的间隔
        start_y = area[1] - 10
        width = 80  # 开关的宽度 80够了
        height = area[3] + 20
        return int(start_x), int(start_y), int(width), int(height)

    def set_switch_area(self, area):
        """
        设置开关的区域
        :param area:
        :return:
        """
        normalized_area = tuple(int(value) for value in area)

        def localized(rule):
            result = copy.copy(rule)
            result.roi_front = list(rule.roi_front)
            result.roi_back = normalized_area
            return result

        return localized(self.I_OPEN_YELLOW), localized(self.I_CLOSE_RED)

    def _set_switch_state(self, name: str, area, is_open: bool) -> bool:
        """Set a buff switch after distinguishing open, closed and unknown states."""
        state, open_rule, close_rule = GeneralBuff._read_switch_state(self, name, area)

        target_state = 'open' if is_open else 'closed'
        logger.info(f'Buff switch state: name={name}, state={state}, target={target_state}')
        if state == target_state:
            return True
        if state in {'ambiguous', 'unknown'}:
            logger.warning(f'Buff switch state not actionable: name={name}, state={state}')
            return False

        click_rule = close_rule if is_open else open_rule
        stop_rule = open_rule if is_open else close_rule
        if not self.ui_click(click=click_rule, stop=stop_rule, interval=1, timeout=5):
            logger.warning(f'Buff switch transition timed out: name={name}')
            return False

        self.screenshot()
        if self.appear(stop_rule):
            logger.info(f'Buff switch state confirmed: name={name}, state={target_state}')
            return True
        logger.warning(f'Buff switch transition unconfirmed: name={name}')
        return False

    def _read_switch_state(self, name: str, area):
        """Return the observed switch state and localized rules without clicking."""
        open_rule, close_rule = self.set_switch_area(area)
        self.screenshot()
        open_seen = self.appear(open_rule)
        close_seen = self.appear(close_rule)

        if open_seen and close_seen:
            state = 'ambiguous'
        elif open_seen:
            state = 'open'
        elif close_seen:
            state = 'closed'
        else:
            state = 'unknown'
        logger.info(f'Buff switch observed: name={name}, state={state}')
        return state, open_rule, close_rule

    def gold_50(self, is_open: bool = True):
        """
        金币50buff
        :param is_open: 是否打开
        :return:
        """
        logger.info(f'{"Open" if is_open else "Close"} gold 50 buff')
        self.screenshot()
        area = self.get_area(self.O_GOLD_50)
        if not area:
            logger.warning('No gold 50 buff')
            return None
        return self._set_switch_state('gold_50', area, is_open)

    def gold_100(self, is_open: bool = True):
        """
        金币100buff
        :param is_open: 是否打开
        :return:
        """
        logger.info(f'{"Open" if is_open else "Close"} gold 100 buff')
        self.screenshot()
        area = self.get_area(self.O_GOLD_100)
        if not area:
            logger.warning('No gold 100 buff')
            return None
        return self._set_switch_state('gold_100', area, is_open)

    def exp_50(self, is_open: bool = True):
        """
        经验50buff
        :param is_open: 是否打开
        :return:
        """
        logger.info(f'{"Open" if is_open else "Close"} exp 50 buff')
        area = self.get_area(self.O_EXP_50)
        if not area:
            logger.warning('No exp 50 buff; skip')
            return None
        return self._set_switch_state('exp_50', area, is_open)

    def exp_100(self, is_open: bool = True):
        """
        经验100buff
        :param is_open: 是否打开
        :return:
        """
        logger.info(f'{"Open" if is_open else "Close"} exp 100 buff')
        area = self.get_area(self.O_EXP_100)
        if not area:
            logger.warning('No exp 100 buff; skip')
            return None
        return self._set_switch_state('exp_100', area, is_open)

    def get_area_image(self, target: RuleImage) -> list:
        """
        获取觉醒加成或者是御魂加成所要点击的区域
        因为实在的图片比ocr快
        :param image:
        :param target:
        :return:
        """
        self.reject_invite()
        self.screenshot()

        if not target.match(self.device.image):
            logger.warning(f'No {target.name} buff')
            return None
            # logger.info(f'front area: {target.roi_front}')
            # logger.info(f'front center: {target.front_center()}')
        start_x = int(target.front_center()[0] + 364)
        start_y = int(target.roi_front[1])
        width = 80
        height = int(target.roi_front[3])
        return [start_x, start_y, width, height]

    def awake(self, is_open: bool = True):
        """
        觉醒buff
        :param is_open: 是否打开
        :return:
        """
        logger.info(f'{"Open" if is_open else "Close"} awake buff')
        self.screenshot()
        area = self.get_area_image(self.I_AWAKE)
        if not area:
            logger.warning('No awake buff')
            return None
        return self._set_switch_state('awake', area, is_open)

    def soul(self, is_open: bool = True):
        """
        御魂buff
        :param is_open: 是否打开
        :return:
        """
        logger.info(f'{"Open" if is_open else "Close"} soul buff')
        self.screenshot()
        area = self.get_area_image(self.I_SOUL)
        if not area:
            logger.warning('No soul buff')
            return None
        return self._set_switch_state('soul', area, is_open)

    def reject_invite(self, timeout: float = 15):
        from tasks.Component.GeneralInvite.assets import GeneralInviteAssets as gia
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.screenshot()
            if not (self.appear(gia.I_I_REJECT_1) or self.appear(gia.I_I_REJECT_2) or self.appear(gia.I_I_REJECT_3)):
                return True
            if self.appear(gia.I_I_REJECT_3):
                self.click(gia.I_I_REJECT_3, 6)
                continue
            if self.appear(gia.I_I_REJECT_2):
                self.click(gia.I_I_REJECT_2, 6)
                continue
            if self.appear(gia.I_I_REJECT_1):
                self.click(gia.I_I_REJECT_1, 6)
                continue
        logger.warning(f'Invite dismissal timed out after {timeout}s')
        return False


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = GeneralBuff(c, d)

    t.open_buff()
    # t.screenshot()
    #
    t.awake(is_open=True)
    t.soul(is_open=True)
    t.gold_50(is_open=False)
    t.gold_100(is_open=False)
    t.exp_50(is_open=True)
    t.exp_100(is_open=True)
