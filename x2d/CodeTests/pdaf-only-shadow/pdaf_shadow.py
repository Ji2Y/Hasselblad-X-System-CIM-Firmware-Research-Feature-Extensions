"""Offline, PDAF-only X2D focus-position shadow evaluator.

This module has no camera, USB, AF-library, or lens-command integration.  Its
input is a *normalized* zone record, not the unverified Type3 binary ABI.
"""

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple


@dataclass(frozen=True)
class Rect:
    # Normalized sensor coordinates in integer units [0, 10000].
    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True)
class Zone:
    rect: Rect
    frame_id: int
    confidence: int  # Normalized [0, 1000], *not* a raw Type3 score.
    target_steps: int  # Calibrated absolute lens position; ABI not established.
    step_direction: int  # Signed direction in calibrated step space: -1, 0, +1.


@dataclass(frozen=True)
class Gate:
    min_zones: int
    max_zones: int
    min_confidence: int
    min_coverage_permille: int
    max_frame_lag: int
    max_spread_steps: int
    max_move_steps: int


@dataclass(frozen=True)
class Decision:
    stock_path_required: bool
    reason: str
    shadow_target_steps: Optional[int]
    accepted_zones: int
    coverage_permille: int


@dataclass(frozen=True)
class FrameSample:
    frame_id: int
    decision: Decision


def _valid_rect(rect: Rect) -> bool:
    return (
        isinstance(rect, Rect)
        and all(type(v) is int for v in (rect.left, rect.top, rect.right, rect.bottom))
        and 0 <= rect.left < rect.right <= 10000
        and 0 <= rect.top < rect.bottom <= 10000
    )


def _intersection(a: Rect, b: Rect) -> Optional[Rect]:
    result = Rect(max(a.left, b.left), max(a.top, b.top),
                  min(a.right, b.right), min(a.bottom, b.bottom))
    return result if result.left < result.right and result.top < result.bottom else None


def _union_area(rects: Sequence[Rect]) -> int:
    """Exact rectangle-union area, including overlapping phase regions."""
    xs = sorted({x for r in rects for x in (r.left, r.right)})
    area = 0
    for left, right in zip(xs, xs[1:]):
        spans = sorted((r.top, r.bottom) for r in rects
                       if r.left < right and r.right > left)
        if not spans:
            continue
        top, bottom = spans[0]
        height = 0
        for next_top, next_bottom in spans[1:]:
            if next_top > bottom:
                height += bottom - top
                top, bottom = next_top, next_bottom
            else:
                bottom = max(bottom, next_bottom)
        height += bottom - top
        area += (right - left) * height
    return area


def _fallback(reason: str, count: int = 0, coverage: int = 0) -> Decision:
    # The caller must leave its original AF path and original parameters intact.
    return Decision(True, reason, None, count, coverage)


