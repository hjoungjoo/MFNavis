"""Frame-wise Auto(Star) exposure and analogue-gain control.

The camera process owns this controller.  It evaluates every released RAW
request, but it never assumes that a submitted libcamera control has already
reached the sensor: ordinary updates are held until captured metadata confirms
the requested exposure/gain pair.  Plate-solver feedback is deliberately a
slower quality input and never writes camera controls itself.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Mapping, Optional

import numpy as np
from scipy import ndimage


GAIN_LADDER = (30.0, 15.0, 8.0, 4.0, 2.0, 1.0)
REGION_NAMES = ("UL", "U", "UR", "L", "C", "R", "DL", "D", "DR")
PERIPHERAL_REGIONS = frozenset(REGION_NAMES) - {"C"}

# A 2026-09-04 on-sky sweep (200/280/400/450/560 ms, IMX462 gain 29.51)
# found the useful maximum at 400 ms: 19-26 catalog matches while the robust
# CFA-cell-max p99.9 of usable peripheral regions was 82.6-83.6% of full
# scale. At 450 ms it reached 87.4% without adding matches; at 560 ms
# saturation spread into the centre/right and solve reliability collapsed.
# Drive this robust highlight statistic, rather than the broad sky median, so
# Auto(Star) can expose faint stars close to the sensor headroom limit.
USABLE_HIGHLIGHT_TARGET_FRACTION = 0.84
USABLE_HIGHLIGHT_LOW_FRACTION = 0.78
USABLE_HIGHLIGHT_HIGH_FRACTION = 0.87
USABLE_HIGHLIGHT_DOWN_P99_FRACTION = 0.68
USABLE_BACKGROUND_TARGET_FRACTION = 0.52
USABLE_BACKGROUND_HIGH_FRACTION = 0.60
PERIPHERAL_SATURATED_AREA_FRACTION = 0.005
PERIPHERAL_BROAD_HIGHLIGHT_FRACTION = 0.85
MIN_USABLE_PERIPHERAL_REGIONS = 4
MIN_HARD_SATURATED_PERIPHERAL_REGIONS = 4
# Three clean peripheral tiles still provide a sky sample when nearby lamps
# occupy the other tiles. This exception requires background and highlight
# headroom in the remaining sky; broad sky glow/bloom retains its guard.
MIN_LOCAL_LIGHT_SKY_REGIONS = 3
SATURATION_CEILING_PROBE_S = 30.0
HIGHLIGHT_RAISE_CONFIRM_FRAMES = 3
# A lost solve must not permanently prevent the exposure needed to reacquire
# stars. Hold transient obscuration, then probe slowly using measured RAW
# headroom. These timers affect exposure controls, not solver preprocessing.
REACQUISITION_HOLD_S = 10.0
REACQUISITION_PROBE_S = 5.0


@dataclass(frozen=True)
class RegionExposureStats:
    background_p50_adu: float
    background_mad_adu: float
    p90_adu: float
    p99_adu: float
    p999_adu: float
    saturated_fraction: float
    background_gradient_adu: float
    usable: bool = True

    @property
    def point_contrast(self) -> float:
        noise = max(1.4826 * self.background_mad_adu, 1.0)
        return max(0.0, self.p99_adu - self.background_p50_adu) / noise


@dataclass(frozen=True)
class FrameExposureSample:
    frame_id: int
    frame_sequence: int
    captured_at: float
    actual_exposure_us: float
    actual_gain: float
    white_level: float
    pedestal_adu: float
    regions: Mapping[str, RegionExposureStats]
    center_contaminated: bool = False
    motion_degrees: float = 0.0

    def peripheral(self) -> tuple[RegionExposureStats, ...]:
        return tuple(
            stats
            for name, stats in self.regions.items()
            if name in PERIPHERAL_REGIONS and stats.usable
        )


@dataclass(frozen=True)
class SolveExposureQuality:
    frame_id: int
    source: str
    region_ids: tuple[str, ...]
    matched_stars: int
    candidate_stars: int
    snr_p25: Optional[float]
    snr_median: Optional[float]
    rmse: Optional[float]
    solve_success: bool
    center_contaminated: bool = False

    @property
    def peripheral(self) -> bool:
        return self.source.startswith("peripheral") or any(
            region != "C" for region in self.region_ids
        )

    @property
    def candidate_pressure(self) -> float:
        return max(0.0, self.candidate_stars - self.matched_stars) / max(
            1, self.matched_stars
        )

    @property
    def score(self) -> float:
        # Matches dominate.  SNR is a tie-breaker and unmatched detections are
        # a penalty, not an assertion that every unused candidate is false.
        score = 20.0 if self.solve_success else 0.0
        score += 2.0 * self.matched_stars
        score += min(20.0, max(0.0, self.snr_median or 0.0))
        score -= min(100.0, self.candidate_pressure)
        return score


@dataclass(frozen=True)
class ExposureGainTarget:
    exposure_us: int
    gain: float
    reason: str
    safety: bool = False


@dataclass
class PendingControl:
    target: ExposureGainTarget
    request_sequence: int
    requested_at: float


@dataclass
class ExposureGainAllocator:
    min_exposure_us: int = 1_000
    max_exposure_us: int = 1_000_000
    preferred_exposure_us: int = 200_000
    max_gain: float = 30.0
    min_gain: float = 1.0
    gain_ladder: tuple[float, ...] = GAIN_LADDER

    def __post_init__(self) -> None:
        ladder = {
            min(self.max_gain, max(self.min_gain, float(gain)))
            for gain in self.gain_ladder
            if self.min_gain <= gain <= self.max_gain
        }
        ladder.update((self.max_gain, self.min_gain))
        self.gain_ladder = tuple(sorted(ladder, reverse=True))

    def clamp_exposure(
        self, value: float, motion_limit_us: Optional[int] = None
    ) -> int:
        upper = self.max_exposure_us
        if motion_limit_us is not None:
            upper = min(upper, max(self.min_exposure_us, int(motion_limit_us)))
        return int(round(min(upper, max(self.min_exposure_us, value))))

    def clamp_gain(self, value: float) -> float:
        return min(self.max_gain, max(self.min_gain, float(value)))

    def adjacent_gain(self, current: float, direction: int) -> Optional[float]:
        index = min(
            range(len(self.gain_ladder)),
            key=lambda i: abs(self.gain_ladder[i] - current),
        )
        target_index = index + direction
        if 0 <= target_index < len(self.gain_ladder):
            return self.gain_ladder[target_index]
        return None

    def preserve_light(
        self,
        exposure_us: float,
        gain: float,
        target_gain: float,
        *,
        motion_limit_us: Optional[int] = None,
    ) -> tuple[int, float]:
        target_gain = self.clamp_gain(target_gain)
        target_exposure = exposure_us * max(gain, self.min_gain) / target_gain
        return self.clamp_exposure(target_exposure, motion_limit_us), target_gain


def _region_stats(values: np.ndarray, white_level: float) -> RegionExposureStats:
    values = np.asarray(values, dtype=np.float32)
    p50, p90, p99, p999 = np.percentile(values, (50.0, 90.0, 99.0, 99.9))
    mad = float(np.median(np.abs(values - p50)))
    mid_y, mid_x = values.shape[0] // 2, values.shape[1] // 2
    quadrants = (
        values[:mid_y, :mid_x],
        values[:mid_y, mid_x:],
        values[mid_y:, :mid_x],
        values[mid_y:, mid_x:],
    )
    medians = [float(np.median(part)) for part in quadrants if part.size]
    return RegionExposureStats(
        background_p50_adu=float(p50),
        background_mad_adu=mad,
        p90_adu=float(p90),
        p99_adu=float(p99),
        p999_adu=float(p999),
        saturated_fraction=float(np.mean(values >= white_level - 1.0)),
        background_gradient_adu=max(medians) - min(medians),
        usable=values.size >= 64,
    )


def collect_spatial_frame_sample(
    raw,
    *,
    frame_id: int,
    frame_sequence: int,
    actual_exposure_us: float,
    actual_gain: float,
    bit_depth: int,
    pedestal_adu: float,
    captured_at: Optional[float] = None,
    motion_degrees: float = 0.0,
    stride: int = 4,
) -> Optional[FrameExposureSample]:
    """Reduce one linear RAW frame to a sparse 3x3 spatial sample.

    The connected-component test runs on the already sparse image. For Bayer
    RAW, each 2x2 CFA cell is reduced before spatial decimation; direct
    ``raw[::stride, ::stride]`` sampling selects only one colour phase and made
    exposure statistics change when the same frame was rotated for display.
    The maximum of the four CFA samples keeps the measurement independent of
    Bayer phase while retaining the brightest colour response and sensor
    clipping; an average diluted exactly the headroom signal being controlled.
    This keeps the fast path small and also catches a central moon/bloom without
    making a full-resolution mask in the camera's latency-sensitive path.
    """
    image = np.asarray(raw)
    if image.ndim != 2 or min(image.shape) < 48 or stride < 1:
        return None
    height = image.shape[0] - image.shape[0] % 2
    width = image.shape[1] - image.shape[1] % 2
    cell_stride = max(1, int(round(stride / 2)))
    sample_step = 2 * cell_stride
    # Reduce only CFA cells that survive the requested spatial stride. Building
    # a full half-resolution CFA image first spent 18-28 ms per live frame and
    # then discarded most of it at the default stride=4.
    sparse = np.maximum.reduce(
        (
            image[0:height:sample_step, 0:width:sample_step],
            image[0:height:sample_step, 1:width:sample_step],
            image[1:height:sample_step, 0:width:sample_step],
            image[1:height:sample_step, 1:width:sample_step],
        )
    )
    if min(sparse.shape) < 12:
        return None
    white_level = float(2 ** int(bit_depth) - 1)
    y_edges = np.linspace(0, sparse.shape[0], 4, dtype=int)
    x_edges = np.linspace(0, sparse.shape[1], 4, dtype=int)
    regions: dict[str, RegionExposureStats] = {}
    index = 0
    for row in range(3):
        for col in range(3):
            values = sparse[
                y_edges[row] : y_edges[row + 1],
                x_edges[col] : x_edges[col + 1],
            ]
            regions[REGION_NAMES[index]] = _region_stats(values, white_level)
            index += 1

    # A large high-level connected component intersecting the middle third is
    # a better moon/bloom indicator than a fixed central circle.
    hot_threshold = max(
        pedestal_adu + 0.60 * (white_level - pedestal_adu), 0.85 * white_level
    )
    hot = sparse >= hot_threshold
    labels, count = ndimage.label(hot)
    center_contaminated = False
    if count:
        center = np.zeros_like(hot, dtype=bool)
        center[y_edges[1] : y_edges[2], x_edges[1] : x_edges[2]] = True
        minimum_blob = max(16, int(hot.size * 0.001))
        for label_id in np.unique(labels[center]):
            if label_id and np.count_nonzero(labels == label_id) >= minimum_blob:
                center_contaminated = True
                break
    center_stats = regions["C"]
    center_contaminated = center_contaminated or (
        center_stats.p999_adu >= 0.92 * white_level
        or center_stats.saturated_fraction >= 0.001
    )

    return FrameExposureSample(
        frame_id=int(frame_id),
        frame_sequence=int(frame_sequence),
        captured_at=float(time.time() if captured_at is None else captured_at),
        actual_exposure_us=float(actual_exposure_us),
        actual_gain=float(actual_gain),
        white_level=white_level,
        pedestal_adu=float(pedestal_adu),
        regions=regions,
        center_contaminated=center_contaminated,
        motion_degrees=float(motion_degrees),
    )


def matched_star_exposure_quality(
    raw,
    matched_centroids,
    *,
    frame_id: int,
    candidate_stars: int,
    bit_depth: int,
    source: str = "peripheral_full",
    rmse: Optional[float] = None,
) -> dict[str, object]:
    """Measure catalog-matched stars on their original full-resolution RAW.

    Coordinates use tetra3's ``(y, x)`` convention and must already be mapped
    back from the rotated solver canvas.  A large saturated connected component
    is dilated to exclude moon/bloom pixels; the middle third is excluded from
    the quality aggregate even when it is not saturated.
    """
    image = np.asarray(raw, dtype=np.float32)
    points = np.asarray(matched_centroids, dtype=np.float64).reshape(-1, 2)
    height, width = image.shape
    white = float(2 ** int(bit_depth) - 1)
    saturated = image >= 0.85 * white
    labels, count = ndimage.label(saturated)
    moon_mask = np.zeros_like(saturated)
    minimum_blob = max(32, int(image.size * 0.0005))
    if count:
        sizes = np.bincount(labels.ravel())
        large_ids = np.flatnonzero(sizes >= minimum_blob)
        large_ids = large_ids[large_ids != 0]
        if large_ids.size:
            moon_mask = np.isin(labels, large_ids)
            moon_mask = ndimage.binary_dilation(moon_mask, iterations=12)

    y0, y1 = height / 3.0, 2.0 * height / 3.0
    x0, x1 = width / 3.0, 2.0 * width / 3.0
    center_contaminated = bool(
        np.mean(saturated[int(y0) : int(y1), int(x0) : int(x1)]) >= 0.001
        or np.any(moon_mask[int(y0) : int(y1), int(x0) : int(x1)])
    )
    scale = min(height, width) / 512.0
    aperture_radius = max(3.0, 3.0 * scale)
    inner_radius = 1.8 * aperture_radius
    outer_radius = 3.0 * aperture_radius
    region_ids: list[str] = []
    snrs: list[float] = []
    used = 0
    for y_float, x_float in points:
        y, x = float(y_float), float(x_float)
        if y0 <= y < y1 and x0 <= x < x1:
            continue
        if (
            y - outer_radius < 0
            or x - outer_radius < 0
            or y + outer_radius >= height
            or x + outer_radius >= width
        ):
            continue
        yy0, yy1 = int(y - outer_radius), int(y + outer_radius) + 1
        xx0, xx1 = int(x - outer_radius), int(x + outer_radius) + 1
        patch = image[yy0:yy1, xx0:xx1]
        mask_patch = moon_mask[yy0:yy1, xx0:xx1]
        yy, xx = np.ogrid[yy0:yy1, xx0:xx1]
        radius2 = (yy - y) ** 2 + (xx - x) ** 2
        aperture = radius2 <= aperture_radius**2
        annulus = (radius2 >= inner_radius**2) & (radius2 <= outer_radius**2)
        if (
            np.any(mask_patch & aperture)
            or np.count_nonzero(annulus & ~mask_patch) < 16
        ):
            continue
        annulus_values = patch[annulus & ~mask_patch]
        background = float(np.median(annulus_values))
        mad = float(np.median(np.abs(annulus_values - background)))
        aperture_values = patch[aperture & ~mask_patch]
        signal = float(np.sum(aperture_values - background))
        noise = max(1.4826 * mad * math.sqrt(aperture_values.size), 1.0)
        snrs.append(max(0.0, signal / noise))
        row = min(2, max(0, int(3 * y / height)))
        col = min(2, max(0, int(3 * x / width)))
        region_ids.append(REGION_NAMES[row * 3 + col])
        used += 1

    return {
        "frame_id": int(frame_id),
        "source": source,
        "region_ids": tuple(sorted(set(region_ids))),
        "matched_stars": used,
        "candidate_stars": int(candidate_stars),
        "snr_p25": float(np.percentile(snrs, 25)) if snrs else None,
        "snr_median": float(np.median(snrs)) if snrs else None,
        "rmse": float(rmse) if rmse is not None else None,
        "solve_success": bool(used),
        "center_contaminated": center_contaminated,
    }


def _robust_median(values: list[float]) -> Optional[float]:
    return float(np.median(values)) if values else None


class AutoStarFrameController:
    """Delay-aware supervisory controller for Auto(Star) v2."""

    def __init__(
        self,
        allocator: ExposureGainAllocator,
        *,
        gain_locked: bool = False,
        pending_timeout_frames: int = 9,
        anchor_trust_s: float = 90.0,
        false_candidate_repeats: int = 3,
        gain_min_dwell_frames: int = 8,
        gain_retry_cooldown_s: float = 90.0,
        highlight_raise_confirm_frames: int = HIGHLIGHT_RAISE_CONFIRM_FRAMES,
    ) -> None:
        self.allocator = allocator
        self.gain_locked = gain_locked
        self.pending_timeout_frames = pending_timeout_frames
        self.anchor_trust_s = anchor_trust_s
        self.false_candidate_repeats = false_candidate_repeats
        self.gain_min_dwell_frames = gain_min_dwell_frames
        self.gain_retry_cooldown_s = gain_retry_cooldown_s
        self.highlight_raise_confirm_frames = max(
            1, int(highlight_raise_confirm_frames)
        )
        self.reset()

    def reset(self, *, gain_locked: Optional[bool] = None) -> None:
        if gain_locked is not None:
            self.gain_locked = gain_locked
        self.pending: Optional[PendingControl] = None
        self._frames: deque[FrameExposureSample] = deque(maxlen=64)
        self._frames_by_id: dict[int, FrameExposureSample] = {}
        self._anchor_sample: Optional[FrameExposureSample] = None
        self._anchor_quality: Optional[SolveExposureQuality] = None
        self._anchor_at = 0.0
        self._latest_quality: Optional[SolveExposureQuality] = None
        self._pressure_streak = 0
        self._good_quality_streak = 0
        self._saturation_at_min_streak = 0
        self._saturation_light_ceiling: Optional[float] = None
        self._saturation_ceiling_at = 0.0
        self._gain_action: Optional[tuple[str, float, Optional[float]]] = None
        self._trial_baseline: Optional[SolveExposureQuality] = None
        self._trial_gain: Optional[float] = None
        self._trial_kind: Optional[str] = None
        self._trial_rollback_gain: Optional[float] = None
        self._last_gain_change_sequence = -10_000
        self._gain_retry_after = 0.0
        self._control_fault = False
        self._reason = "reset"
        self._last_applied_after_frames: Optional[int] = None
        self._direction_reversals = 0
        self._last_direction = 0
        self._highlight_low_streak = 0
        self._reacquisition_since: Optional[float] = None
        self._reacquisition_probe_at: Optional[float] = None

    def _reset_reacquisition(self) -> None:
        self._reacquisition_since = None
        self._reacquisition_probe_at = None

    def _reacquisition_target(
        self, sample: FrameExposureSample, highlight_fraction: float
    ) -> Optional[ExposureGainTarget]:
        if self._reacquisition_since is None:
            self._reacquisition_since = sample.captured_at
        if sample.captured_at - self._reacquisition_since < REACQUISITION_HOLD_S:
            self._highlight_low_streak = 0
            return None
        if (
            self._reacquisition_probe_at is not None
            and sample.captured_at - self._reacquisition_probe_at
            < REACQUISITION_PROBE_S
        ):
            self._highlight_low_streak = 0
            return None
        if not self._highlight_raise_confirmed():
            return None
        ratio = USABLE_HIGHLIGHT_TARGET_FRACTION / max(highlight_fraction, 1e-6)
        target = self._target(
            sample,
            sample.actual_exposure_us * min(math.sqrt(2.0), ratio),
            sample.actual_gain,
            "reacquisition_exposure_up",
        )
        if target is not None:
            self._reacquisition_probe_at = sample.captured_at
        return target

    def _highlight_raise_confirmed(self) -> bool:
        self._highlight_low_streak += 1
        if self._highlight_low_streak < self.highlight_raise_confirm_frames:
            self._reason = "highlight_headroom_low_confirm"
            return False
        self._highlight_low_streak = 0
        return True

    @staticmethod
    def _matches(
        actual_exposure: float, actual_gain: float, target: ExposureGainTarget
    ) -> bool:
        exposure_ok = abs(actual_exposure - target.exposure_us) <= max(
            100.0, 0.02 * target.exposure_us
        )
        gain_ok = abs(actual_gain - target.gain) <= max(0.75, 0.03 * target.gain)
        return exposure_ok and gain_ok

    def mark_submitted(
        self,
        target: ExposureGainTarget,
        frame_sequence: int,
        requested_at: Optional[float] = None,
    ) -> None:
        self.pending = PendingControl(
            target=target,
            request_sequence=int(frame_sequence),
            requested_at=float(
                time.monotonic() if requested_at is None else requested_at
            ),
        )
        self._reason = target.reason

    def _remember_frame(self, sample: FrameExposureSample) -> None:
        if len(self._frames) == self._frames.maxlen:
            oldest = self._frames[0]
            self._frames_by_id.pop(oldest.frame_id, None)
        self._frames.append(sample)
        self._frames_by_id[sample.frame_id] = sample

    @staticmethod
    def _region_is_broadly_saturated(
        sample: FrameExposureSample, region: RegionExposureStats
    ) -> bool:
        return bool(
            region.saturated_fraction >= PERIPHERAL_SATURATED_AREA_FRACTION
            or (
                region.p999_adu >= 0.94 * sample.white_level
                and region.p99_adu
                >= PERIPHERAL_BROAD_HIGHLIGHT_FRACTION * sample.white_level
            )
        )

    @classmethod
    def _peripheral_summary(
        cls, sample: FrameExposureSample
    ) -> dict[str, Optional[float]]:
        all_regions = sample.peripheral()
        regions = tuple(
            region
            for region in all_regions
            if not cls._region_is_broadly_saturated(sample, region)
        )
        if not regions:
            regions = all_regions

        # One bright star or warm-pixel cluster can own a region's maximum.
        # The upper quartile across spatial regions still follows widespread
        # stellar headroom, while a local streetlight/horizon band is removed
        # above. This is the statistic calibrated by the on-sky sweep.
        p99_values = [r.p99_adu for r in regions]
        p999_values = [r.p999_adu for r in regions]
        return {
            "p50": _robust_median([r.background_p50_adu for r in regions]),
            "p99": (float(np.percentile(p99_values, 75)) if p99_values else None),
            "p999": (float(np.percentile(p999_values, 75)) if p999_values else None),
            "sat": max((r.saturated_fraction for r in regions), default=None),
            "contrast": _robust_median([r.point_contrast for r in regions]),
            "usable_regions": float(len(regions)),
            "contaminated_regions": float(len(all_regions) - len(regions)),
        }

    @staticmethod
    def _hard_peripheral_saturation(sample: FrameExposureSample) -> bool:
        """Return true only when a meaningful peripheral area is clipped.

        Several nearby lamps can each clip a small part of separate tiles.
        Counting those tiles alone drove a dark low-altitude sky down to 3 ms.
        With at least three clean sky tiles and headroom in their statistics,
        let the filtered sky statistics drive exposure. Broad sky glow/bloom
        and a field with too little clean sky retain the immediate reduction.
        """
        regions = sample.peripheral()
        saturated_regions = sum(
            1
            for region in regions
            if AutoStarFrameController._region_is_broadly_saturated(sample, region)
        )
        usable_regions = len(regions) - saturated_regions
        if usable_regions >= MIN_LOCAL_LIGHT_SKY_REGIONS:
            sky = AutoStarFrameController._peripheral_summary(sample)
            usable_range = max(1.0, sample.white_level - sample.pedestal_adu)
            p50, p99 = sky["p50"], sky["p99"]
            if (
                p50 is not None
                and p99 is not None
                and (p50 - sample.pedestal_adu) / usable_range
                < USABLE_BACKGROUND_TARGET_FRACTION
                and (p99 - sample.pedestal_adu) / usable_range
                < USABLE_HIGHLIGHT_DOWN_P99_FRACTION
            ):
                return False
        return bool(
            saturated_regions >= MIN_HARD_SATURATED_PERIPHERAL_REGIONS
            or usable_regions < MIN_USABLE_PERIPHERAL_REGIONS
        )

    def _motion_limit(self, sample: FrameExposureSample) -> Optional[int]:
        if sample.motion_degrees <= 0.01:
            return None
        # Scale the current exposure to about 0.25 degrees of motion, with a
        # 25 ms floor retained as a useful solving range (the hardware minimum
        # remains available to the saturation path).
        return max(
            25_000, int(sample.actual_exposure_us * 0.25 / sample.motion_degrees)
        )

    def _target(
        self,
        sample: FrameExposureSample,
        exposure: float,
        gain: float,
        reason: str,
        safety: bool = False,
    ) -> Optional[ExposureGainTarget]:
        requested_light = exposure * gain
        current_light = sample.actual_exposure_us * sample.actual_gain
        held_by_background = False
        if not safety and requested_light > current_light:
            summary = self._peripheral_summary(sample)
            p50 = summary["p50"]
            if p50 is not None:
                background_fraction = max(0.0, p50 - sample.pedestal_adu) / max(
                    1.0, sample.white_level - sample.pedestal_adu
                )
                # In diffuse sky glow the highlight target can be unreachable
                # before the background guard fires. Limit an upward step by
                # both, avoiding repeated 350 -> 420 -> 350 ms oscillation.
                background_limit = current_light * max(
                    1.0,
                    USABLE_BACKGROUND_TARGET_FRACTION / max(background_fraction, 1e-6),
                )
                if requested_light > background_limit:
                    requested_light = background_limit
                    exposure = requested_light / max(self.allocator.min_gain, gain)
                    held_by_background = True
        held_by_ceiling = False
        saturation_ceiling = self._saturation_light_ceiling
        ceiling_active = bool(
            not safety
            and saturation_ceiling is not None
            and sample.captured_at - self._saturation_ceiling_at
            < SATURATION_CEILING_PROBE_S
        )
        if (
            ceiling_active
            and saturation_ceiling is not None
            and requested_light > saturation_ceiling
        ):
            exposure = saturation_ceiling / max(self.allocator.min_gain, gain)
            reason = "saturation_ceiling_hold"
            held_by_ceiling = True
        elif (
            self._saturation_light_ceiling is not None
            and sample.captured_at - self._saturation_ceiling_at
            >= SATURATION_CEILING_PROBE_S
        ):
            # Probe at the ordinary controller's bounded step. A repeated
            # saturation re-establishes the ceiling; a clear probe lets the
            # fading twilight continue to move exposure upward.
            self._saturation_light_ceiling = None
        exposure_i = self.allocator.clamp_exposure(exposure, self._motion_limit(sample))
        gain_f = self.allocator.clamp_gain(gain)
        if self._matches(
            sample.actual_exposure_us,
            sample.actual_gain,
            ExposureGainTarget(exposure_i, gain_f, reason, safety),
        ):
            self._reason = (
                reason
                if held_by_ceiling
                else "background_headroom_hold"
                if held_by_background
                else "deadband"
            )
            return None
        direction = (
            1
            if exposure_i * gain_f > sample.actual_exposure_us * sample.actual_gain
            else -1
        )
        if self._last_direction and direction != self._last_direction:
            self._direction_reversals += 1
        self._last_direction = direction
        return ExposureGainTarget(exposure_i, gain_f, reason, safety)

    def _gain_target(self, sample: FrameExposureSample) -> Optional[ExposureGainTarget]:
        if self._gain_action is None or self.gain_locked:
            return None
        reason, target_gain, rollback_gain = self._gain_action
        exposure, gain = self.allocator.preserve_light(
            sample.actual_exposure_us,
            sample.actual_gain,
            target_gain,
            motion_limit_us=self._motion_limit(sample),
        )
        self._gain_action = None
        if reason.startswith("gain_trial"):
            self._trial_gain = gain
            self._trial_kind = reason
            self._trial_rollback_gain = rollback_gain
        self._last_gain_change_sequence = sample.frame_sequence
        return self._target(sample, exposure, gain, reason)

    def on_frame(self, sample: FrameExposureSample) -> Optional[ExposureGainTarget]:
        self._remember_frame(sample)
        summary = self._peripheral_summary(sample)

        if self.pending is not None:
            if self._matches(
                sample.actual_exposure_us,
                sample.actual_gain,
                self.pending.target,
            ):
                self._last_applied_after_frames = (
                    sample.frame_sequence - self.pending.request_sequence
                )
                self.pending = None
                self._control_fault = False
                self._reason = "control_applied"
            elif (
                sample.frame_sequence - self.pending.request_sequence
                > self.pending_timeout_frames
            ):
                self._control_fault = True
                self._reason = "control_apply_timeout"

        p999 = summary["p999"]
        hard_saturation = self._hard_peripheral_saturation(sample)
        if hard_saturation:
            self._reset_reacquisition()
            self._highlight_low_streak = 0
            saturated_p999 = max(
                (region.p999_adu for region in sample.peripheral()),
                default=sample.white_level,
            )
            ratio = 0.82 * 0.90 * sample.white_level / max(saturated_p999, 1.0)
            ratio = min(0.75, max(0.10, ratio))
            exposure = self.allocator.clamp_exposure(sample.actual_exposure_us * ratio)
            if exposure <= self.allocator.min_exposure_us * 1.02:
                self._saturation_at_min_streak += 1
            else:
                self._saturation_at_min_streak = 0
            gain = sample.actual_gain
            reason = "peripheral_saturation_exposure_down"
            if (
                self._saturation_at_min_streak >= 2
                and not self.gain_locked
                and (lower := self.allocator.adjacent_gain(sample.actual_gain, 1))
                is not None
            ):
                gain = lower
                reason = "peripheral_saturation_gain_down"
            target = self._target(sample, exposure, gain, reason, safety=True)
            if target is not None:
                self._saturation_light_ceiling = target.exposure_us * target.gain
                self._saturation_ceiling_at = sample.captured_at
                if self.pending is None:
                    return target
                pending_light = (
                    self.pending.target.exposure_us * self.pending.target.gain
                )
                if target.exposure_us * target.gain < 0.9 * pending_light:
                    return target
            return None
        self._saturation_at_min_streak = 0

        if self.pending is not None:
            if not self._control_fault:
                self._reason = "pending_apply"
            return None
        if self._control_fault:
            # A failed control channel must not trigger ordinary upward hunting.
            return None

        gain_target = self._gain_target(sample)
        if gain_target is not None:
            return gain_target

        p50 = summary["p50"]
        p99 = summary["p99"]
        p999 = summary["p999"]
        if p50 is None or p99 is None or p999 is None:
            self._reset_reacquisition()
            self._reason = "no_usable_peripheral_regions"
            return None
        highlight_signal = max(1.0, p999 - sample.pedestal_adu)
        usable_range = max(1.0, sample.white_level - sample.pedestal_adu)
        highlight_fraction = highlight_signal / usable_range
        p99_fraction = max(0.0, p99 - sample.pedestal_adu) / usable_range
        background_fraction = max(0.0, p50 - sample.pedestal_adu) / usable_range

        # A broad bright cloud has no need to reach the highlight limit: its
        # median itself consumes dynamic range. Keep this independent of the
        # local polluted-region filter so clean regions remain measurable.
        if background_fraction > USABLE_BACKGROUND_HIGH_FRACTION:
            self._reset_reacquisition()
            self._highlight_low_streak = 0
            return self._target(
                sample,
                sample.actual_exposure_us
                * USABLE_BACKGROUND_TARGET_FRACTION
                / background_fraction,
                sample.actual_gain,
                "bright_sky_exposure_down",
                safety=True,
            )

        # Before the first catalog-confirmed anchor, track a conservative
        # robust-highlight target. This lets twilight fading and a clean dark
        # field climb until faint stars use most of the sensor range, without
        # letting one polluted horizon band dictate the whole field. A single
        # upward application remains capped at +0.5 stop.
        if self._anchor_sample is None:
            self._reset_reacquisition()
            if (
                highlight_fraction > USABLE_HIGHLIGHT_HIGH_FRACTION
                and p99_fraction >= USABLE_HIGHLIGHT_DOWN_P99_FRACTION
            ):
                self._highlight_low_streak = 0
                return self._target(
                    sample,
                    sample.actual_exposure_us
                    * USABLE_HIGHLIGHT_TARGET_FRACTION
                    / highlight_fraction,
                    sample.actual_gain,
                    "acquisition_highlight_exposure_down",
                    safety=True,
                )
            if highlight_fraction < USABLE_HIGHLIGHT_LOW_FRACTION:
                if not self._highlight_raise_confirmed():
                    return None
                acquisition_ratio = USABLE_HIGHLIGHT_TARGET_FRACTION / max(
                    highlight_fraction, 1e-6
                )
                return self._target(
                    sample,
                    sample.actual_exposure_us * min(math.sqrt(2.0), acquisition_ratio),
                    sample.actual_gain,
                    "acquisition_highlight_exposure_up",
                )
            self._highlight_low_streak = 0
            self._reason = "awaiting_peripheral_solve_anchor"
            return None

        anchor_summary = self._peripheral_summary(self._anchor_sample)
        if (
            highlight_fraction > USABLE_HIGHLIGHT_HIGH_FRACTION
            and p99_fraction >= USABLE_HIGHLIGHT_DOWN_P99_FRACTION
        ):
            self._reset_reacquisition()
            self._highlight_low_streak = 0
            return self._target(
                sample,
                sample.actual_exposure_us
                * USABLE_HIGHLIGHT_TARGET_FRACTION
                / highlight_fraction,
                sample.actual_gain,
                "highlight_headroom_exposure_down",
            )
        if highlight_fraction < USABLE_HIGHLIGHT_LOW_FRACTION:
            anchor_fresh = sample.captured_at - self._anchor_at <= self.anchor_trust_s
            current_contrast = float(summary["contrast"] or 0.0)
            anchor_contrast = float(anchor_summary["contrast"] or 0.0)
            cloud_like = (
                anchor_contrast > 0 and current_contrast < 0.35 * anchor_contrast
            )
            quality_sample = (
                self._frames_by_id.get(self._latest_quality.frame_id)
                if self._latest_quality is not None
                else None
            )
            quality_fresh = bool(
                self._latest_quality
                and self._latest_quality.solve_success
                and self._latest_quality.peripheral
                and self._latest_quality.matched_stars >= 3
                and quality_sample is not None
                and sample.captured_at - quality_sample.captured_at <= 10.0
            )
            missing_periphery = sample.center_contaminated and not (
                self._latest_quality
                and self._latest_quality.peripheral
                and self._latest_quality.matched_stars > 0
            )
            if not anchor_fresh or not quality_fresh or cloud_like or missing_periphery:
                self._reason = "dark_cloud_anchor_hold"
                if (
                    (not anchor_fresh or not quality_fresh)
                    and not sample.center_contaminated
                    and sample.motion_degrees <= 0.01
                    and float(summary["usable_regions"] or 0)
                    >= MIN_USABLE_PERIPHERAL_REGIONS
                    and background_fraction < USABLE_BACKGROUND_TARGET_FRACTION
                    and p99_fraction < USABLE_HIGHLIGHT_DOWN_P99_FRACTION
                ):
                    return self._reacquisition_target(sample, highlight_fraction)
                self._reset_reacquisition()
                self._highlight_low_streak = 0
                return None
            self._reset_reacquisition()
            if not self._highlight_raise_confirmed():
                return None
            # Upward changes are limited to +0.5 stop per actual application.
            ratio = USABLE_HIGHLIGHT_TARGET_FRACTION / max(highlight_fraction, 1e-6)
            return self._target(
                sample,
                sample.actual_exposure_us * min(math.sqrt(2.0), ratio),
                sample.actual_gain,
                "highlight_headroom_exposure_up",
            )
        self._highlight_low_streak = 0
        self._reset_reacquisition()
        self._reason = "highlight_headroom_deadband"
        return None

    def update_quality(self, quality: SolveExposureQuality) -> None:
        """Accept one slow solver result; camera controls are not written here."""
        self._latest_quality = quality
        sample = self._frames_by_id.get(quality.frame_id)
        if sample is None:
            self._reason = "stale_quality_frame"
            return

        summary = self._peripheral_summary(sample)
        usable_range = max(1.0, sample.white_level - sample.pedestal_adu)
        highlight_fraction = (
            max(0.0, float(summary["p999"] or 0.0) - sample.pedestal_adu) / usable_range
        )
        background_fraction = (
            max(0.0, float(summary["p50"] or 0.0) - sample.pedestal_adu) / usable_range
        )
        exposure_settled = bool(
            USABLE_HIGHLIGHT_LOW_FRACTION
            <= highlight_fraction
            <= USABLE_HIGHLIGHT_HIGH_FRACTION
            and background_fraction <= USABLE_BACKGROUND_HIGH_FRACTION
            and not self._hard_peripheral_saturation(sample)
        )

        if quality.solve_success and quality.peripheral and quality.matched_stars >= 3:
            if (
                float(summary["sat"] or 0.0) < 0.001
                and float(summary["p999"] or sample.white_level)
                < 0.90 * sample.white_level
            ):
                self._anchor_sample = sample
                self._anchor_quality = quality
                self._anchor_at = sample.captured_at
                self._reset_reacquisition()

        if self._trial_gain is not None and abs(
            sample.actual_gain - self._trial_gain
        ) <= max(0.75, 0.03 * self._trial_gain):
            baseline = self._trial_baseline
            truth_improved = bool(
                quality.solve_success
                and quality.matched_stars >= 3
                and (
                    not baseline
                    or not baseline.solve_success
                    or quality.matched_stars >= baseline.matched_stars
                )
            )
            restoring_high = self._trial_kind == "gain_trial_restore_high"
            restore_not_worse = bool(
                restoring_high
                and baseline is not None
                and quality.solve_success
                and quality.matched_stars >= max(3, baseline.matched_stars - 1)
                and quality.score >= baseline.score - 1.0
            )
            if restore_not_worse or (
                baseline is not None
                and truth_improved
                and quality.score >= baseline.score + 1.0
            ):
                self._reason = "gain_trial_kept"
            elif baseline is not None:
                self._gain_action = (
                    "gain_trial_rollback",
                    self._trial_rollback_gain or sample.actual_gain,
                    None,
                )
                self._reason = "gain_trial_rollback_queued"
                self._gain_retry_after = sample.captured_at + self.gain_retry_cooldown_s
            self._trial_gain = None
            self._trial_kind = None
            self._trial_rollback_gain = None
            self._trial_baseline = None
            self._pressure_streak = 0
            self._good_quality_streak = 0
            return

        pressure_bad = bool(
            exposure_settled
            and quality.candidate_stars >= 20
            and quality.candidate_pressure >= 4.0
            and (not quality.solve_success or quality.matched_stars < 3)
        )
        if not exposure_settled:
            self._pressure_streak = 0
            self._good_quality_streak = 0
        else:
            self._pressure_streak = self._pressure_streak + 1 if pressure_bad else 0
        quality_good = bool(
            exposure_settled
            and quality.solve_success
            and quality.peripheral
            and quality.matched_stars >= 5
            and quality.candidate_pressure < 4.0
        )
        self._good_quality_streak = self._good_quality_streak + 1 if quality_good else 0
        enough_dwell = (
            sample.frame_sequence - self._last_gain_change_sequence
            >= self.gain_min_dwell_frames
        )
        if (
            self._pressure_streak >= self.false_candidate_repeats
            and enough_dwell
            and sample.captured_at >= self._gain_retry_after
            and not self.gain_locked
            and (lower := self.allocator.adjacent_gain(sample.actual_gain, 1))
            is not None
        ):
            self._trial_baseline = quality
            self._gain_action = (
                "gain_trial_candidate_pressure",
                lower,
                sample.actual_gain,
            )
            self._pressure_streak = 0
            self._good_quality_streak = 0
        elif (
            self._good_quality_streak >= 5
            and enough_dwell
            and sample.captured_at >= self._gain_retry_after
            and not self.gain_locked
            and (higher := self.allocator.adjacent_gain(sample.actual_gain, -1))
            is not None
        ):
            self._trial_baseline = quality
            self._gain_action = (
                "gain_trial_restore_high",
                higher,
                sample.actual_gain,
            )
            self._good_quality_streak = 0

    def status(self) -> dict[str, object]:
        latest = self._frames[-1] if self._frames else None
        summary = self._peripheral_summary(latest) if latest else {}
        return {
            "version": 2,
            "reason": self._reason,
            "pending": self.pending is not None,
            "pending_target": (
                {
                    "exposure_us": self.pending.target.exposure_us,
                    "gain": self.pending.target.gain,
                    "reason": self.pending.target.reason,
                }
                if self.pending
                else None
            ),
            "applied_after_frames": self._last_applied_after_frames,
            "control_fault": self._control_fault,
            "saturation_ceiling_light": self._saturation_light_ceiling,
            "saturation_probe_after_s": max(
                0.0,
                SATURATION_CEILING_PROBE_S
                - (
                    self._frames[-1].captured_at - self._saturation_ceiling_at
                    if self._frames and self._saturation_light_ceiling is not None
                    else SATURATION_CEILING_PROBE_S
                ),
            ),
            "gain_locked": self.gain_locked,
            "gain_trial": self._trial_gain,
            "gain_retry_after_s": (
                max(0.0, self._gain_retry_after - latest.captured_at)
                if latest and self._gain_retry_after
                else 0.0
            ),
            "direction_reversals": self._direction_reversals,
            "highlight_low_streak": self._highlight_low_streak,
            "highlight_raise_confirm_frames": self.highlight_raise_confirm_frames,
            "reacquisition_wait_s": (
                max(
                    0.0,
                    REACQUISITION_HOLD_S
                    - (latest.captured_at - self._reacquisition_since),
                )
                if latest and self._reacquisition_since is not None
                else None
            ),
            "reacquisition_probe_after_s": (
                max(
                    0.0,
                    REACQUISITION_PROBE_S
                    - (latest.captured_at - self._reacquisition_probe_at),
                )
                if latest and self._reacquisition_probe_at is not None
                else None
            ),
            "center_contaminated": latest.center_contaminated if latest else None,
            "peripheral_p50_adu": summary.get("p50"),
            "peripheral_p99_adu": summary.get("p99"),
            "peripheral_p999_adu": summary.get("p999"),
            "peripheral_saturation": summary.get("sat"),
            "peripheral_contrast": summary.get("contrast"),
            "usable_peripheral_regions": summary.get("usable_regions"),
            "contaminated_peripheral_regions": summary.get("contaminated_regions"),
            "usable_highlight_target_fraction": USABLE_HIGHLIGHT_TARGET_FRACTION,
            "usable_highlight_low_fraction": USABLE_HIGHLIGHT_LOW_FRACTION,
            "usable_highlight_high_fraction": USABLE_HIGHLIGHT_HIGH_FRACTION,
            "usable_background_high_fraction": USABLE_BACKGROUND_HIGH_FRACTION,
            "last_quality": (
                {
                    "frame_id": self._latest_quality.frame_id,
                    "source": self._latest_quality.source,
                    "matches": self._latest_quality.matched_stars,
                    "candidates": self._latest_quality.candidate_stars,
                    "snr_p25": self._latest_quality.snr_p25,
                    "snr_median": self._latest_quality.snr_median,
                    "rmse": self._latest_quality.rmse,
                    "solve_success": self._latest_quality.solve_success,
                }
                if self._latest_quality
                else None
            ),
        }


__all__ = [
    "AutoStarFrameController",
    "ExposureGainAllocator",
    "ExposureGainTarget",
    "FrameExposureSample",
    "GAIN_LADDER",
    "RegionExposureStats",
    "SolveExposureQuality",
    "collect_spatial_frame_sample",
    "matched_star_exposure_quality",
]
