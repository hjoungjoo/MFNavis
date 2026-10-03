"""Mountcontrol-owned lifecycle/dispatch for the smooth tracking engine."""

import time
import logging
from dataclasses import replace

from PiFinder.tracking_commands import control_epoch
from PiFinder.tracking_contracts import TrackingProfile
from PiFinder.tracking_control import TrackingController
from PiFinder.tracking_mount_adapter import IndiTrackingAdapter
from PiFinder.tracking_recovery import RecoveryCoordinator
from PiFinder.tracking_calibration import CalibrationController


class SmoothMountRuntime:
    def __init__(self, mount):
        self.mount = mount
        self.controller = None
        self.adapter = None
        self.session = None
        self.claimed = False
        self.ownership_epoch = None
        self.deferred_legacy = None
        self.drain_until = 0.0
        self.canceled = False
        self.last_epoch = control_epoch(mount.mount_queue)
        self.last_publish = 0.0
        self.recovery = None
        self.last_status = None

    def _suspend_legacy(self):
        m = self.mount
        settle = self.controller.profile.settle_s if self.controller else 0.0
        self.drain_until = max(self.drain_until, m._guide_pulse_until + settle)
        m._guide_correction_enabled = False
        m._guide_predictive_tracking = False
        m._pending_goto_refine = None
        m._pending_guide_rate = None
        m._approach_rate_request = None
        m._slew_rate_reassert_at = None
        m._cancel_sync_goto("smooth tracking engine handover")
        # Ongoing user/native motion is not adopted as tracking recovery.

    def cancel(self, reason):
        recovery_moving = self.recovery and self.recovery.state in {
            "requested",
            "moving",
        }
        self.canceled = True
        if self.recovery:
            status = self.mount._sync_goto_status or {}
            self.recovery.sync_applied |= (
                status.get("request_id") == self.recovery.request_id
                and "verified_monotonic" in status
            )
            self.recovery.cancel()
        if self.controller:
            inflight = self.controller.inflight
            if inflight and inflight.end_max_mono is None:
                self.drain_until = max(
                    self.drain_until,
                    time.monotonic() + self.controller.profile.stop_bound_s,
                )
            if inflight and inflight.end_max_mono:
                self.drain_until = max(
                    self.drain_until,
                    inflight.end_max_mono + self.controller.profile.settle_s,
                )
            self.controller.disable(reason)
        # Shadow never acquired the actuator and must not alter its owner.
        if self.claimed:
            self._suspend_legacy()
        if recovery_moving and self.mount._goto_motion is not None:
            self.mount.stop_mount()

    def tick(self):
        m, now = self.mount, time.monotonic()
        if not hasattr(m.shared_state, "smooth_tracking"):
            return
        epoch = control_epoch(m.mount_queue)
        if epoch != self.last_epoch:
            self.last_epoch = epoch
            if self.claimed:
                self.cancel("control_epoch_changed")
        if self.adapter:
            outcome = self.adapter.poll(now)
            if outcome:
                plan, receipt = outcome
                if (
                    self.canceled
                    or not self.controller
                    or self.controller.pending_plan is not plan
                ):
                    self.drain_until = max(
                        self.drain_until,
                        (
                            receipt.end_max_mono
                            or now + self.adapter.profile.stop_bound_s
                        )
                        + self.adapter.profile.settle_s,
                    )
                else:
                    self.controller.acknowledge(plan, receipt)
        snapshot = m.shared_state.smooth_tracking()
        request, measurement = snapshot["request"], snapshot["measurement"]
        if not request:
            if self.claimed and not self.canceled:
                self.cancel("session_disabled")
            if now >= self.drain_until and not (
                self.adapter and self.adapter.command_future
            ):
                self.claimed = False
                command, self.deferred_legacy = self.deferred_legacy, None
                if command and command.get("_control_epoch") == epoch:
                    m.handle_command(command)
            return
        active = request["mode"] == "active"
        if request["session"] != self.session:
            if self.adapter and self.adapter.command_future:
                return
            if now < self.drain_until:
                return
            if self.adapter:
                self.adapter.close()
            self.session = request["session"]
            self.deferred_legacy = None
            self.canceled = False
            self.claimed = active
            self.ownership_epoch = request["control"] if active else None
            profile = TrackingProfile.from_dict(request["profile"])
            cls = (
                CalibrationController
                if request.get("purpose") == "calibration"
                else TrackingController
            )
            self.controller = cls(profile)
            self.recovery = RecoveryCoordinator(profile, self.controller.budget)
            self.adapter = IndiTrackingAdapter(m, profile) if active else None
            if active:
                self._suspend_legacy()
        if request["control"] != epoch:
            self.cancel("control_epoch_changed")
            m.shared_state.smooth_tracking("stop", "control_epoch_changed")
            return
        if self.canceled or measurement is None:
            return
        if not request.get("target_integration"):
            self.recovery.observe_reference(
                snapshot["reference"], measurement.context.target
            )
        if self.recovery.state in {"requested", "moving", "observing"}:
            state = self.recovery.progress(
                m._sync_goto_status, m._goto_motion is not None, now
            )
            if (
                state in {"requested", "moving", "observing"}
                and not self.recovery_authorized()
            ):
                self.cancel("recovery_permission_revoked")
                m.shared_state.smooth_tracking("fault", "recovery_permission_revoked")
                return
            self.controller.state = (
                "GOTO_RECOVERY" if state in {"requested", "moving"} else "REACQUIRING"
            )
            self.controller.reason = self.recovery.reason
            if state == "limited":
                m._cancel_sync_goto(self.recovery.reason)
                if m._goto_motion is not None:
                    m.stop_mount()
                self.controller.hold(self.recovery.reason)
                self.controller.state = "LIMITED"
            self._publish(now)
            return
        if self.recovery.state == "limited":
            self.controller.state, self.controller.reason = (
                "LIMITED",
                self.recovery.reason,
            )
            self._publish(now)
            return
        if self.recovery.state == "complete":
            self.controller.hold("recovery_complete_reconfirm")
            self.recovery.state = "idle"
        if self.controller.state == "LIMITED":
            self._publish(now)
            return
        if self.controller.context != measurement.context:
            if (
                isinstance(self.controller, CalibrationController)
                and self.controller.context is not None
            ):
                self.controller.hold("calibration_reference_changed")
                self._publish(now)
                return
            if self.controller.inflight:
                end = self.controller.inflight.end_max_mono
                if end is None or now <= end + self.controller.profile.settle_s:
                    self.controller.hold("reference_changed_during_command")
                    return
                self.controller.inflight = None
            if self.adapter and self.adapter.command_future:
                self.controller.hold("reference_changed_during_command")
                return
            # Preserve recovery budget across reference replacement.
            budget = self.controller.budget
            self.controller.arm(measurement.context)
            self.controller.budget = budget
            if active:
                self.controller.ready_after = max(
                    self.controller.ready_after, self.drain_until
                )
        if active:
            self.adapter.refresh(now)
            reason = self.adapter.ready(
                measurement.context,
                now,
                calibration=request.get("purpose") == "calibration",
            )
            if now < self.drain_until:
                reason = "waiting_legacy_command_end"
            if (
                m._goto_motion is not None
                or m._manual_motion_direction is not None
                or m._pending_sync_goto is not None
            ):
                reason = "other_mount_motion"
            if reason:
                self.controller.hold(reason)
                self._publish(now)
                return
        plan = self.controller.tick(snapshot, now, epoch)
        if active and self.controller.recovery_request and snapshot.get("permission"):
            recovery_plan = self.recovery.propose(
                measurement,
                snapshot["permission"],
                now,
                axis_supported=self.adapter.axis_supported,
            )
            if not recovery_plan and self.recovery.reason in {
                "recovery_not_verified",
                "recovery_travel_limit",
                "recovery_budget_exhausted",
            }:
                self.controller.hold(self.recovery.reason)
                self.controller.state = "LIMITED"
                self._publish(now)
                return
            if recovery_plan and recovery_plan["kind"] == "goto":
                self.controller.pending_plan = None
                self.controller.hold("absolute_recovery_requested")
                try:
                    command = self.adapter.recovery_command(
                        recovery_plan, measurement.context, now
                    )
                    if control_epoch(m.mount_queue) != epoch:
                        raise ValueError("recovery cancelled before dispatch")
                    if not m.begin_sync_and_goto(command):
                        raise ValueError("recovery Sync+GoTo rejected")
                    m.shared_state.smooth_tracking(
                        "recovery_permission",
                        replace(
                            snapshot["permission"],
                            purpose="recovery",
                            allow_prediction=False,
                            allow_axis=False,
                            allow_goto=True,
                        ),
                    )
                    self.controller.state = "GOTO_RECOVERY"
                except (ValueError, KeyError, TypeError):
                    self.recovery.cancel()
                self._publish(now)
                return
        if plan is not None:
            if active:
                current = m.shared_state.smooth_tracking()
                if self.controller.validate_dispatch(
                    plan, current, time.monotonic(), control_epoch(m.mount_queue)
                ):
                    self.adapter.submit(plan, now)
                else:
                    self.controller.hold("dispatch_context_changed")
            else:
                # Shadow plans never enter any hardware adapter.
                self.controller.pending_plan = None
                self.controller.reason = "shadow_proposal"
        self._publish(now)

    def recovery_authorized(self):
        snapshot = self.mount.shared_state.smooth_tracking()
        request, permission, measurement = (
            snapshot.get(k) for k in ("request", "permission", "measurement")
        )
        now = time.monotonic()
        recovery_permission = snapshot.get("recovery_permission")
        if self.recovery.state in {"moving", "observing"} and recovery_permission:
            return bool(
                request
                and not snapshot.get("fault")
                and not self.canceled
                and request["session"] == recovery_permission.context.session
                and request["control"] == control_epoch(self.mount.mount_queue)
                and recovery_permission.context.connection
                == self.mount._client_generation
                and now < recovery_permission.expires_mono
            )
        return bool(
            request
            and permission
            and measurement
            and measurement.valid
            and not snapshot.get("fault")
            and not self.canceled
            and request["control"] == control_epoch(self.mount.mount_queue)
            and permission.context == measurement.context
            and permission.allow_goto
            and now < permission.expires_mono
            and measurement.timing.usable(
                now,
                self.controller.profile.max_age_s,
                self.controller.profile.max_timing_uncertainty_s,
            )
        )

    def _publish(self, now):
        if now - self.last_publish < 0.1:
            return
        self.last_publish = now
        state = (self.controller.state, self.controller.reason)
        if state != self.last_status:
            logging.getLogger("SmoothTracking").info(
                "tracking_state session=%s state=%s reason=%s", self.session, *state
            )
            self.last_status = state
        self.mount.shared_state.smooth_tracking("status", self.controller.status())
