from __future__ import annotations

import re
import time
from enum import Enum

from module.atom.click import RuleClick
from module.exception import GameStuckError, TaskEnd
from module.logger import logger
from tasks.Component.GeneralBattle.battle_outcome import BattleOutcome, record_battle_result
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.XiuxingHexun.assets import XiuxingHexunAssets
from tasks.XiuxingHexun.availability import xiuxing_hexun_globally_enabled


class XiuxingHexunState:
    COURTYARD = "courtyard"
    ACTIVITY_HUB = "activity_hub"
    ACTIVITY_HOME = "activity_home"
    SEARCH_RESULT = "search_result"
    PRESET = "preset"
    CHALLENGE = "challenge"
    PREPARE = "prepare"
    BATTLE = "battle"
    RESULT = "result"
    NO_TICKET = "no_ticket"


class XiuxingHexunTicketState(str, Enum):
    AVAILABLE = "available"
    EMPTY = "empty"
    UNKNOWN = "unknown"


class XiuxingHexunSearchDecision(str, Enum):
    SEARCH = "search"
    RESUME_OWN_CARD = "resume_own_card"
    EMPTY = "empty"
    UNKNOWN = "unknown"


class ScriptTask(GameUi, GeneralBattle, XiuxingHexunAssets):
    """Run ticket-backed 修行合训 challenges with bounded page transitions."""

    PAGE_TIMEOUT = 20.0
    BATTLE_TIMEOUT = 600.0
    TICKET_ZERO_CONFIRM_SAMPLES = 3
    TICKET_ZERO_CONFIRM_INTERVAL = 0.25
    SEARCH_EMPTY_CONFIRM_TIMEOUT = 3.0

    def battle_wait(self, random_click_swipt_enable: bool, timeout=None) -> bool:
        """Keep this activity's long fights bounded at ten minutes."""
        return GeneralBattle.battle_wait(
            self,
            random_click_swipt_enable,
            timeout=self.BATTLE_TIMEOUT if timeout is None else timeout,
        )

    def run(self):
        config = self.config.xiuxing_hexun
        if not xiuxing_hexun_globally_enabled() or not config.activity_enabled:
            logger.info("XIUXING_HEXUN_DISABLED reason=activity_switch_off")
            self._stop("activity disabled")

        max_challenges = int(config.max_challenges)
        completed = 0
        self.screenshot()
        if self.is_in_real_battle(False):
            logger.info("XIUXING_HEXUN_BATTLE_RESUME state=active_battle")
            if not self._resume_active_battle(config):
                self._fail("修行合训 resumed battle did not finish with victory", stage="battle")
            completed += 1
            self._continue_to_activity()
        else:
            self._ensure_courtyard_or_activity()
        self._enter_activity()

        # A worker can stop after the battle itself has finished but before
        # it records the result.  A task-specific victory template is strong
        # evidence, so settle that page exactly once before searching again.
        if self._recover_existing_result():
            completed += 1
            self._continue_to_activity()

        while max_challenges == 0 or completed < max_challenges:
            ticket_state = self._search()
            if ticket_state == XiuxingHexunTicketState.EMPTY:
                self._finish("tickets exhausted", challenges=completed)
            if ticket_state != XiuxingHexunTicketState.AVAILABLE:
                self._fail("修行合训 ticket state remained unknown")

            self._prepare_named_preset(config)
            self._start_challenge()

            result = self.run_general_battle(config=config.general_battle_config)
            outcome = getattr(getattr(self, "last_battle_result", None), "outcome", None)
            if outcome is None:
                self._fail("修行合训 battle result was not recorded")
            logger.info(
                "XIUXING_HEXUN_BATTLE_RESULT "
                f"count={completed + 1} outcome={outcome} success={bool(result)}"
            )
            if outcome != BattleOutcome.VICTORY or not result:
                self._fail(f"修行合训 battle failed: {outcome}")
            completed += 1
            self._continue_to_activity()

        self._finish("challenge limit reached", challenges=completed)

    def _resume_active_battle(self, config) -> bool:
        try:
            win = self.battle_wait(config.general_battle_config.random_click_swipt_enable)
        except GameStuckError as error:
            record_battle_result(
                self,
                BattleOutcome.ABORTED,
                f"resumed active 修行合训 battle failed: {error}",
                recovered=True,
            )
            raise
        outcome = BattleOutcome.VICTORY if win else BattleOutcome.DEFEAT
        record_battle_result(
            self,
            outcome,
            "resumed active 修行合训 battle settled after worker restart",
            recovered=True,
        )
        return bool(win)

    def _recover_existing_result(self) -> bool:
        if not self.appear(self.I_RESULT):
            return False
        # DeepSeek-13 2.6 (F-8): require a second stable frame before trusting
        # the single victory-title template as a recovered VICTORY.
        self.screenshot()
        if not self.appear(self.I_RESULT):
            logger.info(
                "XIUXING_HEXUN_BATTLE_RESULT recovered victory rejected: title not stable"
            )
            return False
        record_battle_result(
            self,
            BattleOutcome.VICTORY,
            "recovered explicit 修行合训 victory settlement after worker restart",
            recovered=True,
        )
        logger.info("XIUXING_HEXUN_BATTLE_RESULT count=recovered outcome=victory recovered=True")
        return True

    def _finish(self, reason: str, *, challenges: int):
        logger.info(f"XIUXING_HEXUN_FINISH reason={reason!r} challenges={challenges}")
        self.set_next_run(task="XiuxingHexun", success=True, finish=True)
        raise TaskEnd.completed(reason, statistics={"challenges": challenges})

    def _stop(self, reason: str) -> None:
        """Stop a disabled activity without recording a successful run."""
        logger.info(f"XIUXING_HEXUN_STOP reason={reason!r}")
        raise TaskEnd.stopped(reason, statistics={"challenges": 0})

    def _save_failure_evidence(self, stage: str) -> None:
        saver = getattr(getattr(self, "device", None), "save_screenshot", None)
        if not callable(saver):
            return
        try:
            saver(genre=f"xiuxing_hexun_{stage}", interval=0)
        except Exception as error:  # noqa: BLE001
            logger.warning(f"XIUXING_HEXUN_EVIDENCE_FAILED stage={stage}: {error}")

    def _fail(self, reason: str, *, stage: str = "failure"):
        self._save_failure_evidence(stage)
        logger.error(f"XIUXING_HEXUN_FAILURE stage={stage} reason={reason}")
        raise GameStuckError(reason)

    def _wait_for(self, marker, *, timeout: float | None = None) -> bool:
        if marker is None:
            return False
        deadline = time.monotonic() + (timeout or self.PAGE_TIMEOUT)
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(marker):
                return True
            time.sleep(0.25)
        return False

    def _prepare_page_visible(self) -> bool:
        """Accept both reviewed activity assets and GeneralBattle evidence."""
        if self.appear(self.I_PREPARE):
            return True
        try:
            return bool(self._prepare_button_visible())
        except Exception as error:  # noqa: BLE001
            logger.debug(f"XIUXING_HEXUN_PREPARE_DETECT_FAILED: {error}")
            return False

    def _wait_for_prepare(self, *, timeout: float | None = None) -> bool:
        deadline = time.monotonic() + (timeout or self.PAGE_TIMEOUT)
        while time.monotonic() < deadline:
            self.screenshot()
            if self._prepare_page_visible():
                return True
            time.sleep(0.25)
        return False

    def _required_click(self, marker, *, timeout: float | None = None) -> None:
        """Click a detected rule or a reviewed coordinate marker."""
        if marker is None:
            self._fail("修行合训 click marker is unavailable", stage="click")
        deadline = time.monotonic() + (timeout or self.PAGE_TIMEOUT)
        while time.monotonic() < deadline:
            self.screenshot()
            if isinstance(marker, RuleClick):
                if self.click(marker, interval=0.5):
                    return
            elif self.appear_then_click(marker, interval=0.5):
                return
            time.sleep(0.25)
        self._fail(
            f"修行合训 marker not found: {getattr(marker, 'name', marker)}",
            stage="click",
        )

    def _ensure_courtyard_or_activity(self) -> None:
        """Accept courtyard, 武道大会, or an already-open activity page."""
        self.screenshot()
        if (
            self.appear(self.I_ACTIVITY_HOME)
            or self.appear(self.I_ACTIVITY_HUB)
            or self.appear(self.I_CHALLENGE_PAGE)
            or self._prepare_page_visible()
            or self.appear(self.I_RESULT)
        ):
            return
        if self.appear(self.I_COURTYARD) or self.appear(self.I_COURTYARD_ALT):
            return
        self.ui_get_current_page()
        if self.ui_current != page_main and not self.ui_goto(page_main):
            self._fail("修行合训 could not return to courtyard", stage="courtyard")

    def _enter_activity(self) -> None:
        self.screenshot()
        if (
            self.appear(self.I_ACTIVITY_HOME)
            or self.appear(self.I_CHALLENGE_PAGE)
            or self._prepare_page_visible()
            or self.appear(self.I_RESULT)
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
            self._fail("修行合训 activity hub was not detected", stage="activity_hub")
        if not self._wait_for(self.I_ACTIVITY_ENTRY):
            self._fail("修行合训 entry marker was not detected", stage="activity_entry")
        self._required_click(self.C_ACTIVITY_ENTRY)
        if not self._wait_for(self.I_ACTIVITY_HOME):
            self._fail("修行合训 activity home did not appear", stage="activity_home")

    def _read_ticket_count(self) -> int | None:
        """Read only the left/free ticket number; unreadable is not zero."""
        image = getattr(getattr(self, "device", None), "image", None)
        if image is None:
            return None
        source_text: str | None = None
        try:
            rule = self.O_TICKET_COUNT
            model = getattr(rule, "model", None)
            raw_reader = getattr(model, "ocr_single_line", None)
            if callable(raw_reader) and hasattr(rule, "roi"):
                roi_image = rule.crop(image, rule.roi)
                roi_image = rule.pre_process(roi_image)
                raw_text, score = raw_reader(roi_image)
                source_text = str(raw_text)
                contains_digit = any(char.isdigit() for char in raw_text)
                accepted = score >= rule.score or (
                    score >= rule.min_score and contains_digit
                )
                if not accepted or not raw_text:
                    return None
                raw = rule.after_process(raw_text)
            else:
                # Lightweight harnesses and custom OCR implementations may not
                # expose the underlying model. They must signal unreadable with
                # None or an empty string.
                raw = rule.ocr_single(image)
        except Exception as error:  # noqa: BLE001
            logger.debug(f"XIUXING_HEXUN_TICKET_OCR_FAILED: {error}")
            return None
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        digits = re.findall(r"\d+", text)
        if not digits:
            return None
        count = int(digits[0])
        # General OCR cleanup maps the letter O to zero.  That is not strong
        # enough evidence to end this activity as ticket-exhausted.
        if count == 0 and source_text is not None and "0" not in source_text:
            return None
        return count

    def _ticket_state_from_current_frame(self) -> XiuxingHexunTicketState:
        if self.appear(self.I_CHALLENGE_PAGE):
            return XiuxingHexunTicketState.AVAILABLE

        # A generated own card is a valid challenge even when the free ticket
        # count has already reached zero: the ticket was consumed by search.
        own_card_marker = getattr(self, "I_OWN_DISCOVERED_BADGE", None)
        if own_card_marker is not None and self.appear(own_card_marker):
            return XiuxingHexunTicketState.AVAILABLE

        # The ticket ROI is meaningful only on the activity home page.  Do
        # not interpret unrelated digits on preset/result pages as tickets.
        if not self.appear(self.I_ACTIVITY_HOME):
            return XiuxingHexunTicketState.UNKNOWN
        count = self._read_ticket_count()
        if count == 0 and self._ticket_count_is_stably_zero(initial_count=count):
            return XiuxingHexunTicketState.EMPTY
        return XiuxingHexunTicketState.UNKNOWN

    def _activity_page_visible(self, *, allow_search_marker: bool = False) -> bool:
        """Return whether the current frame is still the activity page.

        After the final free ticket is consumed, the activity title matcher
        can briefly miss during the disabled-search transition.  The search
        control is an acceptable secondary anchor for that narrow recovery
        path; it is never used as ticket evidence by itself.
        """
        if self.appear(self.I_ACTIVITY_HOME):
            return True
        if not allow_search_marker:
            return False
        search_marker = getattr(self, "I_SEARCH_AVAILABLE", None)
        return search_marker is not None and self.appear(search_marker)

    def _ticket_count_is_stably_zero(
        self,
        *,
        initial_count: int | None = None,
        allow_search_marker: bool = False,
    ) -> bool:
        """Require repeated zero reads without assuming ticket counts decrease.

        A successful challenge can occasionally grant another ticket, and OCR
        can misread a digit.  Therefore this check only confirms repeated zero
        while the activity home remains visible; it never compares readings
        against an earlier count or rejects an increase.
        """
        readings: list[int | None] = []
        if initial_count is not None:
            readings.append(initial_count)

        sample_limit = int(
            getattr(self, "TICKET_ZERO_CONFIRM_SAMPLES", ScriptTask.TICKET_ZERO_CONFIRM_SAMPLES)
        )
        sample_interval = float(
            getattr(
                self,
                "TICKET_ZERO_CONFIRM_INTERVAL",
                ScriptTask.TICKET_ZERO_CONFIRM_INTERVAL,
            )
        )
        while len(readings) < sample_limit:
            if readings:
                time.sleep(sample_interval)
                self.screenshot()
            page_visible = getattr(self, "_activity_page_visible", None)
            if callable(page_visible):
                visible = page_visible(allow_search_marker=allow_search_marker)
            else:
                visible = self.appear(self.I_ACTIVITY_HOME)
            if not visible:
                break
            reading = self._read_ticket_count()
            readings.append(reading)
            if reading != 0:
                break

        confirmed = (
            len(readings) == sample_limit
            and all(reading == 0 for reading in readings)
        )
        logger.info(
            "XIUXING_FREE_TICKET_ZERO_CONFIRM "
            f"readings={readings!r} confirmed={confirmed}"
        )
        return confirmed

    @staticmethod
    def _choose_search_decision(
        *, search_available: bool, own_card_visible: bool, ticket_count: int | None
    ) -> XiuxingHexunSearchDecision:
        """Apply the activity's search-first and own-card-only rule.

        The button's visible state is the primary evidence.  Ticket OCR is
        only used to prove exhaustion after neither a usable search button nor
        a ``自己发现`` card is present.
        """
        if search_available:
            return XiuxingHexunSearchDecision.SEARCH
        if own_card_visible:
            return XiuxingHexunSearchDecision.RESUME_OWN_CARD
        if ticket_count == 0:
            return XiuxingHexunSearchDecision.EMPTY
        return XiuxingHexunSearchDecision.UNKNOWN

    def _open_own_card(self) -> XiuxingHexunTicketState:
        own_card_marker = getattr(self, "I_OWN_DISCOVERED_BADGE", None)
        if own_card_marker is None or not self.appear(own_card_marker):
            self._fail(
                "修行合训 left card is not marked 自己发现; teammate cards are ignored",
                stage="search",
            )
        logger.info("XIUXING_HEXUN_OWN_CARD action=challenge")
        self._required_click(self.C_OWN_CARD)
        if not self._wait_for(self.I_CHALLENGE_PAGE):
            self._fail(
                "修行合训 自己发现 card did not open challenge page",
                stage="challenge",
            )
        return XiuxingHexunTicketState.AVAILABLE

    def _confirm_empty_after_search(self, own_marker) -> bool:
        """Treat a no-result search as empty only with fresh zero evidence.

        The disabled 搜寻 control can still match its visual template after
        the last free ticket is consumed.  Re-read the activity home after
        that click instead of trusting the button template alone.  A visible
        own card always wins, and any non-zero or unstable OCR reading keeps
        this path as a failure rather than spending another resource type.
        """
        search_marker = getattr(self, "I_SEARCH_AVAILABLE", None)
        deadline = time.monotonic() + float(
            getattr(
                self,
                "SEARCH_EMPTY_CONFIRM_TIMEOUT",
                ScriptTask.SEARCH_EMPTY_CONFIRM_TIMEOUT,
            )
        )
        while time.monotonic() < deadline:
            self.screenshot()
            home_visible = self.appear(self.I_ACTIVITY_HOME)
            search_visible = search_marker is not None and self.appear(search_marker)
            own_visible = own_marker is not None and self.appear(own_marker)
            count = self._read_ticket_count()
            logger.info(
                "XIUXING_SEARCH_EMPTY_CONFIRM "
                f"home={home_visible} search={search_visible} "
                f"own={own_visible} count={count!r}"
            )
            if own_visible:
                return False
            if (home_visible or search_visible) and count == 0:
                return self._ticket_count_is_stably_zero(
                    initial_count=count,
                    allow_search_marker=True,
                )
            # DeepSeek-14 O14-3: fail-closed — count=None ('O' misread or OCR
            # failure) is NEVER exhaustion evidence. Only an explicit stable
            # zero, or a dedicated disabled-search visual (OAS-EXHAUST-001,
            # template capture pending) may complete the activity.
            time.sleep(0.25)
        return False

    def _search(self) -> XiuxingHexunTicketState:
        if self.appear(self.I_CHALLENGE_PAGE):
            logger.info("XIUXING_HEXUN_SEARCH_DECISION decision=existing_challenge_page")
            return XiuxingHexunTicketState.AVAILABLE
        if self._prepare_page_visible():
            logger.info("XIUXING_HEXUN_SEARCH_DECISION decision=existing_prepare_page")
            return XiuxingHexunTicketState.AVAILABLE
        if not self._wait_for(self.I_ACTIVITY_HOME):
            self._fail("修行合训 activity home missing before search", stage="search")

        ticket_count = self._read_ticket_count()
        search_marker = getattr(self, "I_SEARCH_AVAILABLE", None)
        search_available = search_marker is not None and self.appear(search_marker)
        own_marker = getattr(self, "I_OWN_DISCOVERED_BADGE", None)
        own_card_visible = own_marker is not None and self.appear(own_marker)
        decision = self._choose_search_decision(
            search_available=search_available,
            own_card_visible=own_card_visible,
            ticket_count=ticket_count,
        )
        logger.info(
            "XIUXING_HEXUN_SEARCH_DECISION "
            f"decision={decision.value} ticket_count={ticket_count!r} "
            f"search_available={search_available} own_card={own_card_visible}"
        )

        if decision == XiuxingHexunSearchDecision.EMPTY:
            if not self._ticket_count_is_stably_zero(initial_count=ticket_count):
                self._fail(
                    "修行合训 ticket OCR zero was not stable; refusing to infer exhaustion",
                    stage="search",
                )
            # This is the only normal completion path for resource exhaustion.
            return XiuxingHexunTicketState.EMPTY
        if decision == XiuxingHexunSearchDecision.RESUME_OWN_CARD:
            return self._open_own_card()
        if decision != XiuxingHexunSearchDecision.SEARCH:
            self._fail(
                "修行合训 search unavailable and no 自己发现 card was found",
                stage="search",
            )

        self._required_click(self.C_SEARCH)
        deadline = time.monotonic() + self.PAGE_TIMEOUT
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(self.I_CHALLENGE_PAGE):
                return XiuxingHexunTicketState.AVAILABLE
            if own_marker is not None and self.appear(own_marker):
                # 搜寻只生成左侧卡片，必须再点开自己发现的卡片。
                return self._open_own_card()
            time.sleep(0.25)

        if self._confirm_empty_after_search(own_marker):
            logger.info(
                "XIUXING_HEXUN_SEARCH_DECISION "
                "decision=empty_after_search_no_result"
            )
            return XiuxingHexunTicketState.EMPTY
        self._fail(
            "修行合训 search did not produce a 自己发现 card or challenge page",
            stage="search",
        )

    def _preset_markers_match(self, config) -> bool:
        group_name = str(config.general_battle_config.preset_group_name or "").strip()
        team_name = str(config.general_battle_config.preset_team_name or "").strip()
        # The bundled OCR model is not a reliable verifier for this game's
        # stylized preset font.  Reviewed templates are safer here and still
        # reject a renamed or stale card before the deploy click.
        group_ok = group_name == "每月活动" and self.appear(self.I_PRESET_PAGE)
        team_ok = team_name == "【修行合训】顶配" and self.appear(self.I_PRESET_TEAM)
        logger.info(
            "XIUXING_HEXUN_PRESET_VISIBLE "
            f"group={group_name!r} team={team_name!r} "
            f"group_ok={group_ok} team_ok={team_ok}"
        )
        return group_ok and team_ok

    def _wait_for_named_preset_markers(self, config, timeout: float = 2.5) -> bool:
        """Debounce the direct activity preset page before selecting a fallback."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._preset_markers_match(config):
                return True
            time.sleep(0.25)
            self.screenshot()
        return False

    def _select_legacy_named_preset_fallback(self, config) -> None:
        """Select team and soul presets by name when the direct card is stale.

        The activity shortcut remembers the last visible team card.  If that
        card is not the configured team, use the shared name selector instead
        of deploying whatever happened to be selected when the page opened.
        """
        battle_config = config.general_battle_config
        group_name = battle_config.preset_group_name
        team_name = battle_config.preset_team_name
        logger.info(
            "XIUXING_HEXUN_PRESET_FALLBACK "
            f"source=general_name_selector group={group_name!r} team={team_name!r}"
        )
        try:
            self._switch_preset_team_by_name(
                group_name,
                team_name,
                page_already_open=True,
            )
            if not self._wait_for(self.I_CHALLENGE_PAGE):
                self._fail(
                    "修行合训 named team selector did not return to challenge",
                    stage="preset",
                )

            # Team and soul presets are separate controls in this activity's
            # shortcut. Reopen the same page and apply the named soul preset
            # before the challenge button is allowed to proceed.
            self._required_click(self.C_TEAM_PRESET, timeout=6)
            if not self._wait_for(self.I_PRESET_PAGE, timeout=6):
                self._fail(
                    "修行合训 could not reopen preset page for soul preset",
                    stage="preset",
                )
            self._switch_preset_soul_by_name(
                group_name,
                team_name,
                page_already_open=True,
            )
        except GameStuckError:
            raise
        except Exception as error:  # noqa: BLE001
            self._fail(f"修行合训 named preset fallback failed: {error}", stage="preset")

        if not self._wait_for(self.I_CHALLENGE_PAGE):
            self._fail(
                "修行合训 named soul selector did not return to challenge",
                stage="preset",
            )
        self._battle_preset_preapplied = True
        logger.info(
            "XIUXING_HEXUN_PRESET_APPLIED "
            f"group={group_name!r} team={team_name!r} source=general_name_selector"
        )

    def _select_activity_preset_group(self, config) -> None:
        """Select the configured group in the activity-specific panel."""
        battle_config = config.general_battle_config
        logger.info(
            "XIUXING_HEXUN_PRESET_GROUP_SELECT "
            f"group={battle_config.preset_group_name!r} source=activity_panel"
        )
        if not self.appear(self.I_PRESET_PAGE):
            self._fail("activity preset panel did not show the monthly group", stage="preset")
        for attempt in range(2):
            self._required_click(self.C_PRESET_GROUP_MONTHLY, timeout=6)
            if self._wait_for_named_preset_markers(config, timeout=6):
                logger.info(
                    "XIUXING_HEXUN_PRESET_GROUP_SELECTED "
                    f"attempt={attempt + 1} team={battle_config.preset_team_name!r}"
                )
                return
            logger.warning(
                "XIUXING_HEXUN_PRESET_GROUP_RETRY "
                f"attempt={attempt + 1} reason=target_team_card_missing"
            )
        self._fail(
            "configured team card did not appear after selecting monthly group",
            stage="preset",
        )

    def _prepare_named_preset(self, config) -> None:
        battle_config = config.general_battle_config
        if not battle_config.preset_enable:
            self._fail("修行合训 requires named team preset", stage="preset")

        if self._prepare_page_visible():
            logger.info("XIUXING_HEXUN_PRESET_RESUME state=existing_prepare_page")
            self._battle_preset_preapplied = True
            return

        if not self._wait_for(self.I_CHALLENGE_PAGE):
            self._fail("修行合训 challenge page did not appear", stage="challenge")

        # Current client exposes the named card directly from the challenge
        # page.  The name check prevents a stale or renamed card from being
        # deployed by accident.
        direct_preset_opened = False
        for attempt in range(2):
            if not self.appear(self.I_CHALLENGE_PAGE):
                break
            self._required_click(self.C_TEAM_PRESET, timeout=6)
            if self._wait_for(self.I_PRESET_PAGE, timeout=6):
                direct_preset_opened = True
                break
            logger.warning(
                "XIUXING_HEXUN_PRESET_OPEN_RETRY "
                f"attempt={attempt + 1} reason=direct_preset_page_missing"
            )

        if direct_preset_opened:
            if self._wait_for_named_preset_markers(config):
                self._required_click(self.C_PRESET_DEPLOY)
                if not self._wait_for(self.I_CHALLENGE_PAGE):
                    self._fail(
                        "修行合训 preset deploy did not return to challenge",
                        stage="preset",
                    )
                self._battle_preset_preapplied = True
                logger.info(
                    "XIUXING_HEXUN_PRESET_APPLIED "
                    f"group={battle_config.preset_group_name!r} "
                    f"team={battle_config.preset_team_name!r} source=activity_card"
                )
                return

            self._select_activity_preset_group(config)
            self._required_click(self.C_PRESET_DEPLOY)
            if not self._wait_for(self.I_CHALLENGE_PAGE):
                self._fail(
                    "preset deploy did not return to challenge",
                    stage="preset",
                )
            self._battle_preset_preapplied = True
            logger.info(
                "XIUXING_HEXUN_PRESET_APPLIED "
                f"group={battle_config.preset_group_name!r} "
                f"team={battle_config.preset_team_name!r} source=activity_group_select"
            )
            return

        # Fallback for clients whose challenge page routes to 式神录 first.
        # This reuses the common named-preset and soul-wear implementation,
        # while the current 2301 layout uses the direct card above.
        try:
            self.preapply_preset_team_from_records(
                battle_config.preset_group_name,
                battle_config.preset_team_name,
            )
            soul_switch = getattr(self, "_switch_preset_soul_by_name", None)
            if not callable(soul_switch):
                self._fail("修行合训 soul preset component is unavailable", stage="preset")
            soul_switch(
                battle_config.preset_group_name,
                battle_config.preset_team_name,
            )
        except GameStuckError:
            raise
        except Exception as error:  # noqa: BLE001
            self._fail(f"修行合训 named preset failed: {error}", stage="preset")
        if not self._wait_for(self.I_CHALLENGE_PAGE):
            self._fail("修行合训 named preset did not return to challenge", stage="preset")

    def _start_challenge(self) -> None:
        # A failed/restarted worker may be attached to the already-open
        # preparation page.  Let GeneralBattle own that transition instead of
        # navigating back and risking a duplicate challenge.
        if self._prepare_page_visible():
            logger.info("XIUXING_HEXUN_PREPARE_RESUME state=existing_prepare_page")
            return
        if not self._wait_for(self.I_CHALLENGE_PAGE):
            self._fail("修行合训 challenge entry missing", stage="challenge")
        self._required_click(self.C_START_CHALLENGE)
        if not self._wait_for_prepare(timeout=self.PAGE_TIMEOUT):
            self._fail("修行合训 battle preparation did not appear", stage="prepare")

    def _continue_to_activity(self) -> None:
        deadline = time.monotonic() + self.PAGE_TIMEOUT
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(self.I_ACTIVITY_HOME):
                return
            if self.appear(self.I_RESULT) or self.ocr_appear(self.O_RESULT_CONTINUE):
                self._required_click(self.C_CONTINUE)
                continue
            time.sleep(0.25)
        self._fail(
            "修行合训 result continuation did not return to activity home",
            stage="result",
        )
