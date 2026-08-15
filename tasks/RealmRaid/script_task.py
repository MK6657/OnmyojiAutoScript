# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
import re
import os
import hashlib
from collections import Counter
from datetime import datetime
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
    import tasks.RealmRaid.assets as _realm_raid_assets_module
    import tasks.Component.GeneralBattle.assets as _general_battle_assets_module
    import tasks.Component.GeneralBattle.general_battle as _general_battle_module
    _importlib.reload(_realm_raid_assets_module)
    # GeneralBattle inherits the click rules at import time. Reload the asset
    # module first or updated green-mark coordinates remain cached in the class.
    _importlib.reload(_general_battle_assets_module)
    _importlib.reload(_general_battle_module)
except Exception as _reload_error:  # noqa: BLE001
    from module.logger import logger as _reload_logger
    _reload_logger.warning(f'reload RealmRaid modules failed, use cached modules: {_reload_error}')

from tasks.Component.GeneralBattle.general_battle import GeneralBattle, PresetLookupError
from tasks.Component.GeneralBattle.preset_name_selector import InvalidPresetConfigError
from tasks.Component.GeneralBattle.preset_name_selector import normalize_preset_name
from tasks.Component.SwitchSoul.assets import SwitchSoulAssets
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_battle, page_realm_raid, page_main, page_shikigami_records
from tasks.RealmRaid.assets import RealmRaidAssets
from tasks.RealmRaid.config import RealmRaid, RaidMode, AttackNumber, WhenAttackFail
from tasks.RealmRaid.level_mode import (
    BoardSnapshot,
    CheckpointStore,
    LevelAction,
    LevelMode,
    PendingAction,
    RealmRaidCheckpoint,
    cached_board_levels,
    decide_next_action,
    generation_changed,
    reconcile_checkpoint,
    schedule_after_cooldown,
)
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul


from module.logger import logger
from module.exception import (
    GameStuckError,
    GameTooManyClickError,
    TaskEnd,
)
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
LEVEL_DEBUG = False
CAPTURE_BOARD = False
CAPTURE_ONLY = False


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


class BrokenLevelOcr(LevelOcr):
    """Read the still-visible level plaque after a card has been marked broken."""

    LEVEL_MIN = 1
    LEVEL_MAX = 60

    def ocr(self, image, keyword=None):
        """Use a high-contrast pass first, then retain the adaptive fallback.

        The current broken-card artwork makes the adaptive pass read the real
        ``60`` plaque as ``BO`` on some frames. Otsu reliably separates that
        plaque, while a few other levels lose their second digit under Otsu.
        Keep the bounded fallback and prefer a two-digit value when available.
        """
        self._broken_ocr_variant = 'otsu'
        primary = self.ocr_single_line(image)
        if isinstance(primary, int) and self.LEVEL_MIN <= primary <= self.LEVEL_MAX:
            if primary >= 10:
                return primary

        self._broken_ocr_variant = 'adaptive'
        fallback = self.ocr_single_line(image)
        if isinstance(fallback, int) and 10 <= fallback <= self.LEVEL_MAX:
            return fallback
        return primary or fallback or 0

    def pre_process(self, image):
        try:
            if image is None or image.size == 0:
                return image

            # The broken overlay darkens both the plaque and its digits. Restrict
            # OCR to the digit body, then use a local threshold instead of the
            # absolute brightness threshold used by normal cards.
            inner = image[8:26, 5:28]
            if inner.shape[:2] != (18, 23):
                return super().pre_process(image)
            gray = cv2.cvtColor(inner, cv2.COLOR_RGB2GRAY) if inner.ndim == 3 else inner
            if getattr(self, '_broken_ocr_variant', 'otsu') == 'otsu':
                _, light = cv2.threshold(
                    gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
                )
            else:
                light = cv2.adaptiveThreshold(
                    gray,
                    255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY,
                    11,
                    0,
                )
            binary = 255 - light
            binary = cv2.copyMakeBorder(
                binary, 8, 8, 10, 10, cv2.BORDER_CONSTANT, value=255
            )
            binary = cv2.resize(
                binary, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC
            )
            return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        except Exception as error:  # noqa: BLE001
            logger.warning(f'已攻破等级铭牌预处理失败，退回普通规则：{error}')
            return super().pre_process(image)


class AttackRecordOcr(RuleOcr):
    """Reject low-confidence digits for the 0-9 attack record counter.

    The global digit OCR accepts scores down to 0.30 when any digit is present.
    On the current RealmRaid artwork that turned a clearly displayed 4 into a
    score-0.36 6. A rejected result remains auxiliary evidence: the nine broken
    stamps still provide the committed win count, while a high-confidence
    counter mismatch continues to make the board unsafe.
    """

    min_score = 0.6

    def after_process(self, result):
        # Digit.after_process turns an empty OCR result into 0.  That value is
        # indistinguishable from a real empty-board counter, so preserve the
        # uncertainty and let the visible broken marks remain the fallback.
        if result is None or not str(result).strip():
            return None
        text = str(result)
        for old, new in {
            'I': '1', 'D': '0', 'S': '5', 'B': '8',
            '？': '2', '?': '2', 'd': '6', 'o': '0', 'O': '0', '→': '1',
        }.items():
            text = text.replace(old, new)
        digits = ''.join(char for char in text if char.isdigit())
        if not digits:
            return None
        return int(digits)

    def ocr(self, image, keyword=None):
        result = self.ocr_single(image)
        if result is None or result == '':
            return None
        return int(result)


