from __future__ import annotations

import re
import time

from module.exception import GameStuckError, TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.battle_outcome import BattleOutcome, record_battle_result
from tasks.XiuxingHexun.script_task import ScriptTask as XiuxingHexunScriptTask
from tasks.XiuxingHexunClimb.assets import XiuxingHexunClimbAssets


class ScriptTask(XiuxingHexunScriptTask):
    """Run 日常训练 challenges with the shared 修行合训 battle pipeline.

    The parent task supplies the bounded page waits, ticket OCR safeguards,
    result recovery, and the GeneralBattle auto-mode fix.  This subclass only
    changes the entry page, right-side ticket counter, challenge click and
    temporary scheduler identity, which keeps removal after the event small.
    """

    I_ACTIVITY_HOME = XiuxingHexunClimbAssets.I_DAILY_HOME
    O_TICKET_COUNT = XiuxingHexunClimbAssets.O_DAILY_TICKET_COUNT
    I_DAILY_ENTRY = XiuxingHexunClimbAssets.I_DAILY_ENTRY
    C_DAILY_ENTRY = XiuxingHexunClimbAssets.C_DAILY_ENTRY
    C_DAILY_CHALLENGE = XiuxingHexunClimbAssets.C_DAILY_CHALLENGE
    I_DAILY_REWARD = XiuxingHexunClimbAssets.I_DAILY_REWARD

    TASK_ID = "XiuxingHexunClimb"
    TASK_PREFIX = "XIUXING_HEXUN_CLIMB"

    def run(self):
        config = self.config.xiuxing_hexun_climb
        if not config.activity_enabled:
            self._stop("activity switch is off")

        max_challenges = int(config.max_challenges)
        completed = 0
        self.screenshot()

        # A worker restart can land in battle or on its result page.  Consume
        # that state before looking at the ticket counter so a ticket is never
        # spent twice.
        if self.is_in_real_battle(False):
            logger.info(f"{self.TASK_PREFIX}_BATTLE_RESUME state=active_battle")
            if not self._resume_active_battle(config):
                self._fail("resumed daily-training battle did not finish with victory", stage="battle")
            completed += 1
            self._continue_to_daily()
        elif self._recover_existing_result():
            completed += 1
            self._continue_to_daily()
        else:
            self._ensure_courtyard_or_activity()

        self._enter_daily_training()

        while max_challenges == 0 or completed < max_challenges:
            # A result transition can be delayed by a low-FPS frame.  Settle
            # it before another ticket read or challenge click.
            # The shared friends template can remain visible on the daily
            # page.  Only treat it as a resume candidate when the daily-home
            # anchor is absent, otherwise a normal post-result page would be
            # misclassified as an active battle.
            if not self._daily_home_anchor_visible() and self.is_in_real_battle(False):
                logger.info(
                    f"{self.TASK_PREFIX}_BATTLE_RESUME state=active_battle "
                    f"completed={completed}"
                )
                if not self._resume_active_battle(config):
                    self._fail(
                        "resumed daily-training battle did not finish with victory",
                        stage="battle",
                    )
                completed += 1
                self._continue_to_daily()
                continue

            if self._recover_existing_result():
                completed += 1
                self._continue_to_daily()
                continue

            if not self._wait_for(self.I_ACTIVITY_HOME, timeout=self.PAGE_TIMEOUT):
                self._fail("日常训练 home missing before challenge", stage="daily_home")

            ticket_count = self._read_ticket_count()
            logger.info(
                f"{self.TASK_PREFIX}_TICKET_COUNT count={ticket_count!r} "
                f"completed={completed} limit={max_challenges}"
            )
            if ticket_count == 0:
                if self._ticket_count_is_stably_zero(initial_count=ticket_count):
                    self._finish("daily-training tickets exhausted", challenges=completed)
                self._fail("daily-training ticket zero was not stable", stage="ticket")
            if ticket_count is None:
                self._fail("daily-training ticket OCR is unreadable; refusing to click", stage="ticket")

            # 日常训练 exposes the named team preset from the activity page
            # itself.  The generic battle component still knows the legacy
            # left-bottom preset button, so apply the reviewed activity panel
            # before spending the ticket and mark it as pre-applied.
            self._prepare_daily_preset(config)
            self._start_daily_challenge()
            result = self.run_general_battle(config=config.general_battle_config)
            outcome = getattr(getattr(self, "last_battle_result", None), "outcome", None)
            logger.info(
                f"{self.TASK_PREFIX}_BATTLE_RESULT count={completed + 1} "
                f"outcome={outcome} success={bool(result)}"
            )
            if outcome != BattleOutcome.VICTORY or not result:
                self._fail(f"daily-training battle failed: {outcome}", stage="battle")
            completed += 1
            self._continue_to_daily()

        self._finish("challenge limit reached", challenges=completed)

    def _prepare_daily_preset(self, config) -> None:
        """Apply the configured named team in the 日常训练 preset panel.

        On the 2301 layout the panel is opened from the activity home (the
        队伍预设 icon at the bottom), before the large 挑战 button is pressed.
        Calling GeneralBattle's legacy preset opener here leaves the task on
        the prepare page and eventually raises ``PresetLookupError``.
        """
        battle_config = config.general_battle_config
        if not bool(getattr(battle_config, "preset_enable", False)):
            self._fail("修行合训爬塔 requires named team preset", stage="preset")

        if not self._wait_for(self.I_ACTIVITY_HOME):
            self._fail("日常训练 home missing before preset", stage="preset")

        if not self.appear(self.I_PRESET_PAGE):
            panel_opened = False
            # The icon sits immediately above a text label.  Even with the
            # narrowed ROI, allow one bounded retry for a dropped low-FPS tap;
            # never escalate the first transient miss into a process restart.
            for attempt in range(1, 3):
                self._required_click(self.C_TEAM_PRESET, timeout=6)
                if self._wait_for(self.I_PRESET_PAGE, timeout=6):
                    panel_opened = True
                    break
                logger.warning(
                    f"{self.TASK_PREFIX}_PRESET_PANEL_RETRY attempt={attempt}"
                )
                if self.is_in_real_battle(False):
                    self._fail(
                        "日常训练预设点击后进入了战斗状态",
                        stage="preset",
                    )
            if not panel_opened:
                self._fail(
                    "日常训练队伍预设面板未打开",
                    stage="preset",
                )

        # The panel remembers the last group.  Verify the exact configured
        # card first; otherwise select 每月活动 and wait for its card to be
        # visible before deploying.
        if not self._wait_for_named_preset_markers(config, timeout=2.5):
            self._select_activity_preset_group(config)

        team_name = str(battle_config.preset_team_name or "").strip()
        normalized_team = re.sub(r"\s+", "", team_name).casefold()
        if normalized_team == "爬塔222":
            self._required_click(self.C_PRESET_TEAM_TOP, timeout=6)
        elif normalized_team == "【修行合训】顶配".casefold():
            self._required_click(self.C_PRESET_TEAM_BOTTOM, timeout=6)
        else:
            self._fail(
                f"日常训练预设队伍未配置受支持的活动卡: {team_name!r}",
                stage="preset",
            )

        self._required_click(self.C_PRESET_DEPLOY, timeout=6)
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            self.screenshot()
            if not self.appear(self.I_PRESET_PAGE) and self.appear(self.I_ACTIVITY_HOME):
                self._battle_preset_preapplied = True
                logger.info(
                    f"{self.TASK_PREFIX}_PRESET_APPLIED "
                    f"group={battle_config.preset_group_name!r} "
                    f"team={battle_config.preset_team_name!r} source=daily_panel"
                )
                return
            time.sleep(0.25)
        self._fail(
            "日常训练队伍预设部署后未回到活动页",
            stage="preset",
        )

    def _preset_markers_match(self, config) -> bool:
        """Use OCR as a fallback for the dynamic shikigami card artwork.

        ``RuleOcr`` in ``Single`` mode requires the whole ROI to equal its
        keyword.  The monthly panel contains two cards in one ROI, so that
        comparison can never reliably distinguish the requested card.  Read
        the bounded card area as a list instead and match the configured name
        as a compact substring; this also tolerates the decorative brackets
        and spaces rendered by different client builds.
        """
        battle_config = config.general_battle_config
        group_name = str(battle_config.preset_group_name or "").strip()
        team_name = str(battle_config.preset_team_name or "").strip()
        group_ok = group_name == "每月活动" and self.appear(self.I_PRESET_PAGE)
        team_ok = bool(team_name) and self.appear(self.I_PRESET_TEAM)
        if not team_ok:
            try:
                image = getattr(getattr(self, "device", None), "image", None)
                detect_and_ocr = getattr(self.O_PRESET_TEAM, "detect_and_ocr", None)
                if image is not None and callable(detect_and_ocr):
                    results = detect_and_ocr(image, logDisplay=False)
                    detected = "".join(
                        str(getattr(item, "ocr_text", "") or "")
                        for item in results
                    )
                    compact_detected = re.sub(r"\s+", "", detected).casefold()
                    compact_target = re.sub(r"\s+", "", team_name).casefold()
                    team_ok = bool(
                        compact_target and compact_target in compact_detected
                    )
                else:
                    # Keep lightweight test doubles and older clients
                    # compatible when the OCR backend is not exposed.
                    team_ok = bool(self.ocr_appear(self.O_PRESET_TEAM))
            except Exception as error:  # noqa: BLE001
                logger.debug(f"{self.TASK_PREFIX}_PRESET_TEAM_OCR_FAILED: {error}")
        logger.info(
            f"{self.TASK_PREFIX}_PRESET_VISIBLE "
            f"group={group_name!r} team={team_name!r} "
            f"group_ok={group_ok} team_ok={team_ok}"
        )
        return group_ok and team_ok

    def _recover_existing_result(self) -> bool:
        """Consume a reward/tap-to-continue page left by a worker restart."""
        if super()._recover_existing_result():
            return True
        if not self._battle_result_continue_visible():
            return False
        try:
            handled = self._dismiss_battle_result_continue(
                timeout=5.0,
                max_clicks=3,
            )
        except GameStuckError:
            raise
        if not handled:
            return False
        record_battle_result(
            self,
            BattleOutcome.VICTORY,
            "recovered daily-training reward continuation after worker restart",
            recovered=True,
        )
        logger.info(
            f"{self.TASK_PREFIX}_BATTLE_RESULT "
            "count=recovered outcome=victory recovered=True"
        )
        return True

    def _enter_daily_training(self) -> None:
        """Navigate from courtyard/武道大会 to the left-side 日常训练 tab."""
        self.screenshot()
        if (
            self.appear(self.I_ACTIVITY_HOME)
            or self._prepare_page_visible()
            or self.appear(self.I_RESULT)
            or self._battle_result_continue_visible()
        ):
            return

        if self.appear(self.I_COURTYARD):
            self._required_click(self.C_COURTYARD_ACCESS)
            if not self._wait_for(self.I_ACTIVITY_HUB):
                self._fail("武道大会页面 did not appear", stage="activity_hub")
        elif self.appear(self.I_COURTYARD_ALT):
            self._required_click(self.C_COURTYARD_ACCESS_ALT)
            if not self._wait_for(self.I_ACTIVITY_HUB):
                self._fail("武道大会页面 did not appear", stage="activity_hub")

        if not self._wait_for(self.I_ACTIVITY_HUB):
            self._fail("修行合训爬塔 activity hub was not detected", stage="activity_hub")
        # The vertical label can be missed by OCR on a low-FPS transition
        # frame.  武道大会 itself is the page guard; use the reviewed,
        # narrow coordinate as a safe fallback when that label is unreadable.
        if not self.appear(self.I_DAILY_ENTRY):
            logger.info(
                f"{self.TASK_PREFIX}_ENTRY_MARKER_FALLBACK "
                "reason=vertical_ocr_unreadable"
            )
        self._required_click(self.C_DAILY_ENTRY)
        if not self._wait_for(self.I_ACTIVITY_HOME):
            self._fail("日常训练 home did not appear", stage="daily_home")

    def _start_daily_challenge(self) -> None:
        """Click the single daily-training challenge control after ticket OCR."""
        if self._prepare_page_visible() or self.is_in_real_battle(False):
            return
        if not self._wait_for(self.I_ACTIVITY_HOME):
            self._fail("日常训练 home disappeared before challenge", stage="challenge")
        self._required_click(self.C_DAILY_CHALLENGE)

        deadline = time.monotonic() + self.PAGE_TIMEOUT
        while time.monotonic() < deadline:
            self.screenshot()
            if self._prepare_page_visible() or self.is_in_real_battle(False):
                return
            if self._battle_result_continue_visible() or self.appear(self.I_RESULT):
                return
            time.sleep(0.25)
        self._fail("日常训练 challenge did not enter prepare/battle", stage="challenge")

    def _daily_reward_visible(self) -> bool:
        """Recognize the daily-training reward modal when generic OCR is faint."""
        try:
            return bool(self.ocr_appear(self.I_DAILY_REWARD))
        except Exception as error:  # noqa: BLE001
            logger.debug(f"{self.TASK_PREFIX}_REWARD_OCR_FAILED: {error}")
            return False

    def _daily_home_anchor_visible(self) -> bool:
        """Check the daily-home OCR without breaking lightweight harnesses."""
        if getattr(getattr(self, "device", None), "image", None) is None:
            return False
        try:
            return bool(self.appear(self.I_ACTIVITY_HOME))
        except Exception as error:  # noqa: BLE001
            logger.debug(f"{self.TASK_PREFIX}_DAILY_HOME_OCR_FAILED: {error}")
            return False

    def _battle_result_continue_visible(self) -> bool:
        """Accept the daily reward modal as a bounded tap-to-continue page.

        This client version renders 获得奖励 with a blank lower strip and can
        lose the generic 点击屏幕继续 OCR at the reduced MuMu frame rate.  The
        shared GeneralBattle continuation handler will then perform its single
        bottom-safe tap, after which the normal result/home guards take over.
        """
        if super()._battle_result_continue_visible():
            return True
        if self._daily_reward_visible():
            logger.info(
                f"{self.TASK_PREFIX}_REWARD_CONTINUE_VISIBLE source=title_ocr"
            )
            return True
        return False

    def _continue_to_daily(self) -> None:
        """Dismiss result continuation until the daily home is truly stable.

        The title can be OCR-visible behind a fading reward overlay.  Requiring
        several fresh, non-battle frames prevents the next iteration from
        clicking 队伍预设 while the previous result is still closing.
        """
        deadline = time.monotonic() + self.PAGE_TIMEOUT
        home_streak = 0
        while time.monotonic() < deadline:
            self.screenshot()
            home_visible = self._daily_home_anchor_visible()
            if home_visible:
                # Check result overlays before accepting the title.  Once the
                # title is visible without an overlay, ignore stale friends
                # artwork and require consecutive fresh home frames instead.
                if self.appear(self.I_RESULT) or self._battle_result_continue_visible():
                    home_streak = 0
                    self._required_click(self.C_CONTINUE)
                    time.sleep(0.35)
                    continue
                home_streak += 1
                if home_streak >= 3:
                    # One final fresh frame guards against a title match from
                    # the outgoing transition being reused by the next loop.
                    self.screenshot()
                    if (
                        self._daily_home_anchor_visible()
                        and not self.appear(self.I_RESULT)
                        and not self._battle_result_continue_visible()
                    ):
                        logger.info(
                            f"{self.TASK_PREFIX}_DAILY_HOME_STABLE frames={home_streak + 1}"
                        )
                        return
            else:
                home_streak = 0
                if self.is_in_real_battle(False):
                    time.sleep(0.35)
                    continue
                if self.appear(self.I_RESULT) or self._battle_result_continue_visible():
                    self._required_click(self.C_CONTINUE)
                    time.sleep(0.35)
                    continue
            time.sleep(0.25)
        self._fail("daily-training result did not return to home", stage="result")

    @staticmethod
    def _parse_ticket_text(raw_text: str | None, source_text: str | None = None) -> int | None:
        """Parse only explicit digits; a stylized O is not exhaustion proof."""
        if raw_text is None or not str(raw_text).strip():
            return None
        text = str(raw_text).strip()
        digits = re.findall(r"\d+", text)
        if not digits:
            return None
        count = int(digits[0])
        if count == 0 and source_text is not None and "0" not in str(source_text):
            return None
        return count

    def _read_ticket_count(self) -> int | None:
        """Read the right-side ticket number and ignore the left stamina."""
        image = getattr(getattr(self, "device", None), "image", None)
        if image is None:
            return None
        source_text = None
        try:
            rule = self.O_TICKET_COUNT
            model = getattr(rule, "model", None)
            raw_reader = getattr(model, "ocr_single_line", None)
            if callable(raw_reader) and hasattr(rule, "roi"):
                roi_image = rule.crop(image, rule.roi)
                roi_image = rule.pre_process(roi_image)
                raw_text, score = raw_reader(roi_image)
                source_text = str(raw_text)
                contains_digit = any(char.isdigit() for char in str(raw_text))
                accepted = score >= rule.score or (score >= rule.min_score and contains_digit)
                if not accepted:
                    return None
                processed = rule.after_process(raw_text)
            else:
                processed = rule.ocr_single(image)
        except Exception as error:  # noqa: BLE001
            logger.debug(f"{self.TASK_PREFIX}_TICKET_OCR_FAILED: {error}")
            return None
        return self._parse_ticket_text(processed, source_text)

    def _finish(self, reason: str, *, challenges: int):
        logger.info(f"{self.TASK_PREFIX}_FINISH reason={reason!r} challenges={challenges}")
        self.set_next_run(task=self.TASK_ID, success=True, finish=True)
        raise TaskEnd.completed(reason, statistics={"challenges": challenges})

    def _stop(self, reason: str) -> None:
        logger.info(f"{self.TASK_PREFIX}_STOP reason={reason!r}")
        raise TaskEnd.stopped(reason, statistics={"challenges": 0})

    def _fail(self, reason: str, *, stage: str = "failure"):
        saver = getattr(getattr(self, "device", None), "save_screenshot", None)
        if callable(saver):
            try:
                saver(genre="xiuxing_hexun_climb_" + stage, interval=0)
            except Exception as error:  # noqa: BLE001
                logger.debug(f"{self.TASK_PREFIX}_EVIDENCE_FAILED stage={stage}: {error}")
        logger.error(f"{self.TASK_PREFIX}_FAILURE stage={stage} reason={reason}")
        raise GameStuckError(reason)
