from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


Rect = tuple[int, int, int, int]
Point = tuple[int, int]


@dataclass(frozen=True)
class GuildCandidate:
    candidate_id: str
    card_rect: Rect
    center: Point
    medal_reward: int | None
    ocr_confidence: float | None
    frame_id: str
    frame_sha256: str


@dataclass(frozen=True)
class GuildSelectionResult:
    candidates: tuple[GuildCandidate, ...]
    selected: GuildCandidate | None
    max_medal: int | None
    verified: bool
    reason: str


@dataclass(frozen=True)
class GuildObservationComparison:
    stable: bool
    reason: str
    first_frame_id: str | None
    second_frame_id: str | None


class GuildSortOrder(str, Enum):
    ASCENDING = "ascending"
    DESCENDING = "descending"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GuildSortSnapshot:
    candidates: tuple[GuildCandidate, ...]
    order: GuildSortOrder
    values: tuple[int, ...]
    verified: bool
    reason: str
    frame_id: str | None
    frame_sha256: str | None


@dataclass(frozen=True)
class GuildSortPairResult:
    verified: bool
    reason: str
    highest_medal: int | None
    lowest_medal: int | None
    descending_values: tuple[int, ...]
    ascending_values: tuple[int, ...]


@dataclass(frozen=True)
class GuildSortVerification:
    verified: bool
    reason: str


def _candidate_geometry_valid(candidate: GuildCandidate) -> bool:
    x, y, width, height = candidate.card_rect
    center_x, center_y = candidate.center
    return (
        width > 0
        and height > 0
        and x <= center_x < x + width
        and y <= center_y < y + height
    )


def choose_highest_medal_guild(
    candidates: Iterable[GuildCandidate],
    *,
    minimum_confidence: float = 0.5,
) -> GuildSelectionResult:
    observed = tuple(candidates)
    if not observed:
        return GuildSelectionResult(observed, None, None, False, "no_candidates")

    if len({candidate.candidate_id for candidate in observed}) != len(observed):
        return GuildSelectionResult(observed, None, None, False, "duplicate_candidate_id")
    if len({candidate.frame_id for candidate in observed}) != 1:
        return GuildSelectionResult(observed, None, None, False, "mixed_frame_identity")
    if len({candidate.frame_sha256 for candidate in observed}) != 1:
        return GuildSelectionResult(observed, None, None, False, "mixed_frame_hash")
    if any(not _candidate_geometry_valid(candidate) for candidate in observed):
        return GuildSelectionResult(observed, None, None, False, "invalid_card_geometry")
    if any(
        candidate.medal_reward is None
        or candidate.medal_reward < 0
        or candidate.ocr_confidence is None
        or candidate.ocr_confidence < minimum_confidence
        for candidate in observed
    ):
        return GuildSelectionResult(observed, None, None, False, "incomplete_medal_ocr")

    maximum = max(candidate.medal_reward for candidate in observed)
    selected = min(
        (candidate for candidate in observed if candidate.medal_reward == maximum),
        key=lambda candidate: (
            candidate.center[1],
            candidate.center[0],
            candidate.candidate_id,
        ),
    )
    return GuildSelectionResult(observed, selected, maximum, True, "selected_maximum")


def classify_guild_sort_order(
    candidates: Iterable[GuildCandidate],
    *,
    minimum_confidence: float = 0.5,
) -> GuildSortSnapshot:
    observed = tuple(candidates)
    frame_id = observed[0].frame_id if observed else None
    frame_sha256 = observed[0].frame_sha256 if observed else None
    validation = choose_highest_medal_guild(
        observed,
        minimum_confidence=minimum_confidence,
    )
    if not validation.verified:
        return GuildSortSnapshot(
            observed,
            GuildSortOrder.UNKNOWN,
            (),
            False,
            validation.reason,
            frame_id,
            frame_sha256,
        )

    ordered = tuple(
        sorted(
            observed,
            key=lambda candidate: (
                candidate.center[1],
                candidate.center[0],
                candidate.candidate_id,
            ),
        )
    )
    values = tuple(int(candidate.medal_reward) for candidate in ordered)
    if len(values) < 2:
        return GuildSortSnapshot(
            ordered,
            GuildSortOrder.UNKNOWN,
            values,
            False,
            "insufficient_rows",
            frame_id,
            frame_sha256,
        )

    nondecreasing = all(left <= right for left, right in zip(values, values[1:]))
    nonincreasing = all(left >= right for left, right in zip(values, values[1:]))
    if nondecreasing and nonincreasing:
        return GuildSortSnapshot(
            ordered,
            GuildSortOrder.UNKNOWN,
            values,
            False,
            "sort_direction_ambiguous",
            frame_id,
            frame_sha256,
        )
    if nondecreasing:
        order = GuildSortOrder.ASCENDING
    elif nonincreasing:
        order = GuildSortOrder.DESCENDING
    else:
        return GuildSortSnapshot(
            ordered,
            GuildSortOrder.UNKNOWN,
            values,
            False,
            "not_monotonic",
            frame_id,
            frame_sha256,
        )
    return GuildSortSnapshot(
        ordered,
        order,
        values,
        True,
        "verified",
        frame_id,
        frame_sha256,
    )


