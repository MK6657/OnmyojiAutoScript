from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dev_tools.green_mark_target_range import capture_rgb, save_png
from module.config.config import Config
from module.device.method.nemu_ipc import NemuIpcImpl, serial_to_id


def _write_status(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Passively capture green-marker evidence without clicking the game."
    )
    parser.add_argument("--config", default="oas1")
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--interval", type=float, default=0.20)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    if not 5.0 <= args.duration <= 600.0:
        parser.error("--duration must be between 5 and 600 seconds")
    if not 0.10 <= args.interval <= 2.0:
        parser.error("--interval must be between 0.10 and 2 seconds")

    config = Config(args.config)
    serial = str(config.script.device.serial)
    instance_id = serial_to_id(serial)
    if instance_id is None:
        raise RuntimeError(f"serial does not identify one MuMu instance: {serial}")
    folder = str(Path(config.script.device.emulatorinfo_path).parent.parent)
    output = args.output or Path("output/evidence/green_mark") / datetime.now().strftime(
        "%Y%m%d-%H%M%S-passive"
    )
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    ipc = NemuIpcImpl(folder, instance_id)
    ipc.connect()
    started = time.monotonic()
    frames: list[dict[str, object]] = []
    try:
        initial = capture_rgb(ipc)
        if initial.shape[:2] != (720, 1280):
            raise RuntimeError(f"unexpected target frame size: {initial.shape}")
        save_png(output / "0000-000.00.png", initial)
        _write_status(
            args.status,
            {
                "state": "armed",
                "serial": serial,
                "instance_id": instance_id,
                "output": str(output),
                "armed_at": datetime.now().isoformat(),
            },
        )

        index = 1
        next_capture = started + args.interval
        while time.monotonic() - started < args.duration:
            delay = next_capture - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            frame = capture_rgb(ipc)
            elapsed = time.monotonic() - started
            name = f"{index:04d}-{elapsed:06.2f}.png"
            save_png(output / name, frame)
            encoded, buffer = cv2.imencode(
                ".png", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            )
            if not encoded:
                raise RuntimeError(f"failed to hash captured frame {name}")
            frames.append(
                {
                    "index": index,
                    "elapsed_seconds": round(elapsed, 3),
                    "file": name,
                    "sha256": hashlib.sha256(buffer.tobytes()).hexdigest(),
                }
            )
            index += 1
            next_capture += args.interval

        manifest = {
            "serial": serial,
            "instance_id": instance_id,
            "duration_seconds": args.duration,
            "interval_seconds": args.interval,
            "frames": frames,
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_status(
            args.status,
            {
                "state": "complete",
                "serial": serial,
                "instance_id": instance_id,
                "output": str(output),
                "frames": len(frames) + 1,
                "completed_at": datetime.now().isoformat(),
            },
        )
        return 0
    except Exception as error:
        _write_status(
            args.status,
            {
                "state": "failed",
                "serial": serial,
                "instance_id": instance_id,
                "output": str(output),
                "reason": f"{type(error).__name__}: {error}",
                "failed_at": datetime.now().isoformat(),
            },
        )
        raise
    finally:
        ipc.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
