"""INDI execution boundary owned exclusively by MountControlIndi."""

from concurrent.futures import ThreadPoolExecutor
import math
import subprocess
import time

import numpy as np

from PiFinder.tracking_commands import control_epoch
from PiFinder.tracking_contracts import COAST_REASONS, CorrectionReceipt
from PiFinder.visual_tracking import sky_vector

PULSE = {
    "north": ("TELESCOPE_TIMED_GUIDE_NS", "TIMED_GUIDE_N", "TIMED_GUIDE_S"),
    "south": ("TELESCOPE_TIMED_GUIDE_NS", "TIMED_GUIDE_S", "TIMED_GUIDE_N"),
    "east": ("TELESCOPE_TIMED_GUIDE_WE", "TIMED_GUIDE_E", "TIMED_GUIDE_W"),
    "west": ("TELESCOPE_TIMED_GUIDE_WE", "TIMED_GUIDE_W", "TIMED_GUIDE_E"),
}


def query_properties(host, port, device):
    names = (
        "TELESCOPE_TRACK_STATE.*",
        "TELESCOPE_PARK.*",
        "TELESCOPE_MOTION_NS.*",
        "TELESCOPE_MOTION_WE.*",
        "TELESCOPE_PIER_SIDE.*",
        "GUIDE_RATE.*",
        "DRIVER_INFO.*",
        "EQUATORIAL_EOD_COORD._STATE",
        "TELESCOPE_TIMED_GUIDE_NS._PERM",
        "TELESCOPE_TIMED_GUIDE_WE._PERM",
    )
    result = subprocess.run(
        [
            "indi_getprop",
            "-h",
            host,
            "-p",
            str(port),
            "-t",
            "1",
            *(f"{device}.{name}" for name in names),
        ],
        capture_output=True,
        text=True,
        timeout=1.5,
        check=False,
    )
    values = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.startswith(device + "."):
            values[key[len(device) + 1 :]] = value.strip()
    if not values:
        raise ValueError("no fresh INDI properties")
    return {"values": values, "received_mono": time.monotonic()}


