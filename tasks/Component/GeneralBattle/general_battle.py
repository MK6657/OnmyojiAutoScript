# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import copy
import json
import os
import time
import random
import re
from dataclasses import replace
from pathlib import Path
from time import sleep

import cv2
from module.atom.click import RuleClick
from module.atom.ocr import RuleOcr
from module.base.timer import Timer

from module.base.utils import get_color, color_similar
from module.exception import GameStuckError
from tasks.base_task import BaseTask
from tasks.Component.GeneralBattle.config_general_battle import GreenMarkType, GeneralBattleConfig
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.GeneralBattle.battle_outcome import (
    BattleOutcome,
    record_battle_result,
)
from tasks.Component.GeneralBattle.green_mark_detector import (
    GreenMarkResult,
    classify_marker_frame,
    diagnose_green_marker,
    resolve_stable_marker_frames,
)
from tasks.Component.GeneralBattle.preset_name_selector import (
    InvalidPresetConfigError,
    PresetApplyUnconfirmedError,
    PresetLookupError,
    boxed_results_to_lines,
    forget_preset_validation,
    merge_ordered_pages,
    normalize_preset_name,
    preset_validation_is_recent,
    remember_preset_validation,
    require_unique_name,
)
from tasks.Component.GeneralBuff.config_buff import BuffClass
from tasks.Component.GeneralBuff.general_buff import GeneralBuff
from tasks.Component.SwitchSoul.assets import SwitchSoulAssets
from tasks.GameUi.assets import GameUiAssets

from module.logger import logger


O_PRESET_STATUS = RuleOcr(
    roi=(350, 90, 600, 240),
    area=(350, 90, 600, 240),
    mode="Full",
    method="Default",
    keyword="",
    name="preset_status",
)

O_PRESET_CONFIRM = RuleOcr(
    roi=(660, 390, 220, 100),
    area=(660, 390, 220, 100),
    mode="Full",
    method="Default",
    keyword="确定",
    name="preset_confirm",
)

O_EXIT_CONFIRM = RuleOcr(
    roi=(650, 370, 230, 120),
    area=(650, 370, 230, 120),
    mode="Full",
    method="Default",
    # The first character covers both the current "确定" button and the
    # alternate "确认" wording without adding a second OCR pass.
    keyword="\u786e",
    name="battle_exit_confirm_text",
)

O_BATTLE_PREPARE_WIDE = RuleOcr(
    roi=(1070, 500, 210, 160),
    area=(1070, 500, 210, 160),
    mode="Single",
    method="Default",
    keyword="准备",
    name="battle_prepare_wide",
)

# The current client renders the circular "准备" control larger than the
# text/template hit area.  A random point from the full template ROI can land
# on the transparent rim and be ignored by the game, so keep a small central
# click zone for this specific control.
C_PREPARE_SAFE = RuleClick(
    roi_front=(1160, 585, 55, 55),
    roi_back=(1160, 585, 55, 55),
    name="GB_PREPARE_SAFE",
)

# The auto/manual switch is rendered in the lower-left corner of every normal
# battle page.  Use a small central zone derived from GameUiAssets' OCR ROI;
# clicking the full OCR ROI can land on the adjacent speed/statistics controls.
C_BATTLE_MODE_SAFE = RuleClick(
    roi_front=(40, 642, 42, 36),
    roi_back=(40, 642, 42, 36),
    name="GB_AUTO_MODE_TOGGLE",
)


