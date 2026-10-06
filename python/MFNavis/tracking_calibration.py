"""Explicit, bounded pulse-response calibration; never activates its own model."""

from collections import deque
import uuid

import numpy as np

from PiFinder.tracking_contracts import CorrectionPlan
from PiFinder.tracking_control import DIRECTIONS, TrackingController
from PiFinder.tracking_mount_adapter import PulseCalibration


class CalibrationController(TrackingController):
    def __init__(self, profile):
        super().__init__(profile)
        self.collector = PulseCalibration(profile)
        self.baseline = deque(maxlen=8)
        self.before = None
        self.probe_drift = None
        self.probe_direction = None
        self.probes = 0
        self.started = None
        self.candidate = None
        self.probe_travel = 0.0

    def hold(self, reason, **kwargs):
        # Calibration cannot infer a pulse's response across an interruption.
        super().hold(reason, **kwargs)
        self.state = "LIMITED" if self.started is not None else "ACQUIRING"
        self.baseline.clear()

    def tick(self, snapshot, now, epoch):
        if self.state in {"DISABLED", "LIMITED", "CALIBRATION_COMPLETE"}:
            return None
        if self.started is None and snapshot.get("permission") is None:
            return None
        if self.started is None:
            self.started = now
        if now - self.started > self.profile.recovery_time_s:
            self.hold("calibration_timeout")
            return None
        reason = self._usable(snapshot, now, epoch)
        if reason or snapshot["permission"].purpose != "calibration":
            self.hold(reason or "calibration_permission_required")
            return None
        m = snapshot["measurement"]
        if m.key == self.last_key or self.pending_plan:
            return None
        self.last_key = m.key
        if self.inflight:
            end = self.inflight.end_max_mono
            if end is None or self.inflight.state == "unknown":
                self.hold("calibration_outcome_unknown")
                return None
            if m.timing.start_min <= end + self.profile.settle_s:
                return None
            try:
                self.collector.add(
                    self.probe_direction,
                    self.profile.max_pulse_ms,
                    self.before,
                    m,
                    self.probe_drift,
                    end,
                )
            except ValueError as exc:
                self.hold(str(exc))
                return None
            self.probes += 1
            self.probe_travel += float(
                np.linalg.norm(
                    np.asarray(self.before.error)
                    - m.error
                    + self.probe_drift
                    * (m.timing.midpoint - self.before.timing.midpoint)
                )
            )
            if self.probe_travel > self.profile.recovery_travel_arcsec:
                self.hold("calibration_travel_limit")
                return None
            self.inflight = None
            self.baseline.clear()
            if self.probes == 12:
                try:
                    response = self.collector.response().tolist()
                    candidate = {
                        **self.profile.to_dict(),
                        "response": response,
                        "model_target": self.context.target,
                        "verified": True,
                    }
                    # Validate rank/signs, but leave activation to explicit review.
                    type(self.profile).from_dict(candidate)
                    candidate["verified"] = False
                    candidate["coast_verified"] = False
                    candidate["axis"] = {**candidate["axis"], "verified": False}
                    candidate["goto"] = {**candidate["goto"], "verified": False}
                    self.candidate = candidate
                    self.state, self.reason = (
                        "CALIBRATION_COMPLETE",
                        "candidate_requires_review",
                    )
                except ValueError as exc:
                    self.hold(str(exc))
                return None
        # Keep a time-spanning baseline even when video arrives faster than
        # the bounded history can retain two seconds of consecutive frames.
        if (
            self.baseline
            and m.timing.midpoint - self.baseline[-1].timing.midpoint < 0.5
        ):
            return None
        self.baseline.append(m)
        self.state, self.reason = "CALIBRATING", "measuring_uncommanded_drift"
        if len(self.baseline) < 4:
            return None
        first = self.baseline[0]
        if m.timing.midpoint - first.timing.midpoint < 2:
            return None
        if now < self.next_send:
            return None
        times = np.array([s.timing.midpoint for s in self.baseline])
        errors = np.array([s.error for s in self.baseline])
        velocities = np.diff(errors, axis=0) / np.diff(times)[:, None]
        drift = np.median(velocities, axis=0)
        residual = errors - errors[0] - (times - times[0])[:, None] * drift
        if (
            np.max(np.linalg.norm(residual, axis=1))
            > 2 * max(s.bound_arcsec for s in self.baseline)
            or np.linalg.norm(drift) > self.profile.max_drift_arcsec_s
        ):
            self.hold("unstable_calibration_baseline")
            return None
        direction = DIRECTIONS[self.probes % 4]
        self.before, self.probe_drift, self.probe_direction = m, drift, direction
        plan = CorrectionPlan(
            uuid.uuid4().hex,
            m.context,
            m.key,
            snapshot["quality_revision"],
            direction,
            self.profile.max_pulse_ms,
            min(now + 0.2, snapshot["permission"].expires_mono),
            (0.0, 0.0),
            kind="calibration",
        )
        self.pending_plan = plan
        return plan

    def status(self):
        return {
            **super().status(),
            "calibration_probes": self.probes,
            "calibration_candidate": self.candidate,
        }
