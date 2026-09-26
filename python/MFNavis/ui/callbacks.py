#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module holds some callbacks
used by the menu system

Each one takes the current ui module as an argument

"""

from __future__ import annotations

import logging
import gettext
import json
import os
import time
from datetime import datetime
from functools import wraps

import pytz
import sh

from typing import Any, Optional, TYPE_CHECKING
from PiFinder import timez
from PiFinder import utils, calc_utils
from PiFinder.boot_config import get_boot_config_path
from PiFinder.locations import Location as SavedLocation
from PiFinder.mf_manual_lens import normalise_manual_focal_length, calibration_lens_key
from PiFinder.mf_wide_calibration import CalibrationProfileStore
from PiFinder.optics import LENSES
from PiFinder.sqm.camera_profiles import get_camera_profile
from PiFinder.state import Location
from PiFinder.types.positioning import (
    CancelDistortionCalibration,
    StartLensMeasurement,
    StartDistortionCalibration,
)
from PiFinder.ui.base import UIModule
from PiFinder.ui.textentry import UITextEntry
from PiFinder.catalogs import CatalogFilter
from PiFinder.composite_object import CompositeObject, MagnitudeObject, SizeObject

if TYPE_CHECKING:
    from PiFinder.ui.text_menu import UITextMenu

    def _(a) -> Any:
        return a


sys_utils = utils.get_sys_utils()


logger = logging.getLogger("UI.Callbacks")


def go_back(ui_module: UIModule) -> None:
    """
    Just removes the current ui module fom the stack
    """
    ui_module.remove_from_stack()
    return


def show_advanced_message(ui_module: UIModule) -> None:
    """
    Show popup message when entering Advanced settings menu
    """
    ui_module.message(_("Options for\nDIY MFNaviss"), 2)
    return


def reset_filters(ui_module: UIModule) -> None:
    """
    Reset all filters to default
    """
    ui_module.config_object.reset_filters()

    new_filter = CatalogFilter(shared_state=ui_module.shared_state)
    new_filter.load_from_config(ui_module.config_object)

    ui_module.catalogs.set_catalog_filter(new_filter)
    ui_module.catalogs.filter_catalogs()
    ui_module.message(_("Filters Reset"))
    ui_module.remove_from_stack()
    return


def activate_debug(ui_module: UIModule) -> None:
    """
    Sets camera into debug
    add fake gps info
    """
    ui_module.command_queues["camera"].put("debug")
    ui_module.command_queues["console"].put("Test Mode Activated")
    ui_module.command_queues["ui_queue"].put("test_mode")
    ui_module.message(_("Test Mode"))


def set_exposure(ui_module: UIModule) -> None:
    """
    Sets exposure to current value in config option
    Can be a numeric value (microseconds), "auto" for match-count
    auto-exposure, or "auto_star" for star-count auto-exposure
    """
    new_exposure = ui_module.config_object.get_option("camera_exp")
    if new_exposure in ("auto", "auto_star"):
        logger.info("Set exposure to %s mode", new_exposure)
    else:
        logger.info("Set exposure %f", new_exposure)
    ui_module.command_queues["camera"].put(f"set_exp:{new_exposure}")


def _format_gain(gain: float | int | None) -> str:
    if gain is None:
        return ""
    gain_float = float(gain)
    if gain_float.is_integer():
        return f"{int(gain_float)}x"
    return f"{gain_float:g}x"


def _get_current_camera_gain(ui_module: UIModule) -> float | None:
    try:
        metadata = ui_module.shared_state.last_image_metadata()
        if metadata and "gain" in metadata:
            return float(metadata["gain"])
    except Exception:
        return None
    return None


def _get_profile_camera_gain(ui_module: UIModule) -> float | None:
    try:
        cam_type = get_camera_type(ui_module)[0]
        return float(get_camera_profile(cam_type).analog_gain)
    except Exception:
        return None


def get_camera_gain_selection(ui_module: UIModule) -> list[float | str | None]:
    """
    Return the current runtime camera gain for the gain menu checkmark.
    """
    current_gain = _get_current_camera_gain(ui_module)
    profile_gain = _get_profile_camera_gain(ui_module)

    if current_gain is None:
        return ["profile"]

    if profile_gain is not None and abs(current_gain - profile_gain) < 0.05:
        return ["profile"]

    if current_gain.is_integer():
        return [int(current_gain)]
    return [current_gain]


def get_camera_profile_gain_display(ui_module: UIModule) -> str:
    """
    Return the profile gain suffix shown beside the Profile gain item.
    """
    profile_gain = _get_profile_camera_gain(ui_module)
    if profile_gain is None:
        return ""
    return f" ({_format_gain(profile_gain)})"


def set_gain(ui_module: UITextMenu) -> None:
    """
    Set runtime camera gain from the current Camera Gain menu item.
    """
    selected_item = ui_module._menu_items[ui_module._current_item_index]
    selected_item_definition = ui_module.get_item(selected_item)
    if selected_item_definition is None:
        logger.warning("Camera Gain menu item %s not found", selected_item)
        return
    new_gain = selected_item_definition["value"]

    if new_gain == "profile":
        logger.info("Set gain to camera profile default")
        ui_module._selected_values = ["profile"]
    else:
        logger.info("Set gain %s", new_gain)
        ui_module._selected_values = [new_gain]

    ui_module.command_queues["camera"].put(f"set_gain:{new_gain}")


def apply_brightness(ui_module: UIModule) -> None:
    """Re-apply display + keypad brightness from current config."""
    ui_module.command_queues["ui_queue"].put("set_brightness")


def reload_config(ui_module: UIModule) -> None:
    """Ask the main loop to reload config-backed runtime services."""
    # A settings-menu change is persistent and supersedes any runtime-only
    # type selected through keypad, keyboard, or Web Remote.
    ui_module.config_object.set_option("session.indi_goto_method", None)
    ui_module.command_queues["ui_queue"].put("reload_config")
    # A GoTo Type picked in Settings is persistent and must replace any
    # keypad/keyboard/Web-Remote session override immediately.
    goto_guide_queue = ui_module.command_queues.get("goto_guide")
    if goto_guide_queue is not None:
        goto_guide_queue.put({"type": "reload_config"})
    ui_module.message(_("Config updated"), 1)


def _send_imu_command(ui_module: UIModule, command_type: str, message: str) -> None:
    imu_queue = ui_module.command_queues.get("imu")
    if imu_queue is None:
        ui_module.message(_("IMU command\nunavailable"), 2)
        return
    imu_queue.put({"type": command_type})
    ui_module.message(message, 1)


def imu_save_calibration(ui_module: UIModule) -> None:
    _send_imu_command(ui_module, "save_calibration", _("IMU Cal Save"))


def imu_load_calibration(ui_module: UIModule) -> None:
    _send_imu_command(ui_module, "load_calibration", _("IMU Cal Load"))


def imu_clear_calibration(ui_module: UIModule) -> None:
    _send_imu_command(ui_module, "clear_calibration", _("IMU Cal Clear"))


def capture_exposure_sweep(ui_module: UIModule) -> None:
    """
    Captures 100 images at different exposures for PID testing/calibration.

    Uses logarithmic spacing from 25ms to 1s for fine-grained analysis.
    Images saved to: ~/PiFinder_data/captures/sweep_YYYYMMDD_HHMMSS/
    Takes approximately 20 seconds to complete.

    Shows real-time progress UI that monitors camera progress messages.
    """
    logger.info("Starting exposure sweep capture")

    # Import the sweep UI module
    from PiFinder.ui.sqm_sweep import UISQMSweep

    # Push the sweep progress UI onto the stack
    # It will handle starting the sweep and showing progress
    sweep_item = {
        "class": UISQMSweep,
        "label": "sqm_sweep_progress",
    }
    ui_module.add_to_stack(sweep_item)


def _camera_exposure_suffix(ui_module: UIModule, auto_value: str) -> str:
    """
    Returns formatted current camera exposure for display.
    Shows the live exposure beside the matching auto menu item
    ("auto" / "auto_star") while that controller is selected.
    """
    config_exp = ui_module.config_object.get_option("camera_exp")

    # For the selected auto mode, get actual exposure from metadata
    if config_exp == auto_value:
        try:
            metadata = ui_module.shared_state.last_image_metadata()
            if metadata and "exposure_time" in metadata:
                actual_exp = metadata["exposure_time"]
                exp_sec = actual_exp / 1_000_000
                if exp_sec < 0.1:
                    return f" ({int(exp_sec * 1000)}ms)"
                else:
                    return f" ({exp_sec:g}s)"
        except Exception:
            pass
        return ""

    # Format numeric exposure nicely for manual mode
    if auto_value == "auto" and isinstance(config_exp, (int, float)):
        exp_sec = config_exp / 1_000_000
        if exp_sec < 0.1:
            return f" ({int(exp_sec * 1000)}ms)"
        else:
            return f" ({exp_sec:g}s)"

    return ""


def get_camera_exposure_display(ui_module: UIModule) -> str:
    """Suffix for the "Auto" (match-count) Camera Exp menu item."""
    return _camera_exposure_suffix(ui_module, "auto")


def get_camera_exposure_star_display(ui_module: UIModule) -> str:
    """Suffix for the "Star" (star-count) Camera Exp menu item."""
    return _camera_exposure_suffix(ui_module, "auto_star")


def _device_operation(callback):
    """Keep the device menu usable when a privileged command is rejected."""

    @wraps(callback)
    def run(ui_module, *args, **kwargs):
        try:
            return callback(ui_module, *args, **kwargs)
        except (sh.ErrorReturnCode, OSError) as error:
            logger.error("Device operation failed: %s", type(error).__name__)
            ui_module.message(_("Operation failed"), 3)

    return run


@_device_operation
def shutdown(ui_module: UIModule) -> None:
    """
    shuts down the Pi
    """
    ui_module.message(_("Shutting Down"), 10)
    sys_utils.shutdown()


def restart_pifinder(ui_module: UIModule) -> None:
    """
    Uses systemctl to restart the PiFinder
    service
    """
    ui_module.message(_("Restarting..."), 2)
    if not sys_utils.restart_pifinder():
        ui_module.message(_("Restart failed"), 3)


def mount_control_toggle(ui_module: UIModule) -> None:
    """Restart MFNavis after changing the optional INDI mount-control process."""
    enabled = ui_module.config_object.get_option("mount_control", False)
    message = _("Mount Control\nOn") if enabled else _("Mount Control\nOff")
    ui_module.message(message, 1)
    restart_pifinder(ui_module)


def _send_mount_control(ui_module: UIModule, command: dict, message: str) -> None:
    """Queue an INDI mount-control command from a text menu item."""
    if not ui_module.config_object.get_option("mount_control", False):
        ui_module.message(_("Mount Control Off"), 1)
        return

    mount_queue = ui_module.command_queues.get("mountcontrol")
    if mount_queue is None:
        ui_module.message(_("Mount Control\nUnavailable"), 1)
        return

    mount_queue.put(command)
    ui_module.message(_(message), 1)


def indi_init(ui_module: UIModule) -> None:
    _send_mount_control(ui_module, {"type": "init"}, "INDI Init")


def indi_sync_location_time(ui_module: UIModule) -> None:
    _send_mount_control(
        ui_module,
        {"type": "sync_location_time"},
        "Time/Location",
    )


def reset_pointing(ui_module: UIModule) -> None:
    """Reinitialize the Pointing Coordinate Service.

    The service runs inside the SkySafari/pos_server process and shares no
    queue with the UI, so (mirroring the web INDI page) we drop a request file
    that its loop polls and then calls clear_state(). The fused coordinate
    re-baselines from the best available source: a valid plate solve, else the
    aligned mount, else the IMU fallback.
    """
    try:
        utils.create_path(utils.runtime_dir)
        request_file = utils.runtime_dir / "pointing_reset_request.json"
        payload = {"requested_at": time.time(), "source": "lcd"}
        tmp_path = request_file.with_name(f"{request_file.name}.{os.getpid()}.tmp")
        with open(tmp_path, "w", encoding="utf-8") as reset_out:
            json.dump(payload, reset_out)
            reset_out.flush()
        tmp_path.replace(request_file)
        ui_module.message(_("Pointing Reset"), 1)
    except OSError:
        logging.exception("Could not request pointing reset")
        ui_module.message(_("Reset Failed"), 1)


def indi_park(ui_module: UIModule) -> None:
    _send_mount_control(
        ui_module,
        {"type": "park_action", "action": "park"},
        "Park",
    )


def indi_unpark(ui_module: UIModule) -> None:
    _send_mount_control(
        ui_module,
        {"type": "park_action", "action": "unpark"},
        "Unpark",
    )


def indi_set_home(ui_module: UIModule) -> None:
    _send_mount_control(
        ui_module,
        {"type": "park_action", "action": "set_home"},
        "Set Home",
    )


def indi_return_home(ui_module: UIModule) -> None:
    _send_mount_control(
        ui_module,
        {"type": "park_action", "action": "return_home"},
        "Return Home",
    )


def indi_set_park(ui_module: UIModule) -> None:
    _send_mount_control(
        ui_module,
        {"type": "park_action", "action": "set_park"},
        "Set-Park",
    )


def indi_restart_driver(ui_module: UIModule) -> None:
    _send_mount_control(
        ui_module,
        {"type": "restart_driver"},
        "INDI Restart",
    )


@_device_operation
def restart_system(ui_module: UIModule) -> None:
    """
    Restarts the system
    """
    ui_module.message(_("Restarting..."), 2)
    sys_utils.restart_system()


def recover_wifi(ui_module: UIModule) -> None:
    """MF: reload the Wi-Fi driver to un-wedge a BT-coexistence firmware
    hang (STA/AP dead, service restarts useless). Blocks ~20-40s; any
    Wi-Fi SSH session will drop by design."""
    ui_module.message(_("WiFi recovering"), 40)
    if sys_utils.recover_wifi():
        ui_module.message(_("WiFi OK"), 2)
    else:
        ui_module.message(_("WiFi still down"), 3)


def _boot_camera_id() -> str:
    """The active camera dtoverlay id in the boot config (imx290 -> imx462)."""
    cam_id = "000"

    # read config.txt into a list
    with open(get_boot_config_path(), "r") as boot_in:
        boot_lines = list(boot_in)

    # Look for the line without a comment...
    for line in boot_lines:
        if line.startswith("dtoverlay=imx"):
            cam_id = line[10:16]
            # Older installs used the imx290 overlay for imx462 cameras.
            if cam_id == "imx290":
                cam_id = "imx462"

    return cam_id


@_device_operation
def _switch_camera(ui_module: UIModule, cam_type: str, variant: Optional[str]) -> None:
    """Apply a Camera Type selection: sensor overlay plus mono/colour variant.

    The boot config owns the sensor choice and changing it needs a reboot;
    the variant is config-only (the dtoverlay is never touched for it -- plan
    doc D1), so a variant-only change restarts just the PiFinder service.
    variant=None leaves the stored variant alone (imx477 ignores it).
    """
    config_object = ui_module.config_object
    variant_changed = (
        variant is not None
        and config_object.get_option("camera_variant", "mono") != variant
    )
    overlay_changed = _boot_camera_id() != cam_type
    if variant_changed:
        config_object.set_option("camera_variant", variant)
    if overlay_changed:
        ui_module.message(_("Switching cam"), 2)
        switch_cam = {
            "imx477": sys_utils.switch_cam_imx477,
            "imx296": sys_utils.switch_cam_imx296,
            "imx462": sys_utils.switch_cam_imx462,
        }[cam_type]
        switch_cam()
        restart_system(ui_module)
    elif variant_changed:
        restart_pifinder(ui_module)


def switch_cam_imx477(ui_module: UIModule) -> None:
    _switch_camera(ui_module, "imx477", None)


def switch_cam_imx296_mono(ui_module: UIModule) -> None:
    _switch_camera(ui_module, "imx296", "mono")


def switch_cam_imx296_color(ui_module: UIModule) -> None:
    _switch_camera(ui_module, "imx296", "color")


def switch_cam_imx462_mono(ui_module: UIModule) -> None:
    _switch_camera(ui_module, "imx462", "mono")


def switch_cam_imx462_color(ui_module: UIModule) -> None:
    _switch_camera(ui_module, "imx462", "color")


def get_camera_type(ui_module: UIModule) -> list[str]:
    cam_id = _boot_camera_id()

    # v3 sensors exist in mono and colour variants; the boot config only
    # knows the sensor, so compose the menu value with the configured variant.
    if cam_id in ("imx296", "imx462"):
        variant = ui_module.config_object.get_option("camera_variant", "mono")
        if variant not in ("mono", "color"):
            variant = "mono"
        return [f"{cam_id}_{variant}"]

    return [cam_id]


def set_camera_lens(ui_module: UIModule) -> None:
    """Select a named lens and clear any previous manual override."""
    lens_key = ui_module.config_object.get_option("camera_lens", "")
    if lens_key and lens_key not in LENSES:
        logger.warning("Ignoring unsupported configured lens %r", lens_key)
        lens_key = ""
    ui_module.config_object.set_option("camera_lens_focal_length_mm", None)
    ui_module.shared_state.set_camera_lens_focal_length_mm(None)
    ui_module.shared_state.set_camera_lens(lens_key)
    logger.info("Camera lens statement updated: %s", lens_key or "automatic")


def start_lens_measurement(ui_module: UIModule) -> None:
    """Open live progress; keep the previous optics until a fit is accepted."""
    command_queue = ui_module.command_queues.get("align_command")
    if command_queue is None:
        ui_module.message(_("Solver unavailable"), 3)
        return
    request_id = time.time_ns()
    ui_module.shared_state.set_lens_measurement_status(
        {
            "state": "requested",
            "request_id": request_id,
            "accepted_frames": 0,
            "required_frames": 5,
            "last_reason": "waiting_stars",
        }
    )
    command_queue.put(
        StartLensMeasurement(
            camera_type=str(ui_module.shared_state.camera_type() or ""),
            request_id=request_id,
        )
    )
    from PiFinder.ui.lens_measurement import UILensMeasurement

    ui_module.add_to_stack(
        {
            "name": _("Auto Lens"),
            "class": UILensMeasurement,
            "label": "lens_measurement_progress",
            "request_id": request_id,
        }
    )


def edit_manual_lens_focal_length(ui_module: UIModule) -> None:
    """Edit a manual lens without rounding away an automatic measurement."""

    current = ui_module.config_object.get_option("camera_lens_focal_length_mm")
    initial = "" if current is None else f"{float(current):.4f}".rstrip("0").rstrip(".")

    def _save(value: str) -> None:
        try:
            focal_length = normalise_manual_focal_length(value, measured=True)
        except ValueError as exc:
            ui_module.message(str(exc), 3)
            return
        ui_module.config_object.set_option("camera_lens_focal_length_mm", focal_length)
        ui_module.shared_state.set_camera_lens_focal_length_mm(focal_length)
        lens_key = "manual" if focal_length is not None else ""
        ui_module.config_object.set_option("camera_lens", lens_key)
        ui_module.shared_state.set_camera_lens(lens_key)
        message = (
            _("Manual lens cleared")
            if focal_length is None
            else _("Manual lens: {value:.1f} mm").format(value=focal_length)
        )
        ui_module.message(message, 2)

    ui_module.add_to_stack(
        {
            "name": _("Manual Lens (mm)"),
            "entry_title": _("Lens (mm)"),
            "class": UITextEntry,
            "mode": "text_entry",
            "initial_text": initial,
            "max_length": 7,
            "callback": _save,
        }
    )


def manual_lens_focal_length_suffix(ui_module: UIModule) -> str:
    """Show the active manual value beside the Lens-menu entry."""

    focal_length = ui_module.config_object.get_option("camera_lens_focal_length_mm")
    if focal_length is None:
        return ""
    try:
        return f"  {float(focal_length):.2f}"
    except (TypeError, ValueError):
        return ""


def _distortion_context(ui_module: UIModule):
    camera_type = str(ui_module.shared_state.camera_type() or "")
    lens_key = str(ui_module.config_object.get_option("camera_lens", "") or "")
    lens_key = calibration_lens_key(
        lens_key, ui_module.config_object.get_option("camera_lens_focal_length_mm")
    )
    if lens_key not in LENSES and not lens_key.startswith("manual-"):
        raise ValueError(_("Select a named lens first or measure Auto"))
    return camera_type, lens_key, get_camera_profile(camera_type)


def _active_distortion_profile(ui_module: UIModule):
    try:
        camera_type, lens_key, profile = _distortion_context(ui_module)
    except (KeyError, ValueError):
        return None
    return CalibrationProfileStore(ui_module.config_object).load_active(
        camera_type, lens_key, profile
    )


def distortion_status_suffix(ui_module: UIModule) -> str:
    """Compact live state beside Advanced > Distortion."""

    try:
        status = ui_module.shared_state.distortion_calibration_status() or {}
    except (AttributeError, BrokenPipeError, ConnectionResetError):
        status = {}
    if status.get("state") in {
        "requested",
        "waiting_stars",
        "measuring",
        "collecting",
    }:
        return "  {}/{}".format(
            int(status.get("accepted_frames") or 0),
            int(status.get("required_frames") or 5),
        )
    active = _active_distortion_profile(ui_module)
    if active is None:
        return "  None"
    return "  Sky" if active.get("source") == "auto_sky" else "  TV"


_DISTORTION_REASON_LABELS = {
    "requested": "Waiting for stars",
    "waiting_stars": "Waiting for stars",
    "not_enough_candidates": "Need more stars",
    "distortion_fit_failed": "No stable fit",
    "not_enough_field_coverage": "Need edge stars",
    "invalid_distortion": "Invalid fit",
    "unsafe_distortion": "Unsafe fit",
    "corrected_replay_failed": "Replay failed",
    "corrected_coordinate_mismatch": "Position mismatch",
    "no_rmse_improvement": "No improvement",
    "frame_moving": "Hold still",
    "waiting_full_frame": "Waiting for frame",
    "measuring_frame": "Solving frame",
}


def show_distortion_status(ui_module: UIModule) -> None:
    try:
        camera_type, lens_key, profile = _distortion_context(ui_module)
    except (KeyError, ValueError) as exc:
        ui_module.message(str(exc), 3)
        return
    status = ui_module.shared_state.distortion_calibration_status() or {}
    state = str(status.get("state") or "idle")
    if state in {"requested", "waiting_stars", "measuring", "collecting"}:
        accepted = int(status.get("accepted_frames") or 0)
        required = int(status.get("required_frames") or 5)
        reason_key = str(status.get("last_reason") or "waiting_stars")
        reason = _DISTORTION_REASON_LABELS.get(reason_key, reason_key)
        ui_module.message(f"Measuring {accepted}/{required}\n{reason}", 3)
        return
    active = CalibrationProfileStore(ui_module.config_object).load_active(
        camera_type, lens_key, profile
    )
    if active is None:
        ui_module.message(f"Not measured\n{lens_key}", 3)
        return
    coefficients = active.get("coefficients") or {}
    source = "Sky measured" if active.get("source") == "auto_sky" else "TV baseline"
    ui_module.message(f"{source}\nk1 {float(coefficients.get('k1', 0.0)):.4f}", 3)


def start_distortion_calibration(ui_module: UIModule) -> None:
    try:
        camera_type, lens_key, _camera_profile = _distortion_context(ui_module)
    except (KeyError, ValueError) as exc:
        ui_module.message(str(exc), 3)
        return
    command_queue = ui_module.command_queues.get("align_command")
    if command_queue is None:
        ui_module.message(_("Solver unavailable"), 3)
        return
    request_id = time.time_ns()
    command_queue.put(
        StartDistortionCalibration(
            camera_type=camera_type,
            lens_key=lens_key,
            request_id=request_id,
        )
    )
    ui_module.shared_state.set_distortion_calibration_status(
        {
            "state": "requested",
            "request_id": request_id,
            "camera_type": camera_type,
            "lens_key": lens_key,
            "accepted_frames": 0,
            "required_frames": 5,
            "last_reason": "requested",
        }
    )
    from PiFinder.ui.distortion_calibration import UIDistortionCalibration

    ui_module.add_to_stack(
        {
            "name": _("Measure Sky"),
            "class": UIDistortionCalibration,
            "label": "distortion_calibration_progress",
            "request_id": request_id,
        }
    )


def cancel_distortion_calibration(ui_module: UIModule) -> None:
    status = ui_module.shared_state.distortion_calibration_status() or {}
    request_id = status.get("request_id")
    command_queue = ui_module.command_queues.get("align_command")
    if command_queue is not None:
        command_queue.put(CancelDistortionCalibration(request_id=request_id))
    ui_module.shared_state.set_distortion_calibration_status(
        {"state": "cancelled", "accepted_frames": 0, "required_frames": 5}
    )
    ui_module.message(_("Measurement cancelled"), 2)


def reset_distortion_calibration(ui_module: UIModule) -> None:
    try:
        camera_type, lens_key, profile = _distortion_context(ui_module)
    except (KeyError, ValueError) as exc:
        ui_module.message(str(exc), 3)
        return
    ui_module.shared_state.set_distortion_calibration_status(
        {"state": "reset", "accepted_frames": 0, "required_frames": 5}
    )
    command_queue = ui_module.command_queues.get("align_command")
    if command_queue is not None:
        command_queue.put(CancelDistortionCalibration())
    removed = CalibrationProfileStore(ui_module.config_object).clear(
        camera_type, lens_key, profile
    )
    ui_module.message(
        _("Distortion reset") if removed else _("No calibration found"), 2
    )
    ui_module.remove_from_stack()


def switch_language(ui_module: UIModule) -> None:
    iso2_code = ui_module.config_object.get_option("language")
    msg = str(f"Language: {iso2_code}")
    ui_module.message(_(msg))
    lang = gettext.translation(
        "messages",
        str(utils.pifinder_dir / "python" / "locale"),
        languages=[iso2_code],
        fallback=(iso2_code == "en"),
    )
    lang.install()
    logger.info("Switch Language: %s", iso2_code)
    if iso2_code in ["ko", "zh"]:
        # CJK languages require a different font, so we have to restart.
        restart_pifinder(ui_module)


@_device_operation
def go_wifi_ap(ui_module: UIModule) -> None:
    ui_module.message(_("WiFi to AP"), 2)
    sys_utils.go_wifi_ap()
    restart_system(ui_module)


@_device_operation
def go_wifi_cli(ui_module: UIModule) -> None:
    ui_module.message(_("WiFi to Client"), 2)
    sys_utils.go_wifi_cli()
    restart_system(ui_module)


@_device_operation
def go_wifi_apsta(ui_module: UIModule) -> None:
    ui_module.message(_("WiFi to AP+STA"), 2)
    sys_utils.go_wifi_apsta()
    restart_system(ui_module)


def get_wifi_mode(ui_module: UIModule) -> list[str]:
    return [utils.read_wifi_mode()]


def set_location(ui_module: UIModule) -> None:
    """
    Sets location from the coordinate entry UI.
    Reads lat, lon, alt from item_definition (passed through the chain).
    """
    lat = ui_module.item_definition.get("lat", 0.0)
    lon = ui_module.item_definition.get("lon", 0.0)
    alt = ui_module.item_definition.get("alt", 0)
    logger.info(f"Setting location to: lat={lat}, lon={lon}, alt={alt}")

    ui_module.command_queues["gps"].put(Location.make_fix(lat, lon, alt, "MANUAL"))
    ui_module.message(
        _("{lat:.2f}, {lon:.2f}\n{alt}m alt").format(lat=lat, lon=lon, alt=alt),
        2,
    )


def gps_reset(ui_module: UIModule) -> None:
    ui_module.command_queues["gps"].put(("reset", {}))
    ui_module.message(_("Location Reset"), 2)


def datetime_reset(ui_module: UIModule) -> None:
    ui_module.command_queues["gps"].put(("reset_datetime", {}))
    ui_module.message(_("Time/Date Reset"), 2)


def save_location(ui_module: UIModule) -> None:
    """Save current location — prompts for name via text entry."""
    location = ui_module.shared_state.location()
    if not location.lock:
        ui_module.message(_("No location lock"), 2)
        return

    def _save(name):
        new_loc = SavedLocation(
            name=name,
            latitude=location.lat,
            longitude=location.lon,
            height=location.altitude,
            error_in_m=location.error_in_m,
            source=location.source,
        )
        ui_module.config_object.locations.add_location(new_loc)
        ui_module.config_object.save_locations()
        ui_module.message(_("Saved\n{name}").format(name=name), 2)

    num = len(ui_module.config_object.locations.locations) + 1
    item_definition = {
        "name": _("Location Name"),
        "class": UITextEntry,
        "mode": "text_entry",
        "initial_text": _("Loc {number}").format(number=num),
        "callback": _save,
    }
    ui_module.add_to_stack(item_definition)


def set_time(ui_module: UIModule, time_str: str) -> None:
    """
    Sets the time from the time entry UI
    """
    logger.info(f"Setting time to: {time_str}")

    # Location.timezone is Optional and pytz.timezone(None) raises, so fall
    # back rather than crash on commit. set_location already settles the zone
    # to UTC when it cannot resolve one; this covers a Location built directly.
    timezone_str = ui_module.shared_state.location().timezone or "UTC"

    # First create a datetime object (using today's date by default)
    dt = timez.parse(time_str, "%H:%M:%S")

    # Get the timezone object
    timezone = pytz.timezone(timezone_str)

    # Create a timezone-aware datetime by combining today's date with the time
    # and localizing it to the specified timezone
    # OS timezone may be different from target timezone so "now's date" needs
    # to also be taken in the target timezone!!
    now = datetime.now(timezone)
    dt_with_date = timez.naive(
        now.year, now.month, now.day, dt.hour, dt.minute, dt.second
    )
    dt_with_timezone = timezone.localize(dt_with_date)

    ui_module.command_queues["gps"].put(("time_force", {"time": dt_with_timezone}))
    ui_module.message(_("Time: {time}").format(time=time_str), 2)


def set_datetime(ui_module: UIModule, date_str: str) -> None:
    """
    Sets both date and time from the date entry UI.
    Reads the time_str from the item_definition (passed from UITimeEntry).
    """
    time_str = ui_module.item_definition.get("time_str", "00:00:00")
    logger.info(f"Setting datetime to: {date_str} {time_str}")

    # See set_time: fall back rather than raise on an unresolved zone.
    timezone_str = ui_module.shared_state.location().timezone or "UTC"
    timezone = pytz.timezone(timezone_str)

    dt = timez.parse(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
    dt_with_timezone = timezone.localize(dt)

    ui_module.command_queues["gps"].put(("time_force", {"time": dt_with_timezone}))
    ui_module.message(_("{date}\n{time}").format(date=date_str, time=time_str), 2)


def handle_radec_entry(ui_module: UIModule, ra_deg: float, dec_deg: float) -> None:
    """
    Handles RA/DEC coordinate entry from the coordinate input UI
    Creates a CompositeObject and adds it to recent list for navigation
    """
    from PiFinder.ui.object_details import UIObjectDetails

    logger.info(f"Received coordinates: RA={ra_deg:.6f}°, DEC={dec_deg:.6f}°")

    # Create a CompositeObject from the coordinates
    custom_object = create_custom_object_from_coords(ra_deg, dec_deg, ui_module)

    # Add to recent objects list for immediate navigation
    ui_module.shared_state.ui_state().add_recent(custom_object)

    # Show popup notification that user object was created
    ui_module.message(
        _("User object created\n{name}").format(name=custom_object.display_name),
        timeout=2,
    )

    # Navigate to object details for the created object
    object_item_definition = {
        "name": custom_object.display_name,
        "class": UIObjectDetails,
        "object": custom_object,
        "object_list": [custom_object],  # Single object list
        "label": "object_details",
    }
    ui_module.add_to_stack(object_item_definition)

    logger.info(
        f"Created custom object: {custom_object.display_name} at RA={ra_deg:.6f}°, DEC={dec_deg:.6f}°"
    )


def create_custom_object_from_coords(
    ra_deg: float, dec_deg: float, ui_module: UIModule
):
    """
    Create a CompositeObject from RA/DEC coordinates
    """
    # Generate unique sequence number for custom objects
    # Use negative numbers to distinguish from regular catalog objects
    current_time_ms = int(time.time() * 1000)
    unique_id = -(current_time_ms % 1000000)  # Negative ID for custom objects

    # Generate automatic name and get the sequence number from it
    custom_name = generate_custom_object_name(ui_module)
    sequence_num = int(custom_name.split(" ")[1])  # Extract number from "CUSTOM X"

    # Determine constellation
    constellation = calc_utils.sf_utils.radec_to_constellation(ra_deg, dec_deg)

    # Generate description with coordinates in all supported formats
    description = generate_coordinate_description(ra_deg, dec_deg)

    # Create the CompositeObject following the pattern from pos_server.py
    custom_object = CompositeObject.from_dict(
        {
            "id": -1,
            "object_id": unique_id,
            "obj_type": "Custom",
            "ra": ra_deg,
            "dec": dec_deg,
            "const": constellation,
            "size": SizeObject([]),
            "mag": MagnitudeObject([]),
            "mag_str": "",
            "catalog_code": "USER",
            "sequence": sequence_num,
            "description": description,
            "names": [custom_name],
            "image_name": "",
            "logged": False,
        }
    )

    return custom_object


def generate_coordinate_description(ra_deg: float, dec_deg: float) -> str:
    """
    Generate a description with coordinates in all supported formats
    """
    # Convert RA from degrees to hours for HMS format
    ra_hours = ra_deg / 15.0

    # Format 1: HMS/DMS (Full format)
    ra_h, ra_m, ra_s = calc_utils.ra_to_hms(ra_deg)
    dec_d, dec_m, dec_s = calc_utils.dec_to_dms(dec_deg)
    dec_sign = "+" if dec_deg >= 0 else "-"
    hms_dms = f"RA: {ra_h:02d}:{ra_m:02d}:{ra_s:02d} DEC: {dec_sign}{abs(dec_d):02d}:{dec_m:02d}:{dec_s:02d}"

    # Format 2: Mixed (Hours/Degrees)
    mixed = f"RA: {ra_hours:.4f}h DEC: {dec_deg:+.4f}°"

    # Format 3: Decimal degrees
    decimal = f"RA: {ra_deg:.4f}° DEC: {dec_deg:+.4f}°"

    return f"User-defined coordinates\n\nHMS/DMS:\n{hms_dms}\n\nMixed:\n{mixed}\n\nDecimal:\n{decimal}"


def generate_custom_object_name(ui_module: UIModule) -> str:
    """
    Generate a unique name for custom objects (CUSTOM 1, CUSTOM 2, etc.)
    """
    # Get current recent list to check for existing custom objects
    recent_list = ui_module.shared_state.ui_state().recent_list()

    # Find highest existing CUSTOM number
    max_num = 0
    for obj in recent_list:
        if hasattr(obj, "catalog_code") and obj.catalog_code == "USER":
            for name in obj.names:
                if name.startswith("CUSTOM "):
                    try:
                        num = int(name.split(" ")[1])
                        max_num = max(max_num, num)
                    except (IndexError, ValueError):
                        pass

    # Return next available number
    return f"CUSTOM {max_num + 1}"


def telemetry_record_toggle(ui_module: UIModule) -> None:
    """Toggle telemetry recording on/off via integrator command queue."""
    enabled = ui_module.config_object.get_option("telemetry_record")
    if "integrator" in ui_module.command_queues:
        if enabled:
            ui_module.command_queues["integrator"].put(("telemetry_record_on", None))
            ui_module.message("Telemetry\nRecording", 2)
        else:
            ui_module.command_queues["integrator"].put(("telemetry_record_off", None))
            ui_module.message("Telemetry\nStopped", 2)
    else:
        ui_module.message("No integrator\nqueue", 2)


def update_gpsd_baud_rate(ui_module: UIModule) -> None:
    """
    Updates the GPSD configuration with the current serial port and baud rate.
    Always updates GPSD config regardless of current GPS type.
    """
    baud_rate = ui_module.config_object.get_option("gps_baud_rate")
    gps_port = ui_module.config_object.get_option(
        "gps_port", sys_utils.DEFAULT_GPSD_DEVICE
    )

    ui_module.message(_("Checking GPS\nconfig..."), 2)
    logger.info("Checking GPSD port %s baud rate %s", gps_port, baud_rate)

    try:
        if sys_utils.check_and_sync_gpsd_config(baud_rate, gps_port):
            ui_module.message(_("GPS config\nupdated"), 2)
        else:
            ui_module.message(_("GPS config\nOK"), 2)
    except Exception as e:
        logger.error(f"Failed to update GPSD config: {e}")
        ui_module.message(_("GPS config\nfailed"), 3)
