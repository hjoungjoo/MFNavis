"""Replayable controller. Plans are proposals; only mountcontrol executes them."""

from collections import deque
from dataclasses import asdict
import math
import logging
import json
import uuid

import numpy as np

from PiFinder.tracking_contracts import COAST_REASONS, CorrectionPlan
from PiFinder.tracking_motion import MotionHistory

DIRECTIONS = ("north", "south", "east", "west")


class RecoveryBudget:
    def __init__(self, profile):
        self.profile = profile
        self.started = None
        self.count = 0
        self.travel = 0.0
        self.last_key = None
        self.last_error = None

    def reserve(self, now, key, error, travel):
        p = self.profile
        if self.started is None:
            self.started = now
        if (
            key == self.last_key
            or self.count >= p.recovery_count
            or now - self.started >= p.recovery_time_s
            or travel < 0
            or self.travel + travel > p.recovery_travel_arcsec
            or not all(math.isfinite(x) for x in (error, travel))
            or (self.last_error is not None and error >= self.last_error)
        ):
            return False
        self.count += 1
        self.travel += travel
        self.last_key, self.last_error = key, error
        return True


class TrackingController:
    def __init__(self, profile):
        self.profile = profile
        self.context = None
        self.state, self.reason = "DISABLED", "not_armed"
        self.history = MotionHistory()
        self.budget = RecoveryBudget(profile)
        self.last_key = None
        self.last_measurement = None
        self.last_time = None
        self.drift = None
        self.position_remaining = np.zeros(2)
        self.applied = np.zeros(2)
        self.inflight = None
        self.ready_after = 0.0
        self.next_send = 0.0
        self.ramp_started = None
        self.confirmations = 0
        self.confirmation_started = None
        self.pending_plan = None
        self.events = deque(maxlen=128)
        self.sent_ids = set()
        self.prediction_step = 0
        self.saturation = deque(maxlen=8)
        self.recovery_request = None
        self.coast_anchor = None
        self.coast_drift = None
        self.coast_travel = 0.0
        self.coasting = False

    def arm(self, context):
        self.__init__(self.profile)
        self.context = context
        self.state, self.reason = "ACQUIRING", "waiting_new_observations"

    def hold(self, reason, *, disturbance=False):
        if self.state == "DISABLED":
            return
        self.state = "DISTURBANCE_HOLD" if disturbance else "QUALITY_HOLD"
        self.reason = reason
        self.position_remaining[:] = 0
        self.drift = self.pending_plan = self.recovery_request = None
        self.ramp_started = None
        self.confirmations = 0
        self.confirmation_started = None
        self.coast_anchor = self.coast_drift = None
        # Step confirmation needs its pending candidate across hold ticks.
        if not disturbance:
            self.history.reset()

    def disable(self, reason):
        self.hold(reason)
        self.state, self.reason = "DISABLED", reason
        self.context = None
        self.coast_anchor = self.coast_drift = None

    def _coast_usable(self, snapshot, now, epoch):
        m, permission = snapshot.get("measurement"), snapshot.get("permission")
        p, anchor = self.profile, self.coast_anchor
        if (
            not p.coast_verified
            or anchor is None
            or self.coast_drift is None
            or snapshot.get("fault")
            or epoch != self.context.control
            or m is None
            or m.context != self.context
            or m.reason not in COAST_REASONS
            or permission is None
            or permission.context != self.context
            or permission.purpose != "coast"
            or not permission.allow_prediction
            or not math.isfinite(permission.expires_mono)
            or now >= permission.expires_mono
            or permission.quality_floor < snapshot.get("invalid_revision", 0)
            or not m.timing.usable(now, p.max_age_s, p.max_timing_uncertainty_s)
        ):
            return False
        horizon = (
            now + p.start_delay_bound_s + p.max_pulse_ms / 1000 - anchor.timing.midpoint
        )
        bound = anchor.bound_arcsec + horizon * p.coast_external_rate_bound
        return (
            0 <= horizon <= p.coast_max_s
            and bound <= p.coast_error_bound_arcsec
            and self.coast_travel < p.coast_travel_arcsec
        )

    def _usable(self, snapshot, now, epoch):
        m, permission = snapshot.get("measurement"), snapshot.get("permission")
        if snapshot.get("fault"):
            return "worker_fault"
        if self.context is None or epoch != self.context.control:
            return "control_epoch_changed"
        if self._coast_usable(snapshot, now, epoch):
            return ""
        if m is None or m.context != self.context or not m.valid:
            return "invalid_measurement"
        if not m.timing.usable(
            now, self.profile.max_age_s, self.profile.max_timing_uncertainty_s
        ):
            return "stale_measurement"
        if m.bound_arcsec > self.profile.max_error_bound_arcsec:
            return "uncertainty_exceeds_budget"
        if (
            permission is None
            or permission.context != self.context
            or not math.isfinite(permission.expires_mono)
            or now >= permission.expires_mono
            or permission.quality_floor < snapshot.get("invalid_revision", 0)
        ):
            return "permission_expired_or_revoked"
        return ""

    def tick(self, snapshot, now, epoch):
        if self.state in {"DISABLED", "LIMITED"}:
            return None
        reason = self._usable(snapshot, now, epoch)
        if reason:
            self.hold(reason)
            return None
        m = snapshot["measurement"]
        permission = snapshot["permission"]
        coast = not m.valid
        if self.pending_plan is not None:
            # A plan must be consumed or explicitly rejected before planning more.
            return None
        if self.inflight:
            if self.inflight.state == "unknown" or self.inflight.end_max_mono is None:
                self.hold("command_outcome_unknown")
                return None
            if now < self.inflight.end_max_mono + self.profile.settle_s:
                return None
            self.ready_after = self.inflight.end_max_mono + self.profile.settle_s
            self.inflight = None
        fresh = m.key != self.last_key
        if coast:
            self.position_remaining[:] = 0
            self.confirmations = 0
            self.ramp_started = self.confirmation_started = None
            self.history.reset()
            self.coasting = True
            self.state, self.reason = "PREDICTION_COAST", "bounded_last_verified_drift"
        elif self.coasting:
            self.coasting = False
            self.hold("coast_ended_reconfirm")
        if fresh and not coast:
            if self.last_key and m.sequence <= self.last_key[1]:
                self.hold("out_of_order_measurement")
                return None
            self.last_key = m.key
            # An exposure overlapping our previous command is not a clean
            # position/response observation; preserve the waiting state.
            if m.timing.start_min <= self.ready_after:
                self.reason = "waiting_post_command_exposure"
                return None
            mode, drift = self.history.observe(
                m.timing.midpoint,
                m.error,
                self.applied,
                m.bound_arcsec,
                self.profile.max_drift_arcsec_s,
            )
            if mode in {"step_pending", "oscillatory", "unknown"}:
                self.hold(mode, disturbance=True)
                return None
            if self.confirmation_started is None:
                self.confirmation_started = m.timing.midpoint
            self.confirmations += 1
            if (
                self.confirmations < 3
                or m.timing.midpoint - self.confirmation_started < 0.5
            ):
                self.reason = "confirming_independent_frames"
                return None
            if self.ramp_started is None:
                self.ramp_started = now
            dt = min(
                1.0,
                max(
                    0.05,
                    m.timing.midpoint - (self.last_time or m.timing.midpoint - 0.5),
                ),
            )
            self.last_time = m.timing.midpoint
            self.last_measurement = m
            self.drift = drift if m.quality == "valid" else None
            if self.drift is not None:
                self.coast_anchor, self.coast_drift = m, self.drift.copy()
                self.coast_travel = 0.0
            error = np.asarray(m.error)
            distance = np.linalg.norm(error)
            deadband = max(self.profile.deadband_arcsec, 2 * m.bound_arcsec)
            usable_error = error * max(0.0, 1 - deadband / max(distance, 1e-12))
            ramp = min(1.0, (now - self.ramp_started) / self.profile.ramp_s)
            gain = self.profile.kp * (0.3 if m.quality == "degraded" else 1.0)
            self.position_remaining = gain * usable_error * dt * ramp
            self.state = (
                "DEGRADED_TRACKING" if m.quality == "degraded" else "FINE_TRACKING"
            )
            self.reason = mode
        elif not coast and (
            self.last_measurement is None or m.key != self.last_measurement.key
        ):
            return None
        if now < self.next_send:
            return None
        desired = self.position_remaining.copy()
        predicted = False
        if coast:
            desired = self.coast_drift * min(0.2, self.profile.coast_max_s)
            predicted = True
        elif (
            np.linalg.norm(desired) <= 1e-9
            and permission.allow_prediction
            and self.drift is not None
        ):
            if now - m.timing.midpoint > self.profile.prediction_horizon_s:
                return None
            desired = self.drift * min(0.2, self.profile.prediction_horizon_s)
            predicted = True
        b = np.asarray(self.profile.response)
        norms = np.linalg.norm(b, axis=0)
        if not self.profile.verified or np.any(norms <= 0):
            self.reason = "response_profile_unverified"
            return None
        # Pick a physical direction that reduces the residual. Serial packets
        # compete for one duty budget and never contain opposing directions.
        dot = b.T @ desired
        durations = np.maximum(0, dot / np.maximum(norms**2, 1e-15))
        scores = dot / norms
        axis = int(np.argmax(scores))
        duration = min(self.profile.max_pulse_ms, math.floor(durations[axis]))
        if duration < self.profile.min_pulse_ms:
            return None
        saturated = durations[axis] > self.profile.max_pulse_ms
        if fresh:
            self.saturation.append((now, saturated, float(np.linalg.norm(m.error))))
        if len(self.saturation) >= 3:
            recent = list(self.saturation)[-3:]
            if all(s[1] for s in recent) and recent[-1][0] - recent[0][0] >= 2:
                self.state, self.reason = "PULSE_RECOVERY", "pulse_saturated"
                if recent[-1][2] >= recent[0][2]:
                    if not (permission.allow_axis or permission.allow_goto):
                        self.hold("pulse_capacity_insufficient")
                        self.state = "LIMITED"
                        return None
                    self.recovery_request = {
                        "measurement_key": m.key,
                        "error": m.error,
                        "absolute": m.absolute,
                        "reason": "capacity_insufficient",
                    }
        delta = b[:, axis] * duration
        total_bound = (
            m.bound_arcsec
            + np.linalg.norm(delta) * self.profile.response_fractional_bound
            + self.profile.max_drift_arcsec_s
            * (m.timing.uncertainty + self.profile.start_delay_bound_s)
        )
        if not coast and (
            total_bound > self.profile.max_error_bound_arcsec
            or np.linalg.norm(delta) <= m.bound_arcsec
        ):
            self.reason = "command_uncertainty_exceeds_budget"
            return None
        if (
            coast
            and self.coast_travel + np.linalg.norm(delta)
            > self.profile.coast_travel_arcsec
        ):
            return None
        expiry = min(
            permission.expires_mono,
            m.timing.start_min + self.profile.max_age_s,
            now + 0.2,
        )
        if coast:
            remaining = min(
                self.profile.coast_max_s,
                (self.profile.coast_error_bound_arcsec - self.coast_anchor.bound_arcsec)
                / self.profile.coast_external_rate_bound,
            )
            expiry = min(
                expiry,
                self.coast_anchor.timing.midpoint
                + remaining
                - self.profile.start_delay_bound_s
                - duration / 1000,
            )
        plan = CorrectionPlan(
            uuid.uuid4().hex,
            self.context,
            m.key,
            snapshot["quality_revision"],
            DIRECTIONS[axis],
            duration,
            expiry,
            tuple(delta),
            predicted,
            "coast" if coast else "pulse",
            self.coast_anchor.aligned_radec
            if coast
            else (m.model_pointing or m.aligned_radec),
        )
        self.pending_plan = plan
        return plan

    def validate_dispatch(self, plan, snapshot, now, epoch):
        return (
            plan is self.pending_plan
            and plan.command_id not in self.sent_ids
            and now < plan.expires_mono
            and not self._usable(snapshot, now, epoch)
            and snapshot["quality_revision"] == plan.quality_revision
            and snapshot["measurement"].key == plan.measurement_key
        )

    def acknowledge(self, plan, receipt):
        if self.pending_plan is not plan:
            raise ValueError("receipt without pending plan")
        self.pending_plan = None
        self.events.append({"plan": asdict(plan), "receipt": asdict(receipt)})
        logging.getLogger("SmoothTracking").info(
            "tracking_command %s", json.dumps(self.events[-1])
        )
        if receipt.state not in {"accepted", "ended"}:
            self.inflight = receipt if receipt.state == "unknown" else None
            self.hold(receipt.reason or "command_rejected")
            return
        self.sent_ids.add(plan.command_id)
        # IDs only live for the session; keep memory bounded independently of run length.
        if len(self.sent_ids) > 256:
            self.sent_ids = {plan.command_id}
        self.applied += np.asarray(plan.expected_delta)
        if not plan.predicted:
            self.position_remaining -= np.asarray(plan.expected_delta)
        else:
            self.prediction_step += 1
        if plan.kind == "coast":
            self.coast_travel += float(np.linalg.norm(plan.expected_delta))
        self.inflight = receipt
        self.next_send = (
            max(
                receipt.submitted_mono,
                (receipt.end_max_mono or receipt.submitted_mono)
                - plan.duration_ms / 1000,
            )
            + plan.duration_ms / 1000 / self.profile.max_duty
        )

    def status(self):
        return {
            "state": self.state,
            "reason": self.reason,
            "context": asdict(self.context) if self.context else None,
            "drift_arcsec_s": self.drift.tolist() if self.drift is not None else None,
            "confirmations": self.confirmations,
            "inflight": asdict(self.inflight) if self.inflight else None,
            "recovery_request": self.recovery_request,
            "last_command": self.events[-1] if self.events else None,
        }
