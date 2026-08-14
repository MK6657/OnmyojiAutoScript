# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
import numpy as np
import random
from dataclasses import dataclass, field
from enum import Enum
from cached_property import cached_property
from datetime import timedelta, datetime

from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.Component.GeneralRoom.general_room import GeneralRoom
from tasks.Component.GeneralInvite.general_invite import GeneralInvite
from tasks.Component.ReplaceShikigami.replace_shikigami import ReplaceShikigami
from tasks.Exploration.assets import ExplorationAssets
from tasks.Exploration.config import ChooseRarity, AutoRotate, AttackNumber, UpType
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_exploration, page_shikigami_records, page_main
from tasks.RealmRaid.script_task import ScriptTask as RealmRaidScriptTask
from tasks.Utils.config_enum import ShikigamiClass

from module.logger import logger
from module.base.timer import Timer
from module.exception import (
    GamePageUnknownError,
    GameStuckError,
    GameTooManyClickError,
    RequestHumanTakeover,
    TaskEnd,
)
from module.atom.image_grid import ImageGrid
from module.atom.animate import RuleAnimate
from module.base.utils import load_image


# The current blue exploration skin places the exit button text in a small,
# stable area.  Share this narrow rule with the common page recovery path so
# normal exits and startup recovery close the same modal first.
O_EXPLORATION_EXIT_CONFIRM = ExplorationAssets.O_E_EXIT_CONFIRM_TEXT

class Scene(Enum):
    UNKNOWN = 0  #
    WORLD = 1  # 探索大世界
    ENTRANCE = 2  # 入口弹窗
    MAIN = 3  # 探索里面
    BATTLE_PREPARE = 4  # 战斗准备
    BATTLE_FIGHTING = 5  # 战斗中
    TEAM = 6  # 组队


class ExplorationExitReason(str, Enum):
    """Why exploration requested an exit, kept in logs for later diagnosis."""

    UNKNOWN = 'unknown'
    BATTLE_LIMIT = 'battle_limit'
    SEARCH_EXHAUSTED = 'search_exhausted'
    TEAM_MEMBER_LEFT = 'team_member_left'
    SEARCH_BUDGET_EXHAUSTED = 'search_budget_exhausted'


class ExplorationBudgetExceeded(GameStuckError):
    def __init__(self, reason: str, *, recognitions: int, swipes: int, elapsed: float):
        self.reason = reason
        self.recognitions = recognitions
        self.swipes = swipes
        self.elapsed = elapsed
        super().__init__(
            'Exploration budget exhausted '
            f'reason={reason} recognitions={recognitions} swipes={swipes} '
            f'elapsed={elapsed:.3f}s'
        )


@dataclass
class ExplorationSearchBudget:
    timeout_seconds: float
    max_recognitions: int
    max_swipes: int
    started_at: float = field(default_factory=time.monotonic)
    recognitions: int = 0
    swipes: int = 0

    def _check(self) -> None:
        elapsed = time.monotonic() - self.started_at
        if elapsed > self.timeout_seconds:
            raise ExplorationBudgetExceeded(
                'time_budget_exhausted',
                recognitions=self.recognitions,
                swipes=self.swipes,
                elapsed=elapsed,
            )
        if self.recognitions > self.max_recognitions:
            raise ExplorationBudgetExceeded(
                'recognition_budget_exhausted',
                recognitions=self.recognitions,
                swipes=self.swipes,
                elapsed=elapsed,
            )
        if self.swipes > self.max_swipes:
            raise ExplorationBudgetExceeded(
                'swipe_budget_exhausted',
                recognitions=self.recognitions,
                swipes=self.swipes,
                elapsed=elapsed,
            )

    def record_recognition(self) -> None:
        self.recognitions += 1
        self._check()

    def record_swipe(self) -> None:
        self.swipes += 1
        self._check()




