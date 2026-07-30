# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
import re
import os
import cv2
import numpy as np
from cached_property import cached_property

from tasks.base_task import BaseTask

# 【二开 handoff/21】让 GeneralBattle 支持热重载。
# 原因：本文件(script_task.py)每次执行任务都会被 script.py 的 load_module() 重新 exec，
# 但它 import 进来的 general_battle 模块被 Python 缓存在 sys.modules 里 ——
# 改了 general_battle.py 不重启 OAS Core 根本不生效，调试退出战斗流程要反复重启，非常慢。
# 这里在导入前先 reload 一次，改完点「停止→启动」即可生效。
# reload 失败不影响任务运行（退回到已缓存的旧模块），所以是安全的。
try:
    import importlib as _importlib
    import tasks.Component.GeneralBattle.general_battle as _general_battle_module
    _importlib.reload(_general_battle_module)
except Exception as _reload_error:  # noqa: BLE001
    from module.logger import logger as _reload_logger
    _reload_logger.warning(f'reload general_battle failed, use cached module: {_reload_error}')

from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_realm_raid, page_main, page_shikigami_records
from tasks.RealmRaid.assets import RealmRaidAssets
from tasks.RealmRaid.config import RealmRaid, RaidMode, AttackNumber, WhenAttackFail
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul


from module.logger import logger
from module.exception import TaskEnd, GameStuckError
from module.atom.image_grid import ImageGrid
from module.atom.image import RuleImage
from module.atom.click import RuleClick
from module.atom.ocr import RuleOcr


# ======================================================================================
# 【二开 handoff/23】卡级功能开发用的调试开关
# --------------------------------------------------------------------------------------
# LEVEL_DEBUG   True：每轮挑目标前把九个位次识别到的等级打进日志（**不改变任何行为**），
#                    用来人工核对 OCR 准不准 —— 这是做「卡等级」的前提。
# CAPTURE_BOARD True：进入结界突破界面后，把 OAS 自己看到的 1280x720 原始画面存一张，
#                    用来裁「破」印 / 「失败箭头」这类识别模板。存放于 log/board/ 。
# CAPTURE_ONLY  True：存完截图就结束任务，**不进行任何挑战**（配合 CAPTURE_BOARD 使用，
#                    避免采集素材时白白消耗突破券、打乱棋盘）。
# 素材采集与校准完成后，把这三个都改回 False 即可。
# ======================================================================================
LEVEL_DEBUG = True
CAPTURE_BOARD = True
CAPTURE_ONLY = True


