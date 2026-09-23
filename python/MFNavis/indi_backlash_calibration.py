#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Backlash calibration support for the INDI mount-control bridge.

This module intentionally keeps the automatic backlash measurement sequence in
one place. ``MountControlIndi`` supplies the hardware-facing operations
(connect, GoTo, tracking, coordinate conversion inputs, and status publishing),
while this mixin owns backlash state transitions, record capture, filtering, and
recommendation generation.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Optional

from PiFinder import calc_utils, config, sys_utils
from PiFinder import utils

logger = logging.getLogger("MountControl.Indi.Backlash")

STOP_REQUEST_FILE = utils.runtime_dir / "mount_control_stop_request.json"
POINTING_STATUS_FILE = utils.runtime_dir / "pointing_coordinate_status.json"
BACKLASH_MIN_VALUE = 0
BACKLASH_MAX_VALUE = 3600
BACKLASH_SOLVED_STATUS_MAX_AGE_SECONDS = 10.0
BACKLASH_SOLVED_WAIT_SECONDS = 15.0
BACKLASH_AUTO_GOTO_TIMEOUT_SECONDS = 90.0
BACKLASH_AUTO_GOTO_POLL_SECONDS = 0.25
BACKLASH_AUTO_GOTO_TARGET_TOLERANCE_DEG = 0.5
BACKLASH_AUTO_SAFE_MIN_ALT_DEG = 15.0
BACKLASH_AUTO_SAFE_MAX_ALT_DEG = 75.0
BACKLASH_AUTO_MODE_COMPASS_GOTO = "compass_goto_loop"
BACKLASH_AUTO_MODES = {
    BACKLASH_AUTO_MODE_COMPASS_GOTO,
}
BACKLASH_COMPASS_DIFF_REJECT_ARCSEC = 3600
BACKLASH_COMPASS_TRIM_FRACTION = 0.30
BACKLASH_COMPASS_GOTO_OFFSET_DEG = 2.0
BACKLASH_COMPASS_GOTO_REPEATS = 10
BACKLASH_COMPASS_GOTO_SETTLE_SECONDS = 0.5
BACKLASH_COMPASS_GOTO_BETWEEN_SECONDS = 1.0
BACKLASH_COMPASS_GOTO_TIMEOUT_SECONDS = 180.0
BACKLASH_GOTO_RETRY_AFTER_SECONDS = 8.0
BACKLASH_GOTO_MAX_RETRIES = 3
GOTO_COMPLETE_MIN_SECONDS = 1.0


def _as_float(value: Any) -> float:
    """float() over an Any/Optional value; raises TypeError/ValueError as float()."""
    return float(value)


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


