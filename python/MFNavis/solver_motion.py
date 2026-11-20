"""Distinguish small IMU jitter from a change of the solver's camera field."""

from __future__ import annotations

import math
from typing import Any, Mapping

import quaternion

from PiFinder.pointing_model.quaternion_transforms import get_quat_angular_diff


class SolverMotionGate:
    """Use measured angular displacement before discarding temporal evidence.

    The IMU's per-sample moving bit is deliberately sensitive for dead reckoning.
    It must not independently tear down preprocessing on a stationary field.
    Keep a fixed orientation reference so a slow pan cannot evade the existing
    0.1-degree exposure-motion limit by moving a little on each frame.
    """

    def __init__(self, threshold_deg: float = 0.1):
        self.threshold_deg = threshold_deg
        self._reference: quaternion.quaternion | None = None
        self.reason = "stationary"
        self.displacement_deg: float | None = None

    def evaluate(self, metadata: Mapping[str, Any], *, mount_moving: bool) -> bool:
        imu = metadata.get("imu")
        imu_moving = bool(getattr(imu, "moving", False))
        self.displacement_deg = None
        try:
            exposure_delta = abs(float(metadata.get("imu_delta") or 0.0))
        except (TypeError, ValueError, OverflowError):
            exposure_delta = math.inf
        if not math.isfinite(exposure_delta):
            self._reference = None
            self.reason = "invalid_exposure_motion"
            return True

        # Only a calibrated, healthy sample contemporary with this exposure
        # can override the instantaneous moving flag.
        orientation = None
        try:
            exposure_end = float(metadata["exposure_end"])
            if (
                imu is not None
                and math.isfinite(exposure_end)
                and imu.is_usable(now=exposure_end)
            ):
                orientation = imu.quat
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            pass

        if mount_moving or exposure_delta > self.threshold_deg:
            self._reference = orientation
            self.reason = "mount_motion" if mount_moving else "exposure_motion"
            return True

        if orientation is None:
            self._reference = None
            self.reason = "unverified_imu_motion" if imu_moving else "no_usable_imu"
            return imu_moving

        if self._reference is None:
            self._reference = orientation
        self.displacement_deg = math.degrees(
            get_quat_angular_diff(self._reference, orientation)
        )
        if self.displacement_deg > self.threshold_deg:
            self._reference = orientation
            self.reason = "field_displacement"
            return True

        self.reason = "small_imu_jitter" if imu_moving else "stationary"
        return False

    def status(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "displacement_deg": self.displacement_deg,
            "threshold_deg": self.threshold_deg,
        }