class GeneralBattle(GeneralBuff, GeneralBattleAssets):
    """
    使用这个通用的战斗必须要求这个任务的config有config_general_battle
    """

    # A locked team should leave the preparation page without another click.
    # Keep the grace bounded so a stale lock indicator cannot strand a battle.
    LOCKED_AUTO_START_GRACE = 2.5

    def run_general_battle(self, config: GeneralBattleConfig = None, buff: BuffClass or list[BuffClass] = None) -> bool:
        """
        运行脚本
        :return:
        """
        logger.hr("General battle start", 2)
        if config is None:
            config = GeneralBattleConfig()
        # A task can be restarted while the client is waiting on the newer
        # result page. Consume that pending page before entering preparation;
        # it is the completion of the previous battle, not a new battle.
        # A task-specific result fallback (for example RealmRaid's 3/6/9
        # reward modal) is unsafe during preflight: the same fixed ROI can be
        # rendered on the preparation page.  Only consume a generic pending
        # result here; task reward handling belongs to the result loop.
        if self._dismiss_battle_result_continue(allow_task_reward=False):
            logger.info('Pending battle result continue prompt detected and dismissed')
            record_battle_result(
                self,
                BattleOutcome.RETURNED,
                'pending battle result was settled before preparation',
            )
            return True
        # 本人选择的策略是只要进来了就算一次，不管是不是打完了
        # 战斗统计
        self.current_count += 1
        logger.info(f"Current count: {self.current_count}")
        # 战前设置。未确认离开准备页时不要进入 battle_wait，否则准备页的
        # 好友图标会被 is_in_battle 当成“已在战斗”，最终无限等待战斗结果。
        if not self.battle_before(buff, config):
            logger.warning('Battle preparation was not confirmed; abort this battle safely')
            record_battle_result(
                self,
                BattleOutcome.NOT_STARTED,
                'battle preparation was not confirmed',
            )
            return False
        # Battle mode is a client-side state and can persist as manual after a
        # previous task or a user interaction.  Confirm it before green-marking
        # or entering the result wait loop so a manual battle cannot hang the
        # task indefinitely.
        auto_mode_confirmed = True
        if not getattr(self, '_battle_before_result_transition', False):
            auto_mode_confirmed = self._ensure_auto_battle_mode()
            if not auto_mode_confirmed:
                logger.warning(
                    'Battle auto mode was not confirmed; keep ownership of the '
                    'active battle until a terminal result is observed'
                )
                record_battle_result(
                    self,
                    BattleOutcome.ACTIVE_UNCONFIRMED,
                    'auto mode was not confirmed after battle started',
                )
        # 绿标
        # A preparation page also contains the friends icon used by the legacy
        # is_in_battle check. Only mark after the real battle state is confirmed.
        green_result = None
        if config.green_enable and auto_mode_confirmed and self.is_in_real_battle(False):
            green_result = self.green_mark(config.green_enable, config.green_mark)
        elif config.green_enable:
            green_result = GeneralBattle._record_green_mark_result(
                self,
                GreenMarkResult(
                    status='skipped',
                    target=getattr(config.green_mark, 'value', str(config.green_mark)),
                    reason='green mark click prohibited because battle or auto mode is unconfirmed',
                ),
            )
        # 战中设置
        try:
            win = self.battle_wait(config.random_click_swipt_enable)
        except GameStuckError as error:
            record_battle_result(
                self,
                BattleOutcome.ABORTED,
                f'battle owner failed before a terminal result: {error}',
                auto_mode_confirmed=auto_mode_confirmed,
            )
            raise
        if win:
            reason = 'battle victory and settlement completed'
            if not auto_mode_confirmed:
                reason += '; auto mode was unconfirmed'
            record_battle_result(
                self,
                BattleOutcome.VICTORY,
                reason,
                auto_mode_confirmed=auto_mode_confirmed,
                green_mark_status=getattr(green_result, 'status', None),
            )
            return True
        else:
            record_battle_result(
                self,
                BattleOutcome.DEFEAT,
                'battle defeat and result page handled',
                auto_mode_confirmed=auto_mode_confirmed,
                green_mark_status=getattr(green_result, 'status', None),
            )
            return False

    def _read_battle_mode(self) -> str | None:
        """Read the current battle mode from the shared lower-left OCR rules."""
        raw_failed = False
        image = getattr(getattr(self, 'device', None), 'image', None)
        if image is not None:
            for state, rule in (
                ('auto', GameUiAssets.O_BATTLE_AUTO),
                ('manual', GameUiAssets.O_BATTLE_HAND),
            ):
                try:
                    cached_ocr = getattr(self, '_ocr_cached', None)
                    if callable(cached_ocr):
                        text = str(cached_ocr(rule, operation='ocr_single') or '')
                    else:
                        text = str(rule.ocr_single(image) or '')
                except Exception as error:  # noqa: BLE001
                    raw_failed = True
                    logger.debug(f'Battle mode OCR unavailable for {state}: {error}')
                    continue
                compact = re.sub(r'\s+', '', text)
                if state == 'auto' and '自动' in compact:
                    return state
                if state == 'manual' and '手动' in compact:
                    return state

        # Keep lightweight harnesses and legacy device adapters compatible. In
        # the real runtime image OCR is preferred; this fallback is only used
        # when an image is unavailable or its direct OCR call failed.
        if image is None or raw_failed:
            for state, rule in (
                ('auto', GameUiAssets.O_BATTLE_AUTO),
                ('manual', GameUiAssets.O_BATTLE_HAND),
            ):
                try:
                    if self.ocr_appear(rule):
                        return state
                except Exception as error:  # noqa: BLE001
                    logger.debug(f'Battle mode OCR fallback unavailable for {state}: {error}')
        return None

    def _click_battle_mode_safe(self) -> tuple[int, int]:
        """Click once inside the stable center of the auto/manual control."""
        device = getattr(self, 'device', None)
        if device is None:
            raise RuntimeError('Battle mode toggle has no device')
        x, y = C_BATTLE_MODE_SAFE.coord()
        device.click(x=x, y=y, control_name=C_BATTLE_MODE_SAFE.name)
        logger.info(f'AUTO_MODE_ACTION action=toggle x={x} y={y} attempt=1')
        return x, y

    def _click_battle_mode_adb_fallback(self, x: int, y: int) -> bool:
        """Use one ADB tap when the configured touch channel did not toggle."""
        device = getattr(self, 'device', None)
        click_adb = getattr(device, 'click_adb', None)
        if not callable(click_adb):
            return False

        configured_method = getattr(
            getattr(getattr(device, 'config', None), 'script', None),
            'device',
            None,
        )
        configured_method = getattr(configured_method, 'control_method', None)
        if str(configured_method).lower() == 'adb':
            return False

        invalidate = getattr(device, 'invalidate_recognition_cache', None)
        if callable(invalidate):
            invalidate('battle_mode_adb_fallback')
        click_adb(x, y)
        logger.info(
            f'AUTO_MODE_ACTION action=toggle x={x} y={y} '
            'attempt=2 method=adb_fallback'
        )
        return True

    def _ensure_auto_battle_mode(
        self,
        detect_timeout: float = 3.0,
        verify_timeout: float = 3.0,
    ) -> bool:
        """Ensure the current battle is in auto mode with bounded retries.

        The mode button is stateful: clicking it when it already says auto can
        switch the game back to manual. Therefore the method never clicks on
        an unknown state. A non-ADB control channel gets one bounded ADB
        fallback only after the first click is still confirmed as manual.
        """
        deadline = time.monotonic() + max(0.0, float(detect_timeout))
        state = self._read_battle_mode()
        while state is None and time.monotonic() < deadline:
            time.sleep(0.15)
            self.screenshot()
            state = self._read_battle_mode()

        if state == 'auto':
            logger.info('AUTO_MODE_STATE state=auto source=ocr')
            logger.info('AUTO_MODE_RESULT result=enabled action=none')
            return True
        if state != 'manual':
            logger.warning(
                'AUTO_MODE_RESULT result=unrecognized '
                f'phase=before_battle timeout={float(detect_timeout):.1f}s'
            )
            return False

        logger.info('AUTO_MODE_STATE state=manual source=ocr')
        x, y = self._click_battle_mode_safe()

        deadline = time.monotonic() + max(0.0, float(verify_timeout))
        while time.monotonic() < deadline:
            time.sleep(0.15)
            self.screenshot()
            state = self._read_battle_mode()
            if state == 'auto':
                logger.info('AUTO_MODE_RESULT result=enabled action=toggle')
                return True

        if self._click_battle_mode_adb_fallback(x, y):
            deadline = time.monotonic() + max(0.0, float(verify_timeout))
            while time.monotonic() < deadline:
                time.sleep(0.15)
                self.screenshot()
                state = self._read_battle_mode()
                if state == 'auto':
                    logger.info(
                        'AUTO_MODE_RESULT result=enabled action=adb_fallback'
                    )
                    return True

        logger.warning(
            'AUTO_MODE_RESULT result=failed '
            f'expected=auto timeout={float(verify_timeout):.1f}s'
        )
        return False

    def battle_before(self, buff: BuffClass | list[BuffClass], config: GeneralBattleConfig, timeout: float = 15) -> bool:
        """战斗前设置
        :return: True:进入战斗或点击了准备按钮且识别不到准备按钮了 False:超过timeout s还没有进入战斗且没有点击过准备
        """
        timeout_timer = Timer(timeout).start()
        self._battle_before_result_transition = False
        # The current client keeps the friends icon visible on the preparation
        # page.  Give the delayed blue "准备" control a short observation
        # window before accepting that weak icon as proof of real combat.
        prepare_grace_until = time.monotonic() + 2.0
        confed = False
        prepare_clicks = 0
        last_prepare_click = 0.0
        locked_auto_start_deadline = None
        lock_auto_start_observed = False
        while not timeout_timer.reached():
            self.screenshot()
            # The current exploration client can finish so quickly that the
            # first frame after clicking auto-challenge is already the result
            # page. Treat that page as a completed battle transition and let
            # battle_wait() consume the tap-to-continue prompt.
            if self._battle_result_continue_visible():
                if (
                    locked_auto_start_deadline is not None
                    and not lock_auto_start_observed
                ):
                    logger.info(
                        'LOCK_VALIDATION state=verified '
                        'reason=result_arrived_without_prepare_click'
                    )
                    lock_auto_start_observed = True
                self._battle_before_result_transition = True
                logger.info(
                    'Battle result continue prompt appeared during preparation; '
                    'hand off to battle_wait'
                )
                return True
            if self.appear_then_click(self.I_DISABLE_7DAYS_DIFF_SOUL, interval=0.6):  # 关闭御魂不一致提示
                continue
            if self.appear_then_click(self.I_CONFIRM_CLOSE_DIFF_SOUL, interval=0.6):  # 确认关闭御魂不一致提示
                continue

            # The preparation page can expose the friends icon, which is only
            # a weak battle signal.  Resolve the preparation state first, and
            # use the same-frame prepare-button evidence even when the broader
            # OCR/template page detector is still in transition.
            prepare_visible = self._prepare_button_visible()
            if prepare_visible or self.is_in_prepare(False):  # 战斗准备阶段
                lock_enabled = bool(getattr(config, 'lock_team_enable', False))
                lock_expected_active = bool(
                    getattr(self, '_battle_lock_expected_active', True)
                )
                if lock_enabled and lock_expected_active:
                    if lock_auto_start_observed:
                        # A weak prepare detector can briefly reappear during
                        # the auto-start transition.  Once real battle has
                        # already proved the lock, never open a second grace
                        # window or click through that transient frame.
                        time.sleep(0.10)
                        continue
                    now = time.monotonic()
                    if locked_auto_start_deadline is None:
                        grace = max(
                            0.0,
                            float(getattr(self, 'LOCKED_AUTO_START_GRACE', 2.5)),
                        )
                        locked_auto_start_deadline = now + grace
                        logger.info(
                            'LOCK_VALIDATION state=waiting '
                            f'reason=prepare_visible grace={grace:.2f}s'
                        )
                    if now < locked_auto_start_deadline:
                        time.sleep(min(0.15, locked_auto_start_deadline - now))
                        continue
                    logger.warning(
                        'LOCK_VALIDATION state=failed '
                        'reason=prepare_persisted_after_lock; '
                        'use bounded prepare fallback'
                    )
                    self._battle_lock_expected_active = False
                    # A transition after the fallback click is a normal
                    # prepare transition, not proof that locking worked.
                    locked_auto_start_deadline = None
                if not lock_enabled:  # 没有锁定阵容
                    if self.current_count == 1 and not confed:  # 第一次战斗且是本次第一次配置
                        if (
                            getattr(config, 'preset_enable', False)
                            and getattr(self, '_battle_preset_preapplied', False)
                        ):
                            logger.info('Reuse preset pre-applied before entering this task')
                        else:
                            self.switch_preset_team(
                                config.preset_enable,
                                config.preset_group,
                                config.preset_team,
                                getattr(config, 'preset_group_name', ''),
                                getattr(config, 'preset_team_name', ''),
                            )
                        if self.check_and_open_buff(buff) is False:
                            logger.warning('Battle buff preparation was not confirmed')
                            return False
                        confed = True
                    elif self.current_count > 1 and getattr(config, 'preset_enable', False):
                        logger.info('Reuse preset already applied by the first battle in this task')
                # 点击准备(锁定阵容自动点准备,不锁定阵容前面也已经配置完毕需要点准备)
                now = time.monotonic()
                if prepare_clicks < 3 and now - last_prepare_click >= 0.8:
                    if self._click_prepare_button(interval=0.8):
                        prepare_clicks += 1
                        last_prepare_click = now
                        logger.info(
                            f'Prepare button clicked ({prepare_clicks}/3); '
                            'wait for real battle transition'
                        )
                        continue
                continue

            if self.is_in_real_battle(False):  # 战斗阶段
                if (
                    locked_auto_start_deadline is not None
                    and not lock_auto_start_observed
                ):
                    logger.info(
                        'LOCK_VALIDATION state=verified '
                        'reason=battle_entered_without_prepare_click'
                    )
                    self._battle_lock_expected_active = True
                    lock_auto_start_observed = True
                    locked_auto_start_deadline = None
                # A strong battle-info marker is safe immediately.  The
                # friends icon alone is deliberately debounced because it is
                # also present on the preparation page during its animation.
                if self.appear(self.I_BATTLE_INFO):
                    logger.info('GB_PREPARE_CONFIRMED state=real_battle_info')
                    return True
                if time.monotonic() < prepare_grace_until:
                    time.sleep(0.25)
                    continue
                logger.info('GB_PREPARE_CONFIRMED state=real_battle_friends')
                return True
            # 未知界面, 既不是准备界面也不是战斗界面
            # logger.info('Wait for preparation page')  # 这玩意刷屏
            sleep(random.uniform(0.4, 0.8))
        return False

    def _request_battle_exit(self, timeout: float = 12, confirm_timeout: float = 3) -> bool:
        """Click the battle exit once, then confirm without repeatedly hitting exit.

        The exit button remains detectable behind the confirmation dialog. Repeatedly
        using appear_then_click on it therefore trips Device's TooManyClick guard even
        though the dialog is already open.
        """
        start = time.time()
        exit_clicked = False
        ensure_seen = False
        while time.time() - start < timeout:
            self.screenshot()
            if self._exit_confirmation_visible(use_ocr=False):
                ensure_seen = True
                break
            if self.appear_then_click(self.I_EXIT, interval=1.5):
                exit_clicked = True
                logger.info(f"Click {self.I_EXIT.name} once; wait for confirmation")
                break
            time.sleep(0.2)

        if not exit_clicked and not ensure_seen:
            logger.warning(f'{self.I_EXIT.name} did not appear within {timeout}s')
            return False

        if not ensure_seen:
            start = time.time()
            while time.time() - start < confirm_timeout:
                self.screenshot()
                if self._exit_confirmation_visible():
                    ensure_seen = True
                    break
                if self.appear(self.I_FALSE):
                    return True
                time.sleep(0.2)

        if ensure_seen:
            if not self._click_exit_confirmation():
                logger.warning(f'{self.I_EXIT_ENSURE.name} disappeared before click')
                return False
            logger.info(f"Click {self.I_EXIT_ENSURE.name} once (template/OCR)")
        else:
            ex, ey, ew, eh = self.I_EXIT_ENSURE.roi_front
            x, y = int(ex + ew / 2), int(ey + eh / 2)
            logger.warning(
                f'{self.I_EXIT_ENSURE.name} not detected within {confirm_timeout}s; '
                f'click ROI center ({x},{y}) once'
            )
            self.device.click(x, y, control_name=f'{self.I_EXIT_ENSURE.name}_FALLBACK')
        time.sleep(1.2)
        return True

    def _exit_confirmation_visible(self, use_ocr: bool = True) -> bool:
        if self.appear(self.I_EXIT_ENSURE):
            return True
        return use_ocr and bool(self.ocr_appear(O_EXIT_CONFIRM))

    def _click_exit_confirmation(self) -> bool:
        if self.appear_then_click(self.I_EXIT_ENSURE, interval=1.5):
            return True
        if not self.ocr_appear(O_EXIT_CONFIRM):
            return False
        x, y = O_EXIT_CONFIRM.coord()
        self.device.click(x, y, control_name=O_EXIT_CONFIRM.name)
        logger.info(f'Click {O_EXIT_CONFIRM.name} once')
        return True

    def run_general_battle_back(self, config: GeneralBattleConfig = None, exit_four: bool = False) -> bool:
        """
        进入挑战然后直接返回
        :param config:
        :return:
        """
        # 【二开修复 handoff/21】本方法原本有 4 个「无超时」的 while 1。
        # 只要「退出确认」弹窗(I_EXIT_ENSURE)的模板匹配不上（游戏改版 / 分辨率差异），
        # 就会无限重复点左上角退出键——而弹窗正挡在前面，点了根本没用，
        # 于是任务静默卡死、日志一直刷 Click GB_EXIT（2026-07-27 个人突破「打九退四」实测复现）。
        # 现在：每个循环都限时；识别不到确认按钮时，按它的 ROI 中心盲点一次兜底再继续。
        timeout = 12
        ok = True

        # 如果没有锁定队伍那么在点击准备后才退出的,退四的话就直接退出
        if not config.lock_team_enable and not exit_four:
            # 点击准备按钮
            self.wait_until_appear(self.I_PREPARE_HIGHLIGHT, wait_time=15)
            t0 = time.time()
            while time.time() - t0 < timeout:
                self.screenshot()
                if self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=1.5):
                    continue
                if not (self.appear(self.I_PRESET) or self.appear(self.I_PRESET_WIT_NUMBER)):
                    break
            else:
                ok = False
                logger.warning(f'{self.I_PREPARE_HIGHLIGHT.name} 点击准备超时({timeout}s)，继续尝试退出')
            logger.info(f"Click {self.I_PREPARE_HIGHLIGHT.name}")

        if not self._request_battle_exit(timeout=timeout):
            return False

        # Wait for the failure result. The fallback may have clicked slightly early,
        # so one template-confirmed retry is allowed, but never a click loop.
        t0 = time.time()
        ensure_retried = False
        while time.time() - t0 < timeout:
            self.screenshot()
            if self.appear(self.I_FALSE):
                break
            if not ensure_retried and self._click_exit_confirmation():
                ensure_retried = True
                logger.info(f"Retry {self.I_EXIT_ENSURE.name} once")
                continue
            time.sleep(0.2)
        else:
            logger.warning(f'{self.I_FALSE.name} did not appear within {timeout}s')
            return False

        if not self.appear_then_click(self.I_FALSE, interval=1.5):
            logger.warning(f'{self.I_FALSE.name} disappeared before click')
            return False
        logger.info(f"Click {self.I_FALSE.name} once")

        t0 = time.time()
        while time.time() - t0 < timeout:
            self.screenshot()
            if not self.appear(self.I_FALSE):
                return ok
            time.sleep(0.2)
        logger.warning(f'{self.I_FALSE.name} did not close within {timeout}s')
        return False

    def exit_battle(self, skip_first: bool = False) -> bool:
        """
        在战斗的时候强制退出战斗
        :return:
        """
        if skip_first:
            self.screenshot()

        if not self.appear(self.I_EXIT) and not self.appear(self.I_EXIT_ENSURE):
            return False

        # 【二开修复】退出键只点一次，避免弹窗出现后仍持续点退出键触发 TooManyClick。
        timeout = 12
        if not self._request_battle_exit(timeout=timeout):
            return False

        # 结算页和战斗页都只允许单次点击；其余时间等待状态变化。
        t0 = time.time()
        ensure_retried = False
        false_clicked = False
        while time.time() - t0 < timeout:
            self.screenshot()
            if not ensure_retried and self._click_exit_confirmation():
                ensure_retried = True
                continue
            if not false_clicked and self.appear_then_click(self.I_FALSE, interval=1.5):
                false_clicked = True
                continue
            if not self.appear(self.I_EXIT) and not self.appear(self.I_EXIT_ENSURE) \
                    and not self.appear(self.I_FALSE):
                break
            time.sleep(0.2)
        else:
            logger.warning(f'exit_battle: {timeout}s 内没能确认退出，交由上层逻辑继续处理')
            return False

        return True

    BATTLE_WAIT_TIMEOUT_SECONDS = 300.0

    def battle_wait(
        self,
        random_click_swipt_enable: bool,
        timeout: float = BATTLE_WAIT_TIMEOUT_SECONDS,
    ) -> bool:
        """
        等待战斗结束 ！！！
        很重要 这个函数是原先写的， 优化版本在tasks/Secret/script_task下。本着不改动原先的代码的原则，所以就不改了
        :param random_click_swipt_enable:
        :return:
        """
        # 有的时候是长战斗，需要在设置stuck检测为长战斗
        # 但是无需取消设置，因为如果有点击或者滑动的话 handle_control_check会自行取消掉
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()
        # 战斗过程 随机点击和滑动 防封
        logger.info("Start battle process")
        deadline = time.monotonic() + max(1.0, float(timeout))
        battle_timing_started = time.monotonic()
        logger.info('BATTLE_RESULT_TIMING stage=wait_start')

        def check_deadline(stage: str) -> None:
            if time.monotonic() >= deadline:
                logger.error(
                    f'General battle timed out after {float(timeout):.1f}s at stage={stage}'
                )
                raise GameStuckError(
                    f'General battle result timeout at stage={stage}'
                )

        win: bool = False
        result_continue_dismissed = False
        result_context_confirmed = False
        rejected_reward_assets: set[str] = set()
        while 1:
            check_deadline('result')
            self.screenshot()
            # 如果出现赢 就点击, 第二个是针对封魔的图片
            # Current clients may show a dimmed "tap to continue" result page
            # instead of the legacy win/reward templates.
            previous_empty_visual = getattr(self, '_allow_empty_result_visual', False)
            self._allow_empty_result_visual = True
            try:
                result_continue_handled = self._dismiss_battle_result_continue()
            finally:
                self._allow_empty_result_visual = previous_empty_visual
            if result_continue_handled:
                logger.info('Battle result continue prompt detected and dismissed')
                logger.info(
                    'BATTLE_RESULT_TIMING stage=continuation_handled '
                    f'elapsed={time.monotonic() - battle_timing_started:.3f}s'
                )
                win = True
                result_continue_dismissed = True
                break

            if self.appear(self.I_WIN, threshold=0.8) or self.appear(self.I_DE_WIN):
                logger.info("Battle result is win")
                result_context_confirmed = True
                if self.appear(self.I_DE_WIN):
                    self.ui_click_until_disappear(self.I_DE_WIN)
                win = True
                break

            # 如果出现失败 就点击，返回False
            if self.appear(self.I_FALSE, threshold=0.8):
                logger.info("Battle result is false")
                result_context_confirmed = True
                win = False
                break

            # 如果领奖励
            if self.appear(self.I_REWARD, threshold=0.6):
                if result_context_confirmed:
                    win = True
                    break
                if 'I_REWARD' not in rejected_reward_assets:
                    logger.warning(
                        'BATTLE_REWARD_REJECTED reason=no_result_context asset=I_REWARD'
                    )
                    rejected_reward_assets.add('I_REWARD')

            # 如果领奖励出现金币
            if self.appear(self.I_REWARD_GOLD, threshold=0.8):
                if result_context_confirmed:
                    win = True
                    break
                if 'I_REWARD_GOLD' not in rejected_reward_assets:
                    logger.warning(
                        'BATTLE_REWARD_REJECTED '
                        'reason=no_result_context asset=I_REWARD_GOLD'
                    )
                    rejected_reward_assets.add('I_REWARD_GOLD')
            # 如果开启战斗过程随机滑动
            if random_click_swipt_enable:
                self.random_click_swipt_nonblocking()

        if result_continue_dismissed:
            logger.info('Tap-to-continue result has no separate reward panel')
            return win

        # 再次确认战斗结果
        logger.info("Reconfirm the results of the battle")
        while 1:
            check_deadline('result_confirmation')
            self.screenshot()
            if win:
                # 点击赢了
                action_click = random.choice([self.C_WIN_1, self.C_WIN_2, self.C_WIN_3])
                if self.appear_then_click(self.I_WIN, action=action_click, interval=0.5):
                    continue
                if not self.appear(self.I_WIN):
                    break
            else:
                # 如果失败且 点击失败后
                if self.appear_then_click(self.I_FALSE, threshold=0.6):
                    continue
                if not self.appear(self.I_FALSE, threshold=0.6):
                    return False

        # 最后保证能点击 获得奖励
        reward_deadline = min(deadline, time.monotonic() + 10.0)
        reward_seen = False
        while time.monotonic() < reward_deadline:
            self.screenshot()
            if (self.appear(self.I_REWARD, threshold=0.6) or
                    self.appear(self.I_REWARD_GOLD, threshold=0.8)):
                reward_seen = True
                break
            if self._battle_result_continue_visible() or self.appear(self.I_STATISTICS):
                break
            time.sleep(0.2)
        logger.info(
            'BATTLE_RESULT_TIMING stage=reward_probe '
            f'reward_seen={reward_seen} elapsed={time.monotonic() - battle_timing_started:.3f}s'
        )
        if not reward_seen:
            if not self.appear(self.I_STATISTICS):
                # 有些的战斗没有下面的奖励，所以直接返回
                logger.info("There is no reward, Exit battle")
                # Current clients can leave the tap-to-continue overlay visible
                # even when no separate reward panel is rendered. Consume that
                # overlay before returning success so the caller can verify the
                # real destination page instead of timing out on the result page.
                if self._battle_result_continue_visible():
                    self._click_result_continue_bottom()
                return win
        logger.info("Get reward")
        while 1:
            check_deadline('reward')
            self.screenshot()
            # 如果出现领奖励
            action_click = random.choice([self.C_REWARD_1, self.C_REWARD_2, self.C_REWARD_3])
            if (self.appear_then_click(self.I_REWARD, action=action_click, interval=1.5) or
                self.appear_then_click(self.I_REWARD_GOLD, action=action_click, interval=1.5)#  or
                # self.appear_then_click(self.I_REWARD_STATISTICS, action=action_click, interval=1.5) or
                # self.appear_then_click(self.I_REWARD_PURPLE_SNAKE_SKIN, action=action_click, interval=1.5) or
                # self.appear_then_click(self.I_REWARD_GOLD_SNAKE_SKIN, action=action_click, interval=1.5) or
                # self.appear_then_click(self.I_REWARD_EXP_SOUL_4, action=action_click, interval=1.5) or
                # self.appear_then_click(self.I_REWARD_SOUL_5, action=action_click, interval=1.5) or
                # self.appear_then_click(self.I_REWARD_SOUL_6, action=action_click, interval=1.5)
                ):
                continue
            if self._hook_special_reward():
                continue
            if (not self.appear(self.I_REWARD) and
                not self.appear(self.I_REWARD_GOLD)  # and
                # not self.appear(self.I_REWARD_STATISTICS) and
                # not self.appear(self.I_REWARD_PURPLE_SNAKE_SKIN) and
                # not self.appear(self.I_REWARD_GOLD_SNAKE_SKIN) and
                # not self.appear(self.I_REWARD_EXP_SOUL_4) and
                # not self.appear(self.I_REWARD_SOUL_5) and
                # not self.appear(self.I_REWARD_SOUL_6)
                ):
                break

        return win

    def _dismiss_battle_result_continue(
        self,
        timeout: float = 5.0,
        max_clicks: int = 3,
        allow_task_reward: bool = True,
    ) -> bool:
        """Consume continuation pages with a fast path and bounded fallback.

        ``allow_task_reward`` is a context contract for task subclasses.  The
        generic implementation has no task-specific reward fallback, but it
        accepts the flag so preflight callers can explicitly disable one in a
        subclass without relying on a best-effort prepare-page recognition.
        """
        sequence_started = time.monotonic()
        timeout_value = float(timeout)
        sequence_deadline = (
            float('inf') if timeout_value <= 0 else sequence_started + timeout_value
        )
        if not self._battle_result_continue_visible():
            return False

        center_fallback_used = False
        bottom_fallback_used = False
        for click_number in range(1, max_clicks + 1):
            if not self._battle_result_continue_visible():
                logger.info(
                    'BATTLE_RESULT_TIMING stage=sequence_complete '
                    f'clicks={click_number - 1} elapsed={time.monotonic() - sequence_started:.3f}s'
                )
                return False
            clicked = self.ocr_appear_click(self.O_BATTLE_RESULT_CONTINUE, interval=0.8)
            if not clicked:
                image = getattr(getattr(self, 'device', None), 'image', None)
                prepare_check = getattr(self, '_prepare_button_visible', None)
                prepare_visible = callable(prepare_check) and prepare_check()
                # Visibility accepts small OCR substitutions such as the first
                # character in "点击屏幕继续". If the exact SINGLE OCR click
                # misses, the same-frame semantic evidence is still enough to
                # use the fixed bottom safe point.
                if not prepare_visible and self._battle_result_continue_visible():
                    clicked = self._click_result_continue_bottom()
                    if clicked:
                        logger.info(
                            'BATTLE_RESULT_TIMING stage=text_guard_click '
                            f'click={click_number} '
                            f'elapsed={time.monotonic() - sequence_started:.3f}s'
                        )
                if not clicked and not prepare_visible and self._battle_result_visual_heuristic(image):
                    clicked = self._click_result_continue_bottom()
                    if clicked:
                        logger.info(
                            'BATTLE_RESULT_TIMING stage=visual_guard_click '
                            f'click={click_number} elapsed={time.monotonic() - sequence_started:.3f}s'
                        )
            if not clicked:
                # The prompt may have disappeared during the interval guard.
                # Re-observe before treating the click as a failed transition.
                if not self._battle_result_continue_visible():
                    return True
                if time.monotonic() >= sequence_deadline:
                    break
                time.sleep(0.05)
                continue

            logger.info(
                'BATTLE_RESULT_TIMING stage=continuation_click '
                f'click={click_number} elapsed={time.monotonic() - sequence_started:.3f}s'
            )

            fast_wait = 0.0 if timeout_value <= 0 else 1.5
            fast_deadline = min(sequence_deadline, time.monotonic() + fast_wait)
            absent_frames = 0
            while time.monotonic() < fast_deadline:
                time.sleep(0.2)
                self.screenshot()
                if self._battle_result_continue_visible():
                    absent_frames = 0
                    continue

                followup_check = getattr(self, '_battle_result_followup_visible', None)
                if callable(followup_check) and followup_check():
                    logger.info(
                        'BATTLE_RESULT_TIMING stage=followup_visible '
                        f'click={click_number} elapsed={time.monotonic() - sequence_started:.3f}s'
                    )
                    break

                absent_frames += 1
                if absent_frames < 2:
                    continue

                # A result animation can briefly lose OCR and then show the
                # next continuation page. Keep the current battle in control
                # instead of returning to the outer scene loop too early.
                grace_deadline = min(sequence_deadline, time.monotonic() + 1.0)
                while time.monotonic() < grace_deadline:
                    time.sleep(0.2)
                    self.screenshot()
                    if self._battle_result_continue_visible():
                        break
                else:
                    logger.info(
                        'BATTLE_RESULT_TIMING stage=sequence_complete '
                        f'clicks={click_number} elapsed={time.monotonic() - sequence_started:.3f}s'
                    )
                    return True
                break

            if not self._battle_result_continue_visible():
                logger.info(
                    'BATTLE_RESULT_TIMING stage=sequence_complete '
                    f'clicks={click_number} elapsed={time.monotonic() - sequence_started:.3f}s'
                )
                return True
            if click_number < max_clicks:
                logger.warning(
                    'Result continuation page remained visible; consume the next '
                    f'page with bounded click {click_number + 1}/{max_clicks}'
                )
                if not center_fallback_used:
                    center_fallback_used = self._click_result_continue_center()
                    if center_fallback_used:
                        logger.info(
                            'BATTLE_RESULT_TIMING stage=center_fallback '
                            f'click={click_number} elapsed={time.monotonic() - sequence_started:.3f}s'
                        )
                        time.sleep(0.2)
                        if not self._battle_result_continue_visible():
                            logger.info(
                                'Battle result continuation completed after center fallback'
                            )
                            return True
                elif not bottom_fallback_used:
                    bottom_fallback_used = self._click_result_continue_bottom()
                    if bottom_fallback_used:
                        logger.info(
                            'BATTLE_RESULT_TIMING stage=bottom_fallback '
                            f'click={click_number} elapsed={time.monotonic() - sequence_started:.3f}s'
                        )
                        time.sleep(0.2)
                        if not self._battle_result_continue_visible():
                            return True

            if time.monotonic() >= sequence_deadline:
                break

        logger.warning(
            f'Result continuation sequence reached the {max_clicks}-click limit'
        )
        raise GameStuckError(
            f'Battle result continuation remained visible after {max_clicks} clicks'
        )

    def _battle_result_continue_visible(self) -> bool:
        """Recognize the continuation prompt without a second OCR pass."""
        device = getattr(self, 'device', None)
        image = getattr(device, 'image', None)
        if image is None:
            # Keep lightweight test harnesses and legacy callers compatible.
            return self.ocr_appear(self.O_BATTLE_RESULT_CONTINUE)

        try:
            cached_ocr = getattr(self, '_ocr_cached', None)
            if callable(cached_ocr):
                text = str(
                    cached_ocr(
                        self.O_BATTLE_RESULT_CONTINUE,
                        operation='ocr_single',
                    ) or ''
                )
            else:
                text = str(self.O_BATTLE_RESULT_CONTINUE.ocr_single(image) or '')
        except Exception as error:  # noqa: BLE001
            logger.debug(f'Battle result continue OCR text unavailable: {error}')
            return False

        compact = re.sub(r'\s+', '', text)
        visible = '屏幕' in compact and '继续' in compact
        if not visible and not compact:
            if getattr(self, '_allow_empty_result_visual', False):
                prepare_check = getattr(self, '_prepare_button_visible', None)
                if callable(prepare_check) and prepare_check():
                    logger.debug(
                        'BATTLE_RESULT_CONTINUE_VISUAL_REJECT reason=prepare_page'
                    )
                    return False
                if self._battle_result_visual_heuristic(image):
                    logger.info(
                        'BATTLE_RESULT_CONTINUE_VISUAL_ACCEPT reason=empty_ocr'
                    )
                    return True
            logger.debug(
                'BATTLE_RESULT_CONTINUE_OCR_EMPTY '
                'visual_fallback=disabled_or_no_match'
            )
        return visible

    def _battle_result_followup_visible(self) -> bool:
        """Detect a confirmed result/reward page while continuation fades."""
        for name in (
            'I_WIN',
            'I_FALSE',
            'I_REWARD',
            'I_REWARD_GOLD',
            'I_STATISTICS',
        ):
            target = getattr(self, name, None)
            if target is not None and self.appear(target):
                return True
        return False

    @staticmethod
    def _battle_result_visual_heuristic(image) -> bool:
        """Recognize a dimmed tap-to-continue result page without OCR text."""
        if image is None or getattr(image, 'ndim', 0) != 3:
            return False
        try:
            height, width = image.shape[:2]
            if width < 1000 or height < 600:
                return False

            # Screenshot providers may return RGB or BGR frames, so use the
            # channel mean instead of a color-specific conversion.
            gray = image.astype('float32').mean(axis=2)
            top = gray[0:160, 0:1280]
            center = gray[360:650, 450:830]
            prompt = gray[650:715, 520:780]
            center_dark = float((center < 100).mean())
            top_mean = float(top.mean())
            prompt_mid = float(((prompt >= 80) & (prompt < 160)).mean())
            return (
                center_dark >= 0.60
                and top_mean <= 50.0
                and prompt_mid >= 0.60
            )
        except Exception as error:  # noqa: BLE001
            logger.debug(f'Battle result visual guard unavailable: {error}')
            return False

    def _click_result_continue_center(self) -> bool:
        """Use one bounded center tap when the text-ROI tap did not advance."""
        device = getattr(self, 'device', None)
        if device is None:
            return False
        click_rule = getattr(self, 'C_RANDOM_CLICK', None)
        if click_rule is None:
            # Test/dry-run harnesses may not load the generated asset class;
            # the runtime device coordinate system is still 1280x720.
            x, y = 629, 332
        else:
            x, y = click_rule.center
        device.click(
            x=x,
            y=y,
            control_name='BATTLE_RESULT_CONTINUE_CENTER',
        )
        logger.info(
            f'Battle result continuation center fallback clicked at ({x},{y})'
        )
        return True

    def _click_result_continue_bottom(self) -> bool:
        """Tap the visible bottom continuation prompt with a stable safe point."""
        device = getattr(self, 'device', None)
        if device is None:
            return False
        image = getattr(device, 'image', None)
        height, width = 720, 1280
        if image is not None and getattr(image, 'ndim', 0) >= 2:
            height, width = image.shape[:2]
        x = width // 2
        y = max(0, height - 45)
        device.click(
            x=x,
            y=y,
            control_name='BATTLE_RESULT_CONTINUE_BOTTOM',
        )
        logger.info(
            f'Battle result continuation bottom fallback clicked at ({x},{y})'
        )
        return True

    def _hook_special_reward(self) -> bool:
        """
        For overwrite https://github.com/runhey/OnmyojiAutoScript/issues/1580
        """
        return False

    def green_mark(self, enable: bool = False, mark_mode: GreenMarkType = GreenMarkType.GREEN_MAIN):
        """
        绿标， 如果不使能就直接返回
        :param enable:
        :param mark_mode:
        :return:
        """
        target_name = getattr(mark_mode, 'value', str(mark_mode))
        if not enable:
            return GeneralBattle._record_green_mark_result(
                self,
                GreenMarkResult(
                    status='skipped',
                    target=target_name,
                    reason='green mark is disabled',
                ),
            )
        if enable:
            logger.info("Green is enable")
            target_rule = None
            match mark_mode:
                case GreenMarkType.GREEN_LEFT1:
                    target_rule = self.C_GREEN_LEFT_1
                    logger.info("Green left 1")
                case GreenMarkType.GREEN_LEFT2:
                    target_rule = self.C_GREEN_LEFT_2
                    logger.info("Green left 2")
                case GreenMarkType.GREEN_LEFT3:
                    target_rule = self.C_GREEN_LEFT_3
                    logger.info("Green left 3")
                case GreenMarkType.GREEN_LEFT4:
                    target_rule = self.C_GREEN_LEFT_4
                    logger.info("Green left 4")
                case GreenMarkType.GREEN_LEFT5:
                    target_rule = self.C_GREEN_LEFT_5
                    logger.info("Green left 5")
                case GreenMarkType.GREEN_MAIN:
                    target_rule = self.C_GREEN_MAIN
                    logger.info("Green main")
            if target_rule is None:
                logger.warning(f'Green mark mode is unsupported: {mark_mode}')
                return GeneralBattle._record_green_mark_result(
                    self,
                    GreenMarkResult(
                        status='skipped',
                        target=target_name,
                        reason='unsupported green mark target',
                    ),
                )

            readiness = GeneralBattle._wait_green_mark_ready_result(
                self,
                target_name=target_name,
            )
            if readiness.status != 'ready':
                logger.warning(f'Green mark skipped: {readiness.reason}')
                return GeneralBattle._record_green_mark_result(
                    self,
                    readiness,
                )

            # 判断有无坐标的偏移
            self.appear_then_click(self.I_LOCAL)
            observation_history = []
            for attempt in range(1, 3):
                x, y = target_rule.coord()
                self.device.click(x, y, control_name=f'GREEN_MARK:{mark_mode.value}:{attempt}')
                result = self._wait_green_marker_confirmation_result(
                    target_rule,
                    timeout=2.0,
                    observation_history=observation_history,
                    auto_mode_preconfirmed=True,
                )
                result = replace(result, click_point=(x, y), attempts=attempt)
                if result.status in {'terminal', 'skipped'}:
                    return GeneralBattle._record_green_mark_result(self, result)
                if result.status == 'confirmed':
                    logger.info(
                        f'Green mark confirmed: {mark_mode.value} at ({x},{y}), '
                        f'attempt={attempt}'
                    )
                    return GeneralBattle._record_green_mark_result(self, result)
                logger.warning(
                    f'Green mark click unconfirmed: {mark_mode.value}, '
                    f'attempt={attempt}, coordinate=({x},{y})'
                )
                time.sleep(0.3)
            return GeneralBattle._record_green_mark_result(self, result)

    def _wait_green_mark_ready_result(
        self,
        *,
        target_name: str,
        timeout: float = 3.0,
        required_frames: int = 2,
    ) -> GreenMarkResult:
        """Require consecutive real-battle and auto-mode frames before clicking."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        stable = 0
        last_reason = 'no valid battle frame was observed'
        while time.monotonic() <= deadline:
            self.screenshot()
            if self._battle_terminal_visible():
                return GreenMarkResult(
                    status='terminal',
                    target=target_name,
                    stable_frames=stable,
                    reason='battle terminal appeared before green mark click',
                )
            real_battle = bool(self.is_in_real_battle(False))
            mode_reader = getattr(self, '_read_battle_mode', None)
            battle_mode = mode_reader() if callable(mode_reader) else None
            if real_battle and battle_mode == 'auto':
                stable += 1
                if stable >= max(2, int(required_frames)):
                    return GreenMarkResult(
                        status='ready',
                        target=target_name,
                        stable_frames=stable,
                        reason='real battle and auto mode were stable in consecutive frames',
                    )
            else:
                stable = 0
                last_reason = (
                    f'real_battle={real_battle}, auto_mode={battle_mode or "unknown"}'
                )
            time.sleep(0.15)
        return GreenMarkResult(
            status='skipped',
            target=target_name,
            stable_frames=stable,
            reason=f'green mark readiness was not confirmed: {last_reason}',
        )

    def _record_green_mark_result(self, result: GreenMarkResult) -> GreenMarkResult:
        self.last_green_mark_result = result
        logger.info(
            'GREEN_MARK_RESULT '
            + json.dumps(result.to_dict(), ensure_ascii=False, separators=(',', ':'))
        )
        return result

    def _wait_green_marker_confirmation(self, target_rule, timeout: float = 2.0) -> bool:
        """Confirm a stable green arrow in the requested exclusive friendly slot."""
        return bool(
            GeneralBattle._wait_green_marker_confirmation_result(
                self,
                target_rule,
                timeout=timeout,
            )
        )

    def _wait_green_marker_confirmation_result(
        self,
        target_rule,
        timeout: float = 2.0,
        observation_history: list | None = None,
        auto_mode_preconfirmed: bool = False,
    ) -> GreenMarkResult:
        """Return structured evidence for one bounded confirmation attempt."""
        target_name = getattr(target_rule, 'name', 'green_mark_target')
        slot_rois = GeneralBattle._green_mark_slot_rois(self)
        canonical_target = GeneralBattle._canonical_green_slot(target_name)
        if canonical_target not in slot_rois:
            return GreenMarkResult(
                status='unconfirmed',
                target=canonical_target,
                expected_slot=canonical_target,
                reason='target has no calibrated exclusive friendly slot',
            )
        deadline = time.monotonic() + timeout
        marker_assets = (
            self.I_GREEN_MARKER_LEFT_TOP,
            self.I_GREEN_MARKER_BOTTOM,
            self.I_GREEN_MARKER,
        )
        diagnostics_enabled = os.environ.get('OAS_GREEN_MARK_DIAGNOSTICS', '').strip().lower() in {
            '1', 'true', 'yes', 'on',
        }
        last_diagnostic = None
        observations = observation_history if observation_history is not None else []
        device = getattr(self, 'device', None)
        interval_timer = getattr(device, '_screenshot_interval', None)
        previous_interval = getattr(interval_timer, 'limit', None)
        interval_setter = getattr(device, 'screenshot_interval_set', None)
        interval_changed = callable(interval_setter) and previous_interval is not None
        if interval_changed:
            # The green arrow can remain fully visible for less than 0.5s.
            # Keep the protected screenshot path, but temporarily sample at
            # 0.1s instead of the normal 0.3s business-page cadence.
            interval_setter(0.1)
        cached_battle_mode = 'auto' if auto_mode_preconfirmed else None
        next_mode_check = time.monotonic() + (
            0.6 if auto_mode_preconfirmed else 0.0
        )
        last_result = GreenMarkResult(
            status='unconfirmed',
            target=canonical_target,
            expected_slot=canonical_target,
            reason='no stable colored marker evidence was observed',
        )
        try:
            while time.monotonic() < deadline:
                self.screenshot()
                last_diagnostic = GeneralBattle._green_mark_diagnostic(
                    self, target_rule, marker_assets
                )
                if diagnostics_enabled:
                    GeneralBattle._log_green_mark_diagnostic(
                        self, last_diagnostic, evidence=True
                    )
                terminal_check = getattr(self, '_battle_terminal_visible', None)
                if callable(terminal_check) and terminal_check():
                    logger.info(
                        'Green mark confirmation short-circuited by battle terminal'
                    )
                    diagnostic = last_diagnostic or GeneralBattle._green_mark_diagnostic(
                        self, target_rule, marker_assets
                    )
                    return GreenMarkResult(
                        status='terminal',
                        target=canonical_target,
                        expected_slot=canonical_target,
                        max_score=GeneralBattle._green_mark_max_score(diagnostic),
                        frame_sha256=getattr(diagnostic, 'frame_sha256', None),
                        reason='battle terminal appeared during green mark confirmation',
                    )
                real_battle = bool(self.is_in_real_battle(False))
                now = time.monotonic()
                if cached_battle_mode is None or now >= next_mode_check:
                    cached_battle_mode = self._read_battle_mode()
                    next_mode_check = now + 0.6
                battle_mode = cached_battle_mode
                if battle_mode == 'manual':
                    return GreenMarkResult(
                        status='skipped',
                        target=canonical_target,
                        expected_slot=canonical_target,
                        max_score=GeneralBattle._green_mark_max_score(last_diagnostic),
                        frame_sha256=getattr(last_diagnostic, 'frame_sha256', None),
                        reason='battle mode explicitly changed to manual during marker verification',
                    )
                if not real_battle or battle_mode != 'auto':
                    # Skill cinematics temporarily hide both the battle marker and
                    # the auto label. Readiness was already confirmed before the
                    # click, so treat an unknown frame as transient within this
                    # bounded verification window. Terminal pages remain owned by
                    # the explicit terminal guard above.
                    logger.debug(
                        'Green mark verification frame is transient: '
                        f'real_battle={real_battle}, auto_mode={battle_mode or "unknown"}'
                    )
                    time.sleep(0.05)
                    continue
                image = getattr(getattr(self, 'device', None), 'image', None)
                if image is None:
                    break
                observation = classify_marker_frame(
                    image,
                    expected_slot=canonical_target,
                    slot_rois=slot_rois,
                )
                if not any(
                    item.frame_sha256 == observation.frame_sha256
                    for item in observations
                ):
                    observations.append(observation)
                    del observations[:-3]
                last_result = resolve_stable_marker_frames(
                    observations,
                    expected_slot=canonical_target,
                )
                last_result = replace(
                    last_result,
                    max_score=GeneralBattle._green_mark_max_score(last_diagnostic),
                )
                if last_result.status in {'enemy_selected', 'wrong_target'}:
                    return last_result
                if last_result.status == 'confirmed':
                    mode = os.environ.get(
                        'OAS_GREEN_MARK_COLOR_SLOT_MODE', 'detect_only'
                    ).strip().lower()
                    if mode == 'enforce':
                        return last_result
                    return replace(
                        last_result,
                        status='unconfirmed',
                        reason=(
                            'stable green marker detected, but color-slot detector is '
                            'detect-only until five anchors and a red sample are validated'
                        ),
                    )
                time.sleep(0.05)
        finally:
            if interval_changed:
                interval_setter(previous_interval)
        if last_diagnostic is None:
            last_diagnostic = GeneralBattle._green_mark_diagnostic(
                self, target_rule, marker_assets
            )
        GeneralBattle._log_green_mark_diagnostic(
            self, last_diagnostic, evidence=False, timeout=True
        )
        return GreenMarkResult(
            status='unconfirmed',
            target=canonical_target,
            marker_point=last_result.marker_point,
            detector=last_result.detector,
            max_score=GeneralBattle._green_mark_max_score(last_diagnostic),
            frame_sha256=getattr(last_diagnostic, 'frame_sha256', None),
            reason='no stable colored marker was confirmed in the requested slot',
            color=last_result.color,
            expected_slot=canonical_target,
            assigned_slot=last_result.assigned_slot,
            marker_tip=last_result.marker_tip,
            stable_frames=last_result.stable_frames,
            confidence=last_result.confidence,
        )

    @staticmethod
    def _canonical_green_slot(name: str) -> str:
        value = str(name).strip().lower()
        for index in range(1, 6):
            if value in {f'green_left{index}', f'green_left_{index}', f'left{index}'}:
                return f'green_left{index}'
        return value

    def _green_mark_slot_rois(self) -> dict[str, tuple[int, int, int, int]]:
        return {
            f'green_left{index}': tuple(
                int(value)
                for value in getattr(
                    self,
                    f'C_GREEN_LEFT_{index}',
                    getattr(GeneralBattleAssets, f'C_GREEN_LEFT_{index}'),
                ).roi_front
            )
            for index in range(1, 6)
        }

    @staticmethod
    def _green_mark_max_score(diagnostic) -> float | None:
        templates = getattr(diagnostic, 'templates', ()) if diagnostic is not None else ()
        scores = [item.max_score for item in templates if item.max_score is not None]
        return max(scores) if scores else None

    def _green_mark_diagnostic(self, target_rule, marker_assets):
        device = getattr(self, 'device', None)
        image = getattr(device, 'image', None)
        if image is None:
            return None
        return diagnose_green_marker(
            image,
            target_name=target_rule.name,
            target_roi=target_rule.roi_front,
            template_assets=marker_assets,
        )

    def _log_green_mark_diagnostic(self, result, *, evidence: bool, timeout: bool = False) -> None:
        if result is None:
            return
        payload = result.to_dict()
        payload['event'] = 'green_mark_confirmation_timeout' if timeout else 'green_mark_frame'
        if evidence:
            evidence_dir = os.environ.get('OAS_GREEN_MARK_EVIDENCE_DIR', '').strip()
            if evidence_dir:
                output_dir = Path(evidence_dir).expanduser().resolve()
                output_dir.mkdir(parents=True, exist_ok=True)
                filename = (
                    f"{time.time_ns()}-{result.target_name}-"
                    f"{result.frame_sha256[:12]}.png"
                )
                output_path = output_dir / filename
                rgb = self.device.image[:, :, :3]
                encoded, buffer = cv2.imencode('.png', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                if encoded:
                    buffer.tofile(str(output_path))
                    payload['evidence_file'] = str(output_path)
        message = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        if timeout:
            logger.warning(f'GREEN_MARK_DIAGNOSTIC {message}')
        else:
            logger.info(f'GREEN_MARK_DIAGNOSTIC {message}')

    def _battle_terminal_visible(self) -> bool:
        """Return true for result/reward states that must own the next click."""
        for name in ('I_WIN', 'I_FALSE', 'I_REWARD', 'I_REWARD_GOLD', 'I_DE_WIN'):
            target = getattr(self, name, None)
            if target is not None and self.appear(target):
                return True
        result_visible = getattr(self, '_battle_result_continue_visible', None)
        return callable(result_visible) and result_visible()

    def switch_preset_team(
        self,
        enable: bool = False,
        preset_group: int = 1,
        preset_team: int = 1,
        preset_group_name: str = '',
        preset_team_name: str = '',
    ):
        """Switch a battle preset by name, with legacy index fallback.

        Current game versions use the same right-side group and middle team lists
        as SwitchSoul. Historical numeric fields stay readable so old task configs
        keep working, but new configurations should always provide both names.
        """
        if not enable:
            logger.info("Preset is disable")
            return None

        group_name = str(preset_group_name or '').strip()
        team_name = str(preset_team_name or '').strip()
        if group_name or team_name:
            if not group_name or not team_name:
                raise InvalidPresetConfigError(
                    '预设队伍配置不完整：分组名称和队伍名称必须同时填写'
                )
            try:
                return self._switch_preset_team_by_name(group_name, team_name)
            except PresetLookupError as error:
                logger.error(f'Preset name selection stopped: {error}')
                raise

        logger.warning(
            'Preset names are empty; use legacy fixed index selection '
            f'group={preset_group}, team={preset_team}'
        )
        return self._switch_preset_team_legacy(preset_group, preset_team)

    @staticmethod
    def _preset_page_names(lines) -> list[str]:
        return [normalize_preset_name(line.text) for line in lines if normalize_preset_name(line.text)]

    def _preset_ocr_lines(self, rule: RuleOcr):
        cached_detect = getattr(self, '_detect_cached', None)
        if callable(cached_detect):
            results = cached_detect(rule)
        else:
            results = rule.detect_and_ocr(self.device.image)
        # Team title inputs start at the left edge of this ROI. Empty-team hints and
        # plus icons are farther right and must not be treated as additional teams.
        max_left = 35 if rule is SwitchSoulAssets.O_SS_TEAM_NAME else None
        return boxed_results_to_lines(results, max_left=max_left)

    PRESET_GROUP_PANEL_ROI = (1110, 94, 1226, 627)
    PRESET_GROUP_PANEL_BRIGHT_THRESHOLD = 160
    PRESET_GROUP_PANEL_MIN_BRIGHT_RATIO = 0.65

    def _preset_group_panel_layout_visible(self) -> bool:
        """Cheaply reject pages without the preset screen's light group cards."""
        image = getattr(getattr(self, 'device', None), 'image', None)
        if image is None or image.ndim != 3:
            return False
        x1, y1, x2, y2 = self.PRESET_GROUP_PANEL_ROI
        panel = image[y1:y2, x1:x2]
        if panel.shape[:2] != (y2 - y1, x2 - x1):
            return False
        bright_ratio = float(
            (panel.mean(axis=2) > self.PRESET_GROUP_PANEL_BRIGHT_THRESHOLD).mean()
        )
        return bright_ratio >= self.PRESET_GROUP_PANEL_MIN_BRIGHT_RATIO

    def _is_current_preset_page(self) -> bool:
        """Recognize the current preset page without relying on one stale template."""
        # RealmRaid and the courtyard also put vertically spaced text in the
        # group/team OCR ROIs. Only the preset page has a continuous stack of
        # light group cards, so reject other layouts before paying for OCR.
        if not self._preset_group_panel_layout_visible():
            return False

        try:
            lines = self._preset_ocr_lines(SwitchSoulAssets.O_SS_GROUP_NAME)
            team_lines = self._preset_ocr_lines(SwitchSoulAssets.O_SS_TEAM_NAME)
        except Exception as error:
            logger.warning(f'Preset page OCR fallback failed: {error}')
            return False

        names = self._preset_page_names(lines)
        if len(names) < 3:
            return False

        centers = sorted(line.center_y for line in lines if normalize_preset_name(line.text))
        plausible_gaps = sum(45 <= current - previous <= 90 for previous, current in zip(centers, centers[1:]))
        if plausible_gaps < 2:
            return False

        # The courtyard's right-side menu occupies the same ROI and can look like
        # a group list. A real preset page must also have a named middle-list team.
        team_names = self._preset_page_names(team_lines)
        if not team_names:
            return False

        logger.info(
            'Preset page recognized by group/team OCR structure: '
            f'groups={names[:3]}, teams={team_names[:2]}'
        )
        return True

    def _preset_swipe_to_top(
        self,
        ocr_rule: RuleOcr,
        swipe_rule,
        kind: str,
        max_swipes: int = 8,
    ) -> None:
        previous = None
        unchanged = 0
        for _ in range(max_swipes):
            self.screenshot()
            page = self._preset_page_names(self._preset_ocr_lines(ocr_rule))
            if not page:
                raise PresetLookupError(f'无法识别{kind}列表，已停止预设切换')
            if page == previous:
                unchanged += 1
                if unchanged >= 2:
                    return
            else:
                unchanged = 0
            previous = page
            self.swipe(swipe_rule)
            sleep(0.8)
        raise PresetLookupError(f'{kind}列表无法回到顶部，已停止预设切换')

    def _scan_preset_names(
        self,
        ocr_rule: RuleOcr,
        to_top_swipe,
        forward_swipe,
        kind: str,
        max_swipes: int = 30,
    ) -> list[str]:
        self._preset_swipe_to_top(ocr_rule, to_top_swipe, kind)
        merged: list[str] = []
        unchanged = 0
        for _ in range(max_swipes + 1):
            self.screenshot()
            page = self._preset_page_names(self._preset_ocr_lines(ocr_rule))
            if not page:
                raise PresetLookupError(f'无法识别{kind}列表，已停止预设切换')
            updated = merge_ordered_pages(merged, page)
            if updated == merged:
                unchanged += 1
                if unchanged >= 2:
                    return merged
            else:
                unchanged = 0
                merged = updated
            self.swipe(forward_swipe)
            sleep(0.8)
        raise PresetLookupError(f'{kind}列表超过扫描上限或无法判断底部，已停止预设切换')

    def _find_preset_line(
        self,
        ocr_rule: RuleOcr,
        to_top_swipe,
        forward_swipe,
        target: str,
        kind: str,
        max_swipes: int = 30,
    ):
        self._preset_swipe_to_top(ocr_rule, to_top_swipe, kind)
        normalized_target = normalize_preset_name(target)
        previous = None
        unchanged = 0
        for _ in range(max_swipes + 1):
            self.screenshot()
            lines = self._preset_ocr_lines(ocr_rule)
            matches = [line for line in lines if normalize_preset_name(line.text) == normalized_target]
            if len(matches) > 1:
                raise PresetLookupError(
                    f'当前画面识别到多个同名{kind}“{target}”，请先在游戏内重命名'
                )
            if matches:
                return matches[0]

            page = self._preset_page_names(lines)
            if page == previous:
                unchanged += 1
                if unchanged >= 2:
                    break
            else:
                unchanged = 0
            previous = page
            self.swipe(forward_swipe)
            sleep(0.8)
        raise PresetLookupError(f'无法重新定位{kind}“{target}”，已停止预设切换')

    def _visible_preset_line(self, ocr_rule: RuleOcr, target: str, kind: str):
        """Return one exact visible row; reject an immediately visible duplicate."""
        self.screenshot()
        normalized_target = normalize_preset_name(target)
        matches = [
            line
            for line in self._preset_ocr_lines(ocr_rule)
            if normalize_preset_name(line.text) == normalized_target
        ]
        if len(matches) > 1:
            raise PresetLookupError(
                f'当前画面识别到多个同名{kind}“{target}”，请先在游戏内重命名'
            )
        return matches[0] if matches else None

    def _switch_recently_validated_preset(self, group_name: str, team_name: str) -> bool:
        """Fast path after a recent full duplicate scan for this account and name pair."""
        logger.info(
            'Reuse recently validated preset names: '
            f'group={group_name}, team={team_name}'
        )
        group_ocr = SwitchSoulAssets.O_SS_GROUP_NAME
        group_line = self._visible_preset_line(group_ocr, group_name, '预设分组')
        if group_line is None:
            group_line = self._find_preset_line(
                group_ocr,
                SwitchSoulAssets.S_SS_GROUP_SWIPE_UP,
                SwitchSoulAssets.S_SS_GROUP_SWIPE_DOWN,
                group_name,
                '预设分组',
            )
        self.device.click(
            group_ocr.roi[0] + group_line.center_x,
            group_ocr.roi[1] + group_line.center_y,
            control_name=f'PRESET_GROUP:{group_name}',
        )
        sleep(1)

        team_ocr = SwitchSoulAssets.O_SS_TEAM_NAME
        team_line = self._visible_preset_line(team_ocr, team_name, '预设队伍')
        if team_line is None:
            team_line = self._find_preset_line(
                team_ocr,
                SwitchSoulAssets.S_SS_TEAM_SWIPE_DOWN,
                SwitchSoulAssets.S_SS_TEAM_SWIPE_UP,
                team_name,
                '预设队伍',
            )
        self._apply_current_preset_team(team_line, team_name)
        self._exit_current_preset_page()
        logger.info(
            'Recent preset validation fast path completed: '
            f'group={group_name}, team={team_name}'
        )
        return True

    def _open_current_preset_page(self, timeout: float = 12) -> None:
        deadline = time.time() + timeout
        stable_frames = 0
        while time.time() < deadline:
            self.screenshot()
            if self._is_current_preset_page():
                stable_frames += 1
                if stable_frames >= 2:
                    return
                sleep(0.25)
                continue
            stable_frames = 0
            if self.appear(self.I_PRESENT_LESS_THAN_5):
                raise PresetLookupError('当前队伍不足五个式神，无法打开队伍预设')
            if self.appear_then_click(self.I_PRESET, threshold=0.8, interval=1):
                continue
            if self.appear_then_click(self.I_PRESET_WIT_NUMBER, threshold=0.8, interval=1):
                continue
            if self.ocr_appear(self.O_PRESET):
                self.click(self.O_PRESET, interval=1)
                continue
            if self.ocr_appear(self.O_PRESET_FULL):
                self.click(self.O_PRESET_FULL, interval=1)
                continue
            sleep(0.3)
        raise PresetLookupError('未能从战斗准备界面打开当前版本的队伍预设')

    def _open_records_preset_page(self, timeout: float = 12) -> None:
        """Open the current team-preset page from Shikigami Records.

        The battle preparation button named "preset" now opens an unrelated
        auto/manual combat panel. Current named team presets must therefore be
        applied before a challenge starts, from Shikigami Records.
        """
        deadline = time.time() + timeout
        stable_frames = 0
        while time.time() < deadline:
            self.screenshot()
            if self._is_current_preset_page():
                stable_frames += 1
                if stable_frames >= 2:
                    return
                sleep(0.25)
                continue
            stable_frames = 0
            if self.appear_then_click(
                SwitchSoulAssets.I_SOUL_PRESET,
                threshold=0.8,
                interval=1,
            ):
                continue
            sleep(0.3)
        raise PresetLookupError('未能从式神录打开当前版本的队伍预设')

    def preapply_preset_team_from_records(
        self,
        group_name: str,
        team_name: str,
        page_already_open: bool = False,
    ) -> bool:
        group_name = str(group_name or '').strip()
        team_name = str(team_name or '').strip()
        if not group_name or not team_name:
            raise InvalidPresetConfigError(
                '预设队伍配置不完整：分组名称和队伍名称必须同时填写'
            )
        try:
            logger.info(
                'Pre-apply preset from Shikigami Records: '
                f'group={group_name}, team={team_name}'
            )
            if not page_already_open:
                self._open_records_preset_page()
            self._switch_preset_team_by_name(
                group_name,
                team_name,
                page_already_open=True,
            )
        except PresetLookupError as error:
            logger.error(f'Preset pre-apply stopped: {error}')
            raise
        self._battle_preset_preapplied = True
        return True

    def _preset_status_text(self) -> str:
        results = O_PRESET_STATUS.detect_and_ocr(self.device.image, logDisplay=False)
        return ''.join(str(result.ocr_text or '') for result in results)

    def _preset_confirm_visible(self) -> bool:
        return self.appear(SwitchSoulAssets.I_SOU_SWITCH_SURE) or self.ocr_appear(O_PRESET_CONFIRM)

    def _click_current_preset_confirm(self) -> bool:
        if self.appear(SwitchSoulAssets.I_SOU_SWITCH_SURE):
            self.click(SwitchSoulAssets.I_SOU_SWITCH_SURE)
            return True
        if self.ocr_appear(O_PRESET_CONFIRM):
            self.click(O_PRESET_CONFIRM)
            return True
        return False

    def _apply_current_preset_team(
        self,
        team_line,
        team_name: str,
        action_rule=None,
    ) -> None:
        team_roi = SwitchSoulAssets.O_SS_TEAM_NAME.roi
        select_rule = action_rule or SwitchSoulAssets.C_SOU_TEAM_SELECT
        select_roi = select_rule.roi_front
        x = int(select_roi[0] + select_roi[2] / 2)
        y = int(team_roi[1] + team_line.center_y)
        self.device.click(x, y, control_name=f'PRESET_TEAM_APPLY:{team_name}')

        deadline = time.time() + 6
        while time.time() < deadline:
            sleep(0.35)
            self.screenshot()
            if self._click_current_preset_confirm():
                break
            status = self._preset_status_text()
            if '正在使用预设' in status:
                logger.info(f'Preset team {team_name} is already active')
                return
        else:
            raise PresetApplyUnconfirmedError(
                f'点击队伍“{team_name}”后未出现确认弹窗或已使用提示'
            )

        disappeared_since = None
        deadline = time.time() + 7
        while time.time() < deadline:
            sleep(0.35)
            self.screenshot()
            status = self._preset_status_text()
            if '成功' in status or '正在使用预设' in status:
                logger.info(f'Preset team {team_name} applied: {status}')
                return
            if not self._preset_confirm_visible():
                if disappeared_since is None:
                    disappeared_since = time.time()
                elif time.time() - disappeared_since >= 1.5:
                    logger.warning(
                        'Preset confirmation disappeared but success toast was not captured; '
                        'accept the confirmed transition as fallback evidence'
                    )
                    return
            else:
                disappeared_since = None
        raise PresetApplyUnconfirmedError(f'队伍“{team_name}”确认后没有完成切换')

    def _apply_current_preset_soul(self, team_line, team_name: str) -> None:
        """Apply the soul preset icon on the same row as the named team."""
        self._apply_current_preset_team(
            team_line,
            team_name,
            action_rule=SwitchSoulAssets.I_SOU_CLICK_PRESENT,
        )

    def _exit_current_preset_page(self, timeout: float = 8) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.screenshot()
            if not self._is_current_preset_page():
                return
            if self.appear_then_click(SwitchSoulAssets.I_RECORD_SOUL_BACK, interval=1):
                sleep(0.6)
                continue
            sleep(0.3)
        raise PresetLookupError('预设切换完成，但未能退出队伍预设页面')

    def _switch_preset_team_by_name(
        self,
        group_name: str,
        team_name: str,
        page_already_open: bool = False,
    ):
        logger.info(f'Switch preset by name: group={group_name}, team={team_name}')
        if not page_already_open:
            self._open_current_preset_page()

        account = str(getattr(getattr(self, 'config', None), 'config_name', '') or '')
        if preset_validation_is_recent(account, group_name, team_name):
            try:
                return self._switch_recently_validated_preset(group_name, team_name)
            except PresetLookupError:
                forget_preset_validation(account, group_name, team_name)
                raise

        group_ocr = SwitchSoulAssets.O_SS_GROUP_NAME
        group_names = self._scan_preset_names(
            group_ocr,
            SwitchSoulAssets.S_SS_GROUP_SWIPE_UP,
            SwitchSoulAssets.S_SS_GROUP_SWIPE_DOWN,
            '预设分组',
        )
        require_unique_name(group_names, group_name, '预设分组')
        group_line = self._find_preset_line(
            group_ocr,
            SwitchSoulAssets.S_SS_GROUP_SWIPE_UP,
            SwitchSoulAssets.S_SS_GROUP_SWIPE_DOWN,
            group_name,
            '预设分组',
        )
        self.device.click(
            group_ocr.roi[0] + group_line.center_x,
            group_ocr.roi[1] + group_line.center_y,
            control_name=f'PRESET_GROUP:{group_name}',
        )
        sleep(1)

        team_ocr = SwitchSoulAssets.O_SS_TEAM_NAME
        team_names = self._scan_preset_names(
            team_ocr,
            SwitchSoulAssets.S_SS_TEAM_SWIPE_DOWN,
            SwitchSoulAssets.S_SS_TEAM_SWIPE_UP,
            '预设队伍',
        )
        require_unique_name(team_names, team_name, '预设队伍')
        team_line = self._find_preset_line(
            team_ocr,
            SwitchSoulAssets.S_SS_TEAM_SWIPE_DOWN,
            SwitchSoulAssets.S_SS_TEAM_SWIPE_UP,
            team_name,
            '预设队伍',
        )
        self._apply_current_preset_team(team_line, team_name)
        self._exit_current_preset_page()
        remember_preset_validation(account, group_name, team_name)
        logger.info(f'Switch preset by name completed: group={group_name}, team={team_name}')
        return True

    def _switch_preset_soul_by_name(
        self,
        group_name: str,
        team_name: str,
        page_already_open: bool = False,
    ):
        """Apply a named soul preset through the current card layout."""
        logger.info(f'Switch soul preset by name: group={group_name}, team={team_name}')
        if not page_already_open:
            # Named soul presets are selected from Shikigami Records. The
            # battle-preparation shortcut is a different control in the
            # current client and can open the auto/manual panel instead.
            self._open_records_preset_page()

        group_ocr = SwitchSoulAssets.O_SS_GROUP_NAME
        group_names = self._scan_preset_names(
            group_ocr,
            SwitchSoulAssets.S_SS_GROUP_SWIPE_UP,
            SwitchSoulAssets.S_SS_GROUP_SWIPE_DOWN,
            '预设分组',
        )
        require_unique_name(group_names, group_name, '预设分组')
        group_line = self._find_preset_line(
            group_ocr,
            SwitchSoulAssets.S_SS_GROUP_SWIPE_UP,
            SwitchSoulAssets.S_SS_GROUP_SWIPE_DOWN,
            group_name,
            '预设分组',
        )
        self.device.click(
            group_ocr.roi[0] + group_line.center_x,
            group_ocr.roi[1] + group_line.center_y,
            control_name=f'SOUL_PRESET_GROUP:{group_name}',
        )
        sleep(1)

        team_ocr = SwitchSoulAssets.O_SS_TEAM_NAME
        team_names = self._scan_preset_names(
            team_ocr,
            SwitchSoulAssets.S_SS_TEAM_SWIPE_DOWN,
            SwitchSoulAssets.S_SS_TEAM_SWIPE_UP,
            '预设队伍',
        )
        require_unique_name(team_names, team_name, '预设队伍')
        team_line = self._find_preset_line(
            team_ocr,
            SwitchSoulAssets.S_SS_TEAM_SWIPE_DOWN,
            SwitchSoulAssets.S_SS_TEAM_SWIPE_UP,
            team_name,
            '预设队伍',
        )
        self._apply_current_preset_soul(team_line, team_name)
        self._exit_current_preset_page()
        logger.info(
            f'SOUL_PRESET_RESULT result=applied_by_name group={group_name}, team={team_name}'
        )
        return True

    def _switch_preset_team_legacy(self, preset_group: int = 1, preset_team: int = 1):
        """
        切换预设的队伍， 要求是在不锁定队伍时的情况下
        :param preset_group:
        :param preset_team:
        :return:
        """
        logger.info("Preset is enable (legacy fixed index mode)")
        # 点击预设按钮
        while 1:
            self.screenshot()

            if self.appear(self.I_PRESET_ENSURE):
                break
            # 首个队伍没有满足5个式神，未出现预设按钮的情况下跳出循环
            if self.appear(self.I_PRESENT_LESS_THAN_5):
                break
            if self.appear_then_click(self.I_PRESET, threshold=0.8, interval=1):
                continue
            if self.appear_then_click(self.I_PRESET_WIT_NUMBER, threshold=0.8, interval=1):
                continue
            if self.ocr_appear(self.O_PRESET):
                self.click(self.O_PRESET, interval=1)
                continue
            if self.ocr_appear(self.O_PRESET_FULL):
                self.click(self.O_PRESET_FULL, interval=1)
                continue
        logger.info("Click preset button")

        def get_unselect_color(tmp1, tmp2, tmp3, size):
            # 获取未选择分组的颜色，3组之中必定存在两个颜色相似
            # area 参数格式是（x1,y1,x2,y2）
            color_1 = get_color(self.device.image,
                                (tmp1.roi_back[0], tmp1.roi_back[1],
                                 tmp1.roi_back[0] + size[0], tmp1.roi_back[1] + size[1]))
            color_2 = get_color(self.device.image,
                                (tmp2.roi_back[0], tmp2.roi_back[1],
                                 tmp2.roi_back[0] + size[0], tmp2.roi_back[1] + size[1]))
            color_3 = get_color(self.device.image,
                                (tmp3.roi_back[0], tmp3.roi_back[1],
                                 tmp3.roi_back[0] + size[0], tmp3.roi_back[1] + size[1]))

            if color_similar(color_1, color_2):
                return color_1
            if color_similar(color_2, color_3):
                return color_2
            return color_3

        # 选择预设组
        tmp = self.__getattribute__("C_PRESET_GROUP_" + str(preset_group))
        if tmp is None:
            tmp = self.C_PRESET_GROUP_1
        color_size = [self.C_PRESET_GROUP_1.roi_back[2],
                      self.C_PRESET_GROUP_1.roi_back[3]]
        # unselected_color = get_unselect_color(self.C_PRESET_GROUP_1, self.C_PRESET_GROUP_2, self.C_PRESET_GROUP_3, size=color_size)
        # 考虑到有些预设组没有预设，所以这里取一个比较固定的颜色
        unselected_color = (224.9, 208.3, 187.4)
        while True:
            self.screenshot()
            color_tmp = get_color(self.device.image,
                                  (tmp.roi_back[0], tmp.roi_back[1], tmp.roi_back[0] + color_size[0],
                                   tmp.roi_back[1] + color_size[1]))
            if color_similar(color_tmp, unselected_color):
                self.click(tmp, interval=0.2)
                continue
            break

        logger.info("Select preset group")

        # 选择预设的队伍
        time.sleep(0.5)
        tmp = self.__getattribute__("C_PRESET_TEAM_" + str(preset_team))
        if tmp is None:
            tmp = self.C_PRESET_TEAM_1
        color_size = [5, 5]
        # unselected_color = get_unselect_color(self.C_PRESET_TEAM_1, self.C_PRESET_TEAM_2, self.C_PRESET_TEAM_3, size=color_size )
        unselected_color = (216.8, 185.0, 146.8)
        while True:
            self.screenshot()
            color_tmp = get_color(self.device.image,
                                  (tmp.roi_back[0], tmp.roi_back[1], tmp.roi_back[0] + color_size[0],
                                   tmp.roi_back[1] + color_size[1]))
            if color_similar(color_tmp, unselected_color):
                self.click(tmp, interval=0.2)
                continue
            break

        self.click(tmp)
        logger.info("Select preset team")

        # 点击预设确认
        self.wait_until_appear(self.I_PRESET_ENSURE, wait_time=1)
        click_timer = Timer(10).start()
        while 1:
            self.screenshot()
            if click_timer.reached():
                logger.warning("Switch preset failure")
            if not self.appear(self.I_PRESET_ENSURE):
                break
            if self.appear_then_click(self.I_PRESET_ENSURE, threshold=0.8, interval=1):
                continue
        logger.info("Click preset ensure")
        return None

    def _legacy_random_click_swipt(self):
        if 0 <= random.randint(0, 500) <= 3:  # 百分之4的概率
            rand_type = random.randint(0, 2)
            match rand_type:
                case 0:
                    self.click(self.C_RANDOM_CLICK, interval=20)
                case 1:
                    self.swipe(self.S_BATTLE_RANDOM_LEFT, interval=20)
                case 2:
                    self.swipe(self.S_BATTLE_RANDOM_RIGHT, interval=20)
            # 重新设置为长战斗
            # self.device.stuck_record_add('BATTLE_STATUS_S')
        else:
            time.sleep(0.4)  # 这样的好像不对

    # 判断是否在战斗中
    def random_click_swipt_nonblocking(self):
        """Schedule an occasional anti-detection gesture without blocking OCR."""
        if self._battle_terminal_visible():
            return False

        now = time.monotonic()
        last = getattr(self, '_random_click_swipt_at', None)
        if last is not None and now - last < 0.7:
            return False
        self._random_click_swipt_at = now

        if random.randint(0, 500) > 3:
            return False

        rand_type = random.randint(0, 2)
        match rand_type:
            case 0:
                self.click(self.C_RANDOM_CLICK, interval=20)
            case 1:
                self.swipe(self.S_BATTLE_RANDOM_LEFT, interval=20)
            case 2:
                self.swipe(self.S_BATTLE_RANDOM_RIGHT, interval=20)
        logger.debug(f'ANTI_DETECT_ACTION type={rand_type}')
        return True

    def random_click_swipt(self):
        """Compatibility entry point for tasks using the shared helper."""
        return GeneralBattle.random_click_swipt_nonblocking(self)

    def is_in_battle(self, is_screenshot: bool = True) -> bool:
        """
        判断是否在战斗中
        tip: 因为有friends判别, 所以即使在准备界面也会识别在战斗中
        :return:
        """
        if is_screenshot:
            self.screenshot()
        if self.appear(self.I_BATTLE_INFO) or \
                self.appear(self.I_FRIENDS) or \
                self.appear(self.I_WIN) or \
                self.appear(self.I_FALSE) or \
                self.appear(self.I_REWARD) or \
                self._battle_result_continue_visible():
            return True
        else:
            return False

    def is_in_real_battle(self, is_screenshot: bool = True):
        """
        判断是否在真正的战斗中(不是战斗准备界面也不是战斗结束界面)
        :param is_screenshot:
        :return:
        """
        if is_screenshot:
            self.screenshot()
        # The upstream battle-info icon is theme-sensitive and no longer matches
        # reliably on the current client. The friends icon is stable, but it is
        # also present on the preparation page, so explicitly exclude preparation
        # and result states before using it as the fallback signal.
        if self._prepare_button_visible():
            return False
        if (self.appear(self.I_WIN) or self.appear(self.I_FALSE) or
                self.appear(self.I_REWARD) or
                self._battle_result_continue_visible()):
            return False
        return self.appear(self.I_BATTLE_INFO) or self.appear(self.I_FRIENDS)

    def is_in_prepare(self, is_screenshot: bool = True) -> bool:
        """
        判断是否在准备中
        :return:
        """
        if is_screenshot:
            self.screenshot()
        if self.appear(self.I_BUFF):
            return True
        elif self.appear(self.I_PREPARE_HIGHLIGHT):
            return True
        elif self.appear(self.I_PREPARE_DARK):
            return True
        elif self.appear(self.I_PRESET) or self.appear(self.I_PRESET_WIT_NUMBER):
            return True
        elif self._prepare_button_visible():
            return True
        else:
            return False

    def _extra_prepare_button_visible(self) -> bool:
        """Optional task-specific prepare control hook."""
        return False

    def _click_extra_prepare_button(self, interval: float = None) -> bool:
        """Optional task-specific prepare control click hook."""
        return False

    def _prepare_button_visible(self) -> bool:
        """Recognize the current prepare button, including the text fallback."""
        return (
            self.appear(self.I_PREPARE_HIGHLIGHT)
            or self.appear(self.I_PREPARE_DARK)
            or self.ocr_appear(self.O_BATTLE_PREPARE)
            or self.ocr_appear(O_BATTLE_PREPARE_WIDE)
            or self._new_prepare_button_visible(
                getattr(getattr(self, 'device', None), 'image', None)
            )
            or self._extra_prepare_button_visible()
        )

    @staticmethod
    def _new_prepare_button_visible(image) -> bool:
        """Detect the current blue prepare control when legacy assets miss it."""
        if image is None or getattr(image, 'ndim', 0) != 3:
            return False
        try:
            height, width = image.shape[:2]
            if width < 1100 or height < 620:
                return False
            # The old broad bottom-right ROI also contains the preparation
            # page background. On the current client that background lowers
            # the color ratio enough to miss the actual blue button. Keep the
            # detector aligned with the 1280x720 asset coordinate system and
            # inspect the button ROI itself.
            base_width, base_height = 1280.0, 720.0
            x = int(round(width * 1128 / base_width))
            y = int(round(height * 536 / base_height))
            roi_width = max(1, int(round(width * 100 / base_width)))
            roi_height = max(1, int(round(height * 100 / base_height)))
            crop = image[y:min(height, y + roi_height), x:min(width, x + roi_width)]
            if crop.size == 0:
                return False
            pixels = crop.astype('float32')
            brightness = pixels.mean(axis=2)
            saturation = pixels.max(axis=2) - pixels.min(axis=2)
            bright_colored = (brightness >= 100.0) & (saturation >= 65.0)
            return (
                float(bright_colored.mean()) >= 0.45
                and float(brightness.mean()) >= 105.0
            )
        except Exception as error:  # noqa: BLE001
            logger.debug(f'Blue prepare visual guard unavailable: {error}')
            return False

    def _click_prepare_button(self, interval: float = None) -> bool:
        """Click the current prepare control after confirming it is visible.

        Newer clients render a blue/tinted button that misses both the legacy
        image template and the narrow OCR ROI.  Keep those fast paths first,
        then use the wide OCR rule and finally the visual guard's known button
        ROI.  The visual fallback is gated by the same detection used by
        ``_prepare_button_visible`` so it never becomes a blind screen click.
        """
        if self.appear(self.I_PREPARE_HIGHLIGHT, interval=interval):
            if self._click_prepare_safe():
                return True
            return self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=interval)
        if self.appear(self.I_PREPARE_DARK, interval=interval):
            if self._click_prepare_safe():
                return True
            return self.appear_then_click(self.I_PREPARE_DARK, interval=interval)
        if self.ocr_appear(self.O_BATTLE_PREPARE, interval=interval):
            if self._click_prepare_safe():
                return True
            return self.ocr_appear_click(self.O_BATTLE_PREPARE, interval=interval)
        if self.ocr_appear(O_BATTLE_PREPARE_WIDE, interval=interval):
            if self._click_prepare_safe():
                return True
            return self.ocr_appear_click(O_BATTLE_PREPARE_WIDE, interval=interval)
        if self._new_prepare_button_visible(
            getattr(getattr(self, 'device', None), 'image', None)
        ):
            return self._click_prepare_safe(control_name='GB_PREPARE_WIDE_VISUAL')
        return self._click_extra_prepare_button(interval=interval)

    def _click_prepare_safe(self, control_name: str = None) -> bool:
        """Click inside the stable center of the current prepare control."""
        device = getattr(self, 'device', None)
        if device is None:
            return False
        x, y = C_PREPARE_SAFE.coord()
        device.click(
            x,
            y,
            control_name=control_name or C_PREPARE_SAFE.name,
        )
        logger.info(
            f'Prepare safe click at ({x},{y}) '
            f'control={control_name or C_PREPARE_SAFE.name}'
        )
        return True

    def check_take_over_battle(self, is_screenshot: bool, config: GeneralBattleConfig) -> bool or None:
        """
        中途接入战斗，并且接管
        :return:  赢了返回True， 输了返回False, 不是在战斗中返回None
        """
        if is_screenshot:
            self.screenshot()
        if not self.is_in_battle():
            return None

        return self.run_general_battle(config=config)

    def check_lock(self, enable: bool, lock_image, unlock_image):
        """
        检测是否锁定队伍，
        :param enable:
        :param lock_image:
        :param unlock_image:
        :return:
        """
        if enable:
            logger.info("Lock team")
            while 1:
                self.screenshot()
                if self.appear(lock_image):
                    break
                if self.appear_then_click(unlock_image, interval=1):
                    continue
        else:
            logger.info("Unlock team")
            while 1:
                self.screenshot()
                if self.appear(unlock_image):
                    break
                if self.appear_then_click(lock_image, interval=1):
                    continue

    def check_and_open_buff(self, buff: BuffClass or list[BuffClass] = None):
        """
        检测是否开启buff
        :param buff:
        :return:
        """
        if not buff:
            return True
        logger.info(f'Open buff {buff}')
        if not self.ui_click(self.I_BUFF, self.I_CLOUD, interval=2, timeout=10):
            logger.warning('Buff panel did not open within 10s')
            return False
        if isinstance(buff, BuffClass):
            buff = [buff]
        match_method = {
            BuffClass.AWAKE: (self.awake, True),
            BuffClass.SOUL: (self.soul, True),
            BuffClass.GOLD_50: (self.gold_50, True),
            BuffClass.GOLD_100: (self.gold_100, True),
            BuffClass.EXP_50: (self.exp_50, True),
            BuffClass.EXP_100: (self.exp_100, True),
            BuffClass.AWAKE_CLOSE: (self.awake, False),
            BuffClass.SOUL_CLOSE: (self.soul, False),
            BuffClass.GOLD_50_CLOSE: (self.gold_50, False),
            BuffClass.GOLD_100_CLOSE: (self.gold_100, False),
            BuffClass.EXP_50_CLOSE: (self.exp_50, False),
            BuffClass.EXP_100_CLOSE: (self.exp_100, False),
        }
        all_confirmed = True
        for b in buff:
            func, is_open = match_method[b]
            if func(is_open) is False:
                all_confirmed = False
            time.sleep(0.1)
        close_deadline = time.monotonic() + 10
        while time.monotonic() < close_deadline:
            self.screenshot()
            if not self.appear(self.I_CLOUD):
                break
            if self.appear_then_click(self.I_BUFF, interval=1):
                continue
        else:
            logger.warning('Buff panel did not close within 10s')
            all_confirmed = False
        if all_confirmed:
            logger.info('Open buff success')
        else:
            logger.warning('Open buff completed with unconfirmed state')
        return all_confirmed

    def boss_mark(self, enable=True) -> bool:
        if not enable or self._boss_mark_flag:
            return False
        if self.ocr_appear(self.O_BOSS_MARK):
            self.screenshot()
            if self.ocr_appear(self.O_BOSS_MARK):
                self._boss_mark_flag = True
                logger.info('Boss marked')
                self.device.stuck_record_add('BATTLE_STATUS_S')
                return True
        if self.device.click_record.count(str(self.O_BOSS_MARK)) >= 3:
            self._boss_mark_flag = True
            logger.info('Boss mark skipped due to maybe no boss')
            self.device.stuck_record_add('BATTLE_STATUS_S')
            return False
        if self.click(self.O_BOSS_MARK, interval=1.8):
            return False
        return False

    def boss_mark_reset(self):
        self._boss_mark_flag = False


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = GeneralBattle(c, d)
    self = t
    # t.check_buff([BuffClass.EXP_50, BuffClass.GOLD_50])

    img = cv2.imread(r"E:\preset3.png")
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    self.device.image = img


    def get_unselect_color(tmp1, tmp2, tmp3, size):
        # 获取未选择分组的颜色，3组之中必定存在两个颜色相似
        # area 参数格式是（x1,y1,x2,y2）
        color_1 = get_color(self.device.image,
                            (tmp1.roi_back[0], tmp1.roi_back[1],
                             tmp1.roi_back[0] + size[0], tmp1.roi_back[1] + size[1]))
        color_2 = get_color(self.device.image,
                            (tmp2.roi_back[0], tmp2.roi_back[1],
                             tmp2.roi_back[0] + size[0], tmp2.roi_back[1] + size[1]))
        color_3 = get_color(self.device.image,
                            (tmp3.roi_back[0], tmp3.roi_back[1],
                             tmp3.roi_back[0] + size[0], tmp3.roi_back[1] + size[1]))

        if color_similar(color_1, color_2):
            return color_1
        if color_similar(color_2, color_3):
            return color_2
        return color_3


    color_size = [self.C_PRESET_GROUP_1.roi_back[2],
                  self.C_PRESET_GROUP_1.roi_back[3]]
    unselected_color = get_unselect_color(self.C_PRESET_GROUP_1, self.C_PRESET_GROUP_2, self.C_PRESET_GROUP_3,
                                          size=color_size)
    print("")
    color_size = [5, 5]
    unselected_color = get_unselect_color(self.C_PRESET_TEAM_1, self.C_PRESET_TEAM_2, self.C_PRESET_TEAM_3,
                                          size=color_size
                                          )
    print("")
