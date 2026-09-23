#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Small INDI mount-control bridge for PiFinder.

The feature is intentionally optional: PyIndi is imported defensively and this
module is only started when ``mount_control`` is enabled in the PiFinder config.
"""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from multiprocessing import Queue
from typing import Any, Optional

from PiFinder import calc_utils, config
from PiFinder import gps_time_sync
from PiFinder import nonsidereal
from PiFinder import sys_utils, utils
from PiFinder.operation_errors import ErrorNotifier, mount_failure
from PiFinder.indi_align import (
    BRIGHT_ALIGN_STARS,
    alignment_altitude_limits,
    clamp_align_points,
    get_align_star,
    nearest_align_star,
    next_align_star,
)
from PiFinder.indi_backlash_calibration import (
    BACKLASH_AUTO_MODE_COMPASS_GOTO,
    BacklashCalibrationMixin,
)
from PiFinder.indi_multipoint_align import (
    ALIGN_MODE_AUTO,
    ALIGN_MODE_MANUAL,
    ALIGN_MODES,
    MultiPointAlignController,
    STATE_ADJUST,
    STATE_CANCELLED,
    STATE_FAILED,
    STATE_IDLE,
    STATE_MOVING,
    STATE_PREPARING,
    STATE_WAITING,
)
from PiFinder.multiproclogging import MultiprocLogging

try:
    import PyIndi  # type: ignore
except ImportError:  # pragma: no cover - exercised only on INDI installs
    PyIndi = None


logger = logging.getLogger("MountControl.Indi")
clientlogger = logging.getLogger("MountControl.Indi.Client")

STATUS_FILE = utils.runtime_dir / "mount_control_status.json"
STOP_REQUEST_FILE = utils.runtime_dir / "mount_control_stop_request.json"
POSITION_STATUS_MIN_INTERVAL = 0.5
# Idle keepalive cadence for the tmpfs mount_control_status.json. State changes
# and in-motion position updates are written promptly (POSITION_STATUS_MIN_INTERVAL),
# so this only bounds idle-status freshness (park/connection/"updated"). Lowered
# 5.0 -> 2.0 for fresher idle UI; tmpfs, so no SD wear and no effect on GoTo
# completion detection.
STATUS_HEARTBEAT_INTERVAL = 2.0

# Re-assert a non-sidereal tracking frequency at this interval. The write is
# idempotent and cheap; it exists because a driver reconnect re-selects
# TRACK_SIDEREAL (:TQ#), which silently resets the frequency to sidereal.
TRACK_FREQ_REASSERT_INTERVAL = 60.0
AUTO_CONNECT_START_DELAY = 5.0
AUTO_CONNECT_RETRY_INTERVAL = 10.0
AUTO_CONNECT_DEVICE_WAIT_SECONDS = 20.0
AUTO_CONNECT_PROPERTY_WAIT_SECONDS = 20.0
AUTO_CONNECT_DEVICE_CONNECT_WAIT_SECONDS = 15.0
AUTO_CONNECT_POSITION_WAIT_SECONDS = 10.0
USB_SERIAL_MONITOR_INTERVAL_SECONDS = 1.0
USB_SERIAL_RETURN_DEBOUNCE_SECONDS = 2.0
USB_SERIAL_DISCONNECT_WAIT_SECONDS = 3.0
# OnStep Status is published at about a 13-second cadence on the field unit.
# A newly attached PyIndi client can miss the first vector while its properties
# are still being defined, so allow the next complete position/status cycle.
USB_SERIAL_FRESH_TELEMETRY_WAIT_SECONDS = 20.0
MANUAL_MOTION_LEASE_SECONDS = 1.2
MANUAL_MOTION_MIN_LEASE_SECONDS = 0.3
MANUAL_MOTION_MAX_LEASE_SECONDS = 5.0
MANUAL_MOTION_MAX_CONTINUOUS_SECONDS = 10.0
MANUAL_MOTION_POLL_SECONDS = 0.1
MANUAL_MOTION_STOP_RETRY_SECONDS = 0.5
GOTO_REFINE_DELAY_SECONDS = 8.0
GOTO_REFINE_SOLVE_TIMEOUT_SECONDS = 45.0
# Solve-based fine-correction target accuracy (arcmin). The 3' default matches
# the tracking-guide hold band and the field-tested eyepiece centering needed
# below the older 6' threshold. Used when a caller does not pass an accuracy.
DEFAULT_GOTO_REFINE_ACCURACY_ARCMIN = 3.0
# Cadence of the closed-loop pulse-guide correction. The loop also gates on a
# FRESH plate solve (it never pulses twice off the same solve), and the 3 s
# floor is longer than the 2.5 s maximum timed pulse. This lets every fresh
# post-pulse solve drive the next correction without overlapping a pulse.
GUIDE_CORRECTION_INTERVAL_SECONDS = 3.0
GUIDE_CORRECTION_MAX_SOLVE_AGE_SECONDS = 12.0
SYNC_GOTO_STAGE_TIMEOUT_SECONDS = 5.0
SYNC_GOTO_COORD_TOLERANCE_ARCMIN = 0.5
# Manual-move fallback lease used only when the driver does not expose the INDI
# timed guide-pulse interface.
GUIDE_CORRECTION_PULSE_SECONDS = 0.4
# OnStep manual approach uses physical Alt/Az axes above the pulse band.
# Keep each move short, then remeasure from a post-stop camera exposure.
GOTO_APPROACH_PULSE_BAND_ARCMIN = 2.0
GOTO_APPROACH_MAX_SECONDS = 1.0
GOTO_APPROACH_SETTLE_SECONDS = 0.5
GOTO_APPROACH_GAIN = 0.5
# Real INDI timed guide pulse (TELESCOPE_TIMED_GUIDE_*): the pulse duration is
# computed from the axis error and the mount's guide rate, so the mount moves
# exactly the time proportional to the correction angle.
SIDEREAL_ARCSEC_PER_SEC = 15.041
# Fraction of sidereal used when the driver does not report GUIDE_RATE.
DEFAULT_GUIDE_RATE_X = 0.5
# Recovery-speed guide-rate switching. While the remaining guide-correction
# error is above accuracy * GUIDE_RATE_FAST_MIN_ERROR_MULTIPLE, the guide rate
# is raised to the fast value so recovery pulses cover ground quickly (needs a
# driver that accepts GUIDE_RATE writes up to 1.0, e.g. the modified OnStepX).
# It drops back to the fine value for the final corrections and is restored
# whenever guide correction converges or is disabled, so precision guiding
# always finishes at the conservative rate.
GUIDE_RATE_FAST_X = 1.0
GUIDE_RATE_FINE_X = 0.5
GUIDE_RATE_FAST_MIN_ERROR_MULTIPLE = 2.0
# Close this fraction of the error per pulse; the periodic loop converges the
# rest. Kept conservative because an OnStepX bench test measured the actual
# pulse motion at ~1.6x the nominal GUIDE_RATE (0.5x sidereal), so a higher
# value would overshoot.
GUIDE_PULSE_AGGRESSIVENESS = 0.5
GUIDE_PULSE_MIN_MS = 20
GUIDE_PULSE_MAX_MS = 2500
# INDI timed-guide (property, element) per computed direction. If a mount guides
# the wrong way in RA, swap the "east"/"west" elements here (hardware-validate
# once, like the manual-motion mapping's E/W handling).
GUIDE_PULSE_ELEMENTS: dict[str, tuple[str, str]] = {
    "north": ("TELESCOPE_TIMED_GUIDE_NS", "TIMED_GUIDE_N"),
    "south": ("TELESCOPE_TIMED_GUIDE_NS", "TIMED_GUIDE_S"),
    "east": ("TELESCOPE_TIMED_GUIDE_WE", "TIMED_GUIDE_E"),
    "west": ("TELESCOPE_TIMED_GUIDE_WE", "TIMED_GUIDE_W"),
}
GOTO_COMPLETE_MIN_SECONDS = 1.0
# A GoTo is declared complete once all completion conditions (INDI not busy,
# OnStep ':GU#' reports no goto, within GOTO_COMPLETE_TARGET_TOLERANCE_DEG of
# target, and position stable within GOTO_COMPLETE_POSITION_STABLE_DEG) hold
# continuously for this long; any failing condition resets the timer. This is
# the primary settle guarantee before the motion flags drop.
# Tuned 4.0 -> 2.5 from the OnStepX field test (2026-07-18): the completion
# conditions became stable within ~1.2 s of the physical stop across 6 slews,
# so 2.5 s keeps ~1 s margin over that (and over the near-arrival OnStep status
# jitter) while trimming ~1.5 s of dead time per GoTo/corrective/recovery slew.
GOTO_COMPLETE_STABLE_SECONDS = 2.5
GOTO_COMPLETE_POSITION_STABLE_DEG = 0.02
GOTO_COMPLETE_TARGET_TOLERANCE_DEG = 0.5
GOTO_ONSTEP_ACTIVE_OBSERVE_GRACE_SECONDS = 3.0
GOTO_COMPLETE_FALLBACK_SECONDS = 180.0
GOTO_TARGET_COMMAND_ATTEMPTS = 2
GOTO_TARGET_ACCEPT_TIMEOUT_SECONDS = 2.0
GOTO_TARGET_ACCEPT_POLL_SECONDS = 0.1
GOTO_TARGET_ACCEPT_TOLERANCE_ARCMIN = 3.0
MULTIPOINT_ALIGN_SYNC_THRESHOLD_ARCMIN = 30.0
MULTIPOINT_ALIGN_SYNC_VERIFY_TIMEOUT_SECONDS = 5.0
MULTIPOINT_ALIGN_SYNC_VERIFY_TOLERANCE_ARCMIN = 5.0


def radec_separation_arcmin(
    ra_a_deg: float, dec_a_deg: float, ra_b_deg: float, dec_b_deg: float
) -> float:
    ra_a = math.radians(ra_a_deg)
    dec_a = math.radians(dec_a_deg)
    ra_b = math.radians(ra_b_deg)
    dec_b = math.radians(dec_b_deg)
    cos_sep = math.sin(dec_a) * math.sin(dec_b) + math.cos(dec_a) * math.cos(
        dec_b
    ) * math.cos(ra_a - ra_b)
    sep_rad = math.acos(max(-1.0, min(1.0, cos_sep)))
    return math.degrees(sep_rad) * 60.0


def shortest_ra_delta_deg(target_ra_deg: float, current_ra_deg: float) -> float:
    return (target_ra_deg - current_ra_deg + 180.0) % 360.0 - 180.0


def _write_status(state: str, message: str = "", **extra: Any) -> None:
    """Persist a compact mount-control status snapshot for logs/web/debug."""
    try:
        utils.create_path(utils.runtime_dir)
        payload = {
            "state": state,
            "message": message,
            "updated": time.time(),
        }
        payload.update(extra)
        tmp_status = STATUS_FILE.with_name(
            f"{STATUS_FILE.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
        )
        with open(tmp_status, "w", encoding="utf-8") as status_out:
            json.dump(payload, status_out, indent=2, sort_keys=True)
            status_out.flush()
        tmp_status.replace(STATUS_FILE)
    except Exception:
        logger.exception("Could not write mount-control status")


if PyIndi is not None:

    class PiFinderIndiClient(PyIndi.BaseClient):
        """Minimal INDI client that finds a telescope-like device."""

        # Emit at most one disconnect WARNING per this many seconds. A dead
        # INDI server makes the client library fire serverDisconnected on a
        # tight reconnect loop; logging every event streams WARNINGs into
        # pifinder.log (SD-card writes) for as long as the mount is down.
        _DISCONNECT_LOG_INTERVAL_S = 60.0

        def __init__(self, mount_control=None, generation: int = 0):
            super().__init__()
            self.telescope_device = None
            self.mount_control = mount_control
            self.generation = generation
            self.preferred_device_name = sys_utils.get_indi_profile_device_name()
            # Monotonic timestamp of the last disconnect WARNING we emitted,
            # so repeats within _DISCONNECT_LOG_INTERVAL_S drop to DEBUG.
            self._last_disconnect_log_monotonic: Optional[float] = None

        def get_telescope_device(self):
            return self.telescope_device

        def _wait_for_property(self, device, property_name: str, timeout: float = 5.0):
            start_time = time.time()
            while time.time() - start_time < timeout:
                prop = device.getProperty(property_name)
                if prop:
                    return prop
                time.sleep(0.1)
            clientlogger.warning(
                "Timeout waiting for property %s on %s",
                property_name,
                device.getDeviceName(),
            )
            return None

        def set_switch(
            self, device, property_name: str, element_name: str, timeout: float = 5.0
        ) -> bool:
            if not self._wait_for_property(device, property_name, timeout):
                return False

            switch_prop = device.getSwitch(property_name)
            if not switch_prop:
                clientlogger.error("Could not get switch property %s", property_name)
                return False

            found = False
            for i in range(len(switch_prop)):
                switch = switch_prop[i]
                if switch.name == element_name:
                    switch.s = PyIndi.ISS_ON
                    found = True
                else:
                    switch.s = PyIndi.ISS_OFF

            if not found:
                clientlogger.error(
                    "Switch element %s.%s not found", property_name, element_name
                )
                return False

            self.sendNewSwitch(switch_prop)
            return True

        def set_number(
            self, device, property_name: str, values: dict[str, float], timeout=5.0
        ) -> bool:
            if not self._wait_for_property(device, property_name, timeout):
                return False

            number_prop = device.getNumber(property_name)
            if not number_prop:
                clientlogger.error("Could not get number property %s", property_name)
                return False

            found = False
            for i in range(len(number_prop)):
                number = number_prop[i]
                if number.name in values:
                    number.value = values[number.name]
                    found = True

            if not found:
                clientlogger.error("No matching elements in %s", property_name)
                return False

            self.sendNewNumber(number_prop)
            return True

        def set_text(
            self, device, property_name: str, values: dict[str, str], timeout=5.0
        ) -> bool:
            if not self._wait_for_property(device, property_name, timeout):
                return False

            text_prop = device.getText(property_name)
            if not text_prop:
                clientlogger.error("Could not get text property %s", property_name)
                return False

            found = False
            for i in range(len(text_prop)):
                text = text_prop[i]
                if text.name in values:
                    text.text = values[text.name]
                    found = True

            if not found:
                clientlogger.error("No matching elements in %s", property_name)
                return False

            self.sendNewText(text_prop)
            return True

        def unpark_mount(self, device) -> bool:
            if not self._wait_for_property(device, "TELESCOPE_PARK", timeout=2.0):
                return True

            park_switch = device.getSwitch("TELESCOPE_PARK")
            if not park_switch:
                return True

            is_parked = False
            for i in range(len(park_switch)):
                if park_switch[i].name == "PARK" and park_switch[i].s == PyIndi.ISS_ON:
                    is_parked = True
                    break

            return not is_parked or self.set_switch(device, "TELESCOPE_PARK", "UNPARK")

        def enable_tracking(self, device) -> bool:
            if self._wait_for_property(device, "TELESCOPE_TRACK_MODE", timeout=2.0):
                self.set_switch(device, "TELESCOPE_TRACK_MODE", "TRACK_SIDEREAL")

            if self._wait_for_property(device, "TELESCOPE_TRACK_STATE", timeout=2.0):
                return self.set_switch(device, "TELESCOPE_TRACK_STATE", "TRACK_ON")
            return True

        def newDevice(self, device):
            device_name = device.getDeviceName().lower()
            preferred = (self.preferred_device_name or "").lower()
            is_preferred = preferred and device_name == preferred
            is_telescope_like = (
                any(
                    word in device_name
                    for word in ("telescope", "mount", "eqmod", "lx200", "celestron")
                )
                or device_name == "telescope simulator"
            )
            if is_preferred or (self.telescope_device is None and is_telescope_like):
                self.telescope_device = device
                clientlogger.info(
                    "Telescope device detected: %s", device.getDeviceName()
                )

        def removeDevice(self, device):
            if (
                self.telescope_device
                and device.getDeviceName() == self.telescope_device.getDeviceName()
            ):
                clientlogger.warning(
                    "Telescope device removed: %s", device.getDeviceName()
                )
                self.telescope_device = None

        def _notify_alignment_limits(self, name, device_name, values=None):
            if (
                name in {"Slew elevation Limit", "CONNECTION"}
                and self.mount_control is not None
                and device_name == self.mount_control._indi_device_name()
            ):
                self.mount_control.refresh_alignment_limits(self.generation, values)

        def newProperty(self, prop):
            # Definitions can arrive long after connection, without an update.
            if prop.getName() in {"Slew elevation Limit", "CONNECTION"}:
                self.updateProperty(prop)

        def removeProperty(self, prop):
            self._notify_alignment_limits(prop.getName(), prop.getDeviceName(), {})

        def newNumber(self, nvp):
            if nvp.name == "Slew elevation Limit":
                self._notify_alignment_limits(
                    nvp.name,
                    getattr(nvp, "device", None),
                    {w.name: w.value for w in nvp},
                )
                return
            if nvp.name not in {
                "EQUATORIAL_EOD_COORD",
                "GUIDE_RATE",
                "GEOGRAPHIC_COORD",
            }:
                return
            self._record_sync_property(
                nvp.name,
                nvp.s,
                {widget.name: widget.value for widget in nvp},
                getattr(nvp, "device", None),
            )
            if nvp.name != "EQUATORIAL_EOD_COORD":
                return

            ra_hours = None
            dec_deg = None
            for widget in nvp:
                if widget.name == "RA":
                    ra_hours = widget.value
                elif widget.name == "DEC":
                    dec_deg = widget.value

            if (
                self.mount_control is not None
                and ra_hours is not None
                and dec_deg is not None
            ):
                self.mount_control.receive_current_position(ra_hours * 15.0, dec_deg)

        def _record_sync_property(self, name, state, values, device_name):
            if self.mount_control is None:
                return
            if device_name != self.mount_control._indi_device_name():
                return
            state_name = {
                PyIndi.IPS_IDLE: "idle",
                PyIndi.IPS_OK: "ok",
                PyIndi.IPS_BUSY: "busy",
                PyIndi.IPS_ALERT: "alert",
            }.get(state, "unknown")
            self.mount_control.receive_sync_property(
                name, state_name, values, self.generation
            )

        def newSwitch(self, svp):
            if svp.name == "CONNECTION":
                self._notify_alignment_limits(svp.name, getattr(svp, "device", None))
            if svp.name in {"ON_COORD_SET", "TELESCOPE_SLEW_RATE"}:
                self._record_sync_property(
                    svp.name,
                    svp.s,
                    {widget.name: widget.s == PyIndi.ISS_ON for widget in svp},
                    getattr(svp, "device", None),
                )

        def newText(self, tvp):
            if getattr(tvp, "name", "") == "TIME_UTC":
                self._record_sync_property(
                    tvp.name,
                    tvp.s,
                    {w.name: w.text for w in tvp},
                    getattr(tvp, "device", None),
                )
            if (
                self.mount_control is not None
                and getattr(tvp, "name", "") == "OnStep Status"
            ):
                self.mount_control.receive_onstep_status()

        def updateProperty(self, prop):
            # INDI 2.x replaced the typed 1.x callbacks (newNumber, ...) with
            # this single entry point. Without it the driver's PERIOD_MS
            # coordinate pushes are silently dropped and the readback only
            # advances on the 5 s status heartbeat — far too slow for the
            # pointing fusion to attribute slew motion to the mount.
            try:
                if prop.getName() == "CONNECTION":
                    self._notify_alignment_limits(prop.getName(), prop.getDeviceName())
                    return
                if prop.getName() == "Slew elevation Limit":
                    nvp = PyIndi.PropertyNumber(prop)
                    self._notify_alignment_limits(
                        prop.getName(),
                        prop.getDeviceName(),
                        {w.getName(): w.getValue() for w in nvp},
                    )
                    return
                # Snapshot only server callbacks. set_number/set_switch mutate
                # the local property cache before sending and cannot be ACKs.
                if prop.getName() in {"ON_COORD_SET", "TELESCOPE_SLEW_RATE"}:
                    svp = PyIndi.PropertySwitch(prop)
                    self._record_sync_property(
                        prop.getName(),
                        prop.getState(),
                        {w.getName(): w.getState() == PyIndi.ISS_ON for w in svp},
                        prop.getDeviceName(),
                    )
                if prop.getName() == "OnStep Status" and self.mount_control is not None:
                    self.mount_control.receive_onstep_status()
                if prop.getName() == "TIME_UTC":
                    tvp = PyIndi.PropertyText(prop)
                    self._record_sync_property(
                        prop.getName(),
                        prop.getState(),
                        {w.getName(): w.getText() for w in tvp},
                        prop.getDeviceName(),
                    )
                if prop.getType() != PyIndi.INDI_NUMBER:
                    return
                if prop.getName() not in {
                    "EQUATORIAL_EOD_COORD",
                    "GUIDE_RATE",
                    "GEOGRAPHIC_COORD",
                }:
                    return
                nvp = PyIndi.PropertyNumber(prop)
                self._record_sync_property(
                    prop.getName(),
                    prop.getState(),
                    {w.getName(): w.getValue() for w in nvp},
                    prop.getDeviceName(),
                )
                if prop.getName() != "EQUATORIAL_EOD_COORD":
                    return
                ra_widget = nvp.findWidgetByName("RA")
                dec_widget = nvp.findWidgetByName("DEC")
                if (
                    self.mount_control is not None
                    and ra_widget is not None
                    and dec_widget is not None
                ):
                    self.mount_control.receive_current_position(
                        ra_widget.getValue() * 15.0, dec_widget.getValue()
                    )
            except Exception:
                clientlogger.exception("updateProperty coordinate handling failed")

        def newMessage(self, device, message):
            # Routine driver chatter (time/coordinate echoes) floods the log
            # at INFO during every session; real state changes are logged by
            # their handlers. Keep the raw stream at debug.
            clientlogger.debug(
                "INDI message from %s: %s",
                device.getDeviceName(),
                device.messageQueue(message),
            )

        def serverConnected(self):
            clientlogger.info("Connected to INDI server")

        def serverDisconnected(self, code):
            now = time.monotonic()
            last = self._last_disconnect_log_monotonic
            if last is None or now - last >= self._DISCONNECT_LOG_INTERVAL_S:
                clientlogger.warning("Disconnected from INDI server: %s", code)
                self._last_disconnect_log_monotonic = now
            else:
                clientlogger.debug("Disconnected from INDI server: %s", code)
            if self.mount_control is not None:
                self.mount_control.mark_disconnected(
                    f"INDI server disconnected: {code}",
                    client_generation=self.generation,
                )

else:

    class PiFinderIndiClient:  # type: ignore[no-redef]
        pass


class MountControlIndi(BacklashCalibrationMixin):
    """Translate MFNavis queue commands into INDI telescope commands."""

    def __init__(
        self,
        mount_queue: Queue,
        console_queue: Queue,
        shared_state,
        imu_command_queue: Optional[Queue] = None,
        indi_host: str = "localhost",
        indi_port: int = 7624,
    ):
        self.mount_queue = mount_queue
        self.console_queue = console_queue
        self.error_notifier = ErrorNotifier(console_queue, "INDI Mount")
        self._connection_announced = False
        self._initial_site_request: Optional[dict[str, Any]] = None
        self._initial_site_after_sequence = 0
        self._initial_site_deadline = 0.0
        self._initial_site_write_ok = False
        self._initial_site_sent_connected = False
        self._initial_site_complete = False
        self._initial_site_failed = False
        self._initial_site_reset_attempted = False
        self._initial_site_recovering = False
        self._initial_site_expected_time: Any = None
        self.shared_state = shared_state
        self.imu_command_queue = imu_command_queue
        self.indi_host = indi_host
        self.indi_port = indi_port
        self.client: Optional[PiFinderIndiClient] = None
        self._client_generation = 0
        self.device = None
        self.slew_rate = 5
        self.guide_rate_we = GUIDE_RATE_FINE_X
        self.guide_rate_ns = GUIDE_RATE_FINE_X
        self._load_motion_rates()
        self._guide_rate_needs_reassert = True
        self._guide_pulse_until = 0.0
        self._pending_guide_rate: Optional[dict[str, Any]] = None
        self._confirmed_guide_rates: Optional[tuple[float, float]] = None
        self.current_ra: Optional[float] = None
        self.current_dec: Optional[float] = None
        self.connected = False
        self._last_position_status_at = 0.0
        self._last_status_heartbeat_at = 0.0
        self._manual_motion_direction: Optional[str] = None
        # Identifies who initiated the low-level manual-move primitive.  User
        # controls (keypad/keyboard/joystick/web/SkySafari) use ``user``;
        # Tracking Guide's driver fallback uses ``guide_correction`` so it can
        # never be mistaken for an intentional re-target.
        self._manual_motion_origin: Optional[str] = None
        self._last_user_motion_started_wall = 0.0
        self._last_user_motion_stopped_wall = 0.0
        self._manual_motion_deadline: Optional[float] = None
        self._manual_motion_started_at: Optional[float] = None
        self._manual_motion_stop_retry_at = 0.0
        self._pending_goto_refine: Optional[dict[str, Any]] = None
        self._last_goto_target: Optional[tuple[float, float]] = None
        self._goto_motion: Optional[dict[str, Any]] = None
        self._guide_correction_enabled = False
        self._guide_correction_target: Optional[tuple[float, float]] = None
        self._guide_correction_accuracy_arcmin = DEFAULT_GOTO_REFINE_ACCURACY_ARCMIN
        self._guide_axis_scale = 1.0
        self._guide_mount_type = "Alt/Az"
        self._guide_correction_next_at = 0.0
        self._guide_correction_observation: dict[str, Any] = {}
        self._guide_correction_last_solve_time = 0.0
        self._guide_pulse_best_error: Optional[float] = None
        self._guide_pulse_worsening = 0
        self._guide_progress_solve_time = 0.0
        self._guide_manual_approach = False
        self._guide_correction_mode = "off"
        self._guide_observation_after_wall = 0.0
        self._approach_rate_request: Optional[dict[str, Any]] = None
        self._approach_previous_error: Optional[float] = None
        self._approach_no_progress = 0
        # Cached result of INDI timed-guide-pulse capability detection (None =
        # not yet probed). When False, guide correction uses the manual-move
        # fallback.
        self._pulse_guide_supported: Optional[bool] = None
        # Guide-rate switching state: boosted is True while the fast recovery
        # rate is applied (must be restored to the fine rate on finish);
        # writable is None until the first GUIDE_RATE write attempt, False when
        # the driver rejected it (no further attempts).
        self._guide_rate_boosted = False
        self._guide_rate_writable: Optional[bool] = None
        self._last_goto_progress_status_at = 0.0
        self._last_manual_motion_status_at = 0.0
        self.backlash_ra: Optional[int] = None
        self.backlash_de: Optional[int] = None
        self._backlash_auto: Optional[dict[str, Any]] = None
        self._backlash_stop_seen_at: float = 0.0
        self._multipoint_align_controller = MultiPointAlignController()
        self._multipoint_align: Optional[dict[str, Any]] = None
        self._coordinate_sync: Optional[dict[str, Any]] = None
        self._controller_status_lock = threading.Lock()
        self._last_controller_status: Optional[dict[str, Any]] = None
        self._sync_property_lock = threading.Lock()
        self._sync_property_sequence = 0
        self._sync_property_receipts: dict[str, dict[str, Any]] = {}
        self._pending_sync_goto: Optional[dict[str, Any]] = None
        self._sync_goto_status: Optional[dict[str, Any]] = None
        # Non-sidereal tracking frequency (None = sidereal firmware default).
        # The target is kept so the frequency can be re-asserted after a
        # driver reconnect resets it (see _reassert_track_frequency).
        self._track_freq_target_hz: Optional[float] = None
        self._track_freq_label: str = ""
        self._track_freq_last_assert_at = 0.0
        # Consecutive failed auto-reconnect attempts. The first failure after
        # a state change logs in full; repeats run with WARNING/INFO logging
        # suppressed so an offline mount does not fill the log every retry.
        self._auto_connect_failures = 0
        # True while the last location/time sync carried an untrusted
        # (provisional) clock -- the A5 hook replaces it once trusted.
        self._time_sync_provisional = False
        # Monotonic deadline for re-applying the user's slew rate after a
        # GUIDE_RATE write. The OnStepX driver maps GUIDE_RATE onto the
        # firmware's shared move-rate selector (:R<n>#), so every fine/fast
        # guide-rate switch also drags the manual-move speed down to
        # 0.5x/1x until TELESCOPE_SLEW_RATE is re-asserted.
        self._slew_rate_reassert_at: Optional[float] = None
        # True from a successful GUIDE_RATE write until the user's slew rate
        # has been re-applied (keeps idle guide cycles from re-writing).
        self._slew_rate_polluted = False
        self._connection_config_ready = True
        self._connection_config_status: dict[str, Any] = {}
        self._position_update_generation = 0
        self._onstep_status_generation = 0
        self._last_fresh_position_at = 0.0
        self._last_fresh_onstep_status_at = 0.0
        self._usb_serial_path = ""
        self._usb_serial_present: Optional[bool] = None
        self._usb_serial_last_check_at = 0.0
        self._usb_absent_latched = False
        self._usb_returned_at: Optional[float] = None
        self._usb_reconnect_used = False
        self._usb_recovery_snapshot: dict[str, Any] = {}
        self._usb_recovery_status: dict[str, Any] = {
            "connection_health": "not_monitored",
            "serial_present": None,
            "recovery_attempt": 0,
        }
        self._serial_discovery_active = False
        self._serial_discovery_status: dict[str, Any] = {
            "serial_discovery_state": "idle",
        }

    def _console(self, message: str) -> None:
        self.console_queue.put(message)

    def _mount_common_status_fields(
        self, state: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        state_lower = state.strip().lower()
        motion_type: Optional[str] = None
        motion_active = False
        readback_priority = False

        if self._manual_motion_direction is not None or payload.get(
            "manual_motion_direction"
        ):
            motion_type = "manual"
            motion_active = True
            readback_priority = True
        elif self._goto_motion is not None or payload.get("goto_motion_active"):
            motion_type = "goto"
            motion_active = True
            readback_priority = True
        elif self._pending_goto_refine is not None or payload.get(
            "goto_refine_pending"
        ):
            motion_type = "goto_refine_settle"
            readback_priority = True

        if state_lower in {"slewing", "align_goto"}:
            motion_type = motion_type or "goto"
            motion_active = True
            readback_priority = True
        elif state_lower == "manual_motion":
            motion_type = motion_type or "manual"
            motion_active = True
            readback_priority = True
        elif state_lower in {"refine_wait", "refine_sent"}:
            motion_type = motion_type or "goto_refine_settle"
            readback_priority = True
        elif state_lower == "guide_correction":
            # A tracking-guide correction is a sub-arcminute pulse (~0.001 deg at
            # guide rate) -- it barely moves the mount readback, and the IMU
            # delta is already rate-gated so the pulse itself is discarded. Do
            # NOT claim readback priority for it: otherwise, while the guide is
            # nulling residual error right after a GoTo/recovery, the fused
            # coordinate falls back to raw mount for several seconds and a real
            # hand-push (external disturbance) is ignored during that window.
            motion_type = motion_type or "guide_correction"
        elif state_lower.startswith("backlash_auto_") and state_lower not in {
            "backlash_auto_complete",
            "backlash_auto_failed",
            "backlash_auto_stopped",
        }:
            motion_type = motion_type or "backlash_auto"
            motion_active = True
            readback_priority = True
        elif "slew" in state_lower or "goto" in state_lower:
            motion_type = motion_type or "goto"
            motion_active = True
            readback_priority = True
        elif "moving" in state_lower or "motion" in state_lower:
            motion_type = motion_type or "manual"
            motion_active = True
            readback_priority = True

        multipoint = payload.get("multipoint_align")
        if isinstance(multipoint, dict):
            align_state = str(multipoint.get("state", "")).strip().lower()
            if "goto" in align_state or "slew" in align_state:
                motion_type = motion_type or "align_goto"
                motion_active = True
                readback_priority = True

        backlash = payload.get("backlash_auto")
        if isinstance(backlash, dict):
            backlash_state = str(backlash.get("state", "")).strip().lower()
            if backlash_state in {"starting", "running"}:
                motion_type = motion_type or "backlash_auto"
                motion_active = True
                readback_priority = True

        return {
            "mount_motion_active": motion_active,
            "mount_motion_type": motion_type,
            "mount_readback_priority": readback_priority,
        }

    def _status_fields(self, state: str = "", **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "connection_established": self._connection_announced,
            "initial_location_sync_state": (
                "resetting"
                if self._initial_site_recovering
                else "failed"
                if self._initial_site_failed
                else "ready"
                if self._initial_site_complete
                else "verifying"
                if self._initial_site_request
                else "waiting_location"
            ),
            "initial_location_reset_attempted": self._initial_site_reset_attempted,
            "tracking_enabled": self._cached_tracking_enabled(),
            "slew_rate": self.slew_rate,
            "manual_slew_rate": self.slew_rate,
            "pulse_guide_rate": self.guide_rate_we,
            "pulse_guide_rate_active": (
                self._confirmed_guide_rates[0]
                if not self._guide_rate_needs_reassert
                and self._confirmed_guide_rates is not None
                else None
            ),
            "pulse_guide_rate_requested": (
                self._pending_guide_rate["rate"]
                if self._pending_guide_rate is not None
                else None
            ),
            "pulse_guide_rate_we": self.guide_rate_we,
            "pulse_guide_rate_ns": self.guide_rate_ns,
            "guide_rate_waiting": self._pending_guide_rate is not None,
            "guide_rate_confirmed": not self._guide_rate_needs_reassert,
            "ra": self.current_ra,
            "dec": self.current_dec,
        }
        low, high = self._alignment_altitude_limits()
        payload["alignment_min_altitude"] = low
        payload["alignment_max_altitude"] = high
        payload.update(self._home_park_status_fields())
        if self._manual_motion_direction is not None:
            payload["manual_motion_direction"] = self._manual_motion_direction
            payload["manual_motion_origin"] = self._manual_motion_origin or "user"
            if self._manual_motion_deadline is not None:
                payload["manual_motion_lease_remaining"] = max(
                    0.0, self._manual_motion_deadline - time.monotonic()
                )
        if self._pending_goto_refine is not None:
            payload["goto_refine_pending"] = True
            payload["goto_refine_accuracy_arcmin"] = self._pending_goto_refine.get(
                "accuracy_arcmin"
            )
        if self._goto_motion is not None:
            payload["goto_motion_active"] = True
            payload["target_ra"] = self._goto_motion.get("target_ra")
            payload["target_dec"] = self._goto_motion.get("target_dec")
        if self._track_freq_target_hz is not None:
            payload["track_freq_hz"] = self._track_freq_target_hz
            payload["track_freq_arcsec_s"] = nonsidereal.rate_from_hz(
                self._track_freq_target_hz
            )
            if self._track_freq_label:
                payload["track_freq_label"] = self._track_freq_label
        if self._time_sync_provisional:
            payload["time_sync_provisional"] = True
        payload["guide_correction_enabled"] = self._guide_correction_enabled
        payload["last_user_motion_started_wall"] = self._last_user_motion_started_wall
        payload["last_user_motion_stopped_wall"] = self._last_user_motion_stopped_wall
        payload["guide_correction_mode"] = self._guide_correction_mode
        payload["guide_observation_after_wall"] = self._guide_observation_after_wall
        payload["guide_pulse_until_wall"] = (
            time.time() + self._guide_pulse_until - time.monotonic()
            if self._guide_pulse_until > 0
            else 0.0
        )
        if self._guide_correction_target is not None:
            payload["guide_correction_target_ra"] = self._guide_correction_target[0]
            payload["guide_correction_target_dec"] = self._guide_correction_target[1]
            payload["guide_correction_accuracy_arcmin"] = (
                self._guide_correction_accuracy_arcmin
            )
        if self.backlash_ra is not None:
            payload["backlash_ra"] = self.backlash_ra
        if self.backlash_de is not None:
            payload["backlash_de"] = self.backlash_de
        if self._backlash_auto is not None:
            payload["backlash_auto"] = self._backlash_auto
        if self._multipoint_align is not None:
            payload["multipoint_align"] = self._multipoint_align
        if self._coordinate_sync is not None:
            payload["coordinate_sync"] = self._coordinate_sync
        if self._sync_goto_status is not None:
            payload["sync_goto"] = dict(self._sync_goto_status)
        payload.update(self._connection_config_status)
        payload.update(self._usb_recovery_status)
        payload.update(self._serial_discovery_status)
        if self.device is not None:
            try:
                payload["device"] = self.device.getDeviceName()
            except Exception:
                pass
        payload.update(extra)
        payload.update(self._mount_common_status_fields(state, payload))
        return payload

    def _alignment_altitude_limits(self) -> tuple[float, float]:
        """Read the connected OnStep driver's current elevation limits.

        Read PyIndi's property cache each time so edits made by other INDI
        clients apply without reconnecting. Never reuse a disconnected device.
        """
        if self.device is not None and self._device_is_connected():
            try:
                prop = self.device.getNumber("Slew elevation Limit")
                if prop:
                    values = {item.name: item.value for item in prop}
                    return alignment_altitude_limits(
                        values.get("minAlt"), values.get("maxAlt")
                    )
            except Exception:
                logger.debug("Could not read INDI elevation limits", exc_info=True)
        return alignment_altitude_limits()

    def _device_switch_on(
        self, property_name: str, element_name: str
    ) -> Optional[bool]:
        if self.device is None:
            return None
        try:
            switch_prop = self.device.getSwitch(property_name)
        except Exception:
            return None
        if not switch_prop:
            return None
        for i in range(len(switch_prop)):
            switch = switch_prop[i]
            if getattr(switch, "name", "") != element_name:
                continue
            state = getattr(switch, "s", None)
            if PyIndi is not None:
                try:
                    return state == PyIndi.ISS_ON
                except Exception:
                    pass
            return str(state).lower() in {"on", "iss_on", "1", "true"}
        return None

    def _device_text_value(self, property_name: str, element_name: str) -> str:
        if self.device is None:
            return ""
        try:
            text_prop = self.device.getText(property_name)
        except Exception:
            return ""
        if not text_prop:
            return ""
        for i in range(len(text_prop)):
            text = text_prop[i]
            if getattr(text, "name", "") == element_name:
                return str(getattr(text, "text", "") or "")
        return ""

    def _home_park_status_fields(self) -> dict[str, str]:
        status_text = self._device_text_value("OnStep Status", "Park")
        raw_status = self._device_text_value("OnStep Status", ":GU# return")
        park_switch = self._device_switch_on("TELESCOPE_PARK", "PARK")
        unpark_switch = self._device_switch_on("TELESCOPE_PARK", "UNPARK")
        state = sys_utils.parse_onstep_home_park_state(
            status_text=status_text,
            park_switch="On" if park_switch else "",
            unpark_switch="On" if unpark_switch else "",
            raw_status=raw_status,
        )
        return {
            "home_state": state["home_state"],
            "park_state": state["park_state"],
            "driver_mount_status": state["driver_status"],
            "raw_mount_status": state["raw_status"],
        }

    def _write_controller_status(
        self, state: str, message: str = "", **extra: Any
    ) -> None:
        initial_recovery_pending = self._initial_site_request is not None and not (
            self._initial_site_complete or self._initial_site_failed
        )
        recovering_error = self._initial_site_recovering or (
            initial_recovery_pending and state in {"sync_failed", "tracking_failed"}
        )
        if mount_failure(state) and not recovering_error:
            self.error_notifier.emit(state, message or state)
        with self._controller_status_lock:
            payload = self._status_fields(state, **extra)
            self._last_controller_status = dict(state=state, message=message, **payload)
            _write_status(**self._last_controller_status)

    def refresh_alignment_limits(
        self, client_generation: int, values: Optional[dict[str, Any]] = None
    ) -> None:
        """Publish arriving limits immediately, preserving the current mount state."""
        with self._controller_status_lock:
            if client_generation != self._client_generation:
                return
            if values is not None and self._device_is_connected():
                low, high = alignment_altitude_limits(
                    values.get("minAlt"), values.get("maxAlt")
                )
            else:
                low, high = self._alignment_altitude_limits()
            # Before the first status, connect() will publish the property cache.
            if self._last_controller_status is None:
                return
            payload = self._last_controller_status
            if (
                payload.get("alignment_min_altitude"),
                payload.get("alignment_max_altitude"),
            ) == (low, high):
                return
            payload.update(alignment_min_altitude=low, alignment_max_altitude=high)
            _write_status(**payload)

    def _indi_device_name(self) -> str:
        if self.device is not None:
            try:
                return self.device.getDeviceName()
            except Exception:
                pass
        return sys_utils.get_indi_profile_device_name()

    def _indi_property_name(self, property_name: str) -> str:
        return f"{self._indi_device_name()}.{property_name}"

    def _indi_property_on(self, property_name: str) -> str:
        return f"{self._indi_property_name(property_name)}=On"

    def _indi_property_state(self, property_name: str) -> Any:
        if self.device is None:
            return None

        for getter_name in ("getProperty", "getNumber", "getSwitch", "getText"):
            getter = getattr(self.device, getter_name, None)
            if getter is None:
                continue
            try:
                prop = getter(property_name)
            except Exception:
                continue
            if not prop:
                continue

            state = getattr(prop, "s", None)
            if state is None:
                get_state = getattr(prop, "getState", None)
                if callable(get_state):
                    try:
                        state = get_state()
                    except Exception:
                        state = None
            if state is not None:
                return state
        return None

    def _indi_state_is_busy(self, state: Any) -> bool:
        if state is None:
            return False
        if PyIndi is not None:
            try:
                if state == PyIndi.IPS_BUSY:
                    return True
            except Exception:
                pass
        return str(state).lower() == "busy"

    def _indi_mount_is_busy(self) -> Optional[bool]:
        saw_state = False
        for property_name in (
            "EQUATORIAL_EOD_COORD",
            "ON_COORD_SET",
            "TELESCOPE_MOTION_NS",
            "TELESCOPE_MOTION_WE",
        ):
            state = self._indi_property_state(property_name)
            if state is None:
                continue
            saw_state = True
            if self._indi_state_is_busy(state):
                return True
        return False if saw_state else None

    def _raw_onstep_status(self) -> str:
        return self._device_text_value("OnStep Status", ":GU# return").strip()

    def _onstep_goto_complete(self) -> Optional[bool]:
        raw_status = self._raw_onstep_status()
        if not raw_status:
            return None
        return "N" in raw_status

    def _goto_completion_ready(
        self,
        motion: dict[str, Any],
        is_busy: Optional[bool],
        now: float,
        current_position: Optional[tuple[float, float]] = None,
    ) -> bool:
        elapsed = now - float(motion.get("started_at", now))
        onstep_complete = self._onstep_goto_complete()

        if is_busy is True:
            motion["indi_seen_busy"] = True
            motion["complete_ready_since"] = None
            return False

        if onstep_complete is False:
            motion["onstep_seen_goto_active"] = True
            motion["complete_ready_since"] = None
            return False

        if onstep_complete is True:
            saw_active = bool(
                motion.get("indi_seen_busy") or motion.get("onstep_seen_goto_active")
            )
            if not saw_active and elapsed < GOTO_ONSTEP_ACTIVE_OBSERVE_GRACE_SECONDS:
                motion["complete_ready_since"] = None
                return False

        if is_busy is not False:
            motion["complete_ready_since"] = None
            return False

        if current_position is not None:
            target_ra = motion.get("target_ra")
            target_dec = motion.get("target_dec")
            if target_ra is not None and target_dec is not None:
                target_error_deg = (
                    radec_separation_arcmin(
                        current_position[0],
                        current_position[1],
                        float(target_ra),
                        float(target_dec),
                    )
                    / 60.0
                )
                motion["target_error_deg"] = target_error_deg
                if target_error_deg > GOTO_COMPLETE_TARGET_TOLERANCE_DEG:
                    motion["complete_ready_since"] = None
                    motion["last_complete_position"] = current_position
                    return False

            last_position = motion.get("last_complete_position")
            if last_position is not None:
                position_change_deg = (
                    radec_separation_arcmin(
                        current_position[0],
                        current_position[1],
                        float(last_position[0]),
                        float(last_position[1]),
                    )
                    / 60.0
                )
                motion["position_change_deg"] = position_change_deg
                if position_change_deg > GOTO_COMPLETE_POSITION_STABLE_DEG:
                    motion["complete_ready_since"] = None
                    motion["last_complete_position"] = current_position
                    return False
            motion["last_complete_position"] = current_position

        ready_since = motion.get("complete_ready_since")
        if ready_since is None:
            motion["complete_ready_since"] = now
            return False
        return now - float(ready_since) >= GOTO_COMPLETE_STABLE_SECONDS

    def _write_status_heartbeat(self) -> None:
        now = time.monotonic()
        if now - self._last_status_heartbeat_at < STATUS_HEARTBEAT_INTERVAL:
            return
        self._last_status_heartbeat_at = now

        if (
            self.connected
            and self.client is not None
            and self.device is not None
            and self.client.isServerConnected()
        ):
            if not self._device_is_connected():
                self.mark_disconnected("INDI mount device is disconnected")
                return
            if (
                self._goto_motion is not None
                or self._manual_motion_direction is not None
            ):
                return
            self._read_cached_current_position()
            # Driver readback may be a temporary guide selector. It must not
            # overwrite the user's separately saved manual speed.
            self._write_controller_status("connected", "INDI mount connected")
        elif not self.connected:
            health = self._usb_recovery_status.get("connection_health")
            if health == "usb_absent":
                self._write_controller_status(
                    "usb_absent", "Configured USB serial device is absent"
                )
            elif health == "return_debounce":
                self._write_controller_status(
                    "usb_return_debounce",
                    "USB serial returned; waiting for stable device node",
                )
            elif health == "recovery_failed":
                self._write_controller_status(
                    "usb_recovery_failed",
                    str(
                        self._usb_recovery_status.get(
                            "recovery_error", "USB serial recovery failed"
                        )
                    ),
                )
            else:
                self._write_controller_status("idle", "INDI mount waiting")

    def _apply_indi_properties(
        self,
        properties: list[str],
        success_state: str,
        success_message: str,
        failure_state: str,
    ) -> bool:
        try:
            result = sys_utils.apply_indi_onstep_properties(
                properties,
                server_host=self.indi_host,
                server_port=self.indi_port,
            )
        except Exception as exc:
            logger.exception("INDI setprop command failed")
            self._write_controller_status(failure_state, str(exc))
            return False

        if not result.get("ok"):
            error = (
                result.get("stderr") or result.get("stdout") or "INDI command failed"
            )
            logger.warning("INDI setprop returned failure: %s", error)
            self._write_controller_status(failure_state, error)
            return False

        self._write_controller_status(success_state, success_message)
        return True

    def _apply_indi_backlash(self, backlash_ra: int, backlash_de: int):
        return sys_utils.apply_indi_onstep_backlash(
            backlash_ra,
            backlash_de,
            server_host=self.indi_host,
            server_port=self.indi_port,
            device_name=self._indi_device_name(),
        )

    def set_current_position(
        self, ra_deg: float, dec_deg: float, write_status: bool = True
    ) -> None:
        self.current_ra = ra_deg % 360.0
        self.current_dec = dec_deg
        if write_status:
            self._write_position_status()

    def receive_current_position(self, ra_deg: float, dec_deg: float) -> None:
        """Record a coordinate pushed by INDI, distinct from a cached read."""
        self._position_update_generation += 1
        self._last_fresh_position_at = time.monotonic()
        self.set_current_position(ra_deg, dec_deg)

    def receive_onstep_status(self) -> None:
        """Record a fresh OnStep Status callback for recovery verification."""
        self._onstep_status_generation += 1
        self._last_fresh_onstep_status_at = time.monotonic()

    def _write_position_status(self, force: bool = False) -> None:
        # Coordinate callbacks can arrive just after a USB removal or while a
        # recovery client is still proving fresh telemetry. They are useful
        # for the generation counters, but must not overwrite usb_absent /
        # recovering with a false top-level connected state.
        if not self.connected:
            return
        now = time.monotonic()
        if (
            not force
            and now - self._last_position_status_at < POSITION_STATUS_MIN_INTERVAL
        ):
            return
        self._last_position_status_at = now
        self._write_controller_status(
            "connected",
            "Mount position updated",
        )

    def _manual_motion_lease(self, requested: Any = None) -> float:
        try:
            lease_seconds = float(requested)
        except (TypeError, ValueError):
            lease_seconds = MANUAL_MOTION_LEASE_SECONDS
        return max(
            MANUAL_MOTION_MIN_LEASE_SECONDS,
            min(MANUAL_MOTION_MAX_LEASE_SECONDS, lease_seconds),
        )

    def _clear_manual_motion_deadline(self) -> None:
        self._manual_motion_direction = None
        self._manual_motion_origin = None
        self._manual_motion_deadline = None
        self._manual_motion_started_at = None
        self._manual_motion_stop_retry_at = 0.0

    def _arm_manual_motion_deadline(
        self,
        direction: str,
        lease_seconds: Any = None,
        origin: str = "user",
    ) -> None:
        now = time.monotonic()
        self._manual_motion_direction = direction
        self._manual_motion_origin = origin
        if origin == "user":
            self._last_user_motion_started_wall = time.time()
        self._manual_motion_deadline = now + self._manual_motion_lease(lease_seconds)
        self._manual_motion_started_at = now
        self._manual_motion_stop_retry_at = 0.0
        self._last_manual_motion_status_at = 0.0

    def manual_motion_keepalive(
        self, direction: str, lease_seconds: Any = None
    ) -> bool:
        direction = direction.lower()
        if (
            self._manual_motion_direction is None
            or direction != self._manual_motion_direction
        ):
            return False

        now = time.monotonic()
        if (
            self._manual_motion_started_at is not None
            and now - self._manual_motion_started_at
            > MANUAL_MOTION_MAX_CONTINUOUS_SECONDS
        ):
            logger.warning("Manual mount motion maximum hold time exceeded")
            return False

        self._manual_motion_deadline = now + self._manual_motion_lease(lease_seconds)
        return True

    def _manual_motion_queue_timeout(self) -> float:
        if (
            self._pending_sync_goto is not None
            or self._pending_guide_rate is not None
            or self._approach_rate_request is not None
        ):
            return MANUAL_MOTION_POLL_SECONDS
        if self._manual_motion_deadline is None:
            return 1.0
        return max(
            MANUAL_MOTION_POLL_SECONDS,
            min(1.0, self._manual_motion_deadline - time.monotonic()),
        )

    def _check_manual_motion_deadline(self) -> None:
        if self._manual_motion_deadline is None:
            return

        now = time.monotonic()
        if (
            now < self._manual_motion_deadline
            or now < self._manual_motion_stop_retry_at
        ):
            return

        logger.warning("Manual mount motion lease expired; sending stop")
        if self.stop_mount():
            return

        self._manual_motion_stop_retry_at = now + MANUAL_MOTION_STOP_RETRY_SECONDS

    def _read_manual_motion_progress_position(
        self,
    ) -> Optional[tuple[float, float]]:
        try:
            return self._read_cached_current_position(write_status=False)
        except TypeError:
            # Some tests monkeypatch this method with a no-argument callable.
            return self._read_cached_current_position()

    def _write_manual_motion_progress_status(
        self,
        current_position: Optional[tuple[float, float]],
        force: bool = False,
    ) -> None:
        if self._manual_motion_direction is None:
            return

        now = time.monotonic()
        if (
            not force
            and now - self._last_manual_motion_status_at < POSITION_STATUS_MIN_INTERVAL
        ):
            return
        self._last_manual_motion_status_at = now

        extra: dict[str, Any] = {
            "manual_motion_direction": self._manual_motion_direction,
            "manual_motion_origin": self._manual_motion_origin or "user",
        }
        if self._manual_motion_started_at is not None:
            extra["manual_motion_elapsed"] = round(
                now - self._manual_motion_started_at, 1
            )
        if current_position is not None:
            extra["ra"] = current_position[0] % 360.0
            extra["dec"] = current_position[1]

        self._write_controller_status(
            "manual_motion",
            f"Manual {self._manual_motion_direction} motion in progress",
            **extra,
        )

    def _publish_manual_motion_progress(self, force: bool = False) -> None:
        if self._manual_motion_direction is None:
            return
        current_position = self._read_manual_motion_progress_position()
        self._write_manual_motion_progress_status(current_position, force=force)

    def _wait_for_device(
        self, timeout: float = AUTO_CONNECT_DEVICE_WAIT_SECONDS
    ) -> bool:
        assert self.client is not None
        start = time.time()
        while time.time() - start < timeout:
            self.device = self.client.get_telescope_device()
            if self.device is not None:
                return True
            time.sleep(0.25)
        return False

    def _device_is_connected(self) -> bool:
        if self.device is None:
            return False
        try:
            if self.device.isConnected():
                return True
        except Exception:
            pass
        return self._device_switch_on("CONNECTION", "CONNECT") is True

    def _wait_for_device_connected(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._device_is_connected():
                return True
            time.sleep(0.25)
        return False

    def _wait_for_current_position(
        self, timeout: float
    ) -> Optional[tuple[float, float]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            position = self._read_current_position()
            if position is not None:
                return position
            time.sleep(0.25)
        return None

    def _wait_for_fresh_telemetry(
        self,
        position_generation: int,
        status_generation: int,
        timeout: float,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (
                self._position_update_generation > position_generation
                and self._onstep_status_generation > status_generation
            ):
                return True
            time.sleep(0.1)
        return False

    def connect(
        self,
        announce: bool = True,
        sync_on_connect: bool = True,
        preserve_mount_state: bool = False,
        require_fresh_telemetry: bool = False,
        publish_connected: bool = True,
    ) -> bool:
        if (
            self.connected
            and self.device is not None
            and self.client is not None
            and self.client.isServerConnected()
        ):
            if self._device_is_connected():
                return True
            self.mark_disconnected("INDI mount device is disconnected")

        if self.connected:
            self.mark_disconnected("INDI server connection is not active")

        if PyIndi is None:
            self._write_controller_status("missing_pyindi", "PyIndi is not installed")
            if announce:
                self._console("INDI mount\nPyIndi missing")
            return False

        direct_sync_for_onstep = self._use_direct_onstep_location_time_sync()
        if sync_on_connect and direct_sync_for_onstep:
            self.sync_location_time(reconnect_after=False)

        if self.client is not None:
            self._client_generation += 1
            try:
                self.client.disconnectServer()
            except Exception:
                logger.debug("Could not close previous INDI client", exc_info=True)
        self.client = None
        self.device = None

        self._client_generation += 1
        self.client = PiFinderIndiClient(self, generation=self._client_generation)
        self.client.setServer(self.indi_host, self.indi_port)
        self._write_controller_status(
            "connecting",
            f"Connecting to INDI server {self.indi_host}:{self.indi_port}",
        )
        logger.info(
            "Connecting to INDI server at %s:%s", self.indi_host, self.indi_port
        )

        if not self.client.connectServer():
            self._write_controller_status(
                "server_unavailable",
                f"Could not connect to INDI server {self.indi_host}:{self.indi_port}",
            )
            if announce:
                self._console("INDI server\nnot found")
            return False

        if not self._wait_for_device():
            self._write_controller_status(
                "no_telescope",
                "No telescope/mount device detected",
            )
            if announce:
                self._console("INDI mount\nnot found")
            return False

        assert self.device is not None
        device_name = self.device.getDeviceName()
        logger.info("Using INDI telescope device: %s", device_name)

        if not self.client._wait_for_property(
            self.device,
            "CONNECTION",
            timeout=AUTO_CONNECT_PROPERTY_WAIT_SECONDS,
        ):
            self._write_controller_status(
                "device_connect_failed",
                f"{device_name} CONNECTION property was not available",
            )
            if announce:
                self._console("INDI mount\nconnect failed")
            return False

        if not self._device_is_connected():
            if not self.client.set_switch(
                self.device,
                "CONNECTION",
                "CONNECT",
                timeout=5.0,
            ):
                self._write_controller_status(
                    "device_connect_failed",
                    f"Could not connect {device_name}",
                )
                if announce:
                    self._console("INDI mount\nconnect failed")
                return False
            if not self._wait_for_device_connected(
                AUTO_CONNECT_DEVICE_CONNECT_WAIT_SECONDS
            ):
                self._write_controller_status(
                    "device_connect_failed",
                    f"{device_name} did not enter connected state",
                )
                if announce:
                    self._console("INDI mount\nconnect failed")
                return False

        if not preserve_mount_state:
            if sync_on_connect and not direct_sync_for_onstep:
                self.sync_location_time()
            self.client.unpark_mount(self.device)
            self.client.enable_tracking(self.device)

        telemetry_ok = True
        if require_fresh_telemetry:
            position_generation = self._position_update_generation
            status_generation = self._onstep_status_generation
            telemetry_ok = self._wait_for_fresh_telemetry(
                position_generation,
                status_generation,
                USB_SERIAL_FRESH_TELEMETRY_WAIT_SECONDS,
            )
        else:
            telemetry_ok = (
                self._wait_for_current_position(AUTO_CONNECT_POSITION_WAIT_SECONDS)
                is not None
            )
        if not telemetry_ok:
            self._write_controller_status(
                "device_connect_failed",
                (
                    f"{device_name} did not publish fresh telemetry"
                    if require_fresh_telemetry
                    else f"{device_name} did not publish telescope coordinates"
                ),
            )
            if announce:
                self._console("INDI mount\nconnect failed")
            return False
        self.connected = True
        self._announce_connection_ready()
        self._last_position_status_at = time.monotonic()
        if publish_connected:
            self._write_controller_status(
                "connected",
                f"Connected to {device_name}",
                device=device_name,
            )
        if announce and publish_connected:
            self._console("INDI mount\nconnected")
        return True

    def _announce_connection_ready(self) -> None:
        if not self._connection_announced:
            self._connection_announced = True
            # Startup failures were deliberately hidden; they must not suppress
            # an identical failure after the mount has become operational.
            self.error_notifier.reset()
            self.console_queue.put(
                {"type": "mount_ready", "monotonic": time.monotonic()}
            )

    def mark_disconnected(
        self, message: str, client_generation: Optional[int] = None
    ) -> None:
        if (
            client_generation is not None
            and client_generation != self._client_generation
        ):
            logger.debug(
                "Ignoring disconnect from stale INDI client generation %s",
                client_generation,
            )
            return
        was_connected = self.connected
        self.connected = False
        self.device = None
        self._guide_rate_needs_reassert = True
        self._guide_rate_writable = None
        self._pending_guide_rate = None
        self._confirmed_guide_rates = None
        self._slew_rate_polluted = True
        self._guide_pulse_until = 0.0
        self._coordinate_sync = None
        self._approach_rate_request = None
        if self._guide_manual_approach:
            self._guide_correction_enabled = False
            self._guide_correction_mode = "failed"
        self._cancel_sync_goto("INDI disconnected")
        if was_connected:
            # A connected->disconnected transition is a state change: let the
            # first reconnect attempt of the new outage log in full again.
            # (Disconnect callbacks also fire during each failed retry; those
            # must not reset the counter or suppression never engages.)
            self._auto_connect_failures = 0
        self._write_controller_status("disconnected", message)

    def _configure_usb_serial_monitor(
        self, connection: Optional[dict[str, Any]]
    ) -> None:
        if (
            connection is None
            or connection.get("connection_type") != sys_utils.ONSTEP_CONNECTION_USB
        ):
            self._usb_serial_path = ""
            self._usb_serial_present = None
            self._usb_absent_latched = False
            self._usb_returned_at = None
            self._usb_reconnect_used = False
            self._usb_recovery_snapshot = {}
            self._usb_recovery_status = {
                "connection_health": "not_monitored",
                "serial_present": None,
                "recovery_attempt": 0,
            }
            return

        serial_path = str(connection.get("serial_port", "") or "").strip()
        if not serial_path or serial_path == self._usb_serial_path:
            return

        present = os.path.exists(serial_path)
        self._usb_serial_path = serial_path
        self._usb_serial_present = present
        self._usb_serial_last_check_at = 0.0
        self._usb_absent_latched = False
        self._usb_returned_at = None
        self._usb_reconnect_used = False
        self._usb_recovery_snapshot = {}
        self._usb_recovery_status = {
            "connection_health": "healthy" if present else "usb_absent",
            "serial_present": present,
            "serial_path": serial_path,
            "serial_path_stable": serial_path.startswith("/dev/serial/by-id/"),
            "recovery_attempt": 0,
            "recovery_reason": None,
        }

    def _cached_tracking_enabled(self) -> Optional[bool]:
        track_on = self._device_switch_on("TELESCOPE_TRACK_STATE", "TRACK_ON")
        track_off = self._device_switch_on("TELESCOPE_TRACK_STATE", "TRACK_OFF")
        if track_on is not None:
            return track_on
        if track_off is not None:
            return not track_off
        tracking_text = self._device_text_value("OnStep Status", "Tracking")
        tracking_lower = tracking_text.strip().lower()
        if tracking_lower in {"on", "tracking", "active"}:
            return True
        if tracking_lower in {"off", "idle", "not tracking", "inactive"}:
            return False
        return None

    def _cached_slew_rate(self) -> Optional[int]:
        for rate in range(10):
            if self._device_switch_on("TELESCOPE_SLEW_RATE", str(rate)) is True:
                return rate
        return None

    def _capture_usb_recovery_snapshot(self) -> dict[str, Any]:
        park_state = self._home_park_status_fields().get("park_state", "Unknown")
        return {
            "park_state": park_state,
            "tracking_enabled": self._cached_tracking_enabled(),
            "slew_rate": self.slew_rate,
            "track_freq_hz": self._track_freq_target_hz,
        }

    def _usb_auto_connect_allowed(self) -> bool:
        if not self._usb_serial_path:
            return True
        if self._usb_serial_present is not True:
            return False
        return self._usb_recovery_status.get("connection_health") not in {
            "return_debounce",
            "recovering",
            "recovery_failed",
        }

    def _wait_for_indi_device_disconnected(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        device_name = self._indi_device_name()
        while time.monotonic() < deadline:
            properties = sys_utils.get_indi_onstep_properties(
                server_host=self.indi_host,
                server_port=self.indi_port,
                device_name=device_name,
            )
            if properties.get(f"{device_name}.CONNECTION.CONNECT") == "Off":
                return True
            time.sleep(0.1)
        return False

    def _restore_mount_state_snapshot(
        self, snapshot: dict[str, Any], reason: str
    ) -> bool:
        expected_park = snapshot.get("park_state")
        current_park = self._home_park_status_fields().get("park_state", "Unknown")
        if (
            expected_park in {"Parked", "Unparked"}
            and current_park in {"Parked", "Unparked"}
            and current_park != expected_park
        ):
            logger.error(
                "%s changed park state from %s to %s; refusing "
                "automatic park movement",
                reason,
                expected_park,
                current_park,
            )
            return False

        expected_tracking = snapshot.get("tracking_enabled")
        current_tracking = self._cached_tracking_enabled()
        if (
            expected_tracking is not None
            and current_tracking is not None
            and current_tracking != expected_tracking
        ):
            logger.warning(
                "Restoring tracking state after %s: %s",
                reason,
                "On" if expected_tracking else "Off",
            )
            if not self.set_tracking(bool(expected_tracking)):
                return False

        expected_slew_rate = snapshot.get("slew_rate")
        current_slew_rate = self._cached_slew_rate()
        if (
            expected_slew_rate is not None
            and current_slew_rate is not None
            and current_slew_rate != expected_slew_rate
        ):
            if not self.set_slew_rate(int(expected_slew_rate)):
                return False

        track_freq_hz = snapshot.get("track_freq_hz")
        if track_freq_hz is not None:
            if not self._write_track_frequency(float(track_freq_hz)):
                return False
            self._track_freq_last_assert_at = time.monotonic()
        return True

    def _restore_usb_recovery_snapshot(self) -> bool:
        return self._restore_mount_state_snapshot(
            self._usb_recovery_snapshot, "USB recovery"
        )

    def _recover_usb_serial_once(self) -> bool:
        self._usb_recovery_status.update(
            {
                "connection_health": "recovering",
                "serial_present": True,
                "recovery_reason": "usb_reinsert",
                "recovery_attempt": 1,
            }
        )
        self._write_controller_status(
            "usb_recovering", "USB serial returned; reconnecting INDI device once"
        )
        logger.info("USB serial returned; resetting stale INDI device session once")

        device_name = self._indi_device_name()
        try:
            result = sys_utils.apply_indi_onstep_properties(
                [f"{device_name}.CONNECTION.DISCONNECT=On"],
                server_host=self.indi_host,
                server_port=self.indi_port,
            )
        except Exception as exc:
            error = f"INDI device disconnect request failed: {exc}"
            self._usb_recovery_status["connection_health"] = "recovery_failed"
            self._usb_recovery_status["recovery_error"] = error
            self._write_controller_status("usb_recovery_failed", error)
            logger.exception(error)
            return False
        if not result.get("ok") or not self._wait_for_indi_device_disconnected(
            USB_SERIAL_DISCONNECT_WAIT_SECONDS
        ):
            error = (
                result.get("stderr")
                or result.get("stdout")
                or "INDI device did not enter disconnected state"
            )
            self._usb_recovery_status["connection_health"] = "recovery_failed"
            self._usb_recovery_status["recovery_error"] = error
            self._write_controller_status("usb_recovery_failed", error)
            logger.error("USB serial recovery failed before reconnect: %s", error)
            return False

        self.connected = False
        try:
            connect_ok = self.connect(
                announce=False,
                sync_on_connect=False,
                preserve_mount_state=True,
                require_fresh_telemetry=True,
                publish_connected=False,
            )
        except Exception as exc:
            error = f"INDI device reconnect raised an exception: {exc}"
            self.connected = False
            self._usb_recovery_status["connection_health"] = "recovery_failed"
            self._usb_recovery_status["recovery_error"] = error
            self._write_controller_status("usb_recovery_failed", error)
            logger.exception(error)
            return False
        if not connect_ok:
            error = "INDI device did not reconnect with fresh telemetry"
            self._usb_recovery_status["connection_health"] = "recovery_failed"
            self._usb_recovery_status["recovery_error"] = error
            self._write_controller_status("usb_recovery_failed", error)
            logger.error(error)
            return False

        try:
            state_restored = self._restore_usb_recovery_snapshot()
        except Exception:
            logger.exception("Mount state restore after USB reconnect failed")
            state_restored = False
        if not state_restored:
            error = "Mount state could not be preserved after USB reconnect"
            self.connected = False
            self._usb_recovery_status["connection_health"] = "recovery_failed"
            self._usb_recovery_status["recovery_error"] = error
            self._write_controller_status("usb_recovery_failed", error)
            logger.error(error)
            return False

        self._usb_absent_latched = False
        self._usb_recovery_status.pop("recovery_error", None)
        self._usb_recovery_status["connection_health"] = "healthy"
        self._write_controller_status(
            "connected", "USB serial reconnected with fresh telemetry"
        )
        self._console("INDI USB\nreconnected")
        logger.info("USB serial device session recovered with fresh telemetry")
        return True

    def _check_usb_serial_reinsert(self, now: Optional[float] = None) -> None:
        if not self._usb_serial_path:
            return
        if now is None:
            now = time.monotonic()
        if now - self._usb_serial_last_check_at < USB_SERIAL_MONITOR_INTERVAL_SECONDS:
            return
        self._usb_serial_last_check_at = now

        present = os.path.exists(self._usb_serial_path)
        previous = self._usb_serial_present
        self._usb_serial_present = present
        self._usb_recovery_status["serial_present"] = present

        if previous is True and not present:
            self._usb_recovery_snapshot = self._capture_usb_recovery_snapshot()
            self._usb_absent_latched = True
            self._usb_returned_at = None
            self._usb_reconnect_used = False
            self.connected = False
            self._coordinate_sync = None
            self._auto_connect_failures = 0
            self._usb_recovery_status.update(
                {
                    "connection_health": "usb_absent",
                    "recovery_reason": "usb_reinsert",
                    "recovery_attempt": 0,
                }
            )
            self._usb_recovery_status.pop("recovery_error", None)
            self._write_controller_status(
                "usb_absent", "Configured USB serial device was removed"
            )
            logger.warning(
                "Configured USB serial device removed: %s", self._usb_serial_path
            )
            return

        if not present:
            self._usb_returned_at = None
            return

        if previous is False and not self._usb_absent_latched:
            self._usb_recovery_status["connection_health"] = "healthy"
            logger.info("USB serial device is present: %s", self._usb_serial_path)
            return

        if not self._usb_absent_latched or self._usb_reconnect_used:
            return

        if self._usb_returned_at is None:
            self._usb_returned_at = now
            self._usb_recovery_status["connection_health"] = "return_debounce"
            self._write_controller_status(
                "usb_return_debounce",
                "USB serial returned; waiting for stable device node",
            )
            logger.info(
                "USB serial device returned; waiting %.1f s for stability",
                USB_SERIAL_RETURN_DEBOUNCE_SECONDS,
            )
            return

        if now - self._usb_returned_at < USB_SERIAL_RETURN_DEBOUNCE_SECONDS:
            return

        self._usb_reconnect_used = True
        self._recover_usb_serial_once()

    @contextmanager
    def _quiet_retry_logging(self, quiet: bool):
        """Silence WARNING/INFO chatter for a repeated auto-reconnect attempt.

        The first attempt after a state change logs normally; while `quiet`,
        the mount-control loggers only pass ERROR and above, so an offline
        mount does not write the same timeout batch every retry."""
        if not quiet:
            yield
            return
        targets = (logger, clientlogger)
        previous = [target.level for target in targets]
        for target in targets:
            target.setLevel(logging.ERROR)
        try:
            yield
        finally:
            for target, level in zip(targets, previous):
                target.setLevel(level)

    def restart_driver(self) -> bool:
        logger.info("Restarting INDI Web Manager, server, and mount driver")
        self._write_controller_status("restarting", "Restarting INDI server/driver")
        self._console("INDI server\nrestarting")
        self.disconnect()
        self.client = None
        self.device = None
        try:
            result = sys_utils.restart_indi_web_manager(timeout=30)
            if not result["ok"]:
                error = (
                    result.get("stderr")
                    or result.get("stdout")
                    or "Could not restart INDI Web Manager"
                )
                logger.error("Could not restart INDI Web Manager: %s", error)
                self._write_controller_status("restart_failed", error)
                self._console("INDI restart\nfailed")
                return False
        except RuntimeError as exc:
            logger.error("Could not restart INDI Web Manager: %s", exc)
            self._write_controller_status("restart_failed", str(exc))
            self._console("INDI restart\nfailed")
            return False

        time.sleep(3.0)
        connect_result = sys_utils.connect_indi_onstep_driver(
            server_host=self.indi_host,
            server_port=self.indi_port,
            device_name=sys_utils.get_indi_profile_device_name(),
            wait_timeout=15,
        )
        if not connect_result["ok"]:
            error = (
                connect_result.get("stderr")
                or connect_result.get("stdout")
                or "Could not connect INDI OnStep driver"
            )
            logger.error(
                "Could not connect INDI OnStep driver after restart: %s", error
            )
            self._write_controller_status("device_connect_failed", error)
            self._console("INDI connect\nfailed")
            return False
        return self.connect()

    def reboot_mount(self) -> bool:
        """Force-reboot the OnStep controller and reinitialize the mount.

        Verified recovery for the wedged OnStepX state (sync/GoTo/tracking
        refused while manual moves work) and for a controller that silently
        rebooted and lost date/time. ``:ERESET#`` drops the controller for
        ~35s; the follow-up ``connect()`` re-runs location/time sync, unpark,
        and tracking enable so GoTo works again without a full restart.
        """
        if not self._initial_site_recovering:
            self._initial_site_failed = False
            self._initial_site_complete = False
        onstep_cfg = self._onstep_connection_config()
        logger.info("Rebooting OnStep mount controller via :ERESET#")
        self._write_controller_status("rebooting", "Rebooting OnStep mount controller")
        self._console("INDI mount\nrebooting")
        self.disconnect()
        self.client = None
        self.device = None
        try:
            result = sys_utils.reboot_onstep_controller_exclusive(
                connection_type=onstep_cfg["connection_type"],
                network_host=onstep_cfg["network_host"],
                network_port=onstep_cfg["network_port"],
                serial_port=onstep_cfg["serial_port"],
                serial_baud=onstep_cfg.get("serial_baud", 9600),
                server_host=self.indi_host,
                server_port=self.indi_port,
            )
        except Exception as exc:
            logger.exception("OnStep controller reboot failed")
            self._write_controller_status("reboot_failed", str(exc))
            self._console("INDI reboot\nfailed")
            return False

        if not result.get("ok"):
            error = (
                result.get("stderr")
                or result.get("stdout")
                or "Could not reboot OnStep controller"
            )
            logger.error("OnStep controller reboot failed: %s", error)
            self._write_controller_status("reboot_failed", error)
            self._console("INDI reboot\nfailed")
            return False

        # The controller boots without date/time (no RTC); connect() re-runs
        # location/time sync, unpark, and tracking enable.
        if not self.connect(announce=False):
            self._write_controller_status(
                "reboot_failed", "Mount did not reconnect after reboot"
            )
            self._console("INDI reboot\nno reconnect")
            return False

        logger.info("OnStep controller rebooted and mount reinitialized")
        self._write_controller_status(
            "connected", "OnStep controller rebooted and reinitialized"
        )
        self._console("INDI mount\nrebooted")
        return True

    def disconnect(self) -> None:
        if self.client is not None:
            try:
                self.client.disconnectServer()
            except Exception:
                logger.exception("Could not disconnect from INDI server")
        self.connected = False
        self._write_controller_status("stopped", "Mount-control process stopped")

    def _stored_onstep_connection_config(
        self, cfg: config.Config
    ) -> Optional[dict[str, Any]]:
        return sys_utils.normalize_onstep_connection_config(
            {
                "connection_type": cfg.get_stored_option("onstep_connection_type", ""),
                "serial_port": cfg.get_stored_option("onstep_serial_port", ""),
                "serial_baud": cfg.get_stored_option(
                    "onstep_serial_baud", sys_utils.DEFAULT_ONSTEP_SERIAL_BAUD
                ),
                "network_host": cfg.get_stored_option("onstep_network_host", ""),
                "network_port": cfg.get_stored_option(
                    "onstep_network_port", sys_utils.DEFAULT_ONSTEP_NETWORK_PORT
                ),
            },
            source="pifinder",
        )

    def _connection_config_status_fields(
        self,
        connection: Optional[dict[str, Any]],
        *,
        valid: bool,
        reconciled: bool = False,
        error: str = "",
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "connection_config_valid": valid,
            "connection_config_reconciled": reconciled,
        }
        if connection is not None:
            fields.update(
                {
                    "connection_config_source": connection.get("source", ""),
                    "onstep_connection_type": connection["connection_type"],
                }
            )
            if connection["connection_type"] == sys_utils.ONSTEP_CONNECTION_USB:
                fields["onstep_serial_port"] = connection["serial_port"]
                fields["onstep_serial_baud"] = connection["serial_baud"]
            else:
                fields["onstep_network_host"] = connection["network_host"]
                fields["onstep_network_port"] = connection["network_port"]
        if error:
            fields["connection_config_error"] = error
        return fields

    def reconcile_onstep_connection_config(
        self, allow_fallback_apply: bool = True
    ) -> bool:
        """Make MFNavis's transport mirror match the effective INDI settings."""
        device_name = sys_utils.get_indi_profile_device_name()
        if not sys_utils.is_onstep_family_device_name(device_name):
            self._configure_usb_serial_monitor(None)
            self._connection_config_status = {
                "connection_config_valid": True,
                "connection_config_source": "not_onstep",
            }
            self._connection_config_ready = True
            return True

        cfg = config.Config()
        cfg.load_config()
        mirror = self._stored_onstep_connection_config(cfg)
        live_properties = sys_utils.get_indi_onstep_properties(
            server_host=self.indi_host,
            server_port=self.indi_port,
            device_name=device_name,
        )
        live = sys_utils.parse_indi_onstep_connection_properties(
            live_properties, device_name=device_name
        )
        saved = sys_utils.read_saved_indi_onstep_connection_config(
            device_name=device_name
        )
        effective = live or saved

        if effective is None and mirror is not None and allow_fallback_apply:
            logger.warning(
                "No valid INDI OnStep transport settings; applying the verified "
                "MFNavis mirror once"
            )
            result = sys_utils.apply_indi_onstep_connection(
                connection_type=mirror["connection_type"],
                serial_port=mirror["serial_port"],
                serial_baud=mirror["serial_baud"],
                network_host=mirror["network_host"],
                network_port=mirror["network_port"],
                server_host=self.indi_host,
                server_port=self.indi_port,
                device_name=device_name,
            )
            if result.get("ok"):
                verified_properties = sys_utils.get_indi_onstep_properties(
                    server_host=self.indi_host,
                    server_port=self.indi_port,
                    device_name=device_name,
                )
                verified = sys_utils.parse_indi_onstep_connection_properties(
                    verified_properties, device_name=device_name
                )
                if sys_utils.onstep_connection_configs_match(verified, mirror):
                    effective = verified

        if effective is None:
            error = "No complete INDI or MFNavis OnStep connection configuration"
            logger.error(error)
            self._connection_config_status = self._connection_config_status_fields(
                mirror, valid=False, error=error
            )
            self._connection_config_ready = False
            self._configure_usb_serial_monitor(mirror)
            self._write_controller_status("config_invalid", error)
            return False

        mirror_options = sys_utils.onstep_connection_mirror_options(effective)
        mirror_options.update(
            {
                "mount_control_indi_host": self.indi_host,
                "mount_control_indi_port": self.indi_port,
            }
        )
        changed_options = {
            key: value
            for key, value in mirror_options.items()
            if cfg.get_stored_option(key) != value
        }
        if changed_options:
            cfg.set_options(changed_options)
            logger.info(
                "Reconciled MFNavis OnStep connection mirror from %s",
                effective.get("source", "INDI"),
            )

        self._connection_config_status = self._connection_config_status_fields(
            effective,
            valid=True,
            reconciled=bool(changed_options),
        )
        self._configure_usb_serial_monitor(effective)
        self._connection_config_ready = True
        return True

    def update_connection_config(self, server_host: Any, server_port: Any) -> bool:
        """Adopt Web-saved INDI endpoint values without restarting PiFinder."""
        host = str(server_host or "localhost").strip() or "localhost"
        try:
            port = int(server_port)
        except (TypeError, ValueError):
            return False
        if not 1 <= port <= 65535:
            return False

        endpoint_changed = host != self.indi_host or port != self.indi_port
        if endpoint_changed and self.client is not None:
            try:
                self.client.disconnectServer()
            except Exception:
                logger.debug("Could not close old INDI endpoint", exc_info=True)
            self.client = None
            self.device = None
            self.connected = False
        self.indi_host = host
        self.indi_port = port
        return self.reconcile_onstep_connection_config(allow_fallback_apply=False)

    def _serial_discovery_busy_reason(self) -> str:
        if self._serial_discovery_active:
            return "Serial discovery is already running"
        if self._manual_motion_direction is not None:
            return "Manual mount movement is active"
        if self._goto_motion is not None or self._pending_goto_refine is not None:
            return "GoTo or GoTo refinement is active"
        if self._guide_correction_enabled:
            return "Tracking guide correction is active"
        if self._backlash_auto is not None and str(
            self._backlash_auto.get("state", "")
        ).lower() not in {"", "idle", "complete", "failed", "stopped"}:
            return "Backlash calibration is active"
        if self._multipoint_align_controller.active_session() is not None:
            return "Multi-point alignment is active"
        if self._home_park_status_fields().get("park_state") == "Parking":
            return "Mount parking is active"
        if self._usb_recovery_status.get("connection_health") in {
            "return_debounce",
            "recovering",
        }:
            return "USB serial recovery is active"
        return ""

    def _publish_serial_discovery(self, state: str, message: str, **extra: Any) -> None:
        status = {
            "serial_discovery_state": state,
            "serial_discovery_message": message,
        }
        for key, value in extra.items():
            status[f"serial_discovery_{key}"] = value
        self._serial_discovery_status = status
        self._write_controller_status(f"serial_discovery_{state}", message)

    def _serial_discovery_scan_status(self, scan_status: dict[str, Any]) -> None:
        self._publish_serial_discovery(
            "scanning",
            "Searching attached serial devices for OnStep",
            candidate_count=scan_status.get("candidate_count", 0),
            verified_count=scan_status.get("verified_count", 0),
            current_port=scan_status.get("current_port", ""),
            current_baud=scan_status.get("current_baud", ""),
        )

    def _disconnect_indi_device_for_serial_discovery(self) -> bool:
        device_name = self._indi_device_name()
        result = sys_utils.apply_indi_onstep_properties(
            [f"{device_name}.CONNECTION.DISCONNECT=On"],
            server_host=self.indi_host,
            server_port=self.indi_port,
        )
        if not result.get("ok"):
            return False
        if not self._wait_for_indi_device_disconnected(
            USB_SERIAL_DISCONNECT_WAIT_SECONDS
        ):
            return False
        self.connected = False
        return True

    def _verify_serial_discovery_telemetry(
        self,
        telemetry_baseline: tuple[int, int],
        expected_connection: dict[str, Any],
    ) -> bool:
        """Verify the new driver session through callbacks or live INDI readback."""
        client = self.client
        client_ready = False
        if client is not None and self.device is not None:
            try:
                client_ready = bool(client.isServerConnected())
            except Exception:
                client_ready = False
        if not client_ready:
            if not self.connect(
                announce=False,
                sync_on_connect=False,
                preserve_mount_state=True,
                require_fresh_telemetry=False,
                publish_connected=False,
            ):
                return False
        if not self._wait_for_device_connected(
            AUTO_CONNECT_DEVICE_CONNECT_WAIT_SECONDS
        ):
            return False
        deadline = time.monotonic() + USB_SERIAL_FRESH_TELEMETRY_WAIT_SECONDS
        device_name = self._indi_device_name()
        while time.monotonic() < deadline:
            if (
                self._position_update_generation > telemetry_baseline[0]
                and self._onstep_status_generation > telemetry_baseline[1]
            ):
                break

            properties = sys_utils.get_indi_onstep_properties(
                server_host=self.indi_host,
                server_port=self.indi_port,
                device_name=device_name,
            )
            live_connection = sys_utils.parse_indi_onstep_connection_properties(
                properties, device_name=device_name
            )
            ra = properties.get(f"{device_name}.EQUATORIAL_EOD_COORD.RA", "")
            dec = properties.get(f"{device_name}.EQUATORIAL_EOD_COORD.DEC", "")
            raw_status = properties.get(f"{device_name}.OnStep Status.:GU# return", "")
            try:
                position_valid = math.isfinite(float(ra)) and math.isfinite(float(dec))
            except (TypeError, ValueError):
                position_valid = False
            if (
                properties.get(f"{device_name}.CONNECTION.CONNECT") == "On"
                and sys_utils.onstep_connection_configs_match(
                    live_connection, expected_connection
                )
                and position_valid
                and str(raw_status).strip()
            ):
                logger.info(
                    "Verified serial discovery from live INDI readback; "
                    "PyIndi callback generation was not available"
                )
                break
            time.sleep(0.5)
        else:
            return False
        self.connected = True
        self._last_position_status_at = time.monotonic()
        return True

    def _rollback_serial_discovery(
        self,
        previous_connection: Optional[dict[str, Any]],
        was_connected: bool,
        mount_snapshot: dict[str, Any],
    ) -> bool:
        """Restore the pre-discovery live transport without changing saved XML."""
        if previous_connection is None:
            try:
                self._disconnect_indi_device_for_serial_discovery()
            except Exception:
                logger.exception("Could not leave INDI disconnected after discovery")
            self._configure_usb_serial_monitor(None)
            return True

        device_name = self._indi_device_name()
        try:
            telemetry_baseline = (
                self._position_update_generation,
                self._onstep_status_generation,
            )
            result = sys_utils.apply_indi_onstep_connection(
                connection_type=previous_connection["connection_type"],
                serial_port=previous_connection.get("serial_port", ""),
                serial_baud=previous_connection.get(
                    "serial_baud", sys_utils.DEFAULT_ONSTEP_SERIAL_BAUD
                ),
                network_host=previous_connection.get("network_host", ""),
                network_port=previous_connection.get(
                    "network_port", sys_utils.DEFAULT_ONSTEP_NETWORK_PORT
                ),
                server_host=self.indi_host,
                server_port=self.indi_port,
                device_name=device_name,
                save_config=False,
            )
            if not result.get("ok"):
                return False

            self.connected = False
            if was_connected:
                if not self._verify_serial_discovery_telemetry(
                    telemetry_baseline, previous_connection
                ):
                    return False
                if not self._restore_mount_state_snapshot(
                    mount_snapshot, "serial discovery rollback"
                ):
                    return False
            else:
                disconnect_result = sys_utils.apply_indi_onstep_properties(
                    [f"{device_name}.CONNECTION.DISCONNECT=On"],
                    server_host=self.indi_host,
                    server_port=self.indi_port,
                )
                if not disconnect_result.get("ok"):
                    return False
                self.connected = False

            self._connection_config_status = self._connection_config_status_fields(
                previous_connection, valid=True
            )
            self._configure_usb_serial_monitor(previous_connection)
            self._connection_config_ready = True
            return True
        except Exception:
            logger.exception("Could not restore pre-discovery INDI connection")
            return False

    def discover_onstep_serial_connection(self) -> bool:
        """Find one local OnStep serial port/baud and persist it after verification."""
        busy_reason = self._serial_discovery_busy_reason()
        if busy_reason:
            self._publish_serial_discovery("failed", busy_reason, error=busy_reason)
            return False
        if not sys_utils.is_local_indi_server_host(self.indi_host):
            error = "Serial discovery requires a local INDI server"
            self._publish_serial_discovery("failed", error, error=error)
            return False
        device_name = self._indi_device_name()
        if not sys_utils.is_onstep_family_device_name(device_name):
            error = "The active INDI driver is not an OnStep driver"
            self._publish_serial_discovery("failed", error, error=error)
            return False

        cfg = config.Config()
        cfg.load_config()
        mirror = self._stored_onstep_connection_config(cfg)
        live_properties = sys_utils.get_indi_onstep_properties(
            server_host=self.indi_host,
            server_port=self.indi_port,
            device_name=device_name,
        )
        live = sys_utils.parse_indi_onstep_connection_properties(
            live_properties, device_name=device_name
        )
        saved = sys_utils.read_saved_indi_onstep_connection_config(
            device_name=device_name
        )
        previous_connection = live or saved or mirror
        was_connected = (
            live_properties.get(f"{device_name}.CONNECTION.CONNECT") == "On"
            or self.connected
        )
        mount_snapshot = self._capture_usb_recovery_snapshot()

        gps_port = str(
            cfg.get_option("gps_port", getattr(sys_utils, "DEFAULT_GPSD_DEVICE", ""))
            or ""
        ).strip()
        candidates = sys_utils.list_onstep_serial_ports(
            excluded_paths=[gps_port] if gps_port else None
        )
        if not candidates:
            error = "No eligible local USB serial ports were found"
            self._publish_serial_discovery("failed", error, error=error)
            return False

        preferred_bauds = []
        for connection in (live, saved, mirror):
            if connection is not None:
                preferred_bauds.append(connection.get("serial_baud"))

        self._serial_discovery_active = True
        self._publish_serial_discovery(
            "precheck",
            "Preparing one-time OnStep serial discovery",
            candidate_count=len(candidates),
        )
        failure = ""
        discovery: dict[str, Any] = {}
        try:
            self._publish_serial_discovery(
                "disconnecting",
                "Disconnecting the INDI device for exclusive serial probing",
                candidate_count=len(candidates),
            )
            if not self._disconnect_indi_device_for_serial_discovery():
                failure = "INDI device did not disconnect for serial discovery"
                raise RuntimeError(failure)

            discovery = sys_utils.discover_onstep_serial(
                preferred_bauds=preferred_bauds,
                ports=candidates,
                status_callback=self._serial_discovery_scan_status,
            )
            if not discovery.get("ok"):
                state = discovery.get("state", "not_found")
                if state == "ambiguous":
                    failure = "Multiple verified OnStep serial devices were found"
                elif state == "timeout":
                    failure = "OnStep serial discovery timed out"
                else:
                    failure = "No verified OnStep serial device was found"
                raise RuntimeError(failure)

            selected = discovery["selected"]
            selected_port = str(selected["stable_path"])
            selected_baud = int(selected["baud"])
            telemetry_baseline = (
                self._position_update_generation,
                self._onstep_status_generation,
            )
            self._publish_serial_discovery(
                "applying",
                "Applying the verified OnStep serial connection",
                selected_port=selected_port,
                selected_baud=selected_baud,
                product=selected.get("product", ""),
                version=selected.get("version", ""),
                candidate_count=discovery.get("candidate_count", 0),
                verified_count=discovery.get("verified_count", 0),
            )
            apply_result = sys_utils.apply_indi_onstep_connection(
                connection_type=sys_utils.ONSTEP_CONNECTION_USB,
                serial_port=selected_port,
                serial_baud=selected_baud,
                server_host=self.indi_host,
                server_port=self.indi_port,
                device_name=device_name,
                save_config=False,
            )
            if not apply_result.get("ok"):
                failure = (
                    apply_result.get("stderr")
                    or apply_result.get("stdout")
                    or "Could not apply the discovered serial connection"
                )
                raise RuntimeError(failure)

            selected_connection = sys_utils.normalize_onstep_connection_config(
                {
                    "connection_type": sys_utils.ONSTEP_CONNECTION_USB,
                    "serial_port": selected_port,
                    "serial_baud": selected_baud,
                    "verified": True,
                },
                source="serial_discovery",
            )
            assert selected_connection is not None

            self._publish_serial_discovery(
                "verifying",
                "Waiting for fresh OnStep position and status telemetry",
                selected_port=selected_port,
                selected_baud=selected_baud,
                product=selected.get("product", ""),
                version=selected.get("version", ""),
            )
            self.connected = False
            if not self._verify_serial_discovery_telemetry(
                telemetry_baseline, selected_connection
            ):
                failure = "Discovered OnStep did not publish fresh telemetry"
                raise RuntimeError(failure)
            if not self._restore_mount_state_snapshot(
                mount_snapshot, "serial discovery"
            ):
                failure = "Mount state changed during serial discovery"
                raise RuntimeError(failure)

            save_result = sys_utils.apply_indi_onstep_properties(
                [f"{device_name}.CONFIG_PROCESS.CONFIG_SAVE=On"],
                server_host=self.indi_host,
                server_port=self.indi_port,
            )
            if not save_result.get("ok"):
                failure = (
                    save_result.get("stderr")
                    or save_result.get("stdout")
                    or "INDI CONFIG_SAVE failed after discovery"
                )
                raise RuntimeError(failure)

            mirror_options = sys_utils.onstep_connection_mirror_options(
                selected_connection
            )
            mirror_options.update(
                {
                    "mount_control_indi_host": self.indi_host,
                    "mount_control_indi_port": self.indi_port,
                }
            )
            cfg.set_options(mirror_options)
            self._connection_config_status = self._connection_config_status_fields(
                selected_connection, valid=True, reconciled=True
            )
            self._configure_usb_serial_monitor(selected_connection)
            self._connection_config_ready = True
            self._publish_serial_discovery(
                "success",
                f"Found {selected_port} at {selected_baud} baud",
                selected_port=selected_port,
                selected_baud=selected_baud,
                product=selected.get("product", ""),
                version=selected.get("version", ""),
                candidate_count=discovery.get("candidate_count", 0),
                verified_count=discovery.get("verified_count", 0),
            )
            self._console("INDI serial\nfound")
            logger.info(
                "OnStep serial discovery selected %s at %s baud",
                selected_port,
                selected_baud,
            )
            return True
        except Exception as exc:
            if not failure:
                failure = str(exc) or "OnStep serial discovery failed"
            logger.warning("OnStep serial discovery failed: %s", failure)
            rollback_ok = self._rollback_serial_discovery(
                previous_connection, was_connected, mount_snapshot
            )
            if not rollback_ok:
                failure = f"{failure}; previous connection rollback failed"
            self._publish_serial_discovery(
                "failed",
                failure,
                error=failure,
                candidate_count=discovery.get("candidate_count", len(candidates)),
                verified_count=discovery.get("verified_count", 0),
                rollback_ok=rollback_ok,
            )
            self._console("INDI serial\nnot found")
            return False
        finally:
            self._serial_discovery_active = False

    def _onstep_connection_config(self) -> dict[str, Any]:
        cfg = config.Config()
        cfg.load_config()
        direct_sync = cfg.get_option("onstep_direct_lx200_location_time_sync", False)
        if isinstance(direct_sync, str):
            direct_sync = direct_sync.strip().lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        return {
            "connection_type": cfg.get_option("onstep_connection_type", "network"),
            "network_host": cfg.get_option("onstep_network_host", ""),
            "network_port": int(cfg.get_option("onstep_network_port", 9999)),
            "serial_port": cfg.get_option("onstep_serial_port", ""),
            "serial_baud": int(cfg.get_option("onstep_serial_baud", 9600)),
            "direct_location_time_sync": bool(direct_sync),
        }

    def _use_direct_onstep_location_time_sync(self) -> bool:
        try:
            if self.device is not None:
                device_name = self.device.getDeviceName()
                if not sys_utils.is_onstep_family_device_name(device_name):
                    return False
            return bool(self._onstep_connection_config()["direct_location_time_sync"])
        except Exception:
            logger.exception("Could not read OnStep direct-sync configuration")
            return False

    def _manual_datetime_active(self) -> bool:
        try:
            return bool(self.shared_state.datetime_is_manual())
        except Exception:
            return False

    def _shared_location_time_values(
        self, include_default_location: bool = False
    ) -> tuple[Optional[float], Optional[float], Optional[float], Any]:
        latitude = longitude = elevation = None
        try:
            location = self.shared_state.location()
        except Exception:
            location = None

        if location and location.lock:
            latitude = float(location.lat)
            longitude = float(location.lon)
            elevation = None if location.altitude is None else float(location.altitude)
        elif include_default_location:
            try:
                cfg = config.Config()
                cfg.load_config()
                default_location = cfg.locations.default_location
                if default_location:
                    latitude = float(default_location.latitude)
                    longitude = float(default_location.longitude)
                    elevation = float(default_location.height)
            except Exception:
                logger.debug("Could not load default location fallback", exc_info=True)

        try:
            dt = self.shared_state.datetime()
        except Exception:
            dt = None
        if dt is None:
            dt = datetime.now(timezone.utc)

        return latitude, longitude, elevation, dt

    def _sync_location_time_direct_onstep(
        self,
        latitude: float,
        longitude: float,
        elevation: float | None,
        dt: Any,
        reconnect_after: bool,
    ) -> bool:
        onstep_cfg = self._onstep_connection_config()
        was_connected = self.connected or (
            self.client is not None and self.client.isServerConnected()
        )

        if self.client is not None:
            self.disconnect()
            self.client = None
            self.device = None

        self._write_controller_status(
            "syncing",
            "Sending location/time via direct LX200 OnStep commands",
        )
        try:
            result = sys_utils.sync_onstep_location_time_exclusive(
                connection_type=onstep_cfg["connection_type"],
                latitude=latitude,
                longitude=longitude,
                elevation=elevation,
                utc_datetime=dt,
                network_host=onstep_cfg["network_host"],
                network_port=onstep_cfg["network_port"],
                serial_port=onstep_cfg["serial_port"],
                serial_baud=onstep_cfg.get("serial_baud", 9600),
                server_host=self.indi_host,
                server_port=self.indi_port,
            )
        except Exception as exc:
            logger.exception("Direct LX200 OnStep location/time sync failed")
            self._write_controller_status("sync_failed", str(exc))
            return False

        if not result.get("ok"):
            error = (
                result.get("stderr")
                or result.get("stdout")
                or "Direct LX200 OnStep sync failed"
            )
            logger.warning("Direct LX200 OnStep location/time sync failed: %s", error)
            self._write_controller_status("sync_failed", error)
            return False

        sys_utils.write_onstep_location_cache(latitude, longitude, elevation, dt)
        self._write_controller_status(
            "connected" if was_connected else "idle",
            "Location/time sent via direct LX200 OnStep commands"
            + (
                " (provisional clock, awaiting GPS/NTP)"
                if self._time_sync_provisional
                else ""
            ),
        )

        if reconnect_after and was_connected:
            return self.connect(announce=False, sync_on_connect=False)
        return True

    def sync_location_time(
        self,
        reconnect_after: bool = True,
        include_default_location: bool = False,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        elevation: Optional[float] = None,
    ) -> bool:
        # Keep the explicit Location selection across the reset; shared_state
        # may still be processing the web/GPS location update.
        if self._initial_site_recovering and self._initial_site_request:
            latitude = self._initial_site_request["latitude"]
            longitude = self._initial_site_request["longitude"]
            elevation = self._initial_site_request["elevation"]
        try:
            lat, lon, alt, dt = self._shared_location_time_values(
                include_default_location
            )
            request = {
                "latitude": lat if latitude is None else latitude,
                "longitude": lon if longitude is None else longitude,
                "elevation": alt if elevation is None else elevation,
            }
            initial = (
                not self._initial_site_complete
                and not self._initial_site_failed
                and request["latitude"] is not None
                and request["longitude"] is not None
                and dt is not None
                and sys_utils.is_onstep_family_device_name(self._indi_device_name())
            )
        except Exception:
            initial = False
        if initial:
            self._initial_site_request = request
            self._initial_site_expected_time = dt
            self._initial_site_sent_connected = self._device_is_connected()
            with self._sync_property_lock:
                self._initial_site_after_sequence = self._sync_property_sequence
            self._initial_site_deadline = time.monotonic() + 8.0
        ok = self._sync_location_time_once(
            reconnect_after, include_default_location, latitude, longitude, elevation
        )
        if initial:
            self._initial_site_write_ok = ok
        return ok

    def _check_initial_location_sync(self) -> None:
        if (
            not self.connected
            or self._initial_site_request is None
            or self._initial_site_complete
            or self._initial_site_failed
            or self._initial_site_recovering
            or self._manual_motion_direction is not None
            or self._goto_motion is not None
            or self._pending_sync_goto is not None
            or self._pending_goto_refine is not None
        ):
            return
        if not self._initial_site_sent_connected:
            self.sync_location_time(**self._initial_site_request)
            return
        reason = self._initial_location_ack_failure()
        if reason is None:  # Still waiting for fresh server callbacks.
            return
        if not reason:
            # OnStep can accept site/time writes while refusing tracking. A
            # successful send is not proof the controller is operational.
            if self.client is not None and self.device is not None:
                if self.client.unpark_mount(self.device) and self.set_tracking(True):
                    self._initial_site_complete = True
                    self._write_controller_status(
                        "connected", "Initial location/time and tracking verified"
                    )
                    return
            reason = "Tracking did not start after initial location/time sync"
        self._recover_initial_location_sync(reason)

    def _initial_location_ack_failure(self) -> Optional[str]:
        if not self._initial_site_write_ok:
            return "Initial location/time command failed"
        # The direct LX200 helper already checks its command replies, and
        # reconnecting replaces the INDI client/receipt generation.
        if self._use_direct_onstep_location_time_sync():
            return ""
        with self._sync_property_lock:
            receipts = [
                self._sync_property_receipts.get(n)
                for n in ("GEOGRAPHIC_COORD", "TIME_UTC")
            ]
        fresh = [
            r
            for r in receipts
            if r and r["sequence"] > self._initial_site_after_sequence
        ]
        if any(r["state"] == "alert" for r in fresh):
            return "Driver rejected initial location/time sync"
        if len(fresh) == 2 and all(r["state"] in {"idle", "ok"} for r in fresh):
            try:
                site, clock = fresh[0]["values"], fresh[1]["values"]
                expected = self._initial_site_request or {}
                delta_lon = (
                    float(site["LONG"]) - float(expected["longitude"]) + 180
                ) % 360 - 180
                delta_time = abs(
                    (
                        sys_utils.parse_indi_utc_datetime(clock["UTC"])
                        - sys_utils.parse_indi_utc_datetime(
                            self._initial_site_expected_time
                        )
                    ).total_seconds()
                )
                if (
                    abs(float(site["LAT"]) - float(expected["latitude"])) < 0.001
                    and abs(delta_lon) < 0.001
                    and delta_time < 10
                ):
                    return ""
            except (KeyError, TypeError, ValueError):
                pass
        if time.monotonic() >= self._initial_site_deadline:
            return "Timeout confirming initial location/time sync"
        return None

    def _recover_initial_location_sync(self, reason: str) -> None:
        if self._initial_site_reset_attempted:
            self._initial_site_failed = True
            self._write_controller_status(
                "initialization_failed",
                f"Automatic INDI reset did not recover initialization: {reason}",
            )
            return
        self._initial_site_reset_attempted = True
        self._initial_site_recovering = True
        self._write_controller_status(
            "initialization_reset",
            f"Initial location sync stalled; automatically resetting INDI: {reason}",
        )
        self._console("INDI init\nauto reset")
        try:
            ok = self.reboot_mount()
        except Exception:
            logger.exception("Automatic initial location recovery failed")
            ok = False
        finally:
            self._initial_site_recovering = False
        if not ok:
            self._initial_site_failed = True
            self._write_controller_status(
                "initialization_failed",
                "Automatic INDI reset failed; check mount connection and power",
            )

    def _sync_location_time_once(
        self,
        reconnect_after: bool = True,
        include_default_location: bool = False,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        elevation: Optional[float] = None,
    ) -> bool:
        try:
            # A4 clock-trust gate, softened (2026-08-08): an untrusted clock
            # (stale fake-hwclock restore, field session before GPS/NTP sync)
            # no longer blocks the send -- a mount with NO time refuses every
            # slew, which strands a field session that only needs to reach a
            # solvable patch of sky. The provisional time is recoverable: the
            # A5 hook re-sends site/time (and drops the tracking target) as
            # soon as the clock steps or becomes trusted, and the PiFinder
            # GoTo method re-anchors the mount frame from plate solves.
            # Multi-point alignment still requires a trusted clock (its model
            # would be built on the wrong LST) -- see
            # _sync_multipoint_location_time. A user-set manual time counts
            # as trusted: the value sent below is shared_state.datetime(),
            # which carries exactly that manual time.
            self._time_sync_provisional = not self._manual_datetime_active() and (
                not gps_time_sync.clock_is_trusted(check_chrony=True)
            )
            if self._time_sync_provisional:
                logger.warning(
                    "System clock is not synchronized (GPS/NTP) yet; sending "
                    "provisional MFNavis time to the mount so it can slew. "
                    "Site/time is re-sent automatically once the clock is "
                    "trusted"
                )

            shared_latitude, shared_longitude, shared_elevation, dt = (
                self._shared_location_time_values(
                    include_default_location=include_default_location
                )
            )
            # A web Location "Load" is an explicit observer action. Its GPS
            # queue update reaches shared_state asynchronously, so accept the
            # selected coordinates with this command rather than re-sending
            # the previous location or waiting for the GPS jitter debounce.
            if latitude is None:
                latitude = shared_latitude
            if longitude is None:
                longitude = shared_longitude
            if elevation is None:
                elevation = shared_elevation
            if self._use_direct_onstep_location_time_sync():
                if latitude is None or longitude is None:
                    self._write_controller_status(
                        "connected" if self.connected else "idle",
                        "No locked location available for direct OnStep sync",
                    )
                    return False
                return self._sync_location_time_direct_onstep(
                    latitude,
                    longitude,
                    elevation,
                    dt,
                    reconnect_after=reconnect_after,
                )

            if latitude is None and longitude is None and dt is None:
                self._write_controller_status(
                    "connected" if self.connected else "idle",
                    "No locked location/time available",
                )
                return False

            try:
                result = sys_utils.apply_indi_onstep_location_time(
                    latitude=latitude,
                    longitude=longitude,
                    elevation=elevation,
                    utc_datetime=dt,
                    server_host=self.indi_host,
                    server_port=self.indi_port,
                    device_name=self._indi_device_name(),
                )
            except Exception as exc:
                logger.exception("INDI location/time sync failed")
                self._write_controller_status("sync_failed", str(exc))
                return False

            if not result.get("ok"):
                error = (
                    result.get("stderr")
                    or result.get("stdout")
                    or "INDI location/time sync failed"
                )
                logger.warning("INDI location/time sync failed: %s", error)
                self._write_controller_status("sync_failed", error)
                return False

            self._write_controller_status(
                "connected" if self.connected else "idle",
                "Location/time sent via INDI"
                + (
                    " (provisional clock, awaiting GPS/NTP)"
                    if self._time_sync_provisional
                    else ""
                ),
            )
            if latitude is not None and longitude is not None:
                sys_utils.write_onstep_location_cache(
                    latitude,
                    longitude,
                    elevation,
                    dt,
                )
            return True
        except Exception:
            logger.exception("Could not sync INDI location/time")
            return False

    def _read_cached_number_position(
        self, property_name: str
    ) -> Optional[tuple[float, float]]:
        if self.device is None:
            return None
        get_number = getattr(self.device, "getNumber", None)
        if get_number is None:
            return None

        coord_prop = get_number(property_name)
        if not coord_prop:
            return None

        ra_hours = None
        dec_deg = None
        for i in range(len(coord_prop)):
            number = coord_prop[i]
            if number.name == "RA":
                ra_hours = number.value
            elif number.name == "DEC":
                dec_deg = number.value

        if ra_hours is None or dec_deg is None:
            return None

        return ra_hours * 15.0, dec_deg

    def _read_cached_current_position(
        self, write_status: bool = True
    ) -> Optional[tuple[float, float]]:
        position = self._read_cached_number_position("EQUATORIAL_EOD_COORD")
        if position is None:
            return None

        self.set_current_position(position[0], position[1], write_status=write_status)
        if self.current_ra is None or self.current_dec is None:
            return None
        return self.current_ra, self.current_dec

    def _read_current_position(
        self, write_status: bool = True
    ) -> Optional[tuple[float, float]]:
        if self.client is None or self.device is None:
            return None

        if not self.client._wait_for_property(
            self.device, "EQUATORIAL_EOD_COORD", timeout=2.0
        ):
            return None

        return self._read_cached_current_position(write_status=write_status)

    def _read_target_position(self) -> Optional[tuple[float, float]]:
        if self.client is None or self.device is None:
            return None

        if not self.client._wait_for_property(
            self.device, "TARGET_EOD_COORD", timeout=0.25
        ):
            return None

        return self._read_cached_number_position("TARGET_EOD_COORD")

    def _goto_target_accepted(self, ra_deg: float, dec_deg: float) -> bool:
        target_ra = ra_deg % 360.0
        started_at = time.monotonic()
        while True:
            target_position = self._read_target_position()
            if (
                target_position is not None
                and radec_separation_arcmin(
                    target_position[0],
                    target_position[1],
                    target_ra,
                    dec_deg,
                )
                <= GOTO_TARGET_ACCEPT_TOLERANCE_ARCMIN
            ):
                return True

            if self._indi_mount_is_busy() is True:
                return True

            onstep_complete = self._onstep_goto_complete()
            if onstep_complete is False:
                return True

            current_position = self._read_cached_current_position()
            if (
                current_position is not None
                and radec_separation_arcmin(
                    current_position[0],
                    current_position[1],
                    target_ra,
                    dec_deg,
                )
                <= GOTO_TARGET_ACCEPT_TOLERANCE_ARCMIN
            ):
                return True

            if time.monotonic() - started_at >= GOTO_TARGET_ACCEPT_TIMEOUT_SECONDS:
                return False

            time.sleep(GOTO_TARGET_ACCEPT_POLL_SECONDS)

    def _current_plate_solve(self) -> Optional[tuple[float, float, Optional[float]]]:
        self._guide_correction_observation = {}
        try:
            solution = self.shared_state.solution()
        except Exception:
            logger.debug("Could not read MFNavis solve for GoTo refine", exc_info=True)
            return None

        if not solution or solution.last_solve_success is None:
            return None

        plate = getattr(solution, "alignment_projection", None) or {}
        if plate.get("target_pixel") is not None and tuple(
            plate["target_pixel"]
        ) != tuple(self.shared_state.target_pixel()):
            return None

        try:
            pointing = solution.pointing.aligned.solve
            if pointing is None:
                return None
            # FailedSolve diagnostics describe a newer failed frame, while
            # aligned.solve still belongs to last_solve_success. Never label
            # that retained coordinate with the failed attempt's frame ID.
            diagnostics = getattr(solution, "diagnostics", None)
            matching_attempt = (
                getattr(solution, "last_solve_attempt", None)
                == solution.last_solve_success
            )
            self._guide_correction_observation = {
                "exposure_end": solution.last_solve_success,
                "frame_id": (
                    getattr(diagnostics, "FrameId", None) if matching_attempt else None
                ),
                "solve_path": (
                    getattr(diagnostics, "solve_path", None)
                    if matching_attempt
                    else None
                ),
                "ra": float(pointing.RA),
                "dec": float(pointing.Dec),
            }
            return float(pointing.RA), float(pointing.Dec), solution.last_solve_success
        except (AttributeError, TypeError, ValueError):
            logger.debug("Invalid MFNavis solve for GoTo refine", exc_info=True)
            return None

    def _arm_goto_refine(
        self, target_ra: float, target_dec: float, accuracy_arcmin: Any = None
    ) -> None:
        try:
            accuracy = float(accuracy_arcmin)
        except (TypeError, ValueError):
            accuracy = DEFAULT_GOTO_REFINE_ACCURACY_ARCMIN
        accuracy = max(0.1, accuracy)
        now = time.monotonic()
        self._pending_goto_refine = {
            "target_ra": target_ra % 360.0,
            "target_dec": target_dec,
            "accuracy_arcmin": accuracy,
            "requested_wall": time.time(),
            "ready_at": now + GOTO_REFINE_DELAY_SECONDS,
            "timeout_at": now + GOTO_REFINE_SOLVE_TIMEOUT_SECONDS,
        }
        self._write_controller_status(
            "refine_wait",
            "Waiting for GoTo settle before solve refine",
            target_ra=target_ra % 360.0,
            target_dec=target_dec,
        )

    def _check_pending_goto_refine(self) -> None:
        pending = self._pending_goto_refine
        if pending is None:
            return

        now = time.monotonic()
        if now < pending["ready_at"]:
            return

        if now >= pending["timeout_at"]:
            self._pending_goto_refine = None
            self._write_controller_status("refine_timeout", "No fresh solve for refine")
            self._console("INDI refine\nno solve")
            return

        solved = self._current_plate_solve()
        if solved is None:
            return

        current_ra, current_dec, solve_time = solved
        if solve_time is None or solve_time < pending["requested_wall"]:
            return

        target_ra = float(pending["target_ra"])
        target_dec = float(pending["target_dec"])
        separation = radec_separation_arcmin(
            current_ra,
            current_dec,
            target_ra,
            target_dec,
        )
        if separation <= float(pending["accuracy_arcmin"]):
            self._pending_goto_refine = None
            self._write_controller_status(
                "refine_complete",
                f"GoTo refine within {separation:.1f} arcmin",
                target_ra=target_ra,
                target_dec=target_dec,
                refine_error_arcmin=separation,
            )
            self._console("INDI refine\nwithin target")
            return

        self._pending_goto_refine = None
        if not self.sync_mount(
            current_ra,
            current_dec,
            sync_context={"origin": "goto_refine", "pointing_source": "solved"},
        ):
            self._write_controller_status(
                "refine_failed", "Could not sync current solve"
            )
            return
        self.goto_target(target_ra, target_dec, refine_after_goto=False)
        self._write_controller_status(
            "refine_sent",
            f"Refine GoTo sent; error {separation:.1f} arcmin",
            target_ra=target_ra,
            target_dec=target_dec,
            refine_error_arcmin=separation,
        )
        self._console("INDI refine\nGoTo sent")

    def _arm_goto_motion(self, ra_deg: float, dec_deg: float) -> None:
        self._goto_motion = {
            "target_ra": ra_deg % 360.0,
            "target_dec": dec_deg,
            "started_at": time.monotonic(),
            "complete_ready_since": None,
            "indi_seen_busy": False,
            "onstep_seen_goto_active": False,
        }
        self._last_goto_progress_status_at = 0.0

    def _complete_goto_motion(self, message: str = "GoTo complete") -> None:
        if self._goto_motion is None:
            return

        target_ra = self._goto_motion.get("target_ra")
        target_dec = self._goto_motion.get("target_dec")
        self._goto_motion = None
        self._read_current_position()
        self._write_controller_status(
            "connected",
            message,
            target_ra=target_ra,
            target_dec=target_dec,
        )
        logger.info("%s: RA %s Dec %s", message, target_ra, target_dec)

    def _read_goto_progress_position(
        self, cached_only: bool
    ) -> Optional[tuple[float, float]]:
        try:
            if cached_only:
                return self._read_cached_current_position(write_status=False)
            return self._read_current_position(write_status=False)
        except TypeError:
            # Some tests monkeypatch these methods with no-argument callables.
            if cached_only:
                return self._read_cached_current_position()
            return self._read_current_position()

    def _write_goto_progress_status(
        self,
        motion: dict[str, Any],
        elapsed: float,
        is_busy: Optional[bool],
        current_position: Optional[tuple[float, float]],
    ) -> None:
        now = time.monotonic()
        if now - self._last_goto_progress_status_at < POSITION_STATUS_MIN_INTERVAL:
            return
        self._last_goto_progress_status_at = now

        target_ra = motion.get("target_ra")
        target_dec = motion.get("target_dec")
        extra: dict[str, Any] = {
            "target_ra": target_ra,
            "target_dec": target_dec,
            "goto_wait_seconds": round(elapsed, 1),
            "indi_busy": is_busy,
        }
        if current_position is not None:
            extra["ra"] = current_position[0] % 360.0
            extra["dec"] = current_position[1]
            if target_ra is not None and target_dec is not None:
                extra["target_error_deg"] = (
                    radec_separation_arcmin(
                        current_position[0],
                        current_position[1],
                        float(target_ra),
                        float(target_dec),
                    )
                    / 60.0
                )

        self._write_controller_status(
            "slewing",
            "GoTo in progress",
            **extra,
        )

    def _check_goto_motion(self) -> None:
        if self._goto_motion is None:
            return
        if self._pending_goto_refine is not None:
            return
        if self._manual_motion_direction is not None:
            return

        started_at = float(self._goto_motion.get("started_at", 0.0))
        elapsed = time.monotonic() - started_at
        if elapsed < GOTO_COMPLETE_MIN_SECONDS:
            return

        is_busy = self._indi_mount_is_busy()
        current_position = self._read_goto_progress_position(
            cached_only=is_busy is True
        )
        self._write_goto_progress_status(
            self._goto_motion,
            elapsed,
            is_busy,
            current_position,
        )
        if self._goto_completion_ready(
            self._goto_motion,
            is_busy,
            time.monotonic(),
            current_position=current_position,
        ):
            self._complete_goto_motion()
            return

        if elapsed > GOTO_COMPLETE_FALLBACK_SECONDS:
            logger.warning(
                "Could not read INDI GoTo busy state after %.1fs; assuming complete",
                elapsed,
            )
            self._complete_goto_motion("GoTo status timeout; assuming complete")

    def _guide_direction_for_error(
        self,
        current_ra: float,
        current_dec: float,
        target_ra: float,
        target_dec: float,
        accuracy_arcmin: float,
    ) -> Optional[str]:
        ra_delta = shortest_ra_delta_deg(target_ra, current_ra)
        dec_delta = target_dec - current_dec
        ra_arcmin = ra_delta * 60.0 * math.cos(math.radians(current_dec))
        dec_arcmin = dec_delta * 60.0
        component_threshold = max(0.01, accuracy_arcmin / 2.0)

        ns = None
        if dec_arcmin > component_threshold:
            ns = "north"
        elif dec_arcmin < -component_threshold:
            ns = "south"

        we = None
        if ra_arcmin > component_threshold:
            we = "east"
        elif ra_arcmin < -component_threshold:
            we = "west"

        if ns and we:
            return ns + we
        return ns or we

    def toggle_guide_correction(
        self,
        enabled: Optional[bool] = None,
        target_ra: Any = None,
        target_dec: Any = None,
        accuracy_arcmin: Any = None,
        manual_approach: bool = False,
    ) -> bool:
        if enabled is None:
            enabled = not self._guide_correction_enabled

        if not enabled:
            self._guide_correction_enabled = False
            self._guide_manual_approach = False
            self._approach_rate_request = None
            self._guide_correction_mode = "off"
            if self._manual_motion_origin == "guide_correction":
                if not self.stop_mount():
                    return False
            self._guide_correction_mode = "off"
            self._restore_fine_guide_rate()
            self._pending_guide_rate = None
            self._write_controller_status("connected", "Guide correction disabled")
            self._console("Guide corr\nOff")
            return True

        target: Optional[tuple[float, float]]
        try:
            target = (
                float(target_ra) % 360.0,
                float(target_dec),
            )
        except (TypeError, ValueError):
            target = self._last_goto_target

        if target is None:
            self._write_controller_status(
                "guide_correction_failed",
                "No GoTo target for guide correction",
            )
            self._console("Guide corr\nno target")
            return False

        try:
            accuracy = float(accuracy_arcmin)
        except (TypeError, ValueError):
            accuracy = self._guide_correction_accuracy_arcmin

        self._guide_correction_enabled = True
        self._guide_correction_target = target
        self._guide_correction_accuracy_arcmin = max(0.1, accuracy)
        self._guide_mount_type = config.Config().get_option("mount_type", "Alt/Az")
        self._guide_correction_next_at = time.monotonic()
        self._guide_correction_last_solve_time = 0.0
        self._guide_pulse_best_error = None
        self._guide_pulse_worsening = 0
        self._guide_progress_solve_time = 0.0
        self._guide_manual_approach = bool(
            manual_approach
            and self._guide_mount_type == "Alt/Az"
            and "onstep" in self._indi_device_name().lower()
        )
        self._guide_correction_mode = "waiting_solve"
        self._guide_observation_after_wall = 0.0
        self._approach_rate_request = None
        self._approach_previous_error = None
        self._approach_no_progress = 0
        self._write_controller_status(
            "guide_correction",
            "Guide correction enabled",
            target_ra=target[0],
            target_dec=target[1],
        )
        self._console("Guide corr\nOn")
        return True

    def _check_guide_correction(self) -> None:
        if self._pending_guide_rate is not None:
            self._finish_guide_rate_request()
        if self._pending_sync_goto is not None:
            return
        if self._goto_motion is not None:
            return
        if time.monotonic() < self._guide_pulse_until:
            return
        if not self._guide_correction_enabled or self._guide_correction_target is None:
            return
        if self._manual_motion_direction is not None:
            return

        now = time.monotonic()
        if now < self._guide_correction_next_at:
            return

        solved = self._current_plate_solve()
        if solved is None:
            return

        current_ra, current_dec, solve_time = solved
        if solve_time is None or solve_time <= self._guide_correction_last_solve_time:
            return
        # Being newer than the previous pulse does not make an old camera
        # observation recent. Leave it unconsumed so a valid solve can resume.
        solve_age = time.time() - solve_time
        if not all(math.isfinite(v) for v in (current_ra, current_dec, solve_age)):
            return
        if not 0.0 <= solve_age <= GUIDE_CORRECTION_MAX_SOLVE_AGE_SECONDS:
            return
        if solve_time < self._guide_observation_after_wall:
            return

        target_ra, target_dec = self._guide_correction_target
        separation = radec_separation_arcmin(
            current_ra,
            current_dec,
            target_ra,
            target_dec,
        )
        axis_error = self._guide_axis_error(
            current_ra, current_dec, target_ra, target_dec
        )
        if axis_error is None:
            return
        error = max(separation, axis_error)
        # Judge progress from distinct post-pulse camera observations, not
        # command submission. A functioning transport can still guide away.
        if self._guide_pulse_best_error is not None:
            if solve_time > self._guide_progress_solve_time:
                self._guide_progress_solve_time = solve_time
                best_error = min(self._guide_pulse_best_error, float(error))
                self._guide_pulse_best_error = best_error
                tolerance = max(2.0, self._guide_correction_accuracy_arcmin)
                if error > best_error + tolerance:
                    self._guide_pulse_worsening += 1
                else:
                    self._guide_pulse_worsening = 0
            if self._guide_pulse_worsening >= 3:
                self._guide_correction_enabled = False
                self._guide_correction_mode = "reacquire"
                self._write_controller_status(
                    "guide_correction",
                    "Pulse correction diverged; waiting for GoTo recovery",
                    guide_error_arcmin=error,
                )
                logger.warning(
                    "Pulse correction diverged: best %.2f, now %.2f arcmin; "
                    "requesting GoTo recovery",
                    self._guide_pulse_best_error,
                    error,
                )
                return
        # At high altitude/declination a small angular distance can still be
        # a large LCD longitude error. Lower the pulse deadband accordingly.
        self._guide_axis_scale = min(1.0, separation / error) if error > 0 else 1.0
        if error <= self._guide_correction_accuracy_arcmin:
            self._guide_correction_mode = "complete"
            self._guide_correction_last_solve_time = solve_time
            self._guide_correction_next_at = now + GUIDE_CORRECTION_INTERVAL_SECONDS
            self._restore_fine_guide_rate()
            self._write_controller_status(
                "guide_correction",
                f"Guide correction within {separation:.1f} arcmin",
                guide_error_arcmin=separation,
            )
            return

        pulse_band = max(
            GOTO_APPROACH_PULSE_BAND_ARCMIN,
            1.25 * self._guide_correction_accuracy_arcmin,
        )
        if self._guide_manual_approach and error > pulse_band:
            self._apply_manual_approach(
                current_ra, current_dec, target_ra, target_dec, error, solve_time
            )
            return
        self._approach_rate_request = None
        self._guide_correction_mode = "pulse"

        # Preferred: real INDI timed guide pulses (moves the mount for a time
        # computed from the axis error and guide rate; NOT a manual move, so it
        # does not show up as manual_motion in status).
        if self._guide_pulse_supported():
            if not self._select_guide_rate_for_error(separation):
                return
            self._guide_correction_last_solve_time = solve_time
            self._guide_correction_next_at = now + GUIDE_CORRECTION_INTERVAL_SECONDS
            if self._guide_pulse_best_error is None:
                self._guide_pulse_best_error = error
                self._guide_progress_solve_time = solve_time
            self._apply_guide_pulse(
                current_ra, current_dec, target_ra, target_dec, separation
            )
            self._guide_observation_after_wall = max(
                self._guide_observation_after_wall,
                time.time() + max(0.0, self._guide_pulse_until - time.monotonic()),
            )
            return

        # Fallback: short manual-movement nudge for drivers without a timed
        # guide-pulse interface.
        direction = self._guide_direction_for_error(
            current_ra,
            current_dec,
            target_ra,
            target_dec,
            self._guide_correction_accuracy_arcmin * self._guide_axis_scale,
        )
        if not direction:
            return

        if not self._select_guide_rate_for_error(0.0):
            return
        self._guide_correction_last_solve_time = solve_time
        self._guide_correction_next_at = now + GUIDE_CORRECTION_INTERVAL_SECONDS

        if self.manual_move(
            direction,
            lease_seconds=GUIDE_CORRECTION_PULSE_SECONDS,
            reassert_slew_rate=False,
            origin="guide_correction",
        ):
            self._write_controller_status(
                "guide_correction",
                f"Guide correction pulse {direction}; error {separation:.1f} arcmin",
                guide_error_arcmin=separation,
                guide_direction=direction,
            )

    def _fail_manual_approach(self, reason: str) -> None:
        self._guide_correction_enabled = False
        self._approach_rate_request = None
        self._guide_correction_mode = "failed"
        self._write_controller_status("guide_correction_failed", reason)
        logger.warning("GoTo manual approach stopped: %s", reason)

    def _select_approach_rate(self, rate: int) -> bool:
        """Confirm a fresh slew-selector ACK without changing the saved rate."""
        if self.client is None or self.device is None:
            self._fail_manual_approach("Manual approach mount unavailable")
            return False
        pending = self._approach_rate_request
        if pending is None or pending["rate"] != rate:
            with self._sync_property_lock:
                sequence = self._sync_property_sequence
            pending = {
                "rate": rate,
                "after_sequence": sequence,
                "deadline": time.monotonic() + SYNC_GOTO_STAGE_TIMEOUT_SECONDS,
            }
            self._approach_rate_request = pending
            self._guide_rate_needs_reassert = True
            self._confirmed_guide_rates = None
            self._pending_guide_rate = None
            self._slew_rate_polluted = True
            self._slew_rate_reassert_at = None
            if not self.client.set_switch(
                self.device, "TELESCOPE_SLEW_RATE", str(rate)
            ):
                self._fail_manual_approach("Manual approach speed request failed")
                return False
        with self._sync_property_lock:
            receipt = self._sync_property_receipts.get("TELESCOPE_SLEW_RATE")
        fresh = receipt is not None and receipt["sequence"] > pending["after_sequence"]
        if fresh and receipt is not None and receipt["state"] == "ok":
            if receipt["values"].get(str(rate)):
                return True
        if (
            fresh and receipt is not None and receipt["state"] == "alert"
        ) or time.monotonic() >= pending["deadline"]:
            self._fail_manual_approach("Manual approach speed not confirmed")
        return False

    def _apply_manual_approach(
        self, ra, dec, target_ra, target_dec, error, solve_time
    ) -> None:
        # Above 2x OnStep moves physical axes; pulse guiding instead uses
        # equatorial offsets. Use Alt/Az here, not the pulse RA/Dec direction.
        if self.shared_state is None:
            return
        errors = calc_utils.pointing_axis_errors(
            ra,
            dec,
            target_ra,
            target_dec,
            "Alt/Az",
            self.shared_state.location(),
            self.shared_state.datetime(),
        )
        if errors is None or not all(math.isfinite(v) for v in errors):
            return
        az_error, alt_error = (v * 60.0 for v in errors)
        if abs(az_error) >= abs(alt_error):
            axis_error = az_error
            direction = "east" if az_error > 0 else "west"
        else:
            axis_error = alt_error
            direction = "north" if alt_error > 0 else "south"
        # Slow down before the pulse band to allow a bounded final approach.
        # One axis per move avoids over-correcting the smaller component.
        if abs(axis_error) > 10.0:
            rate, multiplier = 6, 20.0
        elif abs(axis_error) > 3.0:
            rate, multiplier = 5, 8.0
        else:
            rate, multiplier = 4, 4.0
        self._guide_correction_mode = "manual_approach"
        if not self._select_approach_rate(rate):
            return
        if self._approach_previous_error is not None:
            if error >= self._approach_previous_error - 0.2:
                self._approach_no_progress += 1
            else:
                self._approach_no_progress = 0
            if self._approach_no_progress >= 3:
                # Do not hand an unconverged physical-axis correction to
                # unverified pulses. Ask the service to reacquire this target.
                self._guide_manual_approach = False
                self._guide_correction_enabled = False
                self._approach_rate_request = None
                self._guide_correction_last_solve_time = solve_time
                self._guide_correction_mode = "reacquire"
                self._write_controller_status(
                    "guide_correction",
                    "Manual approach stalled; requesting GoTo recovery",
                )
                logger.info("Manual approach stalled; requesting GoTo recovery")
                return
        duration = min(
            GOTO_APPROACH_MAX_SECONDS,
            abs(axis_error)
            * 60.0
            * GOTO_APPROACH_GAIN
            / (multiplier * SIDEREAL_ARCSEC_PER_SEC),
        )
        self._guide_correction_last_solve_time = solve_time
        self._approach_previous_error = error
        self._approach_rate_request = None
        if not self.manual_move(
            direction,
            lease_seconds=duration,
            reassert_slew_rate=False,
            origin="guide_correction",
        ):
            self._fail_manual_approach("Manual approach movement failed")
            return
        self._guide_correction_next_at = time.monotonic()
        logger.info(
            "GoTo manual approach: %s rate=%dx duration=%.3fs error=%.2f arcmin",
            direction,
            multiplier,
            duration,
            error,
        )

    def _guide_axis_error(self, ra, dec, target_ra, target_dec):
        if self.shared_state is None:
            return radec_separation_arcmin(ra, dec, target_ra, target_dec)
        errors = calc_utils.pointing_axis_errors(
            ra,
            dec,
            target_ra,
            target_dec,
            self._guide_mount_type,
            self.shared_state.location(),
            self.shared_state.datetime(),
        )
        return (
            max(abs(value) * 60.0 for value in errors) if errors is not None else None
        )

    def _guide_pulse_supported(self) -> bool:
        if self._pulse_guide_supported is not None:
            return self._pulse_guide_supported
        if self.device is None:
            # Do not cache a negative result before the device is available;
            # re-probe once it connects.
            return False
        try:
            ns = self.device.getNumber("TELESCOPE_TIMED_GUIDE_NS")
            we = self.device.getNumber("TELESCOPE_TIMED_GUIDE_WE")
            supported = bool(ns) and bool(we)
        except Exception:
            logger.debug("Timed guide capability probe failed", exc_info=True)
            supported = False
        self._pulse_guide_supported = supported
        logger.info("INDI timed guide pulse supported: %s", supported)
        return supported

    def _current_guide_rate_x(self) -> tuple[float, float]:
        """Guide rate (WE, NS) as a fraction of sidereal, with a safe fallback."""
        if self.device is not None:
            try:
                guide_rate = self.device.getNumber("GUIDE_RATE")
                if guide_rate:
                    we = ns = None
                    for i in range(len(guide_rate)):
                        if guide_rate[i].name == "GUIDE_RATE_WE":
                            we = float(guide_rate[i].value)
                        elif guide_rate[i].name == "GUIDE_RATE_NS":
                            ns = float(guide_rate[i].value)
                    if we and ns and we > 0.0 and ns > 0.0:
                        return we, ns
            except Exception:
                logger.debug("GUIDE_RATE read failed", exc_info=True)
        driver = self._read_driver_guide_rate()
        if driver is not None and driver[0] > 0.0 and driver[1] > 0.0:
            return driver
        return DEFAULT_GUIDE_RATE_X, DEFAULT_GUIDE_RATE_X

    def _set_guide_rate(self, rate_x: Any) -> bool:
        if self.client is None or self.device is None:
            return False
        we, ns = rate_x if isinstance(rate_x, tuple) else (rate_x, rate_x)
        return self.client.set_number(
            self.device,
            "GUIDE_RATE",
            {"GUIDE_RATE_WE": we, "GUIDE_RATE_NS": ns},
        )

    def _finish_guide_rate_request(self) -> Optional[bool]:
        pending = self._pending_guide_rate
        if pending is None:
            return True
        with self._sync_property_lock:
            receipt = self._sync_property_receipts.get("GUIDE_RATE")
        fresh = receipt is not None and receipt["sequence"] > pending["after_sequence"]
        if fresh and receipt is not None and receipt["state"] == "ok":
            values = receipt["values"]
            try:
                rates = (float(values["GUIDE_RATE_WE"]), float(values["GUIDE_RATE_NS"]))
            except (KeyError, TypeError, ValueError):
                rates = (float("nan"), float("nan"))
            if all(
                math.isfinite(v) and abs(v - pending["rate"]) <= 0.01 for v in rates
            ):
                self._confirmed_guide_rates = rates
                self._guide_rate_needs_reassert = False
                self._guide_rate_writable = True
                self._pending_guide_rate = None
                return True
        if (
            fresh and receipt is not None and receipt["state"] == "alert"
        ) or time.monotonic() >= pending["deadline"]:
            self._pending_guide_rate = None
            self._guide_rate_writable = False
            self._guide_rate_needs_reassert = True
            self._write_controller_status(
                "guide_rate_failed", "Guide speed not confirmed; pulse blocked"
            )
            return False
        return None

    def _select_guide_rate_for_error(self, separation_arcmin: float) -> bool:
        """Apply the guide profile and wait asynchronously for driver readback.

        OnStepX uses one guide rate for both axes. A manual selector invalidates
        the old guide readback, so it is re-applied before the next pulse.
        """
        if (
            self._guide_rate_writable is False
            or self._manual_motion_direction is not None
        ):
            return False
        if self._finish_guide_rate_request() is not True:
            return False
        fast_band = (
            self._guide_correction_accuracy_arcmin * GUIDE_RATE_FAST_MIN_ERROR_MULTIPLE
        )
        boosted = separation_arcmin > fast_band
        desired = (
            max(self.guide_rate_we, GUIDE_RATE_FAST_X)
            if boosted
            else self.guide_rate_we
        )
        if (
            not self._guide_rate_needs_reassert
            and self._confirmed_guide_rates is not None
            and all(abs(v - desired) <= 0.01 for v in self._confirmed_guide_rates)
        ):
            self._guide_rate_boosted = boosted
            return True
        with self._sync_property_lock:
            sequence = self._sync_property_sequence
        self._pending_guide_rate = {
            "rate": desired,
            "after_sequence": sequence,
            "deadline": time.monotonic() + 5.0,
        }
        self._guide_rate_needs_reassert = True
        self._slew_rate_polluted = True
        try:
            accepted = self._set_guide_rate(desired)
        except Exception:
            logger.exception("Guide speed send failed")
            accepted = False
        if not accepted:
            self._pending_guide_rate = None
            self._guide_rate_writable = False
            self._write_controller_status(
                "guide_rate_failed", "Guide speed unavailable; pulse blocked"
            )
            return False
        self._guide_rate_boosted = boosted
        logger.info(
            "Guide speed requested %.2fx (saved fine %.2fx; error %.1f arcmin)",
            desired,
            self.guide_rate_we,
            separation_arcmin,
        )
        return self._finish_guide_rate_request() is True

    def _restore_fine_guide_rate(self) -> None:
        """Select the saved fine profile for the next correction, without
        changing an in-flight pulse or the user's current manual motion.
        """
        self._guide_rate_boosted = False

    def _schedule_slew_rate_reassert(self, delay_seconds: float) -> None:
        """Queue a TELESCOPE_SLEW_RATE re-apply after a guide-rate write.

        Delayed past the pulse window because the firmware uses the shared
        rate selector for the in-flight timed guide pulse; the later of two
        pending deadlines wins so a fresh pulse extends the wait.
        """
        at = time.monotonic() + max(0.0, delay_seconds)
        at = max(at, self._guide_pulse_until)
        if self._slew_rate_reassert_at is None or at > self._slew_rate_reassert_at:
            self._slew_rate_reassert_at = at

    def _check_slew_rate_reassert(self) -> None:
        if self._slew_rate_reassert_at is None:
            return
        if time.monotonic() < self._slew_rate_reassert_at:
            return
        if time.monotonic() < self._guide_pulse_until:
            return
        if self._manual_motion_origin == "guide_correction":
            return
        if self._reassert_slew_rate():
            self._slew_rate_reassert_at = None
        else:
            self._slew_rate_reassert_at = time.monotonic() + 1.0

    def _reassert_slew_rate(self) -> bool:
        if self.client is not None and self.device is not None:
            accepted = self.client.set_switch(
                self.device, "TELESCOPE_SLEW_RATE", str(self.slew_rate)
            )
        else:
            accepted = self._apply_indi_properties(
                [self._indi_property_on(f"TELESCOPE_SLEW_RATE.{self.slew_rate}")],
                "connected" if self.connected else "idle",
                f"Manual speed {self.slew_rate}",
                "slew_rate_failed",
            )
        self._guide_rate_needs_reassert = True
        self._pending_guide_rate = None
        self._confirmed_guide_rates = None
        if not accepted:
            logger.debug("Slew rate %d re-assert failed", self.slew_rate)
            return False
        self._slew_rate_polluted = False
        logger.debug("Slew rate %d reasserted after guide-rate write", self.slew_rate)
        return True

    def _guide_pulse_ms(self, error_arcsec: float, guide_rate_x: float) -> int:
        rate_arcsec_per_sec = max(0.01, guide_rate_x) * SIDEREAL_ARCSEC_PER_SEC
        ms = (
            abs(error_arcsec)
            / rate_arcsec_per_sec
            * 1000.0
            * GUIDE_PULSE_AGGRESSIVENESS
        )
        return int(max(GUIDE_PULSE_MIN_MS, min(GUIDE_PULSE_MAX_MS, ms)))

    def _send_guide_pulse(self, direction: str, duration_ms: int) -> bool:
        if self.client is None or self.device is None:
            return False
        prop_name, element = GUIDE_PULSE_ELEMENTS[direction]
        sent_wall = time.time()
        sent_monotonic = time.monotonic()
        accepted = self.client.set_number(
            self.device, prop_name, {element: float(duration_ms)}
        )
        returned_wall = time.time()
        returned_monotonic = time.monotonic()
        if accepted:
            self._guide_pulse_until = max(
                self._guide_pulse_until, returned_monotonic + duration_ms / 1000.0 + 0.5
            )
        # Append each axis command to the bounded application log, instead of
        # relying on a status snapshot that the next axis/poll can overwrite.
        # set_number acceptance is NOT confirmation of physical pulse ending.
        logger.info(
            "Guide pulse event %s",
            json.dumps(
                {
                    "observation": self._guide_correction_observation,
                    "target": self._guide_correction_target,
                    "direction": direction,
                    "duration_ms": duration_ms,
                    "accepted": bool(accepted),
                    "sent_wall": sent_wall,
                    "sent_monotonic": sent_monotonic,
                    "returned_wall": returned_wall,
                    "returned_monotonic": returned_monotonic,
                    "expected_end_wall": (
                        returned_wall + duration_ms / 1000.0 if accepted else None
                    ),
                    "expected_end_monotonic": (
                        returned_monotonic + duration_ms / 1000.0 if accepted else None
                    ),
                    "end_confirmed": False,
                },
                separators=(",", ":"),
            ),
        )
        return accepted

    def _guide_pulse_inversions(self) -> tuple[bool, bool]:
        """Per-axis guide-pulse direction inversion (NS, WE) from config.

        Read fresh each cycle so a UI toggle takes effect without extra plumbing;
        the guide loop only runs every GUIDE_CORRECTION_INTERVAL_SECONDS. Applies
        to the timed guide pulse only, not the manual-move fallback (whose
        direction mapping is already hardware-validated).
        """
        try:
            cfg = config.Config()
            cfg.load_config()
            invert_ns = bool(cfg.get_option("indi_guide_pulse_invert_ns", False))
            invert_we = bool(cfg.get_option("indi_guide_pulse_invert_we", False))
        except Exception:
            logger.debug("Guide-pulse inversion config read failed", exc_info=True)
            return False, False
        return invert_ns, invert_we

    def _apply_guide_pulse(
        self,
        current_ra: float,
        current_dec: float,
        target_ra: float,
        target_dec: float,
        separation: float,
    ) -> None:
        ra_delta_deg = shortest_ra_delta_deg(target_ra, current_ra)
        dec_delta_deg = target_dec - current_dec
        ra_arcsec = ra_delta_deg * 3600.0 * math.cos(math.radians(current_dec))
        dec_arcsec = dec_delta_deg * 3600.0
        guide_we_x, guide_ns_x = (
            self._confirmed_guide_rates or self._current_guide_rate_x()
        )
        invert_ns, invert_we = self._guide_pulse_inversions()
        threshold_arcsec = (
            max(
                0.01,
                self._guide_correction_accuracy_arcmin / 2.0 * self._guide_axis_scale,
            )
            * 60.0
        )

        pulses: list[str] = []
        max_pulse_ms = 0
        if abs(dec_arcsec) > threshold_arcsec:
            ns_dir = "north" if dec_arcsec > 0 else "south"
            if invert_ns:
                ns_dir = "south" if ns_dir == "north" else "north"
            ns_ms = self._guide_pulse_ms(dec_arcsec, guide_ns_x)
            if self._send_guide_pulse(ns_dir, ns_ms):
                pulses.append(f"{ns_dir} {ns_ms}ms")
                max_pulse_ms = max(max_pulse_ms, ns_ms)
        if abs(ra_arcsec) > threshold_arcsec:
            we_dir = "east" if ra_arcsec > 0 else "west"
            if invert_we:
                we_dir = "west" if we_dir == "east" else "east"
            we_ms = self._guide_pulse_ms(ra_arcsec, guide_we_x)
            if self._send_guide_pulse(we_dir, we_ms):
                pulses.append(f"{we_dir} {we_ms}ms")
                max_pulse_ms = max(max_pulse_ms, we_ms)

        # Leave the guide selector in place between pulses. Manual motion
        # re-applies its own stored rate on demand; no idle speed oscillation.

        if pulses:
            self._write_controller_status(
                "guide_correction",
                f"Guide pulse {', '.join(pulses)}; error {separation:.1f} arcmin",
                guide_error_arcmin=separation,
                guide_direction=",".join(p.split()[0] for p in pulses),
            )

    def sync_mount(
        self,
        ra_deg: float,
        dec_deg: float,
        sync_context: Optional[dict[str, Any]] = None,
    ) -> bool:
        self._cancel_sync_goto("superseded by standalone sync")
        if not self.connect() or self.client is None or self.device is None:
            return False

        if not self.client.set_switch(self.device, "ON_COORD_SET", "SYNC"):
            self._write_controller_status("sync_failed", "Could not set INDI SYNC mode")
            return False

        if not self.client.set_number(
            self.device,
            "EQUATORIAL_EOD_COORD",
            {"RA": (ra_deg % 360.0) / 15.0, "DEC": dec_deg},
        ):
            self._write_controller_status(
                "sync_failed", "Could not set sync coordinates"
            )
            return False

        self.client.set_switch(self.device, "ON_COORD_SET", "TRACK")
        self.client.set_switch(self.device, "TELESCOPE_TRACK_STATE", "TRACK_ON")
        self._record_coordinate_sync(ra_deg, dec_deg, sync_context)
        return True

    def _record_coordinate_sync(self, ra_deg, dec_deg, sync_context=None) -> None:
        self._coordinate_sync = {
            "active": True,
            "synced": True,
            "ra": ra_deg % 360.0,
            "dec": dec_deg,
            "synced_at": time.time(),
            "source": "sync_mount",
        }
        # B5 visibility (docs/mf_report/mf_field_test_20260724_analysis_ko.md): record
        # who requested this sync and which coordinate source (solve / IMU
        # fusion / target) the value came from, for field diagnostics.
        if sync_context:
            for key in ("origin", "pointing_source", "solve_age_seconds"):
                if sync_context.get(key) is not None:
                    self._coordinate_sync[key] = sync_context[key]
        self.set_current_position(ra_deg, dec_deg)
        logger.info(
            "Mount synced to RA %.4f Dec %.4f (origin=%s source=%s)",
            ra_deg,
            dec_deg,
            (sync_context or {}).get("origin", "unknown"),
            (sync_context or {}).get("pointing_source", "unknown"),
        )
        self._console("INDI mount\nsynced")

    def receive_sync_property(self, name, state, values, client_generation) -> None:
        """Keep immutable snapshots of actual driver acknowledgements."""
        if client_generation != self._client_generation:
            return
        if name not in {
            "ON_COORD_SET",
            "EQUATORIAL_EOD_COORD",
            "GUIDE_RATE",
            "TELESCOPE_SLEW_RATE",
            "GEOGRAPHIC_COORD",
            "TIME_UTC",
        }:
            return
        with self._sync_property_lock:
            self._sync_property_sequence += 1
            self._sync_property_receipts[name] = {
                "sequence": self._sync_property_sequence,
                "state": state,
                "values": dict(values),
                "received_monotonic": time.monotonic(),
            }

    def _cancel_sync_goto(self, reason: str) -> None:
        if self._pending_sync_goto is None:
            return
        self._pending_sync_goto = None
        self._sync_goto_status = {
            **(self._sync_goto_status or {}),
            "state": "failed",
            "reason": reason,
        }
        self._write_controller_status("sync_goto_failed", reason)
        logger.warning("Verified sync+GoTo cancelled: %s", reason)

    def _arm_sync_goto_stage(self, transaction, stage: str) -> None:
        with self._sync_property_lock:
            transaction["after_sequence"] = self._sync_property_sequence
        transaction["stage"] = stage
        transaction["deadline"] = time.monotonic() + SYNC_GOTO_STAGE_TIMEOUT_SECONDS
        self._sync_goto_status = {
            **(self._sync_goto_status or {}),
            "state": stage,
        }
        self._write_controller_status("sync_goto_waiting", stage)

    def begin_sync_and_goto(self, command: dict[str, Any]) -> bool:
        """Verify SYNC mode, matching coordinate ACK, then SLEW mode.

        Stages run in the normal event loop, so a queued stop can cancel the
        pending move. Sending a property or reading its mutated local cache
        never counts as successful alignment.
        """
        self._cancel_sync_goto("superseded by a new GoTo")
        values = [float(command[k]) for k in ("sync_ra", "sync_dec", "ra", "dec")]
        if not all(math.isfinite(v) for v in values) or any(
            abs(values[i]) > 90.0 for i in (1, 3)
        ):
            raise ValueError("Invalid sync+GoTo coordinates")
        if not self.connect() or self.client is None or self.device is None:
            self._sync_goto_status = {
                "request_id": command["request_id"],
                "state": "failed",
                "reason": "INDI connection unavailable",
            }
            self._write_controller_status("sync_goto_failed", "INDI unavailable")
            return False
        transaction = dict(command)
        transaction.update(zip(("sync_ra", "sync_dec", "ra", "dec"), values))
        transaction["generation"] = self._client_generation
        self._pending_sync_goto = transaction
        self._sync_goto_status = {
            "request_id": command["request_id"],
            "state": "starting",
            "sync_ra": values[0] % 360.0,
            "sync_dec": values[1],
            "target_ra": values[2] % 360.0,
            "target_dec": values[3],
            "started_monotonic": time.monotonic(),
        }
        self._arm_sync_goto_stage(transaction, "waiting_sync_mode")
        try:
            requested = self.client.set_switch(self.device, "ON_COORD_SET", "SYNC")
        except Exception as exc:
            logger.exception("Could not request verified SYNC mode")
            self._cancel_sync_goto(f"Could not request SYNC mode: {exc}")
            return False
        if not requested:
            self._cancel_sync_goto("Could not request SYNC mode")
            return False
        return True

    def _check_pending_sync_goto(self) -> None:
        try:
            self._advance_pending_sync_goto()
        except Exception as exc:
            logger.exception("Verified sync+GoTo failed")
            if self._pending_sync_goto is not None:
                self._cancel_sync_goto(f"Sync verification failed: {exc}")
            elif self._sync_goto_status is not None:
                self._sync_goto_status = {
                    **self._sync_goto_status,
                    "state": "failed",
                    "reason": str(exc),
                }
                self._write_controller_status("sync_goto_failed", str(exc))

    def _advance_pending_sync_goto(self) -> None:
        transaction = self._pending_sync_goto
        if transaction is None:
            return
        if (
            not self.connected
            or self.client is None
            or self.device is None
            or transaction["generation"] != self._client_generation
        ):
            self._cancel_sync_goto("INDI connection changed during sync")
            return
        if time.monotonic() >= transaction["deadline"]:
            self._cancel_sync_goto(f"Timeout: {transaction['stage']}")
            return
        stage = transaction["stage"]
        name = (
            "EQUATORIAL_EOD_COORD"
            if stage == "waiting_sync_coordinates"
            else "ON_COORD_SET"
        )
        with self._sync_property_lock:
            receipt = self._sync_property_receipts.get(name)
        if receipt is None or receipt["sequence"] <= transaction["after_sequence"]:
            return
        if receipt["state"] == "alert":
            self._cancel_sync_goto(f"Driver rejected {stage}")
            return
        if receipt["state"] != "ok":
            return
        if stage == "waiting_sync_mode":
            if not receipt["values"].get("SYNC"):
                return
            self._arm_sync_goto_stage(transaction, "waiting_sync_coordinates")
            if not self.client.set_number(
                self.device,
                "EQUATORIAL_EOD_COORD",
                {
                    "RA": (transaction["sync_ra"] % 360.0) / 15.0,
                    "DEC": transaction["sync_dec"],
                },
            ):
                self._cancel_sync_goto("Could not send sync coordinates")
            return
        if stage == "waiting_sync_coordinates":
            try:
                ra = float(receipt["values"]["RA"]) * 15.0
                dec = float(receipt["values"]["DEC"])
            except (KeyError, TypeError, ValueError):
                return
            if not (math.isfinite(ra) and math.isfinite(dec) and abs(dec) <= 90.0):
                return
            error = radec_separation_arcmin(
                ra, dec, transaction["sync_ra"], transaction["sync_dec"]
            )
            if error > SYNC_GOTO_COORD_TOLERANCE_ARCMIN:
                return
            self._record_coordinate_sync(
                transaction["sync_ra"], transaction["sync_dec"], transaction
            )
            self._sync_goto_status = {
                **(self._sync_goto_status or {}),
                "verified_error_arcmin": error,
                "verified_monotonic": receipt["received_monotonic"],
            }
            if not self.client.set_switch(
                self.device, "TELESCOPE_TRACK_STATE", "TRACK_ON"
            ):
                self._cancel_sync_goto("Could not enable tracking after sync")
                return
            self._arm_sync_goto_stage(transaction, "waiting_slew_mode")
            if not self.client.set_switch(self.device, "ON_COORD_SET", "SLEW"):
                self._cancel_sync_goto("Could not request SLEW mode")
            return
        if not receipt["values"].get("SLEW"):
            return
        # Clear before goto_target so its normal supersession guard does not
        # cancel this verified transaction. A failed GoTo remains terminal.
        self._pending_sync_goto = None
        sent_at = time.monotonic()
        accepted = self.goto_target(transaction["ra"], transaction["dec"])
        self._sync_goto_status = {
            **(self._sync_goto_status or {}),
            "state": "goto_sent" if accepted else "failed",
            "reason": "" if accepted else "GoTo target rejected after verified sync",
            "goto_sent_monotonic": sent_at,
        }
        self._write_controller_status(
            "slewing" if accepted else "sync_goto_failed", "Verified sync+GoTo"
        )
        logger.info("Verified sync+GoTo: %s", self._sync_goto_status)

    def goto_target(
        self,
        ra_deg: float,
        dec_deg: float,
        refine_after_goto: bool = False,
        refine_accuracy_arcmin: Any = None,
    ) -> bool:
        self._cancel_sync_goto("superseded by a direct GoTo")
        target_ra = ra_deg % 360.0
        if not self.connect() or self.client is None or self.device is None:
            return False

        for attempt in range(1, GOTO_TARGET_COMMAND_ATTEMPTS + 1):
            if not self.client.set_switch(self.device, "ON_COORD_SET", "SLEW"):
                self._write_controller_status(
                    "goto_failed", "Could not set INDI SLEW mode"
                )
                return False

            if not self.client.set_number(
                self.device,
                "EQUATORIAL_EOD_COORD",
                {"RA": target_ra / 15.0, "DEC": dec_deg},
            ):
                self._write_controller_status(
                    "goto_failed", "Could not set target coordinates"
                )
                return False

            if self._goto_target_accepted(target_ra, dec_deg):
                break

            logger.warning(
                "INDI GoTo target RA %.4f Dec %.4f was not accepted "
                "after attempt %d/%d",
                target_ra,
                dec_deg,
                attempt,
                GOTO_TARGET_COMMAND_ATTEMPTS,
            )
        else:
            self._write_controller_status(
                "goto_failed",
                "INDI GoTo target was not accepted",
                target_ra=target_ra,
                target_dec=dec_deg,
            )
            self._console("INDI mount\nGoTo failed")
            return False

        self._last_goto_target = (target_ra, dec_deg)
        self._arm_goto_motion(target_ra, dec_deg)
        self._write_controller_status(
            "slewing",
            "GoTo target command sent",
            target_ra=target_ra,
            target_dec=dec_deg,
        )
        logger.info("Mount GoTo RA %.4f Dec %.4f", target_ra, dec_deg)
        self._console("INDI mount\nGoTo sent")
        if refine_after_goto:
            self._arm_goto_refine(target_ra, dec_deg, refine_accuracy_arcmin)
        return True

    def stop_mount(self, preserve_tracking: bool = False) -> bool:
        self._cancel_sync_goto("stop requested")
        # Releasing a direction button stops the axes, not sidereal tracking.
        # OnStep's global abort can turn tracking off, leaving the guide loop
        # trying to chase the sky's full drift after an otherwise good retarget.
        manual_stop = self._manual_motion_direction is not None
        was_tracking = (
            manual_stop or preserve_tracking
        ) and self._cached_tracking_enabled() is True
        used_abort = not manual_stop
        properties = (
            [
                f"{self._indi_property_name('TELESCOPE_MOTION_NS')}.MOTION_NORTH=Off;MOTION_SOUTH=Off",
                f"{self._indi_property_name('TELESCOPE_MOTION_WE')}.MOTION_WEST=Off;MOTION_EAST=Off",
            ]
            if manual_stop
            else [self._indi_property_on("TELESCOPE_ABORT_MOTION.ABORT")]
        )
        stopped = self._apply_indi_properties(
            properties,
            "stopped",
            "Mount stop command sent",
            "stop_failed",
        )
        if not stopped and manual_stop:
            used_abort = True
            # Retain an emergency stop if the directional stop was rejected.
            stopped = self._apply_indi_properties(
                [self._indi_property_on("TELESCOPE_ABORT_MOTION.ABORT")],
                "stopped",
                "Manual axis stop failed; mount aborted",
                "stop_failed",
            )
        if not stopped:
            self._console("INDI stop\nfailed")
            return False

        if self._manual_motion_origin == "user":
            self._last_user_motion_stopped_wall = time.time()
        if self._manual_motion_origin == "guide_correction":
            self._guide_observation_after_wall = (
                time.time() + GOTO_APPROACH_SETTLE_SECONDS
            )
            self._guide_correction_next_at = (
                time.monotonic() + GOTO_APPROACH_SETTLE_SECONDS
            )
            self._guide_correction_mode = "settling"
        self._clear_manual_motion_deadline()
        self._goto_motion = None
        self._guide_pulse_until = 0.0
        if used_abort and was_tracking and not self.set_tracking(True):
            return False
        logger.info("Mount stop command sent")
        self._console("INDI mount\nstopped")
        return True

    def manual_move(
        self,
        direction: str,
        lease_seconds: Any = None,
        reassert_slew_rate: bool = True,
        origin: str = "user",
    ) -> bool:
        self._cancel_sync_goto("manual movement requested")
        if origin == "user" and self._goto_motion is not None:
            if not self.stop_mount(preserve_tracking=True):
                return False
        # Stop the correction loop immediately, including normal tracking.
        # A short key tap can end before the guide service sees motion; leaving
        # this armed would resume pulses toward the old target after release.
        if origin == "user" and self._guide_correction_enabled:
            if not self.toggle_guide_correction(enabled=False):
                return False
        direction = direction.lower()
        # A guide-rate write may have just dragged the shared :R<n># selector
        # down to 0.5x/1x; put the user's rate back before the move starts.
        # The guide-correction manual fallback opts out (it wants the slow
        # rate its nudge duration was computed for).
        motion_map = {
            "north": [self._indi_property_on("TELESCOPE_MOTION_NS.MOTION_NORTH")],
            "south": [self._indi_property_on("TELESCOPE_MOTION_NS.MOTION_SOUTH")],
            "east": [self._indi_property_on("TELESCOPE_MOTION_WE.MOTION_WEST")],
            "west": [self._indi_property_on("TELESCOPE_MOTION_WE.MOTION_EAST")],
            "northeast": [
                self._indi_property_on("TELESCOPE_MOTION_NS.MOTION_NORTH"),
                self._indi_property_on("TELESCOPE_MOTION_WE.MOTION_WEST"),
            ],
            "northwest": [
                self._indi_property_on("TELESCOPE_MOTION_NS.MOTION_NORTH"),
                self._indi_property_on("TELESCOPE_MOTION_WE.MOTION_EAST"),
            ],
            "southeast": [
                self._indi_property_on("TELESCOPE_MOTION_NS.MOTION_SOUTH"),
                self._indi_property_on("TELESCOPE_MOTION_WE.MOTION_WEST"),
            ],
            "southwest": [
                self._indi_property_on("TELESCOPE_MOTION_NS.MOTION_SOUTH"),
                self._indi_property_on("TELESCOPE_MOTION_WE.MOTION_EAST"),
            ],
        }
        if direction not in motion_map:
            logger.warning("Unknown manual mount direction: %s", direction)
            return False

        if reassert_slew_rate:
            # Never switch the firmware's shared rate under an active pulse.
            # Manual input takes over only after the abort request succeeds.
            if time.monotonic() < self._guide_pulse_until and not self.stop_mount(
                preserve_tracking=origin == "user"
            ):
                return False
            if not self._reassert_slew_rate():
                self._write_controller_status(
                    "manual_failed", "Manual speed unavailable; movement blocked"
                )
                return False
            self._slew_rate_reassert_at = None

        if not self._apply_indi_properties(
            motion_map[direction],
            "moving",
            f"Manual {direction} motion sent",
            "manual_failed",
        ):
            self._console("INDI motion\nfailed")
            return False

        self._arm_manual_motion_deadline(direction, lease_seconds, origin)
        self._publish_manual_motion_progress(force=True)
        logger.info("Manual %s motion sent", direction)
        self._console(f"INDI move\n{direction}")
        return True

    def park_action(self, action: str) -> bool:
        action_map = {
            "park": ("TELESCOPE_PARK.PARK", "Mount parked"),
            "unpark": ("TELESCOPE_PARK.UNPARK", "Mount unparked"),
            "set_home": ("TELESCOPE_HOME.SET", "Home position set"),
            "return_home": ("TELESCOPE_HOME.GO", "Return home command sent"),
            "set_park": ("TELESCOPE_PARK_OPTION.PARK_CURRENT", "Park position set"),
        }
        if action not in action_map:
            logger.warning("Unknown park action: %s", action)
            return False

        property_name, message = action_map[action]
        if not self._apply_indi_properties(
            [self._indi_property_on(property_name)],
            "connected",
            message,
            "park_failed",
        ):
            self._console("INDI park\nfailed")
            return False

        self._console("INDI\n" + message)
        return True

    def _read_driver_slew_rate(self) -> Optional[int]:
        properties = sys_utils.get_indi_onstep_properties(
            server_host=self.indi_host,
            server_port=self.indi_port,
            device_name=self._indi_device_name(),
        )
        for rate in range(10):
            if (
                properties.get(self._indi_property_name(f"TELESCOPE_SLEW_RATE.{rate}"))
                == "On"
            ):
                return rate
        return None

    def _load_motion_rates(self) -> None:
        cfg = config.Config()
        try:
            rate = int(cfg.get_option("indi_manual_slew_rate", 5))
            if 0 <= rate <= 9:
                self.slew_rate = rate
        except (TypeError, ValueError, OverflowError):
            logger.warning("Invalid saved manual speed; using default")
        try:
            value = float(cfg.get_option("indi_pulse_guide_rate", GUIDE_RATE_FINE_X))
            if value not in (0.25, 0.5, 1.0):
                raise ValueError("Unsupported fine guide speed")
            self.guide_rate_we = self.guide_rate_ns = value
        except (TypeError, ValueError, OverflowError):
            logger.warning("Invalid saved guide speed; using default")

    def refresh_slew_rate(self) -> int:
        # A temporary driver selector is not a user preference. All PiFinder
        # speed controls now update the stored manual profile through this process.
        self._write_controller_status(
            "connected" if self.connected else "idle",
            f"Manual speed {self.slew_rate}",
        )
        return self.slew_rate

    def set_slew_rate(self, rate: int) -> bool:
        rate = max(0, min(9, int(rate)))
        config.Config().set_options({"indi_manual_slew_rate": rate})
        self.slew_rate = rate
        # Save a change made during a pulse, then apply after its time window.
        if (
            time.monotonic() < self._guide_pulse_until
            or self._manual_motion_origin == "guide_correction"
        ):
            self._schedule_slew_rate_reassert(0.0)
            self._write_controller_status(
                "connected", f"Manual speed {rate} saved; waiting for guide motion"
            )
            return True
        if not self._reassert_slew_rate():
            self._console("INDI speed\nfailed")
            return False
        self._slew_rate_reassert_at = None
        self._write_controller_status(
            "connected" if self.connected else "idle", f"Manual speed {rate} saved"
        )
        self._console(f"INDI speed\n{self.slew_rate}")
        return True

    def set_track_frequency(self, hz: float, label: str = "") -> bool:
        """Set a non-sidereal tracking frequency for the current target.

        Writes the INDI ``Tracking Frequency.trackFreq`` number, which the
        LX200 OnStep driver forwards as ``:ST<Hz>#``. Verified on OnStepX
        10.28q: the frequency survives GoTo slews and is only reset by an
        actual track-mode change, so it is periodically re-asserted while a
        target frequency is active (see _reassert_track_frequency).
        """
        clamped, was_clamped = nonsidereal.clamp_hz(hz)
        if was_clamped:
            logger.warning(
                "Track frequency %.5f Hz outside accepted window, clamped to %.5f",
                hz,
                clamped,
            )
        if not self._write_track_frequency(clamped):
            self._write_controller_status(
                "track_freq_failed", f"Could not set tracking frequency {clamped:.5f}"
            )
            self._console("INDI trackrate\nfailed")
            return False
        self._track_freq_target_hz = clamped
        self._track_freq_label = label
        self._write_controller_status(
            "connected" if self.connected else "idle",
            f"Tracking frequency {clamped:.5f} Hz" + (f" for {label}" if label else ""),
        )
        self._console(f"INDI trackrate\n{clamped:.3f} Hz")
        logger.info(
            "Tracking frequency set to %.5f Hz%s",
            clamped,
            f" for {label}" if label else "",
        )
        return True

    def reset_track_frequency(self) -> bool:
        """Restore sidereal tracking frequency.

        Writes the sidereal frequency explicitly instead of re-selecting
        TRACK_SIDEREAL: re-asserting an already-on mode switch is a driver
        no-op and does not reset the firmware frequency (measured).
        """
        if not self._write_track_frequency(nonsidereal.SIDEREAL_FREQ_HZ):
            self._console("INDI trackrate\nreset failed")
            return False
        self._track_freq_target_hz = None
        self._track_freq_label = ""
        self._write_controller_status(
            "connected" if self.connected else "idle",
            "Tracking frequency reset to sidereal",
        )
        self._console("INDI trackrate\nsidereal")
        logger.info("Tracking frequency reset to sidereal")
        return True

    def _write_track_frequency(self, hz: float) -> bool:
        if not self.connect() or self.client is None or self.device is None:
            return False
        if not self.client.set_number(
            self.device, "Tracking Frequency", {"trackFreq": float(hz)}
        ):
            return False
        self._track_freq_last_assert_at = time.monotonic()
        return True

    def _reassert_track_frequency(self) -> None:
        if self._track_freq_target_hz is None or not self.connected:
            return
        if (
            time.monotonic() - self._track_freq_last_assert_at
            < TRACK_FREQ_REASSERT_INTERVAL
        ):
            return
        if not self._write_track_frequency(self._track_freq_target_hz):
            logger.warning(
                "Tracking frequency re-assert failed (%.5f Hz)",
                self._track_freq_target_hz,
            )

    def _read_driver_guide_rate(self) -> Optional[tuple[float, float]]:
        properties = sys_utils.get_indi_onstep_properties(
            server_host=self.indi_host,
            server_port=self.indi_port,
            device_name=self._indi_device_name(),
        )
        try:
            guide_we = float(
                properties[self._indi_property_name("GUIDE_RATE.GUIDE_RATE_WE")]
            )
            guide_ns = float(
                properties[self._indi_property_name("GUIDE_RATE.GUIDE_RATE_NS")]
            )
        except (KeyError, TypeError, ValueError):
            return None
        return guide_we, guide_ns

    def set_guide_rate(self, rate: Any) -> bool:
        try:
            guide_rate = float(rate)
            if guide_rate not in (0.25, 0.5, 1.0):
                raise ValueError("Fine guide speed must be 0.25, 0.5 or 1x sidereal")
        except (TypeError, ValueError):
            self._write_controller_status(
                "guide_rate_failed", f"Invalid guide rate {rate!r}"
            )
            return False
        config.Config().set_options({"indi_pulse_guide_rate": guide_rate})
        self.guide_rate_we = self.guide_rate_ns = guide_rate
        self._guide_rate_needs_reassert = True
        self._guide_rate_writable = None
        self._pending_guide_rate = None
        # Save only: applying here could change a held move or timed pulse.
        self._write_controller_status(
            "connected" if self.connected else "idle",
            f"Guide speed {guide_rate:g}x saved for next pulse",
        )
        self._console(f"INDI guide\n{guide_rate:g}x")
        return True

    def _read_tracking_enabled_from_properties(self) -> Optional[bool]:
        properties = sys_utils.get_indi_onstep_properties(
            server_host=self.indi_host,
            server_port=self.indi_port,
            device_name=self._indi_device_name(),
        )
        track_on = properties.get(
            self._indi_property_name("TELESCOPE_TRACK_STATE.TRACK_ON")
        )
        track_off = properties.get(
            self._indi_property_name("TELESCOPE_TRACK_STATE.TRACK_OFF")
        )
        if track_on in {"On", "Off"}:
            return track_on == "On"
        if track_off in {"On", "Off"}:
            return track_off != "On"
        return None

    def _read_tracking_enabled(self) -> Optional[bool]:
        for attempt in range(3):
            property_state = self._read_tracking_enabled_from_properties()
            if property_state is not None:
                return property_state

            track_on_switch = self._device_switch_on(
                "TELESCOPE_TRACK_STATE", "TRACK_ON"
            )
            track_off_switch = self._device_switch_on(
                "TELESCOPE_TRACK_STATE", "TRACK_OFF"
            )
            if track_on_switch is not None:
                return track_on_switch
            if track_off_switch is not None:
                return not track_off_switch

            tracking_text = self._device_text_value("OnStep Status", "Tracking")
            tracking_lower = tracking_text.strip().lower()
            if tracking_lower in {"on", "tracking", "active"}:
                return True
            if tracking_lower in {"off", "idle", "not tracking", "inactive"}:
                return False

            if attempt < 2:
                time.sleep(0.2)
        return None

    def _confirm_tracking_state(self, enabled: bool, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            property_state = self._read_tracking_enabled_from_properties()
            if property_state is enabled:
                return True
            if property_state is None:
                cached_state = self._read_tracking_enabled()
                if cached_state is enabled:
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)

    def set_tracking(self, enabled: bool) -> bool:
        property_name = (
            "TELESCOPE_TRACK_STATE.TRACK_ON"
            if enabled
            else "TELESCOPE_TRACK_STATE.TRACK_OFF"
        )
        if not self._apply_indi_properties(
            [self._indi_property_on(property_name)],
            "connected" if self.connected else "idle",
            "Tracking enabled" if enabled else "Tracking disabled",
            "tracking_failed",
        ):
            if self._confirm_tracking_state(enabled):
                self._write_controller_status(
                    "connected" if self.connected else "idle",
                    "Tracking enabled" if enabled else "Tracking disabled",
                )
                self._console("Tracking\n" + ("on" if enabled else "off"))
                return True
            self._console("INDI tracking\nfailed")
            return False
        if not self._confirm_tracking_state(enabled):
            self._write_controller_status(
                "tracking_failed",
                (
                    "Tracking command was sent but driver readback did not "
                    f"confirm {'On' if enabled else 'Off'}"
                ),
            )
            self._console("INDI tracking\nmismatch")
            return False
        self._console("Tracking\n" + ("on" if enabled else "off"))
        return True

    def _align_session_status(self, state: str, message: str) -> None:
        self._multipoint_align_controller.set_status(state, message)
        self._multipoint_align = self._multipoint_align_controller.status()
        self._write_controller_status(
            "align_" + state,
            message,
        )

    def _current_align_session(self) -> Optional[dict[str, Any]]:
        self._multipoint_align = self._multipoint_align_controller.status()
        return self._multipoint_align_controller.active_session()

    def _current_pifinder_pointing_for_align(
        self,
    ) -> Optional[tuple[str, float, float]]:
        try:
            solution = self.shared_state.solution()
        except Exception:
            solution = None
        if solution is not None and solution.has_pointing():
            try:
                pointing = solution.pointing.aligned.estimate
                if pointing is None:
                    pointing = solution.pointing.aligned.solve
                if pointing is not None:
                    return "solve", float(pointing.RA) % 360.0, float(pointing.Dec)
            except (AttributeError, TypeError, ValueError):
                logger.debug(
                    "Could not read MFNavis solved pointing for multi-align",
                    exc_info=True,
                )

        # No IMU fallback: the helpers it relied on were removed when backlash
        # calibration moved to solved coordinates, and alignment needs solve
        # accuracy anyway. Without a solve there is no pointing to align with.
        return None

    def _sync_multipoint_location_time(self, session: dict[str, Any]) -> bool:
        # Multi-point alignment keeps the hard clock-trust gate that plain
        # slewing no longer has: the alignment model bakes in the LST, so a
        # provisional (untrusted) time would silently corrupt every point.
        if not self._manual_datetime_active() and not gps_time_sync.clock_is_trusted(
            check_chrony=True
        ):
            self._align_session_status(
                STATE_FAILED,
                "Multi-point alignment needs a synchronized clock (GPS/NTP) "
                "or a manually set time",
            )
            return False
        if not self.sync_location_time(
            reconnect_after=True,
            include_default_location=True,
        ):
            self._align_session_status(
                STATE_FAILED,
                "Could not sync location/time before multi-point alignment",
            )
            return False
        self._multipoint_align_controller.set_location_time_synced()
        return True

    def _onstep_native_alignment_active(self) -> bool:
        if not sys_utils.is_onstepx_device_name(self._indi_device_name()):
            return False

        for element_name in ("6", "7"):
            text_value = self._device_text_value("Align Process", element_name).strip()
            try:
                if int(text_value) > 0:
                    return True
            except (TypeError, ValueError):
                pass

        status_text = self._device_text_value("Align Process", "4")
        match = re.search(r"(\d)(\d)(\d)\s+Alignment", status_text or "")
        if not match:
            return False
        current_star = int(match.group(2))
        last_star = int(match.group(3))
        return current_star > 0 or last_star > 0

    def _reset_stale_onstep_alignment_for_multipoint(
        self, session: dict[str, Any]
    ) -> bool:
        if not self._onstep_native_alignment_active():
            session["onstep_native_align_reset"] = False
            return True

        onstep_cfg = self._onstep_connection_config()
        self._align_session_status(
            STATE_PREPARING,
            "Resetting stale OnStep native alignment before multi-point alignment",
        )
        logger.info("Resetting stale OnStep native alignment before multi-align")
        result = sys_utils.reset_onstep_alignment_exclusive(
            connection_type=onstep_cfg["connection_type"],
            network_host=onstep_cfg["network_host"],
            network_port=onstep_cfg["network_port"],
            serial_port=onstep_cfg["serial_port"],
            serial_baud=onstep_cfg.get("serial_baud", 9600),
            server_host=self.indi_host,
            server_port=self.indi_port,
        )
        session["onstep_native_align_reset"] = bool(result.get("ok"))
        session["onstep_native_align_reset_result"] = result
        if not result.get("ok"):
            error = result.get("stderr") or "Could not reset OnStep native alignment"
            logger.warning("Could not reset stale OnStep native alignment: %s", error)
            self._align_session_status(STATE_FAILED, error)
            return False

        self.disconnect()
        if not self.connect():
            self._align_session_status(
                STATE_FAILED,
                "Could not reconnect INDI after resetting OnStep native alignment",
            )
            return False
        return True

    def _sync_multipoint_mount_to_pifinder(self, session: dict[str, Any]) -> bool:
        pointing = self._current_pifinder_pointing_for_align()
        if pointing is None:
            self._align_session_status(
                STATE_FAILED,
                "No MFNavis solve available for alignment sync",
            )
            return False

        source, pifinder_ra, pifinder_dec = pointing
        mount_position = self._read_current_position()
        separation_arcmin = None
        if mount_position is not None:
            separation_arcmin = radec_separation_arcmin(
                mount_position[0],
                mount_position[1],
                pifinder_ra,
                pifinder_dec,
            )
        self._multipoint_align_controller.record_pifinder_sync(
            source,
            pifinder_ra,
            pifinder_dec,
            separation_arcmin,
        )

        if not self.sync_mount(
            pifinder_ra,
            pifinder_dec,
            sync_context={
                "origin": "multipoint_align_start",
                "pointing_source": source,
            },
        ):
            self._align_session_status(
                STATE_FAILED,
                "Could not sync mount coordinates to MFNavis before alignment",
            )
            return False

        if not self._verify_multipoint_mount_sync(
            session, "before native alignment start"
        ):
            return False

        self._multipoint_align_controller.mark_mount_synced()
        self._align_session_status(
            STATE_WAITING,
            f"Mount synced to MFNavis {source} before alignment",
        )

        return True

    def _verify_multipoint_mount_sync(
        self,
        session: dict[str, Any],
        phase: str,
        timeout: float = MULTIPOINT_ALIGN_SYNC_VERIFY_TIMEOUT_SECONDS,
        tolerance_arcmin: float = MULTIPOINT_ALIGN_SYNC_VERIFY_TOLERANCE_ARCMIN,
    ) -> bool:
        pifinder_ra = session.get("pifinder_sync_ra")
        pifinder_dec = session.get("pifinder_sync_dec")
        if pifinder_ra is None or pifinder_dec is None:
            self._align_session_status(
                STATE_FAILED,
                "No MFNavis pointing was recorded for alignment sync verification",
            )
            return False

        deadline = time.monotonic() + timeout
        last_position = None
        last_separation = None
        while time.monotonic() <= deadline:
            mount_position = self._read_current_position()
            if mount_position is not None:
                last_position = mount_position
                last_separation = radec_separation_arcmin(
                    mount_position[0],
                    mount_position[1],
                    float(pifinder_ra),
                    float(pifinder_dec),
                )
                if last_separation <= tolerance_arcmin:
                    self._multipoint_align_controller.record_mount_sync_verified(
                        True,
                        phase,
                        tolerance_arcmin,
                        mount_position,
                        last_separation,
                    )
                    return True
            time.sleep(0.25)

        self._multipoint_align_controller.record_mount_sync_verified(
            False,
            phase,
            tolerance_arcmin,
            last_position,
            last_separation,
        )
        if last_position is None:
            self._align_session_status(
                STATE_FAILED,
                f"Could not read mount coordinates {phase}",
            )
        else:
            self._align_session_status(
                STATE_FAILED,
                (
                    f"Mount coordinates no longer match MFNavis {phase}; "
                    f"separation {last_separation:.1f} arcmin"
                ),
            )
        return False

    def start_mount_alignment_session(self, points: Any) -> bool:
        total_points = clamp_align_points(points)
        if not self.connect() or self.client is None or self.device is None:
            logger.warning("Could not connect before starting mount alignment session")
            return False

        def set_switch(property_name: str, element_name: str) -> bool:
            try:
                return bool(
                    self.client.set_switch(
                        self.device,
                        property_name,
                        element_name,
                        timeout=1.0,
                    )
                )
            except TypeError:
                return bool(
                    self.client.set_switch(
                        self.device,
                        property_name,
                        element_name,
                    )
                )

        if not set_switch("AlignStars", str(total_points)):
            logger.info(
                "INDI mount does not expose AlignStars; "
                "continuing MFNavis multi-point alignment without mount session"
            )
            return False

        if not set_switch("NewAlignStar", "0"):
            logger.info(
                "INDI mount does not expose NewAlignStar start; "
                "continuing MFNavis multi-point alignment without mount session"
            )
            return False

        logger.info(
            "Started INDI mount native alignment session for %d point(s)",
            total_points,
        )
        return True

    def accept_mount_alignment_point(self) -> bool:
        if not self.connect() or self.client is None or self.device is None:
            logger.warning("Could not connect before accepting mount alignment point")
            return False

        try:
            accepted = bool(
                self.client.set_switch(
                    self.device,
                    "NewAlignStar",
                    "1",
                    timeout=2.0,
                )
            )
        except TypeError:
            accepted = bool(
                self.client.set_switch(
                    self.device,
                    "NewAlignStar",
                    "1",
                )
            )

        if not accepted:
            logger.warning("INDI mount rejected native alignment point accept")
            return False

        logger.info("Accepted current INDI mount native alignment point")
        return True

    def _set_current_align_star(
        self, session: dict[str, Any], star: dict[str, Any]
    ) -> dict[str, Any]:
        return self._multipoint_align_controller.set_current_target(star)

    def _align_auto_star(self, session: dict[str, Any]) -> dict[str, Any]:
        min_altitude, max_altitude = self._alignment_altitude_limits()
        completed = session.get("completed", [])
        used_names = {str(star.get("name", "")).casefold() for star in completed}
        reference = session.get("auto_reference")
        try:
            latitude, longitude, elevation, dt = self._shared_location_time_values(
                include_default_location=True
            )
            if latitude is None or longitude is None or dt is None:
                raise ValueError("No locked location/time for altitude filtering")
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            if getattr(dt, "tzinfo", None) is None:
                dt = dt.replace(tzinfo=timezone.utc)
            calc_utils.sf_utils.set_location(latitude, longitude, elevation or 0.0)
            visible_candidates = []
            for star in BRIGHT_ALIGN_STARS:
                if star["name"].casefold() in used_names:
                    continue
                alt, _az = calc_utils.sf_utils.radec_to_altaz(
                    float(star["ra"]), float(star["dec"]), dt
                )
                if min_altitude <= alt <= max_altitude:
                    visible_candidates.append((alt, star))
            if visible_candidates:
                visible_stars = [star for _alt, star in visible_candidates]
                if reference:
                    return nearest_align_star(
                        float(reference["ra"]),
                        float(reference["dec"]),
                        completed,
                        visible_stars,
                    )
                return dict(max(visible_candidates, key=lambda item: item[0])[1])
        except Exception:
            logger.debug(
                "Could not altitude-filter auto alignment stars", exc_info=True
            )
        if reference:
            return nearest_align_star(
                float(reference["ra"]),
                float(reference["dec"]),
                completed,
            )
        return next_align_star(completed)

    def _align_goto_current_star(self, session: dict[str, Any]) -> bool:
        current_star = session.get("current_star")
        if not current_star:
            self._align_session_status(STATE_WAITING, "Select an alignment star")
            return False

        altaz = self._radec_to_altaz(
            float(current_star["ra"]),
            float(current_star["dec"]),
        )
        min_altitude, max_altitude = self._alignment_altitude_limits()
        if altaz is not None and altaz[0] < min_altitude:
            self._multipoint_align_controller.clear_current_target()
            self._align_session_status(
                STATE_WAITING,
                (
                    f"{current_star['name']} is below the "
                    f"{min_altitude:g} deg alignment limit; "
                    "select another star"
                ),
            )
            self._console("Align star\nbelow horizon")
            return False
        if altaz is not None and altaz[0] > max_altitude:
            self._multipoint_align_controller.clear_current_target()
            self._align_session_status(
                STATE_WAITING,
                (
                    f"{current_star['name']} is above the "
                    f"{max_altitude:g} deg alignment limit; "
                    "select another star"
                ),
            )
            self._console("Align star\nnear zenith")
            return False

        self._align_session_status(STATE_MOVING, f"GoTo {current_star['name']} sent")
        logger.info(
            "Multi-align GoTo requested for %s: RA %.6f Dec %.6f",
            current_star["name"],
            float(current_star["ra"]) % 360.0,
            float(current_star["dec"]),
        )
        if not self.goto_target(
            float(current_star["ra"]),
            float(current_star["dec"]),
            refine_after_goto=False,
        ):
            logger.warning(
                "Multi-align GoTo failed for %s: RA %.6f Dec %.6f",
                current_star["name"],
                float(current_star["ra"]) % 360.0,
                float(current_star["dec"]),
            )
            self._multipoint_align_controller.clear_current_target()
            self._align_session_status(
                STATE_WAITING,
                f"Could not GoTo {current_star['name']}; select another star",
            )
            self._write_controller_status(
                "align_goto_failed",
                f"Could not GoTo {current_star['name']}; select another star",
            )
            self._console("Align GoTo\nfailed")
            return False

        self._multipoint_align_controller.mark_current_target_sent()
        self._align_session_status(
            STATE_ADJUST,
            (
                f"Center {current_star['name']} manually, "
                "then confirm the alignment point"
            ),
        )
        self._console(
            f"Align {session['completed_points'] + 1}\n{current_star['name']}"
        )
        return True

    def start_multipoint_align(
        self,
        mode: str = "manual",
        points: Any = None,
        star_name: str | None = None,
        target_ra: Any = None,
        target_dec: Any = None,
    ) -> bool:
        mode = (mode or "manual").strip().lower()
        if mode not in ALIGN_MODES:
            mode = ALIGN_MODE_MANUAL
        total_points = clamp_align_points(points)
        session = self._multipoint_align_controller.start(mode, total_points)
        self._multipoint_align = session
        self._align_session_status(STATE_PREPARING, "Preparing multi-point alignment")

        if not self._sync_multipoint_location_time(session):
            self._multipoint_align_controller.fail(session["message"])
            return False

        if not self._reset_stale_onstep_alignment_for_multipoint(session):
            self._multipoint_align_controller.fail(session["message"])
            return False

        if not self._sync_multipoint_mount_to_pifinder(session):
            self._multipoint_align_controller.fail(session["message"])
            return False

        # OnStep's native :A<n># alignment start resets the mount home frame.
        # Keep it deferred so the star-selection/GoTo phase starts with the
        # mount coordinates synchronized to PiFinder.
        self._multipoint_align_controller.record_native_alignment_started(False)
        session["mount_align_deferred"] = True
        session["mount_align_message"] = (
            "Mount native alignment start deferred to preserve MFNavis sync"
        )

        if target_ra is not None and target_dec is not None:
            try:
                self._multipoint_align_controller.set_auto_reference(
                    float(target_ra), float(target_dec)
                )
            except (TypeError, ValueError):
                session["auto_reference"] = None
        elif session.get("pifinder_sync_ra") is not None:
            self._multipoint_align_controller.set_auto_reference(
                float(session["pifinder_sync_ra"]),
                float(session["pifinder_sync_dec"]),
            )

        if mode == ALIGN_MODE_AUTO:
            star = self._align_auto_star(session)
            self._set_current_align_star(session, star)
            self._align_session_status(
                STATE_MOVING, f"Auto alignment point 1/{total_points}: {star['name']}"
            )
            return self._align_goto_current_star(session)

        if star_name:
            return self.select_multipoint_align_star(star_name, goto=False)

        self._align_session_status(
            STATE_WAITING, f"Manual alignment 0/{total_points}: select a star"
        )
        self._console("Multi align\nselect star")
        return True

    def select_multipoint_align_star(self, star_name: str, goto: bool = False) -> bool:
        session = self._current_align_session()
        if session is None:
            session_started = self.start_multipoint_align(
                mode="manual", points=None, star_name=None
            )
            if not session_started:
                return False
            session = self._current_align_session()
        if session is None:
            return False

        star = get_align_star(star_name)
        if star is None:
            self._align_session_status(
                STATE_FAILED, f"Unknown alignment star: {star_name}"
            )
            return False

        session["mode"] = ALIGN_MODE_MANUAL
        self._set_current_align_star(session, star)
        logger.info(
            "Multi-align selected star %s, goto=%s, point %d/%d",
            star["name"],
            goto,
            int(session.get("completed_points", 0)) + 1,
            int(session.get("total_points", 0)),
        )
        if goto:
            return self._align_goto_current_star(session)

        self._align_session_status(
            STATE_ADJUST,
            (
                f"Selected {star['name']}; center the target manually, "
                "then confirm the alignment point"
            ),
        )
        self._console(f"Align star\n{star['name']}")
        return True

    def select_multipoint_align_target(
        self,
        ra_deg: Any,
        dec_deg: Any,
        name: str | None = None,
        goto: bool = True,
    ) -> bool:
        session = self._current_align_session()
        if session is None:
            return False
        try:
            ra = float(ra_deg) % 360.0
            dec = float(dec_deg)
        except (TypeError, ValueError):
            self._align_session_status(STATE_FAILED, "Invalid alignment target")
            return False

        current_star = self._set_current_align_star(
            session,
            {
                "name": name or f"SkySafari Target {session['completed_points'] + 1}",
                "ra": ra,
                "dec": dec,
                "mag": None,
            },
        )
        session["mode"] = session.get("mode") or ALIGN_MODE_MANUAL
        if goto:
            return self._align_goto_current_star(session)

        self._align_session_status(
            STATE_ADJUST,
            (
                f"Selected {current_star['name']}; center the target manually, "
                "then confirm the alignment point"
            ),
        )
        self._console(f"Align target\n{current_star['name']}")
        return True

    def confirm_multipoint_align(
        self,
        ra_deg: Any = None,
        dec_deg: Any = None,
        source: str = "ui",
    ) -> bool:
        session = self._current_align_session()
        if session is None:
            self._align_session_status(STATE_IDLE, "No active multi-point alignment")
            return False

        current_star = session.get("current_star")
        if ra_deg is not None and dec_deg is not None:
            try:
                ra_deg = float(ra_deg) % 360.0
                dec_deg = float(dec_deg)
            except (TypeError, ValueError):
                self._align_session_status(
                    STATE_FAILED, "Invalid alignment coordinates"
                )
                return False
            if not current_star:
                current_star = self._set_current_align_star(
                    session,
                    {
                        "name": f"SkySafari Target {session['completed_points'] + 1}",
                        "ra": ra_deg,
                        "dec": dec_deg,
                        "mag": None,
                    },
                )

        if not current_star:
            self._align_session_status(STATE_WAITING, "Select an alignment star first")
            return False

        ra = float(current_star["ra"]) % 360.0
        dec = float(current_star["dec"])
        mount_align_started = bool(session.get("mount_align_started"))
        if not current_star.get("target_sent"):
            self._align_session_status(
                STATE_FAILED,
                (
                    f"{current_star['name']} target was not sent to the mount; "
                    "GoTo the alignment target before confirming"
                ),
            )
            return False
        if mount_align_started:
            if not self.accept_mount_alignment_point():
                self._align_session_status(
                    STATE_FAILED, f"Could not accept {current_star['name']}"
                )
                return False
        elif not self.sync_mount(
            ra,
            dec,
            sync_context={
                "origin": "multipoint_align_confirm",
                "pointing_source": "align_target",
            },
        ):
            self._align_session_status(
                STATE_FAILED, f"Could not confirm {current_star['name']}"
            )
            return False

        self._multipoint_align_controller.record_current_point(
            source,
            "A+" if mount_align_started else "sync",
        )
        completed = list(session.get("completed", []))

        if len(completed) >= int(session["total_points"]):
            self._multipoint_align_controller.complete(
                f"Multi-point alignment complete: {len(completed)} points"
            )
            self._console("Multi align\ncomplete")
            return True

        if session.get("mode") == ALIGN_MODE_AUTO:
            star = self._align_auto_star(session)
            self._set_current_align_star(session, star)
            self._align_session_status(
                STATE_MOVING,
                (
                    f"Auto alignment point {len(completed) + 1}/"
                    f"{session['total_points']}: {star['name']}"
                ),
            )
            return self._align_goto_current_star(session)

        self._align_session_status(
            STATE_WAITING,
            (
                f"Alignment point {len(completed)}/{session['total_points']} saved; "
                "select the next star"
            ),
        )
        self._console(f"Align point\n{len(completed)} saved")
        return True

    def cancel_multipoint_align(self) -> bool:
        self._multipoint_align_controller.cancel()
        self._multipoint_align = self._multipoint_align_controller.status()
        self._write_controller_status(
            "align_" + STATE_CANCELLED, "Multi-point alignment cancelled"
        )
        self._console("Multi align\ncancelled")
        return True

    def clear_multipoint_align_target(self) -> bool:
        session = self._multipoint_align_controller.active_session()
        if not session:
            return False
        self._multipoint_align_controller.clear_current_target()
        self._align_session_status(STATE_WAITING, "Select an alignment star")
        self._write_controller_status("align_target_cleared", "Select another star")
        return True

    def change_slew_rate(self, delta: int) -> bool:
        self.refresh_slew_rate()
        return self.set_slew_rate(self.slew_rate + delta)

    def handle_command(self, command: Any) -> bool:
        if not isinstance(command, dict):
            logger.warning("Ignoring mount-control command: %r", command)
            return True

        command_type = command.get("type")
        if command_type in {
            "init",
            "goto_target",
            "sync_and_goto",
            "manual_movement",
            "sync",
            "set_tracking",
            "reboot_mount",
            "restart_driver",
            "park_action",
            "connection_config_changed",
        }:
            self.error_notifier.reset()
        if command_type == "shutdown":
            return False
        if command_type == "init":
            self.connect()
        elif command_type == "connection_config_changed":
            self.update_connection_config(
                command.get("server_host"), command.get("server_port")
            )
        elif command_type == "discover_serial_connection":
            self.discover_onstep_serial_connection()
        elif command_type == "restart_driver":
            self.restart_driver()
        elif command_type == "reboot_mount":
            self.reboot_mount()
        elif command_type == "sync":
            sync_context = {
                key: command.get(key)
                for key in ("origin", "pointing_source", "solve_age_seconds")
                if command.get(key) is not None
            }
            self.sync_mount(
                float(command["ra"]),
                float(command["dec"]),
                sync_context=sync_context or None,
            )
        elif command_type == "goto_target":
            self.goto_target(
                float(command["ra"]),
                float(command["dec"]),
                bool(command.get("refine_after_goto", False)),
                command.get("refine_accuracy_arcmin"),
            )
        elif command_type == "sync_and_goto":
            self.begin_sync_and_goto(command)
        elif command_type == "toggle_guide_correction":
            self.toggle_guide_correction(
                command.get("enabled"),
                command.get("target_ra"),
                command.get("target_dec"),
                command.get("accuracy_arcmin"),
                manual_approach=bool(command.get("manual_approach", False)),
            )
        elif command_type == "stop_movement":
            self.stop_mount()
        elif command_type == "set_tracking":
            # Joystick "Tracking Off" button. GoTo/sync paths re-enable
            # tracking themselves, so an off state lasts until the next GoTo
            # or an explicit on.
            self.set_tracking(bool(command.get("enabled", True)))
        elif command_type == "manual_movement":
            self.manual_move(
                str(command.get("direction", "")),
                command.get("lease_seconds"),
            )
        elif command_type == "manual_movement_keepalive":
            self.manual_motion_keepalive(
                str(command.get("direction", "")),
                command.get("lease_seconds"),
            )
        elif command_type == "increase_slew_rate":
            changed = self.change_slew_rate(1)
            if changed and command.get("notify_ui"):
                self.console_queue.put(("slew_rate_popup", self.slew_rate))
        elif command_type == "reduce_slew_rate":
            changed = self.change_slew_rate(-1)
            if changed and command.get("notify_ui"):
                self.console_queue.put(("slew_rate_popup", self.slew_rate))
        elif command_type == "set_slew_rate":
            self.set_slew_rate(int(command.get("rate", self.slew_rate)))
        elif command_type == "set_guide_rate":
            self.set_guide_rate(command["rate"])
        elif command_type == "set_track_freq":
            self.set_track_frequency(
                float(command["hz"]),
                str(command.get("label", "")),
            )
        elif command_type == "reset_track_freq":
            self.reset_track_frequency()
        elif command_type == "refresh_slew_rate":
            self.refresh_slew_rate()
        elif command_type == "refresh_backlash":
            self.refresh_backlash()
        elif command_type == "set_backlash":
            self.set_backlash(command.get("ra"), command.get("de"))
        elif command_type == "auto_backlash":
            self.auto_calculate_backlash(
                str(command.get("axis", "")),
                str(command.get("mode", BACKLASH_AUTO_MODE_COMPASS_GOTO)),
                command.get("repeats"),
            )
        elif command_type == "backlash_compass_continue":
            self.continue_backlash_compass_goto_loop()
        elif command_type == "backlash_compass_stop":
            self.stop_backlash_auto()
        elif command_type == "multipoint_align_start":
            self.start_multipoint_align(
                str(command.get("mode", "manual")),
                command.get("points"),
                command.get("star_name"),
                command.get("target_ra"),
                command.get("target_dec"),
            )
        elif command_type == "multipoint_align_select_star":
            self.select_multipoint_align_star(
                str(command.get("star_name", "")),
                bool(command.get("goto", False)),
            )
        elif command_type == "multipoint_align_goto_target":
            self.select_multipoint_align_target(
                command.get("ra"),
                command.get("dec"),
                command.get("name"),
                True,
            )
        elif command_type == "multipoint_align_confirm":
            self.confirm_multipoint_align(
                command.get("ra"),
                command.get("dec"),
                str(command.get("source", "ui")),
            )
        elif command_type == "multipoint_align_cancel":
            self.cancel_multipoint_align()
        elif command_type == "multipoint_align_clear_target":
            self.clear_multipoint_align_target()
        elif command_type == "sync_location_time":
            self.sync_location_time(
                include_default_location=bool(
                    command.get("include_default_location", False)
                ),
                latitude=command.get("latitude"),
                longitude=command.get("longitude"),
                elevation=command.get("elevation"),
            )
        elif command_type == "park_action":
            self.park_action(str(command.get("action", "")))
        else:
            logger.warning("Unknown mount-control command: %s", command_type)
        return True

    def run(self) -> None:
        self._write_controller_status(
            "idle",
            f"Mount-control process ready for {self.indi_host}:{self.indi_port}",
        )
        self.reconcile_onstep_connection_config()

        running = True
        next_auto_connect_at = time.monotonic() + AUTO_CONNECT_START_DELAY
        while running:
            self._check_initial_location_sync()
            self._check_usb_serial_reinsert()
            self._check_manual_motion_deadline()
            self._publish_manual_motion_progress()
            self._check_goto_motion()
            self._check_pending_goto_refine()
            self._check_guide_correction()
            self._check_slew_rate_reassert()
            try:
                command = self.mount_queue.get(
                    timeout=self._manual_motion_queue_timeout()
                )
                running = self.handle_command(command)
                if running:
                    self._check_pending_sync_goto()
            except queue.Empty:
                self._check_usb_serial_reinsert()
                self._check_manual_motion_deadline()
                self._publish_manual_motion_progress()
                self._check_goto_motion()
                self._check_pending_sync_goto()
                self._check_pending_goto_refine()
                self._check_guide_correction()
                self._check_slew_rate_reassert()
                self._reassert_track_frequency()
                now = time.monotonic()
                if (
                    self._connection_config_ready
                    and self._usb_auto_connect_allowed()
                    and not self.connected
                    and now >= next_auto_connect_at
                ):
                    first_attempt = self._auto_connect_failures == 0
                    if first_attempt:
                        logger.info("Attempting automatic INDI mount connection")
                    with self._quiet_retry_logging(quiet=not first_attempt):
                        connect_ok = self.connect(announce=False)
                    if connect_ok:
                        if self._auto_connect_failures:
                            logger.info(
                                "INDI mount connected after %d suppressed retries",
                                self._auto_connect_failures,
                            )
                        self._auto_connect_failures = 0
                        self._console("INDI mount\nconnected")
                    else:
                        self._auto_connect_failures += 1
                        if first_attempt:
                            logger.warning(
                                "INDI mount connection failed; retrying every "
                                "%.0f s with repeat warnings suppressed until "
                                "the state changes",
                                AUTO_CONNECT_RETRY_INTERVAL,
                            )
                    next_auto_connect_at = now + AUTO_CONNECT_RETRY_INTERVAL
                self._write_status_heartbeat()
                continue
            except Exception as exc:
                logger.exception("Mount-control command failed")
                self._write_controller_status("error", str(exc))
                self._console("INDI mount\ncommand failed")

        self.disconnect()


def run(
    mount_queue: Queue,
    console_queue: Queue,
    shared_state,
    log_queue: Queue,
    imu_command_queue: Optional[Queue] = None,
    indi_host: str = "localhost",
    indi_port: int = 7624,
) -> None:
    """Process entry point used by ``main.py``."""
    MultiprocLogging.configurer(log_queue)
    controller = MountControlIndi(
        mount_queue,
        console_queue,
        shared_state,
        imu_command_queue=imu_command_queue,
        indi_host=indi_host,
        indi_port=indi_port,
    )
    controller.run()