class BaseExploration(GameUi, GeneralBattle, GeneralRoom, GeneralInvite, ReplaceShikigami, SwitchSoul, ExplorationAssets):
    BUFF_UNAVAILABLE = 'unavailable'
    minions_cnt = 0
    UNKNOWN_SCENE_LIMIT = 4
    UNKNOWN_SCENE_RETRY_DELAY = 0.5
    LEVEL_SEARCH_MAX_SWIPES = 15
    LEVEL_SEARCH_TIMEOUT = 45.0
    LEVEL_SELECTION_MAX_ATTEMPTS = 20
    LEVEL_SELECTION_TIMEOUT = 30.0
    MAP_SEARCH_TIMEOUT = 120.0
    MAP_SEARCH_MAX_RECOGNITIONS = 120
    MAP_SEARCH_MAX_SWIPES = 8
    CLICK_WORKFLOW_TIMEOUT = 12.0
    CLICK_WORKFLOW_MAX_ACTIONS = 6
    EXTRA_PREPARE_TEXTS = frozenset({'鲁攻', '自动攻'})

    DISCOVERY_PANEL_ROI = (150, 160, 985, 400)
    DISCOVERY_PANEL_BRIGHT_THRESHOLD = 160
    DISCOVERY_PANEL_MIN_BRIGHT_RATIO = 0.55

    @cached_property
    def _config(self):
        self.config.exploration.general_battle_config.lock_team_enable = True
        limit_time = self.config.exploration.exploration_config.limit_time
        self.limit_time: timedelta = timedelta(
            hours=limit_time.hour,
            minutes=limit_time.minute,
            seconds=limit_time.second
        )
        return self.config.model.exploration

    def _raise_exploration_click_boundary(
        self,
        operation: str,
        *,
        reason: str,
        actions: int,
        timeout: float | None,
        max_actions: int | None,
        target: str = 'multiple',
        detail: str | None = None,
    ) -> None:
        raise GameStuckError(
            'Exploration click workflow failed '
            f'operation={operation} reason={reason} target={target} '
            f'actions={actions} timeout={timeout!r} '
            f'max_actions={max_actions!r} detail={detail!r}'
        )

    def _raise_click_workflow_failure(self, operation: str) -> None:
        failure = getattr(self, '_last_ui_click_failure', None)
        BaseExploration._raise_exploration_click_boundary(
            self,
            operation,
            reason=getattr(failure, 'reason', 'unknown'),
            target=getattr(failure, 'target', 'unknown'),
            actions=getattr(failure, 'actions', 0),
            timeout=getattr(failure, 'timeout', None),
            max_actions=getattr(failure, 'max_actions', None),
            detail=getattr(failure, 'detail', None),
        )

    def _require_click_workflow(self, success: bool, operation: str) -> bool:
        if success:
            return True
        self._raise_click_workflow_failure(operation)

    @cached_property
    def _match_end(self):
        return RuleAnimate(self.I_SWIPE_END)

    EXPLORATION_SWIPE_SETTLE_MIN = 0.8
    EXPLORATION_SWIPE_SETTLE_MAX = 2.5
    EXPLORATION_SWIPE_STABLE_FRAMES = 2
    EXPLORATION_SWIPE_RETRY_LIMIT = 1

    def _exploration_frame_marker(self):
        """Return a marker that changes only after a new screenshot is published."""
        device = getattr(self, 'device', None)
        if device is None:
            return None
        return (
            getattr(device, 'frame_id', None),
            id(getattr(device, 'image', None)),
        )

    @staticmethod
    def _exploration_viewport_signature(image):
        """Create a cheap, low-resolution signature for the scrolling viewport."""
        if image is None or not hasattr(image, 'shape'):
            return None
        try:
            array = np.asarray(image)
            if array.ndim < 2:
                return None
            height, width = array.shape[:2]
            if height < 100 or width < 100:
                return None
            # The lower half contains animated shikigami, EXP effects and the
            # fixed controls.  The upper-middle landscape is stable on the
            # current client and still moves with the exploration viewport.
            x1 = min(width, max(0, int(width * 0.12)))
            x2 = min(width, max(x1 + 1, int(width * 0.88)))
            y1 = min(height, max(0, int(height * 0.14)))
            y2 = min(height, max(y1 + 1, int(height * 0.43)))
            sample = array[y1:y2:12, x1:x2:16]
            if sample.size == 0:
                return None
            if sample.ndim == 3:
                sample = sample.mean(axis=2)
            return sample.astype(np.float32, copy=False)
        except Exception as error:  # noqa: BLE001
            logger.debug(f'Exploration viewport signature unavailable: {error}')
            return None

    @staticmethod
    def _exploration_viewport_similar(previous, current, tolerance=8.0) -> bool:
        if previous is None or current is None or previous.shape != current.shape:
            return False
        try:
            delta = np.abs(previous - current)
            mean_delta = float(np.mean(delta))
            high_delta_ratio = float(np.mean(delta > 12.0))
            p90_delta = float(np.percentile(delta, 90))
            # MuMu emits a small amount of per-frame noise even on a static
            # map.  P90 and the changed-pixel ratio keep the first frames of a
            # real scroll from being accepted just because most pixels are
            # unchanged.
            return (
                mean_delta <= tolerance
                and p90_delta <= 12.0
                and high_delta_ratio <= 0.14
            )
        except Exception:  # noqa: BLE001
            return False

    def _wait_for_exploration_new_frame(self, previous_marker, timeout=1.0):
        """Wait for a published frame without treating a throttled capture as new."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            self.screenshot()
            marker = self._exploration_frame_marker()
            if marker != previous_marker:
                return marker
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        return previous_marker

    def _wait_for_exploration_swipe_settle(
        self,
        before_marker,
        before_signature,
        retry_count=0,
    ) -> dict:
        """Wait for a real post-swipe viewport and two stable new frames."""
        started = time.monotonic()
        min_deadline = started + self.EXPLORATION_SWIPE_SETTLE_MIN
        deadline = started + self.EXPLORATION_SWIPE_SETTLE_MAX
        previous_marker = before_marker
        previous_signature = None
        after_marker = before_marker
        stable_frames = 0
        new_frames = 0
        viewport_changed = False

        while time.monotonic() < deadline:
            now = time.monotonic()
            if now < min_deadline:
                time.sleep(min(0.05, min_deadline - now))
                continue

            self.screenshot()
            marker = self._exploration_frame_marker()
            if marker == previous_marker:
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
                continue

            signature = self._exploration_viewport_signature(self.device.image)
            new_frames += 1
            after_marker = marker
            if before_signature is not None and signature is not None:
                if not self._exploration_viewport_similar(before_signature, signature):
                    viewport_changed = True
            if self._exploration_viewport_similar(previous_signature, signature):
                stable_frames += 1
            else:
                stable_frames = 1
            previous_marker = marker
            previous_signature = signature
            if stable_frames >= self.EXPLORATION_SWIPE_STABLE_FRAMES:
                break

        stable = stable_frames >= self.EXPLORATION_SWIPE_STABLE_FRAMES
        elapsed = time.monotonic() - started
        self._exploration_last_swipe_settled = stable
        logger.info(
            'EXPLORATION_SWIPE_SETTLE '
            f'swipe_executed=True frame_before={before_marker} '
            f'frame_after={after_marker} viewport_changed={viewport_changed} '
            f'new_frames={new_frames} stable_frames={stable_frames} '
            f'stable={stable} stable_elapsed={elapsed:.3f}s retry={retry_count}'
        )
        return {
            'stable': stable,
            'viewport_changed': viewport_changed,
            'frame_after': after_marker,
            'new_frames': new_frames,
            'stable_frames': stable_frames,
            'elapsed': elapsed,
        }

    def _execute_exploration_swipe(self, swipe_rule, interval=None) -> bool:
        """Execute a map swipe and confirm its post-swipe state once."""
        self._exploration_last_swipe_failure = None
        before_marker = self._exploration_frame_marker()
        before_signature = self._exploration_viewport_signature(self.device.image)
        retry_count = 0

        while True:
            try:
                executed = self.swipe(swipe_rule, interval=interval)
            except GameTooManyClickError as error:
                # The device click guard can reject a retry while the map is
                # still settling. This is recoverable; do not turn it into a
                # task-wide GameStuck restart.
                logger.warning(
                    'EXPLORATION_SWIPE_CONTROL_REJECTED '
                    f'error={error} retry={retry_count}'
                )
                self._exploration_last_swipe_settled = False
                self._exploration_last_swipe_failure = 'control_rejected'
                return False
            if not executed:
                logger.info(
                    'EXPLORATION_SWIPE_SKIPPED '
                    f'reason=interval_or_invalid frame={before_marker}'
                )
                self._exploration_last_swipe_settled = False
                self._exploration_last_swipe_failure = 'skipped'
                return False

            settle = self._wait_for_exploration_swipe_settle(
                before_marker,
                before_signature,
                retry_count=retry_count,
            )
            if settle['stable'] and (settle['viewport_changed'] or retry_count >= self.EXPLORATION_SWIPE_RETRY_LIMIT):
                self._exploration_last_swipe_failure = None
                return True

            if retry_count >= self.EXPLORATION_SWIPE_RETRY_LIMIT:
                logger.warning(
                    'EXPLORATION_SWIPE_UNCONFIRMED '
                    f'frame={settle["frame_after"]} retry={retry_count}'
                )
                self._exploration_last_swipe_failure = 'unconfirmed'
                return False

            retry_count += 1
            logger.warning(
                'EXPLORATION_SWIPE_RETRY '
                f'reason=viewport_unchanged retry={retry_count}'
            )
            before_marker = self._exploration_frame_marker()
            before_signature = self._exploration_viewport_signature(self.device.image)
            interval = None

    def _confirm_exploration_endpoint(self) -> bool:
        """Require two new frames with an endpoint marker and no target."""
        first_marker = self._exploration_frame_marker()
        first_end = self.appear(self.I_SWIPE_END)
        first_target = self.search_up_fight()
        if not first_end or first_target is not None:
            logger.debug(
                'EXPLORATION_ENDPOINT_CANDIDATE '
                f'frame={first_marker} end={first_end} target={first_target is not None}'
            )
            return False

        second_marker = self._wait_for_exploration_new_frame(first_marker, timeout=1.2)
        if second_marker == first_marker:
            logger.warning(
                f'EXPLORATION_ENDPOINT_UNCONFIRMED reason=no_new_frame frame={first_marker}'
            )
            return False
        second_end = self.appear(self.I_SWIPE_END)
        second_target = self.search_up_fight()
        recent_slide_ready = getattr(self, '_exploration_last_swipe_settled', True)
        confirmed = bool(second_end and second_target is None and recent_slide_ready)
        logger.info(
            'EXPLORATION_ENDPOINT_CHECK '
            f'frame_first={first_marker} frame_second={second_marker} '
            f'end_first={first_end} end_second={second_end} '
            f'target_first={first_target is not None} target_second={second_target is not None} '
            f'recent_slide={recent_slide_ready} confirmed={confirmed}'
        )
        return confirmed

    def _clip_exploration_roi_front(self, rule) -> bool:
        """Keep a SIFT-projected exploration ROI inside the current frame."""
        image = getattr(self.device, 'image', None)
        if image is None or not hasattr(image, 'shape'):
            return False
        height, width = image.shape[:2]
        try:
            original = tuple(int(value) for value in rule.roi_front)
            x, y, roi_width, roi_height = original
        except (TypeError, ValueError):
            logger.warning(f'EXPLORATION_UP_ROI_INVALID roi={getattr(rule, "roi_front", None)}')
            return False

        x1 = max(0, min(width, x))
        y1 = max(0, min(height, y))
        x2 = max(x1, min(width, x + roi_width))
        y2 = max(y1, min(height, y + roi_height))
        clipped = (x1, y1, x2 - x1, y2 - y1)
        if clipped[2] <= 0 or clipped[3] <= 0:
            logger.warning(
                f'EXPLORATION_UP_ROI_OUT_OF_BOUNDS roi={original} frame={width}x{height}'
            )
            return False
        if clipped != original:
            logger.warning(
                f'EXPLORATION_UP_ROI_CLIPPED from={original} to={clipped} '
                f'frame={width}x{height}'
            )
            rule.roi_front = list(clipped)
        return True

    def _extra_prepare_button_visible(self) -> bool:
        """Recognize the current exploration client's auto-challenge button."""
        # The same bottom-right ROI contains the main-page "式神录" entry.
        # Reject stable main-page anchors before using the OCR fallback.
        if self._home_scene_visible():
            return False
        if self.ocr_appear(self.O_E_AUTO_CHALLENGE):
            return True
        image = getattr(getattr(self, 'device', None), 'image', None)
        if image is None:
            return False
        # The current skin's OCR sometimes returns a near-miss such as 鲁攻
        # for the fixed button text. The ROI also contains unrelated labels,
        # so the fallback must use an allow-list rather than any OCR result.
        # Accept only the exact label or known near-miss variants. During a
        # real battle the same ROI can contain "普攻", which is not a prepare
        # button and must not affect scene detection.
        cached_ocr = getattr(self, '_ocr_cached', None)
        if callable(cached_ocr):
            text = ''.join(str(cached_ocr(self.O_E_AUTO_CHALLENGE) or '').split())
        else:
            text = ''.join(str(self.O_E_AUTO_CHALLENGE.ocr(image) or '').split())
        accepted_texts = getattr(self, 'EXTRA_PREPARE_TEXTS', BaseExploration.EXTRA_PREPARE_TEXTS)
        return '挑战' in text or text in accepted_texts

    def _home_scene_visible(self) -> bool:
        """Recognize the courtyard or its idle-protection screen."""
        if self.appear(self.I_MAIN_PROTECTION_BACK, threshold=0.65):
            return True
        return self.appear(self.I_CHECK_MAIN) or self.appear(self.I_MAIN_GOTO_EXPLORATION)

    def _abort_unknown_scene(self, context: str, attempts: int) -> None:
        """Stop safely when the exploration state cannot be identified."""
        logger.error(
            'EXPLORATION_UNKNOWN_SCENE_ABORT '
            f'context={context} attempts={attempts} '
            f'limit={self.UNKNOWN_SCENE_LIMIT}'
        )
        raise GamePageUnknownError(
            f'Exploration scene remained unknown in {context} '
            f'after {attempts} consecutive checks'
        )

    def _handle_unknown_scene(self, context: str, consecutive: int) -> int:
        """Bound unknown-page recovery without any blind coordinate click."""
        if self._click_exploration_exit_confirmation():
            logger.info(
                f'EXPLORATION_UNKNOWN_SCENE_RECOVERED context={context} '
                'action=exit_confirmation'
            )
            return 0

        consecutive += 1
        home_visible = self._home_scene_visible()
        logger.warning(
            'EXPLORATION_UNKNOWN_SCENE '
            f'context={context} consecutive={consecutive}/'
            f'{self.UNKNOWN_SCENE_LIMIT} home_or_protection={home_visible} '
            'action=wait_no_click'
        )
        if consecutive >= self.UNKNOWN_SCENE_LIMIT:
            self._abort_unknown_scene(context, consecutive)
        time.sleep(self.UNKNOWN_SCENE_RETRY_DELAY)
        return consecutive

    def _click_extra_prepare_button(self, interval: float = None) -> bool:
        """Click auto-challenge when the current exploration skin has no Prepare label."""
        if self.ocr_appear_click(self.O_E_AUTO_CHALLENGE, interval=interval):
            return True
        if not self._extra_prepare_button_visible():
            return False
        x, y = self.O_E_AUTO_CHALLENGE.coord()
        self.device.click(x, y, control_name=self.O_E_AUTO_CHALLENGE.name)
        logger.info('Click exploration auto-challenge via tolerant OCR')
        return True

    def _discovery_panel_layout_visible(self) -> bool:
        """Cheaply reject ordinary exploration frames before running OCR."""
        image = getattr(getattr(self, 'device', None), 'image', None)
        if image is None or getattr(image, 'ndim', 0) != 3:
            return False
        x, y, width, height = self.DISCOVERY_PANEL_ROI
        panel = image[y:y + height, x:x + width]
        if panel.shape[:2] != (height, width):
            return False
        bright_ratio = float(
            (panel.mean(axis=2) > self.DISCOVERY_PANEL_BRIGHT_THRESHOLD).mean()
        )
        return bright_ratio >= self.DISCOVERY_PANEL_MIN_BRIGHT_RATIO

    def _discovery_panel_visible(self) -> bool:
        """Recognize the discovery modal by layout and its centered title."""
        if not self._discovery_panel_layout_visible():
            return False
        cached_ocr = getattr(self, '_ocr_cached', None)
        if callable(cached_ocr):
            result = cached_ocr(self.O_E_DISCOVERY_TITLE)
        else:
            result = self.O_E_DISCOVERY_TITLE.ocr(self.device.image)
        return result != (0, 0, 0, 0)

    def _dismiss_discovery_panel(self, timeout: float = 3.0) -> bool:
        """Dismiss one discovery modal without touching the covered settings button."""
        if not self._discovery_panel_visible():
            return False

        x, y = self.C_DISCOVERY_DISMISS.coord()
        self.device.click(x, y, control_name=self.C_DISCOVERY_DISMISS.name)
        logger.warning('Discovery location popup detected; click outside modal once')

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.2)
            self.screenshot()
            if not self._discovery_panel_visible():
                logger.info('Discovery location popup dismissed')
                return True

        logger.warning('Discovery location popup did not close within %.1fs', timeout)
        return False

    def is_exploration_world(self) -> bool:
        """Recognize both chapter-panel states of the exploration world."""
        if self.appear(self.I_E_SETTINGS_BUTTON):
            return False
        if self.appear(self.I_CHECK_EXPLORATION):
            return True
        for marker in (self.I_EXP_ARROW_LEFT, self.I_EXP_ARROW_RIGHT):
            if self.appear(marker):
                logger.debug(f'Exploration world recognized by {marker.name}')
                return True
        return False

    def get_current_scene(self, reuse_screenshot: bool = True) -> Scene:
        if not reuse_screenshot:
            self.screenshot()

        if self.is_exploration_world():
            return Scene.WORLD
        elif self.appear(self.I_E_EXPLORATION_CLICK):
            return Scene.ENTRANCE
        elif self._home_scene_visible():
            # Do not let generic battle templates steal the initial home page.
            # ScriptTask will route UNKNOWN through pre_process().
            return Scene.UNKNOWN
        elif self.appear(self.I_E_SETTINGS_BUTTON) or self.appear(self.I_E_AUTO_ROTATE_ON) or self.appear(self.I_E_AUTO_ROTATE_OFF):
            return Scene.MAIN
        elif self.is_in_prepare():
            return Scene.BATTLE_PREPARE
        elif self.is_in_battle():
            return Scene.BATTLE_FIGHTING
        elif self.is_in_room() or self.appear(self.I_CREATE_ENSURE):
            return Scene.TEAM

        logger.info("Unknown scene")
        return Scene.UNKNOWN

    def pre_process(self):
        explorationConfig = self._config
        if explorationConfig.switch_soul_config.enable:
            self.ui_get_current_page()
            if not self.ui_goto(page_shikigami_records):
                raise GameStuckError('Exploration: unable to open shikigami records')
            self.run_switch_soul(explorationConfig.switch_soul_config.switch_group_team)

        if explorationConfig.switch_soul_config.enable_switch_by_name:
            self.ui_get_current_page()
            if not self.ui_goto(page_shikigami_records):
                raise GameStuckError('Exploration: unable to open shikigami records')
            self.run_switch_soul_by_name(explorationConfig.switch_soul_config.group_name,
                                         explorationConfig.switch_soul_config.team_name)

        # 开启加成
        con = self.config.exploration.exploration_config
        if con.buff_gold_50_click or con.buff_gold_100_click or con.buff_exp_50_click or con.buff_exp_100_click:
            self.ui_get_current_page()
            if not self.ui_goto(page_main):
                raise GameStuckError('Exploration: unable to return to main page before buffs')
            self._capture_and_apply_exploration_buffs(con)

        self.ui_get_current_page()
        # 探索页面
        if not self.ui_goto(page_exploration):
            raise GameStuckError('Exploration: unable to open exploration page')

    def post_process(self):
        if getattr(self, '_exploration_exit_endpoint_confirmed', None):
            logger.info(
                'Exploration post-process: skip red-back stability wait after '
                f"confirmed endpoint={self._exploration_exit_endpoint_confirmed}"
            )
            self._exploration_exit_endpoint_confirmed = None
        else:
            self.wait_until_stable(self.I_UI_BACK_RED)
        if self.appear(self.I_UI_BACK_RED):
            self._require_click_workflow(
                self.ui_click_until_disappear(
                    self.I_UI_BACK_RED,
                    timeout=self.CLICK_WORKFLOW_TIMEOUT,
                    max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                ),
                'post_process_close_back',
            )
        self.ui_get_current_page()
        self.ui_goto(page_main)
        self._restore_exploration_buff_states()
        self.set_next_run(task='Exploration', success=True, finish=False)
        raise TaskEnd.completed('Exploration completed')

    @staticmethod
    def _exploration_buff_specs(con):
        return (
            ('gold_50', con.buff_gold_50_click, 'O_GOLD_50'),
            ('gold_100', con.buff_gold_100_click, 'O_GOLD_100'),
            ('exp_50', con.buff_exp_50_click, 'O_EXP_50'),
            ('exp_100', con.buff_exp_100_click, 'O_EXP_100'),
        )

    def _capture_and_apply_exploration_buffs(self, con) -> None:
        if not self.open_buff():
            raise GameStuckError('Exploration: buff panel did not open')
        snapshot = {}
        try:
            for name, enabled, rule_name in self._exploration_buff_specs(con):
                if not enabled:
                    continue
                area = self.get_area(getattr(self, rule_name))
                if area is None:
                    snapshot[name] = self.BUFF_UNAVAILABLE
                else:
                    state, _open_rule, _close_rule = self._read_switch_state(name, area)
                    snapshot[name] = True if state == 'open' else False if state == 'closed' else None
                getattr(self, name)(is_open=True)
        finally:
            self.close_buff()
        self._exploration_buff_snapshot = snapshot
        logger.info(f'EXPLORATION_BUFF_SNAPSHOT states={snapshot!r}')

    def _restore_exploration_buff_states(self) -> bool:
        snapshot = getattr(self, '_exploration_buff_snapshot', None)
        if snapshot is None:
            return True
        if not self.open_buff():
            logger.warning('Exploration buff restore skipped: panel did not open')
            return False
        success = True
        try:
            for name, original_state in snapshot.items():
                if original_state == BaseExploration.BUFF_UNAVAILABLE:
                    logger.info(f'Exploration buff unavailable and unchanged: name={name}')
                    continue
                if original_state is None:
                    logger.warning(f'Exploration buff restore unknown: name={name}')
                    success = False
                    continue
                result = getattr(self, name)(is_open=original_state)
                success = bool(result) and success
        finally:
            self.close_buff()
        if success:
            self._exploration_buff_snapshot = None
        logger.info(f'EXPLORATION_BUFF_RESTORE success={success} states={snapshot!r}')
        return success

    # 打开指定的章节：
    def open_expect_level(self):
        swipeCount = 0
        search_actions = 0
        search_max_actions = self.LEVEL_SEARCH_MAX_SWIPES + 8
        search_deadline = time.monotonic() + self.LEVEL_SEARCH_TIMEOUT
        while 1:
            if time.monotonic() >= search_deadline:
                raise GameStuckError(
                    'Exploration level search_budget_exhausted '
                    f'swipes={swipeCount} timeout={self.LEVEL_SEARCH_TIMEOUT:.1f}s'
                )
            # 探索的 config
            explorationConfig = self.config.exploration

            # 判断有无目标章节
            self.screenshot()
            # 获取当前章节名
            cached_detect = getattr(self, '_detect_cached', None)
            if callable(cached_detect):
                results = cached_detect(self.O_E_EXPLORATION_LEVEL_NUMBER)
            else:
                results = self.O_E_EXPLORATION_LEVEL_NUMBER.detect_and_ocr(self.device.image)
            text1 = [result.ocr_text for result in results]
            # https://github.com/runhey/OnmyojiAutoScript/issues/1540
            text1 = [text.replace("名", "第").replace("书", "第") for text in text1]
            # 判断当前章节有无目标章节
            result = set(text1).intersection({explorationConfig.exploration_config.exploration_level})
            # 有则跳出检测
            if self.appear(self.I_E_EXPLORATION_CLICK) or result and len(result) > 0:
                break
            if search_actions >= search_max_actions:
                BaseExploration._raise_exploration_click_boundary(self,
                    'level_search',
                    reason='action_budget_exhausted',
                    actions=search_actions,
                    timeout=self.LEVEL_SEARCH_TIMEOUT,
                    max_actions=search_max_actions,
                )
            if self.appear_then_click(self.I_UI_CONFIRM, interval=1):
                search_actions += 1
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1):
                search_actions += 1
                continue
            self.device.click_record_clear()
            if self.swipe(self.S_SWIPE_LEVEL_UP):
                search_actions += 1
            swipeCount += 1
            debug_info = f"Swiped {swipeCount} times, current exploration level: {text1}"
            logger.info(debug_info)
            if swipeCount >= self.LEVEL_SEARCH_MAX_SWIPES:
                raise GameStuckError(
                    f"Swiped too many times ({swipeCount}), seems stuck in exploration level selection"
                )
            time.sleep(1)

        # 选中对应章节
        selection_attempts = 0
        selection_actions = 0
        selection_deadline = time.monotonic() + self.LEVEL_SELECTION_TIMEOUT
        while 1:
            selection_attempts += 1
            if (
                selection_attempts > self.LEVEL_SELECTION_MAX_ATTEMPTS
                or time.monotonic() >= selection_deadline
            ):
                raise GameStuckError(
                    'Exploration level selection_budget_exhausted '
                    f'attempts={selection_attempts - 1} '
                    f'timeout={self.LEVEL_SELECTION_TIMEOUT:.1f}s'
                )
            self.screenshot()
            if selection_actions >= self.LEVEL_SELECTION_MAX_ATTEMPTS:
                BaseExploration._raise_exploration_click_boundary(self,
                    'level_selection',
                    reason='action_budget_exhausted',
                    actions=selection_actions,
                    timeout=self.LEVEL_SELECTION_TIMEOUT,
                    max_actions=self.LEVEL_SELECTION_MAX_ATTEMPTS,
                )
            if self.appear_then_click(self.I_UI_CONFIRM, interval=1):
                selection_actions += 1
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1):
                selection_actions += 1
                continue
            self.O_E_EXPLORATION_LEVEL_NUMBER.keyword = explorationConfig.exploration_config.exploration_level
            if self.ocr_appear_click(self.O_E_EXPLORATION_LEVEL_NUMBER):
                selection_actions += 1
                self.wait_until_appear(self.I_E_EXPLORATION_CLICK, wait_time=3)
            if self.appear(self.I_E_EXPLORATION_CLICK):
                break
            if self.is_in_room():
                break

        return True

    # 候补：
    def enter_settings_and_do_operations(self):
        # 打开设置
        deadline = time.monotonic() + 12
        click_attempts = 0
        while time.monotonic() < deadline:
            self.screenshot()
            if self._discovery_panel_visible():
                if self._dismiss_discovery_panel():
                    continue
                raise GameStuckError(
                    'Exploration: discovery location popup blocked settings entry'
                )
            if self._candidate_panel_visible():
                logger.info(
                    'Candidate panel already visible; skip underlying settings click'
                )
                break
            if self.appear(self.I_E_OPEN_SETTINGS):
                logger.info("Open settings")
                break
            if self.is_in_battle():
                logger.warning('Opening settings failed due to now in battle')
                return
            if click_attempts >= 3:
                raise GameStuckError(
                    'Exploration: settings entry was not confirmed after 3 clicks'
                )
            # The settings button moved to the bottom edge in the current
            # exploration skin.  Match the actual image first so the click
            # follows the captured frame instead of a stale fixed point.
            if self.appear_then_click(self.I_E_SETTINGS_BUTTON, interval=2):
                click_attempts += 1
                continue

        else:
            raise GameStuckError('Exploration: settings entry confirmation timeout')

        # 候补出战数量识别
        self.screenshot()
        if not self.appear(self.I_E_OPEN_SETTINGS) and not self._candidate_panel_visible():
            logger.warning('Opening settings failed due to now in battle')
            return
        cached_ocr = getattr(self, '_ocr_cached', None)
        if callable(cached_ocr):
            cu, res, total = cached_ocr(self.O_E_ALTERNATE_NUMBER)
        else:
            cu, res, total = self.O_E_ALTERNATE_NUMBER.ocr(self.device.image)
        if cu >= 40:
            logger.info("Alternate number is enough")
            self._confirm_candidate_panel()
            return
        else:
            self.add_shiki()

    # 添加式神
    def add_shiki(self, screenshot=True):
        if screenshot:
            self.screenshot()
            if not self.appear(self.I_E_OPEN_SETTINGS) and not self._candidate_panel_visible():
                logger.warning('Opening settings failed due to now in battle')
                return

        # 先点候补式神区域，再切换稀有度，避免点击失败
        self.click(self.C_CLICK_STANDBY_TEAM)

        choose_rarity = self._config.exploration_config.choose_rarity
        rarity = ShikigamiClass.N if choose_rarity == ChooseRarity.N else ShikigamiClass.MATERIAL
        fallback_click = (
            self.C_SHIKIGAMI_CLASS_MATERIAL
            if rarity == ShikigamiClass.MATERIAL
            else None
        )
        self.switch_shikigami_class(rarity, fallback_click=fallback_click)

        # 移动至未候补的狗粮
        panel_scroll_deadline = time.monotonic() + 20.0
        panel_scrolls = 0
        while time.monotonic() < panel_scroll_deadline:
            # 慢一点
            time.sleep(0.5)
            self.screenshot()
            if not self._candidate_panel_visible():
                self._log_candidate_panel_lost()
                return
            if self.appear(self.I_E_RATATE_EXSIT):
                self.swipe(self.S_SWIPE_SHIKI_TO_LEFT)
                panel_scrolls += 1
                if panel_scrolls >= 12:
                    raise GameStuckError('Exploration: candidate list first scroll budget exhausted')
            else:
                break
        else:
            raise GameStuckError('Exploration: candidate list first scroll timeout')
        candidate_deadline = time.monotonic() + 30.0
        candidate_attempts = 0
        while time.monotonic() < candidate_deadline:
            # 候补出战数量识别
            self.screenshot()
            if not self.appear(self.I_E_OPEN_SETTINGS) and not self._candidate_panel_visible():
                self._log_candidate_panel_lost()
                return
            cached_ocr = getattr(self, '_ocr_cached', None)
            if callable(cached_ocr):
                cu, res, total = cached_ocr(self.O_E_ALTERNATE_NUMBER)
            else:
                cu, res, total = self.O_E_ALTERNATE_NUMBER.ocr(self.device.image)
            if cu >= 40:
                break
            self.swipe(self.S_SWIPE_SHIKI_TO_LEFT_ONE)
            candidate_attempts += 1
            if candidate_attempts >= 40:
                raise GameStuckError('Exploration: candidate fill budget exhausted')
            # 慢一点
            time.sleep(0.5)
            self.screenshot()
            self.click(self.L_ROTATE_1)
            self.device.click_record_clear()
        else:
            raise GameStuckError('Exploration: candidate fill timeout')

        self._confirm_candidate_panel()

    def _candidate_panel_visible(self) -> bool:
        """Check the candidate modal itself, not the settings button behind it."""
        return (
            self.appear(self.I_E_SURE_BUTTON)
            or self.appear(self.I_E_RATATE_EXSIT)
        )

    def _log_candidate_panel_lost(self) -> None:
        if self.is_in_real_battle(False):
            logger.warning('Candidate panel disappeared and a real battle is visible')
        else:
            logger.warning(
                'Candidate panel is not visible; abort candidate setup without '
                'classifying the modal as battle'
            )

    def _confirm_candidate_panel(self, timeout: float = 8.0) -> bool:
        """Click the candidate modal confirm button once and wait for it to close."""
        deadline = time.monotonic() + timeout
        clicked = False
        while time.monotonic() < deadline:
            self.screenshot()
            if not self.appear(self.I_E_SURE_BUTTON):
                logger.info('Candidate panel confirmation completed')
                return True
            if not clicked:
                x, y = self.I_E_SURE_BUTTON.front_center()
                self.device.click(x, y, control_name=self.I_E_SURE_BUTTON.name)
                logger.info('Click candidate panel confirmation once')
                clicked = True
            time.sleep(0.25)
        logger.warning('Candidate panel confirmation did not disappear within %.1fs', timeout)
        raise GameStuckError('Exploration: candidate panel confirmation timeout')

    def _ensure_auto_rotate_on(self, timeout: float = 8.0) -> bool:
        """Synchronize auto-rotate when templates exist, with a current-skin fallback."""
        deadline = time.monotonic() + timeout
        click_attempts = 0
        max_actions = 3
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(self.I_E_AUTO_ROTATE_ON):
                logger.info('Auto-rotate is enabled')
                return True
            if self.appear(self.I_E_AUTO_ROTATE_OFF):
                if click_attempts >= max_actions:
                    BaseExploration._raise_exploration_click_boundary(self,
                        'ensure_auto_rotate',
                        reason='action_budget_exhausted',
                        actions=click_attempts,
                        timeout=timeout,
                        max_actions=max_actions,
                        target=self.I_E_AUTO_ROTATE_OFF.name,
                    )
                if self.appear_then_click(self.I_E_AUTO_ROTATE_OFF, interval=1):
                    click_attempts += 1
                    logger.info('Clicked auto-rotate off-state to enable it')
                continue
            if self.appear(self.I_E_SETTINGS_BUTTON):
                logger.warning(
                    'Auto-rotate skin templates not detected; exploration settings '
                    'were confirmed, continue with current-skin fallback'
                )
                return True
            time.sleep(0.25)
        logger.warning('Auto-rotate state was not confirmed within %.1fs', timeout)
        BaseExploration._raise_exploration_click_boundary(self,
            'ensure_auto_rotate',
            reason='page_transition_timeout',
            actions=click_attempts,
            timeout=timeout,
            max_actions=max_actions,
            target=self.I_E_AUTO_ROTATE_OFF.name,
        )

    # 找up按钮
    def search_up_fight(self, up_type: UpType = None):
        if up_type is None:
            up_type = self._config.exploration_config.up_type
        
        # 1. 如果选择了特定的 UP 类型 (比如达摩)
        if up_type != UpType.ALL:
            match up_type:
                case UpType.EXP:
                    find_flag = self.I_UP_EXP
                case UpType.COIN:
                    find_flag = self.I_UP_COIN
                case UpType.DARUMAA:
                    find_flag = self.I_UP_DARUMA
                case _:
                    find_flag = self.I_UP_EXP
            
            # 尝试寻找 UP 图标
            if self.appear(find_flag):
                if not self._clip_exploration_roi_front(find_flag):
                    logger.warning(
                        f'Exploration UP candidate skipped: invalid ROI {find_flag.roi_front}'
                    )
                    return None
                # 获取 UP 图标的坐标和中心点
                x, y, w, h = find_flag.roi_front
                x_center, y_center = find_flag.front_center()
                
                logger.info(f'Found up type: {up_type} at {find_flag.roi_front}')

                # 缩小搜索范围 (ROI)
                # 原来左右各扩 160-200，太宽了容易甚至把隔壁怪算进来
                # 现在改为左右各扩 50-80，强制只找垂直线附近的战斗图标
                roi_back_y = max(0, y - 300)      # 向上找300像素
                roi_back_h = y - 20 - roi_back_y  #直到UP图标上方20像素截止
                
                # 左右范围缩窄：防止误触旁边的怪
                roi_back_x = max(0, x - 60)       
                frame_width = self.device.image.shape[1]
                roi_back_w = min(frame_width, x + w + 60) - roi_back_x
                if roi_back_h <= 0 or roi_back_w <= 0:
                    logger.warning(
                        f'Exploration UP candidate skipped: invalid search ROI '
                        f'{roi_back_x, roi_back_y, roi_back_w, roi_back_h}'
                    )
                    return None
                
                logger.info(f'Searching sword icon in narrowed area: {roi_back_x, roi_back_y, roi_back_w, roi_back_h}')
                
                matches = self.I_NORMAL_BATTLE_BUTTON.match_all(
                    image=self.device.image,
                    threshold=0.9,
                    roi=[roi_back_x, roi_back_y, roi_back_w, roi_back_h]
                )
                
                if matches:
                    distances = []
                    for match in matches:
                        # 这里假设 match[1], match[2] 是 x, y
                        x_match = match[1] + match[3] / 2  # 战斗图标中心 X
                        y_match = match[2] + match[4] / 2  # 战斗图标中心 Y
                        
                        # 这样能完美避开“距离很近但属于隔壁怪”的情况
                        x_diff = abs(x_center - x_match)
                        y_diff = abs(y_center - y_match)
                        weighted_distance = (x_diff * 3) + y_diff
                        
                        distances.append((weighted_distance, match))
                    
                    # 按加权距离排序，取最正对着的一个
                    distances.sort(key=lambda x: x[0], reverse=False)
                    match = distances[0][1]
                    
                    roi_front = list(match[1:])  # x,y,w,h
                    self.I_NORMAL_BATTLE_BUTTON.roi_front = roi_front
                    logger.info(f"Target locked: sword at {roi_front} (aligned with UP icon)")
                    return self.I_NORMAL_BATTLE_BUTTON
            else:
                # 没找到 UP 图标，返回 None 让外层逻辑去处理(滑动或退出)
                return None

        # 2. 如果是默认情况 (UpType.ALL)，则只要有怪就打
        if self.appear(self.I_NORMAL_BATTLE_BUTTON):
            return self.I_NORMAL_BATTLE_BUTTON
            
        return None

    def activate_realm_raid(self, con_scrolls, con) -> None:
        # 判断是否开启突破票检测
        if not con_scrolls.scrolls_enable:
            return
        if self.appear(self.I_E_EXPLORATION_CLICK) and self.appear(self.I_EXP_CREATE_TEAM):
            counter_rule = self.O_REALM_RAID_NUMBER1
        else:
            counter_rule = self.O_REALM_RAID_NUMBER
        cached_ocr = getattr(self, '_ocr_cached', None)
        if callable(cached_ocr):
            cu, res, total = cached_ocr(counter_rule)
        else:
            cu, res, total = counter_rule.ocr(self.device.image)
        # 判断突破票数量
        if cu < con_scrolls.scrolls_threshold:
            return

        # 关闭加成
        if self.appear(self.I_RED_CLOSE):
            self._require_click_workflow(
                self.ui_click_until_disappear(
                    self.I_RED_CLOSE,
                    timeout=self.CLICK_WORKFLOW_TIMEOUT,
                    max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                ),
                'activate_realm_raid_close_red',
            )
        if self.appear(self.I_UI_CANCEL):
            self._require_click_workflow(
                self.ui_click_until_disappear(
                    self.I_UI_CANCEL,
                    timeout=self.CLICK_WORKFLOW_TIMEOUT,
                    max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                ),
                'activate_realm_raid_cancel',
            )
        if self.appear(self.I_UI_CANCEL_SAMLL):
            self._require_click_workflow(
                self.ui_click_until_disappear(
                    self.I_UI_CANCEL_SAMLL,
                    timeout=self.CLICK_WORKFLOW_TIMEOUT,
                    max_actions=self.CLICK_WORKFLOW_MAX_ACTIONS,
                ),
                'activate_realm_raid_cancel_small',
            )
        self.ui_goto(page_main)
        if con.buff_gold_50_click or con.buff_gold_100_click or con.buff_exp_50_click or con.buff_exp_100_click:
            self.open_buff()
            self.gold_50(is_open=False)
            self.gold_100(is_open=False)
            self.exp_50(is_open=False)
            self.exp_100(is_open=False)
            self.close_buff()

        # 设置下次执行行时间
        logger.info("RealmRaid and Exploration  set_next_run !")
        next_run = datetime.now() + con_scrolls.scrolls_cd
        self.set_next_run(task='Exploration', success=False, finish=False, target=next_run)
        self.set_next_run(task='RealmRaid', success=False, finish=False, server=False, target=datetime.now())
        self.set_next_run(task='MemoryScrolls', success=False, finish=False, target=datetime.now())
        raise TaskEnd.completed('Exploration completed')

    #
    def battle_limit_reached(self) -> bool:
        if self.minions_cnt >= self._config.exploration_config.minions_cnt:
            logger.info('Minions count is enough, exit')
            return True
        return False

    def exit_after_battle_limit(self) -> bool:
        if not self.battle_limit_reached():
            return False
        self.quit_explore(reason=ExplorationExitReason.BATTLE_LIMIT)
        return True

    def check_exit(self) -> bool:
        # Count is checked before scene-specific exploration work.
        if self.battle_limit_reached():
            return True
        if datetime.now() - self.start_time >= self.limit_time:
            logger.info('Exploration time limit out')
            return True
        self.activate_realm_raid(self._config.scrolls, self._config.exploration_config)
        return False

    def _click_exploration_exit_confirmation(self) -> bool:
        """Click the exploration exit confirmation across legacy and current skins."""
        if self.appear_then_click(self.I_E_EXIT_CONFIRM, interval=0.8):
            self._wait_for_exploration_exit_transition()
            return True
        if not self._exploration_exit_confirmation_ocr_visible():
            return False
        x, y = O_EXPLORATION_EXIT_CONFIRM.coord()
        self.device.click(x, y, control_name=O_EXPLORATION_EXIT_CONFIRM.name)
        logger.info('Click exploration exit confirmation via narrow OCR once')
        self._wait_for_exploration_exit_transition()
        return True

    def _exploration_exit_confirmation_ocr_visible(self) -> bool:
        if not self.exist_image():
            return False
        cached_ocr = getattr(self, '_ocr_cached', None)
        if callable(cached_ocr):
            result = cached_ocr(O_EXPLORATION_EXIT_CONFIRM)
        else:
            result = O_EXPLORATION_EXIT_CONFIRM.ocr(self.device.image)
        return result != (0, 0, 0, 0)

    def _consume_pending_battle_result_overlay(self) -> bool:
        """Consume a result overlay left behind by the battle wait path."""
        visible_check = getattr(self, '_battle_result_continue_visible', None)
        if not callable(visible_check):
            return False
        try:
            if not visible_check():
                return False
        except Exception as error:  # noqa: BLE001
            logger.debug(f'Pending battle result probe failed: {error}')
            return False

        logger.info('Pending battle result overlay detected during exploration exit')
        dismiss = getattr(self, '_dismiss_battle_result_continue', None)
        if callable(dismiss):
            try:
                dismiss(timeout=1.5, max_clicks=2)
            except GameStuckError as error:
                logger.warning(
                    f'Pending battle result overlay was not dismissed: {error}'
                )
            return True

        # Keep compatibility with reduced test/legacy mixins that expose only
        # the safe visual click helper.
        safe_click = getattr(self, '_click_result_continue_bottom', None)
        if callable(safe_click):
            try:
                safe_click()
            except Exception as error:  # noqa: BLE001
                logger.warning(f'Pending battle result safe click failed: {error}')
        return True

    def _wait_for_exploration_exit_transition(self, timeout: float = 5.0) -> bool:
        """Wait until the exit modal is gone and the exploration page is stable."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.screenshot()
            if (
                self.appear(self.I_E_EXIT_CONFIRM)
                or self._exploration_exit_confirmation_ocr_visible()
            ):
                time.sleep(0.2)
                continue
            if self.appear(self.I_E_EXPLORATION_CLICK) or self.is_exploration_world():
                logger.info('Exploration exit transition completed')
                return True
            time.sleep(0.2)
        logger.warning('Exploration exit transition not confirmed within %.1fs', timeout)
        return False

    def quit_explore(
        self,
        timeout: float = 30.0,
        reason: ExplorationExitReason = ExplorationExitReason.UNKNOWN,
    ) -> bool:
        logger.info(f'Quit explore reason={reason.value}')
        deadline = time.monotonic() + max(1.0, float(timeout))
        forced_back_clicked = False
        exit_actions = 0
        max_actions = 10
        # click_yellow_button = 0 #用于保证只点一次左上返回按钮，不要直接触发连点回到主界面
        
        while time.monotonic() < deadline:
            self.screenshot()
            
            # 探索章节标题界面
            # Consume a result overlay before checking exploration endpoints.
            if self._consume_pending_battle_result_overlay():
                exit_actions += 1
                continue
            if self.appear(self.I_UI_BACK_YELLOW) and self.appear(self.I_E_EXPLORATION_CLICK):
                logger.info(
                    f'Exploration exit confirmed reason={reason.value} endpoint=chapter_page'
                )
                self._exploration_exit_endpoint_confirmed = 'chapter_page'
                return True
            # 探索大世界界面
            if self.is_exploration_world():
                logger.info(
                    f'Exploration exit confirmed reason={reason.value} endpoint=world'
                )
                self._exploration_exit_endpoint_confirmed = 'world'
                return True
            if exit_actions >= max_actions:
                BaseExploration._raise_exploration_click_boundary(self,
                    'quit_explore',
                    reason='action_budget_exhausted',
                    actions=exit_actions,
                    timeout=timeout,
                    max_actions=max_actions,
                )
  
            # 防止BOSS打完箱子刚落地，脚本就手快点退出了
            if self.appear_then_click(self.I_BATTLE_REWARD, interval=1.5):
                exit_actions += 1
                logger.info("Found battle reward during exit, picking it up.")
                continue

            if not forced_back_clicked and time.monotonic() + 15 >= deadline:
                logger.warning('Exit transition is slow, force clicking back button once')
                self.click(self.I_UI_BACK_BLUE)
                exit_actions += 1
                forced_back_clicked = True
                continue

            if self._click_exploration_exit_confirmation():
                exit_actions += 1
                continue
            if self.appear_then_click(self.I_BACK_YOLLOW, interval=3.5):
                exit_actions += 1
                continue
            
            if self.appear(self.I_EXPLORATION_TITLE) or self.is_exploration_world():
                continue

        logger.error(
            f'Exploration exit timeout reason={reason.value} timeout={timeout:.1f}s'
        )
        BaseExploration._raise_exploration_click_boundary(self,
            'quit_explore',
            reason='page_transition_timeout',
            actions=exit_actions,
            timeout=timeout,
            max_actions=max_actions,
            detail=f'exit_reason={reason.value}',
        )

    def _hook_special_reward(self) -> bool:
        if self.appear(self.I_STATISTICS) and not self.appear(self.I_REWARD) and not self.appear(self.I_WIN):
            if self.appear_then_click(self.I_CONFIRM_CLOSE_DIFF_SOUL):
                return True
            self.click(self.C_RANDOM_CLICK, interval=1.5)
        return False

    def fire(self, button) -> bool:
        if not self.ui_click_until_disappear(
            button,
            interval=3,
            timeout=15,
            max_actions=5,
        ):
            logger.warning('Exploration battle button did not leave the screen within 15s')
            return False
        self.screenshot()
        if (self.appear(self.I_E_SETTINGS_BUTTON) or
                self.appear(self.I_E_AUTO_ROTATE_ON) or
                self.appear(self.I_E_AUTO_ROTATE_OFF)):
            # 如果还在探索说明，这个是显示滑动导致挑战按钮不在范围内
            logger.warning('Fire button disappear, but still in exploration')
            return False
        success = self.run_general_battle(self._config.general_battle_config)
        if not success:
            logger.warning('Exploration battle did not complete; keep minions count unchanged')
            return False
        self.minions_cnt += 1
        return True

    def wait_world_stable(self) -> bool:
        """
        # 打开右边箭头 and https://github.com/runhey/OnmyojiAutoScript/pull/1589/
        https://github.com/runhey/OnmyojiAutoScript/issues/1588
        @return:
        """
        deadline = time.monotonic() + 20.0
        arrow_actions = 0
        max_actions = 8
        while time.monotonic() < deadline:
            scene = self.get_current_scene(reuse_screenshot=False)
            if scene == Scene.WORLD and self.appear(self.I_EXP_ARROW_RIGHT):
                return True
            if scene == Scene.ENTRANCE:
                logger.warning('World scene unstable, possibly transient frame after paper doll collection')
                return False
            if arrow_actions >= max_actions:
                BaseExploration._raise_exploration_click_boundary(self,
                    'wait_world_stable',
                    reason='action_budget_exhausted',
                    actions=arrow_actions,
                    timeout=20.0,
                    max_actions=max_actions,
                    target=self.I_EXP_ARROW_LEFT.name,
                )
            if self.appear_then_click(self.I_EXP_ARROW_LEFT, interval=2):
                arrow_actions += 1
                continue
        BaseExploration._raise_exploration_click_boundary(self,
            'wait_world_stable',
            reason='page_transition_timeout',
            actions=arrow_actions,
            timeout=20.0,
            max_actions=max_actions,
            target=self.I_EXP_ARROW_LEFT.name,
        )


if __name__ == "__main__":
    from module.config.config import Config
    from module.device.device import Device

    config = Config('oas1')
    device = Device(config)
    t = BaseExploration(config, device)
    t.screenshot()

    # IMAGE_FILE = r"C:\Users\萌萌哒\Desktop\QQ20240818-163854.png"
    # image = load_image(IMAGE_FILE)
    # t.device.image = image
    while 1:
        # print(t.search_up_fight(UpType.EXP))
        t.screenshot()
        print(t.get_current_scene())
    from PIL import Image
    # Image.fromarray(t.device.image.astype(np.uint8)).show()
