#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is runs a lightweight
server to accept socket connections
and report telescope position
Protocol based on Meade LX200

This is used by SkySafari and Stellarium Mobile Plus. MF keeps target
coordinate receipt separate from GoTo/Align and routes motor control via INDI.
"""

import socket
import copy
import logging
import math
import re
import datetime
import json
import os
import threading
from multiprocessing import Queue
from typing import Any, Optional, Tuple, Union
from PiFinder import config, gps_time_sync, utils
from PiFinder.alignment_projection import cached_target_pixel, projection_context
from PiFinder.calc_utils import (
    FastAltAz,
    ra_to_deg,
    sf_utils,
    equinox_of_date_to_catalog,
    catalog_to_equinox_of_date,
)
from PiFinder.composite_object import CompositeObject, MagnitudeObject, SizeObject
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.pointing_coordinate_service import PointingCoordinateService
from PiFinder.state import Location as StateLocation
from PiFinder.track_freq_policy import track_freq_command_for_coordinates
import sys
import time

logger = logging.getLogger("PosServer")

sr_result = None
sd_result = None
last_target_coordinates: Optional[Tuple[float, float]] = None
sequence = 0
ui_queue: Queue
mountcontrol_queue: Optional[Queue] = None
goto_guide_queue: Optional[Queue] = None
align_command_queue: Optional[Queue] = None
align_response_queue: Optional[Queue] = None
console_queue: Optional[Queue] = None
is_stellarium = False
# Client site echoes are session-local, never applied to GPS or the mount.
stellarium_latitude = ""
stellarium_longitude = ""
_lx200_target_host: Optional[str] = None
_lx200_target_last_seen = 0.0
_LX200_TARGET_RECONNECT_SECONDS = 60.0
pos_server_config: Optional[config.Config] = None

_POINTING_UPDATE_SECONDS = 0.2
_CONFIG_RELOAD_SECONDS = 1.0
_GUIDE_LEASE_SECONDS = 1.2
_GUIDE_KEEPALIVE_SECONDS = 0.4
_GUIDE_RESTART_SECONDS = 8.0
_GUIDE_MAX_HOLD_SECONDS = 60.0
_MOUNT_STATUS_CACHE_SECONDS = 0.2
_SKYSAFARI_SLEW_GRACE_SECONDS = 2.0
_SKYSAFARI_SLEW_STATES = {"slewing", "refine_wait", "refine_sent"}
# Auto re-sync of the INDI mount's site location/time when the observing
# location changes (first GPS lock, or a manual location selection -- both
# arrive as a locked shared_state.location). The mount otherwise only learns
# the location at connect time, so a fix obtained after connect leaves its
# site/clock stale. The first locked location is synced immediately; after that
# the location is only re-checked on a not-too-short cadence, and a re-sync is
# sent only when the location has moved beyond the jitter threshold.
_LOCATION_RESYNC_RECHECK_SECONDS = 60.0
_LOCATION_RESYNC_MOVE_THRESHOLD_M = 500.0
_mount_synced_location: Optional[Tuple[float, float, float]] = None
_next_location_resync_at = 0.0
# A5 clock-event re-sync: when the system clock jumps (chrony stepping a
# stale fake-hwclock time after a late GPS fix / NTP recovery) or the clock
# first becomes trusted, the mount's site time and the tracking frame are
# stale -- re-send location/time and drop the tracking target.
_CLOCK_JUMP_THRESHOLD_SECONDS = 2.0
_CLOCK_TRUST_RECHECK_SECONDS = 5.0
_clock_jump_ref: Optional[Tuple[float, float]] = None
_clock_trust_seen: Optional[bool] = None
_next_clock_trust_check_at = 0.0
_mount_status_cache: dict[str, Any] = {
    "time": 0.0,
    "value": None,
}
_coordinate_service_thread: Optional[threading.Thread] = None
_coordinate_service_stop: Optional[threading.Event] = None
_skysafari_slew_started_at = 0.0
_skysafari_saw_mount_slew = False
_config_last_loaded = 0.0
_fallback_log_last = 0.0
_pointing_debug_last: dict[str, Any] = {
    "time": 0.0,
    "signature": None,
}
_imu_alignment_correction: dict[str, Any] = {
    "active": False,
    "alt_offset": 0.0,
    "az_offset": 0.0,
    "set_at": 0.0,
    "target_coordinates": None,
}
_GUIDE_DIRECTIONS = {
    "Mn": "north",
    "Ms": "south",
    "Me": "east",
    "Mw": "west",
}
_guide_motion_lock = threading.Lock()
_guide_motion_state: dict[str, Any] = {
    "direction": None,
    "timer": None,
    "token": 0,
    "started_at": 0.0,
    "next_restart_at": 0.0,
}
_coordinate_service = PointingCoordinateService()
_POINTING_STATUS_FILE = utils.runtime_dir / "pointing_coordinate_status.json"
# Cross-process "Reset Pointing" request. The web server (server.py) and the
# LCD UI (main.py) run in separate processes and share no queue with the
# pointing coordinate service, so they drop this request file (mirroring the
# backlash stop-request pattern) and the coordinate-service loop below polls
# for it and calls clear_state(). See mf_coordinate_helper_plan.
_POINTING_RESET_REQUEST_FILE = utils.runtime_dir / "pointing_reset_request.json"
_pointing_reset_last_at = 0.0


def _get_config_option(option: str, default):
    global _config_last_loaded
    if pos_server_config is None:
        return default
    now = time.monotonic()
    if now - _config_last_loaded > _CONFIG_RELOAD_SECONDS:
        try:
            pos_server_config.load_config()
        except Exception:
            logger.warning("Could not reload SkySafari server config", exc_info=True)
        _config_last_loaded = now
    return pos_server_config.get_option(option, default)


def _log_fallback_skip(reason: str) -> None:
    global _fallback_log_last
    now = time.monotonic()
    if now - _fallback_log_last < 5.0:
        return
    _fallback_log_last = now
    logger.info("SkySafari IMU fallback unavailable: %s", reason)


def _format_pointing_pair(sample) -> str:
    radec = sample.radec()
    if radec is None:
        return "-"
    return f"{radec[0]:.3f},{radec[1]:.3f}"


def _sample_status_payload(sample) -> dict:
    radec = sample.radec()
    return {
        "valid": bool(sample.valid),
        "source": sample.source,
        "quality": sample.quality,
        "reason": sample.reason,
        "ra": radec[0] if radec is not None else None,
        "dec": radec[1] if radec is not None else None,
        "alt": sample.alt_deg,
        "az": sample.az_deg,
        "timestamp": sample.timestamp,
        "aligned": bool(sample.aligned),
        "metadata": sample.metadata,
    }


def _write_pointing_status(state) -> None:
    try:
        utils.create_path(utils.runtime_dir)
        payload = {
            "updated": time.time(),
            "last_reset_at": _pointing_reset_last_at,
            "selected_source": state.current.source,
            "mode": state.mode,
            "weights": state.weights,
            "current": _sample_status_payload(state.current),
            "solved": _sample_status_payload(state.solved),
            "imu": _sample_status_payload(state.imu),
            "mount": _sample_status_payload(state.mount),
            "display": (
                _sample_status_payload(state.display)
                if getattr(state, "display", None) is not None
                else None
            ),
            "health": {
                "warnings": list(state.health.warnings),
                "mount_pre_alignment_only": bool(state.health.mount_pre_alignment_only),
                "mount_separation_degrees": state.health.mount_separation_degrees,
                "imu_mount_separation_degrees": (
                    state.health.imu_mount_separation_degrees
                ),
                "mount_delta_degrees": state.health.mount_delta_degrees,
                "imu_altaz_delta_degrees": state.health.imu_altaz_delta_degrees,
            },
        }
        tmp_status = _POINTING_STATUS_FILE.with_name(
            f"{_POINTING_STATUS_FILE.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
        )
        with open(tmp_status, "w", encoding="utf-8") as status_out:
            json.dump(payload, status_out, indent=2, sort_keys=True)
            status_out.flush()
        tmp_status.replace(_POINTING_STATUS_FILE)
    except Exception:
        logger.exception("Could not write SkySafari pointing status")


def _log_pointing_state(state) -> None:
    global _pointing_debug_last
    if not all(
        hasattr(state, attr) for attr in ("current", "solved", "imu", "mount", "health")
    ):
        return
    current = state.current
    solved = state.solved
    imu = state.imu
    mount = state.mount
    health = state.health
    current_radec = current.radec()
    signature = (
        current.source,
        current.reason,
        round(current_radec[0], 3) if current_radec is not None else None,
        round(current_radec[1], 3) if current_radec is not None else None,
        round(imu.alt_deg, 2) if imu.alt_deg is not None else None,
        round(imu.az_deg, 2) if imu.az_deg is not None else None,
        imu.metadata.get("filter_state"),
        solved.valid,
        solved.reason,
        imu.valid,
        imu.reason,
        mount.valid,
        mount.aligned,
        mount.reason,
        tuple(health.warnings),
    )
    now = time.monotonic()
    # Hard write throttle: the signature includes IMU alt/az at 0.01deg
    # resolution, so sensor jitter changes it nearly every 0.2s tick and,
    # ungated, this status write ran ~4x/second all
    # day. Consumers tolerate 5s staleness (POINTING_STATUS_MAX_AGE_SECONDS
    # in the GoTo/Guide service; the web UI only displays it), so cap
    # writes at one per 2s. Reset paths still force an immediate write via
    # _invalidate_pointing_cache() zeroing the timestamp.
    if now - _pointing_debug_last["time"] < 2.0:
        return
    _write_pointing_status(state)
    _pointing_debug_last = {
        "time": now,
        "signature": signature,
    }
    logger.debug(
        "SkySafari pointing source=%s coord=%s solved=%s/%s/%s imu=%s/%s "
        "imu_altaz=%s,%s mount=%s/aligned=%s/%s mount_coord=%s warnings=%s",
        current.source,
        _format_pointing_pair(current),
        solved.valid,
        solved.source,
        solved.reason or solved.metadata.get("solve_source", ""),
        imu.valid,
        imu.reason or imu.quality,
        f"{imu.alt_deg:.2f}" if imu.alt_deg is not None else "-",
        f"{imu.az_deg:.2f}" if imu.az_deg is not None else "-",
        mount.valid,
        mount.aligned,
        mount.reason or mount.quality,
        _format_pointing_pair(mount),
        "; ".join(health.warnings) or "-",
    )


def _invalidate_pointing_cache() -> None:
    _pointing_debug_last["time"] = 0.0
    _pointing_debug_last["signature"] = None


def _wrap_angle_delta_degrees(delta: float) -> float:
    return ((delta + 180.0) % 360.0) - 180.0


def _clamp_altitude_degrees(altitude: float) -> float:
    return max(-90.0, min(90.0, altitude))


def _reset_imu_alignment_correction(
    reason: str, *, clear_coordinate_state: bool = True
) -> None:
    if not _imu_alignment_correction["active"]:
        return
    logger.info("SkySafari IMU alignment correction reset: %s", reason)
    _imu_alignment_correction.update(
        {
            "active": False,
            "alt_offset": 0.0,
            "az_offset": 0.0,
            "set_at": 0.0,
            "target_coordinates": None,
        }
    )
    _invalidate_pointing_cache()
    if clear_coordinate_state:
        _coordinate_service.clear_state()


def _apply_imu_alignment_correction(alt: float, az: float) -> Tuple[float, float]:
    if not _imu_alignment_correction["active"]:
        return alt, az

    corrected_alt = _clamp_altitude_degrees(
        alt + float(_imu_alignment_correction["alt_offset"])
    )
    corrected_az = (az + float(_imu_alignment_correction["az_offset"])) % 360.0
    return corrected_alt, corrected_az


def _format_ra_degrees(ra_degrees: float) -> str:
    total_seconds = round(((ra_degrees % 360.0) / 15.0) * 3600.0)
    total_seconds %= 24 * 3600
    hh = total_seconds // 3600
    mm = (total_seconds % 3600) // 60
    ss = total_seconds % 60
    return f"{hh:02.0f}:{mm:02.0f}:{ss:02.0f}"


def _format_dec_degrees(dec_degrees: float) -> str:
    sign = "-" if dec_degrees < 0 else "+"
    total_seconds = min(round(abs(dec_degrees) * 3600.0), 90 * 3600)
    d = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{sign}{d:02d}*{m:02d}'{s:02d}"


def _imu_altaz_degrees(
    imu_sample, screen_direction: str
) -> Optional[Tuple[float, float]]:
    return _coordinate_service.imu_altaz_degrees(imu_sample, screen_direction)


def _configured_default_location() -> Optional[StateLocation]:
    configured = _get_config_option("locations.default", None)
    if configured is None:
        return None
    return StateLocation(
        lat=float(configured.latitude),
        lon=float(configured.longitude),
        altitude=float(configured.height),
        source=f"CONFIG: {configured.name}",
        lock=True,
        lock_type=2,
        error_in_m=float(configured.error_in_m),
    )


def _observer_location(shared_state) -> Optional[StateLocation]:
    location = shared_state.location()
    if location and location.lock:
        return location
    configured = _configured_default_location()
    if configured:
        return configured
    return location


def _requested_coordinates_to_altaz(
    ra_deg: float, dec_deg: float, location: StateLocation, dt
) -> Tuple[float, Optional[float]]:
    # SkySafari/LX200 coordinates are treated as the requested mount
    # coordinates for the current session.  Do not precess or otherwise
    # reinterpret them here; only convert the same coordinate frame to Alt/Az
    # for IMU alignment.
    return FastAltAz(location.lat, location.lon, dt).radec_to_altaz(
        ra_deg,
        dec_deg,
        alt_only=False,
    )


def _imu_fallback_pointing(
    shared_state, dt, apply_alignment: bool = True
) -> Optional[Tuple[float, float]]:
    sample = _coordinate_service.imu_sample(
        shared_state,
        dt,
        config_get=_get_config_option,
        default_location_provider=_configured_default_location,
        imu_alignment_correction=_imu_alignment_correction,
        apply_alignment=apply_alignment,
    )
    if not sample.valid:
        _log_fallback_skip(sample.reason or "unavailable")
        return None
    return sample.radec()


def _current_datetime(shared_state):
    dt = shared_state.datetime()
    if dt is not None:
        return dt
    return datetime.datetime.now(datetime.timezone.utc)


def _update_coordinate_service_state(shared_state):
    dt = _current_datetime(shared_state)
    state = _coordinate_service.update_state(
        shared_state,
        dt,
        config_get=_get_config_option,
        default_location_provider=_configured_default_location,
        mount_status_provider=_mount_control_status,
        imu_alignment_correction=_imu_alignment_correction,
    )
    _log_pointing_state(state)
    if state.solved.valid:
        _reset_imu_alignment_correction(
            "plate solve available",
            clear_coordinate_state=False,
        )
    return state


def _align_mount_to_imu_on_reset(shared_state) -> Optional[Tuple[float, float]]:
    """Re-align the mount to the current IMU coordinate (no-solve reset).

    When there is no valid plate solve, a bare ``clear_state()`` is not enough:
    the mount is still "aligned" (previously synced), so the selection priority
    keeps returning the mount coordinate and the display stays on the (possibly
    diverged) mount value instead of the IMU. To make the coordinate reflect the
    IMU, sync the mount to the current IMU RA/Dec. Sync only redefines the
    mount's coordinate system; it does not slew the scope. Returns the IMU
    RA/Dec that was applied, or None if no sync was issued.
    """
    state = _coordinate_service.get_state()
    if state is None:
        return None
    if state.solved is not None and state.solved.valid:
        # A solve is available; let it drive the coordinate. No IMU alignment.
        return None
    if not _mount_control_enabled():
        # No mount to align; clear_state alone will fall through to the IMU.
        return None
    # Use the raw IMU coordinate (apply_alignment=False), not the cached
    # state.imu sample: that sample was computed with any SkySafari alignment
    # offset applied, and reset must discard that offset, not re-bake it into
    # the mount's coordinate system.
    dt = _current_datetime(shared_state)
    imu_radec = _imu_fallback_pointing(shared_state, dt, apply_alignment=False)
    if imu_radec is None:
        logger.info("Pointing reset: no valid IMU coordinate to align the mount to")
        return None
    ra_deg, dec_deg = imu_radec
    if mountcontrol_queue is None:
        return None
    mountcontrol_queue.put(
        {
            "type": "sync",
            "ra": ra_deg,
            "dec": dec_deg,
            "origin": "pointing_reset",
            "pointing_source": "imu_fallback",
        }
    )
    logger.info(
        "Pointing reset: synced mount to IMU coordinate RA %.4f Dec %.4f",
        ra_deg,
        dec_deg,
    )
    return ra_deg, dec_deg


def _handle_pointing_reset_request(shared_state) -> None:
    """Poll for a "Reset Pointing" request file and reinitialize the service.

    Reset discards the accumulated fusion anchor / IMU-delta and any SkySafari
    IMU alignment offset so the coordinate re-baselines on the next tick from
    the best available source. When there is no plate solve it additionally
    syncs the mount to the current raw IMU coordinate
    (``_align_mount_to_imu_on_reset``) so the display follows the IMU rather
    than staying on the previously-synced mount value. This is the operator's
    escape hatch when the fused coordinate has diverged from the sky
    (bad/absent solves, a sync to the wrong target, or indoor IMU drift
    accumulating on the fused source).
    """
    global _pointing_reset_last_at
    try:
        if not _POINTING_RESET_REQUEST_FILE.exists():
            return
        source = "unknown"
        try:
            with open(_POINTING_RESET_REQUEST_FILE, encoding="utf-8") as request_in:
                request = json.load(request_in)
            source = str(request.get("source", "unknown"))
        except (json.JSONDecodeError, OSError):
            pass
        # Consume the request first so a failure below cannot spin-loop on it.
        try:
            _POINTING_RESET_REQUEST_FILE.unlink()
        except FileNotFoundError:
            pass
        # Discard any SkySafari IMU alignment offset first: reset must return
        # to the raw IMU coordinate, not carry a stale (possibly wrong-target)
        # alignment forward. clear_state runs below either way.
        _reset_imu_alignment_correction(
            "pointing reset request", clear_coordinate_state=False
        )
        # Capture the IMU coordinate and align the mount to it (no-solve case)
        # BEFORE clearing state, since clear_state() drops the cached samples.
        aligned = _align_mount_to_imu_on_reset(shared_state)
        _coordinate_service.clear_state()
        _invalidate_pointing_cache()
        # A reset re-establishes the coordinate frame; a tracking target from
        # before the reset (possibly hours stale or below the horizon) must
        # not drive a recovery slew against the new frame.
        if goto_guide_queue is not None:
            goto_guide_queue.put({"type": "clear_tracking_target"})
        _pointing_reset_last_at = time.time()
        logger.info(
            "Pointing coordinate service reset (source=%s, imu_align=%s)",
            source,
            "yes" if aligned is not None else "no",
        )
    except Exception:
        logger.exception("Could not handle pointing reset request")


def _location_distance_m(
    a: Tuple[float, float, float], b: Tuple[float, float, float]
) -> float:
    """Approximate ground distance in metres between two (lat, lon, alt)
    fixes. Equirectangular approximation -- ample for a "did we move?" gate."""
    lat1, lon1, alt1 = a
    lat2, lon2, alt2 = b
    mean_lat = math.radians((lat1 + lat2) / 2.0)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1) * math.cos(mean_lat)
    horizontal = math.hypot(dlat, dlon) * 6371000.0
    return math.hypot(horizontal, alt2 - alt1)


def _sync_mount_location_on_change(shared_state) -> None:
    """Re-send site location/time to the INDI mount when the observing
    location changes. The first locked fix is synced immediately; later
    changes are rate-limited to ``_LOCATION_RESYNC_RECHECK_SECONDS`` so GPS
    jitter cannot spam the mount (and repeatedly reset the fusion anchor)."""
    global _mount_synced_location, _next_location_resync_at
    if mountcontrol_queue is None:
        return
    if not bool(_get_config_option("mount_control", False)):
        return
    try:
        location = shared_state.location()
    except Exception:
        return
    if not location or not getattr(location, "lock", False):
        return
    current = (
        float(location.lat),
        float(location.lon),
        0.0 if location.altitude is None else float(location.altitude),
    )

    if _mount_synced_location is None:
        # First locked location since the service started -> sync now.
        _enqueue_mount_location_sync(current, "first locked location")
        return

    now = time.monotonic()
    if now < _next_location_resync_at:
        return
    _next_location_resync_at = now + _LOCATION_RESYNC_RECHECK_SECONDS
    if _location_distance_m(_mount_synced_location, current) < (
        _LOCATION_RESYNC_MOVE_THRESHOLD_M
    ):
        return
    _enqueue_mount_location_sync(current, "location changed")


def _enqueue_mount_location_sync(
    location: Tuple[float, float, float], reason: str
) -> None:
    global _mount_synced_location, _next_location_resync_at
    _mount_synced_location = location
    _next_location_resync_at = time.monotonic() + _LOCATION_RESYNC_RECHECK_SECONDS
    if mountcontrol_queue is not None:
        mountcontrol_queue.put({"type": "sync_location_time"})
    logger.info(
        "Mount location/time re-sync queued (%s): lat=%.5f lon=%.5f alt=%.0f",
        reason,
        location[0],
        location[1],
        location[2],
    )


def _detect_clock_jump(now_unix: float, now_monotonic: float) -> Optional[float]:
    """Return the jump size in seconds when the wall clock moved against the
    monotonic clock (chrony stepping a stale boot time), else None."""
    global _clock_jump_ref
    previous = _clock_jump_ref
    _clock_jump_ref = (now_unix, now_monotonic)
    if previous is None:
        return None
    drift = (now_unix - previous[0]) - (now_monotonic - previous[1])
    if abs(drift) < _CLOCK_JUMP_THRESHOLD_SECONDS:
        return None
    return drift


def _resync_mount_on_clock_events(
    now_unix: Optional[float] = None, now_monotonic: Optional[float] = None
) -> None:
    """A5: re-send mount site/time (and drop the tracking target on a jump)
    when the system clock jumps or first becomes trusted this session."""
    global _clock_trust_seen, _next_clock_trust_check_at

    if now_unix is None:
        now_unix = time.time()
    if now_monotonic is None:
        now_monotonic = time.monotonic()
    jump_seconds = _detect_clock_jump(now_unix, now_monotonic)
    if jump_seconds is not None:
        logger.warning(
            "System clock jumped by %+.1f s; re-syncing mount site/time and "
            "clearing the tracking target",
            jump_seconds,
        )
        if goto_guide_queue is not None:
            goto_guide_queue.put({"type": "clear_tracking_target"})
        if mountcontrol_queue is not None and bool(
            _get_config_option("mount_control", False)
        ):
            mountcontrol_queue.put({"type": "sync_location_time"})
        _clock_trust_seen = True
        return

    if now_monotonic < _next_clock_trust_check_at:
        return
    _next_clock_trust_check_at = now_monotonic + _CLOCK_TRUST_RECHECK_SECONDS
    trusted = gps_time_sync.read_clock_trust_marker() is not None
    previous_trust = _clock_trust_seen
    _clock_trust_seen = trusted
    if previous_trust is None or trusted == previous_trust:
        return
    if not trusted:
        return
    # Untrusted -> trusted without a visible jump (offset below the step
    # threshold): the mount still never received a trusted time this session.
    logger.info("System clock became trusted; re-syncing mount site/time")
    if mountcontrol_queue is not None and bool(
        _get_config_option("mount_control", False)
    ):
        mountcontrol_queue.put({"type": "sync_location_time"})


def _coordinate_service_loop(shared_state, stop_event: threading.Event) -> None:
    logger.info("Pointing coordinate service loop started")
    while not stop_event.is_set():
        try:
            _handle_pointing_reset_request(shared_state)
            _sync_mount_location_on_change(shared_state)
            _resync_mount_on_clock_events()
            _update_coordinate_service_state(shared_state)
        except Exception:
            logger.exception("Pointing coordinate service update failed")
        stop_event.wait(_POINTING_UPDATE_SECONDS)
    logger.info("Pointing coordinate service loop stopped")


def _start_coordinate_service_loop(shared_state) -> None:
    global _coordinate_service_thread, _coordinate_service_stop
    if _coordinate_service_thread is not None and _coordinate_service_thread.is_alive():
        return
    _coordinate_service_stop = threading.Event()
    _coordinate_service_thread = threading.Thread(
        target=_coordinate_service_loop,
        args=(shared_state, _coordinate_service_stop),
        name="PointingCoordinateService",
        daemon=True,
    )
    _coordinate_service_thread.start()


def _current_pointing(_shared_state) -> Optional[Tuple[float, float]]:
    state = _coordinate_service.get_state()
    if state is None:
        logger.debug("No published pointing coordinate state yet")
        return None
    display = getattr(state, "display", None)
    pointing: Optional[Tuple[float, float]]
    if display is not None and display.valid:
        pointing = display.radec()
        source = display.source
    else:
        pointing = state.radec()
        source = state.current.source
    if (
        pointing is not None
        and not is_stellarium
        and source in {"solve", "pifinder_imu_estimate"}
    ):
        return catalog_to_equinox_of_date(*pointing, _current_datetime(_shared_state))
    return pointing


def _catalog_target(shared_state, ra, dec):
    # SkySafari LX200 uses equinox of date; Stellarium's existing J2000
    # handshake path already supplies catalog axes. Keep raw protocol targets
    # for reconnects and native INDI alignment, convert at the PiFinder boundary.
    if is_stellarium:
        return ra, dec
    return equinox_of_date_to_catalog(ra, dec, _current_datetime(shared_state))


def get_telescope_ra(shared_state, _):
    """
    Extract RA from current solution
    format for LX200 protocol
    RA = HH:MM:SS
    """
    pointing = _current_pointing(shared_state)
    if pointing is None:
        return "00:00:00"

    ra_result = _format_ra_degrees(pointing[0])
    logger.debug("get_telescope_ra: RA result: %s", ra_result)
    return ra_result


def get_telescope_dec(shared_state, _):
    """
    Extract DEC from current solution
    format for LX200 protocol
    DEC = +/- DD*MM'SS
    """
    pointing = _current_pointing(shared_state)
    if pointing is None:
        return "+00*00'01"

    dec_result = _format_dec_degrees(pointing[1])
    logger.debug("get_telescope_dec: Dec result: %s", dec_result)
    return dec_result


def get_distance_bars(_shared_state, _input_str):
    global _skysafari_slew_started_at, _skysafari_saw_mount_slew
    status = _mount_control_status()
    state = str((status or {}).get("state", ""))
    now = time.monotonic()

    if state in _SKYSAFARI_SLEW_STATES:
        _skysafari_saw_mount_slew = True
        return "\x7f"

    if (
        _skysafari_slew_started_at
        and not _skysafari_saw_mount_slew
        and now - _skysafari_slew_started_at < _SKYSAFARI_SLEW_GRACE_SECONDS
    ):
        return "\x7f"

    _skysafari_slew_started_at = 0.0
    _skysafari_saw_mount_slew = False
    return ""


def _mark_skysafari_slew_started() -> None:
    global _skysafari_slew_started_at, _skysafari_saw_mount_slew
    _skysafari_slew_started_at = time.monotonic()
    _skysafari_saw_mount_slew = False


def _mount_control_status() -> dict:
    now = time.monotonic()
    if now - _mount_status_cache["time"] <= _MOUNT_STATUS_CACHE_SECONDS:
        return _mount_status_cache["value"] or {}

    status_file = utils.runtime_dir / "mount_control_status.json"
    try:
        with open(status_file, encoding="utf-8") as status_in:
            status = json.load(status_in)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        status = {}

    _mount_status_cache["time"] = now
    _mount_status_cache["value"] = status
    return status


def get_firmware_date(_shared_state, _input_str):
    return "Jan 28 2026"


def get_firmware_version(_shared_state, _input_str):
    return "01.0"


def get_product(_shared_state, _input_str):
    return "PiFinder"


def get_firmware_time(_shared_state, _input_str):
    return "17:25:00"


def _skysafari_lx200_mount_code() -> str:
    override = str(_get_config_option("skysafari_lx200_mount_code", "auto")).strip()
    override = override.upper()
    if override in {"A", "P", "G"}:
        return override

    mount_type = str(_get_config_option("mount_type", "Alt/Az")).strip().lower()
    if "alt" in mount_type and "az" in mount_type:
        return "A"
    return "P"


def get_status(_shared_state, _input_str):
    # LX200-style mount status: geometry, tracking, alignment.
    # A=Alt/Az, P=polar/equatorial, G=German equatorial override.
    return f"{_skysafari_lx200_mount_code()}T1"


def respond_none(shared_state, input_str):
    return None


def respond_zero(shared_state, input_str):
    return "0"


def respond_one(shared_state, input_str):
    return "1"


def _mount_control_enabled() -> bool:
    enabled = bool(_get_config_option("mount_control", False))
    has_queue = mountcontrol_queue is not None
    if not enabled or not has_queue:
        logger.info(
            "SkySafari mount-control unavailable: mount_control=%s queue=%s",
            enabled,
            has_queue,
        )
    return bool(enabled and has_queue)


def _goto_guide_enabled() -> bool:
    enabled = bool(_get_config_option("mount_control", False))
    has_queue = goto_guide_queue is not None
    if not enabled or not has_queue:
        logger.info(
            "SkySafari GoTo/Guide service unavailable: mount_control=%s queue=%s",
            enabled,
            has_queue,
        )
    return bool(enabled and has_queue)


def _has_solved_pointing(shared_state) -> bool:
    try:
        solution = shared_state.solution()
    except Exception:
        logger.debug("Could not read PiFinder solution state", exc_info=True)
        return False
    return bool(solution and solution.has_pointing())


def _queue_indi_goto_if_enabled(shared_state, ra_deg: float, dec_deg: float) -> bool:
    multipoint_active = _multipoint_align_active()
    if multipoint_active:
        if not _mount_control_enabled():
            return False
    elif not _goto_guide_enabled():
        return False

    goto_method = str(_get_config_option("indi_goto_method", "pifinder"))
    if goto_method == "off" and not multipoint_active:
        logger.info("SkySafari INDI GoTo skipped; GoTo Type is off")
        return False
    mount_queue = mountcontrol_queue
    guide_queue = goto_guide_queue

    # Same tracking-frequency policy as the web catalog push and the LCD GoTo
    # key, resolved by position: SkySafari sends bare coordinates with no
    # object type, so the ephemeris decides whether this is a planet (feed
    # forward its rate) or a static target (reset any non-sidereal frequency,
    # which would otherwise stay applied and quietly drift every later
    # target). Best-effort -- a missing mount-control queue must not block the
    # GoTo itself.
    if mount_queue is not None:
        try:
            freq_command = track_freq_command_for_coordinates(
                ra_deg,
                dec_deg,
                shared_state,
                identify_planets=bool(
                    _get_config_option("skysafari_planet_track_freq", True)
                ),
            )
            if freq_command is not None:
                mount_queue.put(freq_command)
                logger.info(
                    "SkySafari GoTo tracking frequency: %s", freq_command["type"]
                )
        except Exception:
            logger.exception("SkySafari track frequency policy failed")

    # Each path requires only the queue it actually uses. Demanding both would
    # drop align GoTos whenever the GoTo/Guide service is absent, contradicting
    # the bypass above that deliberately lets them through with GoTo Type off.
    if multipoint_active:
        if mount_queue is None:
            return False
        command = {
            "type": "multipoint_align_goto_target",
            "ra": ra_deg,
            "dec": dec_deg,
            "name": "SkySafari Target",
        }
        mount_queue.put(command)
        logger.info(
            "SkySafari multi-point align GoTo queued: RA %.4f Dec %.4f",
            ra_deg,
            dec_deg,
        )
    else:
        if guide_queue is None:
            return False
        if goto_method == "pifinder":
            ra_deg, dec_deg = _catalog_target(shared_state, ra_deg, dec_deg)
        command = {
            "type": "goto_target",
            "ra": ra_deg,
            "dec": dec_deg,
        }
        guide_queue.put(command)
        logger.info(
            "SkySafari INDI GoTo routed to GoTo/Guide service: RA %.4f Dec %.4f",
            ra_deg,
            dec_deg,
        )
    return True


def _queue_indi_sync_if_enabled(ra_deg: float, dec_deg: float) -> bool:
    if not _mount_control_enabled():
        return False
    if not bool(_get_config_option("skysafari_indi_sync", True)):
        logger.info("SkySafari INDI sync skipped; skysafari_indi_sync is off")
        return False
    if mountcontrol_queue is None:
        return False

    mountcontrol_queue.put(
        {
            "type": "sync",
            "ra": ra_deg,
            "dec": dec_deg,
            "origin": "skysafari_align",
            "pointing_source": "skysafari_target",
        }
    )
    logger.info("SkySafari INDI sync queued: RA %.4f Dec %.4f", ra_deg, dec_deg)
    return True


def _multipoint_align_active() -> bool:
    session = _mount_control_status().get("multipoint_align")
    if not isinstance(session, dict):
        return False
    return bool(session.get("active"))


def _queue_multipoint_align_confirm_if_active(ra_deg: float, dec_deg: float) -> bool:
    if not _multipoint_align_active():
        return False
    if not _mount_control_enabled():
        return False
    if mountcontrol_queue is None:
        return False

    mountcontrol_queue.put(
        {
            "type": "multipoint_align_confirm",
            "ra": ra_deg,
            "dec": dec_deg,
            "source": "skysafari",
        }
    )
    logger.info(
        "SkySafari sync routed to INDI multi-point alignment: RA %.4f Dec %.4f",
        ra_deg,
        dec_deg,
    )
    if console_queue is not None:
        console_queue.put("INDI Multi Align Point")
    return True


def _set_imu_alignment_from_target_if_no_solve(
    shared_state, ra_deg: float, dec_deg: float
) -> bool:
    # Always enabled: a SkySafari Align before the first plate solve is the
    # supported way to bootstrap IMU-only pointing. Confirmed as intended in
    # both GoTo modes (B7, docs/mf_report/mf_field_test_20260724_analysis_ko.md): no
    # mount transmission, target_pixel untouched, IMU-fallback display only.
    if _has_solved_pointing(shared_state):
        return False

    location = _observer_location(shared_state)
    if not location or not location.lock:
        logger.warning("SkySafari IMU align skipped; location is not locked")
        return False

    dt = _current_datetime(shared_state)
    if not dt:
        logger.warning("SkySafari IMU align skipped; no PiFinder time")
        return False

    screen_direction = _get_config_option("screen_direction", "right")
    imu_altaz = _imu_altaz_degrees(shared_state.imu(), screen_direction)
    if imu_altaz is None:
        logger.warning("SkySafari IMU align skipped; no calibrated IMU orientation")
        return False

    try:
        target_alt, target_az = _requested_coordinates_to_altaz(
            ra_deg,
            dec_deg,
            location,
            dt,
        )
    except Exception:
        logger.warning(
            "SkySafari IMU align skipped; target alt/az failed", exc_info=True
        )
        return False
    if target_az is None:
        logger.warning("SkySafari IMU align skipped; target azimuth missing")
        return False

    imu_alt, imu_az = imu_altaz
    alt_offset = target_alt - imu_alt
    az_offset = _wrap_angle_delta_degrees(target_az - imu_az)
    _imu_alignment_correction.update(
        {
            "active": True,
            "alt_offset": alt_offset,
            "az_offset": az_offset,
            "set_at": time.monotonic(),
            "target_coordinates": (ra_deg % 360.0, dec_deg),
        }
    )
    _invalidate_pointing_cache()
    _coordinate_service.clear_state()

    if console_queue is not None:
        console_queue.put("SkySafari IMU Alignment Set")
    logger.info(
        "SkySafari IMU alignment set without solve: "
        "target_alt=%.3f target_az=%.3f imu_alt=%.3f imu_az=%.3f "
        "alt_offset=%.3f az_offset=%.3f",
        target_alt,
        target_az,
        imu_alt,
        imu_az,
        alt_offset,
        az_offset,
    )
    return True


def _align_pifinder_if_enabled(shared_state, ra_deg: float, dec_deg: float) -> bool:
    if not _get_config_option("skysafari_pifinder_align", True):
        return False
    started = time.monotonic()
    try:
        mount = _mount_control_status()
        if mount.get("mount_motion_active") or mount.get("goto_motion_active"):
            raise ValueError("mount is moving")
        if float(mount.get("guide_pulse_until_wall") or 0.0) > time.time():
            raise ValueError("guide pulse is still settling")
        estimate = shared_state.solution()
        target_pixel = cached_target_pixel(
            estimate,
            shared_state.imu(),
            ra_deg,
            dec_deg,
            now=time.time(),
            context=projection_context(shared_state, pos_server_config),
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        if console_queue is not None:
            console_queue.put("SkySafari Align: fresh stationary solve needed")
        logger.warning("SkySafari cached align unavailable: %s", exc)
        return False

    if mountcontrol_queue is not None and _mount_control_enabled():
        mountcontrol_queue.put({"type": "toggle_guide_correction", "enabled": False})
    shared_state.set_target_pixel(target_pixel)
    if pos_server_config is not None:
        pos_server_config.set_option("target_pixel", target_pixel)
    if console_queue is not None:
        console_queue.put("SkySafari Alignment Set")
    ui_queue.put("reload_config")
    logger.info(
        "SkySafari PiFinder align set target pixel: %s (cached solve age %.3fs, %.1fms)",
        target_pixel,
        time.time() - estimate.last_solve_success,
        (time.monotonic() - started) * 1000,
    )
    return True


def _sd_to_deg(parsed) -> float:
    sign, deg, minutes, seconds = parsed
    return sign * (deg + minutes / 60 + seconds / 3600)


def _target_from_parsed_coordinates() -> Optional[Tuple[float, float]]:
    if not sr_result or not sd_result:
        return None

    ra = ra_to_deg(*sr_result)
    dec = _sd_to_deg(sd_result)
    return ra % 360.0, dec


def _queue_mountcontrol_command(command: dict) -> bool:
    if mountcontrol_queue is None:
        return False
    mountcontrol_queue.put(command)
    return True


def _schedule_skysafari_guide_keepalive_locked(token: int) -> None:
    timer = threading.Timer(
        _GUIDE_KEEPALIVE_SECONDS,
        _skysafari_guide_keepalive_if_current,
        args=(token,),
    )
    timer.daemon = True
    _guide_motion_state["timer"] = timer
    timer.start()


def _skysafari_guide_keepalive_if_current(token: int) -> None:
    command_type = "manual_movement_keepalive"
    with _guide_motion_lock:
        if token != _guide_motion_state["token"]:
            return
        direction = _guide_motion_state["direction"]
        if not direction:
            return

        now = time.monotonic()
        started_at = float(_guide_motion_state.get("started_at") or now)
        if now - started_at >= _GUIDE_MAX_HOLD_SECONDS:
            _guide_motion_state["token"] = int(_guide_motion_state["token"]) + 1
            _guide_motion_state["direction"] = None
            _guide_motion_state["timer"] = None
            _guide_motion_state["started_at"] = 0.0
            _guide_motion_state["next_restart_at"] = 0.0
            direction = None
        else:
            next_restart_at = float(_guide_motion_state.get("next_restart_at") or 0.0)
            if next_restart_at and now >= next_restart_at:
                command_type = "manual_movement"
                _guide_motion_state["next_restart_at"] = now + _GUIDE_RESTART_SECONDS
            _schedule_skysafari_guide_keepalive_locked(token)

    if direction is None:
        _queue_mountcontrol_command({"type": "stop_movement"})
        logger.warning("SkySafari guide maximum hold time exceeded; stop queued")
        return

    if token != _guide_motion_state["token"]:
        return
    if not direction:
        return

    _queue_mountcontrol_command(
        {
            "type": command_type,
            "direction": direction,
            "lease_seconds": _GUIDE_LEASE_SECONDS,
        }
    )
    logger.debug("SkySafari guide %s queued: %s", command_type, direction)


def _start_skysafari_guide_keepalive(direction: str) -> Optional[str]:
    with _guide_motion_lock:
        previous_direction = _guide_motion_state["direction"]
        timer = _guide_motion_state.get("timer")
        if timer is not None:
            timer.cancel()

        _guide_motion_state["token"] = int(_guide_motion_state["token"]) + 1
        token = int(_guide_motion_state["token"])
        _guide_motion_state["direction"] = direction
        _guide_motion_state["started_at"] = time.monotonic()
        _guide_motion_state["next_restart_at"] = (
            _guide_motion_state["started_at"] + _GUIDE_RESTART_SECONDS
        )
        _schedule_skysafari_guide_keepalive_locked(token)
        return previous_direction if isinstance(previous_direction, str) else None


def _stop_skysafari_guide_keepalive() -> bool:
    with _guide_motion_lock:
        had_direction = _guide_motion_state["direction"] is not None
        timer = _guide_motion_state.get("timer")
        _guide_motion_state["token"] = int(_guide_motion_state["token"]) + 1
        _guide_motion_state["direction"] = None
        _guide_motion_state["timer"] = None
        _guide_motion_state["started_at"] = 0.0
        _guide_motion_state["next_restart_at"] = 0.0

    if timer is not None:
        timer.cancel()
    return had_direction


def handle_guide_move(_shared_state, input_str: str):
    command = extract_command(input_str)
    direction = _GUIDE_DIRECTIONS.get(command)
    if not direction:
        return None

    if _mount_control_enabled() and mountcontrol_queue is not None:
        previous_direction = _start_skysafari_guide_keepalive(direction)
        if previous_direction and previous_direction != direction:
            _queue_mountcontrol_command({"type": "stop_movement"})
        _queue_mountcontrol_command(
            {
                "type": "manual_movement",
                "direction": direction,
                "lease_seconds": _GUIDE_LEASE_SECONDS,
            }
        )
        logger.debug("SkySafari guide move queued: %s", direction)
    else:
        logger.debug("SkySafari guide move ignored; INDI mount control is disabled")
    return None


def handle_guide_stop(_shared_state, _input_str: str):
    had_active_motion = _stop_skysafari_guide_keepalive()
    command = extract_command(_input_str)
    # SkySafari sends Qn/Qs/Qe/Qw (and some versions send a bare Q) when a
    # direction button is released.  That must stop the motor without erasing
    # the tracking target; the guide service then classifies it as a user
    # manual move and may adopt the stopped position as the new target. A bare
    # Q with no active direction remains an explicit GoTo/Guide abort and
    # clears the target.
    explicit_abort = command == "Q" and not had_active_motion
    if goto_guide_queue is not None and explicit_abort:
        goto_guide_queue.put({"type": "stop_movement"})
    if (
        _mount_control_enabled() or had_active_motion
    ) and mountcontrol_queue is not None:
        _queue_mountcontrol_command({"type": "stop_movement"})
        logger.info(
            "SkySafari %s queued; tracking target %s",
            "abort" if explicit_abort else "guide release",
            "cleared" if explicit_abort else "preserved",
        )
    else:
        logger.debug("SkySafari guide stop ignored; INDI mount control is disabled")
    return None


def not_implemented(shared_state, input_str):
    # return "not implemented"
    return respond_none(shared_state, input_str)


def abort_slew(shared_state, input_str: str) -> Optional[str]:
    """Keep MF's real stop/guide-release behavior; only ACK clients get a reply."""
    handle_guide_stop(shared_state, input_str)
    return "1" if is_stellarium else None