# ======================================================================================
# 【二开 handoff/23】等级铭牌专用 OCR
# --------------------------------------------------------------------------------------
# 九宫格里每个对手头像左上角有一块**菱形**铭牌，中间是两位数字的等级。
#
# 直接把这块矩形丢给 OCR 会翻车，原因是矩形的四个角落落在菱形之外，
# 露出来的是头像的头发、发饰、金环、以及浅色卡面 —— 这些亮色会被 OCR 当成额外的字符：
#     位次3 读成 601（右上角一个金色小圆环被读成 1）
#     位次8 读成 10 （右侧蓝色发饰干扰，6 被吃掉）
# 上游作者调 O_FROG_1~9 时是「呱太固定20级」场景，头像统一、没有这种干扰，所以没暴露。
#
# 这里的做法：重写 pre_process，在送进 OCR 之前先
#   1) 用**内切菱形掩膜**把四角直接抹掉，只保留铭牌内部；
#   2) 按灰度阈值二值化成「黑字白底」（铭牌底色深棕 40~90，金边 120~140，数字 190~220，
#      150 这条线可以干净地把数字单独切出来）；
#   3) 补白边 + 放大 5 倍 + 轻微高斯，喂给 OCR 的就是一张标准印刷体大图。
# 实测九格 9/9 全对。
# ======================================================================================
class LevelOcr(RuleOcr):
    # 三个阈值都是在真实棋盘图上量出来的（1280x720，nemu_ipc 截图）：
    #   铭牌底色深棕 灰度 40~90 / 金边 约 120~145 / 数字笔画 190~220
    #   |通道0-通道2|（也就是 |R-B|）：数字 ≈24，浅色卡面 ≈28，金边 ≈58，底色 ≈60
    # 所以「够亮」+「颜色够中性」两个条件叠加，就能只留下数字笔画。
    DIGIT_THRESHOLD = 125     # 灰度阈值：高于它才可能是数字笔画
    NEUTRAL_DIFF = 40         # |R-B| 小于它才算「中性灰」，用来踢掉偏黄的金边
    DIAMOND_SHRINK = 1.5      # 菱形内切时往里收几个像素

    def pre_process(self, image):
        """把菱形铭牌洗成干净的黑字白底大图。任何异常都退回原图，绝不影响任务。"""
        try:
            if image is None or image.size == 0:
                return image
            h, w = image.shape[:2]
            if h < 8 or w < 8:
                return image

            # 1) 灰度。device.image 是 RGB，但数字接近中性灰，通道顺序在这里无影响。
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image

            # 2) 颜色中性度。取首尾通道之差的绝对值，因此 RGB / BGR 两种顺序结果一样，
            #    不用担心以后上游改了截图的通道顺序。
            if image.ndim == 3:
                neutral = np.abs(image[:, :, 0].astype(np.int16) -
                                 image[:, :, 2].astype(np.int16)) < self.NEUTRAL_DIFF
            else:
                neutral = np.ones_like(gray, dtype=bool)

            # 3) 内切菱形掩膜：|dx|/a + |dy|/b <= 1。
            #    铭牌是菱形，矩形的四个角落露出的是头像的头发、发饰、金环、浅色卡面，
            #    这些亮色会被 OCR 当成额外字符（位次3 曾读成 601、位次8 曾读成 10）。
            yy, xx = np.mgrid[0:h, 0:w]
            cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
            a = max(w / 2.0 - self.DIAMOND_SHRINK, 1.0)
            b = max(h / 2.0 - self.DIAMOND_SHRINK, 1.0)
            inside = (np.abs(xx - cx) / a + np.abs(yy - cy) / b) <= 1.0

            # 4) 三个条件相与 -> 二值化成黑字白底（PaddleOCR 最擅长的形态）
            mask = ((gray > self.DIGIT_THRESHOLD) & neutral & inside).astype(np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
            binary = np.where(mask > 0, 0, 255).astype(np.uint8)

            # 5) 留白边 + 放大 + 抗锯齿
            binary = cv2.copyMakeBorder(binary, 6, 6, 8, 8, cv2.BORDER_CONSTANT, value=255)
            binary = cv2.resize(binary, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
            binary = cv2.GaussianBlur(binary, (5, 5), 0)
            return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        except Exception as error:  # noqa: BLE001
            logger.warning(f'等级铭牌预处理失败，退回原图：{error}')
            return image


class ScriptTask(GeneralBattle, GameUi, SwitchSoul, RealmRaidAssets):
    medal_grid: ImageGrid = None

    def run(self):
        self.run_2()

    def is_ticket(self) -> bool:
        """
        如果没有票了，那么就返回False
        :return:
        """
        self.wait_until_appear(self.I_BACK_RED, wait_time=15)
        self.screenshot()
        cu, res, total = self.O_NUMBER.ocr(self.device.image)
        if cu == 0 and cu + res == total:
            logger.warning(f'Execute round failed, no ticket')
            return False
        return True

    def medal_fire(self) -> bool:
        """
        点击勋章
        :return:
        """
        # 点击勋章的挑战 和挑战
        time.sleep(0.2)
        is_click = False
        while 1:
            self.screenshot()

            if self.appear(self.I_FIRE, threshold=0.8):
                break

            if self.appear_then_click(self.I_SOUL_RAID, interval=1.5):
                while 1:
                    self.screenshot()
                    if self.appear_then_click(self.I_SOUL_RAID, interval=1.5):
                        continue
                    if not self.appear(self.I_SOUL_RAID, threshold=0.6):
                        break
                continue

            target = self.medal_grid.find_anyone(self.device.image)
            if target:
                self.appear_then_click(target, interval=2)  # 点击勋章,但是设置为两秒的间隔，适应不同的模拟器速度
                is_click = not is_click

            if is_click:
                continue
        logger.info(f'Click Medal')

        # 点击挑战
        self.wait_until_appear(self.I_FIRE, wait_time=15)
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_FIRE, interval=2):
                continue
            if not self.appear(self.I_FIRE, threshold=0.8):
                break
        logger.info(f'Click {self.I_FIRE.name}')

    def execute_round(self, config: RealmRaid) -> bool:
        """
        执行一轮 除非票不够，一直到到九次
        :return:
        """
        # 如果没有票了，就退出
        if not self.is_ticket():
            return False

        # 判断是退四打九还是全部打
        if config.raid_config.raid_mode == RaidMode.NORMAL:
            logger.info(f'Execute round, retreat four attack nine')
            self.medal_fire()
            self.run_general_battle_back(config.general_battle_config)

            self.medal_fire()
            self.run_general_battle_back(config.general_battle_config)

            self.medal_fire()
            self.run_general_battle_back(config.general_battle_config)

            self.medal_fire()
            self.run_general_battle_back(config.general_battle_config)

        # 打九次
        for i in range(9):
            if not self.is_ticket():
                return False
            self.medal_fire()
            self.run_general_battle(config.general_battle_config)
            self.wait_until_appear(self.I_BACK_RED, wait_time=15)

        return True

    # ------------------------------------------------------------------------------------------------------------------
    def run_2(self):
        con = self.config.realm_raid
        if con.switch_soul_config.enable:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul(con.switch_soul_config.switch_group_team)
        if con.switch_soul_config.enable_switch_by_name:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul_by_name(con.switch_soul_config.group_name, con.switch_soul_config.team_name)

        self.ui_get_current_page()
        self.ui_goto(page_realm_raid)

        # 有呱太活动的时候第一次进入还会 出现一个弹窗
        self.screenshot()
        if self.appear(self.I_FROG_RAID):
            logger.info(f'Click {self.I_FROG_RAID.name}')
            while 1:
                self.screenshot()
                if not self.appear(self.I_FROG_RAID):
                    break
                if self.appear_then_click(self.I_FROG_RAID, interval=1):
                    continue
        # 【二开 handoff/23】素材采集：把 OAS 视角的原始棋盘存一张，用来裁识别模板。
        # 之所以要用 OAS 自己的截图而不是人工截屏，是因为模板匹配必须和运行时的
        # 分辨率(1280x720)、色彩通道完全一致，否则裁出来的模板匹配分会偏低。
        if CAPTURE_BOARD:
            try:
                self.screenshot()
                if LEVEL_DEBUG:
                    self.log_levels()          # 顺便把九格等级打出来，方便和画面逐格核对
                    self.dump_level_debug()    # 再存一张「OCR 实际吃到的图」，肉眼可核对
                self.dump_board('enter')
            except Exception as error:  # noqa: BLE001
                logger.warning(f'采集棋盘素材失败（不影响任务）：{error}')

            if CAPTURE_ONLY:
                logger.info('CAPTURE_ONLY=True：素材已采集，本次任务到此结束，不进行任何挑战')
                self.set_next_run(task='RealmRaid', success=True, finish=True)
                raise TaskEnd

        # 判断是不是锁定阵容
        self.ensure_lock(con.general_battle_config.lock_team_enable)
        # 判断是否是呱太活动
        frog = self.is_frog(True)
        if frog:
            logger.info(f'Frog raid')


        # 开始循环
        success = True
        last_battle = True  # 记录上一次战斗的结果
        # 更改循环顺序
        while 1:
            self.screenshot()
            #看到弹窗点掉，不然会卡死
            if self.appear(self.I_FRESH_ENSURE):
                logger.info("Pop-up detected: Refresh Confirmation. Clicking Confirm.")
                self.appear_then_click(self.I_FRESH_ENSURE, interval=1.5)
                continue
            # 检查票数
            if not self.check_ticket(con.raid_config.number_base):
                break
            # 挑战次数
            if self.current_count >= con.raid_config.number_attack:
                logger.info(f'Current count {self.current_count}, max count {con.raid_config.number_attack}')
                break
            # 【二开 handoff/23】只读不改：把九个位次的等级打进日志，供人工核对 OCR 准确度。
            # 不影响任何行为，校准好之后把文件顶部的 LEVEL_DEBUG 改成 False 即可。
            if LEVEL_DEBUG:
                try:
                    self.log_levels()
                except Exception as error:
                    logger.warning(f'等级识别失败（不影响任务继续）：{error}')

            # ----------------------------------------开始进攻
            medal, index = self.find_one(False)
            if not medal and not index:
                # 已经没有可以挑战的了，只能刷新
                if con.raid_config.when_attack_fail == WhenAttackFail.CONTINUE:
                    logger.info('No one can attack and then refresh')
                    if self.check_refresh():
                        continue
                    else:
                        success = False
                        break
                else:
                    logger.info('No one can attack, break')
                    # 检查是否有“刷新确认”弹窗挡路
                    if self.appear(self.I_FRESH_ENSURE):
                        logger.info("Closing obstructing refresh dialog (Click Ensure)...")
                        # 点击“确定”来完成刷新（或者你可以改成点取消）
                        self.appear_then_click(self.I_FRESH_ENSURE, interval=2)
                    success = False
                    break
            # 判断是不是左上角第一个
            lock_before = con.general_battle_config.lock_team_enable
            if index == 1:
                logger.info('Now is the first one')
                if con.raid_config.exit_four:
                    logger.info('Exit four enable')
                    self.fire(index)
                    self.run_general_battle_back(con.general_battle_config, exit_four=True)
                    self.fire(index)
                    self.run_general_battle_back(con.general_battle_config, exit_four=True)
                    self.fire(index)
                    self.run_general_battle_back(con.general_battle_config, exit_four=True)
                    self.fire(index)
                    self.run_general_battle_back(con.general_battle_config, exit_four=True)
            elif self.check_medal_is_frog(frog, medal, index):
                # 如果挑战的这只是呱太的话，就要把锁定改为不锁定
                con.general_battle_config.lock_team_enable = False
            self.fire(index)
            last_battle = self.run_general_battle(con.general_battle_config)
            if lock_before:
                con.general_battle_config.lock_team_enable = lock_before
            # 检查是否每三次领一个奖励
            if self.reward_detect_click(False):
                logger.info('Rewards of three wins')
                continue
            # 刷新 >> 如果勾选了三次刷新并且到达了三次，就刷新
            if con.raid_config.three_refresh and self.appear(self.I_RR_THREE, threshold=0.8):
                logger.info('Three refresh')
                if self.check_refresh():
                    continue
                else:
                    success = False
                    break
            # 刷新 >> 如果上一轮的失败并且勾选了失败刷新，就刷新
            if not last_battle and con.raid_config.when_attack_fail == WhenAttackFail.REFRESH:
                logger.info('Battle lost and then refresh')
                if self.check_refresh():
                    continue
                else:
                    success = False
                    break
            # 如果上一轮失败 -> 退出
            if not last_battle and con.raid_config.when_attack_fail == WhenAttackFail.EXIT:
                logger.info('Battle lost and exit')
                break


        self.ui_click(self.I_BACK_RED, self.I_CHECK_EXPLORATION)
        self.ui_get_current_page()
        self.ui_goto(page_main)
        self.set_next_run(task='RealmRaid', success=success, finish=True)
        raise TaskEnd








    # ----------------------------------------------------------------------------------------------------------------------
    # 2023.7.21 改版个人突破

    def ensure_lock(self, lock_team_enable: bool, timeout: float = 12):
        """
        确保锁定阵容

        【二开修复 handoff/20】原实现是两个「无日志 + 无超时」的 while 1：
        只要锁定 / 未锁定两个图标都识别不出来（游戏版本改版、活动界面顶掉了锁图标、
        分辨率或缩放不同、0.9 阈值过严），任务就在这里静默死循环——
        界面还显示「运行中」，日志却停在「Page arrived page_realm_raid」之后再无一行，
        用户完全看不出发生了什么（这正是 2026-07-27 复现的现象）。

        现在改为：限时轮询 + 明确日志；超时就跳过「锁定阵容」这一步继续跑，
        绝不再把整个任务吞掉。锁定状态不对顶多是阵容没锁，远好过永久卡死。
        :param lock_team_enable: True 需要锁定阵容，False 需要解除锁定
        :param timeout: 最长尝试秒数
        :return: True 表示达成目标状态；False 表示超时跳过
        """
        start = time.time()
        want = 'lock' if lock_team_enable else 'unlock'
        logger.info(f'Ensure team {want} (timeout {timeout}s)')
        if lock_team_enable:
            while time.time() - start < timeout:
                self.screenshot()
                if self.appear_then_click(self.I_UNLOCK, interval=1):
                    continue
                if self.appear_then_click(self.I_UNLOCK_2, interval=1):
                    continue
                if self.appear(self.I_LOCK_2, threshold=0.9):
                    logger.info(f'Team locked ({self.I_LOCK_2.name})')
                    return True
                if self.appear(self.I_LOCK, threshold=0.9):
                    logger.info(f'Team locked ({self.I_LOCK.name})')
                    return True
        else:
            while time.time() - start < timeout:
                self.screenshot()
                if self.appear_then_click(self.I_LOCK, interval=1):
                    continue
                if self.appear_then_click(self.I_LOCK_2, interval=1):
                    continue
                if self.appear(self.I_UNLOCK_2, threshold=0.9):
                    logger.info(f'Team unlocked ({self.I_UNLOCK_2.name})')
                    return True
                if self.appear(self.I_UNLOCK, threshold=0.9):
                    logger.info(f'Team unlocked ({self.I_UNLOCK.name})')
                    return True
        logger.warning(f'Ensure team {want} timeout after {timeout}s: '
                       f'识别不到锁定/未锁定图标，跳过这一步继续执行本任务。'
                       f'（若阵容锁定状态不符合预期，请检查游戏内该图标是否被活动 UI 遮挡）')
        return False

    def is_frog(self, screenshot: bool=True) -> bool:
        """
        判断是不是呱太活动
        :return:
        """
        if screenshot:
            self.screenshot()
        if self.appear(self.I_FROG_MEDAL):
            return True
        return False

    def check_ticket(self, base: int=0) -> bool:
        """
        检查是不是有票， 检查这个票是否大于等于基准
        :param base:
        :return:
        """
        if base < 0 or base > 30:
            logger.warning(f'It is not a valid base {base}')
            base = 0
        self.wait_until_appear(self.I_BACK_RED, wait_time=15)
        self.screenshot()
        cu, res, total = self.O_NUMBER.ocr(self.device.image)

        if total == 0:
            self.reward_detect_click(True)
            # 增加出现聊天框遮挡，处理奖励之后，重新识别票数
            cu, res, total = self.O_NUMBER.ocr(self.device.image)
        if cu == 0 and cu + res == total:
            logger.warning(f'Execute raid failed, no ticket')
            return False
        elif cu + res == total and cu < base:
            logger.warning(f'Execute raid failed, ticket is not enough')
            return False
        return True

    @cached_property
    def order_medal(self) -> ImageGrid:
        order_attack = self.config.realm_raid.raid_config.order_attack
        support_number = [0, 1, 2, 3, 4, 5]
        match = {
            0: self.I_MEDAL_0,
            1: self.I_MEDAL_1,
            2: self.I_MEDAL_2,
            3: self.I_MEDAL_3,
            4: self.I_MEDAL_4,
            5: self.I_MEDAL_5,
        }
        order = order_attack.replace(' ', '').replace('\n', '')
        order = re.split(r'>', order)
        order = [int(i) for i in order]
        order = [i for i in order if i in support_number]

        images = []
        for i in order:
            images.append(match[i])
        return ImageGrid(images)

    @cached_property
    def partition(self) -> list[RuleClick]:
        return [self.C_PARTITION_1, self.C_PARTITION_2, self.C_PARTITION_3, self.C_PARTITION_4, self.C_PARTITION_5,
                self.C_PARTITION_6, self.C_PARTITION_7, self.C_PARTITION_8, self.C_PARTITION_9]

    # ------------------------------------------------------- 等级识别（二开 handoff/23）
    # 九宫格里每个对手头像左上角都有一块菱形铭牌，上面是「等级」两位数字。
    # 这是实现「卡等级」的基础数据：九个等级里出现次数最多的那个 = 当前挑战等级。
    #
    # 坐标来历（不是拍脑袋，是量出来的）：
    #   用 CAPTURE_BOARD 存下 OAS 视角的 1280x720 原图，用铭牌底色（棕：R>G>B 且不过亮）
    #   做颜色掩膜定位九块铭牌，九块的外接框完全一致 ——
    #   列起点 x = 162 / 493 / 825（间隔 331/332），行起点 y = 171 / 306 / 441（间隔 135），
    #   菱形外接框 33x34。数字本体固定落在框内 (5,10)-(26,24)，上下左右都留有余量。
    #
    # 为什么不直接复用 O_FROG_1~9：那九个 roi 是作者为「呱太固定20级」调的，偏小且偏位，
    #   实测会把数字切掉或把铭牌边框读成多余数字（位次4读成8、位次5读空、位次8读成160）。
    LEVEL_ROI_X = (162, 493, 825)     # 三列铭牌外接框的起点 x
    LEVEL_ROI_Y = (171, 306, 441)     # 三行铭牌外接框的起点 y
    LEVEL_ROI_W = 33                  # 菱形外接框宽
    LEVEL_ROI_H = 34                  # 菱形外接框高

    LEVEL_MIN = 1                     # 合法等级下界
    LEVEL_MAX = 60                    # 合法等级上界（阴阳师满级 60），超出一律判为「没读到」

    @cached_property
    def level_ocr(self) -> list:
        """九个位次的等级 OCR 规则，顺序与 self.partition 一致：从左到右、从上到下。"""
        rules = []
        for row, y in enumerate(self.LEVEL_ROI_Y):
            for col, x in enumerate(self.LEVEL_ROI_X):
                roi = (x, y, self.LEVEL_ROI_W, self.LEVEL_ROI_H)
                rules.append(LevelOcr(roi=roi, area=roi, mode='Digit', method='Default',
                                      keyword='', name=f'level_{row * 3 + col + 1}'))
        return rules

    def read_levels(self, image=None) -> list:
        """读出九个位次的等级。读不到 / 明显不合理的位置返回 0（后续一律不参与判断）。

        单纯读数，不点击、不改变任何状态，所以可以安全地在任何时候调用。
        """
        if image is None:
            image = self.device.image
        levels = []
        for rule in self.level_ocr:
            try:
                value = rule.ocr(image)
                value = int(value) if value else 0
            except Exception:  # noqa: BLE001
                value = 0
            # 兜底：OCR 偶尔会把边框噪点拼成 601 这种三位数，直接判为没读到，
            # 好过让一个假等级污染「众数=挑战等级」的计算。
            if value and not (self.LEVEL_MIN <= value <= self.LEVEL_MAX):
                logger.warning(f'{rule.name} 读到不合理的等级 {value}，按未识别处理')
                value = 0
            levels.append(value)
        return levels

    def log_levels(self, image=None) -> list:
        """把九个位次的等级按 3x3 排版打进日志，方便和模拟器画面逐格核对。"""
        levels = self.read_levels(image)
        logger.info('等级识别 [位次:等级] '
                    + ' | '.join(f'{i + 1}:{lv if lv else "?"}' for i, lv in enumerate(levels)))
        logger.info(f'   排布  {levels[0]:>3} {levels[1]:>3} {levels[2]:>3}')
        logger.info(f'         {levels[3]:>3} {levels[4]:>3} {levels[5]:>3}')
        logger.info(f'         {levels[6]:>3} {levels[7]:>3} {levels[8]:>3}')
        logger.info(f'   当前挑战等级（九格众数）= {self.current_challenge_level(levels)}')
        return levels

    # 采集序号：同一次任务里多次存盘时用来区分先后（board_01_enter.png、board_02_win.png…）
    _board_seq = 0

    def dump_board(self, tag: str = '') -> str:
        """把 OAS 自己看到的 1280x720 原始棋盘存一张，用来裁「破」印/「失败箭头」模板。

        为什么必须用 OAS 的截图而不是人工截屏：模板匹配要求和运行时的分辨率、
        色彩通道完全一致，人工截屏（缩放过的窗口）裁出来的模板匹配分会明显偏低。
        device.image 是 RGB，磁盘上的模板 PNG 是普通 BGR，所以存盘前转一次。
        """
        try:
            ScriptTask._board_seq += 1
            os.makedirs('./log/board', exist_ok=True)
            path = f'./log/board/board_{ScriptTask._board_seq:02d}_{tag}.png'
            cv2.imwrite(path, cv2.cvtColor(self.device.image, cv2.COLOR_RGB2BGR))
            # 同时覆盖一份固定文件名，方便「只看最新一张」的场景
            cv2.imwrite('./log/board/realm_raid_board.png',
                        cv2.cvtColor(self.device.image, cv2.COLOR_RGB2BGR))
            logger.info(f'已保存结界突破棋盘原图：{path}')
            return path
        except Exception as error:  # noqa: BLE001
            logger.warning(f'保存棋盘截图失败（不影响任务）：{error}')
            return ''

    @staticmethod
    def current_challenge_level(levels: list) -> int:
        """挑战等级 = 九个对手等级里出现次数最多的那个（众数）。

        规则由玩家确认：九格等级基本相同，占多数的那一档就是当前挑战等级。
        读不到的位次（0）不参与统计；并列时取**较大**的那个，
        因为宁可判高也不要判低 —— 判低会误以为已经卡到目标等级而停止降级。
        """
        counter = {}
        for lv in levels:
            if lv:
                counter[lv] = counter.get(lv, 0) + 1
        if not counter:
            return 0
        return max(counter.items(), key=lambda kv: (kv[1], kv[0]))[0]

    def dump_level_debug(self, image=None, tag: str = '') -> str:
        """把九块铭牌「预处理之后」的样子拼成一张图存盘，用来肉眼核对 OCR 吃到的是什么。

        只在校准阶段用（LEVEL_DEBUG=True），失败不影响任务。
        """
        try:
            if image is None:
                image = self.device.image
            tiles = []
            for row, y in enumerate(self.LEVEL_ROI_Y):
                line = []
                for col, x in enumerate(self.LEVEL_ROI_X):
                    crop = image[y:y + self.LEVEL_ROI_H, x:x + self.LEVEL_ROI_W]
                    tile = self.level_ocr[row * 3 + col].pre_process(crop)
                    cv2.putText(tile, str(row * 3 + col + 1), (4, 26),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                    line.append(tile)
                tiles.append(np.hstack(line))
            os.makedirs('./log/board', exist_ok=True)
            path = f'./log/board/level_ocr{tag}.png'
            cv2.imwrite(path, np.vstack(tiles))
            logger.info(f'已保存等级识别调试图：{path}')
            return path
        except Exception as error:  # noqa: BLE001
            logger.warning(f'保存等级识别调试图失败（不影响任务）：{error}')
            return ''

    def find_one(self, screenshot: bool=True) -> tuple:
        """
        找到一个可以打的，并且检查一下是不是这一个的是第几个的
        我们约定次序是：从左到右 上到下
        1 2 3
        4 5 9
        7 8 9
        :return: 返回的第一个参数是一个RuleImage, 第二个参数是位置信息
        如果没有找到，返回None, None
        """
        if screenshot:
            self.screenshot()
        image = self.device.image
        # https://github.com/runhey/OnmyojiAutoScript/issues/71
        # 如果开始失败后继挑战剩下的
        if self.config.realm_raid.raid_config.when_attack_fail == WhenAttackFail.CONTINUE:
            for i, roi in enumerate(self.false_roi):
                self.false_image.roi_back = roi
                if not self.appear(self.false_image):
                    continue
                logger.info(f'Position {i+1} is a failed')
                x, y, w, h = self.partition[i].roi_back
                image[y:y+h, x:x+w, ...] = 0
        # -----------------------------------------------------
        target = self.order_medal.find_anyone(image)
        if target:
            center = target.front_center()
            for i, click in enumerate(self.partition):
                x1, x2, y1, y2 = click.roi_front[0], click.roi_front[0] + click.roi_front[2], \
                                 click.roi_front[1], click.roi_front[1] + click.roi_front[3]
                if x1 < center[0] < x2 and y1 < center[1] < y2:
                    logger.info(f'Find one medal [{target}], order is {i + 1}')
                    return target, i + 1

        return None, None

    def check_medal_is_frog(self, is_activity: False, target: RuleImage, order: int) -> bool:
        """
        检查这个是不是呱太，为此之前你还需要判断是不是 处于呱太活动的
        :param target:
        :param is_activity: 如果不是呱太活动，那么就不需要检查了
        :param order:
        :return:
        """
        if not is_activity:
            return False
        # 好像呱太的位置是只有 789这三个
        if order < 7:
            return False
        # 有时候四星可能和五星的混一起
        if target != self.I_MEDAL_5 and target != self.I_MEDAL_4:
            return False
        match_ocr = {
            1: self.O_FROG_1,
            2: self.O_FROG_2,
            3: self.O_FROG_3,
            4: self.O_FROG_4,
            5: self.O_FROG_5,
            6: self.O_FROG_6,
            7: self.O_FROG_7,
            8: self.O_FROG_8,
            9: self.O_FROG_9,
        }
        target_ocr = match_ocr[order]
        self.screenshot()
        if target_ocr.ocr(self.device.image) == 20:
            logger.info(f'Find frog medal [{target}]')
            return True
        return False

    def reward_detect_click(self, screenshot: bool=True) -> bool:
        """
        检测是否出现 每三次就有奖励的界面, 有就领取
        :return:
        """
        if screenshot:
            self.screenshot()
        # 由于更改识别顺序，退出战斗之后，需要先等待回到个人突破界面，即识别到红色退出按钮，再进行奖励判断
        self.wait_until_appear(self.I_BACK_RED, wait_time=15)
        text = self.O_TEXT.ocr(self.device.image)
        # 识别突破卷区域，如果识别到了且其中含有文字，即有聊天框遮挡则进入循环，等待三胜奖励出现并点击，循环退出条件为识别到票（即*/*的形式）
        if text != "":
            if re.search(r'[\u4e00-\u9fff]', text):
                while 1:
                    self.screenshot()
                    result = self.O_TEXT.ocr(self.device.image)
                    if not re.search(r'[\u4e00-\u9fff]', result) and re.search(r'(\d+)/(\d+)', result):
                        return True
                    if self.appear_then_click(self.I_SOUL_RAID, interval=1.5):
                        continue

        # if self.appear(self.I_SOUL_RAID):
        #     self.screenshot()
        #     # 稳定一次的截图时间
        #     # 再次判断是否出现的
        #     if not self.appear(self.I_SOUL_RAID):
        #         return False
        #     while 1:
        #         self.screenshot()
        #         if not self.appear(self.I_SOUL_RAID, threshold=0.7):
        #             return True
        #         if self.appear_then_click(self.I_SOUL_RAID, interval=1.5):
        #             continue

    def check_refresh(self, screenshot: bool=True) -> bool:
        """
        检查是否出现了刷新的按钮
        如果可以刷新就刷新，返回True
        如果在CD中，就返回False
        :return:
        """
        if screenshot:
            self.screenshot()
        if not self.appear(self.I_FRESH):
            logger.info(f'No find refresh button and it is in CD')
            return False
        # 【二开修复 handoff/20】这两个 while 1 原本也没有超时：
        # 点了「刷新」却等不到确认弹窗（或弹窗关不掉）时会静默卡死，这里统一加 15 秒上限。
        timeout = 15
        start = time.time()
        while time.time() - start < timeout:
            self.screenshot()
            if self.appear(self.I_FRESH_ENSURE):
                break
            if self.appear_then_click(self.I_FRESH, interval=1):
                continue
        else:
            logger.warning('Refresh: 点击刷新后 15s 内没等到确认弹窗，按“刷新失败”处理')
            return False
        start = time.time()
        while time.time() - start < timeout:
            self.screenshot()
            if not self.appear(self.I_FRESH_ENSURE):
                return True
            if self.appear_then_click(self.I_FRESH_ENSURE, interval=1):
                continue
        logger.warning('Refresh: 确认弹窗 15s 内没有消失，按已刷新继续')
        return True

    def fire(self, order: int):
        """
        挑战
        :param order:  第几个
        :return:
        """
        retry_clean = 0
        while not self.appear(self.I_RR_PERSON):
            # 【二开修复 handoff/20】原来这里只打一条 warning 就继续 while，等于永远出不去：
            # 一旦「个人」标题识别不到，就会一直点屏幕顶部并无限重试，日志刷屏却永不结束。
            # 现在超过上限就抛 GameStuckError，交给 OAS 自己的异常处理（保存截图 / 重启流程）。
            if retry_clean > 20:
                logger.critical('Stuck too long: 识别不到「个人」标题(I_RR_PERSON)，'
                                '放弃本次挑战并交给异常处理')
                raise GameStuckError('RealmRaid: I_RR_PERSON not found after 20 retries')

            logger.info("Title not found! Checking for popups or rewards...")
            
            # 如果看到了“刷新确认”弹窗 (I_FRESH_ENSURE 是右边的确定)
            if self.appear(self.I_FRESH_ENSURE):
                logger.info("Refresh popup detected! Clicking CANCEL (Red Button).")
                # 点击“取消”按钮的坐标 (基于1280x720分辨率)
                self.device.click(x=530, y=460) 
                time.sleep(1.5)
                self.screenshot()
                continue

            # 点击屏幕正上方 (640, 50)，而不是右下角，避免误触"刷新"按钮
            logger.info("Clicking safe area to clear rewards...")
            self.device.click(x=640, y=50)  
            time.sleep(1.5)
            self.screenshot()
            retry_clean += 1
        
        click = self.partition[order - 1]
        
        # 进攻循环
        while 1:
            self.screenshot()
            
            # 双重保险：如果在进攻阶段又弹出了窗口，也把它关掉
            if self.appear(self.I_FRESH_ENSURE):
                logger.info("Refresh popup blocking attack! Clicking CANCEL.")
                self.device.click(x=530, y=460) # 点取消
                time.sleep(1.0)
                continue

            if not self.appear(self.I_RR_PERSON, threshold=0.8):
                break
                
            if self.appear_then_click(self.I_FIRE, interval=1):
                continue
            if self.click(click, interval=1.8):
                continue
                
        logger.info(f'Click fire {order} success')

    @cached_property
    def false_roi(self) -> list:
        width = 86
        height = 64
        x1 = 386
        x2 = 714
        x3 = 1047
        y1 = 143
        y2 = 277
        y3 = 414
        return [
            [x1, y1, width, height],  # 左上角
            [x2, y1, width, height],
            [x3, y1, width, height],
            [x1, y2, width, height],  # 左中
            [x2, y2, width, height],
            [x3, y2, width, height],
            [x1, y3, width, height],  # 左下
            [x2, y3, width, height],
            [x3, y3, width, height],
        ]

    @cached_property
    def false_image(self):
        return RuleImage(roi_front=(0 ,0, 63, 32),
                         roi_back=(0, 0, 100, 100),
                         threshold=0.8,
                         method="Template matching",
                         file="./tasks/RyouToppa/dev/loser_sign_1.png")


if __name__ == "__main__":
    from module.config.config import Config
    from module.device.device import Device
    config = Config('oas1')
    device = Device(config)
    t = ScriptTask(config, device)

    t.run()

