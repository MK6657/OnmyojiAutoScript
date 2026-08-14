from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from module.config.config import Config
from module.device.method.nemu_ipc import NemuIpcImpl, serial_to_id
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.GeneralBattle.green_mark_detector import diagnose_green_marker
from tasks.GameUi.assets import GameUiAssets
from tasks.Component.GeneralBattle.green_mark_detector import (
    classify_marker_frame,
    resolve_stable_marker_frames,
)


TARGETS = (
    ('green_left1', GeneralBattleAssets.C_GREEN_LEFT_1),
    ('green_left2', GeneralBattleAssets.C_GREEN_LEFT_2),
    ('green_left3', GeneralBattleAssets.C_GREEN_LEFT_3),
    ('green_left4', GeneralBattleAssets.C_GREEN_LEFT_4),
    ('green_left5', GeneralBattleAssets.C_GREEN_LEFT_5),
)
MARKER_ASSETS = (
    GeneralBattleAssets.I_GREEN_MARKER_LEFT_TOP,
    GeneralBattleAssets.I_GREEN_MARKER_BOTTOM,
    GeneralBattleAssets.I_GREEN_MARKER,
)
SLOT_ROIS = {name: tuple(rule.roi_front) for name, rule in TARGETS}


def capture_rgb(ipc: NemuIpcImpl):
    raw = ipc.screenshot()
    image = cv2.cvtColor(raw, cv2.COLOR_RGBA2RGB)
    cv2.flip(image, 0, dst=image)
    return image


