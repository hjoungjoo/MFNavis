#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Shared pointing coordinate selection for SkySafari/Web/LCD consumers.

The service does not own ``shared_state.solution()``.  It reads the PiFinder
estimate, IMU orientation, and cached INDI mount status, then returns a
purpose-ready coordinate state.  Mount readback is deliberately gated by an
explicit sync/alignment flag so a freshly connected mount cannot override the
PiFinder/IMU pointing before the two coordinate systems have been matched.
"""

from __future__ import annotations

import logging
import math
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Tuple, cast

import numpy as np
import quaternion

from PiFinder.calc_utils import sf_utils
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning


logger = logging.getLogger("PointingCoordinateService")


ConfigGetter = Callable[[str, Any], Any]
DefaultLocationProvider = Callable[[], Any]
MountStatusProvider = Callable[[], dict[str, Any]]


QUALITY_HIGH = "high"
QUALITY_MEDIUM = "medium"
QUALITY_LOW = "low"
QUALITY_INVALID = "invalid"

SOURCE_SOLVE = "solve"
SOURCE_PIFINDER_IMU_ESTIMATE = "pifinder_imu_estimate"
SOURCE_IMU = "imu_fallback"
SOURCE_MOUNT = "mount"
SOURCE_FUSED = "mount_imu_delta"
SOURCE_UNAVAILABLE = "unavailable"

MODE_SOLVED_PRIMARY = "SOLVED_PRIMARY"
MODE_IMU_PRIMARY_UNSOLVED = "IMU_PRIMARY_UNSOLVED"
MODE_MOUNT_REFERENCE_PRIMARY = "MOUNT_REFERENCE_PRIMARY"
MODE_MOUNT_ONLY_SYNCED = "MOUNT_ONLY_SYNCED"
MODE_UNAVAILABLE = "UNAVAILABLE"

IMU_SMOOTH_SMALL_MOVE_DEGREES = 0.3
IMU_SMOOTH_MODERATE_MOVE_DEGREES = 1.5
IMU_SMOOTH_RESET_DEGREES = 5.0
IMU_SMOOTH_SMALL_ALPHA = 0.06
IMU_SMOOTH_MODERATE_ALPHA = 0.25
IMU_SMOOTH_LARGE_ALPHA = 0.65
MOUNT_IMU_DELTA_HOLD_SECONDS = 1.5
MOUNT_READBACK_MOVING_DELTA_DEGREES = 0.005
# Tracking catch-up budget (2026-07-23). While the mount tracks a target the
# readback RA/Dec is constant but the axes physically rotate (~11 arcsec/s
# measured), so the scope follows the alt/az trajectory of the fixed readback.
# The BNO055 cannot resolve that slow motion: its output freezes, then snaps
# ~0.3 deg to catch up at 0.25-0.4 deg/s (hardware capture 2026-07-22) — well
# above the disturbance rate gate, which booked every snap as a physical push
# and stepped the fused coordinate off target (sawtooth drift). The tracker
# therefore keeps a per-axis budget of expected-but-unreported tracking motion
# (predicted trajectory minus reported IMU motion) and cancels the
# budget-matching component of a fast_follow step before booking the rest as a
# disturbance. The cap bounds the budget where the IMU never catches up (yaw
# has no absolute reference in imuplus, so the az budget would otherwise grow
# without bound) — a same-direction real push can be absorbed at most up to
# the budget, which the cap keeps small relative to a deliberate push.
IMU_TRACKING_CATCHUP_BUDGET_CAP_DEG = 3.0
# When the observer location moves more than this (metres), the mount+IMU
# fusion anchor and delta tracker were built for the old site (its psi0 and the
# alt/az <-> RA/Dec conversions assume a fixed lat/lon), so they are discarded
# and rebuilt for the new site -- the same treatment a mount re-sync gets. Well
# above GPS jitter, well below any real relocation.
FUSION_LOCATION_RESET_THRESHOLD_M = 500.0
# Hysteresis rate gate for the mount+IMU-delta fusion. The IMU delta exists to
# catch physical disturbances (a bump, a push, a motor stall slip). While the
# mount is tracking, the smoothed IMU lags the slow (~15"/s) tracking motion,
# so the raw delta drifts at near-sidereal rate and would drag the fused
# coordinate off target without bound — that artifact floor was measured at a
# very stable 0.004-0.005 deg/s (indoors, no wind).
#
# A single threshold chops weak stall-slip events (measured head/tail rates
# 0.02-0.06 deg/s) into fragments, capturing only ~1/3 of the displacement.
# Hence hysteresis: an episode STARTS only above the enter rate (~7x the
# artifact floor, so tracking artifact and outdoor wind rumble never start
# one) and then keeps accumulating down to the exit rate (~4x, so a real
# event's slow tail is captured but outdoor micro-sway cannot keep an episode
# alive indefinitely). Outside an episode, steps are discarded while the
# already-applied offset is HELD (a stopped scope must keep its disturbed
# coordinate — it must not crawl back to the mount readback). The offset
# clears only when the mount frame is re-established by a sync.
IMU_DELTA_ENTER_RATE_DEG_PER_SEC = 0.03
IMU_DELTA_EXIT_RATE_DEG_PER_SEC = 0.015
# After a mount-driven slew the BNO055's internal fusion re-converges for a
# while (the orientation "slides" without any physical motion), at rates above
# the accumulation gate. Require the IMU to stay below the exit rate for this
# long after mount motion before disturbance accumulation may resume, so the
# slide is never booked as a physical push. Together with
# MOUNT_IMU_DELTA_HOLD_SECONDS this sets the total quiet time after a slew
# before IMU disturbance detection re-arms (~3 s).
IMU_DELTA_POST_MOTION_QUIET_SECONDS = 1.5
# Above this IMU altitude a rotation-tracker step switches from the exact
# mount-axis decomposition (Rz(daz) then the alt axis) to the minimal-arc
# rotation between boresight vectors: near the zenith the measured azimuth is
# the ill-conditioned atan2 of a tiny horizontal component, so daz is noise
# while the boresight vector remains well-defined.
ALTAZ_ROTATION_ZENITH_GUARD_ALT_DEG = 80.0

# A 6 mm lens covers a wide field, so even a valid plate solve can move by a
# few image pixels from one frame to the next. Keep the authoritative solve
# and IMU anchor untouched, but stabilize the coordinate published to remote
# consumers over a short window of independent camera solves. Fill all five
# before selecting the frame: with only three, solve noise can hide the small
# sidereal trend and lock a fixed camera to the wrong frame.
SOLVE_AVERAGE_MIN_SAMPLES = 5
SOLVE_AVERAGE_WINDOW = 5
SOLVE_AVERAGE_RESET_DEGREES = 0.25


def _as_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _as_float_vector(value: Any) -> Optional[list[float]]:
    if value is None:
        return None
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    return result if all(math.isfinite(item) for item in result) else None


def _wrap_angle_delta_degrees(delta: float) -> float:
    return ((delta + 180.0) % 360.0) - 180.0


def _altaz_unit_vector(alt_deg: float, az_deg: float) -> "np.ndarray":
    """(east, north, up) unit vector of an alt/az pointing — the same ENU
    convention as imu_altaz_degrees (az measured from north toward east)."""
    alt = math.radians(alt_deg)
    az = math.radians(az_deg)
    cos_alt = math.cos(alt)
    return np.array([cos_alt * math.sin(az), cos_alt * math.cos(az), math.sin(alt)])


def _unit_vector_altaz(vector: "np.ndarray") -> Tuple[float, float]:
    """Inverse of _altaz_unit_vector; az of the exact zenith/nadir is 0."""
    up = max(-1.0, min(1.0, float(vector[2])))
    alt = math.degrees(math.asin(up))
    az = math.degrees(math.atan2(float(vector[0]), float(vector[1]))) % 360.0
    return alt, az


def _min_arc_quaternion(
    v_from: "np.ndarray", v_to: "np.ndarray"
) -> "quaternion.quaternion":
    """Minimal (great-circle, roll-free) rotation taking v_from onto v_to.

    Boresight vectors carry no roll, so the minimal rotation is the only
    physically meaningful one between two pointings. Antiparallel inputs pick
    an arbitrary perpendicular axis (a 0.2 s tracker step is never antipodal
    in practice)."""
    axis = np.cross(v_from, v_to)
    sin_angle = float(np.linalg.norm(axis))
    cos_angle = float(np.dot(v_from, v_to))
    if sin_angle < 1e-12:
        if cos_angle >= 0.0:
            return quaternion.one
        # Antiparallel: rotate 180 deg about any axis perpendicular to v_from.
        helper = (
            np.array([1.0, 0.0, 0.0])
            if abs(float(v_from[0])) < 0.9
            else np.array([0.0, 1.0, 0.0])
        )
        axis = np.cross(v_from, helper)
        axis /= np.linalg.norm(axis)
        return quaternion.from_rotation_vector(axis * math.pi)
    angle = math.atan2(sin_angle, cos_angle)
    return quaternion.from_rotation_vector(axis / sin_angle * angle)


def _az_rotation_quaternion(daz_deg: float) -> "quaternion.quaternion":
    """Rotation that INCREASES azimuth by daz_deg.

    Azimuth runs north -> east (clockwise seen from above), which in the
    right-handed ENU frame (x=east, y=north, z=up) is a rotation about -z.
    """
    return quaternion.from_rotation_vector(np.array([0.0, 0.0, -math.radians(daz_deg)]))


def _rotate_vector(q: "quaternion.quaternion", vector: "np.ndarray") -> "np.ndarray":
    rotated = q * quaternion.quaternion(0.0, *vector) * q.conjugate()
    return np.array([rotated.x, rotated.y, rotated.z])


def clamp_altitude_degrees(altitude: float) -> float:
    return max(-90.0, min(90.0, altitude))


def _tracking_budget_cancel(step: float, budget: float) -> float:
    """Portion of an IMU step explained by the pending tracking budget: same
    sign as the budget and clamped to its magnitude. Zero when the step goes
    the other way — a real push against the tracking direction is never
    cancelled."""
    if budget > 0.0 and step > 0.0:
        return min(step, budget)
    if budget < 0.0 and step < 0.0:
        return max(step, budget)
    return 0.0


def _clamp_tracking_budget(value: float) -> float:
    return max(
        -IMU_TRACKING_CATCHUP_BUDGET_CAP_DEG,
        min(IMU_TRACKING_CATCHUP_BUDGET_CAP_DEG, value),
    )


def valid_radec(ra_deg: Any, dec_deg: Any) -> Optional[Tuple[float, float]]:
    ra = _as_float(ra_deg)
    dec = _as_float(dec_deg)
    if ra is None or dec is None:
        return None
    if dec < -90.0 or dec > 90.0:
        return None
    return ra % 360.0, dec


def angular_separation_degrees(
    ra_a_deg: float, dec_a_deg: float, ra_b_deg: float, dec_b_deg: float
) -> float:
    ra_a = math.radians(ra_a_deg)
    dec_a = math.radians(dec_a_deg)
    ra_b = math.radians(ra_b_deg)
    dec_b = math.radians(dec_b_deg)
    cos_sep = math.sin(dec_a) * math.sin(dec_b) + math.cos(dec_a) * math.cos(
        dec_b
    ) * math.cos(ra_a - ra_b)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


def altaz_separation_degrees(
    alt_a_deg: float, az_a_deg: float, alt_b_deg: float, az_b_deg: float
) -> float:
    return angular_separation_degrees(az_a_deg, alt_a_deg, az_b_deg, alt_b_deg)


def _radec_to_unit_vector(ra_deg: float, dec_deg: float) -> np.ndarray:
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    cos_dec = math.cos(dec)
    return np.array(
        [cos_dec * math.cos(ra), cos_dec * math.sin(ra), math.sin(dec)],
        dtype=float,
    )


def _unit_vector_to_radec(vector: np.ndarray) -> Tuple[float, float]:
    norm = float(np.linalg.norm(vector))
    if norm <= 0.0 or not math.isfinite(norm):
        raise ValueError("Cannot convert a zero vector to RA/Dec")
    x, y, z = vector / norm
    ra = math.degrees(math.atan2(y, x)) % 360.0
    if ra >= 360.0 - 1e-12:
        ra = 0.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, float(z)))))
    return ra, dec


@dataclass
class CoordinateSample:
    ra_deg: Optional[float] = None
    dec_deg: Optional[float] = None
    epoch: str = "session"
    alt_deg: Optional[float] = None
    az_deg: Optional[float] = None
    source: str = SOURCE_UNAVAILABLE
    quality: str = QUALITY_INVALID
    timestamp: Optional[float] = None
    valid: bool = False
    reason: str = ""
    aligned: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def radec(self) -> Optional[Tuple[float, float]]:
        if not self.valid or self.ra_deg is None or self.dec_deg is None:
            return None
        return self.ra_deg % 360.0, self.dec_deg

    @classmethod
    def invalid(
        cls,
        source: str,
        reason: str,
        *,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "CoordinateSample":
        return cls(
            source=source,
            quality=QUALITY_INVALID,
            valid=False,
            reason=reason,
            metadata=metadata or {},
        )


@dataclass
class CoordinateHealth:
    selected_source: str = SOURCE_UNAVAILABLE
    warnings: list[str] = field(default_factory=list)
    mount_pre_alignment_only: bool = False
    mount_separation_degrees: Optional[float] = None
    imu_mount_separation_degrees: Optional[float] = None
    mount_delta_degrees: Optional[float] = None
    imu_altaz_delta_degrees: Optional[float] = None


@dataclass
class CoordinateState:
    current: CoordinateSample
    solved: CoordinateSample
    imu: CoordinateSample
    mount: CoordinateSample
    health: CoordinateHealth
    mode: str = MODE_UNAVAILABLE
    weights: dict[str, float] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def radec(self) -> Optional[Tuple[float, float]]:
        return self.current.radec()


class PointingCoordinateService:
    """Build and select pointing coordinates from solve, IMU, and mount data."""

    def __init__(
        self,
        *,
        mount_weight: float = 0.85,
        imu_weight_when_mount_aligned: float = 0.15,
        max_fusion_separation_degrees: float = 10.0,
    ):
        self.mount_weight = mount_weight
        self.imu_weight_when_mount_aligned = imu_weight_when_mount_aligned
        self.max_fusion_separation_degrees = max_fusion_separation_degrees
        self._mount_imu_anchor: Optional[dict[str, Any]] = None
        self._imu_delta_tracker: Optional[dict[str, Any]] = None
        self._imu_filter_altaz: Optional[Tuple[float, float]] = None
        self._mount_motion_hold_until = 0.0
        self._last_mount_motion_radec: Optional[Tuple[float, float]] = None
        self._last_mount_sample_ts: Optional[float] = None
        # Scalar tracker: (applied_ra, applied_dec); rotation tracker:
        # ("q_off", quaternion).
        self._imu_delta_applied_snapshot: Optional[Tuple[Any, Any]] = None
        # Frame context for the mount+IMU-delta fusion (dt, location,
        # mount_type), refreshed by current_state(). None (e.g. direct
        # _select_current calls in tests) falls back to the equatorial frame.
        self._fusion_context: Optional[dict[str, Any]] = None
        # Observer (lat, lon, altitude) the fusion anchor/tracker were built
        # for; a large move rebuilds them for the new site (see
        # FUSION_LOCATION_RESET_THRESHOLD_M).
        self._fusion_location: Optional[Tuple[float, float, float]] = None
        self._solve_average_samples: list[CoordinateSample] = []
        self._solve_average_frame: Optional[str] = None
        self._solve_alignment_pixel: Optional[tuple] = None
        self._last_health_mount_radec: Optional[Tuple[float, float]] = None
        self._last_health_imu_altaz: Optional[Tuple[float, float]] = None
        self._state_lock = threading.RLock()
        self._state: Optional[CoordinateState] = None

    def update_state(
        self,
        shared_state: Any,
        dt: Any,
        *,
        config_get: ConfigGetter,
        default_location_provider: Optional[DefaultLocationProvider] = None,
        mount_status_provider: Optional[MountStatusProvider] = None,
        imu_alignment_correction: Optional[dict[str, Any]] = None,
    ) -> CoordinateState:
        state = self.current_state(
            shared_state,
            dt,
            config_get=config_get,
            default_location_provider=default_location_provider,
            mount_status_provider=mount_status_provider,
            imu_alignment_correction=imu_alignment_correction,
        )
        with self._state_lock:
            self._state = state
        return state

    def get_state(self) -> Optional[CoordinateState]:
        with self._state_lock:
            return self._state

    def clear_state(self) -> None:
        with self._state_lock:
            self._state = None
            self._mount_imu_anchor = None
            self._imu_delta_tracker = None
            self._imu_filter_altaz = None
            self._mount_motion_hold_until = 0.0
            self._last_mount_motion_radec = None
            self._last_mount_sample_ts = None
            self._imu_delta_applied_snapshot = None
            self._fusion_location = None
            self._reset_solve_average()

    def solved_sample(self, shared_state: Any, dt: Any) -> CoordinateSample:
        try:
            solution = shared_state.solution()
        except Exception:
            logger.debug("Could not read PiFinder solution", exc_info=True)
            return CoordinateSample.invalid(SOURCE_SOLVE, "solution unavailable")

        if not solution or not solution.has_pointing():
            return CoordinateSample.invalid(SOURCE_SOLVE, "no solved pointing")

        solve_source = self._solution_source_value(solution)
        has_plate_anchor = self._solution_has_plate_anchor(solution)
        if solve_source in {"IMU", "CAM_FAILED"} and not has_plate_anchor:
            return CoordinateSample.invalid(
                SOURCE_SOLVE,
                f"{solve_source} estimate has no plate-solve anchor",
            )
        if solve_source not in {"CAM", "CAM_FAILED", "IMU"}:
            return CoordinateSample.invalid(
                SOURCE_SOLVE, f"untrusted solution source {solve_source or 'unknown'}"
            )

        aligned = solution.pointing.aligned.estimate
        plate = getattr(solution, "alignment_projection", None) or {}
        pixel = plate.get("target_pixel")
        pixel = tuple(pixel) if pixel is not None else None
        if pixel != self._solve_alignment_pixel:
            self._reset_solve_average()
            self._mount_imu_anchor = None
            self._imu_delta_tracker = None
            self._solve_alignment_pixel = pixel
        radec = valid_radec(getattr(aligned, "RA", None), getattr(aligned, "Dec", None))
        if radec is None:
            return CoordinateSample.invalid(SOURCE_SOLVE, "invalid solved RA/Dec")

        timestamp = _as_float(getattr(solution, "estimate_time", None))
        # CAM_FAILED does not mean that the retained estimate became invalid.
        # The integrator deliberately keeps the last plate-anchored estimate
        # (and its IMU anchor) when a later frame fails to solve.  Treat that
        # retained value like the plate-anchored IMU estimate so consumers do
        # not fall through to an unrelated absolute-IMU coordinate.
        sample_source = (
            SOURCE_SOLVE if solve_source == "CAM" else SOURCE_PIFINDER_IMU_ESTIMATE
        )
        return CoordinateSample(
            ra_deg=radec[0],
            dec_deg=radec[1],
            epoch="session",
            alt_deg=_as_float(getattr(solution, "Alt", None)),
            az_deg=_as_float(getattr(solution, "Az", None)),
            source=sample_source,
            quality=QUALITY_HIGH if solve_source == "CAM" else QUALITY_MEDIUM,
            timestamp=timestamp,
            valid=True,
            metadata={
                "solve_source": solve_source,
                "has_plate_anchor": has_plate_anchor,
                "source_ra": radec[0],
                "source_dec": radec[1],
                "target_pixel": pixel,
                "source_alt": _as_float(getattr(solution, "Alt", None)),
                "source_az": _as_float(getattr(solution, "Az", None)),
            },
        )

    def _reset_solve_average(self) -> None:
        self._solve_average_samples = []
        self._solve_average_frame = None

    @staticmethod
    def _mean_radec(samples: list[CoordinateSample]) -> Tuple[float, float]:
        vector = np.sum(
            [
                _radec_to_unit_vector(
                    cast(float, sample.ra_deg), cast(float, sample.dec_deg)
                )
                for sample in samples
            ],
            axis=0,
        )
        return _unit_vector_to_radec(vector)

    @staticmethod
    def _mean_altaz(samples: list[CoordinateSample]) -> Tuple[float, float]:
        vector = np.sum(
            [
                _altaz_unit_vector(
                    cast(float, sample.alt_deg), cast(float, sample.az_deg)
                )
                for sample in samples
            ],
            axis=0,
        )
        norm = float(np.linalg.norm(vector))
        if norm <= 0.0 or not math.isfinite(norm):
            raise ValueError("Cannot average antipodal Alt/Az vectors")
        return _unit_vector_altaz(vector / norm)

    @staticmethod
    def _radec_scatter(
        samples: list[CoordinateSample], center: Tuple[float, float]
    ) -> float:
        return statistics.median(
            angular_separation_degrees(
                cast(float, sample.ra_deg),
                cast(float, sample.dec_deg),
                center[0],
                center[1],
            )
            for sample in samples
        )

    @staticmethod
    def _altaz_scatter(
        samples: list[CoordinateSample], center: Tuple[float, float]
    ) -> float:
        return statistics.median(
            altaz_separation_degrees(
                cast(float, sample.alt_deg),
                cast(float, sample.az_deg),
                center[0],
                center[1],
            )
            for sample in samples
        )

    def _choose_solve_average_frame(
        self, equatorial_scatter: float, horizontal_scatter: Optional[float]
    ) -> str:
        if horizontal_scatter is None:
            return "equatorial"
        # Lock the frame selected by the first independent solve set. As the
        # five-solve window slides, random noise can temporarily make the
        # other frame appear quieter. Switching at that point is not harmless:
        # the equatorial mean represents the window's middle epoch while the
        # horizontal mean is converted at the current epoch, so the switch can
        # expose the whole accumulated sidereal-time difference as a jump.
        # Actual IMU motion, a large confirmed solve change, clear_state(), or
        # a real observer relocation resets this lock and permits re-detection.
        if self._solve_average_frame is not None:
            return self._solve_average_frame
        return "horizontal" if horizontal_scatter < equatorial_scatter else "equatorial"

    def _stabilize_solved_sample(
        self, solved: CoordinateSample, imu: CoordinateSample
    ) -> CoordinateSample:
        """Average accepted solves in the frame that best matches the mount.

        A fixed alt/az camera has a constant horizontal coordinate while its
        RA changes at sidereal rate. An equatorial tracking mount has the
        opposite behaviour. Comparing recent scatter in both frames avoids
        averaging away either kind of real tracking motion.
        """
        if bool((imu.metadata or {}).get("moving")):
            self._reset_solve_average()
            return solved
        if not solved.valid:
            return solved

        solve_source = str((solved.metadata or {}).get("solve_source", ""))
        if solve_source == "IMU":
            self._reset_solve_average()
            return solved

        # Add only independent successful camera frames. CAM_FAILED republishes
        # the last anchored estimate and must not overweight it by being polled
        # repeatedly between solves.
        if solve_source == "CAM":
            is_new = not self._solve_average_samples or (
                solved.timestamp is not None
                and solved.timestamp != self._solve_average_samples[-1].timestamp
            )
            if is_new:
                if self._solve_average_samples:
                    previous = self._solve_average_samples[-1]
                    separation = angular_separation_degrees(
                        cast(float, previous.ra_deg),
                        cast(float, previous.dec_deg),
                        cast(float, solved.ra_deg),
                        cast(float, solved.dec_deg),
                    )
                    if separation >= SOLVE_AVERAGE_RESET_DEGREES:
                        self._reset_solve_average()
                self._solve_average_samples.append(solved)
                self._solve_average_samples = self._solve_average_samples[
                    -SOLVE_AVERAGE_WINDOW:
                ]

        samples = self._solve_average_samples
        if len(samples) < SOLVE_AVERAGE_MIN_SAMPLES:
            return solved

        equatorial_center = self._mean_radec(samples)
        equatorial_scatter = self._radec_scatter(samples, equatorial_center)
        horizontal_center: Optional[Tuple[float, float]] = None
        horizontal_scatter: Optional[float] = None
        horizontal_ready = all(
            sample.alt_deg is not None and sample.az_deg is not None
            for sample in samples
        )
        ctx = self._fusion_context or {}
        if (
            horizontal_ready
            and ctx.get("dt") is not None
            and ctx.get("location") is not None
        ):
            horizontal_center = self._mean_altaz(samples)
            horizontal_scatter = self._altaz_scatter(samples, horizontal_center)

        frame = self._choose_solve_average_frame(equatorial_scatter, horizontal_scatter)
        averaged_ra, averaged_dec = equatorial_center
        averaged_alt: Optional[float] = None
        averaged_az: Optional[float] = None
        if frame == "horizontal" and horizontal_center is not None:
            location = ctx["location"]
            try:
                sf_utils.set_location(location.lat, location.lon, location.altitude)
                # Alt/Az samples came from ICRS -> observed radec_to_altaz.
                # Use its inverse, not apparent RA/Dec of the current date.
                averaged_ra, averaged_dec = sf_utils.observed_altaz_to_radec(
                    horizontal_center[0], horizontal_center[1], ctx["dt"]
                )
                averaged_ra %= 360.0
                averaged_alt, averaged_az = horizontal_center
            except Exception:
                logger.debug(
                    "Could not convert averaged Alt/Az to RA/Dec; using equatorial average",
                    exc_info=True,
                )
                frame = "equatorial"

        if frame == "equatorial":
            location = ctx.get("location")
            if location is not None and ctx.get("dt") is not None:
                try:
                    sf_utils.set_location(location.lat, location.lon, location.altitude)
                    averaged_alt, averaged_az = sf_utils.radec_to_altaz(
                        averaged_ra, averaged_dec, ctx["dt"]
                    )
                except Exception:
                    logger.debug(
                        "Could not derive Alt/Az for averaged RA/Dec", exc_info=True
                    )

        self._solve_average_frame = frame
        metadata = dict(solved.metadata)
        metadata.update(
            {
                "stabilized": True,
                "stabilization_method": "spherical_moving_average",
                "stabilization_frame": frame,
                "stabilization_window": len(samples),
                "stabilization_equatorial_scatter_arcmin": equatorial_scatter * 60.0,
                "stabilization_horizontal_scatter_arcmin": (
                    horizontal_scatter * 60.0
                    if horizontal_scatter is not None
                    else None
                ),
                "unstabilized_ra": solved.ra_deg,
                "unstabilized_dec": solved.dec_deg,
            }
        )
        return CoordinateSample(
            ra_deg=averaged_ra,
            dec_deg=averaged_dec,
            epoch=solved.epoch,
            alt_deg=averaged_alt,
            az_deg=averaged_az,
            source=solved.source,
            quality=solved.quality,
            timestamp=solved.timestamp,
            valid=True,
            reason=solved.reason,
            aligned=solved.aligned,
            metadata=metadata,
        )

    def _solution_source_value(self, solution: Any) -> str:
        raw_source = getattr(solution, "solve_source", None)
        value = getattr(raw_source, "value", raw_source)
        return str(value or "")

    def _solution_has_plate_anchor(self, solution: Any) -> bool:
        try:
            aligned_solve = solution.pointing.aligned.solve
        except Exception:
            aligned_solve = None
        return bool(
            aligned_solve is not None
            and getattr(solution, "last_solve_success", None) is not None
        )

    def imu_altaz_degrees(
        self, imu_sample: Any, screen_direction: str
    ) -> Optional[Tuple[float, float]]:
        if not imu_sample or not imu_sample.is_usable():
            return None
        try:
            q_x2cam = (
                imu_sample.quat * ImuDeadReckoning._q_imu2cam(screen_direction)
            ).normalized()
        except (AttributeError, ValueError, ZeroDivisionError):
            logger.debug("Invalid IMU sample", exc_info=True)
            return None

        if not np.isfinite(quaternion.as_float_array(q_x2cam)).all():
            return None

        boresight = q_x2cam * quaternion.quaternion(0, 0, 0, 1) * q_x2cam.conj()
        east, north, up = boresight.x, boresight.y, boresight.z
        norm = math.sqrt(east * east + north * north + up * up)
        if norm <= 0:
            return None

        east, north, up = east / norm, north / norm, up / norm
        alt = math.degrees(math.asin(max(-1.0, min(1.0, up))))
        az = math.degrees(math.atan2(east, north)) % 360.0
        return alt, az

    def observer_location(
        self,
        shared_state: Any,
        default_location_provider: Optional[DefaultLocationProvider] = None,
    ) -> Any:
        try:
            location = shared_state.location()
        except Exception:
            location = None
        if location and getattr(location, "lock", False):
            return location
        if default_location_provider is not None:
            configured = default_location_provider()
            if configured:
                return configured
        return location

    def imu_sample(
        self,
        shared_state: Any,
        dt: Any,
        *,
        config_get: ConfigGetter,
        default_location_provider: Optional[DefaultLocationProvider] = None,
        imu_alignment_correction: Optional[dict[str, Any]] = None,
        apply_alignment: bool = True,
    ) -> CoordinateSample:
        if not bool(config_get("skysafari_imu_fallback", True)):
            return CoordinateSample.invalid(SOURCE_IMU, "disabled")

        location = self.observer_location(shared_state, default_location_provider)
        if not location:
            return CoordinateSample.invalid(SOURCE_IMU, "no location")
        if not getattr(location, "lock", False):
            return CoordinateSample.invalid(SOURCE_IMU, "location unlocked")
        if not dt:
            return CoordinateSample.invalid(SOURCE_IMU, "no datetime")

        screen_direction = str(config_get("screen_direction", "right"))
        imu_sample = shared_state.imu()
        altaz = self.imu_altaz_degrees(imu_sample, screen_direction)
        if altaz is None:
            return CoordinateSample.invalid(SOURCE_IMU, "no calibrated IMU orientation")

        alt, az = altaz

        if (
            apply_alignment
            and imu_alignment_correction
            and imu_alignment_correction.get("active")
        ):
            alt = clamp_altitude_degrees(
                alt + float(imu_alignment_correction.get("alt_offset", 0.0))
            )
            az = (az + float(imu_alignment_correction.get("az_offset", 0.0))) % 360.0

        aligned_alt, aligned_az = alt, az
        smoothed_alt, smoothed_az, filter_state, filter_delta = self._smooth_imu_altaz(
            alt, az
        )
        alt, az = smoothed_alt, smoothed_az

        try:
            sf_utils.set_location(location.lat, location.lon, location.altitude)
            ra_deg, dec_deg = sf_utils.altaz_to_radec(alt, az, dt)
        except Exception:
            logger.debug("Could not convert IMU Alt/Az to RA/Dec", exc_info=True)
            return CoordinateSample.invalid(SOURCE_IMU, "alt/az conversion failed")

        # Unsmoothed counterpart for the disturbance delta tracker: the
        # smoothing filter's slow convergence tail after a large move reads as
        # sustained motion and would keep accumulating into the fused offset
        # long after the scope has stopped. The raw orientation settles
        # immediately, so rate-gating on it ends the episode with the motion.
        raw_ra_deg: Optional[float] = None
        raw_dec_deg: Optional[float] = None
        try:
            raw_ra_deg, raw_dec_deg = sf_utils.altaz_to_radec(
                aligned_alt, aligned_az, dt
            )
            if raw_ra_deg is not None:
                raw_ra_deg = raw_ra_deg % 360.0
        except Exception:
            logger.debug("Could not convert raw IMU Alt/Az to RA/Dec", exc_info=True)

        timestamp = _as_float(getattr(imu_sample, "timestamp", None))
        quat_values = None
        quat_norm = None
        try:
            quat_values = _as_float_vector(
                quaternion.as_float_array(getattr(imu_sample, "quat", None))
            )
            if quat_values is not None:
                quat_norm = math.sqrt(sum(value * value for value in quat_values))
        except Exception:
            quat_values = None
            quat_norm = None

        return CoordinateSample(
            ra_deg=ra_deg % 360.0,
            dec_deg=dec_deg,
            epoch="session",
            alt_deg=alt,
            az_deg=az,
            source=SOURCE_IMU,
            quality=QUALITY_LOW,
            timestamp=timestamp,
            valid=True,
            metadata={
                "location_source": getattr(location, "source", ""),
                "screen_direction": screen_direction,
                "moving": bool(getattr(imu_sample, "moving", False)),
                "status": getattr(imu_sample, "status", None),
                "calibration_status": getattr(imu_sample, "calibration_status", None),
                "fusion_mode": getattr(imu_sample, "fusion_mode", ""),
                "uses_magnetometer": bool(
                    getattr(imu_sample, "uses_magnetometer", False)
                ),
                "raw_alt": altaz[0],
                "raw_az": altaz[1],
                "raw_ra": raw_ra_deg,
                "raw_dec": raw_dec_deg,
                "smoothed_alt": alt,
                "smoothed_az": az,
                "filter_state": filter_state,
                "filter_delta_degrees": filter_delta,
                "quat": quat_values,
                "quat_norm": quat_norm,
                "gyro": _as_float_vector(getattr(imu_sample, "gyro", None)),
                "accel": _as_float_vector(getattr(imu_sample, "accel", None)),
                "alignment_applied": bool(
                    apply_alignment
                    and imu_alignment_correction
                    and imu_alignment_correction.get("active")
                ),
            },
        )

    def mount_sample_from_status(
        self, status: Optional[dict[str, Any]]
    ) -> CoordinateSample:
        if not isinstance(status, dict) or not status:
            return CoordinateSample.invalid(SOURCE_MOUNT, "no mount status")

        usable, unusable_reason = self.mount_status_is_usable(status)
        if not usable:
            return CoordinateSample.invalid(
                SOURCE_MOUNT,
                unusable_reason,
                metadata={
                    "state": status.get("state"),
                    "message": status.get("message"),
                    "device": status.get("device"),
                    "park_state": status.get("park_state"),
                    "driver_mount_status": status.get("driver_mount_status"),
                    "raw_mount_status": status.get("raw_mount_status"),
                },
            )

        radec = self._extract_mount_radec(status)
        if radec is None:
            return CoordinateSample.invalid(SOURCE_MOUNT, "no mount RA/Dec readback")

        aligned = self.mount_status_is_aligned(status)
        timestamp = _as_float(status.get("updated")) or _as_float(
            status.get("timestamp")
        )
        return CoordinateSample(
            ra_deg=radec[0],
            dec_deg=radec[1],
            epoch="session",
            source=SOURCE_MOUNT,
            quality=QUALITY_MEDIUM if aligned else QUALITY_LOW,
            timestamp=timestamp,
            valid=True,
            aligned=aligned,
            metadata={
                "state": status.get("state"),
                "message": status.get("message"),
                "device": status.get("device"),
                "park_state": status.get("park_state"),
                "driver_mount_status": status.get("driver_mount_status"),
                "raw_mount_status": status.get("raw_mount_status"),
                "mount_motion_active": status.get("mount_motion_active"),
                "mount_motion_type": status.get("mount_motion_type"),
                "mount_readback_priority": status.get("mount_readback_priority"),
                "goto_motion_active": status.get("goto_motion_active"),
                "goto_refine_pending": status.get("goto_refine_pending"),
                "manual_motion_direction": status.get("manual_motion_direction"),
                "target_ra": status.get("target_ra"),
                "target_dec": status.get("target_dec"),
                "coordinate_sync": status.get("coordinate_sync"),
                "multipoint_align": status.get("multipoint_align"),
                "backlash_auto": status.get("backlash_auto"),
                "usable": True,
            },
        )

    def current_state(
        self,
        shared_state: Any,
        dt: Any,
        *,
        config_get: ConfigGetter,
        default_location_provider: Optional[DefaultLocationProvider] = None,
        mount_status_provider: Optional[MountStatusProvider] = None,
        imu_alignment_correction: Optional[dict[str, Any]] = None,
    ) -> CoordinateState:
        solved = self.solved_sample(shared_state, dt)
        imu = self.imu_sample(
            shared_state,
            dt,
            config_get=config_get,
            default_location_provider=default_location_provider,
            imu_alignment_correction=imu_alignment_correction,
        )
        mount_enabled = bool(config_get("mount_control", False))
        mount_status = (
            mount_status_provider() if mount_enabled and mount_status_provider else {}
        )
        mount = self.mount_sample_from_status(mount_status)

        # Context for the mount+IMU-delta fusion: the delta must be applied in
        # the mount's native axis frame (alt/az mount -> alt/az space, EQ mount
        # -> RA/Dec space), and the alt/az branch needs location + time for the
        # RA/Dec <-> alt/az conversions.
        fusion_location = self.observer_location(
            shared_state, default_location_provider
        )
        self._fusion_context = {
            "dt": dt,
            "location": fusion_location,
            "mount_type": str(config_get("mount_type", "Alt/Az")),
        }
        self._reset_fusion_on_location_change(fusion_location)
        solved = self._stabilize_solved_sample(solved, imu)

        health = CoordinateHealth()
        current = self._select_current(solved, imu, mount, health)
        mode, weights = self._mode_and_weights(solved, imu, mount, current)
        health.selected_source = current.source
        self._annotate_health(current, imu, mount, health)
        return CoordinateState(
            current=current,
            solved=solved,
            imu=imu,
            mount=mount,
            health=health,
            mode=mode,
            weights=weights,
        )

    def _mode_and_weights(
        self,
        solved: CoordinateSample,
        imu: CoordinateSample,
        mount: CoordinateSample,
        current: CoordinateSample,
    ) -> tuple[str, dict[str, float]]:
        if solved.valid:
            return MODE_SOLVED_PRIMARY, {"solve": 1.0, "imu": 0.0, "mount": 0.0}
        if current.source == SOURCE_FUSED:
            return (
                MODE_MOUNT_REFERENCE_PRIMARY,
                {
                    "solve": 0.0,
                    "mount_reference": self.mount_weight,
                    "imu_delta": self.imu_weight_when_mount_aligned,
                },
            )
        if mount.valid and mount.aligned and current.source == SOURCE_MOUNT:
            return MODE_MOUNT_ONLY_SYNCED, {"solve": 0.0, "imu": 0.0, "mount": 1.0}
        if imu.valid and current.source == SOURCE_IMU:
            mount_weight = 0.0
            if mount.valid and not mount.aligned:
                mount_weight = 0.0
            return (
                MODE_IMU_PRIMARY_UNSOLVED,
                {"solve": 0.0, "imu": 1.0, "mount_absolute": mount_weight},
            )
        return MODE_UNAVAILABLE, {"solve": 0.0, "imu": 0.0, "mount": 0.0}

    def _select_current(
        self,
        solved: CoordinateSample,
        imu: CoordinateSample,
        mount: CoordinateSample,
        health: CoordinateHealth,
    ) -> CoordinateSample:
        if solved.valid:
            return solved

        if mount.valid and mount.aligned:
            if imu.valid:
                if not self.mount_sample_allows_imu_delta(mount):
                    # The mount is moving itself (GoTo/manual/pulse): readback
                    # is authoritative and IMU steps caused by that motion must
                    # not count as a disturbance. Keep the anchor and the
                    # accumulated disturbance offset — only suspend
                    # accumulation — so an offset from an earlier physical
                    # push survives the motion instead of vanishing.
                    self._track_imu_reference_without_accumulation(mount, imu)
                    health.warnings.append(
                        "mount motion/settle active; using mount readback until stationary"
                    )
                    return self._mount_readback_sample(mount)
                fused = self._mount_with_imu_delta(mount, imu, health)
                if fused is not None:
                    return fused
            return self._mount_readback_sample(mount)

        if imu.valid and self._imu_can_supply_absolute_coordinate(imu):
            self._mount_imu_anchor = None
            if mount.valid and not mount.aligned:
                health.mount_pre_alignment_only = True
                health.warnings.append("mount readback ignored before sync/alignment")
            return imu

        if imu.valid:
            # IMUPLUS has no absolute heading. It remains useful as a relative
            # delta after a plate solve (handled by the integrator) or after an
            # aligned mount anchor (handled above), but selecting it directly
            # here can put SkySafari tens of degrees away from the last solve.
            self._mount_imu_anchor = None
            health.warnings.append(
                "absolute IMU fallback unavailable without magnetometer or alignment"
            )

        if mount.valid and not mount.aligned:
            self._mount_imu_anchor = None
            health.mount_pre_alignment_only = True
            health.warnings.append("mount readback available but not aligned")

        return CoordinateSample.invalid(
            SOURCE_UNAVAILABLE, "no valid solve, aligned mount, or IMU fallback"
        )

    @staticmethod
    def _imu_can_supply_absolute_coordinate(imu: CoordinateSample) -> bool:
        """Whether ``imu`` has an absolute heading suitable as a coordinate.

        A magnetometer-backed sample has an absolute azimuth.  A session
        alignment also turns the otherwise relative IMUPLUS heading into an
        absolute direction.  Without either, the quaternion may only be used
        as a delta from a trusted plate-solve or mount anchor.
        """
        metadata = imu.metadata or {}
        return bool(
            metadata.get("uses_magnetometer") or metadata.get("alignment_applied")
        )

    def _smooth_imu_altaz(
        self, alt: float, az: float
    ) -> tuple[float, float, str, float]:
        previous = self._imu_filter_altaz
        if previous is None:
            self._imu_filter_altaz = (alt, az % 360.0)
            return alt, az % 360.0, "initial", 0.0

        delta = altaz_separation_degrees(previous[0], previous[1], alt, az)
        if delta >= IMU_SMOOTH_RESET_DEGREES:
            self._imu_filter_altaz = (alt, az % 360.0)
            return alt, az % 360.0, "reset_large_motion", delta

        if delta < IMU_SMOOTH_SMALL_MOVE_DEGREES:
            alpha = IMU_SMOOTH_SMALL_ALPHA
            state = "smoothed_small_jitter"
        elif delta < IMU_SMOOTH_MODERATE_MOVE_DEGREES:
            alpha = IMU_SMOOTH_MODERATE_ALPHA
            state = "smoothed_motion"
        else:
            alpha = IMU_SMOOTH_LARGE_ALPHA
            state = "tracking_large_motion"

        az_delta = _wrap_angle_delta_degrees((az % 360.0) - previous[1])
        smoothed_alt = previous[0] + (alt - previous[0]) * alpha
        smoothed_az = (previous[1] + az_delta * alpha) % 360.0
        self._imu_filter_altaz = (smoothed_alt, smoothed_az)
        return smoothed_alt, smoothed_az, state, delta

    def _mount_readback_sample(self, mount: CoordinateSample) -> CoordinateSample:
        metadata = dict(mount.metadata)
        metadata["motion_active"] = self.mount_sample_is_motion_active(mount)
        metadata["readback_priority"] = self.mount_sample_prefers_readback(mount)
        return CoordinateSample(
            ra_deg=mount.ra_deg,
            dec_deg=mount.dec_deg,
            epoch=mount.epoch,
            source=mount.source,
            quality=mount.quality,
            timestamp=mount.timestamp,
            valid=True,
            aligned=mount.aligned,
            metadata=metadata,
        )

    def _mount_with_imu_delta(
        self,
        mount: CoordinateSample,
        imu: CoordinateSample,
        health: CoordinateHealth,
    ) -> Optional[CoordinateSample]:
        mount_radec = mount.radec()
        imu_radec = imu.radec()
        if mount_radec is None or imu_radec is None:
            return None

        separation = angular_separation_degrees(
            mount_radec[0], mount_radec[1], imu_radec[0], imu_radec[1]
        )
        health.imu_mount_separation_degrees = separation

        if self._mount_imu_anchor_should_reset(mount, imu):
            self._mount_imu_anchor = self._new_mount_imu_anchor(mount, imu)

        anchor = self._mount_imu_anchor
        if anchor is None:
            return None

        imu_delta_ra = _wrap_angle_delta_degrees(imu_radec[0] - anchor["imu_ra"])
        imu_delta_dec = imu_radec[1] - anchor["imu_dec"]
        # Rate-gate the delta: only fast IMU motion (a real push/bump) is applied
        # to the fused coordinate. Slow accumulation — the smoothed IMU lagging
        # sidereal tracking, or sensor drift — is discarded, so the fused
        # coordinate stays anchored to the mount readback while tracking. The
        # base is the LIVE mount readback (not the anchor snapshot), so guide
        # pulses and slews move the fused coordinate directly and never need a
        # re-anchor that would wipe the disturbance offset.
        #
        # The delta is tracked and applied in the MOUNT'S NATIVE AXIS FRAME
        # (frame chosen from the mount_type config):
        # - alt/az mount: a hand push rotates about the alt/az axes, so the
        #   delta is (az, alt) and is added to the mount readback's alt/az. An
        #   az-only push then stays az-only in the fused coordinate. The old
        #   approach (component-wise RA/Dec addition) linearized a spherical
        #   displacement measured at the IMU's declination onto the mount's
        #   declination; for a large hand swing across a big IMU-vs-mount
        #   separation this produced impossible below-horizon coordinates
        #   (reproduced on hardware 2026-07-19: scope alt never below 7 deg,
        #   fused dec dove to -46).
        # - EQ mount: a rotation about the polar axis changes RA by the same
        #   angle at any declination, and the dec-axis changes dec alone, so
        #   the delta is (RA, Dec) added component-wise WITHOUT any cos(dec)
        #   rescaling.
        fused_radec: Optional[Tuple[float, float]] = None
        frame_metadata: dict[str, Any] = {}
        gate_state = ""
        imu_rate = 0.0
        # Preferred for EVERY mount type: rotation-frame fusion (see
        # _tick_altaz_rotation_tracker). The rotation tracker follows the
        # scope's PHYSICAL rotation and applies it to the mount pointing
        # vector, so it needs no mount-axis assumption. In particular the EQ
        # scalar path is NOT safe as a primary: its RA/Dec deltas are
        # converted from the IMU's own az frame, whose arbitrary imuplus yaw
        # offset bends a pure polar-axis rotation into a large fake Dec
        # component (measured: a +15 deg RA-axis move read as +11.4 RA /
        # +9.9 Dec at the -53 deg offset seen on hardware), and RA is
        # atan2-singular near the celestial pole. Falls through to the scalar
        # component paths only when the rotation prerequisites are missing.
        fused_radec = self._fuse_altaz_rotation(mount_radec, imu, frame_metadata)
        if fused_radec is not None:
            gate_state = str(frame_metadata.get("imu_delta_gate", ""))
            imu_rate = float(frame_metadata.get("imu_delta_rate_deg_per_sec", 0.0))
        if fused_radec is None:
            coords, frame = self._imu_tracker_coords(imu)
            applied_1, applied_2, gate_state, imu_rate = self._gated_imu_delta(
                coords, frame=frame
            )
            frame_metadata["fusion_frame"] = frame
            frame_metadata["fusion_method"] = "component"
            if frame == "altaz":
                fused_radec = self._apply_altaz_delta(
                    mount_radec,
                    applied_1,
                    applied_2,
                    frame_metadata,
                    anchor,
                    imu,
                )
                if fused_radec is None:
                    # Conversion failed (location/time raced away): fall back
                    # to the equatorial component addition rather than
                    # dropping the fused source entirely.
                    frame = "equatorial"
                    frame_metadata["fusion_frame"] = "equatorial_fallback"
            if fused_radec is None:
                dec_deg = max(-89.9, min(89.9, mount_radec[1] + applied_2))
                ra_deg = (mount_radec[0] + applied_1) % 360.0
                fused_radec = (ra_deg, dec_deg)
                frame_metadata.setdefault("imu_delta_applied_ra", applied_1)
                frame_metadata.setdefault("imu_delta_applied_dec", applied_2)

        return CoordinateSample(
            ra_deg=fused_radec[0],
            dec_deg=fused_radec[1],
            epoch="session",
            source=SOURCE_FUSED,
            quality=QUALITY_MEDIUM,
            timestamp=max(
                mount.timestamp or 0.0,
                imu.timestamp or 0.0,
            )
            or None,
            valid=True,
            aligned=True,
            metadata={
                "mode": "mount_readback_plus_imu_delta",
                "anchor_mount_ra": anchor["mount_ra"],
                "anchor_mount_dec": anchor["mount_dec"],
                "anchor_imu_ra": anchor["imu_ra"],
                "anchor_imu_dec": anchor["imu_dec"],
                "imu_delta_ra": imu_delta_ra,
                "imu_delta_dec": imu_delta_dec,
                # Frame-specific applied keys (ra/dec on an EQ mount, az/alt on
                # an alt/az mount) arrive via **frame_metadata below.
                "imu_delta_gate": gate_state,
                "imu_delta_rate_deg_per_sec": imu_rate,
                "mount_ra": mount_radec[0],
                "mount_dec": mount_radec[1],
                "imu_ra": imu_radec[0],
                "imu_dec": imu_radec[1],
                "absolute_mount_imu_separation_degrees": separation,
                "sync_key": anchor["sync_key"],
                "motion_active": False,
                **frame_metadata,
            },
        )

    def _apply_altaz_delta(
        self,
        mount_radec: Tuple[float, float],
        applied_az: float,
        applied_alt: float,
        frame_metadata: dict[str, Any],
        anchor: dict[str, Any],
        imu: CoordinateSample,
    ) -> Optional[Tuple[float, float]]:
        """Add the (az, alt) delta to the mount readback in alt/az space.

        Returns the fused RA/Dec, or None when the required location/time
        context is unavailable or a conversion fails (caller falls back to the
        equatorial component addition).

        The RA/Dec is produced DIFFERENTIALLY: fused = mount_radec +
        (radec(mount_altaz + delta) - radec(mount_altaz)). radec_to_altaz and
        altaz_to_radec are not exact inverses (epoch/precession handling
        differs by ~0.3 deg), so an absolute round trip would shift the fused
        coordinate off the mount readback even at zero delta; the differential
        form cancels that bias and guarantees fused == mount when the applied
        delta is zero. atmos=False keeps the conversions refraction-free.
        """
        ctx = self._fusion_context or {}
        dt = ctx.get("dt")
        location = ctx.get("location")
        if dt is None or location is None:
            return None
        try:
            sf_utils.set_location(location.lat, location.lon, location.altitude)
            mount_alt, mount_az = sf_utils.radec_to_altaz(
                mount_radec[0], mount_radec[1], dt, atmos=False
            )
            if mount_alt is None or mount_az is None:
                return None
            fused_az = (mount_az + applied_az) % 360.0
            fused_alt = mount_alt + applied_alt
            # Pole crossing: fold the altitude back into [-90, 90] and swing
            # the azimuth to the far side.
            if fused_alt > 90.0:
                fused_alt = 180.0 - fused_alt
                fused_az = (fused_az + 180.0) % 360.0
            elif fused_alt < -90.0:
                fused_alt = -180.0 - fused_alt
                fused_az = (fused_az + 180.0) % 360.0
            base_ra, base_dec = sf_utils.altaz_to_radec(mount_alt, mount_az, dt)
            moved_ra, moved_dec = sf_utils.altaz_to_radec(fused_alt, fused_az, dt)
            ra_deg = (
                mount_radec[0] + _wrap_angle_delta_degrees(moved_ra - base_ra)
            ) % 360.0
            dec_deg = max(-89.9, min(89.9, mount_radec[1] + (moved_dec - base_dec)))
        except Exception:
            logger.debug("Alt/Az fusion conversion failed", exc_info=True)
            return None

        frame_metadata.update(
            {
                "mount_alt": mount_alt,
                "mount_az": mount_az,
                "fused_alt": fused_alt,
                "fused_az": fused_az,
                "imu_delta_applied_az": applied_az,
                "imu_delta_applied_alt": applied_alt,
            }
        )
        anchor_alt = anchor.get("imu_alt")
        anchor_az = anchor.get("imu_az")
        imu_altaz = self._imu_raw_altaz(imu)
        if anchor_alt is not None and anchor_az is not None and imu_altaz is not None:
            frame_metadata["imu_delta_az"] = _wrap_angle_delta_degrees(
                imu_altaz[1] - anchor_az
            )
            frame_metadata["imu_delta_alt"] = imu_altaz[0] - anchor_alt
        return ra_deg % 360.0, dec_deg

    def _gated_imu_delta(
        self,
        coords: Tuple[float, float],
        *,
        frame: str = "equatorial",
        accumulate: bool = True,
    ) -> Tuple[float, float, str, float]:
        """Accumulate only fast IMU motion into the applied fusion delta.

        ``coords`` are in the mount's native axis frame: (ra, dec) for the
        equatorial frame, (az, alt) for the alt/az frame — longitude-like axis
        first in both, so the wrap and spherical-rate math is shared. A frame
        change resets the tracker (the accumulated offset is meaningless in
        the other frame).

        Returns (applied_delta_1, applied_delta_2, gate_state, rate_deg_s).
        The gate uses rate hysteresis: an accumulation episode starts above
        IMU_DELTA_ENTER_RATE_DEG_PER_SEC and keeps accumulating until the rate
        drops below IMU_DELTA_EXIT_RATE_DEG_PER_SEC, so a weak slip's slow
        head/tail is captured once the event is underway. Outside an episode,
        steps are discarded but the already-applied offset is HELD — once the
        scope stops, the fused coordinate must stay at the disturbed position,
        not creep back to the mount readback. With ``accumulate=False`` (mount
        moving itself) the IMU reference still advances so the mount's own
        motion is never counted, but the offset is untouched. The tracker
        resets when the anchor is recreated (a sync re-establishes the mount
        frame), which clears the offset.
        """
        now = time.monotonic()
        tracker = self._imu_delta_tracker
        if (
            tracker is None
            or tracker.get("anchor") is not self._mount_imu_anchor
            or tracker.get("frame") != frame
        ):
            self._imu_delta_tracker = {
                "anchor": self._mount_imu_anchor,
                "frame": frame,
                "imu_ra": coords[0],
                "imu_dec": coords[1],
                "t": now,
                "applied_ra": 0.0,
                "applied_dec": 0.0,
                "episode": False,
                "settle_pending": False,
                "quiet_since": None,
            }
            self._imu_delta_applied_snapshot = (0.0, 0.0)
            return 0.0, 0.0, "init", 0.0

        dt = max(1e-3, now - tracker["t"])
        step_ra = _wrap_angle_delta_degrees(coords[0] - tracker["imu_ra"])
        step_dec = coords[1] - tracker["imu_dec"]
        # Same spherical separation formula for both frames: axis 1 is the
        # longitude-like coordinate (ra or az), axis 2 the latitude-like one
        # (dec or alt).
        step_deg = angular_separation_degrees(
            tracker["imu_ra"], tracker["imu_dec"], coords[0], coords[1]
        )
        rate = step_deg / dt

        gate_state = self._gate_decision(tracker, rate, now, accumulate)
        if gate_state == "fast_follow":
            tracker["applied_ra"] += step_ra
            tracker["applied_dec"] += step_dec

        tracker["imu_ra"] = coords[0]
        tracker["imu_dec"] = coords[1]
        tracker["t"] = now
        return (
            tracker["applied_ra"],
            tracker["applied_dec"],
            gate_state,
            rate,
        )

    def _gate_decision(
        self, tracker: dict[str, Any], rate: float, now: float, accumulate: bool
    ) -> str:
        """Shared rate-hysteresis gate for the scalar and rotation trackers.

        Mutates episode/settle_pending/quiet_since on the tracker and returns
        the gate state; on "fast_follow" the caller applies the step (scalar
        addition or rotation composition).
        """
        if not accumulate:
            tracker["episode"] = False
            tracker["settle_pending"] = True
            tracker["quiet_since"] = None
            return "suspended_mount_motion"
        if tracker.get("settle_pending"):
            # Post-motion settle: the BNO055 orientation keeps sliding after a
            # slew; wait for a sustained quiet stretch before booking anything
            # as a disturbance again.
            if rate < IMU_DELTA_EXIT_RATE_DEG_PER_SEC:
                quiet_since = tracker["quiet_since"]
                if quiet_since is None:
                    quiet_since = now
                    tracker["quiet_since"] = quiet_since
                if now - quiet_since >= IMU_DELTA_POST_MOTION_QUIET_SECONDS:
                    tracker["settle_pending"] = False
                    tracker["quiet_since"] = None
            else:
                tracker["quiet_since"] = None
            return "post_motion_settle"
        threshold = (
            IMU_DELTA_EXIT_RATE_DEG_PER_SEC
            if tracker.get("episode")
            else IMU_DELTA_ENTER_RATE_DEG_PER_SEC
        )
        if rate >= threshold:
            tracker["episode"] = True
            return "fast_follow"
        tracker["episode"] = False
        return "hold"

    def _tick_altaz_rotation_tracker(
        self,
        mount_radec: Tuple[float, float],
        imu: CoordinateSample,
        *,
        accumulate: bool = True,
    ) -> Optional[dict[str, Any]]:
        """Advance the rotation-based delta tracker for an alt/az mount.

        Gimbal-lock-free upgrade of the component (az, alt) tracker: the raw
        IMU boresight is kept as a UNIT VECTOR, each tick's motion is the
        minimal (roll-free) rotation between successive boresight vectors, and
        gated steps compose into an offset quaternion ``q_off`` expressed in
        the mount's az frame:

            v_fused = q_off · v_mount(live readback)

        Differencing rotations instead of az angles removes the atan2(az)
        singularity at the zenith (where a tiny physical motion legitimately
        flips az by ~180 and the scalar tracker books garbage). Composing the
        SMALL per-tick steps (rather than one anchor->now rotation) keeps the
        parallel-transport error negligible, because the fused pointing stays
        within the held-drift distance of the physical pointing.

        ``psi0`` maps the IMU's arbitrary yaw frame (imuplus, no magnetometer)
        onto the mount's az frame. It is measured at tracker init — where the
        applied delta is zero, so fused == mount readback corresponds to the
        IMU boresight by construction: psi0 = mount_az - imu_raw_az. Gravity
        pins both frames' "up", so a pure z-conjugation is the full mapping;
        each step is conjugated: q_step_mount = Rz(psi0) q_step_imu Rz(-psi0).

        Returns the tracker (with "gate" and "rate_deg_s" fields refreshed),
        or None when the prerequisites (fusion context, IMU alt/az, mount
        alt/az conversion) are missing — the caller falls back to the scalar
        component tracker.
        """
        ctx = self._fusion_context or {}
        dt_ctx = ctx.get("dt")
        location = ctx.get("location")
        imu_altaz = self._imu_raw_altaz(imu)
        if dt_ctx is None or location is None or imu_altaz is None:
            return None

        now = time.monotonic()
        v_now = _altaz_unit_vector(imu_altaz[0], imu_altaz[1])
        # The expected physical alt/az of the scope: while the mount tracks, the
        # readback RA/Dec is constant and the axes follow this trajectory as
        # time advances. Recomputed every tick — it feeds the tracking catch-up
        # budget and the fusion's mount pointing vector.
        try:
            sf_utils.set_location(location.lat, location.lon, location.altitude)
            mount_alt, mount_az = sf_utils.radec_to_altaz(
                mount_radec[0], mount_radec[1], dt_ctx, atmos=False
            )
        except Exception:
            logger.debug(
                "Mount alt/az conversion failed in rotation tracker",
                exc_info=True,
            )
            return None
        if mount_alt is None or mount_az is None:
            return None

        tracker = self._imu_delta_tracker
        if (
            tracker is None
            or tracker.get("anchor") is not self._mount_imu_anchor
            or tracker.get("frame") != "altaz_rot"
        ):
            tracker = {
                "anchor": self._mount_imu_anchor,
                "frame": "altaz_rot",
                "v_prev": v_now,
                "altaz_prev": imu_altaz,
                "mount_altaz": (mount_alt, mount_az),
                "t": now,
                "q_off": quaternion.one,
                "psi0": _wrap_angle_delta_degrees(mount_az - imu_altaz[1]),
                "budget_alt": 0.0,
                "budget_az": 0.0,
                "cancelled_alt": 0.0,
                "cancelled_az": 0.0,
                "ep_active": False,
                "episode": False,
                "settle_pending": False,
                "quiet_since": None,
                "gate": "init",
                "rate_deg_s": 0.0,
            }
            self._imu_delta_tracker = tracker
            self._imu_delta_applied_snapshot = None
            self._snapshot_imu_delta_applied()
            return tracker

        dt = max(1e-3, now - tracker["t"])
        v_prev = tracker["v_prev"]
        cos_step = max(-1.0, min(1.0, float(np.dot(v_prev, v_now))))
        step_deg = math.degrees(math.acos(cos_step))
        rate = step_deg / dt

        # Per-tick expected motion (trajectory of the constant readback) and
        # reported IMU motion, both as mount-frame alt/az components (az deltas
        # are invariant under the constant psi0 yaw offset, alt is
        # gravity-referenced in both frames).
        prev_mount_alt, prev_mount_az = tracker["mount_altaz"]
        expected_alt = mount_alt - prev_mount_alt
        expected_az = _wrap_angle_delta_degrees(mount_az - prev_mount_az)
        step_alt = imu_altaz[0] - tracker["altaz_prev"][0]
        step_az = _wrap_angle_delta_degrees(imu_altaz[1] - tracker["altaz_prev"][1])

        gate_state = self._gate_decision(tracker, rate, now, accumulate)
        if gate_state in ("suspended_mount_motion", "post_motion_settle"):
            # The mount is moving itself (readback jumping — the trajectory
            # prediction is invalid) or the BNO055 is re-converging; the
            # pending catch-up amount is unknowable, so drop it. A pending
            # episode is discarded without rebalance — its bookings are the
            # mount's own motion and the snapshot/rollback machinery already
            # reverts that leak.
            tracker["budget_alt"] = 0.0
            tracker["budget_az"] = 0.0
            tracker["ep_active"] = False
        elif gate_state == "fast_follow":
            budget_alt = tracker["budget_alt"] + expected_alt
            budget_az = tracker["budget_az"] + expected_az
            alt_prev, az_prev = tracker["altaz_prev"]
            alt_now = imu_altaz[0]
            psi0 = tracker["psi0"]
            if not tracker.get("ep_active"):
                tracker["ep_active"] = True
                tracker["ep_net_alt"] = 0.0
                tracker["ep_net_az"] = 0.0
                tracker["ep_cancel_alt"] = 0.0
                tracker["ep_cancel_az"] = 0.0
                tracker["ep_az_start"] = az_prev
                tracker["ep_zenith"] = False
            if max(abs(alt_prev), abs(alt_now)) <= ALTAZ_ROTATION_ZENITH_GUARD_ALT_DEG:
                # A BNO055 tracking catch-up snap matches the pending budget in
                # direction and (at most) magnitude — cancel that component and
                # book only the residual as a disturbance. A push against the
                # tracking direction cancels nothing; a same-direction push
                # books its excess over the budget. Per-tick cancellation is
                # provisional: an oscillating (wobbling) IMU would otherwise
                # get its tracking-direction half-cycles cancelled and its
                # return half-cycles booked, rectifying symmetric noise into a
                # net offset (hardware capture 2026-07-23: one 20 s wobble
                # episode leaked ~430 arcsec). _rebalance_tracking_episode
                # settles the difference against the episode's NET displacement
                # when the episode ends.
                cancel_alt = _tracking_budget_cancel(step_alt, budget_alt)
                cancel_az = _tracking_budget_cancel(step_az, budget_az)
                budget_alt -= cancel_alt
                budget_az -= cancel_az
                tracker["cancelled_alt"] += cancel_alt
                tracker["cancelled_az"] += cancel_az
                tracker["ep_net_alt"] += step_alt
                tracker["ep_net_az"] += step_az
                tracker["ep_cancel_alt"] += cancel_alt
                tracker["ep_cancel_az"] += cancel_az
                daz = step_az - cancel_az
                dalt = step_alt - cancel_alt
                # Normal altitudes: build the step from the exact mount-axis
                # decomposition. Rz(daz) is exact for the az axis at ANY
                # IMU-vs-mount separation; the alt-axis rotation uses the
                # horizontal axis at the (psi0-mapped) azimuth, matching the
                # fused pointing's azimuth to within the tracked mismatch.
                axis_az_mount = math.radians(az_prev + psi0)
                alt_axis = np.array(
                    [math.cos(axis_az_mount), -math.sin(axis_az_mount), 0.0]
                )
                q_step_mount = _az_rotation_quaternion(
                    daz
                ) * quaternion.from_rotation_vector(alt_axis * math.radians(dalt))
            else:
                # Near the zenith the measured azimuth is noise; use the
                # minimal-arc rotation between the boresight VECTORS, which
                # stays well-conditioned through the pole, conjugated into the
                # mount frame by psi0. No budget cancellation here — the az
                # components it would clamp are exactly the unreliable ones —
                # and the episode is marked so the end-of-episode rebalance
                # skips it too.
                tracker["ep_zenith"] = True
                q_step = _min_arc_quaternion(v_prev, v_now)
                q_step_mount = (
                    _az_rotation_quaternion(psi0)
                    * q_step
                    * _az_rotation_quaternion(-psi0)
                )
            tracker["q_off"] = (q_step_mount * tracker["q_off"]).normalized()
            tracker["budget_alt"] = _clamp_tracking_budget(budget_alt)
            tracker["budget_az"] = _clamp_tracking_budget(budget_az)
        else:
            if tracker.get("ep_active"):
                self._rebalance_tracking_episode(tracker)
            # hold: expected motion the IMU did not report accumulates as
            # pending catch-up; whatever it did report consumes it. A frozen
            # BNO055 grows the budget at the tracking rate; an IMU that follows
            # continuously keeps it near zero.
            tracker["budget_alt"] = _clamp_tracking_budget(
                tracker["budget_alt"] + expected_alt - step_alt
            )
            tracker["budget_az"] = _clamp_tracking_budget(
                tracker["budget_az"] + expected_az - step_az
            )

        tracker["v_prev"] = v_now
        tracker["altaz_prev"] = imu_altaz
        tracker["mount_altaz"] = (mount_alt, mount_az)
        tracker["t"] = now
        tracker["gate"] = gate_state
        tracker["rate_deg_s"] = rate
        return tracker

    def _rebalance_tracking_episode(self, tracker: dict[str, Any]) -> None:
        """Settle an ended fast_follow episode against its NET displacement.

        Per-tick budget cancellation rectifies a symmetric IMU wobble: the
        half-cycles in the tracking direction are cancelled (consuming budget)
        while the return half-cycles are booked, walking the fused coordinate
        off even though the net motion was ~zero. At episode end, recompute the
        ideal cancellation from the episode's net step and apply the
        difference: give back wrongly-consumed budget and un-book (or book) the
        matching rotation. A clean catch-up snap or a clean push already
        matches the ideal, so the correction is zero there.
        """
        tracker["ep_active"] = False
        if tracker.get("ep_zenith"):
            # Zenith ticks book vector min-arcs whose az components the
            # component ledger cannot represent; leave those episodes as-is.
            return
        diff_alt = diff_az = 0.0
        for axis, net_key, cancel_key in (
            ("alt", "ep_net_alt", "ep_cancel_alt"),
            ("az", "ep_net_az", "ep_cancel_az"),
        ):
            provisional = tracker[cancel_key]
            available = tracker[f"budget_{axis}"] + provisional
            ideal = _tracking_budget_cancel(tracker[net_key], available)
            tracker[f"budget_{axis}"] = _clamp_tracking_budget(available - ideal)
            tracker[f"cancelled_{axis}"] += ideal - provisional
            if axis == "alt":
                diff_alt = provisional - ideal
            else:
                diff_az = provisional - ideal
        if abs(diff_alt) < 1e-9 and abs(diff_az) < 1e-9:
            return
        axis_az_mount = math.radians(tracker["ep_az_start"] + tracker["psi0"])
        alt_axis = np.array([math.cos(axis_az_mount), -math.sin(axis_az_mount), 0.0])
        q_corr = _az_rotation_quaternion(diff_az) * quaternion.from_rotation_vector(
            alt_axis * math.radians(diff_alt)
        )
        tracker["q_off"] = (q_corr * tracker["q_off"]).normalized()

    def _fuse_altaz_rotation(
        self,
        mount_radec: Tuple[float, float],
        imu: CoordinateSample,
        frame_metadata: dict[str, Any],
    ) -> Optional[Tuple[float, float]]:
        """Rotation-frame fusion — valid for ANY mount type.

        The tracker follows the scope's physical rotation (working in alt/az
        space, psi0-mapped onto the mount frame) and this applies it to the
        live mount readback's pointing vector, so no mount-axis assumption is
        involved: it serves alt/az and EQ mounts alike. Converts back to
        RA/Dec differentially (same bias cancellation as _apply_altaz_delta).
        Returns None when the rotation tracker cannot run; the caller falls
        back to the scalar component paths.
        """
        tracker = self._tick_altaz_rotation_tracker(mount_radec, imu)
        if tracker is None:
            return None

        ctx = self._fusion_context or {}
        try:
            # The tracker tick just computed this tick's mount alt/az (and set
            # the sf_utils location) — reuse it.
            mount_alt, mount_az = tracker["mount_altaz"]
            v_mount = _altaz_unit_vector(mount_alt, mount_az)
            v_fused = _rotate_vector(tracker["q_off"], v_mount)
            fused_alt, fused_az = _unit_vector_altaz(v_fused)
            base_ra, base_dec = sf_utils.altaz_to_radec(mount_alt, mount_az, ctx["dt"])
            moved_ra, moved_dec = sf_utils.altaz_to_radec(
                fused_alt, fused_az, ctx["dt"]
            )
            ra_deg = (
                mount_radec[0] + _wrap_angle_delta_degrees(moved_ra - base_ra)
            ) % 360.0
            dec_deg = max(-89.9, min(89.9, mount_radec[1] + (moved_dec - base_dec)))
        except Exception:
            logger.debug("Alt/Az rotation fusion failed", exc_info=True)
            return None

        frame_metadata.update(
            {
                "fusion_frame": self._mount_axis_frame(),
                "fusion_method": "rotation",
                "imu_delta_gate": tracker["gate"],
                "imu_delta_rate_deg_per_sec": tracker["rate_deg_s"],
                "psi0_deg": tracker["psi0"],
                "imu_track_budget_alt": tracker["budget_alt"],
                "imu_track_budget_az": tracker["budget_az"],
                "imu_track_cancelled_alt": tracker["cancelled_alt"],
                "imu_track_cancelled_az": tracker["cancelled_az"],
                "mount_alt": mount_alt,
                "mount_az": mount_az,
                "fused_alt": fused_alt,
                "fused_az": fused_az,
                "imu_delta_applied_az": _wrap_angle_delta_degrees(fused_az - mount_az),
                "imu_delta_applied_alt": fused_alt - mount_alt,
            }
        )
        return ra_deg % 360.0, dec_deg

    def _track_imu_reference_without_accumulation(
        self, mount: CoordinateSample, imu: CoordinateSample
    ) -> None:
        """Advance the IMU delta reference while the mount moves itself.

        Called instead of the fusion while mount motion suppresses the IMU
        delta: the tracker's IMU reference must follow the (mount-driven)
        motion so it is not later misread as a physical push, while the
        accumulated disturbance offset stays intact for when the mount is
        stationary again.
        """
        mount_radec = mount.radec()
        imu_radec = imu.radec()
        if mount_radec is None or imu_radec is None:
            return
        if self._mount_imu_anchor_should_reset(mount, imu):
            self._mount_imu_anchor = self._new_mount_imu_anchor(mount, imu)
        # Rotation tracker first (same preference as the fusion itself, for
        # every mount type); its reference vector must keep following the
        # mount-driven motion.
        if (
            self._tick_altaz_rotation_tracker(mount_radec, imu, accumulate=False)
            is not None
        ):
            return
        coords, frame = self._imu_tracker_coords(imu)
        self._gated_imu_delta(coords, frame=frame, accumulate=False)

    def _imu_tracker_radec(self, imu: CoordinateSample) -> Tuple[float, float]:
        """RA/Dec the delta tracker should difference: raw (unsmoothed) when
        available, so the smoothing tail never reads as motion."""
        raw_ra = _as_float(imu.metadata.get("raw_ra"))
        raw_dec = _as_float(imu.metadata.get("raw_dec"))
        if raw_ra is not None and raw_dec is not None:
            return raw_ra, raw_dec
        radec = imu.radec()
        assert radec is not None
        return radec

    def _imu_raw_altaz(self, imu: CoordinateSample) -> Optional[Tuple[float, float]]:
        """(alt, az) the delta tracker should difference in the alt/az frame:
        raw (unsmoothed) when available, mirroring _imu_tracker_radec."""
        raw_alt = _as_float(imu.metadata.get("raw_alt"))
        raw_az = _as_float(imu.metadata.get("raw_az"))
        if raw_alt is not None and raw_az is not None:
            return raw_alt, raw_az % 360.0
        alt = _as_float(imu.alt_deg)
        az = _as_float(imu.az_deg)
        if alt is not None and az is not None:
            return alt, az % 360.0
        return None

    def _mount_axis_frame(self) -> str:
        """The mount's native axis frame from the mount_type config:
        'altaz' for an alt/az mount, 'equatorial' otherwise (EQ/GEM)."""
        ctx = self._fusion_context or {}
        mount_type = str(ctx.get("mount_type", "")).lower()
        if "alt" in mount_type and "az" in mount_type:
            return "altaz"
        return "equatorial"

    def _imu_tracker_coords(
        self, imu: CoordinateSample
    ) -> Tuple[Tuple[float, float], str]:
        """(coords, frame) for the delta tracker in the mount's native frame.

        alt/az frame coords are ordered (az, alt) — longitude-like axis first,
        matching the (ra, dec) ordering of the equatorial frame — and require
        the fusion context (dt + location) plus an IMU alt/az; anything missing
        falls back to the equatorial frame.
        """
        if self._mount_axis_frame() == "altaz":
            ctx = self._fusion_context or {}
            imu_altaz = self._imu_raw_altaz(imu)
            if (
                ctx.get("dt") is not None
                and ctx.get("location") is not None
                and imu_altaz is not None
            ):
                return (imu_altaz[1], imu_altaz[0]), "altaz"
        return self._imu_tracker_radec(imu), "equatorial"

    def _reset_fusion_on_location_change(self, location: Any) -> None:
        """Discard the mount+IMU fusion anchor and delta tracker when the
        observer location moves to a new site. Both encode the old lat/lon (the
        rotation tracker's psi0 and the alt/az <-> RA/Dec conversions), so a
        real relocation must rebuild them -- the same reset a mount re-sync
        triggers. GPS jitter below FUSION_LOCATION_RESET_THRESHOLD_M is ignored
        so the anchor is not reset every tick."""
        if location is None:
            return
        try:
            current = (
                float(location.lat),
                float(location.lon),
                0.0 if location.altitude is None else float(location.altitude),
            )
        except (AttributeError, TypeError, ValueError):
            return

        previous = self._fusion_location
        if previous is not None:
            lat1, lon1, alt1 = previous
            lat2, lon2, alt2 = current
            mean_lat = math.radians((lat1 + lat2) / 2.0)
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1) * math.cos(mean_lat)
            horizontal = math.hypot(dlat, dlon) * 6371000.0
            distance = math.hypot(horizontal, alt2 - alt1)
            if distance < FUSION_LOCATION_RESET_THRESHOLD_M:
                return
            # Both tracker paths re-init when the anchor identity changes; drop
            # the tracker too so the component path also rebuilds cleanly.
            self._mount_imu_anchor = None
            self._imu_delta_tracker = None
            self._imu_delta_applied_snapshot = None
            self._reset_solve_average()
            logger.info(
                "Observer location moved %.0f m; resetting mount+IMU fusion "
                "anchor for the new site",
                distance,
            )
        self._fusion_location = current

    def _new_mount_imu_anchor(
        self, mount: CoordinateSample, imu: CoordinateSample
    ) -> dict[str, Any]:
        mount_radec = mount.radec()
        imu_radec = imu.radec()
        assert mount_radec is not None
        assert imu_radec is not None
        imu_altaz = self._imu_raw_altaz(imu)
        return {
            "mount_ra": mount_radec[0],
            "mount_dec": mount_radec[1],
            "imu_ra": imu_radec[0],
            "imu_dec": imu_radec[1],
            "imu_alt": imu_altaz[0] if imu_altaz is not None else None,
            "imu_az": imu_altaz[1] if imu_altaz is not None else None,
            "mount_timestamp": mount.timestamp,
            "sync_key": self._mount_sync_key(mount),
            "created_at": time.time(),
        }

    def _mount_imu_anchor_should_reset(
        self, mount: CoordinateSample, imu: CoordinateSample
    ) -> bool:
        mount_radec = mount.radec()
        imu_radec = imu.radec()
        if mount_radec is None or imu_radec is None:
            return False
        if self._mount_imu_anchor is None:
            return True

        # Re-anchor (which clears the applied disturbance offset) ONLY when a
        # sync re-establishes the mount frame. Mount readback movement alone
        # must not reset: the fused base follows the live readback, and a
        # pulse/slew-triggered reset would silently erase a real physical
        # disturbance offset.
        sync_key = self._mount_sync_key(mount)
        return self._mount_imu_anchor.get("sync_key") != sync_key

    def _mount_sync_key(self, mount: CoordinateSample) -> tuple[Any, ...]:
        sync = mount.metadata.get("coordinate_sync")
        if isinstance(sync, dict):
            return (
                "coordinate_sync",
                sync.get("synced_at"),
                sync.get("ra"),
                sync.get("dec"),
                sync.get("source"),
            )
        multipoint = mount.metadata.get("multipoint_align")
        if isinstance(multipoint, dict):
            return (
                "multipoint_align",
                multipoint.get("started_at"),
                multipoint.get("completed_points"),
                multipoint.get("pifinder_mount_synced"),
            )
        return ("aligned", mount.metadata.get("device"))

    def _annotate_health(
        self,
        current: CoordinateSample,
        imu: CoordinateSample,
        mount: CoordinateSample,
        health: CoordinateHealth,
    ) -> None:
        current_radec = current.radec()
        mount_radec = mount.radec()
        if current_radec is not None and mount_radec is not None:
            health.mount_separation_degrees = angular_separation_degrees(
                current_radec[0],
                current_radec[1],
                mount_radec[0],
                mount_radec[1],
            )
        if imu.valid and mount.valid and health.imu_mount_separation_degrees is None:
            imu_radec = imu.radec()
            if imu_radec is not None and mount_radec is not None:
                health.imu_mount_separation_degrees = angular_separation_degrees(
                    imu_radec[0],
                    imu_radec[1],
                    mount_radec[0],
                    mount_radec[1],
                )
        self._annotate_source_deltas(imu, mount, health)

    def _annotate_source_deltas(
        self,
        imu: CoordinateSample,
        mount: CoordinateSample,
        health: CoordinateHealth,
    ) -> None:
        mount_radec = mount.radec()
        if mount_radec is not None:
            if self._last_health_mount_radec is not None:
                health.mount_delta_degrees = angular_separation_degrees(
                    self._last_health_mount_radec[0],
                    self._last_health_mount_radec[1],
                    mount_radec[0],
                    mount_radec[1],
                )
            self._last_health_mount_radec = mount_radec
        elif self._last_health_mount_radec is not None:
            self._last_health_mount_radec = None

        if imu.valid and imu.alt_deg is not None and imu.az_deg is not None:
            imu_altaz = (float(imu.alt_deg), float(imu.az_deg))
            if self._last_health_imu_altaz is not None:
                health.imu_altaz_delta_degrees = altaz_separation_degrees(
                    self._last_health_imu_altaz[0],
                    self._last_health_imu_altaz[1],
                    imu_altaz[0],
                    imu_altaz[1],
                )
            self._last_health_imu_altaz = imu_altaz
        elif self._last_health_imu_altaz is not None:
            self._last_health_imu_altaz = None

    def _extract_mount_radec(
        self, status: dict[str, Any]
    ) -> Optional[Tuple[float, float]]:
        candidates = [
            status,
            status.get("coordinates"),
            status.get("mount"),
            status.get("readback"),
            status.get("position"),
            status.get("coordinate_sync"),
        ]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            for ra_key, dec_key in (
                ("ra", "dec"),
                ("current_ra", "current_dec"),
                ("mount_ra", "mount_dec"),
                ("readback_ra", "readback_dec"),
                ("eod_ra", "eod_dec"),
            ):
                radec = valid_radec(candidate.get(ra_key), candidate.get(dec_key))
                if radec is not None:
                    return radec
        return None

    def mount_status_is_aligned(self, status: dict[str, Any]) -> bool:
        coordinate_sync = status.get("coordinate_sync")
        if isinstance(coordinate_sync, dict):
            if bool(
                coordinate_sync.get("active")
                or coordinate_sync.get("synced")
                or coordinate_sync.get("mount_synced")
            ):
                return True

        multipoint = status.get("multipoint_align")
        if isinstance(multipoint, dict):
            if bool(multipoint.get("pifinder_mount_synced")):
                return True

        return bool(
            status.get("mount_coordinate_synced")
            or status.get("pifinder_mount_synced")
            or status.get("aligned")
        )

    def mount_sample_is_motion_active(self, mount: CoordinateSample) -> bool:
        return self.mount_status_motion_active(mount.metadata)

    def mount_sample_prefers_readback(self, mount: CoordinateSample) -> bool:
        return self.mount_status_prefers_readback(mount.metadata)

    def mount_sample_allows_imu_delta(self, mount: CoordinateSample) -> bool:
        now = time.monotonic()
        mount_radec = mount.radec()
        readback_priority = self.mount_sample_prefers_readback(mount)
        readback_moving = False

        if mount_radec is not None and self._last_mount_motion_radec is not None:
            readback_delta = angular_separation_degrees(
                self._last_mount_motion_radec[0],
                self._last_mount_motion_radec[1],
                mount_radec[0],
                mount_radec[1],
            )
            readback_moving = readback_delta >= MOUNT_READBACK_MOVING_DELTA_DEGREES

        if mount_radec is not None:
            self._last_mount_motion_radec = mount_radec

        # Readback samples arrive slower than the fusion ticks, so IMU steps
        # from a mount slew can accumulate as a bogus "disturbance" during the
        # window before the next readback reveals the motion. Bookkeep per
        # fresh readback sample: while stationary, snapshot the applied offset;
        # the moment a sample shows movement, roll the offset back to the last
        # stationary snapshot, discarding only that leaked window.
        fresh_sample = (
            mount.timestamp is not None
            and mount.timestamp != self._last_mount_sample_ts
        )
        if fresh_sample:
            self._last_mount_sample_ts = mount.timestamp
            if readback_moving:
                self._rollback_imu_delta_to_snapshot()
            else:
                self._snapshot_imu_delta_applied()

        if readback_priority or readback_moving:
            self._mount_motion_hold_until = max(
                self._mount_motion_hold_until,
                now + MOUNT_IMU_DELTA_HOLD_SECONDS,
            )
            return False

        return now >= self._mount_motion_hold_until

    def _snapshot_imu_delta_applied(self) -> None:
        tracker = self._imu_delta_tracker
        if tracker is not None and tracker.get("anchor") is self._mount_imu_anchor:
            if tracker.get("frame") == "altaz_rot":
                # q_off is replaced (never mutated in place) on each step, so
                # storing the reference is a safe snapshot.
                self._imu_delta_applied_snapshot = ("q_off", tracker["q_off"])
            else:
                self._imu_delta_applied_snapshot = (
                    tracker["applied_ra"],
                    tracker["applied_dec"],
                )
        else:
            self._imu_delta_applied_snapshot = None

    def _rollback_imu_delta_to_snapshot(self) -> None:
        tracker = self._imu_delta_tracker
        snapshot = self._imu_delta_applied_snapshot
        if (
            tracker is None
            or snapshot is None
            or tracker.get("anchor") is not self._mount_imu_anchor
        ):
            return
        if tracker.get("frame") == "altaz_rot":
            if isinstance(snapshot, tuple) and snapshot[0] == "q_off":
                tracker["q_off"] = snapshot[1]
                tracker["episode"] = False
            return
        if isinstance(snapshot, tuple) and snapshot[0] != "q_off":
            tracker["applied_ra"], tracker["applied_dec"] = snapshot
            tracker["episode"] = False

    def mount_status_motion_active(self, status: dict[str, Any]) -> bool:
        if not isinstance(status, dict):
            return False

        if "mount_motion_active" in status:
            return bool(status.get("mount_motion_active"))

        return self._legacy_mount_status_motion_active(status)

    def mount_status_prefers_readback(self, status: dict[str, Any]) -> bool:
        if not isinstance(status, dict):
            return False

        if "mount_readback_priority" in status:
            return bool(status.get("mount_readback_priority"))

        return self._legacy_mount_status_motion_active(status)

    def _legacy_mount_status_motion_active(self, status: dict[str, Any]) -> bool:
        if status.get("goto_motion_active") or status.get("goto_refine_pending"):
            return True
        if status.get("manual_motion_direction"):
            return True

        state = str(status.get("state", "")).strip().lower()
        if state in {
            "slewing",
            "refine_wait",
            "refine_sent",
            "guide_correction",
            "align_goto",
            "manual_motion",
        }:
            return True
        if state.startswith("backlash_auto_") and state not in {
            "backlash_auto_complete",
            "backlash_auto_failed",
            "backlash_auto_stopped",
        }:
            return True
        if "slew" in state or "goto" in state or "refine" in state:
            return True
        if "moving" in state or "motion" in state:
            return True

        multipoint = status.get("multipoint_align")
        if isinstance(multipoint, dict):
            align_state = str(multipoint.get("state", "")).strip().lower()
            if "goto" in align_state or "slew" in align_state:
                return True

        backlash = status.get("backlash_auto")
        if isinstance(backlash, dict):
            backlash_state = str(backlash.get("state", "")).strip().lower()
            if backlash_state in {"starting", "running"}:
                return True

        return False

    def mount_status_is_usable(self, status: dict[str, Any]) -> tuple[bool, str]:
        state = str(status.get("state", "")).strip().lower()
        message = str(status.get("message", "")).strip().lower()
        if state in {
            "disconnected",
            "disconnecting",
            "error",
            "fault",
            "failed",
            "server_offline",
            "driver_offline",
        }:
            return False, f"mount state unusable: {state}"
        if "disconnected" in message or "failed" in message:
            return False, "mount message reports disconnected/failed"

        for key in ("park_state", "driver_mount_status"):
            raw = str(status.get(key, "")).strip().lower()
            if raw and "park" in raw and "unpark" not in raw:
                return False, f"mount is parked: {key}={status.get(key)}"

        raw_status = str(status.get("raw_mount_status", ""))
        # OnStep status strings commonly start with P when parked and N when
        # not parked.  Treat only an explicit leading P as unusable here.
        if raw_status.startswith("P"):
            return False, f"mount is parked: raw_mount_status={raw_status}"

        return True, ""
