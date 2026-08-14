from __future__ import annotations

import hashlib
import random
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

import numpy as np

from module.atom.ocr import RuleOcr
from module.config.utils import convert_to_underscore
from module.exception import GameStuckError
from module.logger import logger
from tasks.Component.CommonPopup.models import (
    PopupActionKind,
    PopupActionResult,
    PopupDetection,
)
from tasks.GlobalGame.config_emergency import CommonPopupMode


class LongIdleBuffPromptStatus(str, Enum):
    ABSENT = 'absent'
    CONFIRMED = 'confirmed'
    FAILED = 'failed'


class LongIdleBuffPromptChoice(str, Enum):
    CONFIRM = 'confirm'
    CANCEL = 'cancel'


@dataclass(frozen=True)
class TaskBuffIntent:
    choice: LongIdleBuffPromptChoice
    task_name: str
    enabled_fields: tuple[str, ...] = ()
    reason: str = ''


@dataclass(frozen=True)
class LongIdleBuffPromptResult:
    status: LongIdleBuffPromptStatus
    choice: LongIdleBuffPromptChoice | None = None
    click_point: tuple[int, int] | None = None
    frame_sha256: str | None = None
    attempts: int = 0
    reason: str = ''


class LongIdleBuffPromptGuard:
    """Dismiss the global 15-minute idle-buff prompt before business clicks."""

    CANVAS_SIZE = (1280, 720)
    PROMPT_TEXT_ROI = (430, 250, 430, 130)
    # Calibrated in canvas coordinates. Rectangles use half-open bounds.
    CONFIRM_SAFE_RECT = (705, 411, 73, 23)
    CANCEL_SAFE_RECT = (502, 411, 66, 23)
    REQUIRED_KEYWORDS = ('15分钟', '未使用加成', '自动关闭', '再次打开')
    CONFIRM_CONTROL_NAME = 'LONG_IDLE_BUFF_PROMPT_CONFIRM'
    CANCEL_CONTROL_NAME = 'LONG_IDLE_BUFF_PROMPT_CANCEL'
    CONTROL_NAME = CONFIRM_CONTROL_NAME
    MAX_RECENT_POINTS = 16

    # Only fields that are actually consumed by task implementations belong
    # here. An unregistered task has no declared buff requirement.
    TASK_BUFF_RULES = {
        'exploration': (
            None,
            (
                'exploration_config.buff_gold_50_click',
                'exploration_config.buff_gold_100_click',
                'exploration_config.buff_exp_50_click',
                'exploration_config.buff_exp_100_click',
            ),
        ),
        'experience_youkai': (
            None,
            (
                'experience_youkai.buff_exp_50_click',
                'experience_youkai.buff_exp_100_click',
            ),
        ),
        'gold_youkai': (
            None,
            (
                'gold_youkai.buff_gold_50_click',
                'gold_youkai.buff_gold_100_click',
            ),
        ),
        'nian': (
            None,
            (
                'nian_config.buff_gold_50_click',
                'nian_config.buff_gold_100_click',
            ),
        ),
        'sougenbi': (
            'sougenbi_config.buff_enable',
            (
                'sougenbi_config.buff_gold_50_click',
                'sougenbi_config.buff_gold_100_click',
                'sougenbi_config.buff_exp_50_click',
                'sougenbi_config.buff_exp_100_click',
            ),
        ),
        'tako': (
            'tako_config.enable',
            (
                'tako_config.buff_gold_50_click',
                'tako_config.buff_gold_100_click',
                'tako_config.buff_exp_50_click',
                'tako_config.buff_exp_100_click',
            ),
        ),
        'secret': (
            None,
            (
                'secret_config.secret_gold_50',
                'secret_config.secret_gold_100',
            ),
        ),
        'hero_test': (
            None,
            (
                'herotest.exp_50_buff_enable_help',
                'herotest.exp_100_buff_enable_help',
            ),
        ),
        'evo_zone': (
            None,
            ('evo_zone_config.soul_buff_enable',),
        ),
        'orochi': (
            None,
            ('orochi_config.soul_buff_enable',),
        ),
    }

    PROMPT_OCR = RuleOcr(
        name='long_idle_buff_prompt',
        mode='Full',
        method='Default',
        roi=PROMPT_TEXT_ROI,
        area=PROMPT_TEXT_ROI,
        keyword='',
    )

    def __init__(self, rng=None):
        self._rng = rng or random.SystemRandom()

    @staticmethod
    def has_prompt_keywords(text: str) -> bool:
        return all(keyword in text for keyword in LongIdleBuffPromptGuard.REQUIRED_KEYWORDS)

    @staticmethod
    def looks_like_prompt(image) -> bool:
        """Cheaply reject ordinary frames before invoking OCR."""
        if not isinstance(image, np.ndarray) or image.ndim != 3:
            return False
        height, width = image.shape[:2]
        if (width, height) != LongIdleBuffPromptGuard.CANVAS_SIZE:
            return False

        # Compute only the fixed crops; this guard runs at every screenshot.
        message = image[250:380:2, 430:860:2, :3].mean(axis=2)
        corner = image[0:180:3, 0:300:3, :3].mean(axis=2)
        modal = image[260:470:2, 440:830:2, :3].mean(axis=2)
        surrounding = image[180:560:3, 300:1000:3, :3].mean(axis=2)

        bright_ratio = float((message > 140).mean())
        corner_mean = float(corner.mean())
        modal_contrast = float(modal.mean() - surrounding.mean())
        return bright_ratio >= 0.72 and corner_mean < 30 and modal_contrast > 35

    @staticmethod
    def frame_sha256(image) -> str | None:
        if not isinstance(image, np.ndarray):
            return None
        contiguous = np.ascontiguousarray(image)
        return hashlib.sha256(contiguous.tobytes()).hexdigest()

    def prompt_visible(self, image) -> bool:
        if not self.looks_like_prompt(image):
            return False
        text = self.PROMPT_OCR.detect_text(image)
        visible = self.has_prompt_keywords(text)
        if visible:
            logger.warning('Long-idle buff prompt detected by stable OCR keywords')
        return visible

    @staticmethod
    def _read_path(root, path: str):
        value = root
        for part in path.split('.'):
            if isinstance(value, dict):
                if part not in value:
                    return False, None
                value = value[part]
                continue
            if not hasattr(value, part):
                return False, None
            value = getattr(value, part)
        return True, value

    @staticmethod
    def _task_name(task) -> str:
        config = getattr(task, 'config', None)
        model = getattr(config, 'model', None)
        running_task = getattr(model, 'running_task', '')
        if not running_task:
            current = getattr(config, 'task', None)
            running_task = getattr(current, 'command', '')
        if not running_task:
            module_parts = type(task).__module__.split('.')
            if len(module_parts) >= 2 and module_parts[0] == 'tasks':
                running_task = module_parts[1]
        return convert_to_underscore(str(running_task or '')).casefold()

    @classmethod
    def resolve_buff_intent(cls, task) -> TaskBuffIntent:
        task_name = cls._task_name(task)
        config = getattr(task, 'config', None)
        model = getattr(config, 'model', None)
        rule = cls.TASK_BUFF_RULES.get(task_name)
        if rule is None:
            return TaskBuffIntent(
                choice=LongIdleBuffPromptChoice.CANCEL,
                task_name=task_name,
                reason='task_has_no_registered_buff_controls',
            )
        if model is None:
            return TaskBuffIntent(
                choice=LongIdleBuffPromptChoice.CANCEL,
                task_name=task_name,
                reason='config_model_missing',
            )

        exists, task_config = cls._read_path(model, task_name)
        if not exists:
            return TaskBuffIntent(
                choice=LongIdleBuffPromptChoice.CANCEL,
                task_name=task_name,
                reason='task_config_missing',
            )

        gate_path, field_paths = rule
        if gate_path is not None:
            gate_exists, gate_value = cls._read_path(task_config, gate_path)
            if not gate_exists:
                return TaskBuffIntent(
                    choice=LongIdleBuffPromptChoice.CANCEL,
                    task_name=task_name,
                    reason='task_buff_gate_missing',
                )
            if not bool(gate_value):
                return TaskBuffIntent(
                    choice=LongIdleBuffPromptChoice.CANCEL,
                    task_name=task_name,
                    reason='task_buff_gate_disabled',
                )

        enabled = []
        for path in field_paths:
            field_exists, field_value = cls._read_path(task_config, path)
            if field_exists and bool(field_value):
                enabled.append(path)
        enabled_fields = tuple(enabled)
        if enabled_fields:
            return TaskBuffIntent(
                choice=LongIdleBuffPromptChoice.CONFIRM,
                task_name=task_name,
                enabled_fields=enabled_fields,
                reason='configured_buff_requested',
            )
        return TaskBuffIntent(
            choice=LongIdleBuffPromptChoice.CANCEL,
            task_name=task_name,
            reason='no_configured_buff_requested',
        )

    @staticmethod
    def _mode(task) -> CommonPopupMode:
        config = getattr(task, 'config', None)
        global_game = getattr(config, 'global_game', None)
        emergency = getattr(global_game, 'emergency', None)
        value = getattr(
            emergency,
            'long_idle_buff_prompt_mode',
            CommonPopupMode.ENFORCE,
        )
        if isinstance(value, CommonPopupMode):
            return value
        return CommonPopupMode(str(value))

    def detect(self, context) -> PopupDetection | None:
        mode = self._mode(context._task)
        if mode is CommonPopupMode.DISABLED:
            return None
        if not self.looks_like_prompt(context.image):
            return None

        started_at = time.perf_counter()
        text = context.ocr_text(self.PROMPT_OCR)
        ocr_duration_ms = (time.perf_counter() - started_at) * 1000
        if not self.has_prompt_keywords(text):
            return None
        intent = self.resolve_buff_intent(context._task)
        safe_rect = (
            self.CONFIRM_SAFE_RECT
            if intent.choice is LongIdleBuffPromptChoice.CONFIRM
            else self.CANCEL_SAFE_RECT
        )
        logger.warning('Long-idle buff prompt detected by stable OCR keywords')
        return PopupDetection(
            popup_id='long_idle_buff_prompt',
            priority=900,
            frame_id=context.frame_id,
            instance_key='long_idle_buff_prompt',
            pixel_sha256=context.pixel_sha256(),
            evidence={
                'mode': mode.value,
                'ocr_text': text,
                'ocr_duration_ms': round(ocr_duration_ms, 3),
                'choice': intent.choice.value,
                'task_name': intent.task_name,
                'enabled_buff_fields': intent.enabled_fields,
                'intent_reason': intent.reason,
                'safe_rect': safe_rect,
                'frame_size': context.size,
            },
        )

    def act(self, context, detection, attempt: int) -> PopupActionResult:
        mode = self._mode(context._task)
        if mode is CommonPopupMode.DETECT_BLOCK:
            return PopupActionResult(
                kind=PopupActionKind.BLOCKED,
                control_name=self.CONTROL_NAME,
                attempt=attempt,
                reason='detect_block_mode',
            )
        if mode is not CommonPopupMode.ENFORCE:
            return PopupActionResult(
                kind=PopupActionKind.FAILED,
                control_name=self.CONTROL_NAME,
                attempt=attempt,
                reason=f'unsupported_mode:{mode.value}',
            )

        task = context._task
        try:
            choice = LongIdleBuffPromptChoice(
                detection.evidence.get('choice', LongIdleBuffPromptChoice.CANCEL.value)
            )
        except ValueError:
            choice = LongIdleBuffPromptChoice.CANCEL
        point_history = getattr(task, '_long_idle_buff_action_points', None)
        if point_history is None:
            point_history = {}
            task._long_idle_buff_action_points = point_history
        recent = point_history.get(choice.value)
        if recent is None:
            recent = deque(maxlen=self.MAX_RECENT_POINTS)
            point_history[choice.value] = recent
        if choice is LongIdleBuffPromptChoice.CONFIRM:
            point = self.choose_confirm_point(recent)
            control_name = self.CONFIRM_CONTROL_NAME
        else:
            point = self.choose_cancel_point(recent)
            control_name = self.CANCEL_CONTROL_NAME
        recent.append(point)
        context.click(point[0], point[1], control_name=control_name)
        logger.warning(
            f'LONG_IDLE_BUFF_PROMPT action={choice.value} '
            f'attempt={attempt}/{self.max_actions} click={point} '
            f'task={detection.evidence.get("task_name", "unknown")} '
            f'frame_sha256={detection.pixel_sha256 or "unavailable"}'
        )
        return PopupActionResult(
            kind=PopupActionKind.CLICKED,
            control_name=control_name,
            click_point=point,
            attempt=attempt,
            reason=f'{choice.value}_clicked',
        )

    @staticmethod
    def on_resolved(task, detection, action) -> None:
        logger.info(
            'LONG_IDLE_BUFF_PROMPT status=resolved '
            f'action={detection.evidence.get("choice", "unknown")} '
            f'attempts={action.attempt} click={action.click_point} '
            f'frame_sha256={detection.pixel_sha256 or "unavailable"}'
        )

    @staticmethod
    def on_abort(task, detection, reason: str) -> None:
        logger.error(
            'LONG_IDLE_BUFF_PROMPT status=failed '
            f'action={detection.evidence.get("choice", "unknown")} '
            f'reason={reason} frame_sha256={detection.pixel_sha256 or "unavailable"}'
        )

    popup_id = 'long_idle_buff_prompt'
    priority = 900
    max_actions = 1
    verify_absent_frames = 2
    required_deadline_capabilities = ('capture', 'ocr')
    # The modal has a visible close transition. Capturing too early can cause
    # a retry to land on the newly exposed business page.
    post_action_delay = 0.8

    def choose_confirm_point(
        self,
        recent_points: Iterable[tuple[int, int]],
    ) -> tuple[int, int]:
        return self._choose_point(self.CONFIRM_SAFE_RECT, recent_points)

    def choose_cancel_point(
        self,
        recent_points: Iterable[tuple[int, int]],
    ) -> tuple[int, int]:
        return self._choose_point(self.CANCEL_SAFE_RECT, recent_points)

    def _choose_point(
        self,
        rect: tuple[int, int, int, int],
        recent_points: Iterable[tuple[int, int]],
    ) -> tuple[int, int]:
        x, y, width, height = rect
        recent = set(recent_points)
        for _ in range(32):
            point = (
                self._rng.randrange(x, x + width),
                self._rng.randrange(y, y + height),
            )
            if point not in recent:
                return point

        for candidate_y in range(y, y + height):
            for candidate_x in range(x, x + width):
                point = (candidate_x, candidate_y)
                if point not in recent:
                    return point
        return x + width // 2, y + height // 2

    def handle(
        self,
        task,
        *,
        max_attempts: int = 1,
        verify_timeout: float = 1.5,
        poll_interval: float = 0.2,
    ) -> LongIdleBuffPromptResult:
        # Compatibility entry point. The handler itself stays single-action;
        # all retries and captures are owned by the shared dispatcher.
        from tasks.Component.CommonPopup.dispatcher import CommonPopupDispatcher

        image = getattr(getattr(task, 'device', None), 'image', None)
        frame_sha256 = self.frame_sha256(image)
        original_limit = self.max_actions
        self.max_actions = 1
        dispatcher = CommonPopupDispatcher(
            (self,),
            max_elapsed=max(1.0, float(verify_timeout) * self.max_actions + 1.0),
            max_rounds=self.max_actions + self.verify_absent_frames + 1,
            max_actions=self.max_actions,
            poll_interval=poll_interval,
            evidence_enabled=False,
        )
        try:
            report = dispatcher.stabilize(task)
        except GameStuckError as exc:
            return LongIdleBuffPromptResult(
                status=LongIdleBuffPromptStatus.FAILED,
                click_point=None,
                frame_sha256=frame_sha256,
                attempts=self.max_actions,
                reason=str(exc),
            )
        finally:
            self.max_actions = original_limit

        if report.actions == 0:
            return LongIdleBuffPromptResult(
                status=LongIdleBuffPromptStatus.ABSENT,
                frame_sha256=frame_sha256,
                reason='prompt_not_detected',
            )
        click_events = [
            event for event in report.events
            if event.get('event') == 'popup_action'
        ]
        point = click_events[-1].get('click_point') if click_events else None
        reason = click_events[-1].get('reason', '') if click_events else ''
        choice = None
        if reason.endswith('_clicked'):
            try:
                choice = LongIdleBuffPromptChoice(reason[:-8])
            except ValueError:
                choice = None
        return LongIdleBuffPromptResult(
            status=LongIdleBuffPromptStatus.CONFIRMED,
            choice=choice,
            click_point=tuple(point) if point else None,
            frame_sha256=frame_sha256,
            attempts=report.actions,
            reason='prompt_disappeared_stably',
        )