class BacklashCalibrationMixin:
    """Mixin that owns INDI backlash read/write and automatic calibration."""

    # State this mixin owns; the host initializes it in __init__.
    backlash_ra: Optional[int]
    backlash_de: Optional[int]
    _backlash_auto: Optional[dict[str, Any]]
    _backlash_stop_seen_at: float

    if TYPE_CHECKING:
        # Provided by the host class (MountControlIndi); declared for the type
        # checker only. The mixin is never instantiated on its own.
        indi_host: str
        indi_port: int
        connected: bool
        _console: Callable[..., Any]
        _write_controller_status: Callable[..., Any]
        _home_park_status_fields: Callable[..., Any]
        _indi_device_name: Callable[..., Any]
        _indi_property_name: Callable[..., Any]
        _indi_mount_is_busy: Callable[..., Any]
        _apply_indi_backlash: Callable[..., Any]
        _read_current_position: Callable[..., Any]
        _read_tracking_enabled: Callable[..., Any]
        _shared_location_time_values: Callable[..., Any]
        _goto_motion: Optional[dict[str, Any]]
        _goto_completion_ready: Callable[..., Any]
        _complete_goto_motion: Callable[..., Any]
        set_tracking: Callable[..., Any]
        stop_mount: Callable[..., Any]
        goto_target: Callable[..., Any]
        sync_mount: Callable[..., Any]
        connect: Callable[..., Any]
        update: Callable[..., Any]

    def _backlash_stop_request_file(self):
        for module_name in (type(self).__module__, "PiFinder.mountcontrol_indi"):
            owner_module = sys.modules.get(module_name)
            if owner_module is not None and hasattr(owner_module, "STOP_REQUEST_FILE"):
                return getattr(owner_module, "STOP_REQUEST_FILE")
        return STOP_REQUEST_FILE

    def _validate_backlash_value(self, value: Any) -> int:
        try:
            backlash = int(float(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("Backlash must be a number") from exc
        if not BACKLASH_MIN_VALUE <= backlash <= BACKLASH_MAX_VALUE:
            raise ValueError(
                f"Backlash must be between {BACKLASH_MIN_VALUE} and {BACKLASH_MAX_VALUE}"
            )
        return backlash

    def _read_float_property(self, properties: dict[str, str], property_names):
        if isinstance(property_names, str):
            property_names = (property_names,)
        for property_name in property_names:
            try:
                value = properties.get(self._indi_property_name(property_name))
                if value in (None, ""):
                    continue
                return int(_as_float(value))
            except (TypeError, ValueError):
                continue
        return None

    def refresh_backlash(self) -> tuple[Optional[int], Optional[int]]:
        properties = sys_utils.get_indi_onstep_properties(
            server_host=self.indi_host,
            server_port=self.indi_port,
            device_name=self._indi_device_name(),
        )
        self.backlash_de = self._read_float_property(
            properties, sys_utils.ONSTEP_BACKLASH_DE_FALLBACK_PROPERTIES
        )
        self.backlash_ra = self._read_float_property(
            properties, sys_utils.ONSTEP_BACKLASH_RA_FALLBACK_PROPERTIES
        )
        self._write_controller_status(
            "connected" if self.connected else "idle",
            "Backlash values refreshed",
        )
        return self.backlash_ra, self.backlash_de

    def _apply_backlash_values(self, backlash_ra: int, backlash_de: int) -> bool:
        try:
            result = self._apply_indi_backlash(backlash_ra, backlash_de)
        except Exception as exc:
            logger.exception("INDI backlash vector update failed")
            self._write_controller_status("backlash_failed", str(exc))
            return False

        if not result.get("ok"):
            error = result.get("stderr") or result.get("stdout") or "Backlash failed"
            logger.warning("INDI backlash returned failure: %s", error)
            self._write_controller_status("backlash_failed", error)
            return False

        self.backlash_ra = backlash_ra
        self.backlash_de = backlash_de
        return True

    def set_backlash(self, ra_value: Any, de_value: Any) -> bool:
        backlash_ra = self._validate_backlash_value(ra_value)
        backlash_de = self._validate_backlash_value(de_value)
        if not self._apply_backlash_values(backlash_ra, backlash_de):
            self._console("Backlash\nsave failed")
            return False

        self._backlash_auto = None
        self._write_controller_status(
            "connected" if self.connected else "idle",
            f"Backlash saved RA {backlash_ra} DE {backlash_de}",
        )
        self._console("Backlash\nsaved")
        return True

    def _backlash_auto_status(self, state: str, message: str, **extra: Any) -> None:
        if self._backlash_auto is None:
            self._backlash_auto = {}
        self._backlash_auto.update(
            {
                "state": state,
                "message": message,
                "updated": time.time(),
            }
        )
        self._backlash_auto.update(extra)
        self._write_controller_status(f"backlash_auto_{state}", message)

    def _clear_backlash_stop_request(self) -> None:
        try:
            self._backlash_stop_request_file().unlink(missing_ok=True)
        except OSError:
            logger.debug("Could not clear backlash stop request", exc_info=True)

    def _backlash_stop_requested(self) -> bool:
        try:
            with open(self._backlash_stop_request_file(), encoding="utf-8") as stop_in:
                payload = json.load(stop_in)
        except FileNotFoundError:
            return False
        except (json.JSONDecodeError, OSError):
            logger.debug("Could not read backlash stop request", exc_info=True)
            return True

        requested_at = payload.get("requested_at")
        try:
            requested_at = float(requested_at)
        except (TypeError, ValueError):
            requested_at = time.time()
        if requested_at <= self._backlash_stop_seen_at:
            return False
        self._backlash_stop_seen_at = requested_at
        return True

    def stop_backlash_auto(self, message: str = "Backlash motion test stopped") -> bool:
        self.stop_mount()
        self.set_tracking(False)
        if (
            not self._backlash_auto
            or self._backlash_auto.get("auto_mode") != BACKLASH_AUTO_MODE_COMPASS_GOTO
        ):
            self._backlash_auto = {
                "axis": "Mount frame",
                "state": "stopped",
                "message": message,
                "auto_mode": BACKLASH_AUTO_MODE_COMPASS_GOTO,
                "mode": "motion_test",
                "stopped_at": time.time(),
            }
            self._write_controller_status("backlash_auto_stopped", message)
        else:
            self._backlash_auto_status(
                "stopped",
                message,
                phase="stopped",
                stopped_at=time.time(),
            )
        self._clear_backlash_stop_request()
        self._console("Backlash test\nstopped")
        return True

    def _abort_backlash_if_requested(self, phase_label: str) -> bool:
        if not self._backlash_stop_requested():
            return False
        self.stop_backlash_auto(f"{phase_label}: backlash motion test stopped")
        return True

    def _backlash_cancelable_sleep(self, seconds: float, phase_label: str) -> bool:
        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            if self._abort_backlash_if_requested(phase_label):
                return False
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
        return not self._abort_backlash_if_requested(phase_label)

    def _read_pointing_coordinate_status(self) -> Optional[dict[str, Any]]:
        try:
            with open(POINTING_STATUS_FILE, encoding="utf-8") as status_in:
                payload = json.load(status_in)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError):
            logger.debug("Could not read pointing coordinate status", exc_info=True)
            return None
        return payload if isinstance(payload, dict) else None

    def _current_solved_pointing(
        self,
        *,
        min_timestamp: Optional[float] = None,
        max_age_seconds: float = BACKLASH_SOLVED_STATUS_MAX_AGE_SECONDS,
    ) -> Optional[dict[str, Any]]:
        status = self._read_pointing_coordinate_status()
        if not status:
            return None
        solved = status.get("solved")
        if not isinstance(solved, dict) or not bool(solved.get("valid")):
            return None
        try:
            ra = _as_float(solved.get("ra"))
            dec = _as_float(solved.get("dec"))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(ra) or not math.isfinite(dec) or dec < -90.0 or dec > 90.0:
            return None

        timestamp = solved.get("timestamp")
        if timestamp in (None, ""):
            timestamp = status.get("updated")
        try:
            timestamp = _as_float(timestamp)
        except (TypeError, ValueError):
            return None
        now = time.time()
        if now - timestamp > max_age_seconds:
            return None
        if min_timestamp is not None and timestamp < float(min_timestamp):
            return None

        alt = solved.get("alt")
        az = solved.get("az")
        try:
            alt = None if alt in (None, "") else _as_float(alt)
        except (TypeError, ValueError):
            alt = None
        try:
            az = None if az in (None, "") else _as_float(az) % 360.0
        except (TypeError, ValueError):
            az = None

        return {
            "ra": ra % 360.0,
            "dec": dec,
            "altitude": alt,
            "azimuth": az,
            "timestamp": timestamp,
            "source": solved.get("source") or "solve",
            "quality": solved.get("quality"),
            "reason": solved.get("reason", ""),
            "status_updated": status.get("updated"),
        }

    def _wait_for_solved_pointing(
        self,
        phase_label: str,
        *,
        min_timestamp: Optional[float] = None,
        timeout: float = BACKLASH_SOLVED_WAIT_SECONDS,
    ) -> Optional[dict[str, Any]]:
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() <= deadline:
            if self._abort_backlash_if_requested(phase_label):
                return None
            solved = self._current_solved_pointing(min_timestamp=min_timestamp)
            if solved is not None:
                return solved
            self._backlash_auto_status(
                "waiting_for_solved",
                f"{phase_label}: waiting for fresh solved coordinate",
                phase=phase_label,
                solved_required=True,
                solved_min_timestamp=min_timestamp,
            )
            time.sleep(0.5)
        return None

    def _percentile_value(self, sorted_values: list[int], fraction: float) -> int:
        if not sorted_values:
            return 0
        index = min(
            len(sorted_values) - 1,
            max(0, math.ceil((len(sorted_values) - 1) * fraction)),
        )
        return int(sorted_values[index])

    def _spread_percent(
        self, min_value: float, max_value: float, base_value: float
    ) -> float:
        if base_value <= 0:
            return 0.0
        return round(((max_value - min_value) / base_value) * 100.0, 1)

    def _filter_compass_backlash_values(self, values: list[int]) -> dict[str, Any]:
        if not values:
            return {
                "values": [],
                "excluded_values": [],
                "raw_values": [],
                "raw_min": 0,
                "raw_max": 0,
                "min": 0,
                "max": 0,
                "mean": 0.0,
                "median": 0.0,
                "p75": 0,
                "p90": 0,
                "trimmed_mean": 0.0,
                "trim_low_count": 0,
                "trim_high_count": 0,
                "trim_fraction": BACKLASH_COMPASS_TRIM_FRACTION,
                "spread_percent": 0.0,
                "raw_spread_percent": 0.0,
                "sample_count": 0,
                "filtered_count": 0,
                "excluded_count": 0,
                "filter_strategy": "reject_1deg_then_middle_40_mean",
            }

        sorted_all_values = sorted(values)
        raw_min_value = min(sorted_all_values)
        raw_max_value = max(sorted_all_values)
        trim_count = int(len(sorted_all_values) * BACKLASH_COMPASS_TRIM_FRACTION)
        if trim_count * 2 >= len(sorted_all_values):
            trim_count = 0
        trimmed_values = sorted_all_values[
            trim_count : len(sorted_all_values) - trim_count
            if trim_count
            else len(sorted_all_values)
        ]
        if not trimmed_values:
            trimmed_values = sorted_all_values
            trim_count = 0
        mean_value = statistics.mean(trimmed_values)
        median_value = statistics.median(trimmed_values)
        max_value = max(trimmed_values)
        min_value = min(trimmed_values)
        p75_value = self._percentile_value(trimmed_values, 0.75)
        p90_value = self._percentile_value(trimmed_values, 0.90)
        excluded_values = list(sorted_all_values)
        for value in trimmed_values:
            if value in excluded_values:
                excluded_values.remove(value)
        return {
            "values": trimmed_values,
            "excluded_values": excluded_values,
            "raw_values": sorted_all_values,
            "raw_min": raw_min_value,
            "raw_max": raw_max_value,
            "min": min_value,
            "max": max_value,
            "mean": round(mean_value, 1),
            "median": round(float(median_value), 1),
            "p75": p75_value,
            "p90": p90_value,
            "trimmed_mean": round(mean_value, 1),
            "trim_low_count": trim_count,
            "trim_high_count": trim_count,
            "trim_fraction": BACKLASH_COMPASS_TRIM_FRACTION,
            "spread_percent": self._spread_percent(min_value, max_value, mean_value),
            "raw_spread_percent": self._spread_percent(
                raw_min_value, raw_max_value, mean_value
            ),
            "sample_count": len(sorted_all_values),
            "filtered_count": len(trimmed_values),
            "excluded_count": len(excluded_values),
            "filter_strategy": "reject_1deg_then_middle_40_mean",
        }

    def _solved_status_payload(
        self, solved: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        if solved is None:
            solved = self._current_solved_pointing()
        if solved is None:
            return {
                "available": False,
                "valid": False,
                "source": None,
                "timestamp": None,
            }
        return {
            "available": True,
            "valid": True,
            "source": solved.get("source"),
            "quality": solved.get("quality"),
            "ra": solved.get("ra"),
            "dec": solved.get("dec"),
            "altitude": solved.get("altitude"),
            "azimuth": solved.get("azimuth"),
            "timestamp": solved.get("timestamp"),
            "status_updated": solved.get("status_updated"),
        }

    def start_backlash_compass_goto_loop(
        self,
        repeats: int = BACKLASH_COMPASS_GOTO_REPEATS,
        offset_deg: float = BACKLASH_COMPASS_GOTO_OFFSET_DEG,
    ) -> bool:
        self._clear_backlash_stop_request()
        repeats = max(1, int(repeats))
        offset_deg = max(0.1, float(offset_deg))
        self._backlash_auto = {
            "axis": "Mount frame",
            "state": "starting",
            "message": "Solved GoTo loop setup started",
            "started_at": time.time(),
            "mode": "motion_test",
            "auto_mode": BACKLASH_AUTO_MODE_COMPASS_GOTO,
            "method": "solved_goto_loop_motion_record",
            "repeats": repeats,
            "offset_deg": offset_deg,
            "coordinate_records": [],
            "steps": [
                "Verify PointingCoordinateService has a valid solved coordinate",
                "Verify location/time, Unparked state, tracking Off, and current mount coordinates",
                "Sync mount coordinates to the current solved coordinate",
                "Run one-axis tests in mount order: AZ/ALT for Alt/Az or RA/DEC for EQ",
                "For each axis, move to the initial anti-offset point",
                "Record initial mount and solved coordinates for the active axis",
                "GoTo the active-axis offset point while holding the inactive-axis coordinate fixed",
                "Repeat return-to-start and offset GoTo cycles for each active axis",
            ],
        }

        solved = self._current_solved_pointing()
        solved_status = self._solved_status_payload(solved)
        if solved is None:
            self._backlash_auto_status(
                "waiting_for_solved",
                (
                    "Backlash motion test requires a valid plate-solved coordinate. "
                    "Solve first, then start the test again."
                ),
                phase="solved_required",
                solved_status=solved_status,
            )
            self._console("Backlash needs\nsolve first")
            return False

        if not self.connect():
            self._backlash_auto_status(
                "failed",
                "Could not connect to INDI mount before backlash test",
                phase="device_state",
                solved_status=solved_status,
            )
            return False

        if not self.stop_mount():
            self._backlash_auto_status(
                "failed",
                "Could not send mount stop before backlash test",
                phase="device_state",
                solved_status=solved_status,
            )
            return False
        original_tracking = self._read_tracking_enabled()
        if original_tracking is None:
            self._backlash_auto_status(
                "failed",
                "Could not read tracking state before backlash test",
                phase="device_state",
                solved_status=solved_status,
            )
            return False
        if original_tracking and not self.set_tracking(False):
            self._backlash_auto_status(
                "failed",
                "Could not disable tracking before backlash test",
                phase="device_state",
                solved_status=solved_status,
                original_tracking=original_tracking,
            )
            return False

        self._backlash_auto_status(
            "ready",
            "Solved coordinate is ready; press Continue Motion Test to start movement.",
            phase="solved_ready",
            solved_status=solved_status,
            original_tracking=original_tracking,
            tracking_disabled_for_test=bool(original_tracking),
        )
        self._console("Backlash ready\ncontinue")
        return True

    def _record_compass_goto_point(
        self,
        label: str,
        sequence: int,
        *,
        command_start_ra: Optional[float] = None,
        command_start_dec: Optional[float] = None,
        command_start_altitude: Optional[float] = None,
        command_start_azimuth: Optional[float] = None,
        target_ra: Optional[float] = None,
        target_dec: Optional[float] = None,
        target_altitude: Optional[float] = None,
        target_azimuth: Optional[float] = None,
        movement_frame: Optional[str] = None,
        active_axis: Optional[str] = None,
        solved_min_timestamp: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        mount_position = self._read_current_position()
        solved = self._wait_for_solved_pointing(
            label,
            min_timestamp=solved_min_timestamp,
        )
        solved_status = self._solved_status_payload(solved)
        if mount_position is None or solved is None:
            self._backlash_auto_status(
                "failed",
                f"{label}: could not record both mount and solved coordinates",
                phase=label,
                solved_status=solved_status,
            )
            return None

        mount_altaz = self._radec_to_altaz(mount_position[0], mount_position[1])
        solved_altitude = solved.get("altitude")
        solved_azimuth = solved.get("azimuth")
        if solved_altitude is None or solved_azimuth is None:
            solved_altaz = self._radec_to_altaz(solved["ra"], solved["dec"])
            if solved_altaz is not None:
                solved_altitude, solved_azimuth = solved_altaz
        record = {
            "sequence": sequence,
            "label": label,
            "recorded_at": time.time(),
            "mount_ra": mount_position[0] % 360.0,
            "mount_dec": mount_position[1],
            "mount_altitude": None if mount_altaz is None else mount_altaz[0],
            "mount_azimuth": None if mount_altaz is None else mount_altaz[1],
            "pifinder_solved_ra": solved["ra"] % 360.0,
            "pifinder_solved_dec": solved["dec"],
            "pifinder_solved_altitude": solved_altitude,
            "pifinder_solved_azimuth": None
            if solved_azimuth is None
            else solved_azimuth % 360.0,
            "pifinder_solved_timestamp": solved["timestamp"],
            "pifinder_solved_source": solved.get("source") or "solve",
            "pifinder_solved_valid": True,
            "command_start_ra": None
            if command_start_ra is None
            else command_start_ra % 360.0,
            "command_start_dec": command_start_dec,
            "command_start_altitude": command_start_altitude,
            "command_start_azimuth": None
            if command_start_azimuth is None
            else command_start_azimuth % 360.0,
            "target_ra": None if target_ra is None else target_ra % 360.0,
            "target_dec": target_dec,
            "target_altitude": target_altitude,
            "target_azimuth": None
            if target_azimuth is None
            else target_azimuth % 360.0,
            "movement_frame": movement_frame,
            "active_axis": active_axis,
            "solved_status": solved_status,
        }
        return record

    def _append_compass_goto_record(
        self,
        records: list[dict[str, Any]],
        label: str,
        *,
        command_start_ra: Optional[float] = None,
        command_start_dec: Optional[float] = None,
        command_start_altitude: Optional[float] = None,
        command_start_azimuth: Optional[float] = None,
        target_ra: Optional[float] = None,
        target_dec: Optional[float] = None,
        target_altitude: Optional[float] = None,
        target_azimuth: Optional[float] = None,
        movement_frame: Optional[str] = None,
        active_axis: Optional[str] = None,
        solved_min_timestamp: Optional[float] = None,
    ) -> bool:
        record = self._record_compass_goto_point(
            label,
            len(records) + 1,
            command_start_ra=command_start_ra,
            command_start_dec=command_start_dec,
            command_start_altitude=command_start_altitude,
            command_start_azimuth=command_start_azimuth,
            target_ra=target_ra,
            target_dec=target_dec,
            target_altitude=target_altitude,
            target_azimuth=target_azimuth,
            movement_frame=movement_frame,
            active_axis=active_axis,
            solved_min_timestamp=solved_min_timestamp,
        )
        if record is None:
            return False
        records.append(record)
        self._backlash_auto_status(
            "running",
            (
                f"{label}: mount RA {record['mount_ra']:.4f}, "
                f"DEC {record['mount_dec']:.4f}; solved RA "
                f"{record['pifinder_solved_ra']:.4f}, "
                f"DEC {record['pifinder_solved_dec']:.4f}"
            ),
            phase=label,
            coordinate_records=records,
            solved_status=record["solved_status"],
        )
        return True

    def _backlash_active_axes(self, mount_model: str) -> tuple[str, ...]:
        return ("ra", "dec") if mount_model == "eq" else ("az", "alt")

    def _backlash_goto_command_and_wait(
        self,
        command: dict[str, Any],
        phase_label: str,
        active_axis: Optional[str] = None,
    ) -> bool:
        target_ra = float(command["target_ra"]) % 360.0
        target_dec = float(command["target_dec"])
        self._backlash_auto_status(
            "running",
            (f"{phase_label}: GoTo RA {target_ra:.4f}, " f"DEC {target_dec:.4f}"),
            phase=phase_label,
            active_axis=active_axis,
            target_ra=target_ra,
            target_dec=target_dec,
            target_altitude=command.get("target_altitude"),
            target_azimuth=command.get("target_azimuth"),
            movement_frame=command.get("movement_frame"),
        )
        if not self._goto_target_and_wait(
            target_ra,
            target_dec,
            phase_label,
            timeout=BACKLASH_COMPASS_GOTO_TIMEOUT_SECONDS,
        ):
            return False

        tracking_enabled = self._read_tracking_enabled()
        if tracking_enabled and not self.set_tracking(False):
            self._backlash_auto_status(
                "failed",
                f"{phase_label}: could not disable tracking after GoTo",
                phase=phase_label,
                active_axis=active_axis,
            )
            return False
        if tracking_enabled is None:
            self._backlash_auto_status(
                "running",
                f"{phase_label}: GoTo complete, tracking state unreadable",
                phase=phase_label,
                active_axis=active_axis,
            )
        return self._backlash_cancelable_sleep(
            BACKLASH_COMPASS_GOTO_SETTLE_SECONDS,
            f"{phase_label} settle",
        )

    def _compass_goto_loop_plan(
        self,
        start_ra: float,
        start_dec: float,
        offset_deg: float,
        active_axis: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        mount_model = self._backlash_mount_model()
        if mount_model == "eq":
            active_axis = (active_axis or "ra").lower()
            if active_axis not in {"ra", "dec"}:
                self._backlash_auto_status(
                    "failed",
                    f"Unsupported EQ backlash test axis: {active_axis}",
                    phase="target_calculation",
                    mount_model=mount_model,
                    movement_frame="radec",
                    active_axis=active_axis,
                )
                return None
            target_ra = (
                (start_ra + offset_deg) % 360.0
                if active_axis == "ra"
                else start_ra % 360.0
            )
            target_dec = start_dec + offset_deg if active_axis == "dec" else start_dec
            if target_dec > 89.0 or target_dec < -89.0:
                self._backlash_auto_status(
                    "failed",
                    (
                        f"Current DEC {start_dec:.2f} is too close to the pole for a "
                        f"{offset_deg:.1f} degree DEC test move"
                    ),
                    phase="target_calculation",
                    mount_model=mount_model,
                    movement_frame="radec",
                    start_ra=start_ra % 360.0,
                    start_dec=start_dec,
                    offset_deg=offset_deg,
                )
                return None
            start_altaz = self._radec_to_altaz(start_ra, start_dec)
            target_altaz = self._radec_to_altaz(target_ra, target_dec)
            return {
                "mount_model": mount_model,
                "movement_frame": "radec",
                "active_axis": active_axis,
                "start_ra": start_ra % 360.0,
                "start_dec": start_dec,
                "target_ra": target_ra,
                "target_dec": target_dec,
                "start_altitude": None if start_altaz is None else start_altaz[0],
                "start_azimuth": None if start_altaz is None else start_altaz[1],
                "target_altitude": None if target_altaz is None else target_altaz[0],
                "target_azimuth": None if target_altaz is None else target_altaz[1],
            }

        start_altaz = self._radec_to_altaz(start_ra, start_dec)
        if start_altaz is None:
            self._backlash_auto_status(
                "failed",
                (
                    "A usable MFNavis location/time is required to convert the "
                    "Alt/Az backlash test target to RA/DEC"
                ),
                phase="target_calculation",
                mount_model=mount_model,
                movement_frame="altaz",
                start_ra=start_ra % 360.0,
                start_dec=start_dec,
                offset_deg=offset_deg,
            )
            return None

        active_axis = (active_axis or "az").lower()
        if active_axis not in {"az", "alt"}:
            self._backlash_auto_status(
                "failed",
                f"Unsupported Alt/Az backlash test axis: {active_axis}",
                phase="target_calculation",
                mount_model=mount_model,
                movement_frame="altaz",
                active_axis=active_axis,
            )
            return None

        start_altitude, start_azimuth = start_altaz
        target_altitude = (
            start_altitude + offset_deg if active_axis == "alt" else start_altitude
        )
        target_azimuth = (
            (start_azimuth + offset_deg) % 360.0
            if active_axis == "az"
            else start_azimuth
        )
        if (
            target_altitude < BACKLASH_AUTO_SAFE_MIN_ALT_DEG
            or target_altitude > BACKLASH_AUTO_SAFE_MAX_ALT_DEG
        ):
            self._backlash_auto_status(
                "failed",
                (
                    f"Alt/Az target altitude {target_altitude:.1f} deg is outside "
                    f"the safe backlash range "
                    f"{BACKLASH_AUTO_SAFE_MIN_ALT_DEG:.0f}-"
                    f"{BACKLASH_AUTO_SAFE_MAX_ALT_DEG:.0f} deg"
                ),
                phase="target_calculation",
                mount_model=mount_model,
                movement_frame="altaz",
                start_ra=start_ra % 360.0,
                start_dec=start_dec,
                start_altitude=start_altitude,
                start_azimuth=start_azimuth,
                target_altitude=target_altitude,
                target_azimuth=target_azimuth,
                offset_deg=offset_deg,
            )
            return None

        target_radec = self._altaz_to_radec(target_altitude, target_azimuth)
        if target_radec is None:
            self._backlash_auto_status(
                "failed",
                "Could not convert Alt/Az backlash target to RA/DEC",
                phase="target_calculation",
                mount_model=mount_model,
                movement_frame="altaz",
                start_altitude=start_altitude,
                start_azimuth=start_azimuth,
                target_altitude=target_altitude,
                target_azimuth=target_azimuth,
                offset_deg=offset_deg,
            )
            return None

        return {
            "mount_model": mount_model,
            "movement_frame": "altaz",
            "active_axis": active_axis,
            "start_ra": start_ra % 360.0,
            "start_dec": start_dec,
            "start_altitude": start_altitude,
            "start_azimuth": start_azimuth,
            "target_altitude": target_altitude,
            "target_azimuth": target_azimuth,
            "target_ra": target_radec[0] % 360.0,
            "target_dec": target_radec[1],
        }

    def _compass_goto_init_command(
        self,
        current_ra: float,
        current_dec: float,
        offset_deg: float,
        active_axis: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        mount_model = self._backlash_mount_model()
        if mount_model == "eq":
            active_axis = (active_axis or "ra").lower()
            if active_axis not in {"ra", "dec"}:
                self._backlash_auto_status(
                    "failed",
                    f"Unsupported EQ backlash init axis: {active_axis}",
                    phase="init_target_calculation",
                    mount_model=mount_model,
                    movement_frame="radec",
                    active_axis=active_axis,
                )
                return None
            init_ra = (
                (current_ra - offset_deg) % 360.0
                if active_axis == "ra"
                else current_ra % 360.0
            )
            init_dec = current_dec - offset_deg if active_axis == "dec" else current_dec
            if init_dec > 89.0 or init_dec < -89.0:
                self._backlash_auto_status(
                    "failed",
                    (
                        f"Current DEC {current_dec:.2f} is too close to the pole for a "
                        f"{offset_deg:.1f} degree initial DEC test move"
                    ),
                    phase="init_target_calculation",
                    mount_model=mount_model,
                    movement_frame="radec",
                    current_ra=current_ra % 360.0,
                    current_dec=current_dec,
                    offset_deg=offset_deg,
                )
                return None
            init_altaz = self._radec_to_altaz(init_ra, init_dec)
            return {
                "target_ra": init_ra,
                "target_dec": init_dec,
                "target_altitude": None if init_altaz is None else init_altaz[0],
                "target_azimuth": None if init_altaz is None else init_altaz[1],
                "movement_frame": "radec",
                "mount_model": mount_model,
                "active_axis": active_axis,
            }

        current_altaz = self._radec_to_altaz(current_ra, current_dec)
        if current_altaz is None:
            self._backlash_auto_status(
                "failed",
                (
                    "A usable MFNavis location/time is required to convert the "
                    "Alt/Az backlash init target to RA/DEC"
                ),
                phase="init_target_calculation",
                mount_model=mount_model,
                movement_frame="altaz",
                current_ra=current_ra % 360.0,
                current_dec=current_dec,
                offset_deg=offset_deg,
            )
            return None

        active_axis = (active_axis or "az").lower()
        if active_axis not in {"az", "alt"}:
            self._backlash_auto_status(
                "failed",
                f"Unsupported Alt/Az backlash init axis: {active_axis}",
                phase="init_target_calculation",
                mount_model=mount_model,
                movement_frame="altaz",
                active_axis=active_axis,
            )
            return None

        init_altitude = (
            current_altaz[0] - offset_deg if active_axis == "alt" else current_altaz[0]
        )
        init_azimuth = (
            (current_altaz[1] - offset_deg) % 360.0
            if active_axis == "az"
            else current_altaz[1]
        )
        if (
            init_altitude < BACKLASH_AUTO_SAFE_MIN_ALT_DEG
            or init_altitude > BACKLASH_AUTO_SAFE_MAX_ALT_DEG
        ):
            self._backlash_auto_status(
                "failed",
                (
                    f"Alt/Az initial target altitude {init_altitude:.1f} deg is "
                    f"outside the safe backlash range "
                    f"{BACKLASH_AUTO_SAFE_MIN_ALT_DEG:.0f}-"
                    f"{BACKLASH_AUTO_SAFE_MAX_ALT_DEG:.0f} deg"
                ),
                phase="init_target_calculation",
                mount_model=mount_model,
                movement_frame="altaz",
                current_ra=current_ra % 360.0,
                current_dec=current_dec,
                current_altitude=current_altaz[0],
                current_azimuth=current_altaz[1],
                target_altitude=init_altitude,
                target_azimuth=init_azimuth,
                offset_deg=offset_deg,
            )
            return None

        init_radec = self._altaz_to_radec(init_altitude, init_azimuth)
        if init_radec is None:
            self._backlash_auto_status(
                "failed",
                "Could not convert Alt/Az backlash init target to RA/DEC",
                phase="init_target_calculation",
                mount_model=mount_model,
                movement_frame="altaz",
                current_altitude=current_altaz[0],
                current_azimuth=current_altaz[1],
                target_altitude=init_altitude,
                target_azimuth=init_azimuth,
                offset_deg=offset_deg,
            )
            return None

        return {
            "target_ra": init_radec[0] % 360.0,
            "target_dec": init_radec[1],
            "target_altitude": init_altitude,
            "target_azimuth": init_azimuth,
            "movement_frame": "altaz",
            "mount_model": mount_model,
            "active_axis": active_axis,
        }

    def _sync_backlash_mount_to_solved(self) -> bool:
        solved = self._current_solved_pointing()
        solved_status = self._solved_status_payload(solved)
        if solved is None:
            self._backlash_auto_status(
                "failed",
                "Could not read solved MFNavis coordinate before backlash test",
                phase="solved_mount_sync",
                solved_status=solved_status,
            )
            return False

        sync_ra, sync_dec = solved["ra"], solved["dec"]
        self._backlash_auto_status(
            "running",
            "Syncing mount coordinates to current solved coordinate before backlash test",
            phase="solved_mount_sync",
            sync_ra=sync_ra % 360.0,
            sync_dec=sync_dec,
            solved_status=solved_status,
        )
        if not self.sync_mount(sync_ra, sync_dec):
            self._backlash_auto_status(
                "failed",
                "Could not sync mount coordinates to the current solved coordinate",
                phase="solved_mount_sync",
                sync_ra=sync_ra % 360.0,
                sync_dec=sync_dec,
                solved_status=solved_status,
            )
            return False

        # sync_mount() enables tracking for normal operation; this test needs
        # tracking off so drift is not counted as backlash travel.
        if not self.set_tracking(False):
            self._backlash_auto_status(
                "failed",
                "Could not turn tracking back off after solved-coordinate mount sync",
                phase="solved_mount_sync",
                sync_ra=sync_ra % 360.0,
                sync_dec=sync_dec,
                solved_status=solved_status,
            )
            return False

        return True

    def _compass_goto_loop_command(
        self, plan: dict[str, Any], point: str
    ) -> Optional[dict[str, Any]]:
        movement_frame = str(plan.get("movement_frame") or "radec")
        if movement_frame == "altaz":
            altitude = plan.get(f"{point}_altitude")
            azimuth = plan.get(f"{point}_azimuth")
            if altitude is None or azimuth is None:
                return None
            radec = self._altaz_to_radec(float(altitude), float(azimuth))
            if radec is None:
                return None
            return {
                "target_ra": radec[0] % 360.0,
                "target_dec": radec[1],
                "target_altitude": float(altitude),
                "target_azimuth": float(azimuth) % 360.0,
                "movement_frame": movement_frame,
                "active_axis": plan.get("active_axis"),
            }

        return {
            "target_ra": float(plan[f"{point}_ra"]) % 360.0,
            "target_dec": float(plan[f"{point}_dec"]),
            "target_altitude": plan.get(f"{point}_altitude"),
            "target_azimuth": plan.get(f"{point}_azimuth"),
            "movement_frame": movement_frame,
            "active_axis": plan.get("active_axis"),
        }

    def _altaz_separation_deg(
        self, alt1_deg: float, az1_deg: float, alt2_deg: float, az2_deg: float
    ) -> float:
        alt1 = math.radians(alt1_deg)
        alt2 = math.radians(alt2_deg)
        az_delta = math.radians((az2_deg - az1_deg + 180.0) % 360.0 - 180.0)
        cos_sep = math.sin(alt1) * math.sin(alt2) + math.cos(alt1) * math.cos(
            alt2
        ) * math.cos(az_delta)
        return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))

    def _compass_goto_loop_directional_analysis(
        self, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        legs: list[dict[str, Any]] = []
        grouped_values: dict[str, list[int]] = {"offset": [], "return": []}
        axis_grouped_values: dict[str, dict[str, list[int]]] = {
            "offset": {"ra": [], "dec": [], "alt": [], "az": []},
            "return": {"ra": [], "dec": [], "alt": [], "az": []},
        }
        axis_direction_grouped_values: dict[str, list[int]] = {}
        solved_skipped_values: dict[str, list[int]] = {"offset": [], "return": []}
        solved_skipped_leg_indices: dict[str, list[int]] = {"offset": [], "return": []}
        threshold_skipped_values: dict[str, list[int]] = {"offset": [], "return": []}
        threshold_skipped_leg_indices: dict[str, list[int]] = {
            "offset": [],
            "return": [],
        }

        def signed_arcsec(value: Optional[float]) -> Optional[int]:
            if value is None:
                return None
            return int(round(value * 3600.0))

        def backlash_arcsec_from_signed(value: Optional[float]) -> Optional[int]:
            if value is None:
                return None
            return max(
                BACKLASH_MIN_VALUE,
                min(BACKLASH_MAX_VALUE, int(round(abs(value) * 3600.0))),
            )

        def direction_sign_from_delta(value: Optional[float]) -> Optional[str]:
            if value is None or abs(value) < 1e-9:
                return None
            return "positive" if value > 0 else "negative"

        def axis_direction_key(axis: str, delta: Optional[float]) -> Optional[str]:
            sign = direction_sign_from_delta(delta)
            if sign is None:
                return None
            return f"{axis}_{sign}"

        def axis_direction_label(axis: str, sign: str) -> str:
            axis_labels = {
                "ra": "RA",
                "dec": "DEC",
                "alt": "ALT",
                "az": "AZ",
            }
            suffix = "+" if sign == "positive" else "-"
            return f"{axis_labels.get(axis, axis.upper())}{suffix}"

        for index in range(1, len(records)):
            previous = records[index - 1]
            current = records[index]
            label = str(current.get("label", ""))
            if label.startswith("offset"):
                direction = "offset"
            elif label.startswith("return"):
                direction = "return"
            else:
                continue

            movement_frame = str(current.get("movement_frame") or "radec")
            active_axis = current.get("active_axis")
            mount_record_start_ra = float(previous["mount_ra"]) % 360.0
            mount_record_start_dec = float(previous["mount_dec"])
            mount_record_start_alt = previous.get("mount_altitude")
            mount_record_start_az = previous.get("mount_azimuth")
            command_start_ra = current.get("command_start_ra")
            command_start_dec = current.get("command_start_dec")
            command_start_alt = current.get("command_start_altitude")
            command_start_az = current.get("command_start_azimuth")
            fixed_command_start_ra = (
                float(command_start_ra) % 360.0
                if command_start_ra is not None
                else None
            )
            fixed_command_start_dec = (
                float(command_start_dec) if command_start_dec is not None else None
            )
            fixed_command_start_alt = (
                float(command_start_alt) if command_start_alt is not None else None
            )
            fixed_command_start_az = (
                float(command_start_az) % 360.0
                if command_start_az is not None
                else None
            )
            mount_start_ra = mount_record_start_ra
            mount_start_dec = mount_record_start_dec
            mount_start_alt = mount_record_start_alt
            mount_start_az = mount_record_start_az
            mount_end_ra = float(current["mount_ra"]) % 360.0
            mount_end_dec = float(current["mount_dec"])
            mount_end_alt = current.get("mount_altitude")
            mount_end_az = current.get("mount_azimuth")
            target_ra = current.get("target_ra")
            target_dec = current.get("target_dec")
            target_alt = current.get("target_altitude")
            target_az = current.get("target_azimuth")

            mount_delta_ra = shortest_ra_delta_deg(mount_end_ra, mount_start_ra)
            mount_delta_dec = mount_end_dec - mount_start_dec
            mount_delta_alt = (
                float(mount_end_alt) - float(mount_start_alt)
                if mount_start_alt is not None and mount_end_alt is not None
                else None
            )
            mount_delta_az = (
                shortest_ra_delta_deg(float(mount_end_az), float(mount_start_az))
                if mount_start_az is not None and mount_end_az is not None
                else None
            )
            mount_record_delta_ra = shortest_ra_delta_deg(
                mount_end_ra, mount_record_start_ra
            )
            mount_record_delta_dec = mount_end_dec - mount_record_start_dec
            mount_record_delta_alt = (
                float(mount_end_alt) - float(mount_record_start_alt)
                if mount_record_start_alt is not None and mount_end_alt is not None
                else None
            )
            mount_record_delta_az = (
                shortest_ra_delta_deg(float(mount_end_az), float(mount_record_start_az))
                if mount_record_start_az is not None and mount_end_az is not None
                else None
            )

            if (
                movement_frame == "altaz"
                and mount_start_alt is not None
                and mount_start_az is not None
                and mount_end_alt is not None
                and mount_end_az is not None
            ):
                mount_sep_deg = self._altaz_separation_deg(
                    float(mount_start_alt),
                    float(mount_start_az),
                    float(mount_end_alt),
                    float(mount_end_az),
                )
            else:
                mount_sep_deg = (
                    radec_separation_arcmin(
                        mount_start_ra,
                        mount_start_dec,
                        mount_end_ra,
                        mount_end_dec,
                    )
                    / 60.0
                )
            solved_start_ra = previous.get("pifinder_solved_ra")
            solved_start_dec = previous.get("pifinder_solved_dec")
            solved_end_ra = current.get("pifinder_solved_ra")
            solved_end_dec = current.get("pifinder_solved_dec")
            solved_start_alt = previous.get("pifinder_solved_altitude")
            solved_start_az = previous.get("pifinder_solved_azimuth")
            solved_end_alt = current.get("pifinder_solved_altitude")
            solved_end_az = current.get("pifinder_solved_azimuth")
            solved_valid = bool(
                previous.get("pifinder_solved_valid")
                and current.get("pifinder_solved_valid")
                and solved_start_ra is not None
                and solved_start_dec is not None
                and solved_end_ra is not None
                and solved_end_dec is not None
            )
            if (
                movement_frame == "altaz"
                and solved_start_alt is not None
                and solved_start_az is not None
                and solved_end_alt is not None
                and solved_end_az is not None
            ):
                solved_sep_deg = self._altaz_separation_deg(
                    float(solved_start_alt),
                    float(solved_start_az),
                    float(solved_end_alt),
                    float(solved_end_az),
                )
            elif solved_valid:
                solved_sep_deg = (
                    radec_separation_arcmin(
                        _as_float(solved_start_ra),
                        _as_float(solved_start_dec),
                        _as_float(solved_end_ra),
                        _as_float(solved_end_dec),
                    )
                    / 60.0
                )
            else:
                solved_sep_deg = 0.0
            target_delta_ra = (
                shortest_ra_delta_deg(float(target_ra), mount_start_ra)
                if target_ra is not None
                else None
            )
            target_delta_dec = (
                float(target_dec) - mount_start_dec if target_dec is not None else None
            )
            target_delta_alt = (
                float(target_alt) - float(mount_start_alt)
                if target_alt is not None and mount_start_alt is not None
                else None
            )
            target_delta_az = (
                shortest_ra_delta_deg(float(target_az), float(mount_start_az))
                if target_az is not None and mount_start_az is not None
                else None
            )
            coordinate_error_ra_arcsec = (
                int(
                    round(
                        shortest_ra_delta_deg(mount_end_ra, float(target_ra)) * 3600.0
                    )
                )
                if target_ra is not None
                else None
            )
            coordinate_error_dec_arcsec = (
                int(round((mount_end_dec - float(target_dec)) * 3600.0))
                if target_dec is not None
                else None
            )
            coordinate_error_alt_arcsec = (
                int(round((float(mount_end_alt) - float(target_alt)) * 3600.0))
                if target_alt is not None and mount_end_alt is not None
                else None
            )
            coordinate_error_az_arcsec = (
                int(
                    round(
                        shortest_ra_delta_deg(float(mount_end_az), float(target_az))
                        * 3600.0
                    )
                )
                if target_az is not None and mount_end_az is not None
                else None
            )
            coordinate_backlash_ra_arcsec = (
                max(
                    BACKLASH_MIN_VALUE,
                    min(BACKLASH_MAX_VALUE, abs(coordinate_error_ra_arcsec)),
                )
                if coordinate_error_ra_arcsec is not None
                else None
            )
            coordinate_backlash_dec_arcsec = (
                max(
                    BACKLASH_MIN_VALUE,
                    min(BACKLASH_MAX_VALUE, abs(coordinate_error_dec_arcsec)),
                )
                if coordinate_error_dec_arcsec is not None
                else None
            )
            coordinate_backlash_alt_arcsec = (
                max(
                    BACKLASH_MIN_VALUE,
                    min(BACKLASH_MAX_VALUE, abs(coordinate_error_alt_arcsec)),
                )
                if coordinate_error_alt_arcsec is not None
                else None
            )
            coordinate_backlash_az_arcsec = (
                max(
                    BACKLASH_MIN_VALUE,
                    min(BACKLASH_MAX_VALUE, abs(coordinate_error_az_arcsec)),
                )
                if coordinate_error_az_arcsec is not None
                else None
            )
            solved_delta_ra = None
            solved_delta_dec = None
            solved_delta_alt = (
                float(solved_end_alt) - float(solved_start_alt)
                if solved_start_alt is not None and solved_end_alt is not None
                else None
            )
            solved_delta_az = (
                shortest_ra_delta_deg(float(solved_end_az), float(solved_start_az))
                if solved_start_az is not None and solved_end_az is not None
                else None
            )
            motion_difference_ra_deg = None
            motion_difference_dec_deg = None
            motion_difference_alt_deg = None
            motion_difference_az_deg = None
            motion_backlash_ra_arcsec = None
            motion_backlash_dec_arcsec = None
            motion_backlash_alt_arcsec = None
            motion_backlash_az_arcsec = None
            if solved_valid:
                solved_delta_ra = shortest_ra_delta_deg(
                    _as_float(solved_end_ra), _as_float(solved_start_ra)
                )
                solved_delta_dec = _as_float(solved_end_dec) - _as_float(
                    solved_start_dec
                )
                motion_difference_ra_deg = mount_delta_ra - solved_delta_ra
                motion_difference_dec_deg = mount_delta_dec - solved_delta_dec
                motion_backlash_ra_arcsec = backlash_arcsec_from_signed(
                    motion_difference_ra_deg
                )
                motion_backlash_dec_arcsec = backlash_arcsec_from_signed(
                    motion_difference_dec_deg
                )
            if (
                mount_delta_alt is not None
                and mount_delta_az is not None
                and solved_delta_alt is not None
                and solved_delta_az is not None
            ):
                motion_difference_alt_deg = mount_delta_alt - solved_delta_alt
                motion_difference_az_deg = mount_delta_az - solved_delta_az
                motion_backlash_alt_arcsec = backlash_arcsec_from_signed(
                    motion_difference_alt_deg
                )
                motion_backlash_az_arcsec = backlash_arcsec_from_signed(
                    motion_difference_az_deg
                )
            if (
                movement_frame == "altaz"
                and motion_difference_alt_deg is not None
                and motion_difference_az_deg is not None
            ):
                raw_estimated_arcsec = int(
                    round(
                        math.hypot(
                            motion_difference_alt_deg,
                            motion_difference_az_deg,
                        )
                        * 3600.0
                    )
                )
            elif (
                motion_difference_ra_deg is not None
                and motion_difference_dec_deg is not None
            ):
                raw_estimated_arcsec = int(
                    round(
                        math.hypot(
                            motion_difference_ra_deg,
                            motion_difference_dec_deg,
                        )
                        * 3600.0
                    )
                )
            else:
                raw_estimated_arcsec = int(
                    round(max(0.0, mount_sep_deg - solved_sep_deg) * 3600.0)
                )
            estimated_arcsec = max(
                BACKLASH_MIN_VALUE, min(BACKLASH_MAX_VALUE, raw_estimated_arcsec)
            )
            threshold_rejected_axes: list[str] = []
            if movement_frame == "altaz":
                if (
                    motion_difference_alt_deg is not None
                    and abs(motion_difference_alt_deg) * 3600.0
                    >= BACKLASH_COMPASS_DIFF_REJECT_ARCSEC
                ):
                    threshold_rejected_axes.append("alt")
                if (
                    motion_difference_az_deg is not None
                    and abs(motion_difference_az_deg) * 3600.0
                    >= BACKLASH_COMPASS_DIFF_REJECT_ARCSEC
                ):
                    threshold_rejected_axes.append("az")
            else:
                if (
                    motion_difference_ra_deg is not None
                    and abs(motion_difference_ra_deg) * 3600.0
                    >= BACKLASH_COMPASS_DIFF_REJECT_ARCSEC
                ):
                    threshold_rejected_axes.append("ra")
                if (
                    motion_difference_dec_deg is not None
                    and abs(motion_difference_dec_deg) * 3600.0
                    >= BACKLASH_COMPASS_DIFF_REJECT_ARCSEC
                ):
                    threshold_rejected_axes.append("dec")
            threshold_rejected = (
                raw_estimated_arcsec >= BACKLASH_COMPASS_DIFF_REJECT_ARCSEC
                or bool(threshold_rejected_axes)
            )
            if movement_frame == "altaz":
                movement_direction_deltas = {
                    "alt": target_delta_alt
                    if target_delta_alt is not None
                    else mount_delta_alt,
                    "az": target_delta_az
                    if target_delta_az is not None
                    else mount_delta_az,
                }
            else:
                movement_direction_deltas = {
                    "ra": target_delta_ra
                    if target_delta_ra is not None
                    else mount_delta_ra,
                    "dec": target_delta_dec
                    if target_delta_dec is not None
                    else mount_delta_dec,
                }
            axis_movement_directions = {
                axis: direction_sign_from_delta(delta)
                for axis, delta in movement_direction_deltas.items()
                if direction_sign_from_delta(delta) is not None
            }
            warmup = label.startswith("offset initial")
            leg = {
                "index": index,
                "direction": direction,
                "from_label": previous.get("label", ""),
                "to_label": label,
                "warmup": warmup,
                "active_axis": active_axis,
                "pifinder_solved_valid": solved_valid,
                "mount_start_ra": mount_start_ra,
                "mount_start_dec": mount_start_dec,
                "mount_start_altitude": mount_start_alt,
                "mount_start_azimuth": mount_start_az,
                "mount_record_start_ra": mount_record_start_ra,
                "mount_record_start_dec": mount_record_start_dec,
                "mount_record_start_altitude": mount_record_start_alt,
                "mount_record_start_azimuth": mount_record_start_az,
                "mount_end_ra": mount_end_ra,
                "mount_end_dec": mount_end_dec,
                "mount_end_altitude": mount_end_alt,
                "mount_end_azimuth": mount_end_az,
                "command_start_ra": fixed_command_start_ra,
                "command_start_dec": fixed_command_start_dec,
                "command_start_altitude": fixed_command_start_alt,
                "command_start_azimuth": fixed_command_start_az,
                "target_ra": None if target_ra is None else float(target_ra) % 360.0,
                "target_dec": None if target_dec is None else float(target_dec),
                "target_altitude": None if target_alt is None else float(target_alt),
                "target_azimuth": None
                if target_az is None
                else float(target_az) % 360.0,
                "movement_frame": movement_frame,
                "axis_movement_directions": axis_movement_directions,
                "target_delta_ra": target_delta_ra,
                "target_delta_dec": target_delta_dec,
                "target_delta_altitude": target_delta_alt,
                "target_delta_azimuth": target_delta_az,
                "mount_delta_ra": mount_delta_ra,
                "mount_delta_dec": mount_delta_dec,
                "mount_delta_altitude": mount_delta_alt,
                "mount_delta_azimuth": mount_delta_az,
                "mount_record_delta_ra": mount_record_delta_ra,
                "mount_record_delta_dec": mount_record_delta_dec,
                "mount_record_delta_altitude": mount_record_delta_alt,
                "mount_record_delta_azimuth": mount_record_delta_az,
                "coordinate_error_ra_arcsec": coordinate_error_ra_arcsec,
                "coordinate_error_dec_arcsec": coordinate_error_dec_arcsec,
                "coordinate_error_alt_arcsec": coordinate_error_alt_arcsec,
                "coordinate_error_az_arcsec": coordinate_error_az_arcsec,
                "coordinate_backlash_ra_arcsec": coordinate_backlash_ra_arcsec,
                "coordinate_backlash_dec_arcsec": coordinate_backlash_dec_arcsec,
                "coordinate_backlash_alt_arcsec": coordinate_backlash_alt_arcsec,
                "coordinate_backlash_az_arcsec": coordinate_backlash_az_arcsec,
                "pifinder_solved_start_ra": solved_start_ra,
                "pifinder_solved_start_dec": solved_start_dec,
                "pifinder_solved_end_ra": solved_end_ra,
                "pifinder_solved_end_dec": solved_end_dec,
                "pifinder_solved_delta_ra": solved_delta_ra,
                "pifinder_solved_delta_dec": solved_delta_dec,
                "motion_difference_ra_arcsec": signed_arcsec(motion_difference_ra_deg),
                "motion_difference_dec_arcsec": signed_arcsec(
                    motion_difference_dec_deg
                ),
                "motion_difference_alt_arcsec": signed_arcsec(
                    motion_difference_alt_deg
                ),
                "motion_difference_az_arcsec": signed_arcsec(motion_difference_az_deg),
                "mount_sep_deg": mount_sep_deg,
                "pifinder_solved_sep_deg": solved_sep_deg,
                "raw_estimated_arcsec": raw_estimated_arcsec,
                "estimated_arcsec": estimated_arcsec,
                "motion_difference_threshold_arcsec": BACKLASH_COMPASS_DIFF_REJECT_ARCSEC,
                "motion_difference_threshold_rejected": threshold_rejected,
                "motion_difference_threshold_rejected_axes": threshold_rejected_axes,
                "motion_backlash_ra_arcsec": motion_backlash_ra_arcsec,
                "motion_backlash_dec_arcsec": motion_backlash_dec_arcsec,
                "motion_backlash_alt_arcsec": motion_backlash_alt_arcsec,
                "motion_backlash_az_arcsec": motion_backlash_az_arcsec,
                "motion_backlash_combined_arcsec": estimated_arcsec,
                "pifinder_solved_start_altitude": solved_start_alt,
                "pifinder_solved_start_azimuth": solved_start_az,
                "pifinder_solved_end_altitude": solved_end_alt,
                "pifinder_solved_end_azimuth": solved_end_az,
                "pifinder_solved_delta_alt": solved_delta_alt,
                "pifinder_solved_delta_az": solved_delta_az,
            }
            legs.append(leg)
            if not leg["warmup"] and solved_valid:
                if threshold_rejected:
                    threshold_skipped_values[direction].append(raw_estimated_arcsec)
                    threshold_skipped_leg_indices[direction].append(index)
                else:
                    grouped_values[direction].append(raw_estimated_arcsec)
                    if (
                        motion_backlash_ra_arcsec is not None
                        and leg["motion_difference_ra_arcsec"] is not None
                    ):
                        axis_grouped_values[direction]["ra"].append(
                            motion_backlash_ra_arcsec
                        )
                    if (
                        motion_backlash_dec_arcsec is not None
                        and leg["motion_difference_dec_arcsec"] is not None
                    ):
                        axis_grouped_values[direction]["dec"].append(
                            motion_backlash_dec_arcsec
                        )
                    if (
                        motion_backlash_alt_arcsec is not None
                        and leg["motion_difference_alt_arcsec"] is not None
                    ):
                        axis_grouped_values[direction]["alt"].append(
                            motion_backlash_alt_arcsec
                        )
                    if (
                        motion_backlash_az_arcsec is not None
                        and leg["motion_difference_az_arcsec"] is not None
                    ):
                        axis_grouped_values[direction]["az"].append(
                            motion_backlash_az_arcsec
                        )
                    if movement_frame == "altaz":
                        axis_direction_candidates = (
                            ("alt", target_delta_alt, motion_backlash_alt_arcsec),
                            ("az", target_delta_az, motion_backlash_az_arcsec),
                        )
                    else:
                        axis_direction_candidates = (
                            ("ra", target_delta_ra, motion_backlash_ra_arcsec),
                            ("dec", target_delta_dec, motion_backlash_dec_arcsec),
                        )
                    for axis, delta, value in axis_direction_candidates:
                        key = axis_direction_key(axis, delta)
                        if key is not None and value is not None:
                            axis_direction_grouped_values.setdefault(key, []).append(
                                value
                            )
            elif not leg["warmup"]:
                solved_skipped_values[direction].append(estimated_arcsec)
                solved_skipped_leg_indices[direction].append(index)

        direction_stats: dict[str, Any] = {}
        for direction, values in grouped_values.items():
            stats = self._filter_compass_backlash_values(values)
            normal_values = stats.get("values", [])
            normal_min = min(normal_values) if normal_values else None
            normal_max = max(normal_values) if normal_values else None
            normal_leg_indices = [
                leg["index"]
                for leg in legs
                if leg["direction"] == direction
                and not leg.get("warmup")
                and leg.get("pifinder_solved_valid")
                and not leg.get("motion_difference_threshold_rejected")
                and normal_min is not None
                and normal_min <= int(leg["raw_estimated_arcsec"]) <= normal_max
            ]
            direction_stats[direction] = {
                **stats,
                "normal_min": normal_min,
                "normal_max": normal_max,
                "normal_leg_indices": normal_leg_indices,
                "solved_skipped_count": len(solved_skipped_values[direction]),
                "solved_skipped_values": solved_skipped_values[direction],
                "solved_skipped_leg_indices": solved_skipped_leg_indices[direction],
                "threshold_reject_arcsec": BACKLASH_COMPASS_DIFF_REJECT_ARCSEC,
                "threshold_skipped_count": len(threshold_skipped_values[direction]),
                "threshold_skipped_values": threshold_skipped_values[direction],
                "threshold_skipped_leg_indices": threshold_skipped_leg_indices[
                    direction
                ],
                "total_leg_count": (
                    len(values)
                    + len(solved_skipped_values[direction])
                    + len(threshold_skipped_values[direction])
                ),
                "recommended_trimmed_mean": int(round(float(stats["trimmed_mean"])))
                if stats.get("filtered_count", 0)
                else 0,
                "recommended_median": int(round(float(stats["median"])))
                if stats.get("filtered_count", 0)
                else 0,
                "recommended_p75": int(stats["p75"])
                if stats.get("filtered_count", 0)
                else 0,
            }
            for axis in ("ra", "dec", "alt", "az"):
                axis_stats = self._filter_compass_backlash_values(
                    axis_grouped_values[direction][axis]
                )
                direction_stats[direction][f"{axis}_motion_backlash"] = {
                    **axis_stats,
                    "threshold_reject_arcsec": BACKLASH_COMPASS_DIFF_REJECT_ARCSEC,
                    "recommended_trimmed_mean": int(
                        round(float(axis_stats["trimmed_mean"]))
                    )
                    if axis_stats.get("filtered_count", 0)
                    else 0,
                    "recommended_median": int(round(float(axis_stats["median"])))
                    if axis_stats.get("filtered_count", 0)
                    else 0,
                    "recommended_p75": int(axis_stats["p75"])
                    if axis_stats.get("filtered_count", 0)
                    else 0,
                }

        axis_direction_stats: dict[str, Any] = {}
        for direction_key, values in axis_direction_grouped_values.items():
            axis, sign = direction_key.rsplit("_", 1)
            stats = self._filter_compass_backlash_values(values)
            axis_direction_stats[direction_key] = {
                **stats,
                "axis": axis,
                "direction": sign,
                "display_label": axis_direction_label(axis, sign),
                "threshold_reject_arcsec": BACKLASH_COMPASS_DIFF_REJECT_ARCSEC,
                "recommended_trimmed_mean": int(round(float(stats["trimmed_mean"])))
                if stats.get("filtered_count", 0)
                else 0,
                "recommended_median": int(round(float(stats["median"])))
                if stats.get("filtered_count", 0)
                else 0,
                "recommended_p75": int(stats["p75"])
                if stats.get("filtered_count", 0)
                else 0,
            }

        return {
            "method": "mount_minus_pifinder_solved_travel_filtered_by_direction",
            "note": (
                "Indoor directional estimate: each GoTo leg compares mount "
                "travel from the previous settled mount readback to the actual "
                "mount readback after the GoTo, then compares that with MFNavis "
                "solved travel recorded across the same leg. Alt/Az and EQ fixed S/T "
                "points are reused for record analysis; actual motion uses "
                "GoTo commands with only the active-axis coordinate offset. "
                "The offset-initial warm-up leg, legs without valid solved "
                "coordinates, and legs where mount-vs-solved travel differs by at "
                "least 1 degree are excluded. Remaining values are sorted, the "
                "lowest 30% and highest 30% are discarded, and the middle 40% "
                "mean is used as the recommendation."
            ),
            "legs": legs,
            "direction_stats": direction_stats,
            "axis_direction_stats": axis_direction_stats,
        }

    def continue_backlash_compass_goto_loop(self) -> bool:
        if (
            not self._backlash_auto
            or self._backlash_auto.get("auto_mode") != BACKLASH_AUTO_MODE_COMPASS_GOTO
        ):
            return self.start_backlash_compass_goto_loop()

        repeats = int(self._backlash_auto.get("repeats", BACKLASH_COMPASS_GOTO_REPEATS))
        offset_deg = float(
            self._backlash_auto.get("offset_deg", BACKLASH_COMPASS_GOTO_OFFSET_DEG)
        )
        if self._abort_backlash_if_requested("continue"):
            return False

        solved = self._current_solved_pointing()
        solved_status = self._solved_status_payload(solved)
        if solved is None:
            self._backlash_auto_status(
                "waiting_for_solved",
                (
                    "Backlash motion test requires a valid plate-solved coordinate. "
                    "Solve first, then press Continue Motion Test again."
                ),
                phase="solved_required",
                solved_status=solved_status,
            )
            self._console("Backlash needs\nsolve first")
            return False

        records: list[dict[str, Any]] = []
        original_tracking: Optional[bool] = self._backlash_auto.get("original_tracking")
        try:
            if not self.connect():
                self._backlash_auto_status("failed", "Could not connect to INDI mount")
                return False

            latitude, longitude, _elevation, dt = self._shared_location_time_values()
            location_time_available = (
                latitude is not None and longitude is not None and dt is not None
            )
            if not location_time_available:
                self._backlash_auto_status(
                    "running",
                    (
                        "MFNavis shared location/time is not locked in the "
                        "mount-control process; continuing because this motion "
                        "test records mount/solved coordinates from the active "
                        "OnStep session."
                    ),
                    phase="device_state",
                    location_time_available=False,
                )

            park_state = self._home_park_status_fields().get("park_state", "Unknown")
            if park_state != "Unparked":
                self._backlash_auto_status(
                    "failed",
                    f"Mount must be Unparked before the solved GoTo loop ({park_state})",
                    phase="device_state",
                    park_state=park_state,
                )
                return False

            current_tracking = self._read_tracking_enabled()
            if current_tracking is None:
                self._backlash_auto_status(
                    "failed",
                    "Could not read tracking state before solved GoTo loop",
                    phase="device_state",
                )
                return False
            if original_tracking is None:
                original_tracking = current_tracking
            if current_tracking and not self.set_tracking(False):
                self._backlash_auto_status(
                    "failed",
                    "Could not disable tracking before solved GoTo loop",
                    phase="device_state",
                )
                return False

            if not self._sync_backlash_mount_to_solved():
                return False

            mount_model = self._backlash_mount_model()
            active_axes = self._backlash_active_axes(mount_model)
            plan: Optional[dict[str, Any]] = None
            start_ra = start_dec = target_ra = target_dec = 0.0
            movement_frame = "radec" if mount_model == "eq" else "altaz"

            for active_axis in active_axes:
                axis_label = active_axis.upper()
                start_position = self._read_current_position()
                if start_position is None:
                    self._backlash_auto_status(
                        "failed",
                        f"Could not read current mount coordinates before {axis_label}",
                        phase="pre_init_position",
                        active_axis=active_axis,
                    )
                    return False
                pre_init_ra, pre_init_dec = start_position
                init_command = self._compass_goto_init_command(
                    pre_init_ra,
                    pre_init_dec,
                    offset_deg,
                    active_axis=active_axis,
                )
                if init_command is None:
                    return False
                init_label = f"init {axis_label}"
                self._backlash_auto_status(
                    "running",
                    (
                        f"Moving {axis_label} to initial anti-offset point "
                        "before calculating fixed backlash command points"
                    ),
                    phase=init_label,
                    mount_model=init_command.get("mount_model"),
                    movement_frame=init_command.get("movement_frame"),
                    active_axis=active_axis,
                    active_axes=list(active_axes),
                    pre_init_ra=pre_init_ra % 360.0,
                    pre_init_dec=pre_init_dec,
                    target_ra=init_command.get("target_ra"),
                    target_dec=init_command.get("target_dec"),
                    target_altitude=init_command.get("target_altitude"),
                    target_azimuth=init_command.get("target_azimuth"),
                    offset_deg=offset_deg,
                    solved_status=solved_status,
                )
                if not self._backlash_goto_command_and_wait(
                    init_command,
                    init_label,
                    active_axis,
                ):
                    return False

                start_position = self._read_current_position()
                if start_position is None:
                    self._backlash_auto_status(
                        "failed",
                        (
                            "Could not read current mount coordinates after "
                            f"{axis_label} init move"
                        ),
                        phase="initial_position",
                        active_axis=active_axis,
                    )
                    return False
                start_ra, start_dec = start_position
                plan = self._compass_goto_loop_plan(
                    start_ra,
                    start_dec,
                    offset_deg,
                    active_axis=active_axis,
                )
                if plan is None:
                    return False
                mount_model = str(plan.get("mount_model") or "altaz")
                movement_frame = str(plan.get("movement_frame") or "radec")
                start_command = self._compass_goto_loop_command(plan, "start")
                offset_command = self._compass_goto_loop_command(plan, "target")
                if start_command is None or offset_command is None:
                    self._backlash_auto_status(
                        "failed",
                        (
                            f"{axis_label}: could not calculate solved GoTo loop "
                            "start/offset commands"
                        ),
                        phase="target_calculation",
                        mount_model=mount_model,
                        movement_frame=movement_frame,
                        active_axis=active_axis,
                        offset_deg=offset_deg,
                    )
                    return False
                target_ra = float(offset_command["target_ra"])
                target_dec = float(offset_command["target_dec"])

                self._backlash_auto_status(
                    "running",
                    (
                        f"Solved GoTo loop {axis_label} using "
                        f"{movement_frame.upper()} frame: start RA "
                        f"{start_ra:.4f}, DEC {start_dec:.4f}; target RA "
                        f"{target_ra:.4f}, DEC {target_dec:.4f}"
                    ),
                    phase="initial_position",
                    mount_model=mount_model,
                    movement_frame=movement_frame,
                    active_axis=active_axis,
                    active_axes=list(active_axes),
                    start_ra=start_ra % 360.0,
                    start_dec=start_dec,
                    start_altitude=plan.get("start_altitude"),
                    start_azimuth=plan.get("start_azimuth"),
                    target_ra=target_ra,
                    target_dec=target_dec,
                    target_altitude=plan.get("target_altitude"),
                    target_azimuth=plan.get("target_azimuth"),
                    offset_deg=offset_deg,
                    repeats=repeats,
                    solved_status=solved_status,
                )

                initial_label = f"initial {axis_label}"
                if not self._append_compass_goto_record(
                    records,
                    initial_label,
                    active_axis=active_axis,
                ):
                    return False

                offset_initial_label = f"offset initial {axis_label}"
                offset_started_at = time.time()
                if not self._backlash_goto_command_and_wait(
                    offset_command,
                    offset_initial_label,
                    active_axis,
                ):
                    return False
                if not self._append_compass_goto_record(
                    records,
                    offset_initial_label,
                    command_start_ra=float(start_command["target_ra"]),
                    command_start_dec=float(start_command["target_dec"]),
                    command_start_altitude=start_command.get("target_altitude"),
                    command_start_azimuth=start_command.get("target_azimuth"),
                    target_ra=float(offset_command["target_ra"]),
                    target_dec=float(offset_command["target_dec"]),
                    target_altitude=offset_command.get("target_altitude"),
                    target_azimuth=offset_command.get("target_azimuth"),
                    movement_frame=movement_frame,
                    active_axis=active_axis,
                    solved_min_timestamp=offset_started_at,
                ):
                    return False

                for repeat_index in range(1, repeats + 1):
                    if not self._backlash_cancelable_sleep(
                        BACKLASH_COMPASS_GOTO_BETWEEN_SECONDS,
                        f"{axis_label} repeat {repeat_index} pause",
                    ):
                        return False
                    return_label = f"return {repeat_index} {axis_label}"
                    start_command = self._compass_goto_loop_command(plan, "start")
                    if start_command is None:
                        self._backlash_auto_status(
                            "failed",
                            f"{return_label}: could not calculate start command",
                            phase=return_label,
                            mount_model=mount_model,
                            movement_frame=movement_frame,
                            active_axis=active_axis,
                        )
                        return False
                    return_started_at = time.time()
                    if not self._backlash_goto_command_and_wait(
                        start_command,
                        return_label,
                        active_axis,
                    ):
                        return False
                    if not self._append_compass_goto_record(
                        records,
                        return_label,
                        command_start_ra=float(offset_command["target_ra"]),
                        command_start_dec=float(offset_command["target_dec"]),
                        command_start_altitude=offset_command.get("target_altitude"),
                        command_start_azimuth=offset_command.get("target_azimuth"),
                        target_ra=float(start_command["target_ra"]),
                        target_dec=float(start_command["target_dec"]),
                        target_altitude=start_command.get("target_altitude"),
                        target_azimuth=start_command.get("target_azimuth"),
                        movement_frame=movement_frame,
                        active_axis=active_axis,
                        solved_min_timestamp=return_started_at,
                    ):
                        return False

                    offset_label = f"offset {repeat_index} {axis_label}"
                    offset_command = self._compass_goto_loop_command(plan, "target")
                    if offset_command is None:
                        self._backlash_auto_status(
                            "failed",
                            f"{offset_label}: could not calculate offset command",
                            phase=offset_label,
                            mount_model=mount_model,
                            movement_frame=movement_frame,
                            active_axis=active_axis,
                        )
                        return False
                    offset_started_at = time.time()
                    if not self._backlash_goto_command_and_wait(
                        offset_command,
                        offset_label,
                        active_axis,
                    ):
                        return False
                    if not self._append_compass_goto_record(
                        records,
                        offset_label,
                        command_start_ra=float(start_command["target_ra"]),
                        command_start_dec=float(start_command["target_dec"]),
                        command_start_altitude=start_command.get("target_altitude"),
                        command_start_azimuth=start_command.get("target_azimuth"),
                        target_ra=float(offset_command["target_ra"]),
                        target_dec=float(offset_command["target_dec"]),
                        target_altitude=offset_command.get("target_altitude"),
                        target_azimuth=offset_command.get("target_azimuth"),
                        movement_frame=movement_frame,
                        active_axis=active_axis,
                        solved_min_timestamp=offset_started_at,
                    ):
                        return False

            directional_analysis = self._compass_goto_loop_directional_analysis(records)
            self._backlash_auto_status(
                "complete",
                (
                    f"Solved GoTo loop complete: {len(records)} coordinate "
                    "records captured"
                ),
                phase="complete",
                coordinate_records=records,
                mount_model=mount_model,
                movement_frame=movement_frame,
                active_axes=list(active_axes),
                start_ra=start_ra % 360.0,
                start_dec=start_dec,
                start_altitude=(plan or {}).get("start_altitude"),
                start_azimuth=(plan or {}).get("start_azimuth"),
                target_ra=(plan or {}).get("target_ra"),
                target_dec=(plan or {}).get("target_dec"),
                target_altitude=(plan or {}).get("target_altitude"),
                target_azimuth=(plan or {}).get("target_azimuth"),
                offset_deg=offset_deg,
                repeats=repeats,
                solved_status=self._solved_status_payload(),
                directional_analysis=directional_analysis,
                estimate_type="motion_record_only",
                valid=True,
            )
            self._console("Solved loop\ncomplete")
            return True
        except Exception as exc:
            logger.exception("Solved GoTo loop failed")
            self._backlash_auto_status(
                "failed",
                f"Solved GoTo loop failed: {exc}",
                coordinate_records=records,
            )
            self._console("Solved loop\nfailed")
            return False
        finally:
            self.stop_mount()
            final_state = (
                self._backlash_auto.get("state") if self._backlash_auto else None
            )
            if original_tracking and final_state == "complete":
                self.set_tracking(True)

    def _altaz_to_radec(
        self, altitude_deg: float, azimuth_deg: float
    ) -> Optional[tuple[float, float]]:
        latitude, longitude, elevation, dt = self._shared_location_time_values(
            include_default_location=True
        )
        if latitude is None or longitude is None or dt is None:
            return None

        try:
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            if getattr(dt, "tzinfo", None) is None:
                dt = dt.replace(tzinfo=timezone.utc)
            calc_utils.sf_utils.set_location(latitude, longitude, elevation or 0.0)
            ra_deg, dec_deg = calc_utils.sf_utils.altaz_to_radec(
                altitude_deg, azimuth_deg, dt
            )
            return ra_deg % 360.0, dec_deg
        except Exception:
            logger.debug("Could not convert Alt/Az to RA/DEC", exc_info=True)
            return None

    def _radec_to_altaz(
        self, ra_deg: float, dec_deg: float
    ) -> Optional[tuple[float, float]]:
        latitude, longitude, elevation, dt = self._shared_location_time_values(
            include_default_location=True
        )
        if latitude is None or longitude is None or dt is None:
            return None

        try:
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            if getattr(dt, "tzinfo", None) is None:
                dt = dt.replace(tzinfo=timezone.utc)
            calc_utils.sf_utils.set_location(latitude, longitude, elevation or 0.0)
            alt_deg, az_deg = calc_utils.sf_utils.radec_to_altaz(ra_deg, dec_deg, dt)
            return alt_deg, az_deg % 360.0
        except Exception:
            logger.debug("Could not convert RA/DEC to Alt/Az", exc_info=True)
            return None

    def _backlash_mount_model(self) -> str:
        try:
            mount_type = str(config.Config().get_option("mount_type", "Alt/Az"))
        except Exception:
            logger.warning("Could not read mount type; using Alt/Az", exc_info=True)
            return "altaz"
        mount_type = mount_type.strip().lower()
        if "eq" in mount_type or "equatorial" in mount_type:
            return "eq"
        return "altaz"

    def _goto_target_and_wait(
        self,
        ra_deg: float,
        dec_deg: float,
        phase_label: str,
        timeout: float = BACKLASH_AUTO_GOTO_TIMEOUT_SECONDS,
    ) -> bool:
        if self._abort_backlash_if_requested(phase_label):
            return False
        self._backlash_auto_status(
            "running",
            f"{phase_label}: GoTo sent",
            phase=phase_label,
            target_ra=ra_deg % 360.0,
            target_dec=dec_deg,
        )
        if not self.goto_target(ra_deg, dec_deg, refine_after_goto=False):
            self._backlash_auto_status(
                "failed",
                f"{phase_label}: could not send GoTo",
                phase=phase_label,
            )
            return False

        start = time.monotonic()
        motion = self._goto_motion
        if motion is None:
            motion = {
                "started_at": start,
                "complete_ready_since": None,
                "indi_seen_busy": False,
                "onstep_seen_goto_active": False,
            }
        last_retry_at = start
        retry_count = 0
        while time.monotonic() - start < timeout:
            if self._abort_backlash_if_requested(phase_label):
                return False
            elapsed = time.monotonic() - start
            if elapsed >= GOTO_COMPLETE_MIN_SECONDS:
                busy = self._indi_mount_is_busy()
                if busy is True:
                    self._goto_completion_ready(motion, busy, time.monotonic())
                if busy is False:
                    current_position = self._read_current_position()
                    if current_position is not None:
                        separation_deg = (
                            radec_separation_arcmin(
                                current_position[0],
                                current_position[1],
                                ra_deg,
                                dec_deg,
                            )
                            / 60.0
                        )
                        if separation_deg > BACKLASH_AUTO_GOTO_TARGET_TOLERANCE_DEG:
                            now = time.monotonic()
                            if (
                                retry_count < BACKLASH_GOTO_MAX_RETRIES
                                and now - last_retry_at
                                >= BACKLASH_GOTO_RETRY_AFTER_SECONDS
                            ):
                                retry_count += 1
                                last_retry_at = now
                                self._backlash_auto_status(
                                    "running",
                                    (
                                        f"{phase_label}: target is still "
                                        f"{separation_deg:.2f} deg away; "
                                        f"resending GoTo ({retry_count}/"
                                        f"{BACKLASH_GOTO_MAX_RETRIES})"
                                    ),
                                    phase=phase_label,
                                    target_ra=ra_deg % 360.0,
                                    target_dec=dec_deg,
                                    current_ra=current_position[0],
                                    current_dec=current_position[1],
                                    target_error_deg=separation_deg,
                                    retry=retry_count,
                                )
                                self.goto_target(
                                    ra_deg, dec_deg, refine_after_goto=False
                                )
                                motion = self._goto_motion or motion
                                time.sleep(BACKLASH_AUTO_GOTO_POLL_SECONDS)
                                continue
                            motion["complete_ready_since"] = None
                            self._backlash_auto_status(
                                "running",
                                (
                                    f"{phase_label}: INDI is idle but target is "
                                    f"still {separation_deg:.2f} deg away"
                                ),
                                phase=phase_label,
                                target_ra=ra_deg % 360.0,
                                target_dec=dec_deg,
                                current_ra=current_position[0],
                                current_dec=current_position[1],
                                target_error_deg=separation_deg,
                                target_tolerance_deg=(
                                    BACKLASH_AUTO_GOTO_TARGET_TOLERANCE_DEG
                                ),
                            )
                            time.sleep(BACKLASH_AUTO_GOTO_POLL_SECONDS)
                            continue
                    if self._goto_completion_ready(
                        motion,
                        busy,
                        time.monotonic(),
                        current_position=current_position,
                    ):
                        self._complete_goto_motion(f"{phase_label}: GoTo complete")
                        return True
                if busy is None:
                    self._read_current_position()
            self._backlash_auto_status(
                "running",
                f"{phase_label}: waiting for GoTo completion",
                phase=phase_label,
                goto_wait_seconds=round(elapsed, 1),
            )
            time.sleep(BACKLASH_AUTO_GOTO_POLL_SECONDS)

        self.stop_mount()
        self._backlash_auto_status(
            "failed",
            (
                f"{phase_label}: GoTo did not complete or target was not reached "
                f"within {timeout:.0f} seconds; check OnStep mount limits"
            ),
            phase=phase_label,
        )
        return False

    def _normalize_backlash_auto_mode(self, mode: Any) -> str:
        mode_key = str(mode or BACKLASH_AUTO_MODE_COMPASS_GOTO).strip().lower()
        aliases = {
            "compass": BACKLASH_AUTO_MODE_COMPASS_GOTO,
            "goto_loop": BACKLASH_AUTO_MODE_COMPASS_GOTO,
            "compass_goto": BACKLASH_AUTO_MODE_COMPASS_GOTO,
        }
        mode_key = aliases.get(mode_key, mode_key)
        if mode_key not in BACKLASH_AUTO_MODES:
            return BACKLASH_AUTO_MODE_COMPASS_GOTO
        return mode_key

    def auto_calculate_backlash(
        self,
        _axis: str = "",
        mode: str = BACKLASH_AUTO_MODE_COMPASS_GOTO,
        repeats: Any = None,
    ) -> bool:
        mode = self._normalize_backlash_auto_mode(mode)
        if mode != BACKLASH_AUTO_MODE_COMPASS_GOTO:
            logger.warning("Unknown backlash auto mode: %s", mode)
            return False
        repeat_count = BACKLASH_COMPASS_GOTO_REPEATS
        if repeats not in (None, ""):
            repeat_count = int(repeats)
        return self.start_backlash_compass_goto_loop(repeats=repeat_count)