def _match_to_hms(pattern: str, input_str: str) -> Union[Tuple[int, int, int], None]:
    match = re.match(pattern, input_str)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        return hours, minutes, seconds
    else:
        return None


def parse_sr_command(_, input_str: str):
    global sr_result, sd_result
    pattern = r"#?:Sr(\d{2}):(\d{2}):(\d{2})#$"
    match = _match_to_hms(pattern, input_str)
    logger.debug("Parsing sr command, match: %s", match)
    # A new RA begins a fresh pair; never combine it with an old Dec.
    sr_result = sd_result = None
    if match and 0 <= match[0] < 24 and 0 <= match[1] < 60 and 0 <= match[2] < 60:
        sr_result = match
        return "1"
    else:
        return "0"


def parse_sd_command(shared_state, input_str: str):
    global sd_result
    # Capture the sign separately: int("-00") loses it, which flipped every
    # -1 deg < Dec < 0 deg target (e.g. M2) to the northern hemisphere.
    pattern = r"#?:Sd([-+]?)(\d{2})[*:](\d{2}):(\d{2})#"
    match = re.fullmatch(pattern, input_str)
    logger.debug("Parsing sd command, match: %s, sr_result: %s", match, sr_result)
    sd_result = None
    if match and sr_result:
        sign = -1 if match.group(1) == "-" else 1
        degrees, minutes, seconds = map(int, match.groups()[1:])
        if (
            minutes >= 60
            or seconds >= 60
            or degrees + minutes / 60 + seconds / 3600 > 90
        ):
            return "0"
        sd_result = (
            sign,
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
        )
        return "1"
    else:
        return "0"