class IndiTrackingAdapter:
    def __init__(self, mount, profile):
        self.mount, self.profile = mount, profile
        self.io = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="tracking-command"
        )
        self.read_io = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="tracking-read"
        )
        self.read_future = None
        self.readback = None
        self.command_future = None
        self.command_plan = None
        self.submitted = 0.0
        self.next_read = 0.0
        self.timeout_reported = False

    def refresh(self, now):
        if self.read_future and self.read_future.done():
            try:
                self.readback = self.read_future.result()
            except Exception:
                self.readback = None
            self.read_future = None
        if self.read_future is None and now >= self.next_read:
            self.next_read = now + 1.0
            self.read_future = self.read_io.submit(
                query_properties,
                self.mount.indi_host,
                self.mount.indi_port,
                self.profile.device,
            )

    def ready(self, context, now, *, calibration=False):
        m, p = self.mount, self.profile
        if (
            not (p.verified or (calibration and p.equipment_verified))
            or not m.connected
            or m.client is None
            or m.device is None
        ):
            return "mount_unverified_or_disconnected"
        if m._client_generation != context.connection:
            return "connection_epoch_changed"
        if m._indi_device_name() != p.device or context.geometry != p.geometry:
            return "equipment_or_geometry_changed"
        if not self.readback or not 0 <= now - self.readback["received_mono"] <= 2.5:
            return "mount_state_stale"
        values = self.readback["values"]
        if values.get("TELESCOPE_TRACK_STATE.TRACK_ON") != "On":
            return "tracking_not_on"
        if values.get("TELESCOPE_PARK.UNPARK") != "On":
            return "park_state_unknown_or_parked"
        if values.get("EQUATORIAL_EOD_COORD._STATE") not in {"Idle", "Ok"}:
            return "mount_busy_or_unknown"
        for prop, keys in (
            ("TELESCOPE_MOTION_NS", ("MOTION_NORTH", "MOTION_SOUTH")),
            ("TELESCOPE_MOTION_WE", ("MOTION_WEST", "MOTION_EAST")),
        ):
            if any(values.get(f"{prop}.{key}") != "Off" for key in keys):
                return "external_motion_or_unknown"
        driver = (
            values.get("DRIVER_INFO.DRIVER_EXEC", "")
            + ":"
            + values.get("DRIVER_INFO.DRIVER_VERSION", "")
        )
        if driver != p.driver:
            return "driver_version_changed"
        try:
            rates = tuple(
                float(values[f"GUIDE_RATE.{key}"])
                for key in ("GUIDE_RATE_WE", "GUIDE_RATE_NS")
            )
        except (KeyError, ValueError):
            return "guide_rate_unknown"
        if not np.allclose(rates, p.guide_rate, atol=1e-6, rtol=0):
            return "guide_rate_changed"
        if (
            p.mount_type == "EQ"
            and values.get(f"TELESCOPE_PIER_SIDE.{p.pier_side}") != "On"
        ):
            return "pier_side_changed"
        distance = math.degrees(
            math.acos(
                float(
                    np.clip(
                        np.dot(
                            sky_vector(*context.target), sky_vector(*p.model_target)
                        ),
                        -1,
                        1,
                    )
                )
            )
        )
        if not calibration and distance > p.model_radius_deg:
            return "response_outside_calibrated_sky_region"
        for prop in ("TELESCOPE_TIMED_GUIDE_NS", "TELESCOPE_TIMED_GUIDE_WE"):
            if values.get(f"{prop}._PERM") not in {"rw", "wo"}:
                return "pulse_property_not_writable"
        return ""

    def _send(self, plan):
        m = self.mount
        if self.ready(
            plan.context, time.monotonic(), calibration=plan.kind == "calibration"
        ):
            return False
        snapshot = m.shared_state.smooth_tracking()
        permission = snapshot.get("permission")
        measurement = snapshot.get("measurement")
        if (
            snapshot.get("fault")
            or not snapshot.get("request")
            or permission is None
            or permission.context != plan.context
            or permission.expires_mono <= time.monotonic()
            or snapshot["quality_revision"] != plan.quality_revision
            or measurement is None
            or (
                not measurement.valid
                and not (
                    plan.kind == "coast"
                    and permission.purpose == "coast"
                    and self.profile.coast_verified
                    and measurement.reason in COAST_REASONS
                )
            )
            or measurement.key != plan.measurement_key
            or not measurement.timing.usable(
                time.monotonic(),
                self.profile.max_age_s,
                self.profile.max_timing_uncertainty_s,
            )
        ):
            return False
        if plan.kind != "calibration":
            model_pointing = plan.model_pointing or measurement.aligned_radec
            if model_pointing is None:
                return False
            separation = math.degrees(
                math.acos(
                    float(
                        np.clip(
                            np.dot(
                                sky_vector(*model_pointing),
                                sky_vector(*self.profile.model_target),
                            ),
                            -1,
                            1,
                        )
                    )
                )
            )
            margin = (
                self.profile.coast_error_bound_arcsec
                if plan.kind == "coast"
                else measurement.bound_arcsec
            ) / 3600
            if separation + margin > self.profile.model_radius_deg:
                return False
        prop, direction, opposite = PULSE[plan.direction]
        vector = m.device.getNumber(prop)
        if not vector:
            return False
        names = {w.name: w for w in vector}
        if direction not in names or opposite not in names:
            return False
        for name, value in ((direction, plan.duration_ms), (opposite, 0)):
            widget = names[name]
            if not widget.min <= value <= widget.max:
                return False
        # Recheck just before dispatch registration, after all cache lookups.
        if (
            time.monotonic() >= plan.expires_mono
            or control_epoch(m.mount_queue) != plan.context.control
        ):
            return False
        register = getattr(m.mount_queue, "register_dispatch", None)
        if register is None or not register(plan.context.control):
            return False
        names[direction].value = float(plan.duration_ms)
        names[opposite].value = 0.0
        m.client.sendNewNumber(vector)
        return True

    def submit(self, plan, now):
        if self.command_future is not None:
            raise RuntimeError("one in-flight tracking command only")
        self.command_plan, self.submitted = plan, now
        self.timeout_reported = False
        self.command_future = self.io.submit(self._send, plan)

    def poll(self, now):
        if self.command_future is None:
            return None
        if not self.command_future.done():
            if (
                not self.timeout_reported
                and now - self.submitted > self.profile.stop_bound_s
            ):
                self.timeout_reported = True
                return self.command_plan, CorrectionReceipt(
                    self.command_plan.command_id,
                    "unknown",
                    self.submitted,
                    reason="dispatch_timeout",
                )
            return None
        plan = self.command_plan
        try:
            accepted = self.command_future.result()
            state, reason = (
                ("accepted", "") if accepted else ("rejected", "dispatch_gate")
            )
            if self.timeout_reported:
                state, reason = "unknown", "late_dispatch_outcome"
        except Exception as exc:
            state, reason = "unknown", type(exc).__name__
        self.command_future = self.command_plan = None
        return plan, CorrectionReceipt(
            plan.command_id,
            state,
            self.submitted,
            now + self.profile.start_delay_bound_s + plan.duration_ms / 1000
            if state == "accepted"
            else None,
            reason,
        )

    def close(self):
        self.io.shutdown(wait=False, cancel_futures=True)
        self.read_io.shutdown(wait=False, cancel_futures=True)

    @property
    def axis_supported(self):
        # Standard TELESCOPE_MOTION_* is continuous, with no device-side lease.
        # Do not expose it as bounded automatic recovery on process/power loss.
        return False

    def recovery_command(self, request, context, now):
        from PiFinder.calc_utils import catalog_to_equinox_of_date, sf_utils

        if self.ready(context, now):
            raise ValueError("fresh mount state required for recovery")
        policy = self.profile.goto
        if (
            not policy.get("verified")
            or policy.get("coordinate_frame") != "of_date"
            or not policy.get("path_limits_verified")
            or self.profile.mount_type != "Alt/Az"
        ):
            raise ValueError("verified Alt/Az recovery path required")
        shared = self.mount.shared_state
        location, dt = shared.location(), shared.datetime()
        if not location or not location.lock or dt is None or dt.tzinfo is None:
            raise ValueError("trusted observer location/time required")
        sf_utils.set_location(location.lat, location.lon, location.altitude or 0)
        lo, hi = float(policy["min_alt_deg"]), float(policy["max_alt_deg"])
        if not -5 <= lo < hi <= 85:
            raise ValueError("invalid recovery altitude bounds")
        # Small recovery paths only; mount's validated physical limits remain
        # responsible for the actual axis trajectory, not this sky interpolation.
        a, b = (
            sky_vector(*request[key]) for key in ("current_catalog", "target_catalog")
        )
        from PiFinder.visual_tracking import vector_radec

        for fraction in np.linspace(0, 1, 17):
            ra, dec = vector_radec(a * (1 - fraction) + b * fraction)
            alt, _ = sf_utils.radec_to_altaz(ra, dec, dt, atmos=False)
            if not lo <= alt <= hi:
                raise ValueError("recovery crosses altitude limit")
        current = catalog_to_equinox_of_date(*request["current_catalog"], dt)
        target = catalog_to_equinox_of_date(*request["target_catalog"], dt)
        return {
            "type": "sync_and_goto",
            "origin": "smooth_tracking_recovery",
            "request_id": request["request_id"],
            "sync_ra": current[0],
            "sync_dec": current[1],
            "ra": target[0],
            "dec": target[1],
        }


