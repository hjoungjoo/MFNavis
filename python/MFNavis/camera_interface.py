#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the camera
* Captures images
* Places preview images in queue
* Places solver images in queue
* Takes full res images on demand

"""

from typing import Tuple, Optional
from PIL import Image
import json
import os
import random
import time
import numpy as np
import queue
import threading
import logging

from pathlib import Path

from PiFinder import camera_stage_dump, timez, utils
from PiFinder.observation import observation_snapshot
import PiFinder.pointing_model.quaternion_transforms as qt
from PiFinder.auto_exposure import (
    ExposurePIDController,
    ExposureSNRController,
    generate_exposure_sweep,
)
from PiFinder.auto_exposure_starcount import (
    ExposureStarCountController,
    full_frame_star_count,
)
from PiFinder.livecam_config import SOURCE_SOLVER_INPUT, settings_from_config

logger = logging.getLogger("Camera.Interface")

# Daytime alignment uses the camera's native (driver) auto-exposure where it is
# available. On backends with no native AE (debug / non-Pi), `set_exp:native`
# falls back to this fixed short exposure -- short enough not to saturate in
# daylight while still usable for framing a distant object.
DAYTIME_AE_FALLBACK_EXPOSURE = 1000  # microseconds
FULL_FRAME_AUTO_STAR_TARGET = 10

# Driver metadata keys copied into each sweep frame's per-image JSON: the
# exposure/gain actually applied plus every thermal and black-level signal
# the sensor reports. Missing keys are recorded as null so files stay
# comparable across camera types.
SWEEP_FRAME_METADATA_KEYS = (
    "ExposureTime",
    "AnalogueGain",
    "DigitalGain",
    "SensorTemperature",
    "SensorBlackLevels",
    "ColourGains",
    "Lux",
    "FrameDuration",
)


def _json_safe(value):
    """Coerce picamera2 metadata values (numpy scalars, tuples) to JSON types."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def sweep_frame_record(index, exp_us, driver_metadata, cropped_frame, bit_depth):
    """Build one sweep image's metadata record: the camera settings actually
    applied (from driver metadata) plus ADU statistics of the raw frame
    (pre-bias-subtraction).

    The statistics cover the square crop, while the TIFF alongside holds the
    whole sensor. Keeping them on the crop is what makes the black-level
    series comparable with sweeps taken before the archive went full-sensor."""
    camera_metadata = {
        key: _json_safe(driver_metadata.get(key)) if driver_metadata else None
        for key in SWEEP_FRAME_METADATA_KEYS
    }
    record = {
        "index": index,
        "requested_exposure_us": exp_us,
        "exp_ms": exp_us / 1000,
        "sensor_temp_c": camera_metadata["SensorTemperature"],
        "captured_at": timez.local_now().isoformat(),
        "camera_metadata": camera_metadata,
        # Entire driver dict, uncurated: sensors differ in which keys they
        # report (and under what names/types); archived sweeps must not be
        # limited to today's whitelist when characterizing a new camera.
        "camera_metadata_full": (
            _json_safe(driver_metadata) if driver_metadata else None
        ),
    }
    if cropped_frame is not None:
        frame = cropped_frame.astype(np.float64)
        p = np.percentile(frame, [1, 5, 25, 50, 75, 95, 99])
        record["raw_stats"] = {
            # Which pixels these numbers cover. The sibling TIFF is
            # full-sensor, so without this the two would silently be
            # assumed to describe the same pixels. Sweeps from before the
            # archive went full-sensor have no such key; there the TIFF
            # was the crop too, so it meant the same thing either way.
            "extent": "crop",
            "mean_adu": float(frame.mean()),
            "median_adu": float(p[3]),
            "std_adu": float(frame.std()),
            "min_adu": float(frame.min()),
            "max_adu": float(frame.max()),
            "percentiles_adu": {
                "p01": float(p[0]),
                "p05": float(p[1]),
                "p25": float(p[2]),
                "p75": float(p[4]),
                "p95": float(p[5]),
                "p99": float(p[6]),
            },
        }
        if bit_depth:
            record["raw_stats"]["saturated_fraction"] = float(
                np.mean(cropped_frame >= 2**bit_depth - 1)
            )
    return record


