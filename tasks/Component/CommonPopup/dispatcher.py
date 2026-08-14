from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from module.exception import GameStuckError
from module.logger import logger
from tasks.Component.CommonPopup.evidence import CommonPopupEvidenceRecorder
from tasks.Component.CommonPopup.models import (
    PopupActionKind,
    PopupDispatchReport,
    PopupDispatchStatus,
    PopupFrameContext,
)


@dataclass
class _PendingResolution:
    handler: object
    detection: object
    action: object
    absent_frames: int = 0


class CommonPopupDispatcher:
    """Bounded, fail-closed orchestration for truly global popup overlays."""

    EXPECTED_SIZE = (1280, 720)

    def __init__(
        self,
        handlers: Iterable[object],
        *,
        max_elapsed: float = 6.0,
        max_rounds: int = 6,
        max_actions: int = 4,
        poll_interval: float = 0.2,
        evidence_root: Path | None = None,
        evidence_enabled: bool = True,
        time_fn=None,
        sleep_fn=None,
    ):
        self.handlers = tuple(sorted(
            handlers,
            key=lambda item: int(getattr(item, 'priority', 0)),
            reverse=True,
        ))
        self.max_elapsed = float(max_elapsed)
        self.max_rounds = max(1, int(max_rounds))
        self.max_actions = max(1, int(max_actions))
        self.poll_interval = max(0.0, float(poll_interval))
        self.evidence_root = evidence_root
        self.evidence_enabled = bool(evidence_enabled)
        self._time = time_fn or time.monotonic
        self._sleep = sleep_fn or time.sleep

    def capture_and_stabilize(
        self,
        task,
        *,
        capture=None,
        capture_deadline_capable: bool = True,
    ) -> PopupDispatchReport:
        started_at = self._time()
        deadline_at = started_at + self.max_elapsed
        self._capture_raw(task, capture, deadline_at)
        return self.stabilize(
            task,
            started_at=started_at,
            deadline_at=deadline_at,
            capture=capture,
            capture_deadline_capable=capture_deadline_capable,
        )

    def _capture_raw(self, task, capture, deadline_at: float) -> None:
        if self._time() >= deadline_at:
            raise GameStuckError('Common popup budget_exhausted before screenshot')
        runner = getattr(task, '_capture_common_popup_frame', None)
        if callable(runner):
            if capture is None:
                capture = getattr(task.device, 'screenshot')
            runner(deadline=deadline_at, capture=capture)
        elif capture is not None:
            capture()
        else:
            task.device.screenshot()
        if self._time() >= deadline_at:
            raise GameStuckError('Common popup budget_exhausted during screenshot')

    @staticmethod
    def _deadline_capabilities(
        task,
        capture_deadline_capable: bool | None,
    ) -> frozenset[str]:
        capabilities = {'handler'}
        if capture_deadline_capable is None:
            device_config = getattr(
                getattr(getattr(task.config, 'script', None), 'device', None),
                'screenshot_method',
                '',
            )
            method = getattr(device_config, 'value', device_config)
            capture_deadline_capable = str(method).lower() == 'nemu_ipc'
        if capture_deadline_capable:
            capabilities.add('capture')
        if callable(getattr(task, '_common_popup_ocr_text', None)):
            capabilities.add('ocr')
        elif not hasattr(task, '_common_popup_ocr_deadline_capable'):
            # Lightweight test and legacy adapters execute OCR synchronously
            # inside the same bounded call chain.
            capabilities.add('ocr')
        elif bool(getattr(task, '_common_popup_ocr_deadline_capable')):
            capabilities.add('ocr')
        return frozenset(capabilities)

    @classmethod
    def _frame_invalid_reason(cls, context: PopupFrameContext) -> str | None:
        if context.size != cls.EXPECTED_SIZE:
            return f'frame_size_invalid:{context.size!r}'
        image = context.image
        if not isinstance(image, np.ndarray) or image.ndim != 3:
            return 'frame_image_invalid'
        # A sparse sample catches blank emulator buffers without adding a
        # full-frame scan to every ordinary screenshot.
        sample = image[::16, ::16, :3]
        if sample.size == 0 or float(sample.mean()) <= 1.0:
            return 'frame_black'
        return None

    @staticmethod
    def _event(event_name: str, **fields) -> dict:
        return {'event': event_name, **fields}

    @staticmethod
    def _log(level: str, event: dict) -> None:
        message = 'COMMON_POPUP ' + json.dumps(
            event,
            ensure_ascii=False,
            separators=(',', ':'),
            default=str,
        )
        getattr(logger, level)(message)

    def _report(
        self,
        status: PopupDispatchStatus,
        *,
        events: list[dict],
        rounds: int,
        actions: int,
        started_at: float,
        context: PopupFrameContext,
        reason: str,
        recorder: CommonPopupEvidenceRecorder,
    ) -> PopupDispatchReport:
        report = PopupDispatchReport(
            status=status,
            events=events,
            rounds=rounds,
            actions=actions,
            elapsed_ms=(self._time() - started_at) * 1000,
            final_frame_id=context.frame_id,
            reason=reason,
            evidence_event_id=recorder.event_id,
        )
        recorder.finish(report)
        return report

    def _fail(
        self,
        task,
        *,
        status: PopupDispatchStatus,
        events: list[dict],
        rounds: int,
        actions: int,
        started_at: float,
        context: PopupFrameContext,
        reason: str,
        recorder: CommonPopupEvidenceRecorder,
        pending: dict[tuple[str, str], _PendingResolution],
    ):
        for item in pending.values():
            callback = getattr(item.handler, 'on_abort', None)
            if callable(callback):
                try:
                    callback(task, item.detection, reason)
                except Exception as exc:
                    callback_event = self._event(
                        'abort_callback_error',
                        popup_id=item.detection.popup_id,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    events.append(callback_event)
                    recorder.record_event(callback_event)
                    self._log('error', callback_event)
        report = self._report(
            status,
            events=events,
            rounds=rounds,
            actions=actions,
            started_at=started_at,
            context=context,
            reason=reason,
            recorder=recorder,
        )
        task._last_popup_dispatch_report = report
        event = self._event(
            'dispatch_failed',
            status=status.value,
            reason=reason,
            rounds=rounds,
            actions=actions,
            final_frame_id=context.frame_id,
            evidence_event_id=recorder.event_id,
        )
        self._log('error', event)
        raise GameStuckError(
            f'Common popup dispatcher {status.value}: {reason}; '
            f'rounds={rounds}, actions={actions}, frame_id={context.frame_id}'
        )

    def _capture_next(
        self,
        task,
        previous: PopupFrameContext,
        recorder: CommonPopupEvidenceRecorder,
        *,
        phase: str,
        deadline_at: float,
        capture=None,
        deadline_capabilities: frozenset[str],
        delay: float | None = None,
    ) -> PopupFrameContext:
        settle_delay = self.poll_interval if delay is None else max(0.0, float(delay))
        if settle_delay:
            remaining = deadline_at - self._time()
            if remaining <= 0 or settle_delay >= remaining:
                raise GameStuckError('Common popup budget_exhausted before settle delay')
            self._sleep(settle_delay)
        self._capture_raw(task, capture, deadline_at)
        current = PopupFrameContext.from_task(
            task,
            deadline_at=deadline_at,
            deadline_capabilities=deadline_capabilities,
            time_fn=self._time,
        )
        if current.frame_id <= previous.frame_id:
            raise GameStuckError(
                f'Common popup screenshot did not advance frame_id: '
                f'{previous.frame_id} -> {current.frame_id}'
            )
        if current.device_identity != previous.device_identity:
            raise GameStuckError(
                'Common popup screenshot device identity changed: '
                f'{previous.device_identity!r} -> {current.device_identity!r}'
            )
        invalid_reason = self._frame_invalid_reason(current)
        if invalid_reason is not None:
            # Size stays fail-closed on purpose: absolute-pixel popup ROIs are
            # only trustworthy at the 1280x720 contract (DeepSeek-13 2.5 keeps
            # the existing test-enshrined behavior).
            raise GameStuckError(
                f'Common popup screenshot invalid: {invalid_reason}'
            )
        recorder.record_frame(current, phase=phase)
        return current

    def stabilize(
        self,
        task,
        *,
        started_at: float | None = None,
        deadline_at: float | None = None,
        capture=None,
        capture_deadline_capable: bool | None = None,
    ) -> PopupDispatchReport:
        if started_at is None:
            started_at = self._time()
        if deadline_at is None:
            deadline_at = started_at + self.max_elapsed
        rounds = 0
        actions = 0
        handled_any = False
        events: list[dict] = []
        attempts: dict[tuple[str, str], int] = {}
        pending: dict[tuple[str, str], _PendingResolution] = {}
        deadline_capabilities = self._deadline_capabilities(
            task,
            capture_deadline_capable,
        )
        context = PopupFrameContext.from_task(
            task,
            deadline_at=deadline_at,
            deadline_capabilities=deadline_capabilities,
            time_fn=self._time,
        )
        recorder = CommonPopupEvidenceRecorder(
            root=self.evidence_root,
            enabled=self.evidence_enabled,
        )

        initial_invalid_reason = self._frame_invalid_reason(context)
        if initial_invalid_reason is not None:
            reason = f'initial_{initial_invalid_reason}'
            return self._fail(
                task,
                status=PopupDispatchStatus.BLOCKED,
                events=events,
                rounds=rounds,
                actions=actions,
                started_at=started_at,
                context=context,
                reason=reason,
                recorder=recorder,
                pending=pending,
            )

        while True:
            elapsed = self._time() - started_at
            if self._time() >= deadline_at or rounds >= self.max_rounds:
                reason = (
                    f'budget_exhausted elapsed={elapsed:.3f}s '
                    f'rounds={rounds}/{self.max_rounds}'
                )
                return self._fail(
                    task,
                    status=PopupDispatchStatus.EXHAUSTED,
                    events=events,
                    rounds=rounds,
                    actions=actions,
                    started_at=started_at,
                    context=context,
                    reason=reason,
                    recorder=recorder,
                    pending=pending,
                )

            rounds += 1
            selected = None
            detections: dict[str, object | None] = {}
            try:
                for handler in self.handlers:
                    detection = handler.detect(context)
                    context.ensure_deadline(f'detect:{handler.popup_id}')
                    detections[handler.popup_id] = detection
                    if detection is not None and selected is None:
                        selected = (handler, detection)
            except Exception as exc:
                reason = f'detection_error:{type(exc).__name__}:{exc}'
                return self._fail(
                    task,
                    status=PopupDispatchStatus.BLOCKED,
                    events=events,
                    rounds=rounds,
                    actions=actions,
                    started_at=started_at,
                    context=context,
                    reason=reason,
                    recorder=recorder,
                    pending=pending,
                )

            for pending_key, item in list(pending.items()):
                popup_id = item.detection.popup_id
                current_detection = detections.get(popup_id)
                same_instance = (
                    current_detection is not None
                    and current_detection.instance_key == item.detection.instance_key
                )
                if same_instance:
                    item.absent_frames = 0
                    continue
                item.absent_frames += 1
                required = max(1, int(getattr(item.handler, 'verify_absent_frames', 2)))
                if item.absent_frames < required:
                    continue
                resolved = self._event(
                    'popup_resolved',
                    popup_id=popup_id,
                    frame_id=context.frame_id,
                    absent_frames=item.absent_frames,
                )
                events.append(resolved)
                recorder.record_event(resolved)
                callback = getattr(item.handler, 'on_resolved', None)
                if callable(callback):
                    try:
                        callback(task, item.detection, item.action)
                    except Exception as exc:
                        reason = (
                            f'resolution_callback_error:{popup_id}:'
                            f'{type(exc).__name__}:{exc}'
                        )
                        return self._fail(
                            task,
                            status=PopupDispatchStatus.BLOCKED,
                            events=events,
                            rounds=rounds,
                            actions=actions,
                            started_at=started_at,
                            context=context,
                            reason=reason,
                            recorder=recorder,
                            pending=pending,
                        )
                del pending[pending_key]

            if selected is None:
                if pending:
                    try:
                        context = self._capture_next(
                            task,
                            context,
                            recorder,
                            phase='stable_check',
                            deadline_at=deadline_at,
                            capture=capture,
                            deadline_capabilities=deadline_capabilities,
                        )
                    except Exception as exc:
                        reason = f'verification_capture_error:{type(exc).__name__}:{exc}'
                        return self._fail(
                            task,
                            status=PopupDispatchStatus.BLOCKED,
                            events=events,
                            rounds=rounds,
                            actions=actions,
                            started_at=started_at,
                            context=context,
                            reason=reason,
                            recorder=recorder,
                            pending=pending,
                        )
                    continue

                report = self._report(
                    PopupDispatchStatus.HANDLED if handled_any else PopupDispatchStatus.STABLE,
                    events=events,
                    rounds=rounds,
                    actions=actions,
                    started_at=started_at,
                    context=context,
                    reason='all_handlers_absent',
                    recorder=recorder,
                )
                task._last_popup_dispatch_report = report
                if handled_any:
                    self._log('info', self._event(
                        'dispatch_complete',
                        status=report.status.value,
                        rounds=rounds,
                        actions=actions,
                        duration_ms=round(report.elapsed_ms, 3),
                        final_frame_id=context.frame_id,
                        evidence_event_id=recorder.event_id,
                    ))
                return report

            handler, detection = selected
            if recorder.event_id is None:
                recorder.start(task, context, detection)
            detected_event = self._event(
                'popup_detected',
                popup_id=detection.popup_id,
                priority=detection.priority,
                frame_id=detection.frame_id,
                instance_key=detection.instance_key,
                evidence=detection.evidence,
            )
            events.append(detected_event)
            recorder.record_event(detected_event)

            key = (detection.popup_id, detection.instance_key)
            attempt = attempts.get(key, 0) + 1
            handler_limit = max(1, int(getattr(handler, 'max_actions', 2)))
            if attempts.get(key, 0) >= handler_limit or actions >= self.max_actions:
                reason = (
                    f'action_budget_exhausted popup_id={detection.popup_id} '
                    f'instance_attempts={attempts.get(key, 0)}/{handler_limit} '
                    f'actions={actions}/{self.max_actions}'
                )
                return self._fail(
                    task,
                    status=PopupDispatchStatus.EXHAUSTED,
                    events=events,
                    rounds=rounds,
                    actions=actions,
                    started_at=started_at,
                    context=context,
                    reason=reason,
                    recorder=recorder,
                    pending=pending,
                )

            elapsed = self._time() - started_at
            if self._time() >= deadline_at:
                reason = (
                    f'budget_exhausted_before_action elapsed={elapsed:.3f}s '
                    f'limit={self.max_elapsed:.3f}s'
                )
                return self._fail(
                    task,
                    status=PopupDispatchStatus.EXHAUSTED,
                    events=events,
                    rounds=rounds,
                    actions=actions,
                    started_at=started_at,
                    context=context,
                    reason=reason,
                    recorder=recorder,
                    pending=pending,
                )

            required_capabilities = tuple(
                getattr(handler, 'required_deadline_capabilities', ())
            )
            missing_capabilities = [
                item for item in required_capabilities
                if not context.supports_deadline(item)
            ]
            if missing_capabilities:
                reason = 'deadline_capability_missing:' + ','.join(missing_capabilities)
                return self._fail(
                    task,
                    status=PopupDispatchStatus.BLOCKED,
                    events=events,
                    rounds=rounds,
                    actions=actions,
                    started_at=started_at,
                    context=context,
                    reason=reason,
                    recorder=recorder,
                    pending=pending,
                )

            try:
                action = handler.act(context, detection, attempt)
                context.ensure_deadline(f'action:{detection.popup_id}')
            except Exception as exc:
                reason = f'action_error:{detection.popup_id}:{type(exc).__name__}:{exc}'
                return self._fail(
                    task,
                    status=PopupDispatchStatus.BLOCKED,
                    events=events,
                    rounds=rounds,
                    actions=actions,
                    started_at=started_at,
                    context=context,
                    reason=reason,
                    recorder=recorder,
                    pending=pending,
                )

            recorder.record_action(detection.popup_id, action)
            action_event = self._event(
                'popup_action',
                popup_id=detection.popup_id,
                kind=action.kind.value,
                control_name=action.control_name,
                click_point=action.click_point,
                attempt=action.attempt,
                reason=action.reason,
            )
            events.append(action_event)
            recorder.record_event(action_event)

            if action.kind is PopupActionKind.BLOCKED:
                return self._fail(
                    task,
                    status=PopupDispatchStatus.BLOCKED,
                    events=events,
                    rounds=rounds,
                    actions=actions,
                    started_at=started_at,
                    context=context,
                    reason=f'{detection.popup_id}:{action.reason}',
                    recorder=recorder,
                    pending=pending,
                )
            if action.kind is PopupActionKind.FAILED:
                return self._fail(
                    task,
                    status=PopupDispatchStatus.BLOCKED,
                    events=events,
                    rounds=rounds,
                    actions=actions,
                    started_at=started_at,
                    context=context,
                    reason=f'{detection.popup_id}:{action.reason}',
                    recorder=recorder,
                    pending=pending,
                )
            if action.kind is PopupActionKind.SKIPPED:
                return self._fail(
                    task,
                    status=PopupDispatchStatus.BLOCKED,
                    events=events,
                    rounds=rounds,
                    actions=actions,
                    started_at=started_at,
                    context=context,
                    reason=f'{detection.popup_id}:unsafe_skip:{action.reason}',
                    recorder=recorder,
                    pending=pending,
                )

            attempts[key] = attempt
            actions += 1
            handled_any = True
            pending[(detection.popup_id, detection.instance_key)] = _PendingResolution(
                handler=handler,
                detection=detection,
                action=action,
            )
            try:
                context = self._capture_next(
                    task,
                    context,
                    recorder,
                    phase=f'after_{detection.popup_id}',
                    deadline_at=deadline_at,
                    capture=capture,
                    deadline_capabilities=deadline_capabilities,
                    delay=getattr(handler, 'post_action_delay', None),
                )
            except Exception as exc:
                reason = f'post_action_capture_error:{type(exc).__name__}:{exc}'
                return self._fail(
                    task,
                    status=PopupDispatchStatus.BLOCKED,
                    events=events,
                    rounds=rounds,
                    actions=actions,
                    started_at=started_at,
                    context=context,
                    reason=reason,
                    recorder=recorder,
                    pending=pending,
                )
