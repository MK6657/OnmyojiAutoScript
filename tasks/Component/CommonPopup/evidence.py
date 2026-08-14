from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from module.logger import logger


class CommonPopupEvidenceRecorder:
    """Persist frames only after a popup candidate is positively detected."""

    def __init__(self, root: Path | None = None, enabled: bool = True):
        self.enabled = bool(enabled)
        self.root = root or (Path.cwd() / 'log' / 'evidence' / 'common_popup')
        self.event_id: str | None = None
        self.event_dir: Path | None = None
        self.manifest: dict[str, Any] = {}
        self.error: str | None = None

    @staticmethod
    def _task_metadata(task) -> dict[str, Any]:
        config = getattr(task, 'config', None)
        model = getattr(config, 'model', None)
        return {
            'account': str(getattr(config, 'config_name', 'unknown')),
            'task': str(getattr(model, 'running_task', '') or type(task).__name__),
            'run_id': str(getattr(task, '_run_id', '') or 'unknown'),
            'environment': os.environ.get('OAS_ENVIRONMENT', 'production'),
            'guard_version': 1,
        }

    def start(self, task, context, detection) -> None:
        if not self.enabled or self.event_id is not None:
            return
        try:
            self.event_id = f'popup_{uuid.uuid4().hex[:16]}'
            day = datetime.now().strftime('%Y%m%d')
            self.event_dir = self.root / day / self.event_id
            self.event_dir.mkdir(parents=True, exist_ok=False)
            self.manifest = {
                'event_id': self.event_id,
                **self._task_metadata(task),
                'device_identity': context.device_identity,
                'screenshot_method': context.screenshot_method,
                'popup_id': detection.popup_id,
                'detected_at': datetime.now().isoformat(timespec='milliseconds'),
                'status': 'detected',
                'frames': [],
                'actions': [],
                'events': [],
            }
            self.record_frame(context, phase='before')
            self.flush()
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
            logger.error(f'COMMON_POPUP_EVIDENCE status=failed reason={self.error}')

    def record_frame(self, context, *, phase: str) -> dict[str, Any] | None:
        if self.event_dir is None or self.error is not None:
            return None
        image = context.image
        if not isinstance(image, np.ndarray) or image.ndim != 3:
            self.error = 'invalid_frame_for_evidence'
            return None
        try:
            sequence = len(self.manifest['frames']) + 1
            filename = f'{sequence:02d}_{phase}_frame_{context.frame_id}.png'
            path = self.event_dir / filename
            temp = path.with_suffix('.png.tmp')
            Image.fromarray(np.ascontiguousarray(image[:, :, :3])).save(
                temp,
                format='PNG',
            )
            temp.replace(path)
            entry = {
                'phase': phase,
                'file': filename,
                'frame_id': context.frame_id,
                'captured_at': context.captured_at,
                'size': context.size,
                'pixel_sha256': context.pixel_sha256(),
                'file_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            self.manifest['frames'].append(entry)
            return entry
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
            logger.error(f'COMMON_POPUP_EVIDENCE status=failed reason={self.error}')
            return None

    def record_action(self, popup_id: str, action) -> None:
        if not self.manifest:
            return
        self.manifest['actions'].append({
            'popup_id': popup_id,
            'kind': action.kind.value,
            'control_name': action.control_name,
            'click_point': action.click_point,
            'attempt': action.attempt,
            'reason': action.reason,
            'clicked_at': datetime.now().isoformat(timespec='milliseconds'),
        })

    def record_event(self, event: dict[str, Any]) -> None:
        if self.manifest:
            self.manifest['events'].append(event)

    def finish(self, report) -> None:
        if not self.manifest:
            return
        self.manifest.update({
            'status': report.status.value,
            'reason': report.reason,
            'rounds': report.rounds,
            'actions_count': report.actions,
            'duration_ms': round(report.elapsed_ms, 3),
            'final_frame_id': report.final_frame_id,
            'cleared_at': datetime.now().isoformat(timespec='milliseconds'),
            'evidence_error': self.error,
        })
        self.flush()

    def flush(self) -> None:
        if self.event_dir is None or not self.manifest:
            return
        path = self.event_dir / 'manifest.json'
        temp = self.event_dir / 'manifest.json.tmp'
        temp.write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        temp.replace(path)

