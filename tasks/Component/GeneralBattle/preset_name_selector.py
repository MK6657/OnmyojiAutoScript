# This Python file uses the following encoding: utf-8
"""Pure helpers for scanning preset group/team names safely."""

from __future__ import annotations

from dataclasses import dataclass
import time
import unicodedata
from typing import Iterable, Sequence


PRESET_VALIDATION_TTL_SECONDS = 300.0
_PRESET_VALIDATION_CACHE: dict[tuple[str, str, str], float] = {}


class PresetLookupError(ValueError):
    """Raised when a preset name cannot be selected unambiguously."""


class InvalidPresetConfigError(PresetLookupError):
    """Raised before touching the game when a preset setting is invalid."""


class PresetApplyUnconfirmedError(PresetLookupError):
    """Raised when a preset action cannot be visually confirmed."""


class PresetNameNotFoundError(PresetLookupError):
    pass


class PresetNameDuplicateError(PresetLookupError):
    pass


@dataclass(frozen=True)
class OcrNameLine:
    text: str
    center_x: int
    center_y: int


def normalize_preset_name(value: object) -> str:
    """Normalize harmless OCR/input differences without allowing fuzzy matches."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return "".join(text.split()).casefold()


def _preset_validation_key(account: object, group: object, team: object) -> tuple[str, str, str]:
    return (
        normalize_preset_name(account),
        normalize_preset_name(group),
        normalize_preset_name(team),
    )


def remember_preset_validation(
    account: object,
    group: object,
    team: object,
    now: float | None = None,
) -> None:
    """Remember one successful full duplicate scan for a short process-local window."""
    _PRESET_VALIDATION_CACHE[_preset_validation_key(account, group, team)] = (
        time.monotonic() if now is None else float(now)
    )


def preset_validation_is_recent(
    account: object,
    group: object,
    team: object,
    now: float | None = None,
    ttl: float = PRESET_VALIDATION_TTL_SECONDS,
) -> bool:
    key = _preset_validation_key(account, group, team)
    validated_at = _PRESET_VALIDATION_CACHE.get(key)
    if validated_at is None:
        return False
    current = time.monotonic() if now is None else float(now)
    if current - validated_at <= float(ttl):
        return True
    _PRESET_VALIDATION_CACHE.pop(key, None)
    return False


def forget_preset_validation(account: object, group: object, team: object) -> None:
    _PRESET_VALIDATION_CACHE.pop(_preset_validation_key(account, group, team), None)


def merge_ordered_pages(current: Sequence[str], page: Sequence[str]) -> list[str]:
    """Merge two ordered OCR pages using their largest suffix/prefix overlap.

    Keeping sequence order is important: adjacent duplicate names must remain two
    separate entries, while rows repeated by an overlapping swipe are counted once.
    """
    merged = list(current)
    incoming = list(page)
    if not merged:
        return incoming
    if not incoming:
        return merged

    max_overlap = min(len(merged), len(incoming))
    overlap = 0
    for size in range(max_overlap, 0, -1):
        left = merged[-size:]
        right = incoming[:size]
        if left == right:
            overlap = size
            break
        # OCR may confuse one character in an otherwise stable overlap. Use
        # this only for page stitching, never for the later exact duplicate
        # name decision.
        if size >= 3:
            fuzzy_mismatches = 0
            compatible = True
            for left_name, right_name in zip(left, right):
                if normalize_preset_name(left_name) == normalize_preset_name(right_name):
                    continue
                if not _ocr_overlap_name_equal(left_name, right_name):
                    compatible = False
                    break
                fuzzy_mismatches += 1
            if compatible and fuzzy_mismatches <= 1:
                overlap = size
                break
    merged.extend(incoming[overlap:])
    return merged


def _ocr_overlap_name_equal(left: object, right: object) -> bool:
    """Allow one OCR edit when identifying a repeated page row."""
    left_text = normalize_preset_name(left)
    right_text = normalize_preset_name(right)
    if left_text == right_text:
        return True
    if not left_text or not right_text:
        return False
    if abs(len(left_text) - len(right_text)) > 1:
        return False

    previous = list(range(len(right_text) + 1))
    for left_index, left_char in enumerate(left_text, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right_text, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        if min(current) > 1:
            return False
        previous = current
    return previous[-1] <= 1


def require_unique_name(names: Iterable[str], target: str, kind: str) -> int:
    """Return the unique target index, otherwise raise a user-facing error."""
    normalized_target = normalize_preset_name(target)
    if not normalized_target:
        raise PresetNameNotFoundError(f"{kind}名称不能为空")

    normalized_names = [normalize_preset_name(name) for name in names]
    matches = [index for index, name in enumerate(normalized_names) if name == normalized_target]
    if not matches:
        raise PresetNameNotFoundError(
            f"没有识别到{kind}“{target}”，请检查名称是否与游戏内完全一致"
        )
    if len(matches) > 1:
        raise PresetNameDuplicateError(
            f"识别到 {len(matches)} 个同名{kind}“{target}”，请在游戏内重命名后再运行"
        )
    return matches[0]


def boxed_results_to_lines(
    boxed_results,
    y_tolerance: int = 14,
    max_left: int | None = None,
) -> list[OcrNameLine]:
    """Join OCR fragments that belong to the same visual line."""
    fragments = []
    for result in boxed_results:
        box = result.box
        left = int(min(point[0] for point in box))
        right = int(max(point[0] for point in box))
        top = int(min(point[1] for point in box))
        bottom = int(max(point[1] for point in box))
        text = str(result.ocr_text or "").strip()
        if text and (max_left is None or left <= max_left):
            fragments.append((int((top + bottom) / 2), left, right, top, bottom, text))

    fragments.sort(key=lambda item: (item[0], item[1]))
    rows: list[list[tuple]] = []
    for fragment in fragments:
        if rows and abs(fragment[0] - int(sum(item[0] for item in rows[-1]) / len(rows[-1]))) <= y_tolerance:
            rows[-1].append(fragment)
        else:
            rows.append([fragment])

    lines = []
    for row in rows:
        row.sort(key=lambda item: item[1])
        text = "".join(item[5] for item in row)
        left = min(item[1] for item in row)
        right = max(item[2] for item in row)
        top = min(item[3] for item in row)
        bottom = max(item[4] for item in row)
        lines.append(OcrNameLine(text=text, center_x=int((left + right) / 2), center_y=int((top + bottom) / 2)))
    return lines
