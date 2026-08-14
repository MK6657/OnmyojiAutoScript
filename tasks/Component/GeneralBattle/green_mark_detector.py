from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import Counter
import hashlib
from typing import Iterable, Mapping, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class GreenMarkResult:
    status: str
    target: str
    click_point: tuple[int, int] | None = None
    marker_point: tuple[int, int] | None = None
    detector: str | None = None
    max_score: float | None = None
    frame_sha256: str | None = None
    attempts: int = 0
    reason: str = ''
    color: str | None = None
    expected_slot: str | None = None
    assigned_slot: str | None = None
    marker_tip: tuple[int, int] | None = None
    stable_frames: int = 0
    confidence: float | None = None

    def __bool__(self) -> bool:
        return self.status == 'confirmed'

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GreenMarkTemplateDiagnostic:
    name: str
    threshold: float
    max_score: float
    top_left: tuple[int, int] | None
    center: tuple[int, int] | None
    size: tuple[int, int] | None
    inside_target: bool
    matched: bool


@dataclass(frozen=True)
class GreenMarkHsvCandidate:
    bbox: tuple[int, int, int, int]
    center: tuple[int, int]
    area: int
    inside_target: bool


@dataclass(frozen=True)
class ColoredMarkerCandidate:
    color: str
    bbox: tuple[int, int, int, int]
    center: tuple[int, int]
    tip: tuple[int, int]
    area: int
    confidence: float


@dataclass(frozen=True)
class GreenMarkerFrameObservation:
    frame_sha256: str
    expected_slot: str
    observation: str
    color: str | None = None
    assigned_slot: str | None = None
    marker_tip: tuple[int, int] | None = None
    bbox: tuple[int, int, int, int] | None = None
    area: int = 0
    confidence: float = 0.0
    reason: str = ''


@dataclass(frozen=True)
class GreenMarkDiagnostic:
    frame_sha256: str
    frame_size: tuple[int, int]
    target_name: str
    target_roi: tuple[int, int, int, int]
    confirmation_band: tuple[int, int, int, int]
    templates: tuple[GreenMarkTemplateDiagnostic, ...]
    hsv_candidates: tuple[GreenMarkHsvCandidate, ...]
    template_confirmed: bool

    def to_dict(self) -> dict:
        return asdict(self)


def frame_sha256(image: np.ndarray) -> str:
    """Hash the exact decoded frame together with its array identity."""
    contiguous = np.ascontiguousarray(image)
    digest = hashlib.sha256()
    digest.update(str(contiguous.shape).encode('ascii'))
    digest.update(b'|')
    digest.update(str(contiguous.dtype).encode('ascii'))
    digest.update(b'|')
    digest.update(contiguous.tobytes())
    return digest.hexdigest()