class CameraInterface:
    """The CameraInterface interface."""

    exposure_time: float
    _focus_exposure_saved: Optional[dict] = None
    _focus_exposure_token: Optional[str] = None

    _camera_started = False
    _save_next_to = None  # Filename to save next capture to (None = don't save)
    _auto_exposure_enabled = False
    _auto_exposure_mode = "pid"  # "pid" or "snr"
    # Which controller drives the default (non-SQM) branch:
    # "match_count" (ExposurePIDController, camera_exp "auto") or
    # "star_count" (ExposureStarCountController, camera_exp "auto_star").
    # Set by the Camera Exp menu via `set_exp:`. The SQM screen's
    # background controller ("snr" mode above) takes precedence while active.
    _ae_controller_choice = "match_count"
    _auto_exposure_pid: Optional[ExposurePIDController] = None
    _auto_exposure_snr: Optional[ExposureSNRController] = None
    _auto_exposure_star: Optional[ExposureStarCountController] = None
    _last_solve_time: Optional[float] = None
    # Native (camera-driver) auto-exposure, distinct from the solver-driven
    # auto-exposure above. Enabled for daytime alignment via `set_exp:native`.
    _native_ae_enabled = False
    # Runtime-only gain selection.  The sensor-reported AnalogueGain is
    # quantized (for example a requested 30x is reported as about 29.51x), so
    # the web UI cannot reconstruct whether the user selected Profile or a
    # numeric value from actual metadata alone.
    _gain_mode = "profile"  # "profile" or "manual"
    # Handle to an in-flight capture thread (see _capture_with_timeout). A
    # wedged V4L2 capture can outlive its timeout; tracking it lets the next
    # frame decline to start a second, concurrent capture on a camera that is
    # not thread-safe.
    _capture_thread: Optional[threading.Thread] = None
    # One-shot pipeline stage dump (save_stages command). _stage_dump_dir arms
    # the backend's capture() to write stages 0-4 (Pi camera only); it then
    # hands the dir over via _stage_dump_pending for the loop below to add the
    # final rotated solver-input stage and the stats file.
    _stage_dump_dir: Optional[str] = None
    _stage_dump_pending: Optional[str] = None
    _stage_dump_stats: Optional[list] = None
    # Automatic corpus collection: when solve attempts keep failing, arm a
    # stage dump on a cooldown so a night of failures leaves 16-bit frames
    # to bench detectors against offline (config: camera_auto_dump).
    _auto_dump_enabled = False
    _auto_dump_last_attempt: Optional[float] = None
    _auto_dump_fail_streak = 0
    _auto_dump_last_time = 0.0
    AUTO_DUMP_FAIL_STREAK = 10
    AUTO_DUMP_COOLDOWN_S = 180.0

    def set_native_ae(self, enabled: bool) -> bool:
        """Enable/disable the camera's native (driver) auto-exposure.

        Returns True if the backend actually supports native AE; False otherwise
        (the caller then falls back to a fixed short exposure). The base
        implementation has no native AE.
        """
        return False

    def get_default_gain(self) -> float:
        """Return the backend's default startup gain."""
        profile = getattr(self, "profile", None)
        if profile is not None and hasattr(profile, "analog_gain"):
            return float(profile.analog_gain)
        return float(getattr(self, "gain", 1.0))

    def framewise_auto_star_active(self) -> bool:
        """Whether the hardware backend's Auto(Star) v2 owns controls."""
        return False

    def reset_framewise_auto_star(self, *, gain_locked: bool = False) -> None:
        """Reset backend framewise state after a control-ownership change."""

    def update_framewise_auto_star_quality(self, quality) -> None:
        """Feed solver quality to a backend framewise controller, if any."""

    def initialize(self) -> None:
        pass

    def _release_focus_exposure(self) -> None:
        """Restore camera-owned runtime state without reselecting Auto Star.

        Reselecting that regime resets gain to the profile and unlocks manual
        gain. A Focus visit must preserve both the selected controller and
        runtime-only gain, even when the UI's saved config is stale.
        """
        saved = getattr(self, "_focus_exposure_saved", None)
        if saved is None:
            return
        self.set_camera_config(saved["exposure_time"], saved["gain"])
        if saved["_native_ae_enabled"]:
            self.set_native_ae(True)
        for name, value in saved.items():
            setattr(self, name, value)
        self.reset_framewise_auto_star(gain_locked=(self._gain_mode == "manual"))
        self._focus_exposure_saved = None
        self._focus_exposure_token = None

    def _handle_focus_exposure_command(self, command: str) -> bool:
        """Handle token-scoped Focus holds; explicit camera controls take over.

        All changes run in the camera process at the existing command boundary.
        Config and the solver-driven controller instances are never rewritten.
        """
        if not command.startswith(("focus_begin:", "focus_set:", "focus_end:")):
            if (
                command.startswith(("set_exp", "set_gain", "set_ae_mode"))
                or command in ("exp_up", "exp_dn", "exp_save", "stop")
                or command.startswith("capture_exp_sweep")
            ):
                self._release_focus_exposure()
            return False

        kind, token, *values = command.split(":")
        current = getattr(self, "_focus_exposure_token", None)
        if kind == "focus_end":
            if current == token:
                self._release_focus_exposure()
            return True
        if kind == "focus_set" and current != token:
            return True  # A delayed nudge must not reclaim another control.
        exposure = int(values[0])
        if exposure <= 0:
            raise ValueError("Focus exposure must be positive")
        if kind == "focus_begin":
            if current == token:
                return True
            self._release_focus_exposure()
            self._focus_exposure_saved = {
                name: getattr(self, name)
                for name in (
                    "exposure_time",
                    "gain",
                    "_gain_mode",
                    "_auto_exposure_enabled",
                    "_native_ae_enabled",
                    "_ae_controller_choice",
                    "_auto_exposure_mode",
                )
            }
            self._focus_exposure_token = token
        self._auto_exposure_enabled = False
        self._native_ae_enabled = False
        try:
            self.set_camera_config(exposure, self.gain)
            self.exposure_time = exposure
        except Exception:
            self._release_focus_exposure()
            raise
        return True

    def capture(self) -> Image.Image:
        return Image.Image()

    def capture_file(self, filename) -> None:
        pass

    def capture_raw_file(self, filename) -> None:
        pass

    def _settle_exposure(self, requested_us, max_frames=8, tolerance=0.02):
        """Discard frames until the sensor actually delivers `requested_us`.

        A fixed flush count cannot be right for every sensor: the IMX290/462
        serves exactly three frames at the old exposure after a change, while
        the IMX477 emits half-exposure transitional frames instead. Flushing
        two frames -- as this did -- left the next capture still on the old
        exposure, so a sweep's processed PNG was one step behind the raw TIFF
        beside it, and the radiometer sample attached to the record described
        the PNG. Watch the driver's reported ExposureTime instead.

        Returns the number of frames discarded.
        """
        for n in range(max_frames):
            self.capture()
            meta = getattr(self, "last_frame_metadata", None) or {}
            actual = meta.get("ExposureTime")
            if actual is None:
                # Backend reports no exposure metadata (debug/none cameras);
                # nothing to settle against, so don't burn frames on it.
                return n + 1
            if abs(float(actual) - requested_us) <= tolerance * requested_us:
                return n + 1
        logger.warning(
            "Exposure did not settle at %sµs after %d frames; "
            "the frame may not match its label",
            requested_us,
            max_frames,
        )
        return max_frames

    def _blank_capture(self):
        """
        Returns a properly formated black frame
        """
        return Image.new("L", (512, 512), 0)  # Black 512x512 image

    def _capture_with_timeout(self, timeout=10) -> Optional[Image.Image]:
        """Run capture() with a timeout, never overlapping two captures.

        A V4L2 capture can hang indefinitely (e.g. the sensor wedges), which
        would otherwise freeze the whole camera process. Run the capture on a
        daemon thread and give up after ``timeout`` seconds, returning None so
        the caller can recover instead of blocking forever.

        A timed-out capture cannot be cancelled (picamera2/V4L2 exposes no such
        API), so the daemon thread stays stuck inside the driver until it
        eventually returns. To avoid piling concurrent capture_request() calls
        onto a camera that is not thread-safe -- and racing on shared camera
        state -- we keep a handle to the in-flight thread and refuse to launch a
        second capture while it is still alive. At most one capture is ever
        running; the caller just gets blank frames until the stuck one clears.
        """
        # A previous capture is still wedged in the driver -- don't start a
        # second one. Returning None lets the caller fall back to a blank frame
        # while we wait for the stuck capture to clear.
        if self._capture_thread is not None and self._capture_thread.is_alive():
            return None

        result: list = [None]
        exc: list = [None]

        def _do_capture():
            try:
                result[0] = self.capture()
            except Exception as e:  # propagate to the caller's thread
                exc[0] = e

        thread = threading.Thread(target=_do_capture, daemon=True)
        self._capture_thread = thread
        thread.start()
        thread.join(timeout)

        if thread.is_alive():
            # Still running: leave it tracked so the next call sees it and
            # declines to start an overlapping capture.
            return None

        # Finished within the timeout -- clear the handle so the next frame
        # starts a fresh capture.
        self._capture_thread = None
        if exc[0]:
            raise exc[0]
        return result[0]

    def _arm_stage_dump(self, shared_state) -> str:
        """Arm a one-shot pipeline stage dump of the next frame; returns the
        target directory. GPS time for the name when available, Pi time
        otherwise (same fallback as the exposure sweep)."""
        gps_time = shared_state.datetime()
        timestamp = (
            gps_time.strftime("%Y%m%d_%H%M%S")
            if gps_time
            else timez.local_now().strftime("%Y%m%d_%H%M%S")
        )
        self._stage_dump_dir = str(
            Path(utils.runtime_capture_dir) / f"stages_{timestamp}"
        )
        return self._stage_dump_dir

    def _auto_dump_check(self, shared_state, console_queue) -> None:
        """Track per-attempt solve outcomes; arm a stage dump after a failure
        streak, on a cooldown. Config-gated (camera_auto_dump)."""
        solution = shared_state.solution()
        if solution is None or not solution.last_solve_attempt:
            return
        attempt = solution.last_solve_attempt
        if attempt == self._auto_dump_last_attempt:
            return
        self._auto_dump_last_attempt = attempt
        if solution.last_solve_success == attempt:
            self._auto_dump_fail_streak = 0
            return
        self._auto_dump_fail_streak += 1
        if (
            self._auto_dump_fail_streak >= self.AUTO_DUMP_FAIL_STREAK
            and time.time() - self._auto_dump_last_time > self.AUTO_DUMP_COOLDOWN_S
            and self._stage_dump_dir is None
            and self._stage_dump_pending is None
        ):
            self._auto_dump_last_time = time.time()
            self._auto_dump_fail_streak = 0
            dump_dir = self._arm_stage_dump(shared_state)
            console_queue.put("CAM: Auto stage dump")
            logger.info(
                "Auto stage dump armed after solve-failure streak: %s", dump_dir
            )

    def capture_bias(self):
        """
        Capture a bias frame for pedestal calculation.
        Base implementation returns a black frame (no bias correction).
        Override in subclasses that support bias frames.
        Returns Image.Image or np.ndarray depending on implementation.
        """
        return self._blank_capture()

    def set_camera_config(
        self, exposure_time: float, gain: float
    ) -> Tuple[float, float]:
        return (0, 0)

    def get_cam_type(self) -> str:
        return "foo"

    def start_camera(self) -> None:
        pass

    def stop_camera(self) -> None:
        pass

    def get_image_loop(
        self, shared_state, camera_image, command_queue, console_queue, cfg
    ):
        try:
            # Store shared_state for access by capture() methods
            self.shared_state = shared_state
            if hasattr(shared_state, "set_livecam_settings"):
                shared_state.set_livecam_settings(settings_from_config(cfg))

            # MFDS and preprocessing require the native RAW for every frame,
            # independently of historical Cedar and comparison flags.
            self._publish_solver_raw = True
            if self._publish_solver_raw:
                logger.info(
                    "Publishing full-frame solver_raw (full-frame solver path enabled)"
                )
            self._auto_dump_enabled = bool(cfg.get_option("camera_auto_dump"))
            if self._auto_dump_enabled:
                logger.info("Automatic stage dumps on solve-failure streaks")

            # Store camera type in shared state for SQM calibration
            camera_type_str = self.get_cam_type()  # e.g., "PI imx296", "PI hq"
            if " " in camera_type_str:
                # Extract just the sensor type (imx296, hq, imx462, etc.)
                camera_type = camera_type_str.split(" ")[1].lower()
                shared_state.set_camera_type(camera_type)
                logger.info(f"Camera type set to: {camera_type}")

            test_mode_on = False

            # Check if auto-exposure was previously enabled in config.
            # "auto" selects the match-count controller, "auto_star" the
            # star-count controller (both Camera Exp menu items).
            config_exp = cfg.get_option("camera_exp")
            if config_exp in ("auto", "auto_star"):
                self._auto_exposure_enabled = True
                # SQM temporarily replaces the solver-driven controller with
                # its background SNR loop. A saved Auto mode must always boot
                # into its own controller even if a prior UI path failed to
                # send SQM's matching exit command.
                self._auto_exposure_mode = "pid"
                self._ae_controller_choice = (
                    "star_count" if config_exp == "auto_star" else "match_count"
                )
                self._last_solve_time = None
                if self._auto_exposure_pid is None:
                    self._auto_exposure_pid = ExposurePIDController()
                else:
                    self._auto_exposure_pid.reset()
                logger.info(f"Auto-exposure mode enabled from config ({config_exp})")

            screen_direction = cfg.get_option("screen_direction")
            camera_rotation = cfg.get_option("camera_rotation")

            # Publish the display rotation applied to the solve image (PIL
            # CCW degrees, relative to the stored raw frame) so SQM can map
            # solve-image centroids back onto the raw for photometry. Must
            # stay in lockstep with solver_frame_map.stage5_rotation_deg,
            # which mirrors this rule for the SEP full-frame path
            # (test_stage5_rotation_matches_camera_interface_rules pins it).
            if camera_rotation is not None:
                solve_rotation = (-int(camera_rotation)) % 360
            elif screen_direction in ["right", "straight", "flat3", "as_bloom"]:
                solve_rotation = 90
            else:
                solve_rotation = 270
            shared_state.set_solve_image_rotation(solve_rotation)

            # Set path for test mode image
            root_dir = os.path.realpath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            test_image_path = os.path.join(
                root_dir, "test_images", "pifinder_debug_02.png"
            )

            was_sleeping = False
            while True:
                sleeping = shared_state.power_state() <= 0
                if sleeping and not was_sleeping:
                    # Display/UI sleep must not stop the sensor stream.  The
                    # next exposure continues while this frame is processed;
                    # processing overload is handled by latest-wins drops.
                    logger.info(
                        "Display sleep active; camera capture remains continuous"
                    )
                    was_sleeping = True
                elif not sleeping and was_sleeping:
                    logger.info("Display sleep ended; camera remained active")
                    was_sleeping = False

                imu_start = shared_state.imu()
                image_start_time = time.time()
                if self._camera_started:
                    capture_succeeded = True
                    if not test_mode_on:
                        base_image = self._capture_with_timeout()
                        if base_image is None:
                            # Capture hung; fall back to a blank frame so the
                            # loop keeps running and stays responsive to
                            # commands instead of freezing. The blank frame
                            # simply fails to solve.
                            logger.warning("Camera capture timed out; blank frame")
                            base_image = self._blank_capture()
                            capture_succeeded = False
                        base_image = base_image.convert("L")

                        base_image = base_image.rotate(solve_rotation)
                    else:
                        # Test Mode: load image from disc and wait
                        # No real raw matrix backs this frame; prevent a recent
                        # hardware radiometer sample from being paired with it.
                        shared_state.set_sqm_radiometer_sample(None)
                        base_image = Image.open(test_image_path)
                        base_image = base_image.convert(
                            "L"
                        )  # Convert to grayscale to match camera output
                        time.sleep(0.2)
                    image_end_time = time.time()
                    # check imu to make sure we're still static
                    imu_end = shared_state.imu()

                    # see if we moved during exposure
                    if (
                        imu_start
                        and imu_end
                        and imu_start.is_usable(now=image_start_time)
                        and imu_end.is_usable(now=image_end_time)
                    ):
                        # Returns the pointing difference between successive IMU quaternions as
                        # an angle (radians). Note that this also accounts for rotation around the
                        # scope axis. Returns an angle in radians.
                        pointing_diff = qt.get_quat_angular_diff(
                            imu_start.quat, imu_end.quat
                        )
                    else:
                        pointing_diff = 0.0

                    # Make image available.  The solver gets an atomic image +
                    # metadata envelope below; camera_image remains the legacy
                    # latest preview surface used by the UI.
                    if test_mode_on and abs(pointing_diff) > 0.01:
                        # Scope moved during the fake exposure: return a blank
                        # image so the solver doesn't report a stale solve
                        solver_image = self._blank_capture()
                    else:
                        solver_image = base_image

                    if capture_succeeded and not test_mode_on:
                        frame_id = getattr(self, "last_frame_id", None)
                        driver_metadata = (
                            getattr(self, "last_frame_metadata", None) or {}
                        )
                        pipeline = dict(
                            getattr(self, "last_capture_diagnostics", None) or {}
                        )
                    else:
                        # A timeout/test image has no matching sensor request.
                        # Give it a unique synthetic id so no previous full RAW
                        # can be paired with this 512 frame.
                        frame_id = -time.monotonic_ns()
                        driver_metadata = {}
                        pipeline = {}

                    image_metadata = {
                        "frame_id": frame_id,
                        "exposure_start": image_start_time,
                        "exposure_end": image_end_time,
                        "imu": imu_end,
                        "imu_delta": np.rad2deg(pointing_diff),
                        "exposure_time": self.exposure_time,
                        "actual_exposure_us": driver_metadata.get("ExposureTime"),
                        "gain": self.gain,
                        "gain_mode": self._gain_mode,
                        "actual_gain": driver_metadata.get("AnalogueGain"),
                        "sensor_timestamp_ns": driver_metadata.get("SensorTimestamp"),
                        "frame_duration_us": driver_metadata.get("FrameDuration"),
                        "sensor_temp_c": getattr(self, "last_sensor_temp", None),
                        "capture_pipeline": pipeline,
                        "auto_star_control": dict(
                            getattr(self, "last_auto_star_control", None) or {}
                        ),
                    }
                    publish_solver_frame = getattr(
                        shared_state, "set_solver_frame", None
                    )
                    if callable(publish_solver_frame):
                        publish_solver_frame(
                            {
                                "frame_id": frame_id,
                                "image": np.asarray(solver_image, dtype=np.uint8),
                                "metadata": image_metadata,
                            }
                        )
                    camera_image.paste(solver_image)
                    shared_state.set_last_image_metadata(image_metadata)

                    # LiveCam "Input Frame" solver_input stage: what the
                    # solver actually reads exists only here, after rotation,
                    # so this stage is published by the loop and not by
                    # capture() (which publishes every other source).
                    if hasattr(shared_state, "livecam_settings"):
                        livecam_settings = shared_state.livecam_settings()
                        if (
                            livecam_settings
                            and livecam_settings.get("input_frame_source")
                            == SOURCE_SOLVER_INPUT
                        ):
                            try:
                                from PiFinder.raw_live_stack import (
                                    publish_selected_frame,
                                )

                                publish_selected_frame(
                                    shared_state,
                                    livecam_settings,
                                    getattr(self, "profile", None),
                                    self.get_cam_type(),
                                    None,
                                    None,
                                    {
                                        "ExposureTime": self.exposure_time,
                                        "AnalogueGain": self.gain,
                                    },
                                    stage_frames={
                                        SOURCE_SOLVER_INPUT: np.asarray(base_image)
                                    },
                                )
                            except Exception:
                                logger.exception("LiveCam solver_input publish failed")

                    # Automatic corpus collection: arm a stage dump after a
                    # solve-failure streak (config: camera_auto_dump).
                    if self._auto_dump_enabled:
                        try:
                            self._auto_dump_check(shared_state, console_queue)
                        except Exception:
                            logger.exception("Auto stage dump check failed")

                    # Final stage of a pending pipeline dump: base_image after
                    # rotation is exactly what the solver reads.
                    if self._stage_dump_pending:
                        try:
                            dump_dir = Path(self._stage_dump_pending)
                            stats = self._stage_dump_stats or []
                            stats.append(
                                camera_stage_dump.save_stage(
                                    dump_dir,
                                    len(stats),
                                    "solver_input",
                                    np.asarray(base_image),
                                )
                            )
                            camera_stage_dump.finalize(
                                dump_dir,
                                stats,
                                {
                                    "observation": observation_snapshot(shared_state),
                                    "camera": self.get_cam_type(),
                                    "exposure_us": self.exposure_time,
                                    "gain": self.gain,
                                },
                            )
                            camera_stage_dump.prune_dumps(
                                Path(utils.runtime_capture_dir)
                            )
                            console_queue.put("CAM: Stages saved")
                        except Exception:
                            logger.exception("Stage dump finalize failed")
                        finally:
                            self._stage_dump_pending = None
                            self._stage_dump_stats = None

                    # Auto-exposure: adjust based on plate solve results
                    # Updates as fast as new solve results arrive (naturally rate-limited)
                    if self._auto_exposure_enabled and self._auto_exposure_pid:
                        solution = shared_state.solution()
                        solve_source = solution.solve_source if solution else None

                        # Any solution with solve attempts feeds the controller.
                        # This must include "IMU": once a solve has succeeded
                        # and the IMU progresses the estimate, failed camera
                        # attempts leave solve_source at IMU -- gating on
                        # CAM/CAM_FAILED alone froze auto-exposure exactly when
                        # the frames stopped solving (observed: saturated sky,
                        # exposure stuck). The per-attempt gate below is the
                        # real rate limiter.
                        if solve_source in ("CAM", "CAM_FAILED", "IMU"):
                            matched_stars = solution.diagnostics.Matches
                            solve_attempt_time = solution.last_solve_attempt
                            solve_rmse = solution.diagnostics.RMSE

                            # Only update on NEW solve results (not re-processing same solution)
                            # Use last_solve_attempt since it's set for both success and failure
                            if (
                                solve_attempt_time
                                and solve_attempt_time != self._last_solve_time
                            ):
                                rmse_str = (
                                    f"{solve_rmse:.1f}"
                                    if solve_rmse is not None
                                    else "N/A"
                                )
                                logger.debug(
                                    f"Auto-exposure feedback - Stars: {matched_stars}, "
                                    f"RMSE: {rmse_str}, Current exposure: {self.exposure_time}µs"
                                )

                                # Call auto-exposure update based on current mode
                                feedback_stars = matched_stars
                                if self._auto_exposure_mode == "snr":
                                    # SNR mode: use background-based controller (for SQM measurements)
                                    if self._auto_exposure_snr is None:
                                        # Default 8-bit thresholds; the
                                        # controller measures the processed
                                        # display image.
                                        self._auto_exposure_snr = (
                                            ExposureSNRController()
                                        )
                                    # The controller sees the processed 8-bit
                                    # image, so this must remain in 8-bit ADU.
                                    processed_noise_floor = (
                                        self.shared_state.noise_floor()
                                    )
                                    new_exposure = self._auto_exposure_snr.update(
                                        self.exposure_time,
                                        base_image,
                                        noise_floor=processed_noise_floor,
                                    )
                                elif self._ae_controller_choice == "star_count":
                                    # Star-count controller: conservative
                                    # full-frame detector consensus, not
                                    # catalog matches (central crop is only a
                                    # fallback). See auto_star research doc.
                                    if self.framewise_auto_star_active():
                                        quality = getattr(
                                            solution.diagnostics,
                                            "ExposureQuality",
                                            None,
                                        )
                                        if quality is None:
                                            quality = {
                                                "frame_id": getattr(
                                                    solution.diagnostics,
                                                    "FrameId",
                                                    None,
                                                ),
                                                "source": (
                                                    "peripheral_full"
                                                    if "full"
                                                    in solution.diagnostics.solve_path
                                                    else "center"
                                                ),
                                                "region_ids": (
                                                    ("U", "L", "R", "D")
                                                    if "full"
                                                    in solution.diagnostics.solve_path
                                                    else ("C",)
                                                ),
                                                "matched_stars": matched_stars,
                                                "candidate_stars": full_frame_star_count(
                                                    solution.diagnostics.Centroids,
                                                    solution.diagnostics.CedarGatedCentroids,
                                                    solution.diagnostics.CedarRawCentroids,
                                                    solution.diagnostics.SepCentroids,
                                                ),
                                                "snr_p25": None,
                                                "snr_median": None,
                                                "rmse": solve_rmse,
                                                "solve_success": (
                                                    solution.last_solve_success
                                                    == solve_attempt_time
                                                ),
                                            }
                                        if quality.get("frame_id") is not None:
                                            self.update_framewise_auto_star_quality(
                                                quality
                                            )
                                        new_exposure = None
                                        feedback_stars = quality.get(
                                            "candidate_stars", matched_stars
                                        )
                                    elif self._auto_exposure_star is None:
                                        self._auto_exposure_star = (
                                            ExposureStarCountController(
                                                target_stars=(
                                                    FULL_FRAME_AUTO_STAR_TARGET
                                                    if self._publish_solver_raw
                                                    else 20
                                                )
                                            )
                                        )
                                    if not self.framewise_auto_star_active():
                                        arr = np.asarray(base_image)
                                        h, w = arr.shape[0], arr.shape[1]
                                        center_mean = float(
                                            arr[
                                                h // 4 : h - h // 4,
                                                w // 4 : w - w // 4,
                                            ].mean()
                                        )
                                        # Per-attempt success: on success the
                                        # solver stamps last_solve_success with
                                        # the attempt time. solve_source cannot
                                        # tell this (IMU masks it, see gate above).
                                        feedback_stars = full_frame_star_count(
                                            solution.diagnostics.Centroids,
                                            solution.diagnostics.CedarGatedCentroids,
                                            solution.diagnostics.CedarRawCentroids,
                                            solution.diagnostics.SepCentroids,
                                        )
                                        new_exposure = self._auto_exposure_star.update(
                                            feedback_stars,
                                            self.exposure_time,
                                            center_mean=center_mean,
                                            solve_success=(
                                                solution.last_solve_success
                                                == solve_attempt_time
                                            ),
                                        )
                                else:
                                    # Match-count controller (default)
                                    new_exposure = self._auto_exposure_pid.update(
                                        matched_stars, self.exposure_time
                                    )

                                if (
                                    new_exposure is not None
                                    and new_exposure != self.exposure_time
                                ):
                                    # Exposure value actually changed - update camera
                                    logger.info(
                                        f"Auto-exposure adjustment: {feedback_stars} stars → "
                                        f"{self.exposure_time}µs → {new_exposure}µs "
                                        f"(change: {new_exposure - self.exposure_time:+d}µs)"
                                    )
                                    self.exposure_time = new_exposure
                                    self.set_camera_config(
                                        self.exposure_time, self.gain
                                    )
                                elif new_exposure is None:
                                    logger.debug(
                                        f"Auto-exposure: {matched_stars} stars, no adjustment needed"
                                    )
                                self._last_solve_time = solve_attempt_time

                # Loop over any pending commands
                # There may be more than one!
                command = True
                while command:
                    try:
                        # Short block: this get() sits in the per-frame loop, so
                        # its timeout is a fixed tax on the frame period (0.1
                        # cost ~8% of the achievable rate at short exposures).
                        # Commands queued mid-frame are picked up next pass.
                        command = command_queue.get(block=True, timeout=0.01)
                    except queue.Empty:
                        command = ""
                        continue
                    except Exception as e:
                        logger.error(f"CameraInterface: Command error: {e}")

                    try:
                        if self._handle_focus_exposure_command(command):
                            continue
                        if command == "debug":
                            test_mode_on = not test_mode_on

                        if command.startswith("set_exp"):
                            transient_exposure = command.startswith(
                                "set_exp_transient:"
                            )
                            exp_value = command.split(":")[1]
                            if exp_value in ("auto", "auto_star"):
                                # Enable auto-exposure mode. "auto" runs the
                                # match-count controller, "auto_star" the
                                # star-count controller.
                                self._auto_exposure_enabled = True
                                self._native_ae_enabled = False
                                # Selecting either solver-driven mode must end
                                # SQM's temporary background-SNR override.
                                self._auto_exposure_mode = "pid"
                                self._last_solve_time = None  # Reset solve tracking
                                self._ae_controller_choice = (
                                    "star_count"
                                    if exp_value == "auto_star"
                                    else "match_count"
                                )
                                if self._auto_exposure_pid is None:
                                    self._auto_exposure_pid = ExposurePIDController()
                                else:
                                    self._auto_exposure_pid.reset()
                                if self._auto_exposure_star is not None:
                                    self._auto_exposure_star.reset()
                                if exp_value == "auto_star":
                                    # Re-selecting Auto(Star) explicitly
                                    # unlocks automatic gain and begins at the
                                    # sensor profile's high-gain default.
                                    self.gain = self.get_default_gain()
                                    self._gain_mode = "profile"
                                    self.set_camera_config(
                                        self.exposure_time, self.gain
                                    )
                                    self.reset_framewise_auto_star(gain_locked=False)
                                else:
                                    self.reset_framewise_auto_star()
                                # Record the mode the same way a manual exposure
                                # is recorded below: the Camera Exp menu and the
                                # web LiveCam page both read camera_exp back to
                                # show what is in effect, and the loop above
                                # restores it on the next start.
                                cfg.set_option("camera_exp", exp_value)
                                if exp_value == "auto_star":
                                    console_queue.put("CAM: Auto-Exp (Star)")
                                else:
                                    console_queue.put("CAM: Auto-Exposure Enabled")
                                logger.info(f"Auto-exposure mode enabled ({exp_value})")
                            elif exp_value == "native":
                                # Native (driver) auto-exposure for daytime align.
                                # Disable the solver-driven AE so it doesn't fight
                                # the driver; leave the saved camera_exp config
                                # untouched so the prior mode can be restored.
                                self._auto_exposure_enabled = False
                                self._last_solve_time = None
                                self.reset_framewise_auto_star()
                                if self.set_native_ae(True):
                                    self._native_ae_enabled = True
                                    console_queue.put("CAM: Native AE")
                                    logger.info("Native auto-exposure enabled")
                                else:
                                    # No native AE on this backend (debug / non-Pi):
                                    # fall back to a fixed short daylight exposure.
                                    self._native_ae_enabled = False
                                    self.exposure_time = DAYTIME_AE_FALLBACK_EXPOSURE
                                    self.set_camera_config(
                                        self.exposure_time, self.gain
                                    )
                                    console_queue.put("CAM: Day exposure")
                                    logger.info(
                                        "Native AE unsupported; fixed exposure "
                                        f"{self.exposure_time}µs"
                                    )
                            else:
                                # Disable auto-exposure and set manual exposure.
                                # set_camera_config also clears native AE on Pi.
                                self._auto_exposure_enabled = False
                                self._native_ae_enabled = False
                                self.reset_framewise_auto_star()
                                self.exposure_time = int(exp_value)
                                self.set_camera_config(self.exposure_time, self.gain)
                                # Calibration uses transient manual exposures;
                                # never persist those over the user's saved
                                # auto/manual choice.
                                if not transient_exposure:
                                    cfg.set_option("camera_exp", self.exposure_time)
                                console_queue.put("CAM: Exp=" + str(self.exposure_time))
                                logger.info(
                                    f"Manual exposure set: {self.exposure_time}µs"
                                )

                        if command.startswith("set_gain"):
                            # Gain is deliberately runtime-only: unlike the
                            # exposure above it is not written to config, so a
                            # restart goes back to the camera profile default.
                            # Only the Exp Save menu item (`exp_save` below)
                            # commits a gain. Both the Camera Gain menu and the
                            # web LiveCam page read the applied gain back from
                            # the frame metadata, not from config.
                            old_gain = getattr(self, "gain", self.get_default_gain())
                            gain_value = command.split(":", 1)[1]
                            if gain_value == "profile":
                                self.gain = self.get_default_gain()
                                gain_mode = "profile"
                            else:
                                self.gain = float(gain_value)
                                gain_mode = "manual"
                            self.exposure_time, self.gain = self.set_camera_config(
                                self.exposure_time, self.gain
                            )
                            # Only publish the selection after the camera
                            # accepted the corresponding control update.
                            self._gain_mode = gain_mode
                            if (
                                self._auto_exposure_enabled
                                and self._ae_controller_choice == "star_count"
                            ):
                                # Numeric gain is an explicit lock. Profile
                                # remains the automatic ladder's high-gain
                                # start and therefore stays unlocked.
                                self.reset_framewise_auto_star(
                                    gain_locked=(gain_mode == "manual")
                                )
                            gain_text = f"{self.gain:g}"
                            console_queue.put("CAM: Gain=" + gain_text)
                            logger.info(f"Gain changed: {old_gain:g}x → {gain_text}x")

                        if command.startswith("set_ae_mode"):
                            mode = command.split(":")[1]
                            if mode in ["pid", "snr"]:
                                self._auto_exposure_mode = mode
                                self.reset_framewise_auto_star(
                                    gain_locked=(self._gain_mode == "manual")
                                )
                                console_queue.put(f"CAM: AE Mode={mode.upper()}")
                                logger.info(
                                    f"Auto-exposure mode changed to: {mode.upper()}"
                                )
                            else:
                                logger.warning(
                                    f"Unknown auto-exposure mode: {mode} (valid: pid, snr)"
                                )

                        if command == "exp_up" or command == "exp_dn":
                            # Manual exposure adjustments disable auto-exposure
                            # (both solver-driven and native; set_camera_config
                            # also clears native AeEnable on Pi).
                            self._auto_exposure_enabled = False
                            self._native_ae_enabled = False
                            self.reset_framewise_auto_star()
                            if command == "exp_up":
                                self.exposure_time = int(self.exposure_time * 1.25)
                            else:
                                self.exposure_time = int(self.exposure_time * 0.75)
                            self.set_camera_config(self.exposure_time, self.gain)
                            console_queue.put("CAM: Exp=" + str(self.exposure_time))
                        if command == "exp_save":
                            # Saving exposure disables auto-exposure and locks to current value
                            self._auto_exposure_enabled = False
                            self.reset_framewise_auto_star()
                            cfg.set_option("camera_exp", self.exposure_time)
                            cfg.set_option("camera_gain", int(self.gain))
                            console_queue.put(
                                f"CAM: Exp Saved ({self.exposure_time}µs)"
                            )
                            logger.info(
                                f"Exposure saved and auto-exposure disabled: {self.exposure_time}µs"
                            )

                        if command == "save_stages":
                            # Arm a one-shot dump of every pipeline stage of
                            # the next frame (camera_stage_dump).
                            dump_dir = self._arm_stage_dump(shared_state)
                            console_queue.put("CAM: Stage dump armed")
                            logger.info("Stage dump armed: %s", dump_dir)

                        if command.startswith("save_image:"):
                            # Save current camera frame to specified path
                            save_path = command.split(":", 1)[1]
                            try:
                                img = camera_image.copy()
                                img.save(save_path, "PNG", compress_level=6)
                                Path(save_path).with_suffix(
                                    ".observation.json"
                                ).write_text(
                                    json.dumps(observation_snapshot(shared_state))
                                )
                                logger.debug("Telemetry image saved: %s", save_path)
                            except Exception as e:
                                logger.error("Failed to save telemetry image: %s", e)

                        if command.startswith("save:"):
                            # Set flag to save next capture to this file
                            self._save_next_to = command.split(":", 1)[1]
                            console_queue.put("CAM: Save flag set")

                        if (
                            command.startswith("capture")
                            and command != "capture_exp_sweep"
                        ):
                            # Capture one identified frame. Calibration waits on
                            # this timestamp, preventing it from analysing the
                            # preceding continuously captured frame.
                            capture_imu_start = shared_state.imu()
                            capture_start = time.time()
                            captured_image = self.capture().convert("L")
                            captured_image = captured_image.rotate(solve_rotation)
                            captured_raw = None
                            if self._save_next_to:
                                captured_raw = shared_state.cam_raw()
                                if captured_raw is not None:
                                    captured_raw = captured_raw.copy()
                            camera_image.paste(captured_image)
                            capture_end = time.time()
                            capture_imu_end = shared_state.imu()
                            if (
                                capture_imu_start
                                and capture_imu_end
                                and capture_imu_start.is_usable(now=capture_start)
                                and capture_imu_end.is_usable(now=capture_end)
                            ):
                                capture_pointing_diff = qt.get_quat_angular_diff(
                                    capture_imu_start.quat,
                                    capture_imu_end.quat,
                                )
                            else:
                                capture_pointing_diff = 0.0
                            shared_state.set_last_image_metadata(
                                {
                                    "exposure_start": capture_start,
                                    "exposure_end": capture_end,
                                    "imu": capture_imu_end,
                                    "imu_delta": np.rad2deg(capture_pointing_diff),
                                    "exposure_time": self.exposure_time,
                                    "actual_exposure_us": (
                                        getattr(self, "last_frame_metadata", None) or {}
                                    ).get("ExposureTime"),
                                    "gain": self.gain,
                                    "gain_mode": self._gain_mode,
                                    "actual_gain": (
                                        getattr(self, "last_frame_metadata", None) or {}
                                    ).get("AnalogueGain"),
                                    "sensor_temp_c": getattr(
                                        self, "last_sensor_temp", None
                                    ),
                                }
                            )

                            # If save flag is set, save to disk
                            if self._save_next_to:
                                requested_path = Path(self._save_next_to)
                                if not requested_path.is_absolute():
                                    requested_path = (
                                        Path(utils.data_dir)
                                        / "captures"
                                        / requested_path
                                    )
                                filename = requested_path.with_suffix(".png")
                                filename.parent.mkdir(parents=True, exist_ok=True)

                                # Save the identified capture itself. Calling
                                # capture_file()/capture_raw_file() here would
                                # acquire different frames and break pairing.
                                captured_image.save(filename)
                                if captured_raw is not None:
                                    Image.fromarray(captured_raw).save(
                                        filename.with_suffix(".tiff")
                                    )

                                filename.with_suffix(".observation.json").write_text(
                                    json.dumps(
                                        {
                                            "exposure_start_unix_s": capture_start,
                                            "exposure_end_unix_s": capture_end,
                                            "observation": observation_snapshot(
                                                shared_state
                                            ),
                                        }
                                    )
                                )
                                console_queue.put("CAM: Captured + Saved")
                                self._save_next_to = None  # Clear flag
                            else:
                                console_queue.put("CAM: Captured")

                        if command.startswith("capture_exp_sweep"):
                            # Capture exposure sweep - save both RAW and processed images
                            # at different exposures for SQM testing
                            # RAW: 16-bit TIFF to preserve full sensor bit depth
                            # Processed: 8-bit PNG from normal camera.capture() pipeline

                            # Parse reference SQM if provided
                            reference_sqm = None
                            if ":" in command:
                                try:
                                    reference_sqm = float(command.split(":")[1])
                                    logger.info(f"Reference SQM: {reference_sqm:.2f}")
                                except (ValueError, IndexError):
                                    logger.warning("Invalid reference SQM in command")

                            logger.info(
                                "Starting exposure sweep capture (20 image pairs)"
                            )
                            console_queue.put("CAM: Starting sweep...")

                            # Save current settings
                            original_exposure = self.exposure_time
                            original_gain = self.gain
                            original_ae_enabled = self._auto_exposure_enabled

                            # Disable auto-exposure during sweep
                            self._auto_exposure_enabled = False

                            # Generate 20 exposure values with logarithmic spacing
                            # from 25ms (25000µs) to 1s (1000000µs)
                            min_exp = 25000  # 25ms
                            max_exp = 1000000  # 1s
                            num_images = 20

                            # Generate logarithmic sweep using shared utility
                            sweep_exposures = generate_exposure_sweep(
                                min_exp, max_exp, num_images
                            )
                            # Capture in random order: a monotonic ramp lets any
                            # temporal sky drift (twilight, passing haze) alias
                            # into an apparent exposure dependence in analysis.
                            # Each file name carries its exposure, so order is
                            # irrelevant downstream.
                            random.shuffle(sweep_exposures)

                            # Generate timestamp for this sweep session using GPS time
                            gps_time = shared_state.datetime()
                            if gps_time:
                                timestamp = gps_time.strftime("%Y%m%d_%H%M%S")
                            else:
                                # Fallback to Pi time if GPS not available
                                timestamp = timez.local_now().strftime("%Y%m%d_%H%M%S")
                                logger.warning(
                                    "GPS time not available, using Pi system time for sweep directory name"
                                )

                            # Create sweep directory
                            sweep_dir = Path(
                                f"{utils.data_dir}/captures/sweep_{timestamp}"
                            )
                            sweep_dir.mkdir(parents=True, exist_ok=True)

                            logger.info(f"Saving sweep to: {sweep_dir}")
                            console_queue.put("CAM: Starting sweep...")

                            sweep_frames: list = []
                            for i, exp_us in enumerate(sweep_exposures, 1):
                                # Update progress at start of each capture
                                console_queue.put(f"CAM: Sweep {i}/{num_images}")

                                # Set exposure
                                self.exposure_time = exp_us
                                self.set_camera_config(self.exposure_time, self.gain)

                                # Flush camera buffer - discard pre-buffered frames with old exposure
                                # Picamera2 maintains a frame queue, need to flush frames captured
                                # before the new exposure setting was applied
                                logger.debug(f"Settling camera at {exp_us}µs exposure")
                                settled = self._settle_exposure(exp_us)

                                # Now capture both processed and RAW images with correct exposure
                                exp_ms = exp_us / 1000

                                # Save processed 8-bit PNG (same as production capture() method)
                                processed_filename = (
                                    sweep_dir
                                    / f"img_{i:03d}_{exp_ms:.2f}ms_processed.png"
                                )
                                processed_img = (
                                    self.capture()
                                )  # Returns 8-bit PIL Image
                                processed_img.save(str(processed_filename))

                                # Save RAW TIFF (16-bit, from
                                # camera.capture_raw_file()), always the full
                                # sensor. The "rawfull" name keeps these out of
                                # readers globbing the cropped era's
                                # "*_raw_RGGB.tiff", so an un-updated tool finds
                                # nothing rather than silently scaling centroids
                                # against the wrong frame size.
                                raw_filename = (
                                    sweep_dir
                                    / f"img_{i:03d}_{exp_ms:.2f}ms_rawfull.tiff"
                                )
                                self.capture_raw_file(str(raw_filename))

                                # Per-image metadata JSON alongside each
                                # PNG/TIFF pair: applied exposure/gain, sensor
                                # die temperature and black levels, and raw
                                # ADU statistics, so a sweep resolves the
                                # pedestal-vs-temperature relation frame by
                                # frame.
                                frame_record = sweep_frame_record(
                                    i,
                                    exp_us,
                                    getattr(self, "last_frame_driver_metadata", None),
                                    getattr(self, "last_cropped_frame", None),
                                    getattr(
                                        getattr(self, "profile", None),
                                        "bit_depth",
                                        None,
                                    ),
                                )
                                # Live SQM pipeline state at this frame:
                                # sqm_details carries the full rolling-window
                                # dumps (black level, wings, clouds,
                                # radiometer) published by the solver. The
                                # solver starves during a sweep, so that
                                # snapshot freezes — the camera-side radiometer
                                # sample below does NOT: it is recomputed on
                                # every capture and gives live per-frame
                                # background/MAD/gradient through the sweep.
                                frame_record["observation"] = observation_snapshot(
                                    shared_state
                                )
                                frame_record["settle_frames"] = settled
                                try:
                                    frame_record["sqm_details"] = _json_safe(
                                        shared_state.sqm_details()
                                    )
                                    # The freeze is expected, but only the
                                    # source said so -- an analyst reading the
                                    # archive saw one value repeated across
                                    # every frame with nothing marking it as a
                                    # single pre-sweep snapshot. Say so in the
                                    # data.
                                    frame_record["sqm_details_frozen"] = True
                                except Exception:
                                    frame_record["sqm_details"] = None
                                    frame_record["sqm_details_frozen"] = None
                                try:
                                    frame_record["radiometer_sample"] = _json_safe(
                                        shared_state.sqm_radiometer_sample()
                                    )
                                except Exception:
                                    frame_record["radiometer_sample"] = None

                                sweep_frames.append(frame_record)
                                frame_meta_filename = (
                                    sweep_dir
                                    / f"img_{i:03d}_{exp_ms:.2f}ms_metadata.json"
                                )
                                try:
                                    with open(frame_meta_filename, "w") as f:
                                        json.dump(frame_record, f, indent=2)
                                except OSError:
                                    logger.exception(
                                        "Failed to save per-image sweep metadata"
                                    )

                                logger.debug(
                                    f"Captured sweep images {i}/{num_images}: {exp_ms:.2f}ms (PNG+TIFF)"
                                )

                            # Restore original settings
                            self.exposure_time = original_exposure
                            self.gain = original_gain
                            self._auto_exposure_enabled = original_ae_enabled
                            self.set_camera_config(self.exposure_time, self.gain)

                            try:
                                with open(sweep_dir / "frame_metadata.json", "w") as f:
                                    json.dump({"frames": sweep_frames}, f, indent=2)
                            except OSError:
                                logger.exception("Failed to save sweep frame metadata")

                            # Save sweep metadata (GPS time, location, altitude)
                            logger.info("Starting sweep metadata save...")
                            try:
                                from PiFinder.sqm.save_sweep_metadata import (
                                    save_sweep_metadata,
                                )

                                # Get GPS datetime (not Pi time)
                                gps_datetime = shared_state.datetime()
                                logger.debug(f"GPS datetime: {gps_datetime}")

                                # Get observer location
                                location = shared_state.location()
                                logger.debug(
                                    f"Location: lat={location.lat}, lon={location.lon}, alt={location.altitude}"
                                )

                                # Get current solve with RA/Dec/Alt/Az
                                solve_state = shared_state.solution()
                                ra_deg = None
                                dec_deg = None
                                altitude_deg = None
                                azimuth_deg = None

                                if (
                                    solve_state is not None
                                    and solve_state.has_pointing()
                                ):
                                    aligned = solve_state.pointing.aligned.estimate
                                    ra_deg = aligned.RA
                                    dec_deg = aligned.Dec
                                    altitude_deg = solve_state.Alt
                                    azimuth_deg = solve_state.Az
                                    logger.debug(
                                        f"Solve: RA={ra_deg}, Dec={dec_deg}, Alt={altitude_deg}, Az={azimuth_deg}"
                                    )

                                # Save metadata
                                logger.info(
                                    f"Calling save_sweep_metadata for {sweep_dir}"
                                )
                                save_sweep_metadata(
                                    sweep_dir=sweep_dir,
                                    observer_lat=location.lat,
                                    observer_lon=location.lon,
                                    observer_altitude_m=location.altitude,
                                    gps_datetime=gps_datetime.isoformat()
                                    if gps_datetime
                                    else None,
                                    reference_sqm=reference_sqm,
                                    ra_deg=ra_deg,
                                    dec_deg=dec_deg,
                                    altitude_deg=altitude_deg,
                                    azimuth_deg=azimuth_deg,
                                    camera_type=shared_state.camera_type(),
                                    lens_key=shared_state.camera_lens(),
                                    notes=f"Exposure sweep: {num_images} images, {min_exp / 1000:.1f}-{max_exp / 1000:.1f}ms",
                                )
                                logger.info(
                                    f"Successfully saved sweep metadata to {sweep_dir}/sweep_metadata.json"
                                )
                            except Exception as e:
                                logger.error(
                                    f"Failed to save sweep metadata: {e}", exc_info=True
                                )

                            console_queue.put("CAM: Sweep done!")
                            logger.info(
                                f"Exposure sweep completed: {num_images} image pairs in {sweep_dir}"
                            )

                        if command.startswith("stop"):
                            self.stop_camera()
                            console_queue.put("CAM: Stopped camera")
                        if command.startswith("start"):
                            self.start_camera()
                            console_queue.put("CAM: Started camera")
                    except ValueError as e:
                        logger.error(
                            f"Error processing camera command '{command}': {str(e)}"
                        )
                        console_queue.put(
                            f"CAM ERROR: Invalid command format - {str(e)}"
                        )
                    except AttributeError as e:
                        logger.error(
                            f"Camera component not initialized for command '{command}': {str(e)}"
                        )
                        console_queue.put("CAM ERROR: Camera not properly initialized")
                    except Exception as e:
                        logger.error(
                            f"Unexpected error processing camera command '{command}': {str(e)}"
                        )
                        console_queue.put(f"CAM ERROR: {str(e)}")
            logger.info(
                f"CameraInterface: Camera loop exited with command: '{command}'"
            )
        except (BrokenPipeError, EOFError, FileNotFoundError):
            logger.exception("Error in Camera Loop")
