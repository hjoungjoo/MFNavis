#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the camera
* Captures images
* Places preview images in queue
* Places solver images in queue
* Takes full res images on demand

"""

from PIL import Image
from PiFinder import config
from PiFinder.camera_interface import CameraInterface
from PiFinder.auto_exposure_framewise import (
    AutoStarFrameController,
    ExposureGainAllocator,
    SolveExposureQuality,
    collect_spatial_frame_sample,
)
from PiFinder.camera_controls import MAX_EXPOSURE_US, MIN_EXPOSURE_US
from PiFinder.sqm import apply_variant, detect_camera_type, get_camera_profile
from PiFinder.sqm.radiometer import collect_radiometer_sample
from typing import Any, Optional, Tuple
import logging
import re
import time
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.livecam_config import (
    SOURCE_BIAS_SUBTRACTED,
    SOURCE_DIGITAL_GAIN,
    SOURCE_ORIGINAL,
    SOURCE_RESIZED_512,
    SOURCE_SOLVER_INPUT,
    SOURCE_STAR_ONLY,
    SOURCE_STRETCHED_8BIT,
    normalize_settings,
    processing_enabled,
)
import numpy as np

logger = logging.getLogger("Camera.Pi")

CONTINUOUS_BUFFER_COUNT = 3


def raw_downshift(delivered_format: str, profile_bit_depth: int) -> int:
    """Bits to right-shift delivered raw samples into profile-depth units.

    Pi 5 / CM5 (PiSP frontend) delivers raw only as 16-bit samples with the
    sensor's bits MSB-aligned: a SRGGB12 request comes back as SRGGB16 with
    values x16. Pi 4's Unicam returns true profile-depth values (shift 0).
    An unparseable format is treated as profile-depth -- passing values
    through unscaled is the conservative choice.
    """
    match = re.search(r"\d+", str(delivered_format))
    delivered_depth = int(match.group()) if match else profile_bit_depth
    return max(0, delivered_depth - profile_bit_depth)


def estimate_sensor_drops(
    previous_timestamp_ns, current_timestamp_ns, frame_duration_us
) -> int:
    """Estimate skipped sensor frames between two delivered frames.

    Picamera2 deliberately recycles completed requests when ``queue=False``
    and no capture job is waiting.  Those drops are the desired overload
    policy, but they must be observable.  The sensor timestamps and reported
    frame duration let us estimate how many frame intervals were skipped.
    Invalid or changing metadata is treated conservatively as no measured
    drop rather than inventing a large count.
    """
    try:
        previous_ns = int(previous_timestamp_ns)
        current_ns = int(current_timestamp_ns)
        duration_ns = float(frame_duration_us) * 1000.0
    except (TypeError, ValueError):
        return 0
    if previous_ns <= 0 or current_ns <= previous_ns or duration_ns <= 0:
        return 0
    intervals = max(1, int(round((current_ns - previous_ns) / duration_ns)))
    return max(0, intervals - 1)


class CameraPI(CameraInterface):
    """The camera class for PI cameras.  Implements the CameraInterface interface."""

    def __init__(self, exposure_time, cfg=None) -> None:
        from picamera2 import Picamera2

        self.camera = Picamera2()
        self.exposure_time = exposure_time

        # Detect camera type and load complete profile (hardware config + noise
        # characteristics). The mono/colour variant cannot be detected -- it is
        # declared in config ("camera_variant") and folded into the profile
        # name here, so camType carries it to every consumer process.
        detected_type = detect_camera_type(self.camera.camera.id)
        variant = cfg.get_option("camera_variant", "mono") if cfg else "mono"
        self.camera_type = apply_variant(detected_type, variant)
        self.profile = get_camera_profile(self.camera_type)
        logger.info(
            f"Loaded profile for {self.camera_type}: "
            f"{self.profile.format}, {self.profile.raw_size}, "
            f"gain={self.profile.analog_gain:.0f}, dgain={self.profile.digital_gain:.1f}, "
            f"{self.profile.bit_depth}bit, offset={self.profile.bias_offset:.1f} ADU"
        )

        # Initialize runtime gain from profile (can be changed via commands)
        self.gain = self.profile.analog_gain
        self._auto_star_framewise_enabled = bool(
            cfg and cfg.get_option("camera_auto_star_framewise")
        )
        self._auto_star_controller: Optional[AutoStarFrameController] = None
        self.last_auto_star_control: dict[str, object] = {}
        self._radiometer_sequence = 0
        self._capture_sequence = 0
        self._last_sensor_timestamp_ns: Optional[int] = None
        self._estimated_sensor_drops = 0
        self.last_frame_id: Optional[int] = None
        self.last_capture_diagnostics: dict[str, object] = {}

        self.camType = f"PI {self.camera_type}"
        self.initialize()

    def initialize(self) -> None:
        """Initializes the camera and set the needed control parameters"""
        self.stop_camera()
        cam_config = self.camera.create_still_configuration(
            {"size": (512, 512)},
            raw={"size": self.profile.raw_size, "format": self.profile.format},
            buffer_count=CONTINUOUS_BUFFER_COUNT,
            queue=False,
        )
        self.camera.configure(cam_config)

        # Downshift PiSP's MSB-aligned 16-bit raw (see raw_downshift) in
        # _raw_array() so every consumer keeps working in the profile's
        # bit-depth units (bias offsets, the 8-bit stretch, saturation
        # checks, SQM calibration).
        delivered_format = str(self.camera.camera_configuration()["raw"]["format"])
        self._raw_shift = raw_downshift(delivered_format, self.profile.bit_depth)
        if self._raw_shift:
            logger.info(
                f"Raw delivered as {delivered_format}; downshifting by "
                f"{self._raw_shift} bits to {self.profile.bit_depth}-bit units"
            )

        self._default_controls()
        self._configure_framewise_controller()
        self.start_camera()

    def _driver_control_range(self, name, fallback):
        """Return a numeric (minimum, maximum) from Picamera2 control info."""
        try:
            info = self.camera.camera_controls.get(name)
            if info is not None and len(info) >= 2:
                return float(info[0]), float(info[1])
        except (AttributeError, TypeError, ValueError):
            pass
        return fallback

    def _configure_framewise_controller(self) -> None:
        exposure_min, exposure_max = self._driver_control_range(
            "ExposureTime", (MIN_EXPOSURE_US, MAX_EXPOSURE_US)
        )
        gain_min, gain_max = self._driver_control_range(
            "AnalogueGain",
            (1.0, float(getattr(self.profile, "analog_gain", self.gain))),
        )
        allocator = ExposureGainAllocator(
            min_exposure_us=max(MIN_EXPOSURE_US, int(exposure_min)),
            max_exposure_us=min(MAX_EXPOSURE_US, int(exposure_max)),
            max_gain=min(
                float(getattr(self.profile, "analog_gain", self.gain)), gain_max
            ),
            min_gain=max(1.0, gain_min),
        )
        self._auto_star_controller = AutoStarFrameController(allocator)
        logger.info(
            "Auto(Star) framewise %s (exposure=%d..%dus, gain=%s)",
            (
                "enabled"
                if getattr(self, "_auto_star_framewise_enabled", False)
                else "shadow-disabled"
            ),
            allocator.min_exposure_us,
            allocator.max_exposure_us,
            allocator.gain_ladder,
        )

    def framewise_auto_star_active(self) -> bool:
        return bool(
            self._auto_star_framewise_enabled
            and self._auto_star_controller is not None
            and self._auto_exposure_enabled
            and self._ae_controller_choice == "star_count"
            and self._auto_exposure_mode != "snr"
            and not self._native_ae_enabled
        )

    def reset_framewise_auto_star(self, *, gain_locked: bool = False) -> None:
        if self._auto_star_controller is not None:
            self._auto_star_controller.reset(gain_locked=gain_locked)
        self.last_auto_star_control = (
            self._auto_star_controller.status()
            if self._auto_star_controller is not None
            else {}
        )

    def update_framewise_auto_star_quality(self, quality) -> None:
        if self._auto_star_controller is None or not isinstance(quality, dict):
            return
        try:
            self._auto_star_controller.update_quality(
                SolveExposureQuality(
                    frame_id=int(quality["frame_id"]),
                    source=str(quality.get("source") or "center"),
                    region_ids=tuple(quality.get("region_ids") or ()),
                    matched_stars=int(quality.get("matched_stars") or 0),
                    candidate_stars=int(quality.get("candidate_stars") or 0),
                    snr_p25=quality.get("snr_p25"),
                    snr_median=quality.get("snr_median"),
                    rmse=quality.get("rmse"),
                    solve_success=bool(quality.get("solve_success")),
                    center_contaminated=bool(quality.get("center_contaminated", False)),
                )
            )
            self.last_auto_star_control = self._auto_star_controller.status()
        except (KeyError, TypeError, ValueError):
            logger.exception("Invalid Auto(Star) solver quality payload")

    def _process_framewise_auto_star(self, raw_capture, metadata) -> None:
        controller = self._auto_star_controller
        if controller is None:
            return
        if not self.framewise_auto_star_active():
            self.last_auto_star_control = controller.status()
            return
        try:
            actual_exposure = float(metadata.get("ExposureTime", self.exposure_time))
            actual_gain = float(metadata.get("AnalogueGain", self.gain))
            sample = collect_spatial_frame_sample(
                raw_capture,
                frame_id=int(
                    self.last_frame_id
                    if self.last_frame_id is not None
                    else self._capture_sequence
                ),
                frame_sequence=self._capture_sequence,
                actual_exposure_us=actual_exposure,
                actual_gain=actual_gain,
                bit_depth=self.profile.bit_depth,
                pedestal_adu=self.profile.bias_offset,
                captured_at=time.time(),
            )
            if sample is None:
                return
            target = controller.on_frame(sample)
            if target is not None:
                self.exposure_time, self.gain = self.set_camera_config(
                    target.exposure_us, target.gain
                )
                controller.mark_submitted(target, self._capture_sequence)
                logger.info(
                    "Auto(Star) framewise: %sus/%sx -> %dus/%gx (%s)",
                    int(actual_exposure),
                    f"{actual_gain:g}",
                    target.exposure_us,
                    target.gain,
                    target.reason,
                )
            self.last_auto_star_control = controller.status()
        except Exception:
            # A diagnostic/controller bug must not interrupt continuous capture.
            logger.exception("Auto(Star) framewise processing failed")

    def _raw_array(self, request) -> np.ndarray:
        """A request's raw frame in the profile's bit-depth units (uint16)."""
        raw = request.make_array("raw").copy().view(np.uint16)
        if self._raw_shift:
            raw >>= self._raw_shift
        return raw

    def _default_controls(self) -> None:
        self.camera.set_controls(
            {
                "AeEnable": False,
                "AnalogueGain": self.gain,
                "ExposureTime": self.exposure_time,
            }
        )

    def start_camera(self) -> None:
        self.camera.start()
        self._camera_started = True

    def stop_camera(self) -> None:
        self.camera.stop()
        self._camera_started = False

    def capture(self) -> Image.Image:
        """
        Captures a raw 10/12bit sensor output and converts
        it to an 8 bit mono image stretched to use the maximum
        amount of the 255 level space.
        """
        capture_started_ns = time.monotonic_ns()
        _request = self.camera.capture_request()
        request_received_ns = time.monotonic_ns()
        try:
            # Copy the DMA-backed array and metadata, then return the request as
            # soon as possible.  With triple buffering this lets libcamera keep
            # exposing while all CPU-heavy work below runs.
            sensor_raw = self._raw_array(_request)
            metadata = dict(_request.get_metadata())
        finally:
            _request.release()
        request_released_ns = time.monotonic_ns()

        self._capture_sequence += 1
        sensor_timestamp = metadata.get("SensorTimestamp")
        sensor_timestamp_ns: Optional[int]
        if sensor_timestamp is None:
            sensor_timestamp_ns = None
        else:
            try:
                sensor_timestamp_ns = int(sensor_timestamp)
            except (TypeError, ValueError):
                sensor_timestamp_ns = None
        self.last_frame_id = (
            sensor_timestamp_ns
            if sensor_timestamp_ns is not None
            else self._capture_sequence
        )
        skipped_frames = estimate_sensor_drops(
            self._last_sensor_timestamp_ns,
            sensor_timestamp_ns,
            metadata.get("FrameDuration"),
        )
        self._estimated_sensor_drops += skipped_frames
        if sensor_timestamp_ns is not None:
            self._last_sensor_timestamp_ns = sensor_timestamp_ns

        self.last_capture_diagnostics = {
            "frame_id": self.last_frame_id,
            "frame_sequence": self._capture_sequence,
            "sensor_timestamp_ns": sensor_timestamp_ns,
            "request_wait_ms": (request_received_ns - capture_started_ns) / 1e6,
            "request_held_ms": (request_released_ns - request_received_ns) / 1e6,
            "estimated_dropped_since_last": skipped_frames,
            "estimated_dropped_total": self._estimated_sensor_drops,
            "processing_ms": None,
        }

        # Log actual camera metadata for exposure verification (debug level only).
        actual_exposure = metadata.get("ExposureTime", "unknown")
        actual_gain = metadata.get("AnalogueGain", "unknown")
        logger.debug(
            "Captured frame %s - Requested: %sµs/%sx gain, Actual: %sµs/%sx gain",
            self.last_frame_id,
            self.exposure_time,
            self.gain,
            actual_exposure,
            actual_gain,
        )
        # Sensor die temperature (diagnostic only): the black level wanders
        # ±2 ADU night-to-night and temperature is the prime suspect. Not all
        # sensors report it (imx296/HQ drivers may omit or mistype the key);
        # temperature must never be able to break a capture.
        try:
            temp = metadata.get("SensorTemperature")
            self.last_sensor_temp = float(temp) if temp is not None else None
        except (TypeError, ValueError):
            self.last_sensor_temp = None
        # Full driver metadata for the latest frame: calibration and sweeps
        # need the ACTUAL ExposureTime (drivers deliver transitional frames at
        # other-than-requested exposures) and whatever else this sensor's
        # driver chooses to report.
        self.last_frame_metadata = metadata

        # Crop and run the sparse radiometer before any optional LiveCam,
        # manager-proxy or PIL work.  The request is already released, so the
        # sensor is exposing the next frame concurrently.
        raw_capture = self.profile.crop_and_rotate(sensor_raw)
        cropped_raw = raw_capture
        control_started_ns = time.monotonic_ns()
        self._process_framewise_auto_star(raw_capture, metadata)
        self.last_capture_diagnostics["capture_to_control_ms"] = (
            time.monotonic_ns() - request_released_ns
        ) / 1e6
        self.last_capture_diagnostics["controller_processing_ms"] = (
            time.monotonic_ns() - control_started_ns
        ) / 1e6
        if hasattr(self, "shared_state"):
            self._radiometer_sequence += 1
            try:
                radiometer_exposure = float(actual_exposure) / 1_000_000.0
            except (TypeError, ValueError):
                radiometer_exposure = float(self.exposure_time) / 1_000_000.0
            sample = collect_radiometer_sample(
                raw_capture,
                self.profile,
                radiometer_exposure,
                sequence=self._radiometer_sequence,
                captured_at=time.time(),
            )
            if sample is not None:
                self.shared_state.set_sqm_radiometer_sample(sample)

        livecam_settings: dict[str, Any] = {}
        livecam_active = False
        livecam_source = None
        if hasattr(self, "shared_state") and hasattr(
            self.shared_state, "livecam_settings"
        ):
            livecam_settings = self.shared_state.livecam_settings() or {}
            livecam_active = processing_enabled(livecam_settings)
            if livecam_active:
                livecam_source = normalize_settings(livecam_settings)[
                    "input_frame_source"
                ]

        solver_preprocess_enabled = bool(
            livecam_settings.get("solver_preprocess_enabled", False)
        )
        # When production preprocessing is active, LiveCam reads the exact
        # already-warm solver output from shared state. A camera-side
        # accumulator remains only as a diagnostic fallback while production
        # preprocessing is disabled.
        camera_star_only_selected = bool(
            livecam_source == SOURCE_STAR_ONLY and not solver_preprocess_enabled
        )

        # Only the full-sensor frame needs keeping past the crop, and only
        # when the LiveCam viewer is actually looking at it.
        original_raw = (
            sensor_raw
            if livecam_source == SOURCE_ORIGINAL or camera_star_only_selected
            else None
        )

        # Diagnostic fallback used only when production solver preprocessing
        # is off. It deliberately runs only while selected because the robust
        # RAW preprocessor is substantially heavier than the ordinary preview
        # pipeline. With production preprocessing on, duplicating it here
        # would add capture-path work and show a different, newly-warming
        # temporal state from the frame Cedar+SEP actually consumes.
        star_only_raw = None
        if camera_star_only_selected:
            try:
                from PiFinder.mf_star_only_preprocess import (
                    MFStarOnlyAccumulator,
                    preprocess_geometry_fingerprint,
                )

                accumulator = getattr(self, "_mf_star_only_accumulator", None)
                if accumulator is None:
                    accumulator = MFStarOnlyAccumulator()
                    self._mf_star_only_accumulator = accumulator
                fingerprint = preprocess_geometry_fingerprint(
                    camera_type=self.camera_type,
                    pixel_format=self.profile.format,
                    frame_shape=tuple(sensor_raw.shape),
                    rotation_deg=self.profile.rotation_90,
                )
                star_only_raw = accumulator.add(
                    sensor_raw,
                    saturation_level=float(2**self.profile.bit_depth - 1),
                    fingerprint=fingerprint,
                ).frame
                self._mf_star_only_live_selected = True
            except Exception:
                logger.exception("LiveCam star-only preprocessing failed")
        elif getattr(self, "_mf_star_only_live_selected", False):
            accumulator = getattr(self, "_mf_star_only_accumulator", None)
            if accumulator is not None:
                accumulator.reset()
            self._mf_star_only_live_selected = False

        # Uncropped frame for the SEP full-frame detection path (shadow /
        # fallback). Same orientation convention as the cropped frame:
        # profile rotation applied, crop skipped. The reference is free --
        # the manager proxy pickles (copies) on set_solver_raw below.
        solver_full = None
        if getattr(self, "_publish_solver_raw", False) or solver_preprocess_enabled:
            solver_full = sensor_raw
            if self.profile.rotation_90 != 0:
                solver_full = np.rot90(solver_full, self.profile.rotation_90)

        # One-shot pipeline stage dump (save_stages command): collect a copy
        # of every processing stage of THIS frame; written at the end of this
        # capture so the writes don't sit between the processing steps.
        stage_dump_dir = getattr(self, "_stage_dump_dir", None)
        stages = []
        if stage_dump_dir:
            # The uncropped frame first when the SEP path is publishing it:
            # the offline detector bench needs the same input the full-frame
            # path sees, vignetted edges included.
            if solver_full is not None:
                stages.append(("raw_full", solver_full.copy()))
            stages.append(("raw_cropped", raw_capture.copy()))
        # LiveCam "Input Frame" pipeline stage view: keep only the stage the
        # viewer selected (solver_input is published by the camera loop after
        # rotation, not here).
        stage_frames = {}
        if star_only_raw is not None:
            stage_frames[SOURCE_STAR_ONLY] = star_only_raw

        # Store raw in shared state (before processing) for calibration and analysis
        if hasattr(self, "shared_state"):
            self.shared_state.set_cam_raw(raw_capture.copy())
            if solver_full is not None:
                self.shared_state.set_solver_raw(
                    {
                        "frame": solver_full,
                        "timestamp": time.time(),
                        "frame_id": self.last_frame_id,
                        "frame_sequence": self._capture_sequence,
                        "sensor_timestamp_ns": sensor_timestamp_ns,
                        "exposure_us": metadata.get("ExposureTime"),
                        "gain": metadata.get("AnalogueGain"),
                    }
                )

        # covert to 32 bit int to avoid overflow
        raw_capture = raw_capture.astype(np.float32)

        # sensor offset (bias pedestal from camera profile)
        raw_capture -= self.profile.bias_offset
        if stage_dump_dir:
            stages.append(("bias_subtracted", raw_capture.copy()))
        if livecam_source == SOURCE_BIAS_SUBTRACTED:
            stage_frames[livecam_source] = raw_capture.copy()

        # apply digital gain
        raw_capture *= self.profile.digital_gain
        if stage_dump_dir:
            stages.append(("digital_gain", raw_capture.copy()))
        if livecam_source == SOURCE_DIGITAL_GAIN:
            stage_frames[livecam_source] = raw_capture.copy()

        # rescale to 8 bit
        raw_capture = (
            raw_capture
            * 255
            / (2**self.profile.bit_depth - self.profile.bias_offset - 1)
        )

        # clip to avoid <0 or >255 values
        raw_capture = np.clip(raw_capture.astype(np.int32), 0, 255).astype(np.uint8)
        if stage_dump_dir:
            stages.append(("stretched_8bit", raw_capture.copy()))
        if livecam_source == SOURCE_STRETCHED_8BIT:
            stage_frames[livecam_source] = raw_capture.copy()

        # convert to PIL image and resize to 512x512
        raw_image = Image.fromarray(raw_capture).resize((512, 512))
        if livecam_source == SOURCE_RESIZED_512:
            stage_frames[livecam_source] = np.asarray(raw_image)

        if stage_dump_dir:
            stages.append(("resized_512", np.asarray(raw_image)))
            self._write_stage_dump(stage_dump_dir, stages)

        if livecam_active and livecam_source != SOURCE_SOLVER_INPUT:
            try:
                from PiFinder.raw_live_stack import publish_selected_frame

                publish_selected_frame(
                    self.shared_state,
                    livecam_settings,
                    self.profile,
                    self.camera_type,
                    original_raw,
                    cropped_raw,
                    metadata,
                    stage_frames=stage_frames,
                )
            except Exception as exc:
                logger.warning("LiveCam RAW publish failed: %s", exc)

        self.last_capture_diagnostics["processing_ms"] = (
            time.monotonic_ns() - request_released_ns
        ) / 1e6
        return raw_image

    def _write_stage_dump(self, stage_dump_dir, stages) -> None:
        """Write stages 0-4 and hand off to the camera loop for the final
        (rotated) solver-input stage. One-shot: disarm whatever happens."""
        from pathlib import Path

        from PiFinder import camera_stage_dump

        try:
            dump_dir = Path(stage_dump_dir)
            stats = [
                camera_stage_dump.save_stage(dump_dir, i, name, arr)
                for i, (name, arr) in enumerate(stages)
            ]
            self._stage_dump_stats = stats
            self._stage_dump_pending = stage_dump_dir
        except Exception:
            logger.exception("Stage dump failed")
        finally:
            self._stage_dump_dir = None

    def capture_bias(self) -> np.ndarray:
        """Capture a bias frame for measuring black level offset.

        Captures with 0µs exposure (lens cap on) to measure sensor black level.
        Returns raw sensor values before any processing.
        """
        self.camera.stop()
        self.camera.set_controls({"ExposureTime": 0})
        self.camera.start()
        _request = self.camera.capture_request()
        raw_capture = self._raw_array(_request)
        _request.release()

        self.camera.stop()
        self.camera.set_controls({"AnalogueGain": self.gain})
        self.camera.set_controls({"ExposureTime": self.exposure_time})
        self.camera.start()

        # Crop like normal capture but don't process
        return self.profile.crop_and_rotate(raw_capture)

    def capture_file(self, filename) -> None:
        tmp_capture = self.capture()
        tmp_capture.save(filename)

    def capture_raw_file(self, filename) -> None:
        """
        Captures raw sensor data and saves as 16-bit TIFF.

        For Bayer sensors (profile.mono False):
        - Saves raw Bayer mosaic (RGGB pattern)
        - Adds "_RGGB" suffix to filename (indicates Bayer pattern for post-processing)
        - Post-processing can debayer using scikit-image, opencv, etc.

        For mono sensors (profile.mono True): no suffix -- the data is
        luminance even when the driver labels the stream SRGGB12.

        For RGB sensors:
        - Converts to grayscale
        - Saves without Bayer pattern suffix

        The square crop is never applied here, and there is deliberately no
        option to apply it. The crop is a plain slice, so the full frame is a
        superset and ``profile.ensure_cropped()`` reproduces the cropped frame
        from it exactly -- while margins not written now are gone for good.
        Live photometry is unaffected: it reads ``cam_raw()``, still the crop.
        """
        _request = self.camera.capture_request()
        raw_capture = self._raw_array(_request)

        # Log actual camera metadata for exposure verification (debug level only)
        metadata = _request.get_metadata()
        actual_exposure = metadata.get("ExposureTime", "unknown")
        actual_gain = metadata.get("AnalogueGain", "unknown")
        logger.debug(
            f"Captured raw frame - Requested: {self.exposure_time}µs/{self.gain}x gain, "
            f"Actual: {actual_exposure}µs/{actual_gain:.2f}x gain"
        )

        _request.release()

        # Expose this frame's driver metadata and its CROPPED pixels so the
        # sweep capture can record per-image radiometry (exposure sweeps are
        # the only caller; both are overwritten on every raw capture).
        #
        # Note the asymmetry, and that it is deliberate: the TIFF written below
        # is full-sensor, while these statistics cover the crop. They are the
        # black-level-versus-temperature series, and the vignetted margins
        # would shift every mean and percentile, silently ending comparability
        # with the archive taken before sweeps went full-sensor. Full-sensor
        # statistics stay computable from the TIFF.
        self.last_frame_driver_metadata = metadata
        self.last_cropped_frame = self.profile.crop_and_rotate(raw_capture)

        # Determine if we need to flag for debayering
        needs_debayer = False

        # Handle different input types
        if raw_capture.ndim == 3:
            # Already RGB - convert to grayscale
            logger.debug(
                f"Converting RGB raw data to grayscale (shape: {raw_capture.shape})"
            )
            raw_capture = (
                raw_capture[:, :, 0] * 0.299
                + raw_capture[:, :, 1] * 0.587
                + raw_capture[:, :, 2] * 0.114
            ).astype(np.uint16)
            needs_debayer = False
        elif raw_capture.ndim == 2:
            # 2D raw: only a real CFA needs the debayer flag. Mono sensors
            # (imx296, and imx462/imx290 which measure mono despite their
            # SRGGB12 label -- see CameraProfile.mono) deliver luminance;
            # tagging them _RGGB makes post-processing fabricate chroma noise.
            needs_debayer = not self.profile.mono
            logger.debug(
                f"Saving raw frame (shape: {raw_capture.shape}, "
                f"debayer={'yes' if needs_debayer else 'no, mono sensor'})"
            )
        else:
            raise ValueError(f"Unexpected raw image dimensions: {raw_capture.ndim}")

        # Modify filename if debayering needed
        if needs_debayer:
            # Insert "_RGGB" suffix before extension to indicate Bayer pattern
            import os

            base, ext = os.path.splitext(filename)
            filename = f"{base}_RGGB{ext}"

        # Save as 16-bit TIFF
        raw_image = Image.fromarray(raw_capture, mode="I;16")
        raw_image.save(filename, format="TIFF")

        debayer_note = " (RGGB Bayer pattern)" if needs_debayer else ""
        logger.debug(
            f"Saved raw {self.profile.bit_depth}-bit image as 16-bit TIFF: {filename}{debayer_note}"
        )

    def set_camera_config(
        self, exposure_time: float, gain: float
    ) -> Tuple[float, float]:
        # picamera2 supports changing controls on-the-fly without restart.
        # Setting a manual exposure always disables native auto-exposure, so a
        # prior `set_exp:native` (daytime align) can't keep overriding it.
        self.camera.set_controls(
            {
                "AeEnable": False,
                "AnalogueGain": gain,
                "ExposureTime": exposure_time,
            }
        )

        # Start camera if it's not already running
        if not self._camera_started:
            self.start_camera()
        return exposure_time, gain

    def set_native_ae(self, enabled: bool) -> bool:
        """Enable/disable picamera2's native auto-exposure (AEC/AGC).

        Used by the daytime alignment screen so the driver picks a short
        daylight exposure automatically. Returns True (Pi cameras support it).
        """
        self.camera.set_controls({"AeEnable": enabled})
        if not self._camera_started:
            self.start_camera()
        return True

    def get_cam_type(self) -> str:
        return self.camType


def get_images(shared_state, camera_image, command_queue, console_queue, log_queue):
    """
    Instantiates the camera hardware
    then calls the universal image loop
    """
    MultiprocLogging.configurer(log_queue)

    cfg = config.Config()
    exposure_time = cfg.get_option("camera_exp")

    # Handle auto-exposure modes: use default value, auto-exposure will adjust
    if exposure_time in ("auto", "auto_star"):
        exposure_time = 400000  # Start with default 400ms

    camera_hardware = CameraPI(exposure_time, cfg)
    camera_hardware.get_image_loop(
        shared_state, camera_image, command_queue, console_queue, cfg
    )