def handle_slew_command(shared_state, _input_str: str):
    if sr_result and sd_result:
        logger.info("SkySafari :MS# received; queuing GoTo for stored target")
        handle_goto_command(shared_state, sr_result, sd_result)
        _mark_skysafari_slew_started()
        # LX200 :MS# returns 0 when the slew starts. 1 means "object below
        # horizon", so do not forward the target-coordinate ACK here.
        return "0"
    logger.warning("SkySafari GoTo ignored; target coordinates are incomplete")
    return "1"


def handle_sync_command(shared_state, _input_str: str):
    parsed_target = _target_from_parsed_coordinates()
    target_source = "parsed_coordinates" if parsed_target is not None else "last_goto"
    target = parsed_target or last_target_coordinates
    if target is None:
        logger.warning("SkySafari sync ignored; no target coordinates")
        return "No target."

    ra_deg, dec_deg = target
    if _queue_multipoint_align_confirm_if_active(ra_deg, dec_deg):
        return "Coordinates matched."

    goto_method = str(_get_config_option("indi_goto_method", "pifinder"))
    has_solved_pointing = _has_solved_pointing(shared_state)
    pifinder_aligned = False
    imu_aligned = False
    if has_solved_pointing:
        _reset_imu_alignment_correction("SkySafari sync with solved pointing")
        # B6 mode routing (docs/mf_report/mf_field_test_20260724_analysis_ko.md): in
        # pifinder mode a SkySafari Align performs BOTH the PiFinder align
        # (same as LCD Start > Align) and the INDI mount sync below. In
        # indi_mount mode only the mount sync goes out; the PiFinder align
        # (target_pixel) changes through the LCD menu alone.
        if goto_method == "pifinder":
            ra_deg, dec_deg = _catalog_target(shared_state, ra_deg, dec_deg)
            pifinder_aligned = _align_pifinder_if_enabled(shared_state, ra_deg, dec_deg)
            if (
                _get_config_option("skysafari_pifinder_align", True)
                and not pifinder_aligned
            ):
                # Do not partially sync the mount or arm tracking after a
                # rejected local alignment. No delayed solver command exists.
                return "Alignment unavailable."
    else:
        imu_aligned = _set_imu_alignment_from_target_if_no_solve(
            shared_state, ra_deg, dec_deg
        )
    indi_synced = _queue_indi_sync_if_enabled(ra_deg, dec_deg)
    tracking_target_set = False
    if (
        goto_method == "pifinder"
        and goto_guide_queue is not None
        and (pifinder_aligned or imu_aligned or indi_synced)
    ):
        tracking_command = {"type": "set_tracking_target", "ra": ra_deg, "dec": dec_deg}
        if pifinder_aligned:
            tracking_command["alignment_target_pixel"] = list(
                shared_state.target_pixel()
            )
        goto_guide_queue.put(tracking_command)
        tracking_target_set = True
    if pifinder_aligned:
        _publish_push_target(shared_state, ra_deg, dec_deg, preserve_name=True)
    logger.info(
        "SkySafari sync handled: target_source=%s goto_method=%s "
        "pifinder_aligned=%s imu_aligned=%s indi_synced=%s "
        "tracking_target=%s target=%.4f,%.4f",
        target_source,
        goto_method,
        pifinder_aligned,
        imu_aligned,
        indi_synced,
        tracking_target_set,
        ra_deg,
        dec_deg,
    )
    return "Coordinates matched."


