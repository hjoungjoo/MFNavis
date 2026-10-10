"""Movement interlock using live INDI limits and OnStep firmware errors."""

import math
import time

from PiFinder.calc_utils import FastAltAz


LIMIT_ERRORS = {
    2: "lower elevation limit",
    3: "hardware limit switch",
    4: "declination limit",
    5: "azimuth limit",
    6: "under-pole limit",
    7: "meridian limit",
    12: "upper elevation limit",
}


class MountMotionLimitsMixin:
    def _limit_numbers(self, name):
        if self.device is None:
            return {}
        try:
            return {
                w.name: float(w.value)
                for w in (self.device.getNumber(name) or [])
                if math.isfinite(float(w.value))
            }
        except (AttributeError, TypeError, ValueError):
            return {}

    def _motion_limit_reason(self, target=None):
        pending = getattr(self, "_pending_motion_limit", "")
        if pending:
            return pending
        raw = self._raw_onstep_status().rstrip("#")
        # GU ends with guide rate, axis rate and a single encoded error char.
        if len(raw) >= 3 and raw[-3:-1].isdigit():
            error = LIMIT_ERRORS.get(ord(raw[-1]) - ord("0"))
            if error:
                return error
        limits = self._limit_numbers("Slew elevation Limit")
        if not limits and not (target is None and "E" in raw):
            return ""
        horizontal = self._limit_numbers("HORIZONTAL_COORD") if target is None else {}
        altitude = horizontal.get("ALT")
        position = target or self._read_cached_current_position(write_status=False)
        transform = None
        if position is not None:
            lat, lon, _, dt = self._shared_location_time_values()
            site = self._limit_numbers("GEOGRAPHIC_COORD")
            if "LAT" in site and "LONG" in site and abs(site["LAT"]) <= 90:
                # Use the controller's actual site, including indoor sessions
                # with no current GPS lock on the handheld.
                lat, lon = site["LAT"], site["LONG"]
            if lat is not None and lon is not None:
                transform = FastAltAz(lat, lon, dt)
                if altitude is None:
                    altitude = transform.radec_to_altaz(*position, alt_only=True)[0]
        if altitude is not None and math.isfinite(altitude):
            if "minAlt" in limits and altitude < limits["minAlt"]:
                return f"altitude {altitude:.2f} < {limits['minAlt']:.2f} deg"
            if "maxAlt" in limits and altitude > limits["maxAlt"]:
                return f"altitude {altitude:.2f} > {limits['maxAlt']:.2f} deg"
        # A GoTo may flip pier side. Evaluate current GEM travel only; the
        # firmware validates the target's selected pier side during its slew.
        if target is None and transform is not None and "E" in raw:
            meridian = self._limit_numbers("Minutes Past Meridian")
            ha = (transform.local_siderial_time - position[0] + 180) % 360 - 180
            if "T" in raw and "East" in meridian and ha < -meridian["East"] / 4:
                return "east meridian limit"
            if "W" in raw and "West" in meridian and ha > meridian["West"] / 4:
                return "west meridian limit"
        return ""

    def _guard_motion(self, target=None, *, defer_stop=False):
        if getattr(self, "_motion_limit", {}).get("latched"):
            return False
        reason = self._motion_limit_reason()
        if not reason and target is not None:
            reason = self._motion_limit_reason(target)
        if not reason:
            return True
        if defer_stop:
            # Pulse worker only publishes the fault. The mount event loop
            # owns stopping hardware and canceling the runtime's own future.
            self._pending_motion_limit = reason
            return False
        self._trip_motion_limit(reason)
        return False

    def _trip_motion_limit(self, reason):
        if getattr(self, "_motion_limit", {}).get("latched"):
            return
        message = f"Mount movement limit exceeded: {reason}"
        self._motion_limit = {"latched": True, "message": message, "time": time.time()}
        invalidate = getattr(self.mount_queue, "invalidate_motion", None)
        if invalidate is not None:
            invalidate()
        self._cancel_sync_goto("mount limit exceeded")
        if hasattr(self.shared_state, "smooth_tracking"):
            self.shared_state.smooth_tracking("stop", "mount_limit_exceeded")
        runtime = getattr(self, "_smooth_runtime", None)
        if runtime is not None:
            runtime.cancel("mount_limit_exceeded")
        stopped = self.stop_mount(stop_tracking=True)
        self._motion_limit_retry_at = time.monotonic() + 1 if not stopped else 0.0
        self._write_controller_status("limit_exceeded", message)

    def _check_motion_limits(self):
        if self.connected and self.device is not None:
            if getattr(self, "_motion_limit", {}).get("latched"):
                now = time.monotonic()
                retry = getattr(self, "_motion_limit_retry_at", 0.0)
                if now >= retry and (retry or self._cached_tracking_enabled() is True):
                    stopped = self.stop_mount(stop_tracking=True)
                    self._motion_limit_retry_at = (
                        time.monotonic() + 1 if not stopped else 0.0
                    )
                return
            self._guard_motion()

    def _acknowledge_motion_limit(self):
        """An explicit tracking-on request can release a cleared interlock."""
        # Driver rejection text is an event, unlike current firmware status.
        self._pending_motion_limit = ""
        if self._motion_limit_reason():
            return False
        self._motion_limit = {}
        return True