def compare_guild_sort_snapshots(
    first: GuildSortSnapshot,
    second: GuildSortSnapshot,
) -> GuildSortPairResult:
    if not first.verified:
        return GuildSortPairResult(False, f"first_{first.reason}", None, None, (), ())
    if not second.verified:
        return GuildSortPairResult(False, f"second_{second.reason}", None, None, (), ())
    if first.order is second.order:
        return GuildSortPairResult(
            False,
            "sort_order_not_toggled",
            None,
            None,
            (),
            (),
        )
    if {first.order, second.order} != {
        GuildSortOrder.ASCENDING,
        GuildSortOrder.DESCENDING,
    }:
        return GuildSortPairResult(False, "sort_direction_unknown", None, None, (), ())

    descending = first if first.order is GuildSortOrder.DESCENDING else second
    ascending = first if first.order is GuildSortOrder.ASCENDING else second
    highest = descending.values[0]
    lowest = ascending.values[0]
    if highest <= lowest:
        return GuildSortPairResult(
            False,
            "sort_extremes_invalid",
            highest,
            lowest,
            descending.values,
            ascending.values,
        )
    return GuildSortPairResult(
        True,
        "verified",
        highest,
        lowest,
        descending.values,
        ascending.values,
    )


def verify_final_descending_snapshot(
    expected: GuildSortSnapshot,
    actual: GuildSortSnapshot,
) -> GuildSortVerification:
    if not expected.verified or expected.order is not GuildSortOrder.DESCENDING:
        return GuildSortVerification(False, "expected_descending_invalid")
    if not actual.verified or actual.order is not GuildSortOrder.DESCENDING:
        return GuildSortVerification(False, "final_page_not_descending")
    if actual.values != expected.values:
        return GuildSortVerification(False, "descending_values_changed")
    return GuildSortVerification(True, "verified")


def compare_guild_observations(
    first: Iterable[GuildCandidate],
    second: Iterable[GuildCandidate],
) -> GuildObservationComparison:
    first_observation = tuple(first)
    second_observation = tuple(second)
    first_frame_id = first_observation[0].frame_id if first_observation else None
    second_frame_id = second_observation[0].frame_id if second_observation else None

    first_result = choose_highest_medal_guild(first_observation)
    second_result = choose_highest_medal_guild(second_observation)
    if not first_result.verified:
        return GuildObservationComparison(
            False,
            f"first_{first_result.reason}",
            first_frame_id,
            second_frame_id,
        )
    if not second_result.verified:
        return GuildObservationComparison(
            False,
            f"second_{second_result.reason}",
            first_frame_id,
            second_frame_id,
        )
    if first_frame_id == second_frame_id:
        return GuildObservationComparison(
            False,
            "same_frame_reused",
            first_frame_id,
            second_frame_id,
        )

    def stable_projection(observation: tuple[GuildCandidate, ...]) -> tuple:
        return tuple(
            sorted(
                (
                    candidate.candidate_id,
                    candidate.card_rect,
                    candidate.center,
                    candidate.medal_reward,
                )
                for candidate in observation
            )
        )

    if stable_projection(first_observation) != stable_projection(second_observation):
        return GuildObservationComparison(
            False,
            "candidate_values_changed",
            first_frame_id,
            second_frame_id,
        )
    return GuildObservationComparison(
        True,
        "stable",
        first_frame_id,
        second_frame_id,
    )
