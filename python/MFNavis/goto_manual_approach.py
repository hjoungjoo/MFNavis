"""Bounded manual-axis approach before the optical pulse-guide finish."""

import math
import time

from PiFinder import calc_utils
from PiFinder.tracking_commands import control_epoch


MANUAL_APPROACH_PULSE_MULTIPLE = 1.5
MANUAL_APPROACH_MAX_ARCMIN = 60.0
MANUAL_APPROACH_MAX_SECONDS = 1.2
MANUAL_APPROACH_SETTLE_SECONDS = 0.5
MANUAL_APPROACH_RATE_SECONDS = 0.6
MANUAL_APPROACH_FRACTION = 0.6
MANUAL_APPROACH_RATES = ((7, 48.0), (6, 20.0), (5, 8.0), (4, 4.0))


def manual_approach_pulse_entry(accuracy_arcmin):
    return min(15.0, max(0.75, accuracy_arcmin * MANUAL_APPROACH_PULSE_MULTIPLE))


def manual_approach_motion(residual_arcsec):
    travel = abs(residual_arcsec) * MANUAL_APPROACH_FRACTION
    for rate, multiplier in MANUAL_APPROACH_RATES:
        duration = travel / (multiplier * 15.041)
        if duration >= MANUAL_APPROACH_RATE_SECONDS or rate == 4:
            return rate, multiplier, min(MANUAL_APPROACH_MAX_SECONDS, duration)