def handle_goto_command(shared_state, ra_parsed, dec_parsed):
    global sequence, ui_queue, is_stellarium, last_target_coordinates
    ra = ra_to_deg(*ra_parsed)
    dec = _sd_to_deg(dec_parsed)
    target_ra, target_dec = ra % 360.0, dec
    last_target_coordinates = (target_ra, target_dec)
    logger.debug("Goto target coordinates: %s, %s", target_ra, target_dec)
    if _multipoint_align_active():
        logger.info(
            "SkySafari GoTo routed to INDI multi-point alignment without "
            "push-to UI transition: RA %.4f Dec %.4f",
            target_ra,
            target_dec,
        )
        _queue_indi_goto_if_enabled(shared_state, target_ra, target_dec)
        return "1"

    _publish_push_target(
        shared_state, *_catalog_target(shared_state, target_ra, target_dec)
    )
    _queue_indi_goto_if_enabled(shared_state, target_ra, target_dec)
    return "1"


def _publish_push_target(shared_state, target_ra, target_dec, preserve_name=False):
    """Show the exact target used for alignment and tracking on the LCD."""
    global sequence
    sequence += 1
    constellation = sf_utils.radec_to_constellation(target_ra, target_dec)
    obj = CompositeObject.from_dict(
        {
            "id": -1,
            "object_id": sys.maxsize - sequence,
            "obj_type": "",
            "ra": target_ra,
            "dec": target_dec,
            "const": constellation,
            "size": SizeObject([]),
            "mag": MagnitudeObject([]),
            "catalog_code": "PUSH",
            "sequence": sequence,
            "description": f"Pushed object nr {sequence}",
        }
    )
    if preserve_name:
        previous = getattr(shared_state.ui_state(), "target", lambda: None)()
        if previous is not None:
            from PiFinder.track_freq_policy import _angular_separation_deg

            if (
                _angular_separation_deg(
                    previous.ra, previous.dec, target_ra, target_dec
                )
                < 0.1
            ):
                obj = copy.deepcopy(previous)
                obj.ra, obj.dec = target_ra, target_dec
    logger.debug("handle_goto_command: Pushing object: %s", obj)
    shared_state.ui_state().add_recent(obj)
    shared_state.ui_state().set_new_pushto(True)
    ui_queue.put("push_object")


