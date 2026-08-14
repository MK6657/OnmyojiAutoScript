# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
from time import sleep
from typing import Union

from module.atom.click import RuleClick
from module.atom.long_click import RuleLongClick
from module.atom.ocr import RuleOcr
from module.base.timer import Timer
from module.exception import GameStuckError
from tasks.base_task import BaseTask
from tasks.Component.GeneralInvite.assets import GeneralInviteAssets
from tasks.Component.GeneralInvite.config_invite import InviteConfig, InviteNumber, FindMode
from tasks.Component.SwitchSoul.assets import SwitchSoulAssets
from tasks.Component.GeneralBattle.preset_name_selector import (
    InvalidPresetConfigError,
    PresetApplyUnconfirmedError,
)
from module.logger import logger


SWITCH_SOUL_TIMEOUT = 45.0

# 当前游戏版本的确认按钮可能与旧模板存在色差。保留模板快速路径，
# 再用 OCR 识别同一确认区域，避免确认框存在时无限点击底层队伍列表。
O_SOU_SWITCH_CONFIRM = RuleOcr(
    roi=(660, 390, 220, 100),
    area=(660, 390, 220, 100),
    mode="Full",
    method="Default",
    keyword="确定",
    name="sou_switch_confirm",
)

O_SOU_PRESET_STATUS = RuleOcr(
    roi=(350, 90, 600, 240),
    area=(350, 90, 600, 240),
    mode="Full",
    method="Default",
    keyword="",
    name="sou_preset_status",
)


def switch_parser(switch_str: str) -> tuple:
    if not isinstance(switch_str, str):
        raise InvalidPresetConfigError('Switch soul config must be a string like group,team')
    switch_list = [item.strip() for item in switch_str.split(',')]
    if len(switch_list) != 2:
        raise InvalidPresetConfigError('Switch soul config must contain exactly group,team')
    try:
        return int(switch_list[0]), int(switch_list[1])
    except (TypeError, ValueError) as error:
        raise InvalidPresetConfigError('Switch soul group and team must be integers') from error


