# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
import hashlib
from datetime import datetime, timedelta, time as dt_time
from enum import Enum
import random

from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.RyouToppa.assets import RyouToppaAssets
from tasks.RyouToppa.guild_selector import (
    GuildCandidate,
    GuildSortOrder,
    GuildSortSnapshot,
    classify_guild_sort_order,
    compare_guild_sort_snapshots,
    compare_guild_observations,
    verify_final_descending_snapshot,
)
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.config_base import ConfigBase, Time
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_realm_raid, page_main, page_kekkai_toppa, page_shikigami_records
from tasks.RealmRaid.assets import RealmRaidAssets

from module.logger import logger
from module.exception import TaskEnd
from module.atom.image_grid import ImageGrid
from module.atom.ocr import RuleOcr
from module.base.utils import point2str
from module.base.timer import Timer
from module.exception import GamePageUnknownError



area_map = (
    {
        "fail_sign": (RyouToppaAssets.I_AREA_1_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_1_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_1,
        "finished_sign": (RyouToppaAssets.I_AREA_1_FINISHED, RyouToppaAssets.I_AREA_1_FINISHED_NEW)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_2_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_2_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_2,
        "finished_sign": (RyouToppaAssets.I_AREA_2_FINISHED, RyouToppaAssets.I_AREA_2_FINISHED_NEW)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_3_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_3_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_3,
        "finished_sign": (RyouToppaAssets.I_AREA_3_FINISHED, RyouToppaAssets.I_AREA_3_FINISHED_NEW)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_4_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_4_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_4,
        "finished_sign": (RyouToppaAssets.I_AREA_4_FINISHED, RyouToppaAssets.I_AREA_4_FINISHED_NEW)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_5_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_5_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_5,
        "finished_sign": (RyouToppaAssets.I_AREA_5_FINISHED, RyouToppaAssets.I_AREA_5_FINISHED_NEW)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_6_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_6_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_6,
        "finished_sign": (RyouToppaAssets.I_AREA_6_FINISHED, RyouToppaAssets.I_AREA_6_FINISHED_NEW)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_7_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_7_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_7,
        "finished_sign": (RyouToppaAssets.I_AREA_7_FINISHED, RyouToppaAssets.I_AREA_7_FINISHED_NEW)
    },
    {
        "fail_sign": (RyouToppaAssets.I_AREA_8_IS_FAILURE_NEW, RyouToppaAssets.I_AREA_8_IS_FAILURE),
        "rule_click": RyouToppaAssets.C_AREA_8,
        "finished_sign": (RyouToppaAssets.I_AREA_8_FINISHED, RyouToppaAssets.I_AREA_8_FINISHED_NEW)
    }
)


class AreaStatus(str, Enum):
    AVAILABLE = "available"
    FINISHED = "finished"
    FAILED = "failed"


class TicketStatus(str, Enum):
    AVAILABLE = "available"
    EMPTY = "empty"
    UNKNOWN = "unknown"


class AttackResult(str, Enum):
    SUCCESS = "success"
    AREA_FINISHED = "area_finished"
    AREA_FAILED = "area_failed"
    CLICK_TIMEOUT = "click_timeout"
    BATTLE_FAILED = "battle_failed"
    PAGE_TIMEOUT = "page_timeout"


class BattleEntryMode(str, Enum):
    PREPARE_REQUIRED = "prepare_required"
    DIRECT_BATTLE = "direct_battle"


class TeamLockValidationState(str, Enum):
    DISABLED = "disabled"
    OBSERVING = "observing"
    CLICK_AFTER_RETURN = "click_after_return"
    VERIFY_NEXT_BATTLE = "verify_next_battle"
    VERIFIED = "verified"
    VERIFIED_PREPARE_REQUIRED = "verified_prepare_required"
    FAILED = "failed"


RYOU_ENTRY_TIMEOUT_SECONDS = 30
RYOU_GUILD_SELECT_TIMEOUT_SECONDS = 30
RYOU_BOARD_IDLE_TIMEOUT_SECONDS = 20
RYOU_BATTLE_ENTRY_TIMEOUT_SECONDS = 20
RYOU_BOARD_RETURN_TIMEOUT_SECONDS = 25
RYOU_PREPARE_STABLE_FRAMES = 2
RYOU_LOCK_STATE_TIMEOUT_SECONDS = 3


GUILD_CANDIDATE_OCR_RULES = tuple(
    (
        f"row_{index}",
        (1070, 96 + (index - 1) * 144, 180, 138),
        RuleOcr(
            roi=(1144, 170 + (index - 1) * 144, 68, 42),
            area=(1144, 170 + (index - 1) * 144, 68, 42),
            mode="Digit",
            method="Default",
            keyword="",
            name=f"ryou_guild_medal_{index}",
        ),
    )
    for index in range(1, 5)
)


def random_delay(min_value: float = 1.0, max_value: float = 2.0, decimal: int = 1):
    """
    生成一个指定范围内的随机小数
    """
    random_float_in_range = random.uniform(min_value, max_value)
    return (round(random_float_in_range, decimal))

class ScriptTask(GeneralBattle, GameUi, SwitchSoul, RyouToppaAssets):
    medal_grid: ImageGrid = None
    GUILD_CANDIDATE_OCR_RULES = GUILD_CANDIDATE_OCR_RULES

    def _legacy_run(self):
        """
        执行
        :return:
        """
        ryou_config = self.config.ryou_toppa
        time_limit: Time = ryou_config.raid_config.limit_time
        time_delta = timedelta(hours=time_limit.hour, minutes=time_limit.minute, seconds=time_limit.second)
        self.medal_grid = ImageGrid([RealmRaidAssets.I_MEDAL_5, RealmRaidAssets.I_MEDAL_4, RealmRaidAssets.I_MEDAL_3,
                                     RealmRaidAssets.I_MEDAL_2, RealmRaidAssets.I_MEDAL_1, RealmRaidAssets.I_MEDAL_0])

        if ryou_config.switch_soul_config.enable:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul(ryou_config.switch_soul_config.switch_group_team)

        if ryou_config.switch_soul_config.enable_switch_by_name:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul_by_name(ryou_config.switch_soul_config.group_name, ryou_config.switch_soul_config.team_name)

        self.ui_get_current_page()
        self.ui_goto(page_kekkai_toppa)
        ryou_toppa_start_flag = True
        ryou_toppa_success_penetration = False
        ryou_toppa_admin_flag = False
        # 点击突破
        while 1:
            self.screenshot()
            if self.appear_then_click(RealmRaidAssets.I_REALM_RAID, interval=1):
                continue
            if self.appear(self.I_REAL_RAID_REFRESH, threshold=0.8):
                if self.appear_then_click(self.I_RYOU_TOPPA, interval=1):
                    continue
            # 攻破阴阳寮，说明寮突已开，则退出
            elif self.appear(self.I_SUCCESS_PENETRATION, threshold=0.8):
                ryou_toppa_start_flag = True
                ryou_toppa_success_penetration = True
                break
            # 出现选择寮突说明寮突未开
            elif self.appear(self.I_SELECT_RYOU_BUTTON, threshold=0.8):
                ryou_toppa_start_flag = False
                ryou_toppa_admin_flag = True
                break
            # 出现晴明说明寮突未开
            elif self.appear(self.I_NO_SELECT_RYOU, threshold=0.8):
                ryou_toppa_start_flag = False
                break
            # 出现寮奖励， 说明寮突已开
            elif self.appear(self.I_RYOU_REWARD, threshold=0.8) or self.appear(self.I_RYOU_REWARD_90, threshold=0.8):
                ryou_toppa_start_flag = True
                break

        logger.attr('ryou_toppa_start_flag', ryou_toppa_start_flag)
        logger.attr('ryou_toppa_success_penetration', ryou_toppa_success_penetration)
        # 寮突未开 并且有权限， 开开寮突，没有权限则标记失败
        if not ryou_toppa_start_flag:
            if ryou_config.raid_config.ryou_access and ryou_toppa_admin_flag:
                # 作为寮管理，开启今天的寮突
                logger.info("As the manager of the ryou, try to start ryou toppa.")
                self.start_ryou_toppa()
            else:
                logger.info("The ryou toppa is not open and you are a ryou member.")
                self.set_next_run(task='RyouToppa', finish=True, server=True, success=False)
                raise TaskEnd.completed('RyouToppa completed')

        # 100% 攻破, 第二天再执行
        if ryou_toppa_success_penetration:
            logger.info('RyouToppa is 100%')
            self.plan_tomorrow_ryoutoppa()
            raise TaskEnd.completed('RyouToppa completed')
        if self.config.ryou_toppa.general_battle_config.lock_team_enable:
            logger.info("Lock team.")
            self.ui_click(self.I_TOPPA_UNLOCK_TEAM, self.I_TOPPA_LOCK_TEAM)
        else:
            logger.info("Unlock team.")
            self.ui_click(self.I_TOPPA_LOCK_TEAM, self.I_TOPPA_UNLOCK_TEAM)
        # --------------------------------------------------------------------------------------------------------------
        # 开始突破
        # --------------------------------------------------------------------------------------------------------------
        area_index = 0
        success = True
        while 1:
            self.screenshot()
            if not self.appear(self.I_TOPPA_RECORD, threshold=0.6):
                continue
            # 设置长任务标志,用来寻找寮突可进攻的目标
            self.device.stuck_record_add('PREPARE_BEFORE_BATTLE')
            if not self.has_ticket():
                logger.info("We have no chance to attack. Try again after 1 hour.")
                success = False
                break
            if self.current_count >= ryou_config.raid_config.limit_count:
                logger.warning("We have attacked the limit count.")
                break
            if datetime.now() >= self.start_time + time_delta:
                logger.warning("We have attacked the limit time.")
                break
            # 进攻
            res = self.attack_area(area_index)
            # 如果战斗失败或区域不可用，则弹出当前区域索引，开始进攻下一个
            if not res:
                area_index += 1
                if area_index >= len(area_map):
                    logger.warning('All areas are not available, it will flush the area cache')
                    area_index = 0
                    self.flush_area_cache()
                continue


        # 回 page_main 失败
        # self.ui_current = page_ryou_toppa
        # self.ui_goto(page_main)
        if success:
            self.set_next_run(task='RyouToppa', finish=True, server=True, success=True)
        else:
            self.set_next_run(task='RyouToppa', finish=True, server=True, success=False)
        raise TaskEnd.completed('RyouToppa completed')

    def plan_tomorrow_ryoutoppa(self):
        # 安排下次寮突破，便于复用
        now = datetime.now()
        # 如果时间在00:00-5:00之间则设定时间为当天的自定义时间
        if now.time() < dt_time(5, 0):  # 不确定 time 的使用范围，重命名 datetime 中的 time
            self.custom_next_run(task='RyouToppa', custom_time=self.config.ryou_toppa.raid_config.next_ryoutoppa_time, time_delta=0)
        # 如果时间在05:00-23:59之间则设定时间为明天的自定义时间
        else:
            self.custom_next_run(task='RyouToppa', custom_time=self.config.ryou_toppa.raid_config.next_ryoutoppa_time, time_delta=1)

    def _legacy_start_ryou_toppa(self):
        logger.warning(
            "Legacy fixed-first guild selection is disabled; use verified OCR selection"
        )
        return False
        """
        开启寮突破
        :return:
        """
        # 点击寮突
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_SELECT_RYOU_BUTTON, interval=1):
                break
        logger.info(f'Click {self.I_SELECT_RYOU_BUTTON.name}')

        # 选择第一个寮
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_GUILD_ORDERS_REWARDS, action=self.C_SELECT_FIRST_RYOU, interval=1):
                break
        logger.info(f'Click {self.C_SELECT_FIRST_RYOU.name}')

        # 点击开始突入
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_START_TOPPA_BUTTON, interval=1):
                continue
            # 出现寮奖励， 说明寮突已开
            if self.appear(self.I_RYOU_REWARD, threshold=0.8):
                break
        logger.info(f'Click {self.I_START_TOPPA_BUTTON.name}')

    def _legacy_has_ticket(self) -> bool:
        """
        如果没有票了，那么就返回False
        :return:
        """
        # 21点后、次日5点前无限进攻机会
        if datetime.now().hour >= 21 or datetime.now().hour <= 5:
            return True
        self.wait_until_appear(self.I_TOPPA_RECORD)
        self.screenshot()
        cu, res, total = self.O_NUMBER.ocr(self.device.image)
        if cu == 0 and cu + res == total:
            logger.warning(f'Execute round failed, no ticket')
            return False
        return True

    def _legacy_check_area(self, index: int) -> bool:
        """
        检查该区域是否攻略失败
        :return:
        """
        f1, f2 = area_map[index].get("fail_sign")
        f3, f4 = area_map[index].get("finished_sign")
        self.screenshot()
        # 如果该区域已经被攻破则退出
        # Ps: 这时候能打过的都打过了，没有能攻打的结界了, 代表任务已经完成，set_next_run time=1d
        if self.appear(f3, threshold=0.8) or self.appear(f4, threshold=0.8):
            logger.info('RyouToppa has tried to attack')
            self.plan_tomorrow_ryoutoppa()
            raise TaskEnd.completed('RyouToppa completed')
        # 如果该区域攻略失败返回 False
        if self.appear(f1, threshold=0.8) or self.appear(f2, threshold=0.8):
            logger.info('Area [%s] is futile attack, skip.' % str(index + 1))
            return False
        return True

    def flush_area_cache(self):
        time.sleep(2)
        duration = 0.352
        count = random.randint(1, 3)
        for i in range(count):
            # 测试过很多次 win32api, win32gui 的 MOUSEEVENTF_WHEEL, WM_MOUSEWHEEL
            # 都出现过很多次离奇的事件，索性放弃了使用以下方法，参数是精心调试的
            # 每次执行刚好刷新一组（2个）设定随机刷新 1 - 3 次
            safe_pos_x = random.randint(540, 1000)
            safe_pos_y = random.randint(320, 540)
            p1 = (safe_pos_x, safe_pos_y)
            p2 = (safe_pos_x, safe_pos_y - 101)
            logger.info('Swipe %s -> %s, %s ' % (point2str(*p1), point2str(*p2), duration))
            self.device.swipe_adb(p1, p2, duration=duration)
            time.sleep(2)

    def _legacy_attack_area(self, index: int):
        """
        :return: 战斗成功(True) or 战斗失败(False) or 区域不可用（False） or 没有进攻机会（设定下次运行并退出）
        """
        # 每次进攻前检查区域可用性
        if not self.check_area(index):
            return False

        # 正式进攻会设定 2s - 10s 的随机延迟，避免攻击间隔及其相近被检测为脚本。
        if self.config.ryou_toppa.raid_config.random_delay:
            delay = random_delay()
            time.sleep(delay)


        rcl = area_map[index].get("rule_click")
        # # 点击攻击区域，等待攻击按钮出现。
        # self.ui_click(rcl, stop=RealmRaidAssets.I_FIRE, interval=2)
        # 塔塔开！
        click_failure_count = 0
        while True:
            self.screenshot()
            if click_failure_count >= 5:
                logger.warning("Click failure, check your click position")
                return False
            if not self.appear(self.I_TOPPA_RECORD, threshold=0.85):
                time.sleep(1)
                self.screenshot()
                if self.appear(self.I_TOPPA_RECORD, threshold=0.85):
                    continue
                logger.info("Start attach area [%s]" % str(index + 1))
                return self.run_general_battle(config=self.config.ryou_toppa.general_battle_config)

            if self.appear_then_click(RealmRaidAssets.I_FIRE, interval=2, threshold=0.8):
                click_failure_count += 1
                continue
            if self.click(rcl, interval=5):
                click_failure_count += 1
                continue


    def run(self):
        ryou_config = self.config.ryou_toppa
        time_limit: Time = ryou_config.raid_config.limit_time
        time_delta = timedelta(
            hours=time_limit.hour,
            minutes=time_limit.minute,
            seconds=time_limit.second,
        )
        self.current_count = 0
        self._battle_preset_preapplied = False

        if ryou_config.switch_soul_config.enable:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul(ryou_config.switch_soul_config.switch_group_team)

        if ryou_config.switch_soul_config.enable_switch_by_name:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul_by_name(
                ryou_config.switch_soul_config.group_name,
                ryou_config.switch_soul_config.team_name,
            )

        # Guild raids do not expose the personal-raid quick preset button.
        if not self._prepare_ryou_team_preset(ryou_config.general_battle_config):
            self._end_ryou_task(False, "preset_prepare_failed")

        self.ui_get_current_page()
        if not self.ui_goto(page_kekkai_toppa, timeout=60):
            self._end_ryou_task(False, "page_kekkai_toppa_timeout")

        entry_state = self._wait_ryou_entry_state()
        logger.attr("RYOU_ENTRY_STATE", entry_state)
        if entry_state == "unselected":
            logger.warning("No guild is selected and automatic medal selection failed")
            self._end_ryou_task(False, "guild_auto_select_failed")
        if entry_state == "timeout":
            self._end_ryou_task(False, "ryou_entry_timeout")
        if entry_state == "complete":
            self._end_ryou_task(True, "already_complete")

        self._initialize_team_lock_validation(
            ryou_config.general_battle_config.lock_team_enable,
        )

        outcome = self._run_ryou_board(ryou_config, time_delta)
        logger.attr("RYOU_OUTCOME", outcome)
        self._end_ryou_task(outcome == "completed", outcome)

    def _end_ryou_task(self, success: bool, reason: str) -> None:
        logger.info(f"RyouToppa task end: success={success}, reason={reason}")
        if success:
            self.plan_tomorrow_ryoutoppa()
        else:
            self.set_next_run(
                task="RyouToppa",
                finish=True,
                server=True,
                success=False,
            )
        statistics = {'ryou_outcome': reason}
        if success:
            raise TaskEnd.completed(
                'RyouToppa completed',
                statistics=statistics,
            )
        if reason in {'no_ticket', 'count_limit', 'time_limit', 'no_attackable_target'}:
            raise TaskEnd.deferred(
                f'RyouToppa deferred: {reason}',
                statistics=statistics,
            )
        raise TaskEnd.failed(
            f'RyouToppa failed: {reason}',
            statistics=statistics,
        )

    def _prepare_ryou_team_preset(self, config) -> bool:
        if not getattr(config, "preset_enable", False):
            logger.info("RyouToppa named preset is disabled")
            return True

        group_name = str(getattr(config, "preset_group_name", "") or "").strip()
        team_name = str(getattr(config, "preset_team_name", "") or "").strip()
        if not group_name or not team_name:
            logger.warning(
                "RyouToppa named preset is enabled but group/team name is incomplete"
            )
            return False

        logger.info(
            "RYOU_PRESET_PREPARE_START "
            f"group={group_name}, team={team_name}"
        )
        current_page = self.ui_get_current_page()
        if current_page != page_shikigami_records:
            if not self.ui_goto(page_shikigami_records, timeout=60):
                logger.error("RYOU_PRESET_PREPARE_PAGE_TIMEOUT")
                return False
        try:
            self.preapply_preset_team_from_records(group_name, team_name)
        except Exception as error:
            logger.error(f"RYOU_PRESET_RESULT result=failed error={error}")
            raise
        self._battle_preset_preapplied = True
        logger.info(
            "RYOU_PRESET_RESULT result=applied "
            f"group={group_name}, team={team_name}"
        )
        return True

    def _wait_ryou_entry_state(self, timeout: float = RYOU_ENTRY_TIMEOUT_SECONDS) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(self.I_SELECT_RYOU_BUTTON, threshold=0.8):
                if self._auto_select_highest_medal_ryou():
                    return "board"
                return "unselected"
            if self.appear(self.I_NO_SELECT_RYOU, threshold=0.8):
                if self._auto_select_highest_medal_ryou():
                    return "board"
                return "unselected"
            if self.appear(self.I_SUCCESS_PENETRATION, threshold=0.8):
                return "complete"
            if (
                self.appear(self.I_TOPPA_RECORD, threshold=0.6)
                or self.appear(self.I_RYOU_REWARD, threshold=0.8)
                or self.appear(self.I_RYOU_REWARD_90, threshold=0.8)
            ):
                return "board"

            # Keep the old two-entry navigation compatible, but never select
            # a guild on the user's behalf.
            if self.appear_then_click(RealmRaidAssets.I_REALM_RAID, interval=1):
                continue
            if self.appear(self.I_REAL_RAID_REFRESH, threshold=0.8):
                if self.appear_then_click(self.I_RYOU_TOPPA, interval=1):
                    continue
            time.sleep(0.25)
        logger.warning("RYOU_ENTRY_TIMEOUT")
        return "timeout"

    def _auto_select_highest_medal_ryou(
        self,
        timeout: float = RYOU_GUILD_SELECT_TIMEOUT_SECONDS,
    ) -> bool:
        """Verify both built-in sort orders, then select the first descending row."""
        enabled = bool(
            getattr(
                self.config.ryou_toppa.raid_config,
                "auto_select_highest_guild",
                False,
            )
        )
        if not enabled:
            logger.warning("RYOU_GUILD_SELECT_RESULT result=disabled")
            return False
        if not self.GUILD_CANDIDATE_OCR_RULES:
            logger.warning(
                "RYOU_GUILD_SELECT_RESULT result=unavailable "
                "reason=candidate_ocr_rules_unconfigured"
            )
            return False

        deadline = time.monotonic() + timeout
        logger.info("RYOU_GUILD_SELECT_START strategy=sort_extremes_fixed_top")
        while time.monotonic() < deadline:
            self.screenshot()
            if self._board_marker_visible():
                logger.info("RYOU_GUILD_SELECT_RESULT result=board_already_visible")
                return True
            if self.appear(self.I_GUILD_ORDERS_REWARDS, threshold=0.7):
                break
            if self.appear_then_click(self.I_SELECT_RYOU_BUTTON, interval=1):
                logger.info("RYOU_GUILD_SELECT_OPEN_LIST")
            time.sleep(0.25)
        else:
            logger.warning("RYOU_GUILD_SELECT_TIMEOUT phase=open_list")
            return False

        first = self._wait_stable_guild_sort_snapshot(deadline)
        if first is None:
            return False
        if not self.click(self.C_GUILD_ORDERS_REWARDS, interval=0.5):
            logger.warning("RYOU_GUILD_SELECT_RESULT result=failed reason=sort_click_failed")
            return False

        second = self._wait_stable_guild_sort_snapshot(
            deadline,
            changed_from=first.values,
        )
        if second is None:
            return False
        pair = compare_guild_sort_snapshots(first, second)
        if not pair.verified:
            logger.warning(
                "RYOU_GUILD_SELECT_RESULT result=unconfirmed "
                f"reason={pair.reason} first={first.values} second={second.values}"
            )
            return False

        expected_descending = (
            first if first.order is GuildSortOrder.DESCENDING else second
        )
        changed_from = None
        if second.order is not GuildSortOrder.DESCENDING:
            if not self.click(self.C_GUILD_ORDERS_REWARDS, interval=0.5):
                logger.warning(
                    "RYOU_GUILD_SELECT_RESULT result=failed "
                    "reason=return_descending_click_failed"
                )
                return False
            changed_from = second.values

        final_descending = self._wait_stable_guild_sort_snapshot(
            deadline,
            changed_from=changed_from,
        )
        if final_descending is None:
            return False
        final_check = verify_final_descending_snapshot(
            expected_descending,
            final_descending,
        )
        if not final_check.verified:
            logger.warning(
                "RYOU_GUILD_SELECT_RESULT result=unconfirmed "
                f"reason={final_check.reason} expected={expected_descending.values} "
                f"actual={final_descending.values}"
            )
            return False

        logger.info(
            "RYOU_GUILD_SORT_VERIFIED "
            f"highest={pair.highest_medal} lowest={pair.lowest_medal} "
            f"descending={pair.descending_values} ascending={pair.ascending_values} "
            f"frame_id={final_descending.frame_id} "
            f"frame_sha256={final_descending.frame_sha256}"
        )
        if not self.click(self.C_SELECT_FIRST_RYOU, interval=1):
            logger.warning(
                "RYOU_GUILD_SELECT_RESULT result=failed reason=first_card_click_failed"
            )
            return False
        logger.info(
            "RYOU_GUILD_SELECT_CARD candidate=row_1 "
            f"medal_reward={pair.highest_medal} verified_sort=descending"
        )

        start_clicked = False
        while time.monotonic() < deadline:
            self.screenshot()
            if self._board_marker_visible():
                logger.info("RYOU_GUILD_SELECT_RESULT result=board")
                return True
            if not start_clicked and self.appear_then_click(
                self.I_START_TOPPA_BUTTON,
                interval=1,
            ):
                start_clicked = True
                logger.info("RYOU_GUILD_SELECT_START_RAID")
                continue
            if start_clicked and self.appear(self.I_SELECT_RYOU_BUTTON, threshold=0.8):
                logger.warning(
                    "RYOU_GUILD_SELECT_RESULT result=selection_prompt_remains"
                )
                return False
            time.sleep(0.25)

        logger.warning("RYOU_GUILD_SELECT_TIMEOUT")
        return False

    def _wait_stable_guild_sort_snapshot(
        self,
        deadline: float,
        *,
        changed_from: tuple[int, ...] | None = None,
    ) -> GuildSortSnapshot | None:
        previous = None
        last_reason = "timeout"
        while time.monotonic() < deadline:
            self.screenshot()
            observation = self._observe_guild_candidates()
            snapshot = classify_guild_sort_order(observation)
            if not snapshot.verified:
                previous = None
                last_reason = snapshot.reason
                time.sleep(0.2)
                continue
            if changed_from is not None and snapshot.values == changed_from:
                previous = None
                last_reason = "sort_values_not_changed"
                time.sleep(0.2)
                continue
            if previous is not None:
                comparison = compare_guild_observations(previous, observation)
                if comparison.stable:
                    logger.info(
                        "RYOU_GUILD_SORT_STABLE "
                        f"order={snapshot.order.value} values={snapshot.values} "
                        f"frame_id={snapshot.frame_id} "
                        f"frame_sha256={snapshot.frame_sha256}"
                    )
                    return snapshot
                last_reason = comparison.reason
            previous = observation
            time.sleep(0.2)

        logger.warning(
            "RYOU_GUILD_SELECT_RESULT result=unconfirmed "
            f"reason={last_reason} phase=stable_sort"
        )
        return None

    def _observe_guild_candidates(self) -> tuple[GuildCandidate, ...]:
        image = self.device.image
        frame_sha256 = hashlib.sha256(image.tobytes()).hexdigest()
        frame_id = f"guild_{time.monotonic_ns()}"
        candidates = []
        for candidate_id, card_rect, medal_ocr in self.GUILD_CANDIDATE_OCR_RULES:
            results = medal_ocr.detect_and_ocr(image, logDisplay=False)
            if len(results) == 1:
                result = results[0]
                medal_reward = (
                    int(result.ocr_text)
                    if isinstance(result.ocr_text, int)
                    or str(result.ocr_text).isdigit()
                    else None
                )
                confidence = float(result.score)
            else:
                medal_reward = None
                confidence = None
            x, y, width, height = card_rect
            candidates.append(
                GuildCandidate(
                    candidate_id=str(candidate_id),
                    card_rect=tuple(card_rect),
                    center=(x + width // 2, y + height // 2),
                    medal_reward=medal_reward,
                    ocr_confidence=confidence,
                    frame_id=frame_id,
                    frame_sha256=frame_sha256,
                )
            )
        return tuple(candidates)

    def _initialize_team_lock_validation(self, lock_enable: bool) -> None:
        self._team_lock_validation_state = (
            TeamLockValidationState.OBSERVING
            if lock_enable
            else TeamLockValidationState.DISABLED
        )
        logger.info(
            "RYOU_LOCK_VALIDATION "
            f"state={self._team_lock_validation_state.value} method=battle_entry_effect"
        )

    def _observe_team_lock_entry(self, entry_mode: BattleEntryMode) -> None:
        state = getattr(
            self,
            "_team_lock_validation_state",
            TeamLockValidationState.DISABLED,
        )
        if state is TeamLockValidationState.DISABLED:
            return

        if state is TeamLockValidationState.OBSERVING:
            if entry_mode is BattleEntryMode.DIRECT_BATTLE:
                self._team_lock_validation_state = TeamLockValidationState.VERIFIED
                logger.info(
                    "RYOU_LOCK_VALIDATION state=verified "
                    "reason=first_battle_entered_directly"
                )
            else:
                self._team_lock_validation_state = (
                    TeamLockValidationState.CLICK_AFTER_RETURN
                )
                logger.info(
                    "RYOU_LOCK_VALIDATION state=click_after_return "
                    "reason=first_battle_required_prepare"
                )
            return

        if state is TeamLockValidationState.VERIFY_NEXT_BATTLE:
            if entry_mode is BattleEntryMode.DIRECT_BATTLE:
                self._team_lock_validation_state = TeamLockValidationState.VERIFIED
                logger.info(
                    "RYOU_LOCK_VALIDATION state=verified "
                    "reason=second_battle_entered_directly"
                )
            else:
                self._team_lock_validation_state = (
                    TeamLockValidationState.VERIFIED_PREPARE_REQUIRED
                )
                logger.info(
                    "RYOU_LOCK_VALIDATION state=verified_prepare_required "
                    "reason=visual_lock_active_but_ryou_still_requires_prepare "
                    "action=bounded_prepare_no_reclick"
                )

    def _after_ryou_battle_return(self) -> None:
        state = getattr(
            self,
            "_team_lock_validation_state",
            TeamLockValidationState.DISABLED,
        )
        if state is not TeamLockValidationState.CLICK_AFTER_RETURN:
            return

        locked, action = self._ensure_ryou_team_locked()
        if not locked:
            self._team_lock_validation_state = TeamLockValidationState.FAILED
            logger.warning(
                "RYOU_LOCK_VALIDATION state=failed "
                f"reason=lock_state_unconfirmed action={action}"
            )
            return

        self._team_lock_validation_state = TeamLockValidationState.VERIFY_NEXT_BATTLE
        logger.info(
            "RYOU_LOCK_VALIDATION state=verify_next_battle "
            f"action={action}"
        )

    def _ensure_ryou_team_locked(
        self,
        timeout: float = RYOU_LOCK_STATE_TIMEOUT_SECONDS,
        required_stable_frames: int = 2,
    ) -> tuple[bool, str]:
        """Use action-icon semantics and verify the transition to locked."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        clicked = False
        locked_streak = 0
        lock_action_streak = 0
        required = max(2, int(required_stable_frames))
        while time.monotonic() <= deadline:
            self.screenshot()
            # These controls describe the available action.  The open-lock
            # icon means the team is already locked and can now be unlocked.
            if self.appear(self.I_TOPPA_UNLOCK_TEAM, threshold=0.8):
                locked_streak += 1
                lock_action_streak = 0
                if locked_streak >= required:
                    return (
                        True,
                        "lock_already_active" if not clicked else "lock_clicked_and_verified",
                    )
            elif self.appear(self.I_TOPPA_LOCK_TEAM, threshold=0.8):
                locked_streak = 0
                lock_action_streak += 1
                if not clicked and lock_action_streak >= required:
                    if self.appear_then_click(
                        self.I_TOPPA_LOCK_TEAM,
                        interval=0.5,
                        threshold=0.8,
                    ):
                        clicked = True
                        locked_streak = 0
                        lock_action_streak = 0
                        logger.info(
                            "RYOU_LOCK_VALIDATION state=locking "
                            "action=click_stable_lock_action"
                        )
                        continue
            else:
                locked_streak = 0
                lock_action_streak = 0
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.2, remaining))
        return False, "lock_click_not_verified" if clicked else "lock_state_unknown"

    def _board_marker_visible(self) -> bool:
        return (
            self.appear(self.I_TOPPA_RECORD, threshold=0.6)
            or self.appear(self.I_RYOU_REWARD, threshold=0.8)
            or self.appear(self.I_RYOU_REWARD_90, threshold=0.8)
            or self.appear(self.I_SUCCESS_PENETRATION, threshold=0.8)
        )

    def _area_status(self, index: int, screenshot: bool = True) -> AreaStatus:
        if screenshot:
            self.screenshot()
        finished_signs = area_map[index]["finished_sign"]
        failed_signs = area_map[index]["fail_sign"]
        if any(self.appear(sign, threshold=0.8) for sign in finished_signs):
            return AreaStatus.FINISHED
        if any(self.appear(sign, threshold=0.8) for sign in failed_signs):
            return AreaStatus.FAILED
        return AreaStatus.AVAILABLE

    def _read_area_statuses(self) -> list[AreaStatus]:
        self.screenshot()
        statuses = [
            self._area_status(index, screenshot=False)
            for index in range(len(area_map))
        ]
        logger.info(
            "RYOU_BOARD_STATUS "
            + ",".join(
                f"{index + 1}:{status.value}"
                for index, status in enumerate(statuses)
            )
        )
        return statuses

    @staticmethod
    def _ticket_status_from_ocr(result) -> TicketStatus:
        if not isinstance(result, tuple) or len(result) != 3:
            return TicketStatus.UNKNOWN
        used, remaining, total = result
        if not all(isinstance(value, int) for value in result):
            return TicketStatus.UNKNOWN
        if total <= 0 or used < 0 or remaining < 0 or used > total:
            return TicketStatus.UNKNOWN
        if remaining == 0:
            return TicketStatus.EMPTY
        return TicketStatus.AVAILABLE

    def ticket_status(self) -> TicketStatus:
        # The game permits unlimited attacks in the nightly window.
        if datetime.now().hour >= 21 or datetime.now().hour <= 5:
            return TicketStatus.AVAILABLE
        if not self.wait_until_appear(self.I_TOPPA_RECORD, wait_time=5):
            return TicketStatus.UNKNOWN
        self.screenshot()
        try:
            result = self.O_NUMBER.ocr(self.device.image)
        except Exception as error:
            logger.warning(f"RYOU_TICKET_OCR_ERROR error={error}")
            return TicketStatus.UNKNOWN
        return self._ticket_status_from_ocr(result)

    def _ticket_status_with_retry(self, attempts: int = 3) -> TicketStatus:
        for attempt in range(1, attempts + 1):
            status = self.ticket_status()
            if status is not TicketStatus.UNKNOWN:
                return status
            logger.warning(f"RYOU_TICKET_OCR_UNKNOWN retry={attempt}/{attempts}")
            time.sleep(0.5)
        return TicketStatus.UNKNOWN

    def _click_ryou_attack_button(self) -> bool:
        """Consume the attack confirmation shown after selecting a guild card."""
        if self.appear_then_click(
            RealmRaidAssets.I_FIRE,
            interval=1,
            threshold=0.8,
        ):
            logger.info("RYOU_ATTACK_CONFIRM variant=I_FIRE")
            return True
        if self.appear_then_click(RealmRaidAssets.I_FIRE_CURRENT, interval=1):
            logger.info("RYOU_ATTACK_CONFIRM variant=I_FIRE_CURRENT")
            return True
        return False

    def has_ticket(self) -> bool:
        return self.ticket_status() is TicketStatus.AVAILABLE

    def _wait_for_battle_entry(
        self,
        timeout: float = RYOU_BATTLE_ENTRY_TIMEOUT_SECONDS,
    ) -> BattleEntryMode | None:
        deadline = time.monotonic() + timeout
        prepare_streak = 0
        while time.monotonic() < deadline:
            self.screenshot()
            if self._click_ryou_attack_button():
                prepare_streak = 0
                continue
            if self._prepare_button_visible() or self.is_in_prepare(False):
                prepare_streak += 1
                logger.info(
                    "RYOU_PREPARE_CANDIDATE "
                    f"streak={prepare_streak}/{RYOU_PREPARE_STABLE_FRAMES}"
                )
                if prepare_streak >= RYOU_PREPARE_STABLE_FRAMES:
                    return BattleEntryMode.PREPARE_REQUIRED
                time.sleep(0.2)
                continue
            prepare_streak = 0
            if (
                self.is_in_real_battle(False)
                or self._battle_result_continue_visible()
                or self.appear(self.I_WIN, threshold=0.8)
                or self.appear(self.I_FALSE, threshold=0.8)
            ):
                return BattleEntryMode.DIRECT_BATTLE
            time.sleep(0.2)
        logger.warning("RYOU_BATTLE_ENTRY_TIMEOUT")
        return None

    def _wait_for_board_return(
        self,
        timeout: float = RYOU_BOARD_RETURN_TIMEOUT_SECONDS,
    ) -> bool:
        deadline = time.monotonic() + timeout
        result_continue_clicks = 0
        while time.monotonic() < deadline:
            self.screenshot()
            if self._board_marker_visible():
                return True
            if self.appear(self.I_SELECT_RYOU_BUTTON, threshold=0.8):
                return False
            if self._battle_result_continue_visible():
                if result_continue_clicks >= 3:
                    logger.warning(
                        'RYOU_BOARD_RETURN_RESULT_CONTINUE_LIMIT reached'
                    )
                    return False
                result_continue_clicks += 1
                if not self._click_result_continue_bottom():
                    return False
                logger.info(
                    'RYOU_BOARD_RETURN_RESULT_CONTINUE '
                    f'attempt={result_continue_clicks}'
                )
                time.sleep(0.5)
                continue
            time.sleep(0.25)
        logger.warning("RYOU_BOARD_RETURN_TIMEOUT")
        return False

    def _attack_area_detailed(self, index: int, battle_config) -> AttackResult:
        status = self._area_status(index)
        if status is AreaStatus.FINISHED:
            return AttackResult.AREA_FINISHED
        if status is AreaStatus.FAILED:
            return AttackResult.AREA_FAILED

        if self.config.ryou_toppa.raid_config.random_delay:
            time.sleep(random_delay())

        rule_click = area_map[index]["rule_click"]
        for attempt in range(1, 6):
            self.screenshot()
            if self.appear(self.I_TOPPA_RECORD, threshold=0.85):
                if not self.click(rule_click, interval=0.8):
                    time.sleep(0.25)
                    continue
                logger.info(f"RYOU_AREA_CLICK area={index + 1}, attempt={attempt}")

            entry_mode = self._wait_for_battle_entry()
            if entry_mode is None:
                continue

            self._observe_team_lock_entry(entry_mode)
            logger.info(
                f"RYOU_BATTLE_START area={index + 1}, entry={entry_mode.value}"
            )
            win = self.run_general_battle(config=battle_config)
            if not win:
                logger.warning(f"RYOU_BATTLE_RESULT area={index + 1}, result=failed")
                return AttackResult.BATTLE_FAILED
            if not self._wait_for_board_return():
                return AttackResult.PAGE_TIMEOUT
            self._after_ryou_battle_return()
            logger.info(f"RYOU_BATTLE_RESULT area={index + 1}, result=success")
            return AttackResult.SUCCESS

        return AttackResult.CLICK_TIMEOUT

    def attack_area(self, index: int) -> bool:
        result = self._attack_area_detailed(
            index,
            self.config.ryou_toppa.general_battle_config,
        )
        return result is AttackResult.SUCCESS

    def check_area(self, index: int) -> bool:
        return self._area_status(index) is AreaStatus.AVAILABLE

    def start_ryou_toppa(self):
        logger.warning(
            "RyouToppa start requires a manually selected guild; automatic first-guild selection is disabled"
        )
        return False

    def _run_ryou_board(self, ryou_config, time_delta: timedelta) -> str:
        deadline = self.start_time + time_delta
        idle_since = None
        while datetime.now() < deadline:
            self.screenshot()
            if not self._board_marker_visible():
                if idle_since is None:
                    idle_since = time.monotonic()
                elif time.monotonic() - idle_since >= RYOU_BOARD_IDLE_TIMEOUT_SECONDS:
                    logger.warning("RYOU_BOARD_MARKER_TIMEOUT")
                    return "page_unknown"
                time.sleep(0.25)
                continue
            idle_since = None

            if self.current_count >= ryou_config.raid_config.limit_count:
                logger.warning("RYOU_COUNT_LIMIT")
                return "count_limit"

            if self.appear(self.I_SUCCESS_PENETRATION, threshold=0.8):
                logger.info("RYOU_BOARD_COMPLETE success penetration marker is visible")
                return "completed"

            statuses = self._read_area_statuses()
            if all(status is AreaStatus.FINISHED for status in statuses):
                logger.info("RYOU_BOARD_COMPLETE all area finish markers are visible")
                return "completed"

            available = [
                index
                for index, status in enumerate(statuses)
                if status is AreaStatus.AVAILABLE
            ]
            if not available:
                if any(status is AreaStatus.FAILED for status in statuses):
                    logger.warning("RYOU_BOARD_NO_ATTACKABLE_TARGET area failure marker remains")
                    return "area_failed"
                logger.warning("RYOU_BOARD_NO_ATTACKABLE_TARGET")
                return "no_attackable_target"

            ticket_status = self._ticket_status_with_retry()
            logger.attr("RYOU_TICKET_STATUS", ticket_status.value)
            if ticket_status is TicketStatus.EMPTY:
                logger.info("RYOU_NO_TICKET")
                return "no_ticket"
            if ticket_status is TicketStatus.UNKNOWN:
                logger.warning("RYOU_TICKET_OCR_UNKNOWN")
                return "ocr_unknown"

            target = available[0]
            self.device.stuck_record_add("RYOU_PREPARE_BEFORE_BATTLE")
            result = self._attack_area_detailed(
                target,
                ryou_config.general_battle_config,
            )
            logger.info(f"RYOU_AREA_RESULT area={target + 1}, result={result.value}")
            if result in (AttackResult.SUCCESS, AttackResult.AREA_FINISHED, AttackResult.AREA_FAILED):
                continue
            return result.value

        logger.warning("RYOU_TIME_LIMIT")
        return "time_limit"


if __name__ == "__main__":
    from module.config.config import Config
    from module.device.device import Device

    config = Config('oas1')
    device = Device(config)
    t = ScriptTask(config, device)
    t.run()