# Site and clock commands.  Stellarium runs through these during its connection
# handshake and gives up on the push if they go unanswered.


def set_current_date(_shared_state, _input_str) -> str:
    """:SCMM/DD/YY# -- accept and discard the client's date.

    PiFinder takes its civil time from GPS or manual entry, so the value is
    dropped.  The reply shape is fixed by the protocol: "1" followed by the
    already-terminated status string a Meade mount sends while it rebuilds
    planetary data.
    """
    return "1Updating Planetary Data#                         #"


def get_current_date(shared_state, _input_str) -> Optional[str]:
    """:GC# -- local calendar date as MM/DD/YY.

    Hardcoded rather than %x: LX200 fixes this format, while %x follows the
    process locale, which the i18n work can change out from under us.
    """
    dt = shared_state.local_datetime()
    if dt is None:
        return None
    return dt.strftime("%m/%d/%y")


def get_current_time(shared_state, _input_str) -> Optional[str]:
    """:GL# -- local civil time as 24-hour HH:MM:SS.

    LX200 defines this as *local* time, so read the observer's zone directly
    (ADR-0018) rather than offsetting UTC by hand.  %X is avoided for the same
    locale reason as %x above.
    """
    dt = shared_state.local_datetime()
    if dt is None:
        return None
    return dt.strftime("%H:%M:%S")


