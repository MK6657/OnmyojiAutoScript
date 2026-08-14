from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class PopupActionKind(str, Enum):
    CLICKED = 'clicked'
    SKIPPED = 'skipped'
    BLOCKED = 'blocked'
    FAILED = 'failed'


class PopupVerificationStatus(str, Enum):
    RESOLVED = 'resolved'
    RETRY = 'retry'
    BLOCKED = 'blocked'
    FAILED = 'failed'


class PopupDispatchStatus(str, Enum):
    STABLE = 'stable'
    HANDLED = 'handled'
    BLOCKED = 'blocked'
    EXHAUSTED = 'exhausted'


@dataclass(frozen=True)
class PopupFrameContext:
    image: Any
    frame_id: int
    captured_at: float
    device_identity: str
    screenshot_method: str
    size: tuple[int, int] | None
    deadline_at: float | None
    deadline_capabilities: frozenset[str]
    _task: Any = field(repr=False, compare=False)
    _time_fn: Any = field(repr=False, compare=False)

    @classmethod
    def from_task(
        cls,
        task,
        *,
        deadline_at: float | None = None,
        deadline_capabilities: frozenset[str] | None = None,
        time_fn=None,
    ) -> 'PopupFrameContext':
        device = task.device
        image = getattr(device, 'image', None)
        shape = getattr(image, 'shape', None)
        size = None
        if shape is not None and len(shape) >= 2:
            size = (int(shape[1]), int(shape[0]))

        config = getattr(task, 'config', None)
        script = getattr(config, 'script', None)
        device_config = getattr(script, 'device', None)
        serial = getattr(device, 'serial', None)
        if serial is None:
            serial = getattr(device_config, 'serial', 'unknown')
        screenshot_method = getattr(device_config, 'screenshot_method', 'unknown')
        identity = f'{serial}|{screenshot_method}'
        frame_id = int(getattr(device, 'frame_id', id(image)))
        return cls(
            image=image,
            frame_id=frame_id,
            captured_at=time.time(),
            device_identity=identity,
            screenshot_method=str(screenshot_method),
            size=size,
            deadline_at=deadline_at,
            deadline_capabilities=deadline_capabilities or frozenset(),
            _task=task,
            _time_fn=time_fn or time.monotonic,
        )

    def remaining_seconds(self) -> float | None:
        if self.deadline_at is None:
            return None
        return max(0.0, float(self.deadline_at - self._time_fn()))

    def ensure_deadline(self, operation: str) -> None:
        remaining = self.remaining_seconds()
        if remaining is not None and remaining <= 0:
            raise TimeoutError(f'popup_deadline_exceeded:{operation}')

    def supports_deadline(self, capability: str) -> bool:
        return capability in self.deadline_capabilities

    def appear(self, target, **kwargs) -> bool:
        return bool(self._task.appear(target, **kwargs))

    def ocr_text(self, rule) -> str:
        self.ensure_deadline('ocr_before')
        runner = getattr(self._task, '_common_popup_ocr_text', None)
        if callable(runner):
            result = runner(rule, self.image, deadline=self.deadline_at)
        else:
            result = rule.detect_text(self.image)
        self.ensure_deadline('ocr_after')
        return str(result)

    def click(self, x: int, y: int, *, control_name: str) -> None:
        self.ensure_deadline('click_before')
        self._task.device.click(int(x), int(y), control_name=control_name)
        self.ensure_deadline('click_after')

    def pixel_sha256(self) -> str | None:
        if not isinstance(self.image, np.ndarray):
            return None
        contiguous = np.ascontiguousarray(self.image)
        return hashlib.sha256(contiguous.tobytes()).hexdigest()


@dataclass(frozen=True)
class PopupDetection:
    popup_id: str
    priority: int
    frame_id: int
    instance_key: str
    pixel_sha256: str | None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PopupActionResult:
    kind: PopupActionKind
    control_name: str = ''
    click_point: tuple[int, int] | None = None
    attempt: int = 0
    reason: str = ''


@dataclass(frozen=True)
class PopupVerification:
    status: PopupVerificationStatus
    reason: str
    after_frame_id: int
    after_sha256: str | None = None


@dataclass
class PopupDispatchReport:
    status: PopupDispatchStatus
    events: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0
    actions: int = 0
    elapsed_ms: float = 0.0
    final_frame_id: int = 0
    reason: str = ''
    evidence_event_id: str | None = None