class ManualGotoApproachMixin:
    def _manual_approach_errors(self, ra, dec, target_ra, target_dec):
        if self.shared_state is None:
            return None
        errors = calc_utils.pointing_axis_errors(
            ra,
            dec,
            target_ra,
            target_dec,
            self._guide_mount_type,
            self.shared_state.location(),
            self.shared_state.datetime(),
        )
        if errors is None or not all(math.isfinite(value) for value in errors):
            return None
        longitude, latitude = errors
        if self._guide_mount_type != "Alt/Az":
            longitude = -longitude
        return longitude * 3600, latitude * 3600

    def _restore_manual_approach_speed(self):
        pending = self._manual_approach
        if pending is None:
            return True
        pending["stage"] = "restoring"
        self._guide_observation_after_wall = max(
            self._guide_observation_after_wall,
            time.time() + MANUAL_APPROACH_SETTLE_SECONDS,
        )
        if not self._reassert_slew_rate():
            self._write_controller_status(
                "slew_rate_failed", "Could not restore manual speed after GoTo approach"
            )
            return False
        self._manual_approach = None
        self._write_controller_status(
            "guide_correction", "Manual approach stopped; speed restored"
        )
        return True

    def _cancel_manual_approach(self):
        if self._manual_approach is None:
            return True
        if self._manual_motion_origin == "goto_approach":
            return self.stop_mount(preserve_tracking=True)
        return self._restore_manual_approach_speed()

    def _check_manual_approach(self):
        pending = self._manual_approach
        if pending is None:
            return False
        if (
            not self._guide_correction_enabled
            or control_epoch(self.mount_queue) != pending["epoch"]
        ):
            self._guide_manual_approach = False
            self._guide_correction_enabled = False
            self._cancel_manual_approach()
            return True
        if pending["stage"] == "restoring":
            self._restore_manual_approach_speed()
            return True
        if pending["stage"] == "moving":
            if self._manual_motion_direction is None:
                self._restore_manual_approach_speed()
            elif time.monotonic() >= self._manual_motion_deadline:
                self.stop_mount(preserve_tracking=True)
            return True
        if pending["stage"] == "ready":
            return False
        receipt = self._motion_property_receipt("TELESCOPE_SLEW_RATE")
        if receipt is not None and receipt["sequence"] > pending["sequence"]:
            if receipt["state"] in {"idle", "ok"} and receipt["values"].get(
                str(pending["rate"])
            ):
                pending["stage"] = "ready"
                return False
            if receipt["state"] == "alert":
                pending["deadline"] = 0.0
        if time.monotonic() >= pending["deadline"]:
            self._guide_correction_enabled = False
            self._guide_correction_mode = "failed"
            self._cancel_manual_approach()
            self._write_controller_status(
                "guide_correction_failed", "Manual approach speed not confirmed"
            )
        return True

    def _apply_manual_approach(
        self, current_ra, current_dec, target_ra, target_dec, error, solve_time
    ):
        if not self._guide_manual_approach:
            return False
        if self._indi_mount_is_busy() is not False:
            return True
        entry = manual_approach_pulse_entry(self._guide_correction_accuracy_arcmin)
        if error <= entry:
            restoring_speed = self._manual_approach is not None
            if not self._cancel_manual_approach():
                return True
            self._guide_manual_approach = False
            self._guide_pulse_best_error = None
            self._guide_pulse_previous_error = None
            self._guide_pulse_no_progress = 0
            self._guide_pulse_worsening = 0
            self._guide_progress_solve_time = 0.0
            return restoring_speed
        self._guide_correction_mode = "manual_approach"
        errors = self._manual_approach_errors(
            current_ra, current_dec, target_ra, target_dec
        )
        if errors is None:
            self._cancel_manual_approach()
            return True
        if error > MANUAL_APPROACH_MAX_ARCMIN:
            self._cancel_manual_approach()
            self._guide_correction_mode = "reacquire"
            self._guide_correction_enabled = False
            return True
        if not self._guard_motion((target_ra, target_dec)):
            return True
        if not self._finish_active_guide_pulses():
            return True
        progress = self._manual_approach_progress
        if (
            progress is not None
            and progress["awaiting_result"]
            and solve_time > progress["timestamp"]
        ):
            if error >= progress["error"] - 0.1:
                progress["failures"] += 1
            else:
                progress["failures"] = 0
            progress.update(error=error, timestamp=solve_time, awaiting_result=False)
            if progress["failures"] >= 4:
                self._guide_correction_enabled = False
                self._guide_correction_mode = "failed"
                self._cancel_manual_approach()
                self._write_controller_status(
                    "guide_correction_failed", "Manual approach is not converging"
                )
                return True
        longitude, latitude = errors
        if abs(longitude) > abs(latitude):
            residual = longitude
            direction = "east" if residual > 0 else "west"
        else:
            residual = latitude
            direction = "north" if residual > 0 else "south"
        rate, multiplier, duration = manual_approach_motion(residual)
        if duration < 0.3:
            return True
        pending = self._manual_approach
        if pending is None or pending["rate"] != rate:
            if pending is not None and not self._cancel_manual_approach():
                return True
            if self.client is None or self.device is None:
                return True
            with self._sync_property_lock:
                sequence = self._sync_property_sequence
            self._manual_approach = {
                "stage": "waiting_rate",
                "rate": rate,
                "sequence": sequence,
                "deadline": time.monotonic() + 3.0,
                "epoch": control_epoch(self.mount_queue),
            }
            self._slew_rate_polluted = True
            self._selector_invalidated_after_sequence = sequence
            self._guide_rate_needs_reassert = True
            self._pending_guide_rate = None
            self._confirmed_guide_rates = None
            if not self.client.set_switch(
                self.device, "TELESCOPE_SLEW_RATE", str(rate)
            ):
                self._manual_approach["deadline"] = 0.0
            return True
        if pending["stage"] != "ready":
            return True
        from PiFinder.mountcontrol_indi import MANUAL_MOTION_PROPERTIES

        self._guide_correction_last_solve_time = solve_time
        if self._manual_approach_progress is None:
            self._manual_approach_progress = {
                "error": error,
                "timestamp": solve_time,
                "failures": 0,
                "awaiting_result": True,
            }
        else:
            self._manual_approach_progress.update(
                error=error, timestamp=solve_time, awaiting_result=True
            )
        if not self._apply_indi_properties(
            [
                self._indi_property_on(name)
                for name in MANUAL_MOTION_PROPERTIES[direction]
            ],
            "guide_correction",
            "Manual GoTo approach",
            "guide_correction_failed",
        ):
            self.stop_mount(preserve_tracking=True)
            self._guide_correction_enabled = False
            self._guide_correction_mode = "failed"
            return True
        self._arm_manual_motion_deadline(direction, duration, origin="goto_approach")
        pending["stage"] = "moving"
        self._guide_observation_after_wall = (
            time.time() + duration + MANUAL_APPROACH_SETTLE_SECONDS
        )
        self._write_controller_status(
            "guide_correction",
            f"Manual GoTo approach: {direction}, {multiplier:g}x, {duration:.2f}s",
        )
        return True