def get_utc_offset(shared_state, _input_str) -> Optional[str]:
    """:GG# -- hours to ADD to local time to reach UTC, as sHH (or sHH.H).

    Note the inverted sign: LX200 asks for the correction *towards* UTC, so US
    Eastern (UTC-5) answers "+05" and Berlin in winter (UTC+1) answers "-01".
    Half-hour zones use the sHH.H form; zones on a quarter hour round to the
    nearest tenth, which is as fine as the protocol goes.
    """
    dt = shared_state.local_datetime()
    if dt is None:
        return None
    offset = dt.utcoffset()
    if offset is None:
        return None
    hours = -offset.total_seconds() / 3600.0
    sign = "-" if hours < 0 else "+"
    magnitude = abs(hours)
    if magnitude == int(magnitude):
        return f"{sign}{int(magnitude):02d}"
    return f"{sign}{magnitude:04.1f}"


# The site setters keep the sign and the degree width the client used so :Gt#
# and :Gg# can echo it back unchanged; only the seconds field, which the
# getters have no room for, is dropped.
_SITE_LAT_PATTERN = r"#?:St([-+]?)(\d{1,2})\*(\d{2})"
_SITE_LON_PATTERN = r"#?:Sg([-+]?)(\d{1,3})\*(\d{2})"


