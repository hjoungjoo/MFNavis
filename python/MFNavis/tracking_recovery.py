"""Bounded recovery decisions. Absolute observations authorize Sync+GoTo."""

from collections import deque
import math
import uuid

import numpy as np

from PiFinder.tracking_contracts import CaptureTiming
from PiFinder.tracking_quality import tangent_error
from PiFinder.visual_tracking import CameraGeometry, vector_radec


class RecoveryCoordinator:
    def __init__(self, profile, budget):
        self.profile, self.budget = profile, budget
        self.references = deque(maxlen=3)
        self.state = "idle"
        self.request_id = None
        self.deadline = 0.0
        self.observation_after = 0.0
        self.last_reference = None
        self.sync_applied = False
        self.reason = ""

    def observe_reference(self, reference, target):
        if not reference or reference["id"] == self.last_reference:
            return
        timing = CaptureTiming(**reference["timing"])
        geometry = CameraGeometry(**reference["geometry"])
        aligned = vector_radec(
            geometry.rays([geometry.target_yx])[0] @ np.asarray(reference["pose"])
        )
        self.references.append(
            {
                "id": reference["id"],
                "timing": timing,
                "aligned": aligned,
                "error": tangent_error(aligned, target),
                "geometry": reference["geometry_key"],
                "epoch": reference["capture_epoch"],
            }
        )
        self.last_reference = reference["id"]

    def propose(self, measurement, permission, now, *, axis_supported=False):
        p = self.profile
        if self.state not in {"idle", "ready"} or not measurement.valid:
            return None
        error = float(np.linalg.norm(measurement.error))
        if permission.allow_axis and axis_supported and p.axis.get("verified"):
            # Actual adapter must provide device-timed termination, not just a
            # Python timer; capability is supplied by the adapter, not JSON.
            self.reason = "axis_recovery_available"
            return {"kind": "axis", "error": measurement.error}
        if not permission.allow_goto or not p.goto.get("verified"):
            self.reason = "recovery_not_verified"
            return None
        if len(self.references) < 2:
            self.reason = "confirming_absolute_recovery"
            return None
        a, b = list(self.references)[-2:]
        if (
            a["epoch"] != b["epoch"]
            or a["geometry"] != b["geometry"]
            or b["geometry"] != measurement.context.geometry
            or not b["timing"].usable(now, p.max_age_s, p.max_timing_uncertainty_s)
            or not a["timing"].usable(now, p.max_age_s, p.max_timing_uncertainty_s)
            or b["epoch"] != measurement.context.capture_epoch
            or b["timing"].midpoint <= a["timing"].midpoint
            or a["timing"].start_min <= self.observation_after
        ):
            self.reason = "absolute_recovery_reference_stale"
            return None
        tolerance = max(
            2 * measurement.bound_arcsec,
            p.max_drift_arcsec_s * (b["timing"].midpoint - a["timing"].midpoint),
        )
        if np.linalg.norm(np.asarray(a["error"]) - b["error"]) > tolerance:
            self.reason = "absolute_recovery_disagreement"
            return None
        if np.linalg.norm(np.asarray(measurement.error) - b["error"]) > tolerance:
            self.reason = "absolute_relative_disagreement"
            return None
        maximum = float(p.goto.get("max_separation_deg", 0)) * 3600
        if not math.isfinite(maximum) or not 0 < error <= maximum:
            self.reason = "recovery_travel_limit"
            return None
        if not self.budget.reserve(now, measurement.key, error, error):
            self.state, self.reason = "limited", "recovery_budget_exhausted"
            return None
        self.request_id = uuid.uuid4().hex
        self.state, self.reason = "requested", "fresh_absolute_recovery"
        self.deadline = now + p.recovery_time_s
        return {
            "kind": "goto",
            "request_id": self.request_id,
            "current_catalog": b["aligned"],
            "target_catalog": measurement.context.target,
        }

    def progress(self, status, moving, now):
        if self.state not in {"requested", "moving", "observing"}:
            return self.state
        if now >= self.deadline:
            self.state, self.reason = "limited", "recovery_timeout"
        elif status and status.get("request_id") == self.request_id:
            self.sync_applied = self.sync_applied or "verified_monotonic" in status
            if status.get("state") in {"failed", "cancelled"}:
                self.state = "limited"
                self.reason = (
                    "sync_applied_goto_cancelled"
                    if self.sync_applied
                    else "recovery_failed"
                )
            elif status.get("state") == "goto_sent":
                if moving:
                    self.state = "moving"
                elif self.state != "observing":
                    self.state = "observing"
                    self.observation_after = now + self.profile.settle_s
                    self.reason = "waiting_absolute_arrival"
        if self.state == "observing" and self.references:
            latest = self.references[-1]
            if latest["timing"].start_min > self.observation_after:
                error = float(np.linalg.norm(latest["error"]))
                if error <= max(
                    self.profile.deadband_arcsec,
                    self.profile.max_error_bound_arcsec * 2,
                ):
                    self.state, self.reason = "complete", "arrival_observed"
                elif (
                    self.budget.last_error is not None
                    and error < self.budget.last_error
                ):
                    self.state, self.reason = "ready", "recovery_progress_observed"
                else:
                    self.state, self.reason = "limited", "recovery_no_optical_progress"
        return self.state

    def cancel(self):
        self.state = "limited"
        self.reason = (
            "sync_applied_goto_cancelled" if self.sync_applied else "recovery_cancelled"
        )