def save_png(path: Path, image) -> None:
    encoded, buffer = cv2.imencode('.png', cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    if not encoded:
        raise RuntimeError(f'failed to encode {path}')
    buffer.tofile(str(path))


def write_status(path: Path | None, payload: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    temporary.replace(path)


def adb_binary() -> Path:
    root = Path(sys.executable).resolve().parent.parent
    binary = root / 'Lib' / 'site-packages' / 'adbutils' / 'binaries' / 'adb.exe'
    if not binary.is_file():
        raise RuntimeError(f'ADB binary is unavailable: {binary}')
    return binary


def tap(adb: Path, serial: str, point: tuple[int, int]) -> None:
    subprocess.run(
        [str(adb), '-s', serial, 'shell', 'input', 'tap', str(point[0]), str(point[1])],
        check=True,
        capture_output=True,
        timeout=8,
    )


def _match(rule, image) -> bool:
    candidate = copy.copy(rule)
    candidate.roi_front = list(rule.roi_front)
    return bool(candidate.match(image))


def sampling_frame_ready(image) -> tuple[bool, str]:
    if image.shape[:2] != (720, 1280):
        return False, f'unexpected frame size {image.shape}'
    if _match(GeneralBattleAssets.I_PREPARE_HIGHLIGHT, image) or _match(
        GeneralBattleAssets.I_PREPARE_DARK, image
    ):
        return False, 'prepare page is still visible'
    if _match(GeneralBattleAssets.I_WIN, image) or _match(
        GeneralBattleAssets.I_FALSE, image
    ) or _match(GeneralBattleAssets.I_REWARD, image):
        return False, 'battle terminal is visible'
    if not (
        _match(GeneralBattleAssets.I_BATTLE_INFO, image)
        or _match(GeneralBattleAssets.I_FRIENDS, image)
    ):
        return False, 'real battle evidence is absent'
    try:
        mode_text = str(GameUiAssets.O_BATTLE_AUTO.ocr_single(image) or '')
    except Exception as error:  # noqa: BLE001
        return False, f'auto mode OCR failed: {error}'
    if '自动' not in mode_text.replace(' ', ''):
        return False, f'auto mode is unconfirmed: {mode_text!r}'
    return True, 'real battle and auto mode confirmed'


def wait_sampling_ready(ipc: NemuIpcImpl, timeout: float) -> tuple[object, str]:
    deadline = time.monotonic() + max(0.0, float(timeout))
    stable = 0
    last_frame = None
    last_reason = 'no frame captured'
    while time.monotonic() <= deadline:
        last_frame = capture_rgb(ipc)
        ready, last_reason = sampling_frame_ready(last_frame)
        stable = stable + 1 if ready else 0
        if stable >= 2:
            return last_frame, last_reason
        time.sleep(0.15)
    raise RuntimeError(f'sampling gate did not become stable: {last_reason}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Capture reproducible green-marker target-range evidence.')
    parser.add_argument('--config', default='oas1')
    parser.add_argument('--rounds', type=int, default=10)
    parser.add_argument(
        '--target',
        choices=('all', *(name for name, _ in TARGETS)),
        default='all',
    )
    parser.add_argument('--output', type=Path)
    parser.add_argument('--status', type=Path)
    parser.add_argument('--readiness-timeout', type=float, default=4.0)
    parser.add_argument('--confirmation-timeout', type=float, default=2.0)
    parser.add_argument('--max-attempts', type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 50:
        parser.error('--rounds must be between 1 and 50')
    if not 0.5 <= args.confirmation_timeout <= 3.0:
        parser.error('--confirmation-timeout must be between 0.5 and 3.0')
    if not 1 <= args.max_attempts <= 2:
        parser.error('--max-attempts must be between 1 and 2')

    config = Config(args.config)
    serial = str(config.script.device.serial)
    instance_id = serial_to_id(serial)
    if instance_id is None:
        raise RuntimeError(f'serial does not identify one MuMu instance: {serial}')
    folder = str(Path(config.script.device.emulatorinfo_path).parent.parent)
    output = args.output or Path('output/evidence/green_mark') / datetime.now().strftime(
        '%Y%m%d-%H%M%S-target-range'
    )
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = output / 'samples.jsonl'
    selected_targets = (
        TARGETS
        if args.target == 'all'
        else tuple(item for item in TARGETS if item[0] == args.target)
    )
    adb = adb_binary()
    ipc = NemuIpcImpl(folder, instance_id)
    ipc.connect()
    try:
        initial = capture_rgb(ipc)
        if initial.shape[:2] != (720, 1280):
            raise RuntimeError(f'unexpected target frame size: {initial.shape}')
        save_png(output / 'initial.png', initial)
        write_status(
            args.status,
            {
                'state': 'armed',
                'serial': serial,
                'instance_id': instance_id,
                'target': args.target,
                'output': str(output.resolve()),
            },
        )
        with manifest_path.open('w', encoding='utf-8', newline='\n') as manifest:
            sequence = 0
            for round_index in range(1, args.rounds + 1):
                for target_name, target_rule in selected_targets:
                    sequence += 1
                    stable_result = None
                    point = None
                    used_attempts = 0
                    for attempt in range(1, args.max_attempts + 1):
                        used_attempts = attempt
                        before, readiness_reason = wait_sampling_ready(
                            ipc,
                            timeout=args.readiness_timeout,
                        )
                        point = tuple(int(value) for value in target_rule.coord())
                        before_path = output / (
                            f'{sequence:03d}-{target_name}-attempt-{attempt}-before.png'
                        )
                        save_png(before_path, before)
                        tap(adb, serial, point)
                        observations = []
                        started = time.monotonic()
                        next_capture = started + 0.15
                        frame_index = 0
                        while True:
                            remaining = next_capture - time.monotonic()
                            if remaining > 0:
                                time.sleep(remaining)
                            delay = time.monotonic() - started
                            if delay > args.confirmation_timeout + 0.05:
                                break
                            frame_index += 1
                            frame = capture_rgb(ipc)
                            frame_path = output / (
                                f'{sequence:03d}-{target_name}-attempt-{attempt}'
                                f'-after-{frame_index}.png'
                            )
                            save_png(frame_path, frame)
                            diagnostic = diagnose_green_marker(
                                frame,
                                target_name=target_name,
                                target_roi=target_rule.roi_front,
                                template_assets=MARKER_ASSETS,
                            )
                            observation = classify_marker_frame(
                                frame,
                                expected_slot=target_name,
                                slot_rois=SLOT_ROIS,
                            )
                            observations.append(observation)
                            stable_result = resolve_stable_marker_frames(
                                observations,
                                expected_slot=target_name,
                            )
                            record = {
                                'sequence': sequence,
                                'round': round_index,
                                'target': target_name,
                                'attempt': attempt,
                                'attempt_frame': frame_index,
                                'click_point': point,
                                'delay_seconds': round(delay, 3),
                                'before_file': before_path.name,
                                'frame_file': frame_path.name,
                                'serial': serial,
                                'instance_id': instance_id,
                                'readiness': readiness_reason,
                                'frame_observation': observation.__dict__,
                                'stable_result': stable_result.to_dict(),
                                **diagnostic.to_dict(),
                            }
                            manifest.write(json.dumps(record, ensure_ascii=False) + '\n')
                            manifest.flush()
                            if stable_result.status in {
                                'confirmed',
                                'wrong_target',
                                'enemy_selected',
                            }:
                                break
                            next_capture += 0.20
                            if next_capture - started > args.confirmation_timeout:
                                break
                        if stable_result is not None and stable_result.status == 'confirmed':
                            break
                        if attempt < args.max_attempts:
                            time.sleep(0.3)
                    print(
                        json.dumps(
                            {
                                'sequence': sequence,
                                'round': round_index,
                                'target': target_name,
                                'click_point': point,
                                'attempts': used_attempts,
                                'status': (
                                    stable_result.status
                                    if stable_result is not None
                                    else 'unconfirmed'
                                ),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
        write_status(
            args.status,
            {
                'state': 'complete',
                'serial': serial,
                'instance_id': instance_id,
                'target': args.target,
                'output': str(output.resolve()),
                'samples': args.rounds * len(selected_targets),
            },
        )
    except Exception as error:
        write_status(
            args.status,
            {
                'state': 'failed',
                'serial': serial,
                'instance_id': instance_id,
                'target': args.target,
                'output': str(output.resolve()),
                'reason': f'{type(error).__name__}: {error}',
            },
        )
        raise
    finally:
        ipc.disconnect()
    print(
        json.dumps(
            {
                'output': str(output.resolve()),
                'samples': args.rounds * len(selected_targets),
            }
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