def set_latitude(_shared_state, input_str: str) -> str:
    """:StsDD*MM# -- remember the client's site latitude for :Gt# to echo."""
    global stellarium_latitude
    match = re.search(_SITE_LAT_PATTERN, input_str)
    if not match:
        logger.debug("set_latitude: no match in %s", input_str)
        return "0"
    sign, degrees, minutes = match.groups()
    stellarium_latitude = f"{sign or '+'}{int(degrees):02d}*{minutes}"
    return "1"


def set_longitude(_shared_state, input_str: str) -> str:
    """:SgDDD*MM# -- remember the client's site longitude for :Gg# to echo."""
    global stellarium_longitude
    match = re.search(_SITE_LON_PATTERN, input_str)
    if not match:
        logger.debug("set_longitude: no match in %s", input_str)
        return "0"
    sign, degrees, minutes = match.groups()
    stellarium_longitude = f"{sign}{int(degrees):03d}*{minutes}"
    return "1"


def _deg_to_dm(value: float, degree_len: int) -> str:
    """Format signed decimal degrees as the LX200 sDD*MM form.

    Rounds to whole arcminutes and carries into the degrees field, so 42.999
    formats as "+43*00" rather than the out-of-range "+42*60".
    """
    sign = "-" if value < 0 else "+"
    degrees, minutes = divmod(round(abs(value) * 60), 60)
    return f"{sign}{degrees:0{degree_len}d}*{minutes:02d}"


def _lon_to_meade_dm(value: float) -> str:
    """Format signed east-positive longitude as Meade's unsigned DDD*MM.

    Meade counts site longitude positive *westward* across 000-359 -- the same
    convention :Sg# accepts -- while PiFinder stores it signed and
    east-positive.  Negating and wrapping converts between the two: Boston
    (-71.06) becomes 071*04 and Berlin (+13.4) becomes 346*36.  The wrap is
    applied after rounding to minutes so a site just east of Greenwich cannot
    round up into a nonexistent 360*00.
    """
    degrees, minutes = divmod(round(-value * 60) % (360 * 60), 60)
    return f"{degrees:03d}*{minutes:02d}"