class PulseCalibration:
    """Fit direction-specific response from confirmed clean probe observations.

    Probe execution uses the same executor/Stop limits. This collector cannot
    command hardware, increase pulse bounds, or bless timing/equipment identity.
    """

    def __init__(self, profile):
        self.profile = profile
        self.samples = {direction: [] for direction in PULSE}

    def add(self, direction, duration_ms, before, after, drift, end_max):
        if (
            direction not in self.samples
            or not before.valid
            or not after.valid
            or before.context != after.context
            or before.key == after.key
            or not self.profile.min_pulse_ms <= duration_ms <= self.profile.max_pulse_ms
            or after.timing.start_min <= end_max + self.profile.settle_s
        ):
            raise ValueError("invalid calibration observation")
        dt = after.timing.midpoint - before.timing.midpoint
        if dt <= 0:
            raise ValueError("reversed calibration time")
        response = np.asarray(before.error) - after.error + np.asarray(drift) * dt
        if np.linalg.norm(response) <= 3 * (before.bound_arcsec + after.bound_arcsec):
            raise ValueError("calibration signal below uncertainty")
        if 3 * (
            before.bound_arcsec + after.bound_arcsec
        ) > self.profile.response_fractional_bound * np.linalg.norm(response):
            raise ValueError("calibration uncertainty exceeds response budget")
        self.samples[direction].append(response / duration_ms)
        self.samples[direction] = self.samples[direction][-8:]

    def response(self):
        columns = []
        for direction in PULSE:
            samples = self.samples[direction]
            if len(samples) < 3:
                raise ValueError("three independent probes per direction required")
            values = np.asarray(samples)
            center = np.median(values, axis=0)
            if np.max(
                np.linalg.norm(values - center, axis=1)
            ) > self.profile.response_fractional_bound * np.linalg.norm(center):
                raise ValueError("unstable actuator response")
            columns.append(center)
        return np.asarray(columns).T