class SwitchSoul(BaseTask, SwitchSoulAssets):

    @staticmethod
    def _validate_switch_pair(group, team) -> tuple[int, int]:
        try:
            group = int(group)
            team = int(team)
        except (TypeError, ValueError) as error:
            raise InvalidPresetConfigError(
                'Switch soul group and team must be integers'
            ) from error
        if group == -1 and team == -1:
            raise InvalidPresetConfigError(
                'Switch soul is enabled but switch_group_team is still -1,-1'
            )
        if group < 1 or group > 7:
            raise InvalidPresetConfigError('Switch soul group must be in [1-7]')
        if team < 1 or team > 4:
            raise InvalidPresetConfigError('Switch soul team must be in [1-4]')
        return group, team

    @classmethod
    def validate_switch_config(cls, enabled: bool, target):
        """Validate an enabled numeric preset before any game navigation."""
        if not enabled:
            return None
        if isinstance(target, str):
            target = switch_parser(target)
        if isinstance(target, tuple) and len(target) == 2:
            return cls._validate_switch_pair(*target)
        if isinstance(target, list) and target:
            return [cls._validate_switch_pair(*pair) for pair in target]
        raise InvalidPresetConfigError('Switch soul config must be a group,team pair')

    @staticmethod
    def _check_switch_soul_deadline(deadline: float, stage: str) -> None:
        if time.monotonic() >= deadline:
            raise GameStuckError(
                f'Switch soul {stage} timeout after {SWITCH_SOUL_TIMEOUT:.0f}s'
            )

    def _switch_confirm_visible(self) -> bool:
        return self.appear(self.I_SOU_SWITCH_SURE) or self.ocr_appear(O_SOU_SWITCH_CONFIRM)

    def _click_switch_confirm(self) -> bool:
        if self.appear(self.I_SOU_SWITCH_SURE):
            self.click(self.I_SOU_SWITCH_SURE)
            return True
        if self.ocr_appear(O_SOU_SWITCH_CONFIRM):
            self.click(O_SOU_SWITCH_CONFIRM)
            return True
        return False

    def _preset_status_visible(self) -> bool:
        # Full OCR 的 keyword 过滤允许模糊命中；标题“预设”不能当成
        # “正在使用预设御魂和阴阳术”的成功提示，必须检查完整文本。
        results = O_SOU_PRESET_STATUS.detect_and_ocr(self.device.image, logDisplay=False)
        status = ''.join(str(result.ocr_text or '') for result in results)
        return '正在使用预设' in status

    def _resolve_switch_confirm(self, deadline: float) -> bool:
        """点击确认并等待确认框消失；不会无期限点击。"""
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear_then_click(self.I_CHECK_BLOCK, interval=0.6):
                continue
            if not self._switch_confirm_visible():
                return True
            if self._click_switch_confirm():
                sleep(0.3)
                continue
            sleep(0.25)
        return False

    def run_switch_soul(self, target: tuple | list[tuple] | str):
        """
        保证在式神录的界面
        :return:
        """
        target = self.validate_switch_config(True, target)
        self.click_preset()
        self.switch_souls(target)

    def click_preset(self) -> None:
        """
        点击预设
        :return:
        """
        deadline = time.monotonic() + SWITCH_SOUL_TIMEOUT
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(self.I_SOU_SWITCH_1):
                break
            if self.appear(self.I_SOU_SWITCH_2):
                break
            if self.appear(self.I_SOU_SWITCH_3):
                break
            if self.appear(self.I_SOU_SWITCH_4):
                break
            if self.appear(self.I_SOU_TEAM_PRESENT):
                break
            if self.appear(self.I_SOUL_PRESET):
                self.click(self.I_SOUL_PRESET, interval=3)
                continue
        else:
            raise GameStuckError('Switch soul preset page did not appear')
        logger.info('Click preset in switch soul')

    def switch_soul_one(self, group: int, team: int) -> None:
        """
        设置一个队伍的预设御魂
        :param group: 只能是[1-7]
        :param team: 只能是[1-4]
        :return:
        """

        group, team = self._validate_switch_pair(group, team)

        def get_group_assets(group: int) -> tuple:
            match = {
                1: tuple([self.C_SOU_GROUP_1, self.I_SOU_CHECK_GROUP_1]),
                2: tuple([self.C_SOU_GROUP_2, self.I_SOU_CHECK_GROUP_2]),
                3: tuple([self.C_SOU_GROUP_3, self.I_SOU_CHECK_GROUP_3]),
                4: tuple([self.C_SOU_GROUP_4, self.I_SOU_CHECK_GROUP_4]),
                5: tuple([self.C_SOU_GROUP_5, self.I_SOU_CHECK_GROUP_5]),
                6: tuple([self.C_SOU_GROUP_6, self.I_SOU_CHECK_GROUP_6]),
                7: tuple([self.C_SOU_GROUP_7, self.I_SOU_CHECK_GROUP_7]),
            }
            return match[group]

        def get_team_asset(team: int):
            match = {
                1: self.I_SOU_SWITCH_1,
                2: self.I_SOU_SWITCH_2,
                3: self.I_SOU_SWITCH_3,
                4: self.I_SOU_SWITCH_4,
            }
            return match[team]

        # 滑动至分组最上层(分組過多, 导致第一个分组显示不全)
        deadline = time.monotonic() + SWITCH_SOUL_TIMEOUT
        cur_text = ""
        while time.monotonic() < deadline:
            self.screenshot()
            compare1 = self.O_SS_GROUP_NAME.detect_and_ocr(self.device.image)
            ocr_text = str([result.ocr_text for result in compare1])
            # 相等时 滑动到最上层
            if cur_text == ocr_text:
                break
            cur_text = ocr_text
            # 向上滑动
            self.swipe(self.S_SS_GROUP_SWIPE_UP, 1.5)
            # 等待滑动动画
            sleep(0.5)

        self._check_switch_soul_deadline(deadline, 'group list')

        # 这一步是选择组
        target_click, target_check = get_group_assets(group)
        # while 1:
        #     self.screenshot()
        #     if self.click(target_click, interval=1):
        #         continue
        #     if self.appear(target_check):
        #         break
        # 2023.8.5 修改为无反馈的点击切换
        for i in range(2):
            self.click(target_click)
            sleep(0.5)
        # 点击队伍
        target_team = get_team_asset(team)
        for i in range(3):
            self._check_switch_soul_deadline(deadline, 'team apply')
            sleep(0.8)
            self.screenshot()
            if self._switch_confirm_visible():
                if not self._resolve_switch_confirm(deadline):
                    raise PresetApplyUnconfirmedError(
                        'Switch soul confirmation did not disappear'
                    )
                continue
            if not self.appear_then_click(target_team, interval=3):
                logger.warning(f'Click team {team} failed in group {group}')
        # 兜底处理模板失配但 OCR 能识别的确认按钮。
        if self._switch_confirm_visible() and not self._resolve_switch_confirm(deadline):
            raise PresetApplyUnconfirmedError(
                'Switch soul confirmation did not disappear'
            )
        logger.info(f'Switch soul_one group {group} team {team}')

    def switch_souls(self, target: tuple or list[tuple]) -> None:
        """
        切换御魂
        :param target: [(1, 1), (2, 2), (3, 3), (4, 4)]  或者是单独的一个元组(4, 4) 第一个是组, 第二个是队伍
        :return:
        """
        if isinstance(target, tuple):
            target = [target]
        for group, team in target:
            group = int(group)
            team = int(team)
            self.switch_soul_one(group, team)

    def exit_shikigami_records(self) -> None:
        """
        退出式神录的界面
        :return:
        """
        deadline = time.monotonic() + SWITCH_SOUL_TIMEOUT
        while time.monotonic() < deadline:
            self.screenshot()
            if not self.appear(self.I_SOU_CHECK_IN):
                break
            if self.appear_then_click(self.I_RECORD_SOUL_BACK, interval=3.5):
                continue
        self._check_switch_soul_deadline(deadline, 'exit records')
        logger.info('Exit shikigami records')

    def run_switch_soul_by_name(self, groupName, teamName):
        """
        保证在式神录的界面
        :return:
        """
        if isinstance(groupName, str) and isinstance(teamName, str):
            selector = getattr(self, '_switch_preset_soul_by_name', None)
            if selector is not None:
                return selector(groupName, teamName)
            self.click_preset()
            return self.switch_soul_by_name(groupName, teamName)
        return False

    def switch_soul_by_name(self, groupName, teamName):
        """
        保证在式神录的界面
        :return:
        """
        selector = getattr(self, '_switch_preset_soul_by_name', None)
        if selector is not None:
            return selector(groupName, teamName)

        logger.hr('Switch soul by name')
        deadline = time.monotonic() + SWITCH_SOUL_TIMEOUT
        # 滑动至分组最上层
        last_group_text = ''
        while time.monotonic() < deadline:
            self.screenshot()
            compare1 = self.O_SS_GROUP_NAME.detect_and_ocr(self.device.image)
            now_group_text = str([result.ocr_text for result in compare1])
            if now_group_text == last_group_text:
                break
            self.swipe(self.S_SS_GROUP_SWIPE_UP, 2)
            sleep(2.5)
            last_group_text = now_group_text
        self._check_switch_soul_deadline(deadline, 'group list')
        logger.info('Swipe to top of group')

        # 判断有无目标分组
        while time.monotonic() < deadline:
            self.screenshot()
            # 获取当前分组名
            results = self.O_SS_GROUP_NAME.detect_and_ocr(self.device.image)
            text1 = [result.ocr_text for result in results]
            # 判断当前分组有无目标分组
            result = set(text1).intersection({groupName})
            # 有则跳出检测
            if result and len(result) > 0:
                break
            self.swipe(self.S_SS_GROUP_SWIPE_DOWN)
            sleep(1.5)
        self._check_switch_soul_deadline(deadline, f'find group {groupName}')
        logger.info('Swipe down to find target group')

        # 选中分组
        while time.monotonic() < deadline:
            self.screenshot()
            self.O_SS_GROUP_NAME.keyword = groupName
            if self.ocr_appear_click(self.O_SS_GROUP_NAME):
                break
        self._check_switch_soul_deadline(deadline, f'select group {groupName}')
        logger.info(f'Select group {groupName}')

        # 滑动至阵容最上层
        last_team_text = ''
        while time.monotonic() < deadline:
            self.screenshot()
            compare1 = self.O_SS_TEAM_NAME.detect_and_ocr(self.device.image)
            now_team_text = str([result.ocr_text for result in compare1])
            # 向上滑动
            if now_team_text == last_team_text:
                break
            self.swipe(self.S_SS_TEAM_SWIPE_DOWN, 1.5)
            sleep(2)
            last_team_text = now_team_text
        self._check_switch_soul_deadline(deadline, 'team list')
        logger.info('Swipe to top of team')

        # 判断当前分组有无目标阵容
        while time.monotonic() < deadline:
            self.screenshot()
            # 获取当前阵容名
            results = self.O_SS_TEAM_NAME.detect_and_ocr(self.device.image)
            text1 = [result.ocr_text for result in results]
            # 判断当前分组有无目标阵容
            result = set(text1).intersection({teamName})
            # 有则跳出检测
            if result and len(result) > 0:
                break
            self.swipe(self.S_SS_TEAM_SWIPE_UP, 0.3)
        self._check_switch_soul_deadline(deadline, f'find team {teamName}')
        logger.info('Swipe up to find target team')

        # 选中分组
        while time.monotonic() < deadline:
            self.screenshot()
            self.O_SS_TEAM_NAME.keyword = teamName
            if self.ocr_appear_click(self.O_SS_TEAM_NAME):
                break
        self._check_switch_soul_deadline(deadline, f'select team {teamName}')
        logger.info(f'Select team {teamName}')
        # 切换御魂：应用按钮只点击一次，确认框消失即完成。
        self.O_SS_TEAM_NAME.keyword = teamName
        clicked = False
        click_time = None
        while time.monotonic() < deadline:
            self.screenshot()
            if self._switch_confirm_visible():
                if not self._resolve_switch_confirm(deadline):
                    raise PresetApplyUnconfirmedError(
                        'Switch soul confirmation did not disappear'
                    )
                logger.info(f'Switch soul_one group {groupName} team {teamName}')
                return True
            if self._preset_status_visible():
                logger.info(f'Team {teamName} is already using preset soul')
                return True
            if not clicked and self.ocr_appear_click_by_rule(
                    self.O_SS_TEAM_NAME, self.I_SOU_CLICK_PRESENT, interval=1.5):
                clicked = True
                click_time = time.monotonic()
                continue
            if clicked and time.monotonic() - click_time >= 6:
                raise PresetApplyUnconfirmedError(
                    f'Team {teamName} preset click produced no confirmation or status'
                )
            sleep(0.25)
        raise PresetApplyUnconfirmedError(f'Switch soul team {teamName} timeout')

    def ocr_appear_click_by_rule(self,
                                 target: RuleOcr,
                                 action: Union[RuleClick, RuleLongClick] = None,
                                 interval: float = None,
                                 duration: float = None) -> bool:
        """
        ocr识别目标，如果目标存在，则触发动作
        :param target:
        :param action:
        :param interval:
        :param duration:
        :return:
        """
        appear = self.ocr_appear(target, interval)

        if not appear:
            return False

        _, y1, _, h1 = target.area
        x, _ = action.coord()

        # OCR 的 area 已在 ocr_appear() 中更新为目标队伍文字框，
        # 只复用操作按钮的 X 坐标，Y 坐标必须跟随当前队伍行。
        self.device.click(x=x, y=int(y1 + h1 / 2), control_name=target.name)
        return True


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    s = SwitchSoul(c, d)

    s.click_preset()
    # s.switch_soul_one(4, 1)
    # s.switch_soul_by_name('契灵', '茨球')
    s.switch_soul_by_name('默认分组', '队伍5')