def get_latitude(shared_state, _input_str) -> str:
    """:Gt# -- current site latitude as sDD*MM."""
    if stellarium_latitude:
        return stellarium_latitude
    return _deg_to_dm(shared_state.location().lat, 2)


def get_longitude(shared_state, _input_str) -> str:
    """:Gg# -- current site longitude as DDD*MM."""
    if stellarium_longitude:
        return stellarium_longitude
    return _lon_to_meade_dm(shared_state.location().lon)


# Function to extract command
def extract_command(s):
    match = re.search(r":([A-Za-z]+)", s)
    return match.group(1) if match else None


def _pop_lx200_message(buffer: str) -> Tuple[Optional[str], str]:
    ack_index = buffer.find("\x06")
    command_index = buffer.find(":")

    if ack_index != -1 and (command_index == -1 or ack_index < command_index):
        return "\x06", buffer[ack_index + 1 :]

    if command_index == -1:
        return None, buffer[-1:] if buffer.endswith(":") else ""

    if command_index > 0:
        buffer = buffer[command_index:]

    end_index = buffer.find("#")
    if end_index == -1:
        return None, buffer

    return buffer[: end_index + 1], buffer[end_index + 1 :]


def _format_lx200_response(out_data: str) -> bytes:
    is_bare_status = bool(re.fullmatch(r"[APG]T\d", out_data))
    response = (
        out_data
        if out_data in ("0", "1") or is_bare_status or out_data.endswith("#")
        else out_data + "#"
    )
    return response.encode()


lx_command_dict = {
    "D": get_distance_bars,
    "GD": get_telescope_dec,
    "GR": get_telescope_ra,
    "GVD": get_firmware_date,
    "GVN": get_firmware_version,
    "GVP": get_product,
    "GVT": get_firmware_time,
    "GW": get_status,
    "CM": handle_sync_command,
    "Mn": handle_guide_move,
    "Ms": handle_guide_move,
    "Me": handle_guide_move,
    "Mw": handle_guide_move,
    "Qn": handle_guide_stop,
    "Qs": handle_guide_stop,
    "Qe": handle_guide_stop,
    "Qw": handle_guide_stop,
    "RS": respond_none,  # Set slew rate to max
    "RM": respond_none,  # Set slew rate to find
    "RC": respond_none,  # Set slew rate to center
    "RG": respond_none,  # Set slew rate to guide
    "MS": handle_slew_command,  # Slew to object
    "Q": abort_slew,  # Actual MF stop, plus Stellarium-only acknowledgement
    "U": respond_none,  # Precision toggle
    "Sd": parse_sd_command,  # Set declination
    "Sr": parse_sr_command,  # Set RA
    # Handshake-only setters: never steer MF's GPS clock or observing site.
    "SG": respond_one,
    "SL": respond_one,
    "SC": set_current_date,
    "St": set_latitude,
    "Sg": set_longitude,
    "GC": get_current_date,
    "GL": get_current_time,
    "GG": get_utc_offset,
    "Gt": get_latitude,
    "Gg": get_longitude,
}


def setup_server_socket():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("", 4030))
    server_socket.listen(1)
    return server_socket


def _reset_lx200_session(*, preserve_target: bool = False) -> None:
    """Clear socket-local state, optionally retaining a reconnecting target."""
    global is_stellarium, stellarium_latitude, stellarium_longitude
    global sr_result, sd_result, last_target_coordinates
    global _lx200_target_host, _lx200_target_last_seen
    is_stellarium = False
    stellarium_latitude = stellarium_longitude = ""
    if not preserve_target:
        sr_result = sd_result = last_target_coordinates = None
        _lx200_target_host = None
        _lx200_target_last_seen = 0.0


def handle_frame(frame: str, shared_state) -> Optional[str]:
    """Dispatch one complete frame; the socket loop owns stream reassembly."""
    global is_stellarium
    if frame.lstrip("#") == "\x06":
        is_stellarium = True
        # Upstream's Mobile Plus compatibility handshake. This is only an ACK
        # reply; :GW# still reports MF's configured mount geometry truthfully.
        return "P"
    command = extract_command(frame)
    # A malformed alphabetical payload (e.g. :Srbad#) is still a target
    # setter. Send it through validation so it invalidates a stale target,
    # rather than treating 'Srbad' as an unrelated unknown command.
    target_setter = re.match(r"#?:(Sr|Sd)", frame)
    if target_setter is not None:
        command = target_setter.group(1)
    if not command:
        return None
    handler = lx_command_dict.get(command, not_implemented)
    payload = handler(shared_state, frame)
    return None if payload is None else _format_lx200_response(payload).decode()


def handle_client(client_socket, shared_state, client_host: Optional[str] = None):
    global _lx200_target_host, _lx200_target_last_seen
    # SkySafari can send Sr, Sd and MS/CM on separate TCP connections. Retain
    # its target across those connections, including intervening GR/GD polls.
    # A different host or an idle gap starts a fresh target transaction.
    preserve_target = (
        client_host is not None
        and client_host == _lx200_target_host
        and time.monotonic() - _lx200_target_last_seen < _LX200_TARGET_RECONNECT_SECONDS
    )
    _reset_lx200_session(preserve_target=preserve_target)
    _lx200_target_host = client_host
    input_buffer = ""
    try:
        client_socket.settimeout(60)
        client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        while True:
            # LX200 is byte-oriented; an unexpected high byte must not crash
            # the entire position server. Command validators reject bad data.
            in_data = client_socket.recv(1024).decode("latin-1")
            if not in_data:
                break
            _lx200_target_last_seen = time.monotonic()
            input_buffer += in_data
            if len(input_buffer) > 4096:
                logger.warning("LX200 unterminated command too long; closing client")
                break
            logger.debug("Received from planetarium client: %s", in_data)
            while input_buffer:
                message, input_buffer = _pop_lx200_message(input_buffer)
                if message is None:
                    break
                command_started = time.monotonic()
                response = handle_frame(message, shared_state)
                if response is not None:
                    client_socket.sendall(response.encode())
                if extract_command(message) == "CM":
                    logger.info(
                        "SkySafari CM response sent in %.1fms: %s",
                        (time.monotonic() - command_started) * 1000,
                        response,
                    )
    except socket.timeout:
        logger.warning("Connection timed out.")
    except (ConnectionResetError, BrokenPipeError):
        logger.warning("Client disconnected unexpectedly.")
    finally:
        # MF guide buttons may use short-lived command connections. Keep their
        # motion/keepalive state across sockets; Q/Qn/... and the existing
        # lease/max-hold safeguards own the stop, not a socket close.
        _reset_lx200_session(preserve_target=client_host is not None)
        client_socket.close()


def run_server(
    shared_state,
    p_ui_queue,
    log_queue,
    p_mountcontrol_queue=None,
    p_goto_guide_queue=None,
    p_align_command_queue=None,
    p_align_response_queue=None,
    p_console_queue=None,
):
    MultiprocLogging.configurer(log_queue)
    global ui_queue, mountcontrol_queue, goto_guide_queue, pos_server_config
    global _config_last_loaded
    global align_command_queue, align_response_queue, console_queue
    ui_queue = p_ui_queue
    mountcontrol_queue = p_mountcontrol_queue
    goto_guide_queue = p_goto_guide_queue
    align_command_queue = p_align_command_queue
    align_response_queue = p_align_response_queue
    console_queue = p_console_queue
    pos_server_config = config.Config()
    _config_last_loaded = time.monotonic()
    logger = logging.getLogger(__name__)
    _start_coordinate_service_loop(shared_state)

    while True:
        try:
            with setup_server_socket() as server_socket:
                logger.info("SkySafari server started and listening")
                while True:
                    client_socket, address = server_socket.accept()
                    logger.debug("New connection from %s", address)
                    handle_client(client_socket, shared_state, address[0])
        except Exception:
            logger.exception("Unexpected server error")
            logger.info("Attempting to restart server in 5 seconds...")
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Server shutting down...")
            break
