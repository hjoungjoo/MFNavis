"""Versioned, serializable contracts for optional optical tracking.

No hardware access. Times ending in ``_mono`` belong to the local monotonic
clock; wall times are only for pointing publication and audit records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math

import numpy as np

COAST_REASONS = frozenset(
    {"stars_lost_or_ambiguous", "too_few_stars", "poor_spatial_distribution"}
)


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False, default=str).encode()
    ).hexdigest()[:24]


def finite(value, name="value", *, positive=False) -> float:
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"invalid {name}")
    return result


@dataclass(frozen=True)
class TrackingContext:
    session: str
    geometry: str
    capture_epoch: str
    connection: int
    control: int
    reference: str
    target: tuple[float, float]
    frame: str = "catalog"

    def __post_init__(self):
        if not all((self.session, self.geometry, self.capture_epoch, self.reference)):
            raise ValueError("incomplete tracking context")
        if self.frame != "catalog" or len(self.target) != 2:
            raise ValueError("explicit catalog target required")
        finite(self.target[0])
        finite(self.target[1])
        if abs(self.target[1]) > 90:
            raise ValueError("invalid target declination")


@dataclass(frozen=True)
class CaptureTiming:
    start_min: float
    end_max: float
    midpoint: float
    uncertainty: float
    wall_midpoint: float
    verified: bool
    clock_epoch: str

    def usable(self, now, max_age, max_uncertainty):
        values = (
            self.start_min,
            self.end_max,
            self.midpoint,
            self.uncertainty,
            self.wall_midpoint,
            now,
        )
        return (
            all(math.isfinite(v) for v in values)
            and self.verified
            and bool(self.clock_epoch)
            and self.start_min <= self.midpoint <= self.end_max <= now
            and 0 <= self.uncertainty <= max_uncertainty
            and now - self.start_min <= max_age
        )


@dataclass(frozen=True)
class TrackingMeasurement:
    context: TrackingContext
    sequence: int
    timing: CaptureTiming
    error: tuple[float, float]
    bound_arcsec: float
    quality: str
    reason: str
    camera_radec_roll: tuple[float, float, float] | None = None
    aligned_radec: tuple[float, float] | None = None
    stars: int = 0
    rmse_px: float | None = None
    exposure: tuple[float, float] = (0.0, 0.0)
    absolute: bool = False
    source: str = "catalog_stars"
    degrees_of_freedom: int = 3
    model_pointing: tuple[float, float] | None = None
    target_radec: tuple[float, float] | None = None

    @property
    def key(self):
        return self.context.capture_epoch, self.sequence

    @property
    def valid(self):
        return (
            self.quality in {"valid", "degraded"}
            and self.sequence >= 0
            and len(self.error) == 2
            and all(math.isfinite(v) for v in self.error)
            and math.isfinite(self.bound_arcsec)
            and self.bound_arcsec >= 0
        )


@dataclass(frozen=True)
class TrackingPermission:
    context: TrackingContext
    expires_mono: float
    quality_floor: int
    allow_prediction: bool = True
    allow_axis: bool = False
    allow_goto: bool = False
    purpose: str = "tracking"


@dataclass(frozen=True)
class CorrectionPlan:
    command_id: str
    context: TrackingContext
    measurement_key: tuple[str, int]
    quality_revision: int
    direction: str
    duration_ms: int
    expires_mono: float
    expected_delta: tuple[float, float]
    predicted: bool = False
    kind: str = "pulse"
    model_pointing: tuple[float, float] | None = None


@dataclass
class CorrectionReceipt:
    command_id: str
    state: str
    submitted_mono: float
    end_max_mono: float | None = None
    reason: str = ""
    end_confirmed: bool = False


@dataclass(frozen=True)
class TrackingProfile:
    """Empty/unverified profiles can observe but never authorize hardware.

    Response columns are N,S,E,W in the fixed TARGET tangent plane, arcsec/ms.
    A measured model has an explicit sky-position validity radius.
    """

    profile_id: str = "unverified"
    verified: bool = False
    equipment_verified: bool = False
    device: str = ""
    driver: str = ""
    camera: str = ""
    geometry: str = ""
    mount_type: str = "Alt/Az"
    pier_side: str = ""
    guide_rate: tuple[float, float] = (0.5, 0.5)
    response: tuple = ((0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0))
    response_fractional_bound: float = 0.25
    model_target: tuple[float, float] = (0.0, 0.0)
    model_radius_deg: float = 2.0
    min_pulse_ms: int = 50
    max_pulse_ms: int = 250
    max_duty: float = 0.25
    start_delay_bound_s: float = 0.25
    settle_s: float = 0.3
    stop_bound_s: float = 1.0
    max_age_s: float = 2.0
    max_timing_uncertainty_s: float = 0.05
    max_error_bound_arcsec: float = 30.0
    deadband_arcsec: float = 10.0
    kp: float = 0.25
    ramp_s: float = 3.0
    prediction_horizon_s: float = 0.5
    max_drift_arcsec_s: float = 5.0
    reference_valid_s: float = 120.0
    min_stars: int = 6
    min_regions: int = 3
    max_rmse_px: float = 1.0
    max_condition: float = 100.0
    roi_radius_px: int = 12
    max_stars: int = 48
    min_snr: float = 8.0
    max_elongation: float = 2.5
    max_width_px: float = 4.0
    reference_bound_arcsec: float = 0.0
    timing: dict = field(default_factory=dict)
    axis: dict = field(default_factory=dict)
    goto: dict = field(default_factory=dict)
    recovery_count: int = 3
    recovery_time_s: float = 60.0
    recovery_travel_arcsec: float = 1800.0
    coast_verified: bool = False
    coast_max_s: float = 0.5
    coast_error_bound_arcsec: float = 5.0
    coast_travel_arcsec: float = 2.0
    coast_external_rate_bound: float = 5.0
    local_reference: dict = field(default_factory=dict)

    def __post_init__(self):
        for name in (
            "min_pulse_ms",
            "max_pulse_ms",
            "min_stars",
            "max_stars",
            "roi_radius_px",
            "min_regions",
            "recovery_count",
        ):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        for name in ("timing", "axis", "goto", "local_reference"):
            if not isinstance(getattr(self, name), dict):
                raise ValueError(f"{name} must be an object")
        for name in (
            "model_radius_deg",
            "start_delay_bound_s",
            "settle_s",
            "stop_bound_s",
            "max_age_s",
            "max_timing_uncertainty_s",
            "max_error_bound_arcsec",
            "deadband_arcsec",
            "kp",
            "ramp_s",
            "prediction_horizon_s",
            "max_drift_arcsec_s",
            "reference_valid_s",
            "max_rmse_px",
            "max_condition",
            "min_snr",
            "max_elongation",
            "max_width_px",
            "recovery_time_s",
            "recovery_travel_arcsec",
            "coast_max_s",
            "coast_error_bound_arcsec",
            "coast_travel_arcsec",
            "coast_external_rate_bound",
        ):
            finite(getattr(self, name), name, positive=True)
        if not 1 <= self.min_pulse_ms <= self.max_pulse_ms <= 2500:
            raise ValueError("invalid pulse bounds")
        if not 0 < finite(self.max_duty) <= 0.5:
            raise ValueError("invalid pulse duty")
        if not 0 <= finite(self.response_fractional_bound) < 1:
            raise ValueError("invalid pulse response uncertainty")
        if not 0 < self.kp <= 1:
            raise ValueError("position gain exceeds conservative bound")
        if self.start_delay_bound_s + self.max_pulse_ms / 1000 > self.stop_bound_s:
            raise ValueError("pulse exceeds Stop bound")
        if not 6 <= self.min_stars <= self.max_stars <= 128:
            raise ValueError("invalid star count")
        if not 2 <= self.roi_radius_px <= 32 or not 3 <= self.min_regions <= 4:
            raise ValueError("invalid ROI/region bound")
        if self.mount_type not in {"Alt/Az", "EQ"} or self.recovery_count < 1:
            raise ValueError("invalid mount/recovery profile")
        if self.coast_max_s > min(2.0, self.max_age_s):
            raise ValueError("coast duration exceeds short observation bound")
        if self.coast_verified and not self.verified:
            raise ValueError("coast requires verified pulse response")
        b = np.asarray(self.response, dtype=float)
        if b.shape != (2, 4) or not np.isfinite(b).all():
            raise ValueError("response must be finite 2x4")
        if len(self.guide_rate) != 2 or any(finite(v) <= 0 for v in self.guide_rate):
            raise ValueError("invalid guide rates")
        if len(self.model_target) != 2 or abs(finite(self.model_target[1])) > 90:
            raise ValueError("invalid response location")
        finite(self.model_target[0])
        if finite(self.reference_bound_arcsec) < 0:
            raise ValueError("invalid reference bound")
        if self.verified or self.equipment_verified:
            if self.reference_bound_arcsec <= 0:
                raise ValueError("verified absolute reference error bound required")
            if self.timing.get("camera") != self.camera or not self.timing.get(
                "backend"
            ):
                raise ValueError("timing must identify camera and capture backend")
            if not all((self.device, self.driver, self.camera, self.geometry)):
                raise ValueError("verified profile requires equipment identity")
            if self.mount_type == "EQ" and not self.pier_side:
                raise ValueError("EQ requires verified pier-side semantics")
            if not self.timing.get("verified"):
                raise ValueError("verified capture timing required")
            if self.timing.get("clock") not in {
                "monotonic",
                "boottime",
            } or self.timing.get("timestamp_semantics") not in {
                "first_row_readout",
                "first_row_exposure_start",
            }:
                raise ValueError("explicit sensor timestamp semantics required")
            for name in ("uncertainty_s", "rolling_skew_bound_s"):
                if finite(self.timing.get(name, -1)) < 0:
                    raise ValueError("invalid sensor timing bound")
            if (
                self.timing["uncertainty_s"] + self.timing["rolling_skew_bound_s"] / 2
                > self.max_timing_uncertainty_s
            ):
                raise ValueError("sensor timing exceeds observation uncertainty budget")
        if self.verified:
            if np.linalg.matrix_rank(b) != 2 or np.linalg.cond(b) > self.max_condition:
                raise ValueError("unobservable pulse response")
            if any(np.dot(b[:, a], b[:, a + 1]) >= 0 for a in (0, 2)):
                raise ValueError("opposing responses must oppose")
        local = self.local_reference
        if local:
            if type(local.get("verified")) is not bool:
                raise ValueError("explicit local optical verification required")
            if local["verified"]:
                shape = local.get("raw_shape", ())
                if len(shape) != 2 or any(type(v) is not int or v < 8 for v in shape):
                    raise ValueError("invalid local RAW dimensions")
                if not local.get("optics") or not isinstance(local.get("info"), dict):
                    raise ValueError("local optical identity required")
                if not 0 < finite(local.get("fov_deg", -1)) < 120:
                    raise ValueError("invalid local FOV")
                finite(local.get("roll_deg", float("nan")))
                if (
                    not 0
                    < finite(local.get("bound_arcsec", -1))
                    <= self.max_error_bound_arcsec
                ):
                    raise ValueError("invalid local optical error bound")
                if self.mount_type == "Alt/Az":
                    finite(local.get("roll_timestamp", float("nan")))
                    baseline = local.get("roll_target", ())
                    if len(baseline) != 2 or abs(finite(baseline[1])) > 90:
                        raise ValueError("Alt/Az local roll baseline required")
                    finite(baseline[0])

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("tracking profile must be an object")
        return cls(**value)

    def to_dict(self):
        return asdict(self)