class ScriptTask(GeneralBattle, GameUi, SwitchSoul, RealmRaidAssets):
    medal_grid: ImageGrid = None
    MEDAL_RELAXED_THRESHOLD = 0.75

    def run(self):
        try:
            self.run_2()
        except (GameStuckError, GameTooManyClickError) as error:
            if not self.config.realm_raid.level_mode_config.enable:
                raise
            # Cover navigation and preset pre-application as well as the board
            # loop. The global handler would otherwise schedule a game restart.
            logger.error(
                'Target level mode task aborted without restarting the game: '
                f'{type(error).__name__}: {error}'
            )
            try:
                self.dump_board('level_mode_task_error')
            except Exception as dump_error:  # noqa: BLE001
                logger.warning(f'Level mode error screenshot failed: {dump_error}')
            retry_at = ScriptTask.level_short_retry_target()
            logger.info(
                f'Target level mode exception retry scheduled at {retry_at.isoformat(timespec="seconds")}'
            )
            self.set_next_run(
                task='RealmRaid',
                success=False,
                finish=True,
                server=False,
                target=retry_at,
            )
            raise TaskEnd.failed(
                'RealmRaid target-level setup failed',
                next_run=retry_at,
            )

    def open_current_team_preset(self, timeout: float = 15) -> None:
        """Open the current Records team-preset page without its obsolete page check."""
        self.screenshot()
        if self._is_current_preset_page():
            return
        if self.appear(SwitchSoulAssets.I_SOUL_PRESET, threshold=0.8):
            self._open_records_preset_page(timeout=timeout)
            return

        # The upstream Records page check is stale in the current game version.
        # Only use the generic navigator to reach the still-recognizable courtyard,
        # then enter Records and wait for its current Preset control directly.
        self.ui_get_current_page()
        self.ui_goto(page_main)

        deadline = time.time() + 8
        while time.time() < deadline:
            self.screenshot()
            if self.appear_then_click(
                self.I_MAIN_GOTO_SHIKIGAMI_RECORDS,
                interval=1,
            ):
                break
            time.sleep(0.3)
        else:
            raise PresetLookupError(
                '无法从庭院进入式神录，已停止本次任务，未开始挑战'
            )

        self._open_records_preset_page(timeout=timeout)

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

    def medal_fire(self, timeout: float = 30.0) -> bool:
        """
        点击勋章
        :return:
        """
        # 点击勋章的挑战 和挑战
        time.sleep(0.2)
        is_click = False
        deadline = time.monotonic() + max(1.0, float(timeout))
        while time.monotonic() < deadline:
            self.screenshot()

            if self._realm_raid_fire_visible():
                break

            if self.appear_then_click(self.I_SOUL_RAID, interval=1.5):
                while time.monotonic() < deadline:
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
        else:
            raise GameStuckError(
                f'RealmRaid medal selection did not reach the attack button within {timeout:.1f}s'
            )
        logger.info(f'Click Medal')

        # 点击挑战
        self.wait_until_appear(self.I_FIRE, wait_time=15)
        while time.monotonic() < deadline:
            self.screenshot()
            if self._click_realm_raid_fire(interval=2):
                continue
            if not self._realm_raid_fire_visible():
                break
        else:
            raise GameStuckError(
                f'RealmRaid attack button did not disappear within {timeout:.1f}s'
            )
        logger.info(f'Click {self.I_FIRE.name}')
        return True

    def _realm_raid_fire_visible(self) -> bool:
        """Recognize both the legacy board button and the current detail-card button."""
        return self.appear(self.I_FIRE, threshold=0.8) or self.appear(self.I_FIRE_CURRENT)

    def _click_realm_raid_fire(self, interval: float = 1.0) -> bool:
        """Click the first confirmed RealmRaid attack-button variant."""
        if self.appear_then_click(self.I_FIRE, interval=interval, threshold=0.8):
            return True
        return self.appear_then_click(self.I_FIRE_CURRENT, interval=interval)

    def _realm_raid_partition_targets(self, order: int) -> list[RuleClick]:
        """Return bounded, semantic click areas for one target card.

        The medal OCR selects the card order, but the old fallback treated the
        entire partition ROI as a hitbox.  That made a retry click blank card
        pixels and falsely logged it as a successful selection.  Keep each
        candidate small and explainable: the first medal is the historical
        working anchor, followed by the portrait area used by the current
        card layout.  The name area is intentionally excluded because a
        selected card treats it as a Friend Book entry point.
        """
        source = self.partition[order - 1]
        x, y, width, height = (int(value) for value in source.roi_front)

        def area(left: int, top: int, candidate_width: int, candidate_height: int,
                 suffix: str) -> RuleClick:
            left = max(0, left)
            top = max(0, top)
            candidate_width = max(1, min(candidate_width, 1280 - left))
            candidate_height = max(1, min(candidate_height, 720 - top))
            roi = (left, top, candidate_width, candidate_height)
            return RuleClick(roi_front=roi, roi_back=roi,
                             name=f'{source.name}:{suffix}')

        matched = getattr(self, '_level_target_image', None)
        if matched is not None:
            try:
                center = matched.front_center()
                logger.info(
                    f'RealmRaid target selection uses matched medal evidence: '
                    f'target={order}, center={center}; click candidates are bounded'
                )
            except Exception as error:  # noqa: BLE001
                logger.debug(f'RealmRaid matched medal evidence unavailable: {error}')

        self._level_target_image = None
        return [
            area(
                x + 6,
                y + height - 51,
                min(42, width - 12),
                32,
                'first_medal',
            ),
            area(
                x - 62,
                y + 14,
                60,
                min(78, height - 20),
                'portrait',
            ),
        ]

    def _realm_raid_partition_target(self, order: int) -> RuleClick:
        """Backward-compatible access to the primary target click area."""
        return self._realm_raid_partition_targets(order)[0]

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
            if not self.run_general_battle_back(config.general_battle_config):
                return False

            self.medal_fire()
            if not self.run_general_battle_back(config.general_battle_config):
                return False

            self.medal_fire()
            if not self.run_general_battle_back(config.general_battle_config):
                return False

            self.medal_fire()
            if not self.run_general_battle_back(config.general_battle_config):
                return False

        # 打九次
        for i in range(9):
            if not self.is_ticket():
                return False
            self.medal_fire()
            self.run_general_battle(config.general_battle_config)
            self.wait_until_appear(self.I_BACK_RED, wait_time=15)

        return True

    # ------------------------------------------------------------------------------------------------------------------
    def prepare_realm_raid_battle(self, config: RealmRaid) -> None:
        """Run the single RealmRaid preparation phase.

        Team preset and soul preset remain separate business intents, but they
        share one navigation/lock boundary.  This prevents the old soul entry
        from failing before the newer named team entry gets a chance to run.
        """
        battle_config = config.general_battle_config
        soul_config = config.switch_soul_config
        self._battle_preset_preapplied = False
        # The named preset flow deliberately unlocks the first battle. The
        # next battle, not the lock icon alone, proves that locking took effect.
        self._battle_lock_expected_active = False

        preset_group_name = str(getattr(battle_config, 'preset_group_name', '') or '').strip()
        preset_team_name = str(getattr(battle_config, 'preset_team_name', '') or '').strip()
        team_name_partial = bool(preset_group_name or preset_team_name)
        team_name_complete = bool(preset_group_name and preset_team_name)
        team_requested = bool(getattr(battle_config, 'preset_enable', False))
        soul_by_name = bool(getattr(soul_config, 'enable_switch_by_name', False))
        soul_by_index = bool(getattr(soul_config, 'enable', False)) and not soul_by_name
        soul_requested = soul_by_name or soul_by_index
        self._lock_after_first_battle_pending = bool(
            team_requested and team_name_complete and battle_config.lock_team_enable
        )
        self._team_preset_covers_soul = False

        logger.info(
            'PREPARE_START '
            f'team_requested={team_requested}, soul_requested={soul_requested}, '
            f'lock_desired={getattr(battle_config, "lock_team_enable", False)}'
        )

        if team_requested and team_name_partial and not team_name_complete:
            raise InvalidPresetConfigError(
                '预设队伍配置不完整：分组名称和队伍名称必须同时填写'
            )

        # Validate the numeric compatibility path before navigating anywhere.
        # The disabled default -1,-1 remains valid because soul_by_index is false.
        if soul_by_index:
            SwitchSoul.validate_switch_config(
                True,
                soul_config.switch_group_team,
            )

        unlock_confirmed = True
        if team_requested and team_name_complete and battle_config.lock_team_enable:
            # Lock state is only meaningful on the RealmRaid board.  Reach it
            # before attempting the unlock, then the preset helpers can return
            # to Records and the caller will enter the board again afterward.
            self.ui_get_current_page()
            self.ui_goto(page_realm_raid)
            logger.info('LOCK_STATE desired=locked, unlock_required=true')
            unlock_confirmed = self.ensure_lock(False, timeout=12)
            logger.info(
                f'LOCK_STATE unlock_result={"confirmed" if unlock_confirmed else "unconfirmed"}'
            )
        else:
            logger.info(
                'LOCK_STATE '
                f'desired={"locked" if battle_config.lock_team_enable else "unlocked"}, '
                'unlock_required=false'
            )

        if team_requested and team_name_complete:
            if not unlock_confirmed:
                # User-confirmed fallback: an unconfirmed unlock must not block
                # soul preparation and the current battle attempt.
                logger.warning(
                    'TEAM_PRESET_RESULT result=skipped_unlock_unconfirmed; '
                    'continue with soul preset and current team'
                )
            else:
                try:
                    self.open_current_team_preset()
                    self.preapply_preset_team_from_records(
                        preset_group_name,
                        preset_team_name,
                        page_already_open=True,
                    )
                except PresetLookupError as error:
                    logger.error(f'Preset entry stopped before battle: {error}')
                    raise
                self._team_preset_covers_soul = bool(
                    soul_by_name
                    and normalize_preset_name(preset_group_name)
                    == normalize_preset_name(soul_config.group_name)
                    and normalize_preset_name(preset_team_name)
                    == normalize_preset_name(soul_config.team_name)
                )
                logger.info('TEAM_PRESET_RESULT result=applied')
        elif team_requested:
            # Empty names keep the old numeric compatibility path inside the
            # first battle's preparation page.
            logger.info('TEAM_PRESET_RESULT result=deferred_legacy_compatibility')
        else:
            logger.info('TEAM_PRESET_RESULT result=disabled')

        if soul_by_name:
            if self._team_preset_covers_soul:
                logger.info(
                    'SOUL_PRESET_RESULT result=covered_by_team_preset; '
                    'skip duplicate composite preset action'
                )
            else:
                self.ui_get_current_page()
                self.ui_goto(page_shikigami_records)
                soul_result = self.run_switch_soul_by_name(
                    soul_config.group_name,
                    soul_config.team_name,
                )
                if soul_result is False:
                    raise GameStuckError('RealmRaid named soul preset was not applied')
                logger.info('SOUL_PRESET_RESULT result=applied_by_name')
        elif soul_by_index:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul(soul_config.switch_group_team)
            logger.info('SOUL_PRESET_RESULT result=applied_by_index')
        else:
            logger.info('SOUL_PRESET_RESULT result=disabled')

        logger.info(
            'PREPARE_RESULT result=ready '
            f'team={team_requested}, soul={soul_requested}, '
            f'lock_desired={battle_config.lock_team_enable}'
        )

    @staticmethod
    def _realm_raid_page_name(page) -> str:
        if page is None:
            return 'none'
        return getattr(page, 'name', str(page))

    def _stop_realm_raid_for_scene(self, current_page, reason: str) -> None:
        """Stop RealmRaid safely when the client is in an incompatible scene.

        In particular, never use the generic page graph to leave an active battle
        here.  A RealmRaid task can be scheduled while another task's battle is
        still running, and clicking that battle's back control would change the
        user's in-game state and potentially lose its result.
        """
        page_name = self._realm_raid_page_name(current_page)
        logger.error(
            'REALM_RAID_SCENE_GATE result=blocked '
            f'current={page_name} reason={reason}'
        )
        try:
            self.screenshot()
            dump_board = getattr(self, 'dump_board', None)
            if callable(dump_board):
                dump_board(f'scene_guard_{reason}')
        except Exception as error:  # noqa: BLE001
            logger.warning(f'RealmRaid scene-guard evidence save failed: {error}')

        retry_at = self.level_short_retry_target()
        self.set_next_run(
            task='RealmRaid',
            success=False,
            finish=True,
            server=False,
            target=retry_at,
        )
        logger.warning(
            'RealmRaid scene guard paused the task without touching the current page; '
            f'retry scheduled at {retry_at.isoformat(timespec="seconds")}'
        )
        raise TaskEnd.deferred(
            f'RealmRaid scene guard: {reason}',
            next_run=retry_at,
        )

    def _realm_raid_startup_scene_guard(self):
        """Reject startup from an active battle before preset/navigation code runs."""
        current_page = self.ui_get_current_page()
        logger.info(
            'REALM_RAID_SCENE_GATE stage=startup '
            f'current={self._realm_raid_page_name(current_page)}'
        )
        if current_page == page_battle:
            self._stop_realm_raid_for_scene(
                current_page,
                reason='active_battle_page',
            )
        return current_page

    def _confirm_realm_raid_board(self, config: RealmRaid) -> None:
        """Require a fresh RealmRaid page before any lock or battle action."""
        current_page = self.ui_get_current_page()
        page_name = self._realm_raid_page_name(current_page)
        if current_page == page_battle:
            self._stop_realm_raid_for_scene(
                current_page,
                reason='active_battle_after_navigation',
            )
        if current_page != page_realm_raid:
            self._stop_realm_raid_for_scene(
                current_page,
                reason=f'expected_realm_raid_got_{page_name}',
            )

        self.screenshot()
        if not self.appear(self.I_CHECK_REALM_RAID, threshold=0.7):
            self._stop_realm_raid_for_scene(
                current_page,
                reason='realm_raid_marker_missing',
            )

        ticket_state = 'unreadable'
        ticket_values = None
        try:
            ticket_values = self.O_NUMBER.ocr(self.device.image)
            if isinstance(ticket_values, tuple) and len(ticket_values) >= 3:
                ticket_current, ticket_rest, ticket_total = ticket_values[:3]
                ticket_state = f'{ticket_current}+{ticket_rest}/{ticket_total}'
        except Exception as error:  # noqa: BLE001
            logger.warning(f'RealmRaid entry ticket OCR failed: {error}')

        level_gate = (
            'stable_board_observation'
            if getattr(config.level_mode_config, 'enable', False)
            else 'not_required'
        )
        logger.info(
            'REALM_RAID_SCENE_GATE result=board_confirmed '
            f'page={page_name} tickets={ticket_state} level_gate={level_gate}'
        )

    def run_2(self):
        con = self.config.realm_raid
        self._realm_raid_startup_scene_guard()
        prepare = getattr(self, 'prepare_realm_raid_battle', None)
        if prepare is None:
            # Keep lightweight test/dry-run harnesses that only borrow run_2
            # compatible with the new preparation boundary.
            ScriptTask.prepare_realm_raid_battle(self, con)
        else:
            prepare(con)

        self.ui_get_current_page()
        navigation_result = self.ui_goto(page_realm_raid)
        if navigation_result is False:
            self._stop_realm_raid_for_scene(
                getattr(self, 'ui_current', None),
                reason='realm_raid_navigation_failed',
            )
        self._confirm_realm_raid_board(con)

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

            if CAPTURE_ONLY and not con.level_mode_config.enable:
                logger.info('CAPTURE_ONLY=True：素材已采集，本次任务到此结束，不进行任何挑战')
                self.set_next_run(task='RealmRaid', success=True, finish=True)
                raise TaskEnd.completed('RealmRaid completed')

        # 页面切换后的首帧和 Nemu IPC 取帧可能晚于页面到达事件；目标等级模式仍
        # 保持有限等待，给锁图标一个完整的稳定窗口，避免刚进页面就误判为未知状态。
        lock_timeout = 5 if con.level_mode_config.enable else 12
        lock_deferred_until_after_battle = getattr(
            self, '_lock_after_first_battle_pending', False
        )
        if lock_deferred_until_after_battle:
            logger.info(
                'LOCK_STATE initial_lock=deferred; '
                'first battle must complete before relock'
            )
            lock_confirmed = True
            self._battle_lock_expected_active = False
        else:
            lock_confirmed = self.ensure_lock(
                con.general_battle_config.lock_team_enable,
                timeout=lock_timeout,
            )
            self._battle_lock_expected_active = bool(
                con.general_battle_config.lock_team_enable and lock_confirmed
            )
        if not lock_confirmed:
            retry_at = self.level_short_retry_target()
            logger.error(
                f'RealmRaid team lock state is unconfirmed; pause and retry at '
                f'{retry_at.isoformat(timespec="seconds")}'
            )
            if con.level_mode_config.enable:
                self.finish_level_mode(
                    success=False,
                    target=retry_at,
                    reason='team_lock_unconfirmed',
                )
            self.finish_realm_raid_retry(
                target=retry_at,
                reason='team_lock_unconfirmed',
            )
        # 判断是否是呱太活动
        frog = self.is_frog(True)
        if frog:
            logger.info(f'Frog raid')

        if con.level_mode_config.enable and not frog:
            logger.info(
                f'Target level mode enabled: target={con.level_mode_config.target_level}, '
                f'single_step={con.level_mode_config.single_step}'
            )
            try:
                self.run_level_mode(con)
            except (GameStuckError, GameTooManyClickError) as error:
                # The target-level flow is still under supervised validation. Preserve its
                # pending checkpoint and stop this task without invoking the global app restart.
                logger.error(
                    'Target level mode action aborted without restarting the game: '
                    f'{type(error).__name__}: {error}'
                )
                try:
                    self.dump_board('level_mode_action_error')
                except Exception as dump_error:  # noqa: BLE001
                    logger.warning(f'Level mode error screenshot failed: {dump_error}')
                retry_at = ScriptTask.level_short_retry_target()
                logger.info(
                    f'Target level mode action retry scheduled at {retry_at.isoformat(timespec="seconds")}'
                )
                self.set_next_run(
                    task='RealmRaid',
                    success=False,
                    finish=True,
                    server=False,
                    target=retry_at,
                )
                raise TaskEnd.failed(
                    f'RealmRaid target-level action failed: {error}',
                    next_run=retry_at,
                )


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
                    for _ in range(4):
                        self.fire(index)
                        if not self.run_general_battle_back(
                                con.general_battle_config, exit_four=True):
                            self.finish_realm_raid_retry(
                                target=self.level_short_retry_target(),
                                reason='surrender_unconfirmed',
                            )
            elif self.check_medal_is_frog(frog, medal, index):
                # 如果挑战的这只是呱太的话，就要把锁定改为不锁定
                con.general_battle_config.lock_team_enable = False
            self.fire(index)
            last_battle = self.run_general_battle(con.general_battle_config)
            if lock_before:
                con.general_battle_config.lock_team_enable = lock_before
                self.retry_lock_after_battle(con.general_battle_config)
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
        if success:
            raise TaskEnd.completed('RealmRaid completed')
        raise TaskEnd.failed('RealmRaid battle flow failed')

    def finish_realm_raid_retry(
        self,
        target: datetime,
        reason: str,
        leave_current_page: bool = True,
    ) -> None:
        """Leave RealmRaid without a global restart and retry after a short delay."""
        if leave_current_page:
            try:
                self.ui_click(self.I_BACK_RED, self.I_CHECK_EXPLORATION)
                self.ui_get_current_page()
                self.ui_goto(page_main)
            except Exception as error:  # noqa: BLE001
                logger.warning(f'Leave RealmRaid page failed during retry scheduling: {error}')
        else:
            logger.info(
                'RealmRaid retry keeps current page untouched: '
                f'reason={reason}'
            )
        self.set_next_run(
            task='RealmRaid',
            success=False,
            finish=True,
            server=False,
            target=target,
        )
        logger.info(
            f'RealmRaid retry scheduled: reason={reason}, '
            f'target={target.isoformat(timespec="seconds")}'
        )
        raise TaskEnd.failed(
            f'RealmRaid retry after explicit failure: {reason}',
            next_run=target,
        )

    def retry_lock_after_battle(self, battle_config, timeout: float = 5.0) -> bool:
        """Retry the post-battle lock without blocking the next preparation.

        A failed re-lock is recoverable: the next battle still exposes the
        Prepare button, so that battle may proceed while this guard retries on
        the following board frame.
        """
        if not getattr(battle_config, 'lock_team_enable', False):
            self._battle_lock_expected_active = False
            return True
        if self.ensure_lock(True, timeout=timeout):
            self._battle_lock_expected_active = True
            logger.info(
                'LOCK_AFTER_BATTLE result=indicator_confirmed '
                'validation=pending_next_battle'
            )
            return True
        self._battle_lock_expected_active = False
        logger.warning(
            'LOCK_AFTER_BATTLE result=unconfirmed; '
            'next battle will use Prepare and retry the lock'
        )
        return False

    # ------------------------------------------------------- 目标等级模式（二开 Codex-05）

    @cached_property
    def level_failure_sign(self) -> RuleImage:
        return RuleImage(
            roi_front=(0, 0, 42, 24),
            roi_back=tuple(self.false_roi[0]),
            threshold=0.78,
            method='Template matching',
            file='./tasks/RyouToppa/dev/loser_sign_1.png|./tasks/RyouToppa/dev/loser_sign_2.png',
        )

    @cached_property
    def level_broken_sign(self) -> RuleImage:
        return RuleImage(
            roi_front=(0, 0, 25, 37),
            roi_back=tuple(self.partition[0].roi_back),
            threshold=0.80,
            method='Template matching',
            file='./tasks/RyouToppa/dev/finished_1.png|./tasks/RyouToppa/dev/finished_2.png',
        )

    @cached_property
    def attack_record_ocr(self) -> RuleOcr:
        # 数字位于“攻破记录”下方。0 的 OCR 结果与空结果相同，因此 0 只在没有破印时采用。
        roi = (210, 595, 30, 35)
        return AttackRecordOcr(roi=roi, area=roi, mode='Digit', method='Default',
                               keyword='', name='realm_raid_attack_record')

    def detect_level_board_marks(self, image=None) -> tuple[frozenset[int], frozenset[int]]:
        if image is None:
            image = self.device.image

        started_at = time.perf_counter()
        broken = set()
        for index, click in enumerate(self.partition, start=1):
            self.level_broken_sign.roi_back = tuple(click.roi_back)
            if self.level_broken_sign.match(image):
                broken.add(index)

        failure_marked = set()
        for index, roi in enumerate(self.false_roi, start=1):
            self.level_failure_sign.roi_back = tuple(roi)
            if self.level_failure_sign.match(image):
                failure_marked.add(index)

        # “破”印本身包含红色，且目标已经不可挑战；不把它同时当作失败箭头。
        failure_marked.difference_update(broken)
        logger.info(
            'REALM_RAID_BOARD_TIMING phase=marks '
            f'durationMs={(time.perf_counter() - started_at) * 1000:.1f} '
            f'brokenChecks={len(self.partition)} failureChecks={len(self.false_roi)} '
            f'broken={len(broken)} failure={len(failure_marked)}'
        )
        return frozenset(broken), frozenset(failure_marked)

    @staticmethod
    def _layout_hash(image, partitions) -> str:
        """Hash binarized opponent names, ignoring card lighting and status effects."""
        fingerprints = []
        for click in partitions:
            x, y, w, h = click.roi_back
            crop = image[y + 4:y + min(h, 52), x + 4:x + min(w, 145)]
            if crop.size == 0:
                continue
            gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY) if crop.ndim == 3 else crop
            blur = cv2.GaussianBlur(gray, (3, 3), 0)
            _threshold, ink = cv2.threshold(
                blur,
                0,
                255,
                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
            )
            # Downsampling removes anti-aliased edge differences caused by dimmed
            # broken cards while retaining the overall nine-name layout.
            small = cv2.resize(ink, (16, 8), interpolation=cv2.INTER_AREA)
            fingerprints.append(np.packbits(small >= 64).tobytes())
        if not fingerprints:
            return ''
        return hashlib.sha1(b''.join(fingerprints)).hexdigest()[:20]

    def read_refresh_cd_seconds(self, image=None) -> int | None:
        if image is None:
            image = self.device.image
        try:
            cached_ocr = getattr(self, '_ocr_cached', None)
            if callable(cached_ocr) and image is getattr(self.device, 'image', None):
                text = str(cached_ocr(self.O_FRESH_TIME, operation='ocr_single') or '')
            else:
                text = str(self.O_FRESH_TIME.ocr_single(image) or '')
        except Exception as error:  # noqa: BLE001
            logger.warning(f'Refresh CD OCR failed: {error}')
            return None

        parts = [int(value) for value in re.findall(r'\d+', text)]
        if len(parts) >= 3:
            return parts[-3] * 3600 + parts[-2] * 60 + parts[-1]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 1:
            digits = re.sub(r'\D', '', text)
            if 3 <= len(digits) <= 4:
                return int(digits[:-2]) * 60 + int(digits[-2:])
        return None

    def build_level_board_snapshot(
        self,
        screenshot: bool = True,
        expected_level: int = 0,
        expected_board_signature: str = '',
        trust_expected_level: bool = False,
        level_cache: RealmRaidCheckpoint | None = None,
        use_checkpoint_cache: bool = False,
    ) -> BoardSnapshot:
        # Compatibility-only arguments: checkpoint evidence must never replace
        # any of the nine levels used to calculate the current board mode.
        _ = expected_level, expected_board_signature, trust_expected_level
        if screenshot:
            self.screenshot()
        image = self.device.image
        timing_started = time.perf_counter()
        marks_started = time.perf_counter()
        broken, failure_marked = self.detect_level_board_marks(image)
        marks_ms = (time.perf_counter() - marks_started) * 1000
        layout_started = time.perf_counter()
        layout_signature = self._layout_hash(image, self.partition)
        layout_ms = (time.perf_counter() - layout_started) * 1000
        levels = ()
        if use_checkpoint_cache:
            levels = cached_board_levels(
                level_cache,
                layout_signature,
                broken,
                failure_marked,
                now=datetime.now(),
            )
        if levels:
            level_source = 'checkpoint-cache'
            level_ms = 0.0
        else:
            level_started = time.perf_counter()
            levels = tuple(self.read_levels(image, broken=broken))
            level_ms = (time.perf_counter() - level_started) * 1000
            level_source = 'ocr'
        challenge_level = self.current_challenge_level(levels)
        votes = Counter(level for level in levels if level).get(challenge_level, 0)

        try:
            cached_ocr = getattr(self, '_ocr_cached', None)
            if callable(cached_ocr) and image is getattr(self.device, 'image', None):
                tickets_current, _tickets_rest, tickets_total = cached_ocr(self.O_NUMBER)
            else:
                tickets_current, _tickets_rest, tickets_total = self.O_NUMBER.ocr(image)
        except Exception as error:  # noqa: BLE001
            logger.warning(f'Ticket OCR failed: {error}')
            tickets_current, tickets_total = -1, 30
        if tickets_total <= 0:
            tickets_current, tickets_total = -1, 30

        try:
            cached_ocr = getattr(self, '_ocr_cached', None)
            if callable(cached_ocr) and image is getattr(self.device, 'image', None):
                record_value = cached_ocr(self.attack_record_ocr)
            else:
                record_value = self.attack_record_ocr.ocr(image)
        except Exception as error:  # noqa: BLE001
            logger.warning(f'Attack record OCR failed: {error}')
            record_value = None
        if record_value is None:
            attack_record = None
        elif 0 <= record_value <= 9:
            attack_record = record_value
        else:
            attack_record = None

        refresh_available = self.appear(self.I_FRESH)
        refresh_cd_seconds = None if refresh_available else self.read_refresh_cd_seconds(image)
        snapshot = BoardSnapshot(
            levels=levels,
            challenge_level=challenge_level,
            challenge_level_votes=votes,
            broken=broken,
            failure_marked=failure_marked,
            attack_record=attack_record,
            tickets_current=tickets_current,
            tickets_total=tickets_total,
            refresh_available=refresh_available,
            refresh_cd_seconds=refresh_cd_seconds,
            layout_signature=layout_signature,
            level_source=level_source,
            captured_at=datetime.now(),
        )
        logger.info(
            'REALM_RAID_BOARD_TIMING phase=snapshot '
            f'totalMs={(time.perf_counter() - timing_started) * 1000:.1f} '
            f'marksMs={marks_ms:.1f} layoutMs={layout_ms:.1f} '
            f'levelOcrMs={level_ms:.1f} levelSource={level_source} '
            f'cells={len(levels)}'
        )
        logger.info(
            'Level board: '
            f'levels={list(snapshot.levels)}, current={snapshot.challenge_level}({snapshot.challenge_level_votes}), '
            f'level_source={snapshot.level_source}, '
            f'broken={sorted(snapshot.broken)}, '
            f'failed={sorted(snapshot.failure_marked)}, '
            f'record={snapshot.attack_record}, tickets={snapshot.tickets_current}/{snapshot.tickets_total}, '
            f'refresh={snapshot.refresh_available}, cd={snapshot.refresh_cd_seconds}'
        )
        return snapshot

    @staticmethod
    def _level_reward_overlay_heuristic(image) -> bool:
        """Detect the dimmed 3/6/9 reward modal when its small template varies."""
        if image is None or getattr(image, 'ndim', 0) != 3:
            return False
        height, width = image.shape[:2]
        if width < 640 or height < 360:
            return False

        # The board is rendered at 1280x720. Scale the modal ROI for harmless
        # compatibility with a resized capture while keeping the test cheap.
        scale_x, scale_y = width / 1280, height / 720
        x, y, w, h = (
            round(450 * scale_x),
            round(370 * scale_y),
            round(380 * scale_x),
            round(300 * scale_y),
        )
        roi = image[y:min(height, y + h), x:min(width, x + w)]
        if roi.size == 0:
            return False

        gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
        hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
        hue, saturation, value = cv2.split(hsv)
        warm = (
            (hue <= 30)
            & (saturation >= 70)
            & (value >= 50)
        )
        cool = (
            (hue >= 90)
            & (hue <= 140)
            & (saturation >= 70)
            & (value >= 50)
        )
        # A ready board is bright in this region. The reward modal dims the
        # board and adds a large colored reward object in the same area. The
        # current client uses a blue object, while older clients used a
        # red/orange one, so keep both signatures without lowering the global
        # template threshold.
        dimmed = float(gray.mean()) <= 105 and float((gray < 100).mean()) >= 0.55
        return dimmed and (
            float(warm.mean()) >= 0.12 or float(cool.mean()) >= 0.20
        )

    def level_reward_overlay_visible(self) -> bool:
        """Return true for either the known reward template or its modal shape."""
        if self.appear(self.I_SOUL_RAID, threshold=0.65):
            return True
        return self._level_reward_overlay_heuristic(self.device.image)

    def dismiss_level_reward_overlay(self) -> None:
        """Dismiss the modal without reusing a stale template click timer."""
        template_clicked = self.appear_then_click(self.I_SOUL_RAID, threshold=0.65)
        if template_clicked:
            # The reward artwork can remain detectable after a tap that was
            # accepted visually but did not advance the modal. Re-sample once
            # before deciding that the template click was sufficient.
            self.screenshot()
            if not self.level_reward_overlay_visible():
                return

        image = self.device.image
        height, width = image.shape[:2]
        # Some client versions only respond to the visible bottom
        # "tap-to-continue" area, while the reward artwork template can still
        # match. Keep this deterministic and away from the refresh control.
        x, y = width // 2, max(0, height - 45)
        self.device.click(
            x,
            y,
            control_name='REALM_RAID_REWARD_CONTINUE',
        )
        logger.info(f'RealmRaid reward continue fallback clicked at ({x},{y})')

    def wait_level_board(self, timeout: float = 25) -> bool:
        start = time.time()
        timing_started = time.perf_counter()
        reward_seen = False
        reward_clear_since = None
        reward_clicked = False
        reward_click_at = 0.0
        reward_attempts = 0
        reward_logged = False
        while time.time() - start < timeout:
            self.screenshot()

            # A slow preparation transition can leave us in real combat after
            # GeneralBattle has returned false. Never interpret that combat frame
            # as a RealmRaid reward modal and click its centre repeatedly.
            is_in_real_battle = getattr(self, 'is_in_real_battle', None)
            if is_in_real_battle is not None and is_in_real_battle(False):
                logger.warning('RealmRaid board wait stopped: still in real battle')
                logger.info(
                    'REALM_RAID_BOARD_TIMING phase=wait result=real_battle '
                    f'durationMs={(time.perf_counter() - timing_started) * 1000:.1f}'
                )
                return False

            # The red back button remains visible behind the 3/6/9 reward overlay.
            # Detect the overlay independently from the click cooldown so that a
            # still-visible reward can never be mistaken for a ready board.
            reward_visible = self.level_reward_overlay_visible()
            if reward_visible:
                reward_seen = True
                reward_clear_since = None
                if not reward_logged:
                    logger.info('RealmRaid reward overlay detected; board OCR is blocked')
                    reward_logged = True
                if not reward_clicked or time.time() - reward_click_at >= 2.0:
                    if reward_attempts >= 5:
                        logger.warning(
                            'RealmRaid reward overlay did not clear after 5 dismiss attempts'
                        )
                        return False
                    self.dismiss_level_reward_overlay()
                    reward_clicked = True
                    reward_click_at = time.time()
                    reward_attempts += 1
                    logger.info('Dismiss RealmRaid 3/6/9 reward')
                time.sleep(0.5)
                continue

            if reward_seen:
                if reward_clear_since is None:
                    reward_clear_since = time.time()
                clear_duration = time.time() - reward_clear_since
                if clear_duration < 1.0:
                    time.sleep(min(0.5, 1.0 - clear_duration))
                    continue
                logger.info('RealmRaid reward overlay cleared; board is stable')
                reward_seen = False
                reward_clicked = False
                reward_attempts = 0
                reward_logged = False

            if self.appear(self.I_BACK_RED, threshold=0.7):
                logger.info(
                    'REALM_RAID_BOARD_TIMING phase=wait result=ready '
                    f'durationMs={(time.perf_counter() - timing_started) * 1000:.1f}'
                )
                return True
            time.sleep(0.5)
        logger.warning(f'Wait RealmRaid board timeout after {timeout}s')
        logger.info(
            'REALM_RAID_BOARD_TIMING phase=wait result=timeout '
            f'durationMs={(time.perf_counter() - timing_started) * 1000:.1f}'
        )
        return False

    def observe_level_board(
        self,
        retries: int = 3,
        expected_level: int = 0,
        expected_board_signature: str = '',
        pending_checkpoint: RealmRaidCheckpoint | None = None,
        stable_reads: int = 2,
    ) -> BoardSnapshot | None:
        _ = expected_level, expected_board_signature
        if not self.wait_level_board(timeout=20):
            return None
        last = None
        stable_count = 0
        self._last_level_observation = None
        required_stable = max(1, int(stable_reads))
        base_attempts = max(1, int(retries))
        max_attempts = base_attempts
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            attempt_started = time.perf_counter()
            last = self.build_level_board_snapshot(
                screenshot=True,
                # A checkpoint is recovery metadata, never a replacement for
                # the current nine OCR reads.  Reusing it here was the source
                # of the single-frame level misread self-reinforcement loop.
                level_cache=None,
            )
            if last.is_safe():
                logger.info(
                    'REALM_RAID_BOARD_TIMING phase=observe '
                    f'attempt={attempt} result=safe '
                    f'durationMs={(time.perf_counter() - attempt_started) * 1000:.1f} '
                    f'levelSource={last.level_source}'
                )
                if self._same_level_evidence(last, getattr(self, '_last_level_observation', None)):
                    stable_count += 1
                else:
                    stable_count = 1
                self._last_level_observation = last
                if stable_count >= required_stable:
                    return last
                logger.info(
                    f'Level board evidence stable {stable_count}/{required_stable}'
                )
                # A transient OCR frame can consume the base retry budget just
                # before the first safe read. Reserve a short confirmation tail
                # once a safe read arrives at the end of that budget.
                if attempt >= max_attempts:
                    max_attempts += required_stable - 1
                time.sleep(0.8)
                continue
            stable_count = 0
            self._last_level_observation = None
            logger.warning(
                f'Unsafe RealmRaid board evidence, retry {attempt}/{max_attempts}'
            )
            logger.info(
                'REALM_RAID_BOARD_TIMING phase=observe '
                f'attempt={attempt} result=unsafe '
                f'durationMs={(time.perf_counter() - attempt_started) * 1000:.1f}'
            )
            time.sleep(0.8)
        if last is not None:
            self.dump_board('unsafe')
        return last if last is not None and not last.is_safe() else None

    @staticmethod
    def _same_level_evidence(
        current: BoardSnapshot,
        previous: BoardSnapshot | None,
    ) -> bool:
        if previous is None:
            return False
        return (
            current.levels == previous.levels
            and current.challenge_level == previous.challenge_level
            and current.challenge_level_votes == previous.challenge_level_votes
            and current.broken == previous.broken
            and current.failure_marked == previous.failure_marked
            and current.attack_record == previous.attack_record
            and current.tickets_current == previous.tickets_current
        )

    def choose_level_target(self, snapshot: BoardSnapshot) -> int | None:
        attackable = sorted(snapshot.attackable)
        if not attackable:
            self._level_target_image = None
            return None

        image = self.device.image.copy()
        for index in snapshot.broken:
            x, y, w, h = self.partition[index - 1].roi_back
            image[y:y + h, x:x + w, ...] = 0

        target = self.order_medal.find_anyone(image)
        if target is None:
            # A transient reward/banner overlay can lower a valid medal row
            # from 0.80 to around 0.78.  Retry only the configured medal
            # templates at a bounded threshold before using a positional
            # fallback; do not relax unrelated page recognition.
            for candidate in self.order_medal.images:
                if candidate.match(image, threshold=self.MEDAL_RELAXED_THRESHOLD):
                    target = candidate
                    logger.info(
                        f'Medal order matched with relaxed threshold '
                        f'{self.MEDAL_RELAXED_THRESHOLD:.2f}: {candidate.name}'
                    )
                    break
        if target:
            center = target.front_center()
            for index in attackable:
                x, y, w, h = self.partition[index - 1].roi_front
                if x < center[0] < x + w and y < center[1] < y + h:
                    self._level_target_image = target
                    return index
        self._level_target_image = None
        logger.warning(f'Medal order did not select a target; fallback to position {attackable[0]}')
        return attackable[0]

    @staticmethod
    def pending_snapshot_confirms_same_board(
        checkpoint: RealmRaidCheckpoint,
        snapshot: BoardSnapshot,
    ) -> bool:
        try:
            pending = PendingAction(checkpoint.pending_action)
        except ValueError:
            return False

        target = checkpoint.last_target
        if pending == PendingAction.ATTACK:
            auto_refreshed = (
                checkpoint.pending_success_before >= 8
                and snapshot.success_count == 0
                and not snapshot.broken
                and checkpoint.pending_tickets_before >= 0
                and snapshot.tickets_current < checkpoint.pending_tickets_before
            )
            if auto_refreshed:
                return False
            return bool(
                snapshot.success_count > checkpoint.pending_success_before
                or (
                    target in snapshot.broken
                    and checkpoint.pending_tickets_before >= 0
                    and snapshot.tickets_current < checkpoint.pending_tickets_before
                )
                or (
                    checkpoint.pending_tickets_before >= 0
                    and snapshot.tickets_current < checkpoint.pending_tickets_before
                )
                or (
                    target
                    and not checkpoint.pending_failure_marked_before
                    and target in snapshot.failure_marked
                )
            )

        if pending == PendingAction.SURRENDER:
            return bool(
                target
                and not checkpoint.pending_failure_marked_before
                and target in snapshot.failure_marked
                and snapshot.tickets_current == checkpoint.pending_tickets_before
            )
        return False

    @staticmethod
    def level_attack_generation_changed(
        before: BoardSnapshot,
        after: BoardSnapshot,
        won: bool,
    ) -> bool:
        """A confirmed defeat cannot trigger RealmRaid's automatic board refresh."""
        if not won:
            return False
        return generation_changed(before, after)

    def recover_pending_level_action(
        self,
        checkpoint: RealmRaidCheckpoint,
        snapshot: BoardSnapshot,
        store: CheckpointStore,
    ) -> bool | None:
        try:
            pending = PendingAction(checkpoint.pending_action)
        except ValueError:
            pending = PendingAction.NONE
        if pending == PendingAction.NONE:
            return None

        # A ticket count increase is impossible within an in-flight attack or
        # surrender. It proves that the checkpoint belongs to an earlier task
        # run (for example, tickets were earned between retries), so keeping it
        # would block the current board forever as an "ambiguous" action.
        if (
            pending in (PendingAction.ATTACK, PendingAction.SURRENDER)
            and checkpoint.pending_tickets_before >= 0
            and snapshot.tickets_current > checkpoint.pending_tickets_before
        ):
            logger.warning(
                'Discard stale pending action after ticket count increased: '
                f'{pending.value}, before={checkpoint.pending_tickets_before}, '
                f'current={snapshot.tickets_current}'
            )
            store.clear()
            return True

        target = checkpoint.last_target
        if pending == PendingAction.REFRESH:
            if (
                checkpoint.board_signature
                and snapshot.board_signature
                and checkpoint.board_signature != snapshot.board_signature
                and snapshot.success_count == 0
                and not snapshot.broken
            ):
                logger.warning('Recovered committed pending refresh: board generation changed')
                store.clear()
                return True
            checkpoint.pending_refresh = True
            store.save(checkpoint)
            return True

        if (
            pending in (PendingAction.ATTACK, PendingAction.SURRENDER)
            and checkpoint.pending_stage == 'selection'
            and checkpoint.pending_tickets_before >= 0
            and snapshot.tickets_current == checkpoint.pending_tickets_before
            and checkpoint.board_signature == snapshot.board_signature
            and target not in snapshot.broken
        ):
            # The action was persisted before target selection so a crash or
            # failed medal/detail transition could be recovered safely.  No
            # ticket, broken marker, or board generation changed here, so the
            # battle cannot have committed; clear only the pre-battle marker
            # and retry selection on this same board.
            logger.warning(
                'Recovered pre-battle pending action without board change: '
                f'{pending.value}, target={target}; clear for safe replay'
            )
            checkpoint.remember_board(snapshot)
            checkpoint.finish_action()
            store.save(checkpoint)
            return True

        if (
            pending == PendingAction.SURRENDER
            and checkpoint.pending_failure_marked_before
            and target in snapshot.failure_marked
            and checkpoint.pending_tickets_before >= 0
            and snapshot.tickets_current == checkpoint.pending_tickets_before
        ):
            # Repeated surrenders do not add another visible arrow.  If the
            # process stopped between returning to the board and committing
            # the checkpoint, the screen cannot prove whether that surrender
            # happened.  Clear only the pending marker and replay it; an extra
            # ticket-free surrender is safer than under-counting the hold/lower
            # requirement or stopping on the same pending action forever.
            logger.warning(
                'Repeated surrender is visually ambiguous; clear pending '
                'without counting it and replay safely'
            )
            checkpoint.remember_board(snapshot)
            checkpoint.finish_action()
            store.save(checkpoint)
            return True

        if (
            pending == PendingAction.ATTACK
            and checkpoint.pending_stage == 'battle'
            and checkpoint.pending_failure_marked_before
            and target in snapshot.failure_marked
            and checkpoint.pending_tickets_before >= 0
            and snapshot.tickets_current == checkpoint.pending_tickets_before
            and checkpoint.board_signature == snapshot.board_signature
        ):
            # A failed attack does not consume a ticket. When the target's
            # failure marker was already present and the same board returns
            # with the same ticket count, there is no evidence of a committed
            # win. Clear the stale marker and replay the attack instead of
            # blocking every later run on an unverifiable battle.
            logger.warning(
                'Ambiguous failed attack is safe to replay; clear pending '
                f'without counting it: target={target}'
            )
            checkpoint.remember_board(snapshot)
            checkpoint.finish_action()
            store.save(checkpoint)
            return True

        if (
            pending == PendingAction.ATTACK
            and checkpoint.pending_success_before >= 8
            and snapshot.success_count == 0
            and not snapshot.broken
            and checkpoint.pending_tickets_before >= 0
            and snapshot.tickets_current < checkpoint.pending_tickets_before
        ):
            logger.warning('Recovered ninth win followed by automatic board refresh')
            store.clear()
            return True

        committed = False
        if pending == PendingAction.ATTACK:
            ticket_spent = (
                checkpoint.pending_tickets_before >= 0
                and snapshot.tickets_current < checkpoint.pending_tickets_before
            )
            if (
                ticket_spent
                and (
                    snapshot.success_count > checkpoint.pending_success_before
                    or target in snapshot.broken
                )
            ):
                checkpoint.success_count = snapshot.success_count
                committed = True
            elif (target and not checkpoint.pending_failure_marked_before
                  and target in snapshot.failure_marked):
                checkpoint.failure_count += 1
                checkpoint.pending_refresh = checkpoint.level_mode == LevelMode.RAISE
                committed = True
        elif pending == PendingAction.SURRENDER:
            if (target and not checkpoint.pending_failure_marked_before
                    and target in snapshot.failure_marked):
                checkpoint.failure_count += 1
                committed = True

        if committed:
            logger.warning(f'Recovered committed pending action: {pending.value}, target={target}')
            checkpoint.remember_board(snapshot)
            checkpoint.finish_action()
            store.save(checkpoint)
            return True

        logger.warning(
            'Pending action has no conclusive evidence; preserve it and stop: '
            f'{pending.value}, target={target}'
        )
        store.save(checkpoint)
        return False

    def execute_level_surrender(
        self,
        snapshot: BoardSnapshot,
        checkpoint: RealmRaidCheckpoint,
        store: CheckpointStore,
        battle_config,
    ) -> BoardSnapshot | None:
        target = self.choose_level_target(snapshot)
        if target is None:
            logger.warning('No attackable target for surrender')
            return None

        checkpoint.begin_action(PendingAction.SURRENDER, snapshot, target)
        store.save(checkpoint)
        logger.info(f'Level mode surrender: target={target}, failure={checkpoint.failure_count + 1}')
        try:
            self.fire(target)
        except (GameStuckError, GameTooManyClickError):
            if checkpoint.pending_stage == 'selection':
                logger.warning(
                    f'Clear pre-battle surrender pending after target selection failure: target={target}'
                )
                checkpoint.remember_board(snapshot)
                checkpoint.finish_action()
                store.save(checkpoint)
            raise
        checkpoint.pending_stage = 'battle'
        store.save(checkpoint)
        action_ok = self.run_general_battle_back(battle_config, exit_four=True)
        after = self.observe_level_board(
            expected_level=checkpoint.observed_level,
            expected_board_signature=checkpoint.board_signature,
            pending_checkpoint=checkpoint,
        )
        if after is None or not after.is_safe():
            return None
        if after.tickets_current != snapshot.tickets_current:
            logger.warning('Surrender unexpectedly changed ticket count; stop without committing checkpoint')
            self.dump_board('surrender_ticket_changed')
            return None
        self.retry_lock_after_battle(battle_config)
        if not action_ok and not (
            target not in snapshot.failure_marked and target in after.failure_marked
        ):
            logger.warning('Surrender result is ambiguous; keep pending action for recovery')
            return None

        checkpoint.failure_count += 1
        checkpoint.remember_board(after)
        checkpoint.finish_action()
        store.save(checkpoint)
        return after

    def execute_level_attack(
        self,
        snapshot: BoardSnapshot,
        checkpoint: RealmRaidCheckpoint,
        store: CheckpointStore,
        battle_config,
    ) -> BoardSnapshot | None:
        target = self.choose_level_target(snapshot)
        if target is None:
            logger.warning('No attackable target for attack')
            return None

        checkpoint.begin_action(PendingAction.ATTACK, snapshot, target)
        store.save(checkpoint)
        logger.info(f'Level mode attack: target={target}, success={snapshot.success_count}/9')
        try:
            self.fire(target)
        except (GameStuckError, GameTooManyClickError):
            if checkpoint.pending_stage == 'selection':
                logger.warning(
                    f'Clear pre-battle attack pending after target selection failure: target={target}'
                )
                checkpoint.remember_board(snapshot)
                checkpoint.finish_action()
                store.save(checkpoint)
            raise
        checkpoint.pending_stage = 'battle'
        store.save(checkpoint)
        won = self.run_general_battle(battle_config)
        after = self.observe_level_board(
            expected_level=checkpoint.observed_level,
            expected_board_signature=checkpoint.board_signature,
            pending_checkpoint=checkpoint,
        )
        if after is None or not after.is_safe():
            return None

        self.retry_lock_after_battle(battle_config)

        raw_generation_changed = generation_changed(snapshot, after)
        changed = self.level_attack_generation_changed(snapshot, after, won)
        if raw_generation_changed and not won:
            logger.warning(
                'Ignore board-signature drift after a confirmed defeat; '
                'automatic refresh only follows the ninth win'
            )
        if won:
            confirmed = (
                changed
                or after.success_count > snapshot.success_count
                or target in after.broken
                or after.tickets_current < snapshot.tickets_current
            )
            if not confirmed:
                logger.warning('Battle reported win but board/ticket evidence did not change')
                self.dump_board('win_unconfirmed')
                return None
            logger.info(f'Level mode battle won: target={target}')
        else:
            checkpoint.failure_count += 1
            if checkpoint.level_mode == LevelMode.RAISE:
                checkpoint.pending_refresh = True
            logger.info(f'Level mode battle lost: target={target}, failures={checkpoint.failure_count}')

        checkpoint.success_count = after.success_count
        checkpoint.finish_action()
        if changed:
            logger.info('RealmRaid board generation changed after battle')
            store.clear()
        else:
            checkpoint.remember_board(after)
            store.save(checkpoint)
        return after

    def wait_level_generation_change(
        self,
        before: BoardSnapshot,
        timeout: float = 25,
        level_cache: RealmRaidCheckpoint | None = None,
    ) -> BoardSnapshot | None:
        start = time.time()
        previous = None
        stable_count = 0
        while time.time() - start < timeout:
            if not self.wait_level_board(timeout=5):
                continue
            after = self.build_level_board_snapshot(
                screenshot=True,
                level_cache=None,
            )
            if after.is_safe() and generation_changed(before, after):
                if self._same_level_evidence(after, previous):
                    stable_count += 1
                else:
                    stable_count = 1
                previous = after
                if stable_count >= 2:
                    return after
            else:
                previous = None
                stable_count = 0
            time.sleep(1)
        return None

    def execute_level_refresh(
        self,
        snapshot: BoardSnapshot,
        checkpoint: RealmRaidCheckpoint,
        store: CheckpointStore,
    ) -> BoardSnapshot | None:
        checkpoint.begin_action(PendingAction.REFRESH, snapshot)
        checkpoint.pending_refresh = True
        store.save(checkpoint)
        if not self.check_refresh(screenshot=False):
            logger.info('Manual refresh is unavailable')
            return None

        after = self.wait_level_generation_change(
            snapshot,
            timeout=25,
            level_cache=checkpoint,
        )
        if after is None:
            logger.warning('Manual refresh clicked but a new board was not confirmed')
            self.dump_board('refresh_unconfirmed')
            return None
        logger.info(f'Manual refresh confirmed: level {snapshot.challenge_level} -> {after.challenge_level}')
        store.clear()
        return after

    def finish_level_mode(
        self,
        success: bool,
        target: datetime | None = None,
        reason: str = '',
    ) -> None:
        manual_stop_reasons = {'test_paused', 'test_recovery_paused'}
        deferred_reasons = {'refresh_cooldown'}
        if success:
            outcome = 'completed'
        elif reason in manual_stop_reasons:
            outcome = 'stopped'
        elif reason in deferred_reasons:
            outcome = 'deferred'
        else:
            outcome = 'failed'
        logger.info(
            f'Level mode exit: outcome={outcome}, reason={reason or "unspecified"}'
        )
        try:
            self.ui_click(self.I_BACK_RED, self.I_CHECK_EXPLORATION)
            self.ui_get_current_page()
            self.ui_goto(page_main)
        except Exception as error:  # noqa: BLE001
            logger.warning(f'Leave RealmRaid page failed; scheduler will recover next run: {error}')
        self.set_next_run(task='RealmRaid', success=success, finish=True,
                          server=target is None, target=target)
        statistics = {'level_mode_reason': reason or 'unspecified'}
        if outcome == 'completed':
            raise TaskEnd.completed(
                'RealmRaid level mode completed',
                statistics=statistics,
                next_run=target,
            )
        if outcome == 'stopped':
            raise TaskEnd.stopped(
                'RealmRaid level mode stopped manually',
                statistics=statistics,
                next_run=target,
            )
        if outcome == 'deferred':
            raise TaskEnd.deferred(
                'RealmRaid level mode deferred',
                statistics=statistics,
                next_run=target,
            )
        raise TaskEnd.failed(
            'RealmRaid level mode failed',
            statistics=statistics,
            next_run=target,
        )

    @staticmethod
    def level_short_retry_target(delay_seconds: int = 300) -> datetime:
        """Retry recoverable target-level errors without waiting for the daily slot."""
        return schedule_after_cooldown(
            delay_seconds,
            safety_buffer_seconds=0,
        )

    def confirm_level_auto_refresh(
        self,
        snapshot: BoardSnapshot,
        checkpoint: RealmRaidCheckpoint,
        store: CheckpointStore,
    ) -> BoardSnapshot | None:
        after = self.wait_level_generation_change(
            snapshot,
            timeout=25,
            level_cache=checkpoint,
        )
        if after is None:
            logger.warning('Ninth win did not produce a confirmed automatic refresh')
            self.dump_board('auto_refresh_timeout')
            return None
        store.clear()
        return after

    def finish_level_test_step(
        self,
        config: RealmRaid,
        action: LevelAction,
        transaction_count: int,
        store: CheckpointStore,
    ) -> None:
        # Normal RealmRaid execution owns the whole ticket-draining workflow.
        # Only the explicit development switch may pause after one committed action.
        if not config.level_mode_config.single_step:
            return
        action_limit = self.level_action_limit(config)
        if transaction_count < action_limit:
            return
        checkpoint = store.load()
        if checkpoint is None:
            state = 'checkpoint=cleared'
        else:
            state = (
                f'failure={checkpoint.failure_count}, success={checkpoint.success_count}, '
                f'pending={checkpoint.pending_action}'
            )
        logger.info(
            f'Level single-step paused: limit={action_limit}, '
            f'action={action.value}, {state}'
        )
        self.finish_level_mode(success=False, reason='test_paused')

    @staticmethod
    def level_action_limit(config: RealmRaid) -> int | None:
        if config.level_mode_config.single_step:
            return 1
        return None

    @staticmethod
    def level_transaction_safety_cap(config: RealmRaid) -> int:
        """Fault guard only; normal completion is driven by tickets, not actions."""
        return max(60, int(config.raid_config.number_attack) * 4)

    @staticmethod
    def level_ticket_stop_reason(
        snapshot: BoardSnapshot,
        config: RealmRaid,
        tickets_at_start: int | None,
    ) -> str:
        reserve = max(0, int(config.raid_config.number_base))
        if snapshot.tickets_current <= reserve:
            return 'ticket_reserve_reached'
        if tickets_at_start is None:
            return ''
        tickets_spent = max(0, tickets_at_start - snapshot.tickets_current)
        if tickets_spent >= max(1, int(config.raid_config.number_attack)):
            return 'ticket_spend_limit_reached'
        return ''

    def run_level_mode(self, config: RealmRaid) -> None:
        account = getattr(self.config, 'config_name', 'default')
        target_level = config.level_mode_config.target_level
        store = CheckpointStore(account)
        checkpoint = store.load()
        transaction_count = 0
        tickets_at_start = None
        snapshot = None
        max_transactions = self.level_transaction_safety_cap(config)
        action_limit = self.level_action_limit(config)
        logger.info(
            'Level execution policy: '
            f'single_step={config.level_mode_config.single_step}, '
            f'action_limit={action_limit}, safety_cap={max_transactions}, '
            f'ticket_spend_limit={config.raid_config.number_attack}, '
            f'ticket_reserve={config.raid_config.number_base}'
        )

        while True:
            if snapshot is None:
                snapshot = self.observe_level_board(
                    expected_level=checkpoint.observed_level if checkpoint else 0,
                    expected_board_signature=checkpoint.board_signature if checkpoint else '',
                    pending_checkpoint=checkpoint,
                )
            if snapshot is None or not snapshot.is_safe():
                logger.warning('Target level mode stopped: board evidence is unsafe')
                self.finish_level_mode(
                    success=False,
                    target=self.level_short_retry_target(),
                    reason='board_evidence_unsafe',
                )

            recovered = None
            if checkpoint is not None:
                recovered = self.recover_pending_level_action(checkpoint, snapshot, store)
            if recovered is False:
                self.finish_level_mode(
                    success=False,
                    target=self.level_short_retry_target(),
                    reason='pending_action_ambiguous',
                )
            if recovered is True:
                checkpoint = store.load()
                recovery_committed = (
                    checkpoint is None
                    or checkpoint.pending_action == PendingAction.NONE.value
                )
                if config.level_mode_config.single_step and recovery_committed:
                    logger.info('Level single-step complete: recovered pending action; stop')
                    self.finish_level_mode(success=False, reason='test_recovery_paused')

            if tickets_at_start is None:
                tickets_at_start = snapshot.tickets_current
            stop_reason = self.level_ticket_stop_reason(
                snapshot,
                config,
                tickets_at_start,
            )
            if stop_reason:
                tickets_spent = max(0, tickets_at_start - snapshot.tickets_current)
                logger.info(
                    'Target level mode ticket budget complete: '
                    f'reason={stop_reason}, tickets={snapshot.tickets_current}, '
                    f'spent={tickets_spent}'
                )
                self.finish_level_mode(success=True, reason=stop_reason)

            checkpoint = reconcile_checkpoint(
                account=account,
                snapshot=snapshot,
                target_level=target_level,
                checkpoint=checkpoint,
            )
            store.save(checkpoint)
            decision = decide_next_action(snapshot, checkpoint)
            logger.info(
                f'Level decision: mode={decision.mode}, action={decision.action}, '
                f'failure={decision.failure_count}, success={decision.success_count}, reason={decision.reason}'
            )

            if decision.action == LevelAction.STOP:
                logger.info('Target level mode finished: no RealmRaid tickets')
                self.finish_level_mode(success=True, reason='no_tickets')

            if (
                transaction_count >= max_transactions
                and decision.action in {
                    LevelAction.SURRENDER,
                    LevelAction.ATTACK,
                    LevelAction.REFRESH,
                }
            ):
                logger.warning(
                    'Target level mode reached the abnormal transaction safety cap: '
                    f'{max_transactions}'
                )
                self.finish_level_mode(
                    success=False,
                    target=self.level_short_retry_target(),
                    reason='transaction_safety_cap',
                )

            if decision.action == LevelAction.SURRENDER:
                after = self.execute_level_surrender(
                    snapshot, checkpoint, store, config.general_battle_config
                )
                if after is None:
                    self.finish_level_mode(
                        success=False,
                        target=self.level_short_retry_target(),
                        reason='surrender_unconfirmed',
                    )
                snapshot = after
                transaction_count += 1
                self.finish_level_test_step(
                    config, decision.action, transaction_count, store
                )
                continue

            if decision.action == LevelAction.ATTACK:
                after = self.execute_level_attack(
                    snapshot, checkpoint, store, config.general_battle_config
                )
                if after is None:
                    self.finish_level_mode(
                        success=False,
                        target=self.level_short_retry_target(),
                        reason='attack_unconfirmed',
                    )
                snapshot = after
                transaction_count += 1
                checkpoint = store.load()
                if (
                    checkpoint is not None
                    and decide_next_action(snapshot, checkpoint).action
                    == LevelAction.WAIT_AUTO_REFRESH
                ):
                    after_refresh = self.confirm_level_auto_refresh(
                        snapshot,
                        checkpoint,
                        store,
                    )
                    if after_refresh is None:
                        self.finish_level_mode(
                            success=False,
                            target=self.level_short_retry_target(),
                            reason='auto_refresh_unconfirmed',
                        )
                    snapshot = after_refresh
                    checkpoint = None
                self.finish_level_test_step(
                    config, decision.action, transaction_count, store
                )
                continue

            if decision.action == LevelAction.REFRESH:
                after = self.execute_level_refresh(snapshot, checkpoint, store)
                if after is not None:
                    snapshot = after
                    transaction_count += 1
                    checkpoint = None
                    self.finish_level_test_step(
                        config, decision.action, transaction_count, store
                    )
                    continue
                refreshed = self.build_level_board_snapshot(screenshot=True)
                if refreshed.refresh_available:
                    self.finish_level_mode(
                        success=False,
                        target=self.level_short_retry_target(),
                        reason='manual_refresh_unconfirmed',
                    )
                snapshot = refreshed
                decision = decide_next_action(snapshot, checkpoint)

            if decision.action == LevelAction.WAIT_AUTO_REFRESH:
                after = self.confirm_level_auto_refresh(
                    snapshot,
                    checkpoint,
                    store,
                )
                if after is None:
                    self.finish_level_mode(
                        success=False,
                        target=self.level_short_retry_target(),
                        reason='auto_refresh_unconfirmed',
                    )
                checkpoint = None
                snapshot = after
                continue

            if decision.action == LevelAction.WAIT_COOLDOWN:
                cd_seconds = snapshot.refresh_cd_seconds
                if cd_seconds is None or cd_seconds <= 0:
                    cd_seconds = 300
                    logger.warning('Refresh CD OCR unavailable; fallback to the known 5-minute cooldown')
                due = schedule_after_cooldown(cd_seconds)
                checkpoint.pending_refresh = True
                checkpoint.refresh_not_before = due.isoformat(timespec='seconds')
                checkpoint.finish_action()
                store.save(checkpoint)
                logger.info(f'RealmRaid refresh cooling down; next run at {due.isoformat(timespec="seconds")}')
                self.finish_level_mode(
                    success=False,
                    target=due,
                    reason='refresh_cooldown',
                )

            logger.warning(f'Target level mode stopped on unsafe action: {decision.action}')
            self.dump_board('level_mode_unsafe')
            self.finish_level_mode(
                success=False,
                target=self.level_short_retry_target(),
                reason='unsafe_action',
            )

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

        现在改为：限时轮询 + 明确日志；超时返回 False，由上层暂停本次任务并短重试，
        不在阵容状态未知时继续消耗突破券。
        :param lock_team_enable: True 需要锁定阵容，False 需要解除锁定
        :param timeout: 最长尝试秒数
        :return: True 表示达成目标状态；False 表示状态未知，需要上层暂停
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
                       f'识别不到锁定/未锁定图标，交由上层暂停并短重试。'
                       f'（请检查游戏内该图标是否被活动 UI 遮挡）')
        # Keep the exact frame used by the final match attempt.  This is
        # diagnostic-only: it does not click, alter state, or affect retry
        # scheduling, and lets us distinguish a stale/wrong page from a
        # template or threshold mismatch.
        self.dump_board('lock_timeout')
        try:
            diagnostics = []
            for label, target in (
                ('lock', self.I_LOCK),
                ('unlock', self.I_UNLOCK),
                ('lock_2', self.I_LOCK_2),
                ('unlock_2', self.I_UNLOCK_2),
            ):
                target.load_image()
                source = target.corp(self.device.image)
                template = target.image
                if template is None or source.size == 0:
                    score = 'unavailable'
                else:
                    result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
                    score = f'{cv2.minMaxLoc(result)[1]:.4f}'
                diagnostics.append(f'{label}={score}@{tuple(target.roi_back)}')
            logger.info(
                'RealmRaid lock match diagnostics: '
                f'shape={getattr(self.device.image, "shape", None)}, '
                + ', '.join(diagnostics)
            )
        except Exception as error:  # noqa: BLE001
            logger.warning(f'RealmRaid lock match diagnostics failed: {error}')
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

    @cached_property
    def broken_level_ocr(self) -> list:
        rules = []
        for row, y in enumerate(self.LEVEL_ROI_Y):
            for col, x in enumerate(self.LEVEL_ROI_X):
                roi = (x, y, self.LEVEL_ROI_W, self.LEVEL_ROI_H)
                rules.append(BrokenLevelOcr(
                    roi=roi,
                    area=roi,
                    mode='Digit',
                    method='Default',
                    keyword='',
                    name=f'broken_level_{row * 3 + col + 1}',
                ))
        return rules

    def read_levels(self, image=None, broken=()) -> list:
        """读出九个位次的等级。读不到 / 明显不合理的位置返回 0（后续一律不参与判断）。

        单纯读数，不点击、不改变任何状态，所以可以安全地在任何时候调用。
        """
        if image is None:
            image = self.device.image
        broken = set(broken)
        levels = []
        started_at = time.perf_counter()
        cached_ocr = getattr(self, '_ocr_cached', None)
        use_cached_ocr = callable(cached_ocr) and image is getattr(self.device, 'image', None)
        for index, normal_rule in enumerate(self.level_ocr, start=1):
            rule = self.broken_level_ocr[index - 1] if index in broken else normal_rule
            try:
                if use_cached_ocr:
                    value = cached_ocr(rule)
                else:
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
        logger.info(
            'REALM_RAID_BOARD_TIMING phase=level_ocr '
            f'durationMs={(time.perf_counter() - started_at) * 1000:.1f} '
            f'calls={len(self.level_ocr)} brokenFallbacks={len(broken)} '
            f'valid={sum(1 for value in levels if value)}'
        )
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

    def _dismiss_battle_result_continue(
        self,
        timeout: float = 5.0,
        max_clicks: int = 3,
        allow_task_reward: bool = True,
    ) -> bool:
        """Consume the normal battle result before checking board rewards.

        A red board-exit marker can remain visible behind a normal result
        overlay.  Treating that combination as a milestone reward caused the
        generic result prompt to be skipped and the board waiter to click the
        same result page repeatedly.  The board waiter owns 3/6/9 rewards
        after this method returns.
        """
        # A preparation page can also contain the reward artwork at the fixed
        # ROI.  Leave it to ``battle_before`` so the prepare button is clicked
        # before any result/reward handling is attempted.
        prepare_check = getattr(self, 'is_in_prepare', None)
        if callable(prepare_check) and prepare_check(False):
            logger.info('RealmRaid result detector skipped on battle prepare page')
            return False

        # The generic result prompt can render the same reward artwork behind
        # it. Let GeneralBattle consume that prompt first; the board waiter
        # owns the 3/6/9 modal after the result page has actually been left.
        # A milestone modal is the exception: it is already on the board, so
        # its own tap-to-continue prompt must not be sent through the generic
        # bounded result click loop.
        if allow_task_reward and self._realm_raid_board_reward_context():
            logger.info(
                'RealmRaid board reward overlay owns continuation handling'
            )
            return self._dismiss_realm_raid_board_reward(timeout)

        try:
            if super()._dismiss_battle_result_continue(
                timeout=timeout,
                max_clicks=max_clicks,
                allow_task_reward=allow_task_reward,
            ):
                return True
        except GameStuckError:
            # The board reward modal can appear during the generic result
            # sequence, after its first screenshot did not expose the board
            # close anchor. Re-check the task-specific context before
            # propagating the bounded generic failure.
            if allow_task_reward and self._realm_raid_board_reward_context():
                logger.info(
                    'RealmRaid board reward overlay appeared during '
                    'generic result handling'
                )
                return self._dismiss_realm_raid_board_reward(timeout)
            raise

        if not allow_task_reward:
            logger.info(
                'RealmRaid task reward fallback skipped: '
                'context=preflight'
            )
            return False

        if self._realm_raid_board_reward_context():
            logger.info(
                'RealmRaid board reward overlay owns continuation handling'
            )
            return self._dismiss_realm_raid_board_reward(timeout)
        return False

    def _realm_raid_board_reward_context(self) -> bool:
        """Require board context before consuming a milestone reward modal."""
        if not self.appear(self.I_BACK_RED, threshold=0.7):
            logger.info(
                'RealmRaid task reward fallback skipped: board_exit_not_visible'
            )
            return False
        is_in_real_battle = getattr(self, 'is_in_real_battle', None)
        if callable(is_in_real_battle) and is_in_real_battle(False):
            logger.info(
                'RealmRaid task reward fallback skipped: real_battle'
            )
            return False
        return self.level_reward_overlay_visible()

    def _dismiss_realm_raid_board_reward(self, timeout: float = 5.0) -> bool:
        """Dismiss one board reward modal and confirm that it cleared."""
        logger.info(
            'RealmRaid milestone reward overlay detected; '
            'dismiss with the RealmRaid reward handler'
        )
        self.dismiss_level_reward_overlay()
        deadline = time.monotonic() + min(float(timeout), 3.0)
        while time.monotonic() < deadline:
            time.sleep(0.2)
            self.screenshot()
            if not self.level_reward_overlay_visible():
                logger.info('RealmRaid milestone reward overlay cleared')
                return True
        logger.warning(
            'RealmRaid milestone reward overlay remained visible after '
            'the bounded dismiss attempt'
        )
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
                deadline = time.time() + 15
                reward_clicked = False
                reward_click_at = 0.0
                while time.time() < deadline:
                    self.screenshot()
                    result = self.O_TEXT.ocr(self.device.image)
                    if not re.search(r'[\u4e00-\u9fff]', result) and re.search(r'(\d+)/(\d+)', result):
                        return True
                    if self.level_reward_overlay_visible() and (
                        not reward_clicked or time.time() - reward_click_at >= 1.5
                    ):
                        self.dismiss_level_reward_overlay()
                        reward_clicked = True
                        reward_click_at = time.time()
                        continue
                    time.sleep(0.3)
                logger.warning('RealmRaid reward/chat overlay did not clear within 15s')
                return False

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

    def fire(self, order: int, timeout: float = 25.0) -> bool:
        """
        挑战
        :param order:  第几个
        :return:
        """
        retry_clean = 0
        deadline = time.monotonic() + max(1.0, float(timeout))
        # I_RR_PERSON is the board's right-side tab in the current client.  It
        # is not a reliable signal that a target detail card is open.  Only
        # clear a refresh popup here; target selection is handled below.
        while self.appear(self.I_FRESH_ENSURE) and time.monotonic() < deadline:
            if time.monotonic() >= deadline:
                raise GameStuckError(
                    f'RealmRaid person page did not appear within {timeout:.1f}s'
                )
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
        
        click_candidates = self._realm_raid_partition_targets(order)
        retry_clean = 0

        # 进攻循环
        while time.monotonic() < deadline:
            self.screenshot()
            
            # 双重保险：如果在进攻阶段又弹出了窗口，也把它关掉
            if self.appear(self.I_FRESH_ENSURE):
                logger.info("Refresh popup blocking attack! Clicking CANCEL.")
                self.device.click(x=530, y=460) # 点取消
                time.sleep(1.0)
                continue

            if self._click_realm_raid_fire(interval=1):
                transition_deadline = min(deadline, time.monotonic() + 4.0)
                while time.monotonic() < transition_deadline:
                    self.screenshot()
                    if not self._realm_raid_fire_visible():
                        logger.info(f'RealmRaid attack transition confirmed: target={order}')
                        logger.info(f'Click fire {order} success')
                        return True
                    time.sleep(0.2)
                self.dump_board(f'target_{order}_fire_still_visible')
                raise GameStuckError(
                    f'RealmRaid attack target {order} attack button remained visible '
                    'after click'
                )

            if retry_clean >= len(click_candidates):
                logger.error(
                    'RealmRaid target selection did not expose the attack button: '
                    f'target={order}, attempts={retry_clean}, '
                    f'candidates={len(click_candidates)}'
                )
                self.dump_board(f'target_{order}_fire_not_found')
                raise GameStuckError(
                    f'RealmRaid target {order} did not expose the attack button '
                    f'after {retry_clean} bounded selection attempts'
                )

            click = click_candidates[retry_clean]
            if self.click(click, interval=1.8):
                retry_clean += 1
                logger.info(
                    f'RealmRaid target probe: target={order}, '
                    f'candidate={click.name}, attempt={retry_clean}/'
                    f'{len(click_candidates)}'
                )
                # Each candidate has a distinct name, so BaseTask's per-rule
                # interval timer cannot enforce a settle delay across the
                # candidate list.  Give the selected-card overlay time to
                # reveal the attack button before probing another area.
                if retry_clean < len(click_candidates):
                    settle = min(0.7, max(0.0, deadline - time.monotonic()))
                    if settle > 0:
                        time.sleep(settle)
                continue
            time.sleep(0.2)

        raise GameStuckError(
            f'RealmRaid attack target {order} did not expose the attack button '
            f'within {timeout:.1f}s'
        )

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