def evaluate_shadow(zones: Sequence[Zone], roi: Rect, *, frame_id: int,
                    current_steps: int, far_steps: int, near_steps: int,
                    gate: Gate) -> Decision:
    """Evaluate a position suggestion, never issue or authorize a lens command.

    Missing, malformed, stale, contradictory, or out-of-range data never
    produces a target. The original path remains required even when a shadow
    target exists; no runtime hook exists in this experiment.
    """
    if not isinstance(gate, Gate):
        return _fallback("invalid_limits_or_gate")
    ints = (frame_id, current_steps, far_steps, near_steps, gate.min_zones,
            gate.max_zones,
            gate.min_confidence, gate.min_coverage_permille, gate.max_frame_lag,
            gate.max_spread_steps, gate.max_move_steps)
    if not _valid_rect(roi) or not all(type(v) is int for v in ints):
        return _fallback("invalid_input")
    if not (0 <= far_steps <= current_steps <= near_steps
            and 2 <= gate.min_zones <= gate.max_zones
            and 0 <= gate.min_confidence <= 1000
            and 0 <= gate.min_coverage_permille <= 1000
            and gate.max_frame_lag >= 0
            and gate.max_spread_steps >= 0
            and gate.max_move_steps >= 0):
        return _fallback("invalid_limits_or_gate")
    if zones is None:
        return _fallback("missing_zones")
    if not isinstance(zones, Sequence):
        return _fallback("invalid_zones_container")
    if len(zones) > gate.max_zones:
        return _fallback("too_many_zones")

    accepted: list[Tuple[int, int]] = []
    clipped: list[Rect] = []
    try:
        for zone in zones:
            if not isinstance(zone, Zone) or not _valid_rect(zone.rect):
                return _fallback("invalid_zone")
            if not all(type(v) is int for v in
                       (zone.frame_id, zone.confidence, zone.target_steps,
                        zone.step_direction)):
                return _fallback("invalid_zone")
            lag = frame_id - zone.frame_id
            if lag < 0 or lag > gate.max_frame_lag:
                return _fallback("stale_or_future_frame")
            if not 0 <= zone.confidence <= 1000:
                return _fallback("invalid_confidence")
            if zone.confidence < gate.min_confidence:
                continue
            if zone.step_direction not in (-1, 0, 1):
                return _fallback("invalid_direction")
            if not far_steps <= zone.target_steps <= near_steps:
                return _fallback("target_outside_lens_limits")
            overlap = _intersection(roi, zone.rect)
            if overlap is None:
                continue
            area = (overlap.right - overlap.left) * (overlap.bottom - overlap.top)
            accepted.append((zone.target_steps, area * zone.confidence))
            clipped.append(overlap)
    except (TypeError, ValueError, IndexError):
        return _fallback("invalid_zones_container")

    count = len(accepted)
    roi_area = (roi.right - roi.left) * (roi.bottom - roi.top)
    coverage = 1000 * _union_area(clipped) // roi_area if clipped else 0
    if count < gate.min_zones:
        return _fallback("too_few_valid_zones", count, coverage)
    if coverage < gate.min_coverage_permille:
        return _fallback("insufficient_roi_coverage", count, coverage)
    positions = [position for position, _ in accepted]
    if max(positions) - min(positions) > gate.max_spread_steps:
        return _fallback("inconsistent_zone_targets", count, coverage)
    directions = {zone.step_direction for zone in zones
                  if isinstance(zone, Zone) and zone.confidence >= gate.min_confidence
                  and _intersection(roi, zone.rect) is not None}
    if len(directions) != 1:
        return _fallback("inconsistent_zone_directions", count, coverage)
    weighted = sorted(accepted)
    half_weight = (sum(weight for _, weight in weighted) + 1) // 2
    cumulative = 0
    target = weighted[-1][0]
    for position, weight in weighted:
        cumulative += weight
        if cumulative >= half_weight:
            target = position
            break
    if abs(target - current_steps) > gate.max_move_steps:
        return _fallback("movement_gate", count, coverage)
    expected_direction = (target > current_steps) - (target < current_steps)
    if directions != {expected_direction}:
        return _fallback("direction_target_mismatch", count, coverage)
    return Decision(True, "shadow_only", target, count, coverage)


def evaluate_temporal_shadow(samples: Sequence[FrameSample], *, current_frame: int,
                             min_frames: int = 3, max_frame_lag: int = 1,
                             max_target_spread_steps: int = 20) -> Decision:
    """Require consecutive, agreeing *shadow* frames; stock AF always runs.

    The thresholds are explicit offline hypotheses, not X2D or X2D II values.
    """
    if not all(type(v) is int for v in
               (current_frame, min_frames, max_frame_lag, max_target_spread_steps)):
        return _fallback("invalid_temporal_gate")
    if min_frames < 3 or max_frame_lag < 0 or max_target_spread_steps < 0:
        return _fallback("invalid_temporal_gate")
    if not isinstance(samples, Sequence) or len(samples) < min_frames:
        return _fallback("insufficient_stable_frames")
    selected = samples[-min_frames:]
    if not all(isinstance(item, FrameSample)
               and type(item.frame_id) is int
               and isinstance(item.decision, Decision)
               for item in selected):
        return _fallback("invalid_frame_sample")
    frame_ids = [item.frame_id for item in selected]
    if any(right != left + 1 for left, right in zip(frame_ids, frame_ids[1:])):
        return _fallback("nonconsecutive_frames")
    if current_frame < frame_ids[-1] or current_frame - frame_ids[-1] > max_frame_lag:
        return _fallback("stale_or_future_frame")
    if any(item.decision.reason != "shadow_only"
           or item.decision.stock_path_required is not True
           or type(item.decision.shadow_target_steps) is not int
           for item in selected):
        return _fallback("unstable_or_rejected_frame")
    positions = sorted(item.decision.shadow_target_steps for item in selected)
    if positions[-1] - positions[0] > max_target_spread_steps:
        return _fallback("unstable_target_over_time")
    return Decision(True, "stable_shadow_only", positions[len(positions) // 2],
                    min(item.decision.accepted_zones for item in selected),
                    min(item.decision.coverage_permille for item in selected))