def confirmation_band(
    target_roi: tuple[int, int, int, int],
    canvas_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Mirror the production head-to-body confirmation band."""
    x, y, width, height = (int(value) for value in target_roi)
    canvas_width, canvas_height = canvas_size
    left = max(0, x - 45)
    top = max(0, y - 180)
    right = min(canvas_width, x + width + 45)
    bottom = min(canvas_height, y + height + 100)
    return left, top, right - left, bottom - top


def point_in_rect(
    point: tuple[int, int] | None,
    rect: tuple[int, int, int, int],
) -> bool:
    if point is None:
        return False
    x, y = point
    left, top, width, height = rect
    return left <= x < left + width and top <= y < top + height


def _best_template_match(image: np.ndarray, asset) -> tuple[float, tuple[int, int] | None, tuple[int, int] | None]:
    source = asset.corp(image)
    _ = asset.image
    templates = asset._images if asset._images else [asset.image]
    best_score = -1.0
    best_location = None
    best_size = None
    for template in templates:
        if template is None or template.size == 0:
            continue
        template_height, template_width = template.shape[:2]
        if template_height > source.shape[0] or template_width > source.shape[1]:
            continue
        result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if score > best_score:
            best_score = float(score)
            best_location = (
                int(location[0] + asset.roi_back[0]),
                int(location[1] + asset.roi_back[1]),
            )
            best_size = (int(template_width), int(template_height))
    return best_score, best_location, best_size


def _hsv_candidates(
    image: np.ndarray,
    band: tuple[int, int, int, int],
    min_area: int = 8,
) -> tuple[GreenMarkHsvCandidate, ...]:
    if image.ndim != 3 or image.shape[2] < 3:
        return ()
    rgb = image[:, :, :3]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(
        hsv,
        np.array((30, 80, 45), dtype=np.uint8),
        np.array((95, 255, 255), dtype=np.uint8),
    )
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    candidates = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        x = int(stats[index, cv2.CC_STAT_LEFT])
        y = int(stats[index, cv2.CC_STAT_TOP])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        center = (int(round(centroids[index][0])), int(round(centroids[index][1])))
        candidates.append(
            GreenMarkHsvCandidate(
                bbox=(x, y, width, height),
                center=center,
                area=area,
                inside_target=point_in_rect(center, band),
            )
        )
    return tuple(sorted(candidates, key=lambda item: (-item.area, item.center)))


def _canonical_slot_name(name: str) -> str:
    value = str(name).strip().lower()
    for index in range(1, 6):
        if value in {f'green_left{index}', f'green_left_{index}', f'left{index}'}:
            return f'green_left{index}'
    return value


def _canonical_slot_rois(
    slot_rois: Mapping[str, tuple[int, int, int, int]],
) -> dict[str, tuple[int, int, int, int]]:
    canonical = {}
    for name, roi in slot_rois.items():
        key = _canonical_slot_name(name)
        canonical[key] = tuple(int(value) for value in roi)
    return canonical


def assign_marker_slot(
    marker_tip: tuple[int, int],
    slot_rois: Mapping[str, tuple[int, int, int, int]],
) -> str | None:
    """Assign a marker tip to exactly one friendly slot by horizontal midlines."""
    canonical = _canonical_slot_rois(slot_rois)
    ordered = sorted(
        (
            (name, roi[0] + roi[2] / 2.0)
            for name, roi in canonical.items()
            if name.startswith('green_left')
        ),
        key=lambda item: item[1],
    )
    if not ordered:
        return None
    x = float(marker_tip[0])
    boundaries = [
        (ordered[index][1] + ordered[index + 1][1]) / 2.0
        for index in range(len(ordered) - 1)
    ]
    for index, boundary in enumerate(boundaries):
        if x < boundary:
            return ordered[index][0]
    return ordered[-1][0]


def _marker_color_masks(image: np.ndarray) -> tuple[tuple[str, np.ndarray], ...]:
    rgb = image[:, :, :3]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    green = cv2.inRange(
        hsv,
        np.array((30, 90, 60), dtype=np.uint8),
        np.array((95, 255, 255), dtype=np.uint8),
    )
    # The rendered enemy marker has a stable pink/magenta outline even when its
    # lower tip appears red. Low-red pixels alone are unsafe: health bars,
    # characters and battle effects fill most real battle frames with them.
    enemy = cv2.inRange(
        hsv,
        np.array((145, 105, 65), dtype=np.uint8),
        np.array((179, 255, 255), dtype=np.uint8),
    )
    return ('green', green), ('red', enemy)


def _is_down_arrow_component(component: np.ndarray) -> tuple[bool, float]:
    """Require a body plus a narrow, protruding lower tip instead of a color blob."""
    rows = np.flatnonzero(np.any(component > 0, axis=1))
    if rows.size < 8:
        return False, 0.0
    widths = np.count_nonzero(component[rows] > 0, axis=1)
    widest = int(widths.max(initial=0))
    if widest < 6:
        return False, 0.0
    tail_count = max(1, int(np.ceil(rows.size * 0.2)))
    tail_width = float(np.median(widths[-tail_count:]))
    narrowness = 1.0 - min(1.0, tail_width / float(widest))
    # A rectangle/circle has no isolated lower arrow tip. A mild threshold is
    # intentional because perspective and skill effects can partially occlude it.
    return narrowness >= 0.30, narrowness


def _marker_profile_matches(
    *,
    color: str,
    bbox: tuple[int, int, int, int],
    contour_area: float,
    fill_ratio: float,
    tip_score: float,
    symmetry: float,
    bottom_outer_fill: float,
) -> bool:
    x, y, width, height = bbox
    del x
    if color == 'green':
        return (
            28 <= width <= 82
            and 28 <= height <= 82
            and 250.0 <= contour_area <= 2600.0
            and 0.18 <= fill_ratio <= 0.78
            and tip_score >= 0.30
            and symmetry >= 0.62
            and bottom_outer_fill <= 0.12
        )

    # Normal enemy arrows in the current 1280x720 renderer are about 63x45.
    # The central boss marker can be clipped by the top edge, leaving only its
    # 29x20 magenta upper body. Keep that case explicit so unrelated red UI
    # fragments cannot silently widen the accepted profile.
    top_clipped = (
        y == 0
        and 20 <= width <= 42
        and 15 <= height <= 32
        and 220.0 <= contour_area <= 700.0
        and fill_ratio >= 0.35
        and tip_score >= 0.50
    )
    regular = (
        45 <= width <= 82
        and 35 <= height <= 68
        and 700.0 <= contour_area <= 2200.0
        and 0.32 <= fill_ratio <= 0.72
        and tip_score >= 0.45
    )
    return top_clipped or regular


def _marker_shape_features(component: np.ndarray) -> tuple[float, float]:
    normalized = cv2.resize(
        (component > 0).astype(np.uint8),
        (64, 64),
        interpolation=cv2.INTER_NEAREST,
    )
    mirrored = np.fliplr(normalized)
    union = int(np.logical_or(normalized, mirrored).sum())
    symmetry = float(np.logical_and(normalized, mirrored).sum()) / float(max(1, union))
    left_bottom = float(normalized[38:64, 0:18].mean())
    right_bottom = float(normalized[38:64, 46:64].mean())
    return symmetry, max(left_bottom, right_bottom)


def detect_colored_markers(image: np.ndarray) -> tuple[ColoredMarkerCandidate, ...]:
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] < 3:
        raise ValueError('colored marker detection requires an RGB image')
    candidates = []
    for color, mask in _marker_color_masks(image):
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            contour_area = float(cv2.contourArea(contour))
            if contour_area < 12.0 or contour_area > 5000.0:
                continue
            x, y, width, height = cv2.boundingRect(contour)
            if width < 6 or height < 8 or width > 120 or height > 120:
                continue
            component = np.zeros((height, width), dtype=np.uint8)
            shifted = contour - np.array([[[x, y]]], dtype=contour.dtype)
            cv2.drawContours(component, [shifted], -1, 255, thickness=cv2.FILLED)
            arrow_like, tip_score = _is_down_arrow_component(component)
            if not arrow_like:
                continue
            colored_component = cv2.bitwise_and(
                mask[y:y + height, x:x + width],
                component,
            )
            symmetry, bottom_outer_fill = _marker_shape_features(colored_component)
            points = contour.reshape(-1, 2)
            max_y = int(points[:, 1].max())
            tip_points = points[points[:, 1] == max_y]
            tip = (int(round(float(tip_points[:, 0].mean()))), max_y)
            moments = cv2.moments(contour)
            if moments['m00']:
                center = (
                    int(round(moments['m10'] / moments['m00'])),
                    int(round(moments['m01'] / moments['m00'])),
                )
            else:
                center = (x + width // 2, y + height // 2)
            fill_ratio = contour_area / float(max(1, width * height))
            if not _marker_profile_matches(
                color=color,
                bbox=(int(x), int(y), int(width), int(height)),
                contour_area=contour_area,
                fill_ratio=fill_ratio,
                tip_score=tip_score,
                symmetry=symmetry,
                bottom_outer_fill=bottom_outer_fill,
            ):
                continue
            area_score = min(1.0, contour_area / 120.0)
            confidence = max(
                0.0,
                min(1.0, 0.45 * tip_score + 0.35 * area_score + 0.20 * fill_ratio),
            )
            candidates.append(
                ColoredMarkerCandidate(
                    color=color,
                    bbox=(int(x), int(y), int(width), int(height)),
                    center=center,
                    tip=tip,
                    area=int(round(contour_area)),
                    confidence=float(confidence),
                )
            )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                0 if item.color == 'red' else 1,
                -item.confidence,
                -item.area,
                item.tip,
            ),
        )
    )


def classify_marker_frame(
    image: np.ndarray,
    *,
    expected_slot: str,
    slot_rois: Mapping[str, tuple[int, int, int, int]],
) -> GreenMarkerFrameObservation:
    """Classify one frame without ever authorizing a confirmed result."""
    canonical_rois = _canonical_slot_rois(slot_rois)
    expected = _canonical_slot_name(expected_slot)
    digest = frame_sha256(image)
    classified = []
    for candidate in detect_colored_markers(image):
        if candidate.color == 'red':
            # Enemy markers occupy the battlefield, not the bottom skill bar.
            # They have their own ownership semantics and must not be forced
            # through friendly-slot confirmation bands.
            if not (
                20 <= candidate.tip[0] < image.shape[1] - 20
                and 0 <= candidate.tip[1] < int(image.shape[0] * 0.55)
            ):
                continue
            classified.append((candidate, 'enemy', 'enemy_selected'))
            continue
        assigned = assign_marker_slot(candidate.tip, canonical_rois)
        if assigned is None:
            continue
        if not 0 <= candidate.tip[1] < int(image.shape[0] * 0.60):
            continue
        roi = canonical_rois.get(assigned)
        if roi is None:
            continue
        band = confirmation_band(roi, (image.shape[1], image.shape[0]))
        if not point_in_rect(candidate.tip, band):
            continue
        if assigned == expected:
            observation = 'expected_candidate'
        else:
            observation = 'wrong_target'
        classified.append((candidate, assigned, observation))
    if not classified:
        return GreenMarkerFrameObservation(
            frame_sha256=digest,
            expected_slot=expected,
            observation='not_found',
            reason='no complete red or green arrow candidate was found',
        )
    # Enemy and friendly markers can coexist: the game keeps an independent red
    # enemy target while a green ally target is active.  Green verification must
    # therefore use the friendly marker whenever one is valid.  A red marker is
    # only decisive when no valid friendly marker is visible.
    classified.sort(
        key=lambda item: (
            0 if item[0].color == 'green' else 1,
            0 if item[2] == 'expected_candidate' else 1,
            -item[0].confidence,
            -item[0].area,
        )
    )
    candidate, assigned, observation = classified[0]
    return GreenMarkerFrameObservation(
        frame_sha256=digest,
        expected_slot=expected,
        observation=observation,
        color=candidate.color,
        assigned_slot=assigned,
        marker_tip=candidate.tip,
        bbox=candidate.bbox,
        area=candidate.area,
        confidence=candidate.confidence,
        reason=f'{candidate.color} arrow tip assigned to {assigned}',
    )


def resolve_stable_marker_frames(
    frames: Sequence[GreenMarkerFrameObservation],
    *,
    expected_slot: str,
    required: int = 2,
    window: int = 3,
) -> GreenMarkResult:
    """Require the same color, slot and semantic result in 2/3 frames."""
    expected = _canonical_slot_name(expected_slot)
    unique = []
    seen_hashes = set()
    for item in frames:
        if item.frame_sha256 in seen_hashes:
            continue
        seen_hashes.add(item.frame_sha256)
        unique.append(item)
    recent = tuple(unique[-max(1, int(window)):])
    keys = [
        (item.color, item.assigned_slot, item.observation)
        for item in recent
        if item.color and item.assigned_slot and item.observation != 'not_found'
    ]
    counts = Counter(keys)
    best_key, best_count = (counts.most_common(1)[0] if counts else ((None, None, None), 0))
    color, assigned, observation = best_key
    matching = [
        item
        for item in recent
        if (item.color, item.assigned_slot, item.observation) == best_key
    ]
    latest = matching[-1] if matching else (recent[-1] if recent else None)
    if best_count >= max(2, int(required)):
        status = {
            'expected_candidate': 'confirmed',
            'wrong_target': 'wrong_target',
            'enemy_selected': 'enemy_selected',
        }.get(observation, 'unconfirmed')
        reason = f'{best_count}/{len(recent)} stable frames: {observation}'
    else:
        status = 'unconfirmed'
        reason = f'stable marker evidence is insufficient: {best_count}/{max(2, int(required))}'
    confidence = None
    if matching:
        confidence = float(sum(item.confidence for item in matching) / len(matching))
    return GreenMarkResult(
        status=status,
        target=expected,
        marker_point=getattr(latest, 'marker_tip', None),
        detector='color-contour-tip-slot',
        frame_sha256=getattr(latest, 'frame_sha256', None),
        reason=reason,
        color=color,
        expected_slot=expected,
        assigned_slot=assigned,
        marker_tip=getattr(latest, 'marker_tip', None),
        stable_frames=int(best_count),
        confidence=confidence,
    )


def diagnose_green_marker(
    image: np.ndarray,
    *,
    target_name: str,
    target_roi: tuple[int, int, int, int],
    template_assets: Iterable,
) -> GreenMarkDiagnostic:
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] < 3:
        raise ValueError('green marker diagnostics require an RGB image')
    height, width = image.shape[:2]
    band = confirmation_band(target_roi, (width, height))
    template_results = []
    for asset in template_assets:
        score, top_left, size = _best_template_match(image, asset)
        center = None
        if top_left is not None and size is not None:
            center = (top_left[0] + size[0] // 2, top_left[1] + size[1] // 2)
        inside_target = point_in_rect(center, band)
        template_results.append(
            GreenMarkTemplateDiagnostic(
                name=asset.name,
                threshold=float(asset.threshold),
                max_score=score,
                top_left=top_left,
                center=center,
                size=size,
                inside_target=inside_target,
                matched=score > float(asset.threshold),
            )
        )
    templates = tuple(template_results)
    return GreenMarkDiagnostic(
        frame_sha256=frame_sha256(image),
        frame_size=(width, height),
        target_name=target_name,
        target_roi=tuple(int(value) for value in target_roi),
        confirmation_band=band,
        templates=templates,
        hsv_candidates=_hsv_candidates(image, band),
        template_confirmed=any(item.matched and item.inside_target for item in templates),
    )
