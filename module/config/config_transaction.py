from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from filelock import FileLock

from module.config.atomicwrites import atomic_write


class ConfigRevisionConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class ConfigWriteResult:
    revision: str
    data: dict[str, Any]
    changed_paths: tuple[tuple[str, ...], ...]


def merge_validated_existing(
    original: dict[str, Any],
    validated: dict[str, Any],
) -> dict[str, Any]:
    """Overlay normalized known fields while retaining unknown extensions."""
    result = copy.deepcopy(original)
    for key, value in list(result.items()):
        if key not in validated:
            continue
        normalized = validated[key]
        if isinstance(value, dict) and isinstance(normalized, dict):
            result[key] = merge_validated_existing(value, normalized)
        else:
            result[key] = normalized
    return result


def file_revision(path: str | Path) -> str:
    target = Path(path)
    payload = target.read_bytes() if target.exists() else b""
    return hashlib.sha256(payload).hexdigest()


def _read_unlocked(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_unlocked(path: Path, data: dict[str, Any]) -> None:
    with atomic_write(str(path), overwrite=True, encoding="utf-8", newline="") as stream:
        stream.write(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False, default=str)
        )


def _set_existing(
    data: dict[str, Any],
    path: tuple[str, ...],
    value: Any,
    *,
    allow_new_leaf: bool = False,
) -> None:
    if not path:
        raise KeyError("empty config path")
    current: Any = data
    for key in path[:-1]:
        if not isinstance(current, dict) or key not in current:
            raise KeyError(".".join(path))
        current = current[key]
    leaf = path[-1]
    if not isinstance(current, dict) or (leaf not in current and not allow_new_leaf):
        raise KeyError(".".join(path))
    current[leaf] = value


def _get_existing(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            raise KeyError(".".join(path))
        current = current[key]
    return current


def apply_json_patch(
    path: str | Path,
    updates: Iterable[tuple[tuple[str, ...], Any]],
    *,
    expected_revision: str | None = None,
    validator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    allow_new_leaf: bool = False,
) -> ConfigWriteResult:
    target = Path(path)
    normalized_updates = tuple((tuple(item_path), value) for item_path, value in updates)
    with FileLock(f"{target}.lock"):
        current_revision = file_revision(target)
        if expected_revision is not None and expected_revision != current_revision:
            raise ConfigRevisionConflict(
                f"stale config revision: expected={expected_revision}, current={current_revision}"
            )
        candidate = copy.deepcopy(_read_unlocked(target))
        for item_path, value in normalized_updates:
            _set_existing(
                candidate,
                item_path,
                value,
                allow_new_leaf=allow_new_leaf,
            )
        if validator is not None:
            candidate = validator(candidate)
        _write_unlocked(target, candidate)
        return ConfigWriteResult(
            revision=file_revision(target),
            data=candidate,
            changed_paths=tuple(item_path for item_path, _value in normalized_updates),
        )


def _collect_changed_paths(
    baseline: Any,
    current: Any,
    prefix: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], Any]]:
    if isinstance(baseline, dict) and isinstance(current, dict):
        changes = []
        for key in current:
            if key not in baseline:
                changes.append((prefix + (str(key),), current[key]))
            else:
                changes.extend(
                    _collect_changed_paths(
                        baseline[key],
                        current[key],
                        prefix + (str(key),),
                    )
                )
        return changes
    if baseline != current:
        return [(prefix, current)]
    return []


def merge_changed_json(
    path: str | Path,
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    validator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> ConfigWriteResult:
    updates = _collect_changed_paths(baseline, current)
    target = Path(path)
    if not updates:
        return ConfigWriteResult(file_revision(target), _read_unlocked(target), ())

    with FileLock(f"{target}.lock"):
        latest = _read_unlocked(target)
        conflicts = []
        for item_path, desired in updates:
            try:
                baseline_value = _get_existing(baseline, item_path)
                latest_value = _get_existing(latest, item_path)
            except KeyError:
                continue
            if latest_value != baseline_value and latest_value != desired:
                conflicts.append(".".join(item_path))
        if conflicts:
            raise ConfigRevisionConflict(
                "concurrent config fields changed: " + ", ".join(conflicts)
            )

        candidate = copy.deepcopy(latest)
        for item_path, value in updates:
            _set_existing(candidate, item_path, value, allow_new_leaf=True)
        if validator is not None:
            candidate = validator(candidate)
        _write_unlocked(target, candidate)
        return ConfigWriteResult(
            revision=file_revision(target),
            data=candidate,
            changed_paths=tuple(item_path for item_path, _value in updates),
        )
