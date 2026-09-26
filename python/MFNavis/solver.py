#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the solver
* runs loop looking for new images
* tries to solve them
* If solved, emits solution into queue

"""

from PiFinder.multiproclogging import MultiprocLogging
from concurrent.futures import ThreadPoolExecutor
import json
import queue
import numpy as np
import time
import logging
import sys
from time import perf_counter as precision_timestamp
import os
import threading
from typing import Optional

from PiFinder import config as config_mod
from PiFinder import state_utils
from PiFinder import utils
from PiFinder import timez
from PiFinder import horizon_mask
from PiFinder import solver_frame_map as sfm
from PiFinder.auto_exposure_framewise import matched_star_exposure_quality
from PiFinder.alignment_projection import make_projection, projection_context
from PiFinder.mf_distortion_calibration import (
    DistortionCalibrationSession,
    MIN_CANDIDATES as DISTORTION_MIN_CANDIDATES,
    measure_distortion_frame,
)
from PiFinder.mf_manual_lens import manual_focal_from_state, calibration_lens_key
from PiFinder.lens_measurement import LensMeasurement, measure_lens_frame
from PiFinder.mf_star_only_preprocess import preprocess_geometry_fingerprint
from PiFinder.mf_wide_calibration import CalibrationProfileStore
from PiFinder.mf_wide_distortion import active_coefficients
from PiFinder.optics import OpticalTrainResolver, build_optical_train
from PiFinder.latest_frame_worker import LatestFrameWorker
from PiFinder.preprocess_bias import PreprocessBiasTracker
from PiFinder.solver_scheduling import SolverSchedulingPolicy
from PiFinder.solver_capture import CaptureRecorder
from PiFinder.sep_shadow import (
    MAX_FRAME_AGE_S,
    WARM_MAP_PATH,
    SepShadowRunner,
    configure_runtime_detection,
)
from PiFinder.solve_acceptance import (
    SolveContinuityGate,
    angular_separation_deg,
)
from PiFinder.sqm import SQM as SQMCalculator
from PiFinder.sqm.camera_profiles import get_camera_profile
from PiFinder.sqm.black_level import BlackLevelTracker
from PiFinder.sqm.clouds import CloudEstimator
from PiFinder.sqm.radiometer import RadiometerAccumulator, extract_photometry_image
from PiFinder.sqm.wings import WingEstimator
from PiFinder.state import SQM as SQMState
from PiFinder.types.positioning import (
    AlignCancel,
    AlignOnRaDec,
    AlignedResult,
    AlignmentResult,
    CancelDistortionCalibration,
    StartLensMeasurement,
    CancelLensMeasurement,
    FailedSolve,
    Pointing,
    ReloadSqmCalibration,
    SolveDiagnostics,
    SuccessfulSolve,
    StartDistortionCalibration,
)

sys.path.append(str(utils.tetra3_dir))
import tetra3

logger = logging.getLogger("Solver")

# SQM publication interval - the radiometric value publishes at most every
# N seconds (samples are collected on every frame regardless)
SQM_CALCULATION_INTERVAL_SECONDS = 1.0

# Stellar photometry is a transmission diagnostic in the radiometer-first
# path; it is expensive, so it runs at most every N seconds on solves.
SQM_STELLAR_DIAGNOSTIC_INTERVAL_SECONDS = 10.0
# A motorized slew invalidates the temporal star-only window, but a valid raw
# solve is already available before the expensive rebuild.  Release up to two
# stationary raw solves immediately: one handles an ordinary near correction,
# while the second can confirm a >5-degree continuity jump.  Normal temporal
# preprocessing resumes on the following frame.
POST_MOTION_RAW_FAST_FRAMES = 2
MOUNT_STATUS_MAX_AGE_SECONDS = 5.0


def _post_motion_raw_fast_path(
    *, frame_moving: bool, raw_solved: bool, remaining: int
) -> tuple[bool, int]:
    """Return whether this frame should bypass preprocessing and new budget."""

    if frame_moving:
        return False, POST_MOTION_RAW_FAST_FRAMES
    if raw_solved and remaining > 0:
        return True, remaining - 1
    return False, remaining


def _mount_status_reports_motion(status: object, *, now: float | None = None) -> bool:
    """Return a fresh mount-driven motion flag from the runtime status."""

    if not isinstance(status, dict):
        return False
    timestamp = time.time() if now is None else float(now)
    try:
        updated = float(status.get("updated") or 0.0)
    except (TypeError, ValueError):
        return False
    if updated <= 0.0 or timestamp - updated > MOUNT_STATUS_MAX_AGE_SECONDS:
        return False
    return bool(
        status.get("mount_motion_active")
        or status.get("goto_motion_active")
        or status.get("manual_motion_direction")
    )


def _mount_motion_active() -> bool:
    """Read the mount status from tmpfs without coupling solver processes."""

    try:
        with (utils.runtime_dir / "mount_control_status.json").open(
            "r", encoding="utf-8"
        ) as status_file:
            return _mount_status_reports_motion(json.load(status_file))
    except (OSError, ValueError, TypeError):
        return False


def _solver_preprocess_enabled(shared_state) -> bool:
    """Read the persisted production solver-preprocessing switch defensively."""

    try:
        settings = shared_state.livecam_settings() or {}
        return bool(settings.get("solver_preprocess_enabled", False))
    except (AttributeError, BrokenPipeError, ConnectionResetError):
        return False


def _read_matching_solver_inputs(shared_state, attempts: int = 2):
    """Read the newest 512 frame envelope and its matching full RAW.

    Production state embeds the corresponding RAW in the 512 envelope, so
    one manager call freezes the pair. Older/debug state implementations
    retain the bounded two-getter compatibility path.
    """

    latest_frame = None
    for _ in range(max(1, int(attempts))):
        candidate_frame = shared_state.solver_frame()
        if not (
            isinstance(candidate_frame, dict)
            and "image" in candidate_frame
            and isinstance(candidate_frame.get("metadata"), dict)
        ):
            continue
        latest_frame = candidate_frame
        candidate_raw = (
            candidate_frame["raw"]
            if "raw" in candidate_frame
            else shared_state.solver_raw()
        )
        frame_id = candidate_frame["metadata"].get("frame_id")
        if (
            isinstance(candidate_raw, dict)
            and "frame" in candidate_raw
            and frame_id is not None
            and candidate_raw.get("frame_id") == frame_id
        ):
            return candidate_frame, candidate_raw
    return latest_frame, None


def _preprocessed_fast_path_allowed(
    *,
    enabled: bool,
    trusted: bool,
    moving: bool,
    aligning: bool,
    scheduling_mode: str = "sync",
) -> bool:
    """Whether a trusted preprocessed path may replace slow RAW fallbacks."""

    return bool(
        scheduling_mode == "sync"
        and enabled
        and trusted
        and not moving
        and not aligning
    )


def _solution_coordinate_snapshot(solution: dict) -> Optional[dict]:
    """Copy only coordinate fields needed by asynchronous bias calibration."""

    if not solution or solution.get("RA") is None:
        return None
    snapshot = {
        "RA": float(solution["RA"]),
        "Dec": float(solution["Dec"]),
    }
    for key in ("RA_target", "Dec_target"):
        value = solution.get(key)
        if value is not None:
            snapshot[key] = float(value)
    return snapshot


def _publish_solver_scheduling_status(status: dict) -> None:
    """Keep field diagnostics in RAM, independently of the selected preview."""
    try:
        path = utils.runtime_dir / "solver_scheduling_status.json"
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as status_file:
            json.dump(status, status_file)
        temporary.replace(path)
    except OSError:
        logger.debug("Could not publish solver scheduling status", exc_info=True)


def _publish_solver_preprocess_status(
    shared_state,
    *,
    enabled: bool,
    state: str,
    frame_count: int = 0,
    frame_id=None,
    reset_reason=None,
    error=None,
    clear_frame: bool = False,
) -> None:
    """Publish lightweight production-preprocessor state for LiveCam.

    Best-effort by design: preview/status publication must never turn a valid
    solve into a failed attempt.
    """

    try:
        setter = getattr(shared_state, "set_solver_preprocess_status", None)
        if callable(setter):
            setter(
                {
                    "enabled": bool(enabled),
                    "state": state,
                    "frame_count": int(frame_count),
                    "frame_limit": 5,
                    "frame_id": frame_id,
                    "reset_reason": reset_reason,
                    "error": error,
                    "updated": time.time(),
                }
            )
        if clear_frame:
            frame_setter = getattr(shared_state, "set_solver_preprocessed_frame", None)
            if callable(frame_setter):
                frame_setter(None)
    except Exception:
        logger.exception("Could not publish solver preprocessing status")


def _publish_solver_preprocessed_preview(
    shared_state, preprocessed_run, image_metadata
) -> None:
    """Cache the exact production star-only frame for instant LiveCam use."""

    try:
        from PiFinder.raw_live_stack import publish_solver_preprocessed_frame

        camera_type = shared_state.camera_type()
        profile = get_camera_profile(camera_type)
        settings = shared_state.livecam_settings() or {}
        publish_solver_preprocessed_frame(
            shared_state,
            preprocessed_run.frame,
            profile,
            camera_type,
            image_metadata,
            preprocess_frames=preprocessed_run.diagnostics.frame_count,
            display_rotation_degrees=int(
                settings.get("display_rotation_degrees", 0) or 0
            ),
        )
        _publish_solver_preprocess_status(
            shared_state,
            enabled=True,
            state="ready",
            frame_count=preprocessed_run.diagnostics.frame_count,
            frame_id=preprocessed_run.frame_id,
            reset_reason=preprocessed_run.diagnostics.reset_reason,
        )
    except Exception as exc:
        logger.exception("Could not publish solver preprocessed LiveCam frame")
        _publish_solver_preprocess_status(
            shared_state,
            enabled=True,
            state="preview_error",
            frame_id=image_metadata.get("frame_id"),
            error=f"{exc.__class__.__name__}: {exc}",
            clear_frame=True,
        )


def _optical_fov_gate_params(shared_state) -> tuple[float, float]:
    """Return the stated/assumed optical-train gate, or legacy values safely.

    This helper is only consumed when ``solver_optics_fov_gate`` is enabled.
    A malformed camera or lens value must never turn a recoverable solve into
    a solver restart loop, so preserve the established 12 +/- 4 degree gate
    on any resolution error.
    """
    try:
        lens_getter = getattr(shared_state, "camera_lens", None)
        lens_key = lens_getter() if callable(lens_getter) else None
        train = build_optical_train(
            shared_state.camera_type(), lens_key, manual_focal_from_state(shared_state)
        )
        return train.solver_fov_params()
    except Exception:
        logger.exception("Optical FOV gate unavailable; using legacy gate")
        return (12.0, 4.0)


def _optical_crop_fov(shared_state) -> float:
    """Return one train's crop FOV, or legacy 12 degrees on bad state."""
    try:
        lens_getter = getattr(shared_state, "camera_lens", None)
        lens_key = lens_getter() if callable(lens_getter) else None
        return build_optical_train(
            shared_state.camera_type(), lens_key, manual_focal_from_state(shared_state)
        ).fov_degrees
    except Exception:
        logger.exception("Optical crop FOV unavailable; using legacy FOV")
        return sfm.SOLVER_FOV_DEG


def _fullframe_optics_key(
    shared_state, base_fov_degrees: float, calibration_id: str = ""
) -> tuple[str, str, float, str]:
    """A lightweight identity for cached full-frame solver geometry.

    The camera lens can be changed from the Advanced menu while the solver is
    running.  MFDS/SEP geometry is cached for speed, so the cache must be
    invalidated on the next frame rather than silently retaining the previous
    lens FOV.  Bad shared-state reads are represented in the key and still
    fall back to the established FOV path.
    """

    try:
        camera_type = str(shared_state.camera_type() or "")
    except Exception:
        camera_type = ""
    try:
        lens_getter = getattr(shared_state, "camera_lens", None)
        lens_key = str(lens_getter() or "") if callable(lens_getter) else ""
    except Exception:
        lens_key = ""
    manual_focal = manual_focal_from_state(shared_state)
    return (
        camera_type,
        f"{lens_key}:{manual_focal or ''}",
        round(float(base_fov_degrees), 8),
        str(calibration_id or ""),
    )


def _active_calibration_id(cfg, shared_state) -> str:
    """Return the active profile ID used to invalidate solver geometry."""

    try:
        camera_type = str(shared_state.camera_type() or "")
        lens_key = str(getattr(shared_state, "camera_lens", lambda: "")() or "")
        calibration = CalibrationProfileStore(cfg).load_active(
            camera_type, lens_key, get_camera_profile(camera_type)
        )
        return str(calibration.get("id") or "") if calibration else ""
    except Exception:
        return ""


def create_sqm_calculator(shared_state):
    """Create a new SQM calculator instance with current calibration.

    Photometry always runs on the raw linear frame (green channel for Bayer
    sensors); the 8-bit processed image is for solving/display only.
    """
    camera_type = shared_state.camera_type()
    logger.info(f"Creating raw-green SQM calculator for camera: {camera_type}")
    return SQMCalculator(camera_type=camera_type)


def _extract_raw_photometry_image(raw, profile):
    """Build the linear photometry image from the stored raw frame.

    For Bayer sensors (SRGGB*) returns the averaged green channel (half-res);
    for mono sensors returns the raw frame as-is. Returns None on any shape/
    dtype problem so the caller can skip the SQM cycle.
    """
    return extract_photometry_image(raw, profile)


def _scaled_photometry_radii(
    scale, aperture_radius=5, inner_radius=10, outer_radius=18
):
    """Convert photometry radii from solve-image (512px) pixels to the
    photometry image's own pitch.

    The radii were tuned on the ~1.0-scale Bayer-green images (imx462: 490px).
    On the full-res mono imx296 (scale 2.125) the unscaled r=5 aperture holds
    only ~85% of a star's flux and the annuli land on the PSF itself, biasing
    every local sky estimate. The floors keep the geometry ordered
    (aperture < inner < outer) at any scale.
    """
    aperture = max(1, round(aperture_radius * scale))
    inner = max(aperture + 1, round(inner_radius * scale))
    outer = max(inner + 2, round(outer_radius * scale))
    return aperture, inner, outer


def _scale_solution_centroids(solution, scale):
    """Return a shallow copy of solution with matched_centroids scaled.

    The solve runs on the 512x512 processed image; the raw photometry image has a
    different pixel pitch, so the matched star positions must be rescaled to it.
    """
    scaled = dict(solution)
    mc = np.asarray(solution["matched_centroids"], dtype=np.float64) * scale
    scaled["matched_centroids"] = mc
    return scaled


def _derotate_centroids(points, rotation_deg, size):
    """Map (y, x) centroids from the display-rotated solve image back onto
    the unrotated raw frame's pixel grid.

    The camera process rotates the solve/display image by ``rotation_deg``
    (PIL CCW) relative to the raw it stores in shared state; photometry runs
    on the raw, so star positions must be counter-rotated or every aperture
    lands on the wrong sky (SQM then reads magnitudes too bright).

    Args:
        points: (N, 2) array of (y, x) positions in the rotated image.
        rotation_deg: degrees the solve image was rotated (PIL CCW).
        size: side length of the (square) pixel grid the points live on.
    """
    pts = np.asarray(points, dtype=np.float64)
    k = int(rotation_deg) % 360
    y, x = pts[:, 0], pts[:, 1]
    m = size - 1
    if k == 0:
        return pts
    if k == 90:
        # solve = raw rotated 90 CCW: raw_y = x, raw_x = m - y
        return np.stack([x, m - y], axis=1)
    if k == 180:
        return np.stack([m - y, m - x], axis=1)
    if k == 270:
        # solve = raw rotated 270 CCW: raw_y = m - x, raw_x = y
        return np.stack([m - x, y], axis=1)
    # Arbitrary angle: rotate about the image centre. PIL's rotate(a) fills
    # dest(x2, y2) from src at c + R(a)·(p2 − c) in (x, y) with y down.
    c = m / 2.0
    a = np.radians(k)
    dx, dy = x - c, y - c
    rx = c + np.cos(a) * dx - np.sin(a) * dy
    ry = c + np.sin(a) * dx + np.cos(a) * dy
    return np.stack([ry, rx], axis=1)


def update_radiometric_sqm(
    shared_state,
    sqm_calculator,
    accumulator,
    sample,
    calculation_interval_seconds=1.0,
    now=None,
    black_level_tracker=None,
    field_width_degrees=None,
):
    """Collect every frame and publish a solve-independent value at cadence."""
    from datetime import datetime

    fresh_sample = accumulator.add(sample)
    current_time = time.time() if now is None else float(now)

    # Every fresh radiometer sample carries (exposure, background) — feed the
    # black-level tracker here rather than only from the 10-second stellar
    # diagnostics: this cadence conditions its fit in minutes and keeps working
    # through failed solves. Withheld while the last transmission diagnostic
    # said cloud (a moving sky breaks the intercept's single-line model; the
    # tracker's own stderr gate catches drift the flag misses).
    if black_level_tracker is not None and fresh_sample:
        cloudy_now = shared_state.sqm_details().get("cloud_flag") is True
        black_level_tracker.add_sample(
            float(sample["exposure_sec"]),
            float(sample["background_per_pixel"]),
            stable=not cloudy_now,
        )

    current_sqm = shared_state.sqm()
    if current_sqm.last_update is not None:
        try:
            last_update = datetime.fromisoformat(current_sqm.last_update).timestamp()
            if current_time - last_update < calculation_interval_seconds:
                return False
        except (ValueError, AttributeError):
            logger.warning("Failed to parse SQM timestamp, recalculating")

    noise = sqm_calculator.noise_floor_estimator

    def tracked_or_static_bias():
        # The in-session intercept supersedes any static bias, wizard-measured
        # or profile: the OB clamp level moves with sensor state, so a stored
        # constant goes stale while the tracker measures the running session's
        # own frames — bounded by its stderr, deviation-band, and lease gates.
        # The wander is negligible over a city background but worth
        # 0.2–0.4 mag (and dead short-exposure frames) at a dark site.
        if black_level_tracker is not None:
            tracked = black_level_tracker.pedestal()
            if tracked is not None:
                return tracked
        return sqm_calculator.profile.bias_offset

    def pedestal_for_exposure(exposure_sec):
        bias = tracked_or_static_bias()
        if not noise.dark_current_calibrated:
            return bias
        # Dark current stays the wizard's: the intercept fit cannot separate
        # dark from sky (both are linear in exposure).
        return bias + sqm_calculator.profile.dark_current_rate * exposure_sec

    sqm_value, details = accumulator.estimate(
        sqm_calculator.profile,
        current_time,
        pedestal_for_exposure=pedestal_for_exposure,
        field_width_degrees=field_width_degrees,
    )
    if sqm_value is None:
        previous = shared_state.sqm_details()
        shared_state.set_sqm_details({**previous, **details})
        return False

    previous = shared_state.sqm_details()
    diagnostic_at = previous.get("transmission_diagnostic_at")
    diagnostic_age = current_time - diagnostic_at if diagnostic_at is not None else None
    if (
        previous.get("optics_attenuation_candidate")
        and diagnostic_age is not None
        and 0 <= diagnostic_age <= 15.0
    ):
        deficit = previous.get("transmission_deficit")
        if deficit is not None and 0.0 < deficit <= 2.0:
            details["sqm_radiometric_uncorrected"] = sqm_value
            details["optics_attenuation_correction"] = -float(deficit)
            sqm_value -= float(deficit)

    if black_level_tracker is not None:
        tracked, tracked_stderr, _ = black_level_tracker.state()
        # pedestal() applies the lease; the flag must reflect what the
        # publication actually used, not the raw last fit.
        details["black_level_tracked"] = black_level_tracker.pedestal() is not None
        details["black_level_pedestal"] = tracked
        details["black_level_stderr"] = tracked_stderr
        details["window_black_level"] = black_level_tracker.dump()
    details["window_radiometer"] = accumulator.dump()
    details["measurement_role"] = "primary_radiometer"
    shared_state.set_sqm_details({**previous, **details})
    shared_state.set_sqm(
        SQMState(
            value=sqm_value,
            source="Radiometer",
            last_update=timez.local_now().isoformat(),
        )
    )
    # Publishes at 1 Hz in steady state; DEBUG per the MF logging policy
    # (c0ca4dcc) so a night's log isn't 30k identical lines.
    logger.debug("Radiometric SQM updated: %.2f mag/arcsec²", sqm_value)
    return True


def update_sqm(
    shared_state,
    sqm_calculator,
    centroids,
    solution,
    exposure_sec,
    altitude_deg,
    calculation_interval_seconds=5.0,
    aperture_radius=5,
    annulus_inner_radius=10,
    annulus_outer_radius=18,
    wing_estimator=None,
    cloud_estimator=None,
    black_level_tracker=None,
    publish=True,
):
    """
    Calculate SQM from image.

    Args:
        shared_state: SharedStateObj instance
        sqm_calculator: SQM calculator instance
        centroids: List of detected star centroids
        solution: Tetra3 solve solution with matched stars
        exposure_sec: Exposure time in seconds
        altitude_deg: Altitude in degrees for extinction correction
        calculation_interval_seconds: Minimum time between calculations (default: 5.0)
        aperture_radius: Aperture radius for photometry, in solve-image
            (512px) pixels; rescaled to the photometry image (default: 5)
        annulus_inner_radius: Inner annulus radius, solve-image pixels (default: 10)
        annulus_outer_radius: Outer annulus radius, solve-image pixels (default: 18)
        wing_estimator: WingEstimator that supplies the rolling aperture
            (wing-loss) mzero correction and is fed each frame's photometry
            image + matched centroids.

    Returns:
        bool: True if SQM was calculated and updated, False otherwise
    """
    from datetime import datetime

    # Get current SQM state from shared state
    current_sqm = shared_state.sqm()
    current_time = time.time()

    # Check if we should calculate SQM
    should_calculate = not publish or current_sqm.last_update is None

    if publish and current_sqm.last_update is not None:
        try:
            last_update_time = datetime.fromisoformat(
                current_sqm.last_update
            ).timestamp()
            should_calculate = (
                current_time - last_update_time
            ) >= calculation_interval_seconds
        except (ValueError, AttributeError):
            logger.warning("Failed to parse SQM timestamp, recalculating")
            should_calculate = True

    if not should_calculate:
        return False

    profile = sqm_calculator.profile

    try:
        raw = shared_state.cam_raw()
    except (BrokenPipeError, ConnectionResetError):
        raw = None
    green = _extract_raw_photometry_image(raw, profile)
    if green is None or green.shape[0] < 256:
        # cam_raw() is None until the first real capture (test mode never
        # fills it), and a malformed frame comes through far smaller than a
        # real one. A genuine green frame is several hundred px per side —
        # e.g. ~490 for the imx462/imx290 crop, larger for the imx296 — so
        # the floor only rejects missing/garbage frames, not valid sensors.
        # Photometry runs at the green frame's own scale, so a side shorter
        # than the 512px solve image is fine.
        logger.debug("Raw frame unavailable/invalid for SQM; skipping this cycle")
        return False
    scale = green.shape[0] / 512.0
    aperture_radius, annulus_inner_radius, annulus_outer_radius = (
        _scaled_photometry_radii(
            scale, aperture_radius, annulus_inner_radius, annulus_outer_radius
        )
    )
    calc_image = green
    calc_solution = _scale_solution_centroids(solution, scale)
    # All detected centroids, scaled to the photometry image: sqm masks them
    # out of background annuli (neighbour-star contamination in dense fields).
    calc_centroids = (
        np.asarray(centroids, dtype=np.float64) * scale
        if centroids is not None and len(centroids) > 0
        else None
    )

    # The solve image is display-rotated relative to the raw; counter-rotate
    # all star positions onto the raw's grid before photometry.
    try:
        solve_rotation = shared_state.solve_image_rotation()
    except (BrokenPipeError, ConnectionResetError, AttributeError):
        solve_rotation = None
    if solve_rotation:
        side = green.shape[0]
        calc_solution["matched_centroids"] = _derotate_centroids(
            calc_solution["matched_centroids"], solve_rotation, side
        )
        if calc_centroids is not None:
            calc_centroids = _derotate_centroids(calc_centroids, solve_rotation, side)
    image_pixels_per_side = int(green.shape[0])
    # 0.70 of full scale, not ~1.0: CMOS response bends well before hard
    # clip, and stars peaking at 75-90% already read systematically low.
    saturation_threshold = int(0.70 * (2**profile.bit_depth - 1))

    mzero_correction = 0.0
    if wing_estimator is not None:
        # Match the estimator's patch geometry to this photometry image
        # (no-op after the first frame; the scale is a per-camera constant).
        wing_estimator.set_scale(scale)
        mzero_correction = wing_estimator.correction()

    # Pedestal from the sky-vs-exposure intercept (see sqm.black_level): the
    # in-session tracked bias supersedes any static constant, wizard-measured
    # or profile — the OB clamp level moves with sensor state, so a stored
    # value goes stale. The wizard's dark-current rate remains authoritative
    # (the intercept fit cannot separate dark from sky) and is added on top,
    # matching the calculator's own bias + dark composition.
    pedestal_override = None
    if black_level_tracker is not None:
        tracked = black_level_tracker.pedestal()
        if tracked is not None:
            pedestal_override = tracked
            if sqm_calculator.noise_floor_estimator.dark_current_calibrated:
                pedestal_override += (
                    sqm_calculator.profile.dark_current_rate * exposure_sec
                )

    try:
        # Calculate SQM from image
        sqm_value, details = sqm_calculator.calculate(
            centroids=calc_centroids,
            solution=calc_solution,
            image=calc_image,
            exposure_sec=exposure_sec,
            altitude_deg=altitude_deg,
            aperture_radius=aperture_radius,
            annulus_inner_radius=annulus_inner_radius,
            annulus_outer_radius=annulus_outer_radius,
            saturation_threshold=saturation_threshold,
            image_pixels_per_side=image_pixels_per_side,
            mzero_correction=mzero_correction,
            pedestal_override=pedestal_override,
        )

        # Feed this frame's stars into the rolling wing (aperture-loss) fit.
        if (
            wing_estimator is not None
            and calc_solution.get("matched_centroids") is not None
        ):
            wing_estimator.add_frame(
                calc_image,
                calc_solution["matched_centroids"],
                saturation_threshold,
            )

        # Stellar photometry is now a live transmission diagnostic. The primary
        # sky value is the fixed-calibration radiometer and remains meaningful
        # through cloud; stars classify cloud versus instrument attenuation.
        # Feed the estimator and report the deficit. Only a recent non-cloud
        # deficit against a conditioned session baseline may compensate the
        # next radiometric publication for instrument-side attenuation.
        cloud_flag = None
        if cloud_estimator is not None and details.get("mzero") is not None:
            try:
                pointing = shared_state.solution()
                pointing_alt = getattr(pointing, "Alt", None)
            except (BrokenPipeError, ConnectionResetError, AttributeError):
                pointing_alt = None
            # sky_brightness is the independent radiometric measurement,
            # UNCORRECTED: the guard asks whether the raw sky is anomalously
            # bright vs the device's learned clear-sky level (cloud brightens
            # the sky; dew/optics dim stars and sky together). Feeding the
            # optics-compensated published value back would let a transient
            # correction overshoot masquerade as sky excess and mislabel dew
            # onset as cloud.
            previous_details = shared_state.sqm_details()
            radiometric_sky = previous_details.get("sqm_radiometric")
            if radiometric_sky is None:
                radiometric_sky = shared_state.sqm().value
            cloud_deficit = cloud_estimator.add_sample(
                details["mzero"],
                exposure_sec,
                sky_brightness=radiometric_sky,
                # details['mzero'] already includes the wing correction.
                wing_correction=0.0,
                altitude_deg=pointing_alt,
            )
            cloud_flag = cloud_estimator.is_cloudy()
            details["cloud_extinction"] = cloud_deficit
            details["cloud_flag"] = cloud_flag
            details["transmission_deficit"] = cloud_deficit
            details["optics_attenuation_candidate"] = bool(
                cloud_deficit is not None
                and cloud_deficit > cloud_estimator.cloud_threshold
                and cloud_flag is False
                and cloud_estimator.conditioned()
            )
            details["transmission_diagnostic_at"] = time.time()
            primary_value = shared_state.sqm().value
            if details["optics_attenuation_candidate"]:
                details["sqm_optics_compensated"] = primary_value - cloud_deficit

        # The tracker is fed from the radiometer samples (denser cadence, and
        # the same background estimator its pedestal is applied to); here it is
        # only consumed, so stellar diagnostics report the pedestal actually
        # used for their photometry.
        if black_level_tracker is not None:
            details["black_level_tracked"] = pedestal_override is not None

        details["sqm_star_calibrated"] = sqm_value
        details["measurement_role"] = "stellar_transmission_diagnostic"

        # Full rolling-window state of every tracker, so diagnostics dumps
        # (exposure sweeps in particular) carry the samples behind each
        # published number, not just the summary.
        if wing_estimator is not None:
            details["window_wings"] = wing_estimator.dump()
        if cloud_estimator is not None:
            details["window_clouds"] = cloud_estimator.dump()
        if black_level_tracker is not None:
            details["window_black_level"] = black_level_tracker.dump()

        # Store SQM details (filter out large per-star arrays)
        filtered_details = {
            k: v
            for k, v in details.items()
            if k
            not in (
                "star_centroids",
                "star_mags",
                "star_fluxes",
                "star_local_backgrounds",
                "star_mzeros",
            )
        }
        previous = shared_state.sqm_details()
        shared_state.set_sqm_details({**previous, **filtered_details})

        # Update shared state
        if publish and sqm_value is not None:
            new_sqm_state = SQMState(
                value=sqm_value,
                source="Calculated",
                last_update=timez.local_now().isoformat(),
            )
            shared_state.set_sqm(new_sqm_state)
            logger.debug(f"SQM updated: {sqm_value:.2f} mag/arcsec²")
            return True
        if sqm_value is not None:
            return True

    except Exception as e:
        logger.error(f"Error calculating SQM: {e}")
        return False

    return False


def _build_successful_solve(
    solution: dict,
    last_image_metadata: dict,
    last_solve_attempt: float,
    last_solve_success: float,
    centroid_count: int = 0,
    solve_path: str = "",
    cedar_raw_centroids: Optional[int] = None,
    cedar_gated_centroids: Optional[int] = None,
    cedar_center_centroids: Optional[int] = None,
    sep_centroids: Optional[int] = None,
    frame_id: Optional[int] = None,
    exposure_quality: Optional[dict[str, object]] = None,
    alignment_context: Optional[tuple] = None,
) -> SuccessfulSolve:
    """Fold a successful tetra3 ``solution`` dict into a
    :class:`SuccessfulSolve` message.

    Carries flat per-axis solve-truth (no ``solve``/``estimate`` split);
    the integrator fans ``camera``/``aligned`` into both cells of its
    long-lived :class:`PointingEstimate` and advances only the
    ``estimate`` cells via IMU dead-reckoning between solves.
    """
    camera_value = Pointing(
        RA=solution["RA"],
        Dec=solution["Dec"],
        Roll=solution["Roll"],
    )
    aligned_value = Pointing(
        RA=solution.get("RA_target", solution["RA"]),
        Dec=solution.get("Dec_target", solution["Dec"]),
        Roll=solution["Roll"],
    )

    imu_anchor = None
    imu_sample = last_image_metadata.get("imu")
    if imu_sample and imu_sample.is_usable(now=last_image_metadata.get("exposure_end")):
        imu_anchor = imu_sample.quat

    return SuccessfulSolve(
        camera=camera_value,
        aligned=aligned_value,
        imu_anchor=imu_anchor,
        last_solve_attempt=last_solve_attempt,
        last_solve_success=last_solve_success,
        diagnostics=SolveDiagnostics(
            Matches=solution.get("Matches", 0),
            Centroids=centroid_count,
            RMSE=solution.get("RMSE"),
            Prob=solution.get("Prob"),
            FOV=solution.get("FOV"),
            T_solve=solution.get("T_solve"),
            solve_path=solve_path,
            T_extract=solution.get("T_extract"),
            CedarRawCentroids=cedar_raw_centroids,
            CedarGatedCentroids=cedar_gated_centroids,
            CedarCenterCentroids=cedar_center_centroids,
            SepCentroids=sep_centroids,
            FrameId=frame_id,
            ExposureQuality=exposure_quality,
            AlignmentProjection=make_projection(
                solution, last_solve_success, alignment_context
            ),
        ),
        alignment=AlignmentResult(
            x_target=solution.get("x_target"),
            y_target=solution.get("y_target"),
        ),
        matched_centroids=solution.get("matched_centroids"),
        matched_stars=solution.get("matched_stars"),
        matched_catID=solution.get("matched_catID"),
    )


def _build_failed_solve(
    last_solve_attempt: float,
    last_solve_success,
    t_extract_ms: float,
    centroid_count: int = 0,
    solve_path: str = "",
    cedar_raw_centroids: Optional[int] = None,
    cedar_gated_centroids: Optional[int] = None,
    cedar_center_centroids: Optional[int] = None,
    sep_centroids: Optional[int] = None,
    frame_id: Optional[int] = None,
    exposure_quality: Optional[dict[str, object]] = None,
) -> FailedSolve:
    """Build a :class:`FailedSolve` message for an attempt that produced
    no pointing. The integrator's long-lived estimate preserves the
    previous ``solve`` cells so IMU dead-reckoning continues.

    ``centroid_count`` defaults to 0 for the exception path, where the
    ``centroids`` list may be stale from a previous loop iteration."""
    return FailedSolve(
        last_solve_attempt=last_solve_attempt,
        last_solve_success=last_solve_success,
        diagnostics=SolveDiagnostics(
            Matches=0,
            Centroids=centroid_count,
            T_extract=t_extract_ms,
            solve_path=solve_path,
            CedarRawCentroids=cedar_raw_centroids,
            CedarGatedCentroids=cedar_gated_centroids,
            CedarCenterCentroids=cedar_center_centroids,
            SepCentroids=sep_centroids,
            FrameId=frame_id,
            ExposureQuality=exposure_quality,
        ),
    )


def _calibration_input_from_run(
    run,
    geometry,
    *,
    expected_frame_id,
    source,
    previous=None,
    minimum_candidates=1,
    central_crop=False,
):
    """Snapshot native detector coordinates from the current exposure only.

    A weak preprocessed frame must not replace a usable RAW observation.
    Calibration receives unrotated, undistorted sensor coordinates; fitting
    already corrected coordinates would bias the new optical model.
    """
    if (
        run is None
        or geometry is None
        or expected_frame_id is None
        or run.frame_id != expected_frame_id
    ):
        return previous
    points = np.asarray(run.detection.centroids, dtype=np.float64).reshape(-1, 2)
    if not len(points) or not np.isfinite(points).all():
        return previous
    count = (
        _count_in_crop(points, run.frame_hw, geometry["crop_width_px"])
        if central_crop
        else len(points)
    )
    if previous is not None and count < minimum_candidates:
        return previous
    return {
        "centroids": points.copy(),
        "frame_hw": run.frame_hw,
        "rotation_deg": geometry["rotation_deg"],
        "crop_width_px": geometry["crop_width_px"],
        "base_fov_degrees": geometry["base_fov_degrees"],
        "source": f"{source}_{run.detection.backend}",
        "frame_id": run.frame_id,
    }


def _make_async_preprocess_worker(runner):
    """Confine the clone's frame history to the lifetime of its worker."""

    def process(job):
        return runner.preprocess_frame(
            job["frame"],
            fingerprint=job["fingerprint"],
            frame_id=job["metadata"].get("frame_id"),
        )

    return LatestFrameWorker(
        process,
        thread_name="solver-preprocess",
        on_close=lambda: runner.close_preprocessor("inactive"),
    )


def _solve_preprocessed_run(
    t3,
    runner,
    run,
    shared_state,
    *,
    centroids,
    center_first,
    target_sky_coord=None,
    trace=None,
    path_prefix="preprocessed_",
):
    """Solve the detected frame once per distinct candidate subset.

    Keep the historic sep path labels for capture/acceptance compatibility;
    the detector backend is recorded separately and normally is MFDS.
    """
    minimum = runner.min_fallback_stars
    if len(centroids) < minimum:
        return {}, ""

    def solve(subset, path):
        return runner.solve(
            t3,
            run,
            shared_state,
            target_sky_coord=target_sky_coord,
            centroids_override=subset,
            solve_path=path,
        )

    stages = []
    center = _center_square_subset(centroids, run.frame_hw)
    if center_first and minimum <= len(center) < len(centroids):
        stages.append(
            (
                f"{path_prefix}sep_center",
                lambda: solve(center, f"{path_prefix}sep_center"),
            )
        )
    stages.append(
        (
            f"{path_prefix}sep_full",
            lambda: solve(centroids, f"{path_prefix}sep_full"),
        )
    )
    return _solve_center_first_remainder(stages, trace=trace)


def _solve_sep_emergency(
    t3,
    runner,
    shared_state,
    *,
    primary_solution,
    raw_entry,
    preprocessed_run,
    expected_frame_id,
    moving,
    center_first,
    primary_paths_complete=True,
    target_sky_coord=None,
    filter_centroids=None,
    trace=None,
):
    """Last-resort SEP after MFDS paths fail, on this exposure only.

    A valid MFDS candidate awaiting continuity confirmation is not a failure.
    Recovery still passes the ordinary quality and downstream continuity gates.
    """
    if runner is None or not runner.emergency_should_attempt(
        primary_solved=bool(
            primary_solution and primary_solution.get("RA") is not None
        ),
        moving=moving or not primary_paths_complete,
    ):
        return {}, "", None
    try:
        age = time.time() - float((raw_entry or {}).get("timestamp") or 0)
    except (TypeError, ValueError):
        return {}, "", None
    if (
        expected_frame_id is None
        or not raw_entry
        or "frame" not in raw_entry
        or raw_entry.get("frame_id") != expected_frame_id
        or not 0 <= age <= MAX_FRAME_AGE_S
    ):
        return {}, "", None

    # One extra search budget shared by preprocessed and RAW SEP retries.
    # Repeated empty-sky failures back off before invoking SEP extraction.
    logger.debug("SEP emergency retry after MFDS failure, frame %s", expected_frame_id)
    try:
        with tetra3.search_budget(1000):
            for preprocessed in (True, False):
                if tetra3.search_budget_expired():
                    break
                if preprocessed:
                    if (
                        preprocessed_run is None
                        or preprocessed_run.frame_id != expected_frame_id
                    ):
                        continue
                    run = runner.detect_emergency_preprocessed(preprocessed_run)
                else:
                    run = runner.detect(
                        shared_state,
                        expected_frame_id=expected_frame_id,
                        raw_entry=raw_entry,
                        emergency=True,
                    )
                if run is None:
                    continue
                cents = run.detection.centroids
                if filter_centroids is not None:
                    cents = filter_centroids(cents, run.frame_hw)
                if preprocessed:
                    runner.use_preprocessed_overlay(run)
                solution, path = _solve_preprocessed_run(
                    t3,
                    runner,
                    run,
                    shared_state,
                    centroids=cents,
                    center_first=center_first,
                    target_sky_coord=target_sky_coord,
                    trace=trace,
                    path_prefix="preprocessed_" if preprocessed else "",
                )
                if path:
                    runner.record_emergency_result(True)
                    logger.debug(
                        "SEP emergency solved frame %s via %s", expected_frame_id, path
                    )
                    return solution, path, run
    except Exception:
        logger.exception("SEP emergency recovery failed")
    runner.record_emergency_result(False)
    return {}, "", None


def _fullframe_geometry(
    cfg,
    camera_type,
    base_fov_degrees: float = sfm.SOLVER_FOV_DEG,
    lens_key: str = "",
):
    """Context for native full-frame detection, or None until resolvable.

    Same sources as SepShadowRunner.create_if_enabled: the camera profile
    for the production crop width and saturation level, the display config
    for the stage-5 rotation, plus the warm-pixel map and screen direction
    for the detection gates / horizon mask. Camera type is published after
    the camera process boots, so resolution is retried from the loop until
    it succeeds."""
    try:
        if not camera_type:
            return None
        profile = get_camera_profile(camera_type)
        crop_width = int(profile.raw_size[0] - profile.crop_x[0] - profile.crop_x[1])
        rotation = sfm.stage5_rotation_deg(
            cfg.get_option("screen_direction"),
            cfg.get_option("camera_rotation"),
        )
        warm_map = None
        try:
            if WARM_MAP_PATH.exists():
                warm_map = np.asarray(np.load(WARM_MAP_PATH), dtype=np.int32)
        except Exception:
            logger.exception("Warm-pixel map load failed; FF gates run unmasked")
        calibration = CalibrationProfileStore(cfg).load_active(
            camera_type,
            str(lens_key or ""),
            profile,
        )
        return {
            "rotation_deg": rotation,
            "crop_width_px": crop_width,
            "saturation_level": float(2**profile.bit_depth - 1),
            "warm_map": warm_map,
            "screen_direction": cfg.get_option("screen_direction"),
            "base_fov_degrees": base_fov_degrees,
            "distortion_coefficients": active_coefficients(calibration),
        }
    except Exception:
        logger.exception("full-frame geometry unavailable")
        return None


def _center_square_subset(centroids, frame_hw):
    """Centroids inside the largest centred square of the frame.

    The centre-first cascade (user design 2026-08-04) solves this subset
    before the full set: near the frame centre optical distortion is
    lowest (offline A/B: RMSE 24 -> 13 arcsec on the dark-sky corpus)
    and edge junk that survives the gates is excluded. Selection happens
    on coordinates -- the frame itself is never re-processed."""
    pts = np.asarray(centroids, dtype=np.float64)
    if pts.ndim != 2 or len(pts) == 0:
        return pts.reshape(0, 2)
    h, w = float(frame_hw[0]), float(frame_hw[1])
    side = min(h, w)
    y0, x0 = (h - side) / 2.0, (w - side) / 2.0
    keep = (
        (pts[:, 0] >= y0)
        & (pts[:, 0] < y0 + side)
        & (pts[:, 1] >= x0)
        & (pts[:, 1] < x0 + side)
    )
    return pts[keep]


def _solve_center_first_remainder(stages, trace=None, budget_ms=2600):
    """Run the remaining cascade in global centre-first order.

    Candidate subsets are supplied in centre-first order. A stage callback
    may return an empty dict when it is unavailable or fails quality checks.
    """
    with tetra3.search_budget(budget_ms):
        last_solution = {}
        for solve_path, solve_stage in stages:
            if tetra3.search_budget_expired():
                if trace is not None:
                    trace.append(
                        {"path": solve_path, "skipped": "search_budget_expired"}
                    )
                break
            started_ns = time.monotonic_ns() if trace is not None else 0
            last_solution = solve_stage() or {}
            if trace is not None:
                trace.append(
                    {
                        "path": solve_path,
                        "elapsed_ms": (time.monotonic_ns() - started_ns) / 1e6,
                        "quality_solved": last_solution.get("RA") is not None,
                    }
                )
            if last_solution.get("RA") is not None:
                return last_solution, solve_path
        return last_solution, ""


def _count_in_crop(centroids, frame_hw, crop_width_px: int) -> int:
    """Detections inside the (centred) production crop window.

    Published as SolveDiagnostics.Centroids on the full-frame path for legacy
    diagnostics and as the Auto(Star) fallback when full-frame per-detector
    counts are unavailable."""
    if centroids is None or len(centroids) == 0:
        return 0
    arr = np.asarray(centroids, dtype=np.float64)
    height, width = float(frame_hw[0]), float(frame_hw[1])
    y0 = max(0.0, (height - crop_width_px) / 2.0)
    x0 = max(0.0, (width - crop_width_px) / 2.0)
    inside = (
        (arr[:, 0] >= y0)
        & (arr[:, 0] < y0 + crop_width_px)
        & (arr[:, 1] >= x0)
        & (arr[:, 1] < x0 + crop_width_px)
    )
    return int(np.count_nonzero(inside))


def solver(
    shared_state,
    solver_queue,
    camera_image,
    console_queue,
    log_queue,
    align_command_queue,
    align_result_queue,
    camera_command_queue,
    is_debug=False,
    max_imu_ang_during_exposure=1.0,  # Max allowed turn during exp [degrees]
):
    MultiprocLogging.configurer(log_queue)
    logger.debug("Starting Solver")
    t3 = tetra3.Tetra3(str(utils.tetra3_dir / "data" / "default_database.npz"))
    distortion_calibration_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="distortion-calibration"
    )
    distortion_calibration_t3 = None
    distortion_calibration_future = None

    def _measure_distortion_task(request_id, payload):
        nonlocal distortion_calibration_t3
        if distortion_calibration_t3 is None:
            distortion_calibration_t3 = tetra3.Tetra3(
                str(utils.tetra3_dir / "data" / "default_database.npz")
            )
        observation = measure_distortion_frame(
            distortion_calibration_t3,
            payload["centroids"],
            payload["frame_hw"],
            rotation_deg=payload["rotation_deg"],
            crop_width_px=payload["crop_width_px"],
            base_fov_degrees=payload["base_fov_degrees"],
        )
        return request_id, payload["source"], observation

    def _measure_lens_task(request_id, payload, camera_type):
        nonlocal distortion_calibration_t3
        if distortion_calibration_t3 is None:
            distortion_calibration_t3 = tetra3.Tetra3(
                str(utils.tetra3_dir / "data" / "default_database.npz")
            )
        return request_id, measure_lens_frame(
            distortion_calibration_t3, payload, camera_type
        )

    lens_measurement = LensMeasurement(
        config_mod.Config(),
        shared_state,
        lambda request_id, payload, camera_type: distortion_calibration_executor.submit(
            _measure_lens_task, request_id, payload, camera_type
        ),
    )

    align_ra = 0
    align_dec = 0
    last_solve_attempt: float = 0.0
    last_solve_success = None  # exposure_end of most recent successful solve
    solve_continuity = SolveContinuityGate()
    post_motion_raw_fast_frames = 0
    preprocessed_fast_trusted = False
    async_preprocess_worker = None
    async_preprocess_runner = None
    async_preprocess_generation = 0
    preprocess_target_pixel = None
    async_motion_seen = False
    async_preprocess_mode_active = False
    preprocess_bias = PreprocessBiasTracker(
        max_agreement_deg=0.12,
        required_samples=2,
        alpha=0.25,
    )

    centroids = []
    # Failed pattern matches log once per streak (same idiom as the
    # no-stars message): under an unsolvable sky the per-attempt WARNING
    # was 93% of the whole log (5,011 lines in one evening, 2026-08-04).
    solve_fail_streak = 0

    # SQM calculator is created lazily on the first radiometer sample (or
    # solve), not here: at solver startup shared_state.camera_type() still
    # holds the pre-camera default, and a calculator built from it would
    # photometer with the wrong sensor profile (pedestal etc.). The camera
    # process records the real type before it captures its first frame, and a
    # solve requires a captured frame, so first real-frame use is guaranteed
    # to see the real camera type.
    sqm_calculator = None
    # Rolling aperture (wing-loss) correction, fed by bright matched stars
    sqm_wing_estimator = WingEstimator()
    # Cloud/dew estimator and black-level tracker are created with the
    # calculator (below) so they get the real sensor's profile seeds; the
    # camera type is not yet known here.
    sqm_cloud_estimator = None
    sqm_black_level = None
    sqm_radiometer = RadiometerAccumulator()
    sqm_optical_train = OpticalTrainResolver()
    last_stellar_diagnostic = 0.0

    # Full-frame MFDS runner (historical SepShadowRunner name). Needs
    # the camera type for crop geometry, which the camera process publishes
    # after startup -- so creation is retried in the loop until it works.
    _sep_cfg = config_mod.Config()
    configure_runtime_detection()
    sep_emergency_enabled = bool(_sep_cfg.get_option("solver_sep_emergency", True))
    logger.info(
        "Live detection: MFDS only; final SEP emergency=%s", sep_emergency_enabled
    )
    field_capture = CaptureRecorder("solver", _sep_cfg, shared_state=shared_state)
    sep_shadow = None
    sep_shadow_wanted = True
    # Optical-train FOV gating is deliberately opt-in for the first field
    # phase. It applies only to the ordinary 512 path below; full-frame
    # MFDS/SEP have their own crop/canvas validation stage.
    optics_fov_gate_wanted = bool(_sep_cfg.get_option("solver_optics_fov_gate"))
    if optics_fov_gate_wanted:
        logger.info("Optical-train FOV gate enabled for the 512 solver path")
    optics_fullframe_fov_wanted = bool(
        _sep_cfg.get_option("solver_optics_fullframe_fov")
    )
    if optics_fullframe_fov_wanted:
        logger.info("Optical-train FOV enabled for MFDS/SEP full-frame paths")
    # Native RAW geometry is required by MFDS detection and preprocessing.
    auto_star_framewise_wanted = bool(_sep_cfg.get_option("camera_auto_star_framewise"))
    fullframe_geometry = None  # context dict, resolved lazily
    cached_fullframe_geometry_key = None
    distortion_calibration_session = None
    # Detection gates belong to star_detect; the optional IMU mask is applied
    # to preprocessed solve candidates below.
    horizon_mask_wanted = bool(_sep_cfg.get_option("solver_horizon_mask"))
    # Centre-first cascade (user design 2026-08-04): solve the centred-square
    # coordinate subset first, full set on failure, using one detection.
    center_first_wanted = bool(_sep_cfg.get_option("solver_center_first"))
    timing_debug_wanted = bool(_sep_cfg.get_option("solver_timing_debug", False))
    skip_slow_raw_fallbacks_wanted = bool(
        _sep_cfg.get_option("solver_preprocess_skip_slow_raw_fallbacks", False)
    )
    scheduling_mode = os.environ.get("MFNAVIS_PREPROCESS_MODE") or _sep_cfg.get_option(
        "solver_preprocess_mode"
    )
    if scheduling_mode is None:
        scheduling_mode = (
            "auto" if _sep_cfg.get_option("solver_preprocess_async", False) else "sync"
        )
    if scheduling_mode not in {"auto", "sync"}:
        logger.warning("Invalid preprocessing mode %r; using auto", scheduling_mode)
        scheduling_mode = "auto"
    solve_scheduling = SolverSchedulingPolicy(scheduling_mode)
    logger.info("Solver preprocessing scheduling: %s", scheduling_mode)
    logger.info(
        "MFDS full-frame path enabled (horizon_mask=%s, center_first=%s)",
        horizon_mask_wanted,
        center_first_wanted,
    )

    while True:
        logger.info("Starting Solver Loop")
        # Normal extraction is MFDS-only; SEP is the final recovery stage.
        try:
            while True:
                # Drain any pending command queue messages.
                while True:
                    try:
                        command = align_command_queue.get(block=False)
                    except queue.Empty:
                        break

                    if isinstance(command, AlignOnRaDec):
                        logger.debug("Align Command Received: %s", command)
                        align_ra = command.ra
                        align_dec = command.dec
                    elif isinstance(command, AlignCancel):
                        align_ra = 0
                        align_dec = 0
                    elif isinstance(command, ReloadSqmCalibration):
                        # Invalidate; the next solve recreates the calculator
                        # with fresh calibration (single creation site).
                        logger.info("Reloading SQM calibration...")
                        sqm_calculator = None
                        sqm_wing_estimator.reset()
                        # Cloud estimator and black-level tracker are recreated
                        # from the fresh profile on the next solve; drop them
                        # here so stale seeds/history cannot carry over.
                        sqm_cloud_estimator = None
                        sqm_black_level = None
                        sqm_radiometer.reset()
                        last_stellar_diagnostic = 0.0
                    elif isinstance(command, StartLensMeasurement):
                        distortion_calibration_session = None
                        shared_state.set_distortion_calibration_status(
                            {"state": "cancelled"}
                        )
                        lens_measurement.start(command)
                    elif isinstance(command, CancelLensMeasurement):
                        lens_measurement.cancel(command.request_id)
                    elif isinstance(command, StartDistortionCalibration):
                        if lens_measurement.active:
                            lens_measurement.cancel()
                        current_camera = str(shared_state.camera_type() or "")
                        current_lens = calibration_lens_key(
                            str(
                                getattr(shared_state, "camera_lens", lambda: "")() or ""
                            ),
                            manual_focal_from_state(shared_state),
                        )
                        if (
                            command.camera_type != current_camera
                            or command.lens_key != current_lens
                        ):
                            shared_state.set_distortion_calibration_status(
                                {
                                    "state": "error",
                                    "request_id": command.request_id,
                                    "accepted_frames": 0,
                                    "required_frames": 5,
                                    "last_reason": "camera_or_lens_changed",
                                }
                            )
                            distortion_calibration_session = None
                        else:
                            distortion_calibration_session = (
                                DistortionCalibrationSession(
                                    current_camera,
                                    current_lens,
                                    command.request_id,
                                )
                            )
                            shared_state.set_distortion_calibration_status(
                                distortion_calibration_session.status()
                            )
                            logger.info(
                                "Distortion calibration armed for %s/%s",
                                current_camera,
                                current_lens,
                            )
                    elif isinstance(command, CancelDistortionCalibration):
                        if (
                            distortion_calibration_session is None
                            or command.request_id is None
                            or command.request_id
                            == distortion_calibration_session.request_id
                        ):
                            distortion_calibration_session = None
                            shared_state.set_distortion_calibration_status(
                                {
                                    "state": "cancelled",
                                    "accepted_frames": 0,
                                    "required_frames": 5,
                                }
                            )
                            logger.info("Distortion calibration cancelled")
                    else:
                        logger.warning(
                            "Unknown solver command (type=%s): %r",
                            type(command).__name__,
                            command,
                        )

                state_utils.sleep_for_framerate(shared_state)
                field_capture.poll()

                # use the time the exposure started here to
                # reject images started before the last solve
                # which might be from the IMU
                solver_frame_entry = None
                solver_raw_entry = None
                try:
                    solver_frame_getter = getattr(shared_state, "solver_frame", None)
                    if callable(solver_frame_getter):
                        solver_frame_entry, solver_raw_entry = (
                            _read_matching_solver_inputs(shared_state)
                        )
                    if solver_frame_entry is not None:
                        last_image_metadata = solver_frame_entry["metadata"]
                    else:
                        # Backwards-compatible path for debug/test shared-state
                        # implementations that do not publish an atomic frame.
                        last_image_metadata = shared_state.last_image_metadata()
                except (BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Lost connection to shared state manager: {e}")
                    continue

                # An incomplete pair is not a failed plate solve. Wait for
                # a complete exposure without consuming its frame timestamp.
                if solver_frame_entry is not None and solver_raw_entry is None:
                    logger.debug("Waiting for matching RAW/512 solver inputs")
                    continue

                # Check if we should process this image
                capture_input_ready_ns = time.monotonic_ns()
                is_new_image = last_image_metadata["exposure_end"] > last_solve_attempt

                if not is_new_image:
                    continue

                # Every camera frame already carries a tiny radiometer sample
                # reduced in the camera process. Collect all of them and publish
                # at most once per second for CPU/battery stability.
                try:
                    radiometer_sample = shared_state.sqm_radiometer_sample()
                except (BrokenPipeError, ConnectionResetError, AttributeError):
                    radiometer_sample = None
                if radiometer_sample is not None and sqm_calculator is None:
                    sqm_calculator = create_sqm_calculator(shared_state)
                    sqm_wing_estimator.reset()
                    profile = sqm_calculator.profile
                    sqm_cloud_estimator = CloudEstimator(
                        clear_zero_point=profile.clear_zero_point,
                        clear_sky_brightness=profile.clear_sky_brightness,
                    )
                    sqm_black_level = BlackLevelTracker(profile.bias_offset)
                if sqm_calculator is not None:
                    try:
                        lens_getter = getattr(shared_state, "camera_lens", lambda: None)
                        radiometric_fov = sqm_optical_train.resolve(
                            shared_state.camera_type(),
                            lens_getter(),
                            manual_focal_from_state(shared_state),
                        ).fov_degrees
                    except (BrokenPipeError, ConnectionResetError):
                        radiometric_fov = None
                    update_radiometric_sqm(
                        shared_state,
                        sqm_calculator,
                        sqm_radiometer,
                        radiometer_sample,
                        calculation_interval_seconds=SQM_CALCULATION_INTERVAL_SECONDS,
                        black_level_tracker=sqm_black_level,
                        field_width_degrees=radiometric_fov,
                    )

                capture_token = None
                try:
                    if solver_frame_entry is not None:
                        np_image = np.asarray(
                            solver_frame_entry["image"], dtype=np.uint8
                        )
                    else:
                        img = camera_image.copy()
                        img = img.convert(mode="L")
                        np_image = np.asarray(img, dtype=np.uint8)

                    capture_token = field_capture.begin(last_image_metadata)
                    capture_candidate = None
                    capture_continuity = None
                    capture_stages = [] if capture_token is not None else None
                    capture_counts = {}
                    preprocess_ms = 0.0
                    preprocess_context = None
                    # Results carry full-size frame/evidence arrays. Do not
                    # retain the last async result during sync/disabled mode.
                    completed_preprocess = None
                    preprocessed_run = None

                    # Mark that we're attempting a solve - use image exposure_end timestamp.
                    # This is more accurate than wall clock and ties the attempt to the
                    # actual image so the integrator can dedupe.
                    last_solve_attempt = last_image_metadata["exposure_end"]

                    solver_preprocess_enabled = _solver_preprocess_enabled(shared_state)
                    target_pixel_key = tuple(shared_state.target_pixel())
                    if target_pixel_key != preprocess_target_pixel:
                        preprocess_target_pixel = target_pixel_key
                        async_preprocess_generation += 1
                        preprocess_bias.reset()
                        solve_scheduling.reset("target_pixel_changed")
                        if async_preprocess_worker is not None:
                            async_preprocess_worker.clear_pending()
                    imu_sample = last_image_metadata.get("imu")
                    frame_moving = bool(getattr(imu_sample, "moving", False))
                    try:
                        frame_moving = (
                            frame_moving
                            or abs(float(last_image_metadata.get("imu_delta") or 0.0))
                            > 0.1
                        )
                    except (TypeError, ValueError):
                        frame_moving = True
                    frame_moving = frame_moving or _mount_motion_active()
                    if frame_moving:
                        if not async_motion_seen:
                            async_preprocess_generation += 1
                            preprocess_bias.reset()
                            solve_scheduling.reset("moving")
                            if async_preprocess_worker is not None:
                                async_preprocess_worker.close(wait=False)
                                async_preprocess_worker = None
                                async_preprocess_runner = None
                        async_motion_seen = True
                    else:
                        async_motion_seen = False

                    fullframe_base_fov = (
                        _optical_crop_fov(shared_state)
                        if optics_fullframe_fov_wanted
                        else sfm.SOLVER_FOV_DEG
                    )
                    fullframe_geometry_key = _fullframe_optics_key(
                        shared_state,
                        fullframe_base_fov,
                        _active_calibration_id(_sep_cfg, shared_state),
                    )
                    if fullframe_geometry_key != cached_fullframe_geometry_key:
                        if cached_fullframe_geometry_key is not None:
                            logger.info(
                                "Lens/optics changed; rebuilding full-frame solver geometry "
                                "(%s -> %s)",
                                cached_fullframe_geometry_key,
                                fullframe_geometry_key,
                            )
                        fullframe_geometry = None
                        cached_fullframe_geometry_key = fullframe_geometry_key
                        preprocessed_fast_trusted = False
                        preprocess_bias.reset()
                        solve_scheduling.reset("optics_changed")
                        if async_preprocess_worker is not None:
                            async_preprocess_worker.close(wait=False)
                            async_preprocess_worker = None
                            async_preprocess_runner = None
                        # The runner has cached the old base FOV too.  It is
                        # cheap and safe to recreate on the following use.
                        if sep_shadow is not None:
                            sep_shadow.close_preprocessor("optics_changed")
                        sep_shadow = None

                    if fullframe_geometry is None:
                        fullframe_geometry = _fullframe_geometry(
                            _sep_cfg,
                            shared_state.camera_type(),
                            fullframe_base_fov,
                            getattr(shared_state, "camera_lens", lambda: "")(),
                        )

                    t0 = precision_timestamp()
                    with tetra3.search_budget(3000):
                        used_fullframe = False
                        ff_frame = None
                        ff_frame_hw = None
                        cedar_raw_count = None
                        cedar_gated_count = None
                        cedar_center_count = None
                        sep_count = None
                        emergency_preprocessed_run = None
                        ff_entry = None
                        prefer_preprocessed_fast = False
                        # Read the same fresh RAW exposure for SEP and preprocessing.
                        centroids = np.empty((0, 2), dtype=np.float64)
                        if fullframe_geometry is not None:
                            ff_entry = solver_raw_entry
                            if ff_entry is None and solver_frame_entry is None:
                                ff_entry = shared_state.solver_raw()
                            if (
                                not ff_entry
                                or "frame" not in ff_entry
                                or time.time() - float(ff_entry.get("timestamp") or 0)
                                > MAX_FRAME_AGE_S
                                or (
                                    last_image_metadata.get("frame_id") is not None
                                    and ff_entry.get("frame_id")
                                    != last_image_metadata.get("frame_id")
                                )
                            ):
                                # No fresh raw: fall back to the 512 path for
                                # this attempt rather than skipping it.
                                ff_entry = None
                            if ff_entry is not None:
                                ff_frame = np.asarray(ff_entry["frame"])
                                ff_frame_hw = (
                                    int(ff_frame.shape[0]),
                                    int(ff_frame.shape[1]),
                                )
                        prefer_preprocessed_fast = _preprocessed_fast_path_allowed(
                            enabled=solver_preprocess_enabled
                            and skip_slow_raw_fallbacks_wanted,
                            trusted=preprocessed_fast_trusted,
                            moving=frame_moving,
                            aligning=align_ra != 0 and align_dec != 0,
                            scheduling_mode=scheduling_mode,
                        )
                        t_extract = (precision_timestamp() - t0) * 1000

                        logger.debug(
                            "File %s, extracted %d centroids in %.2fms"
                            % ("camera", len(centroids), t_extract)
                        )

                        solution: dict = {}
                        ff_matched_for_overlay = None
                        ff_in_crop_count = 0
                        if used_fullframe:
                            ff_in_crop_count = _count_in_crop(
                                centroids,
                                ff_frame_hw,
                                fullframe_geometry["crop_width_px"],
                            )

                        solve_path = "sep_full"

                        capture_sep_started_ns = (
                            time.monotonic_ns() if capture_token is not None else 0
                        )
                        capture_primary_extract_ms = t_extract

                        # Detect once per RAW attempt through the MFDS-first runner.
                        if sep_shadow is None and (
                            sep_shadow_wanted or solver_preprocess_enabled
                        ):
                            sep_shadow = SepShadowRunner.create_if_enabled(
                                _sep_cfg,
                                shared_state.camera_type(),
                                fullframe_base_fov,
                                getattr(shared_state, "camera_lens", lambda: "")(),
                                force_create=solver_preprocess_enabled,
                            )
                        sep_run = None
                        sep_fallback_used = False
                        exposure_quality = None
                        distortion_calibration_input = None
                        sep_can_solve = False
                        if capture_token is not None:
                            capture_counts["raw_sep"] = 0
                        if sep_shadow is not None and sep_shadow_wanted:
                            sep_run = sep_shadow.detect(
                                shared_state,
                                expected_frame_id=last_image_metadata.get("frame_id"),
                                raw_entry=solver_raw_entry,
                            )
                            if sep_run is not None:
                                sep_count = len(sep_run.detection.centroids)
                                if capture_token is not None:
                                    # Snapshot before a synchronous preprocessed
                                    # solve replaces sep_run and its candidate count.
                                    capture_counts["raw_sep"] = sep_count
                                if (
                                    (
                                        distortion_calibration_session is not None
                                        or lens_measurement.active
                                    )
                                    and not frame_moving
                                    and fullframe_geometry is not None
                                ):
                                    distortion_calibration_input = (
                                        _calibration_input_from_run(
                                            sep_run,
                                            fullframe_geometry,
                                            expected_frame_id=last_image_metadata.get(
                                                "frame_id"
                                            ),
                                            source="raw",
                                        )
                                    )
                            sep_can_solve = bool(
                                sep_run is not None
                                and sep_shadow.fallback_enabled
                                and (not solution or solution.get("RA") is None)
                                and len(sep_run.detection.centroids)
                                >= sep_shadow.min_fallback_stars
                                # Backoff: persistently unsolvable scenes
                                # (indoors, thick cloud) otherwise burn up to
                                # solve_timeout per attempt, starving the whole
                                # solver loop. Re-arms instantly on a SEP count
                                # jump (cloud gap opening on stars).
                                and sep_shadow.fallback_should_attempt(
                                    len(sep_run.detection.centroids)
                                )
                            )

                        capture_sep_wait_ms = (
                            (time.monotonic_ns() - capture_sep_started_ns) / 1e6
                            if capture_token is not None
                            else 0.0
                        )

                        # Preserve centre saturation feedback for Auto(Star).
                        center_contaminated_for_ae = False
                        if (
                            auto_star_framewise_wanted
                            and used_fullframe
                            and ff_frame is not None
                        ):
                            profile = get_camera_profile(shared_state.camera_type())
                            center_height = ff_frame.shape[0] // 3
                            center_width = ff_frame.shape[1] // 3
                            center_y = (ff_frame.shape[0] - center_height) // 2
                            center_x = (ff_frame.shape[1] - center_width) // 2
                            center_sparse = ff_frame[
                                center_y : center_y + center_height : 8,
                                center_x : center_x + center_width : 8,
                            ]
                            center_contaminated_for_ae = bool(
                                center_sparse.size
                                and np.percentile(center_sparse, 99.9)
                                >= 0.85 * (2**profile.bit_depth - 1)
                            )

                        if (
                            center_first_wanted
                            and not prefer_preprocessed_fast
                            and (not solution or solution.get("RA") is None)
                        ):
                            # Try the central subset before allowing the detector
                            # to use edge coordinates.
                            # This keeps optical distortion, horizon glow and
                            # obstructions out of the solve whenever the centre is
                            # sufficient.
                            _sep_target_sky = (
                                [[align_ra, align_dec]]
                                if align_ra != 0 and align_dec != 0
                                else None
                            )
                            sep_subset = None
                            if sep_can_solve:
                                sep_subset = _center_square_subset(
                                    sep_run.detection.centroids,
                                    sep_run.frame_hw,
                                )
                            sep_attempted = [False]

                            def _sep_center_stage():
                                if not (
                                    sep_can_solve
                                    and 4
                                    <= len(sep_subset)
                                    < len(sep_run.detection.centroids)
                                ):
                                    return {}
                                sep_attempted[0] = True
                                return sep_shadow.solve(
                                    t3,
                                    sep_run,
                                    shared_state,
                                    target_sky_coord=_sep_target_sky,
                                    centroids_override=sep_subset,
                                    solve_path="sep_center",
                                )

                            def _sep_full_stage():
                                if not sep_can_solve:
                                    return {}
                                sep_attempted[0] = True
                                return sep_shadow.solve(
                                    t3,
                                    sep_run,
                                    shared_state,
                                    target_sky_coord=_sep_target_sky,
                                )

                            solution, selected_path = _solve_center_first_remainder(
                                (
                                    ("sep_center", _sep_center_stage),
                                    ("sep_full", _sep_full_stage),
                                ),
                                trace=capture_stages,
                            )
                            if selected_path:
                                solve_path = selected_path
                                sep_fallback_used = selected_path.startswith("sep")
                            if sep_attempted[0]:
                                sep_shadow.record_fallback_result(
                                    sep_fallback_used,
                                    len(sep_run.detection.centroids),
                                )
                        elif sep_can_solve and not prefer_preprocessed_fast:
                            # Non-centre mode solves the full candidate set once.
                            solution = sep_shadow.solve(
                                t3,
                                sep_run,
                                shared_state,
                                target_sky_coord=(
                                    [[align_ra, align_dec]]
                                    if align_ra != 0 and align_dec != 0
                                    else None
                                ),
                            )
                            sep_fallback_used = bool(
                                solution and solution.get("RA") is not None
                            )
                            sep_shadow.record_fallback_result(
                                sep_fallback_used,
                                len(sep_run.detection.centroids),
                            )
                            if sep_fallback_used:
                                solve_path = "sep_full"

                    raw_cascade_ms = (precision_timestamp() - t0) * 1000.0
                    raw_solution_diagnostic = None
                    if solution and solution.get("RA") is not None:
                        raw_solution_diagnostic = {
                            "ra": float(solution["RA"]),
                            "dec": float(solution["Dec"]),
                            "path": solve_path,
                            "matches": int(solution.get("Matches") or 0),
                            "rmse": solution.get("RMSE"),
                        }

                    # Production star-only path controlled from LiveCam. The
                    # raw cascade remains available while the temporal window
                    # warms and as a fallback, but once preprocessing produces
                    # a valid solve it is preferred. The exact frame and its
                    # warm/reset/error state are cached for LiveCam; selecting
                    # that view never starts a second accumulator.
                    fast_raw_after_motion = False
                    if not solver_preprocess_enabled:
                        preprocessed_fast_trusted = False
                        preprocess_bias.reset()
                        solve_scheduling.reset("disabled")
                        if async_preprocess_mode_active:
                            async_preprocess_generation += 1
                            async_preprocess_mode_active = False
                        if async_preprocess_worker is not None:
                            async_preprocess_worker.close(wait=False)
                            async_preprocess_worker = None
                            async_preprocess_runner = None
                        if sep_shadow is not None:
                            sep_shadow.reset_preprocessor("disabled")
                        _publish_solver_preprocess_status(
                            shared_state,
                            enabled=False,
                            state="disabled",
                            frame_id=last_image_metadata.get("frame_id"),
                            clear_frame=True,
                        )
                    elif (
                        solver_preprocess_enabled
                        and sep_shadow is not None
                        and ff_frame is not None
                    ):
                        raw_solved = bool(solution and solution.get("RA") is not None)
                        (
                            fast_raw_after_motion,
                            post_motion_raw_fast_frames,
                        ) = _post_motion_raw_fast_path(
                            frame_moving=frame_moving,
                            raw_solved=raw_solved,
                            remaining=post_motion_raw_fast_frames,
                        )
                        if frame_moving:
                            preprocessed_fast_trusted = False
                            sep_shadow.reset_preprocessor("reset_moving")
                            _publish_solver_preprocess_status(
                                shared_state,
                                enabled=True,
                                state="reset_moving",
                                frame_id=last_image_metadata.get("frame_id"),
                                reset_reason="moving",
                                clear_frame=True,
                            )
                        elif fast_raw_after_motion:
                            _publish_solver_preprocess_status(
                                shared_state,
                                enabled=True,
                                state="fast_raw_after_motion",
                                frame_id=last_image_metadata.get("frame_id"),
                                reset_reason="moving",
                                clear_frame=True,
                            )
                            logger.info(
                                "Post-motion fast RAW solve frame %s; "
                                "preprocessing resumes after %d more fast frame(s)",
                                last_image_metadata.get("frame_id"),
                                post_motion_raw_fast_frames,
                            )
                        else:
                            lens_key = getattr(
                                shared_state, "camera_lens", lambda: ""
                            )()
                            calibration_key = tuple(
                                sorted(
                                    (
                                        fullframe_geometry["distortion_coefficients"]
                                        or {}
                                    ).items()
                                )
                            )
                            camera_type = shared_state.camera_type()
                            preprocess_fingerprint = preprocess_geometry_fingerprint(
                                camera_type=camera_type,
                                pixel_format=get_camera_profile(camera_type).format,
                                lens_key=str(lens_key or ""),
                                manual_focal=manual_focal_from_state(shared_state),
                                frame_shape=tuple(ff_frame.shape),
                                rotation_deg=fullframe_geometry["rotation_deg"],
                                calibration_key=calibration_key,
                            )
                            preprocess_started = precision_timestamp()
                            forced_sync = bool(
                                align_ra != 0
                                or align_dec != 0
                                or distortion_calibration_session is not None
                                or lens_measurement.active
                            )
                            execution = solve_scheduling.choose(
                                raw_solved=raw_solved, forced_sync=forced_sync
                            )
                            async_preprocess_active = execution == "async"
                            if forced_sync:
                                preprocess_bias.reset()
                            if async_preprocess_active != async_preprocess_mode_active:
                                async_preprocess_generation += 1
                                if async_preprocess_worker is not None:
                                    async_preprocess_worker.close(wait=False)
                                    async_preprocess_worker = None
                                    async_preprocess_runner = None
                                if not async_preprocess_active:
                                    # The synchronous accumulator has not seen
                                    # intervening frames during background mode.
                                    sep_shadow.reset_preprocessor("sync_recovery")
                                else:
                                    # This history is stale on returning to sync
                                    # mode. Release it as the clone takes over.
                                    sep_shadow.reset_preprocessor("async_mode")
                                logger.info(
                                    "Solver scheduling -> %s: %s (raw streak=%d)",
                                    execution,
                                    solve_scheduling.reason,
                                    solve_scheduling.raw_success_streak,
                                )
                                async_preprocess_mode_active = async_preprocess_active
                            preprocess_context = None
                            if async_preprocess_active:
                                if async_preprocess_worker is None:
                                    async_preprocess_runner = (
                                        sep_shadow.preprocessing_clone()
                                    )
                                    async_preprocess_worker = (
                                        _make_async_preprocess_worker(
                                            async_preprocess_runner
                                        )
                                    )
                                    logger.info(
                                        "Asynchronous latest-frame preprocessing enabled"
                                    )

                                completed_preprocess = async_preprocess_worker.exchange(
                                    {
                                        "frame": ff_frame,
                                        "metadata": dict(last_image_metadata),
                                        "fingerprint": (
                                            preprocess_fingerprint,
                                            async_preprocess_generation,
                                        ),
                                        "generation": async_preprocess_generation,
                                        "raw_solution": _solution_coordinate_snapshot(
                                            solution
                                        ),
                                        "imu_sample": imu_sample,
                                    }
                                )
                                if (
                                    completed_preprocess is not None
                                    and completed_preprocess.error is None
                                    and completed_preprocess.is_fresh()
                                    and completed_preprocess.item["generation"]
                                    == async_preprocess_generation
                                ):
                                    preprocessed_run = completed_preprocess.value
                                    preprocess_context = completed_preprocess.item
                                    preprocess_ms = completed_preprocess.elapsed_ms
                                else:
                                    preprocessed_run = None
                                    preprocess_ms = 0.0
                                    if (
                                        completed_preprocess is not None
                                        and completed_preprocess.error is not None
                                    ):
                                        logger.error(
                                            "Asynchronous preprocessing failed: %s",
                                            completed_preprocess.error,
                                        )
                            else:
                                preprocessed_run = sep_shadow.preprocess_frame(
                                    ff_frame,
                                    fingerprint=preprocess_fingerprint,
                                    frame_id=last_image_metadata.get("frame_id"),
                                )
                                preprocess_ms = (
                                    precision_timestamp() - preprocess_started
                                ) * 1000.0
                            # Background wall time is diagnostic only. Adding
                            # it to the foreground extraction duration would
                            # falsely report a long solve even though RAW
                            # solving continued every camera frame.
                            if not async_preprocess_active:
                                t_extract += preprocess_ms
                            if preprocessed_run is not None:
                                if not async_preprocess_active:
                                    emergency_preprocessed_run = preprocessed_run
                                preprocess_metadata = (
                                    preprocess_context["metadata"]
                                    if preprocess_context is not None
                                    else last_image_metadata
                                )
                                preprocess_imu_sample = (
                                    preprocess_context["imu_sample"]
                                    if preprocess_context is not None
                                    else imu_sample
                                )
                                _publish_solver_preprocessed_preview(
                                    shared_state,
                                    preprocessed_run,
                                    preprocess_metadata,
                                )
                                raw_overlay = sep_shadow._last_overlay
                                sep_shadow.use_preprocessed_overlay(preprocessed_run)
                                # MFDS (or its SEP fallback) already applied the
                                # detection gates to this exact synthesized frame.
                                preprocessed_centroids = (
                                    preprocessed_run.detection.centroids
                                )
                                if horizon_mask_wanted and len(preprocessed_centroids):
                                    preprocessed_centroids, _ = (
                                        horizon_mask.filter_ground_centroids(
                                            preprocessed_centroids,
                                            preprocessed_run.frame_hw,
                                            fullframe_geometry["rotation_deg"],
                                            preprocess_imu_sample,
                                            fullframe_geometry["screen_direction"],
                                            fullframe_geometry["crop_width_px"],
                                        )
                                    )

                                if (
                                    (
                                        distortion_calibration_session is not None
                                        or lens_measurement.active
                                    )
                                    and not frame_moving
                                    and not async_preprocess_active
                                ):
                                    distortion_calibration_input = (
                                        _calibration_input_from_run(
                                            preprocessed_run,
                                            fullframe_geometry,
                                            expected_frame_id=last_image_metadata.get(
                                                "frame_id"
                                            ),
                                            source="preprocessed",
                                            previous=distortion_calibration_input,
                                            minimum_candidates=(
                                                DISTORTION_MIN_CANDIDATES
                                                if distortion_calibration_session
                                                is not None
                                                else 8
                                            ),
                                            central_crop=lens_measurement.active,
                                        )
                                    )

                                preprocessed_count = len(preprocessed_centroids)
                                preprocessed_center = _center_square_subset(
                                    preprocessed_centroids,
                                    preprocessed_run.frame_hw,
                                )
                                if capture_token is not None:
                                    capture_counts.update(
                                        {
                                            "preprocessed_center": len(
                                                preprocessed_center
                                            ),
                                            "preprocessed_full": preprocessed_count,
                                            "preprocessed_detector": preprocessed_run.detection.backend,
                                        }
                                    )
                                preprocess_target_sky = (
                                    [[align_ra, align_dec]]
                                    if align_ra != 0 and align_dec != 0
                                    else None
                                )

                                preprocessed_solution, selected_path = (
                                    _solve_preprocessed_run(
                                        t3,
                                        sep_shadow,
                                        preprocessed_run,
                                        shared_state,
                                        centroids=preprocessed_centroids,
                                        center_first=center_first_wanted,
                                        target_sky_coord=preprocess_target_sky,
                                        trace=capture_stages,
                                    )
                                )
                                if (
                                    async_preprocess_active
                                    and completed_preprocess is not None
                                    and not completed_preprocess.is_fresh()
                                ):
                                    selected_path = ""
                                if selected_path:
                                    preprocessed_fast_trusted = True
                                    if async_preprocess_active:
                                        bias_accepted = bool(
                                            preprocess_context is not None
                                            and preprocess_context.get("raw_solution")
                                            and preprocess_bias.update(
                                                preprocess_context["raw_solution"],
                                                preprocessed_solution,
                                            )
                                        )
                                        bias_status = preprocess_bias.status()
                                        if (
                                            preprocess_context.get("raw_solution")
                                            and not bias_accepted
                                        ):
                                            preprocess_bias.reset()
                                            solve_scheduling.reset(
                                                "raw_preprocessed_disagreement"
                                            )
                                        if raw_solved:
                                            solution = preprocess_bias.apply(solution)
                                        else:
                                            # The completed result belongs to
                                            # an older frame. Never publish it
                                            # after a newer camera attempt.
                                            solution = {}
                                        logger.debug(
                                            "Async preprocess calibration frame %s: "
                                            "accepted=%s ready=%s samples=%d "
                                            "rejected=%d separation=%s skipped=%d",
                                            preprocess_context["metadata"].get(
                                                "frame_id"
                                            ),
                                            bias_accepted,
                                            bias_status.ready,
                                            bias_status.accepted_samples,
                                            bias_status.rejected_samples,
                                            (
                                                f"{bias_status.last_separation_deg:.5f}deg"
                                                if bias_status.last_separation_deg
                                                is not None
                                                else "none"
                                            ),
                                            async_preprocess_worker.stats().skipped,
                                        )
                                    else:
                                        # Calibrate on paired synchronous
                                        # frames before handing over to RAW.
                                        # Keep the correction across ordinary
                                        # scheduling changes, but not motion,
                                        # alignment or an optics change.
                                        if raw_solved and not forced_sync:
                                            if not preprocess_bias.update(
                                                solution, preprocessed_solution
                                            ):
                                                preprocess_bias.reset()
                                                solve_scheduling.reset(
                                                    "raw_preprocessed_disagreement"
                                                )
                                        solution = preprocessed_solution
                                        solve_path = selected_path
                                        sep_fallback_used = "_sep_" in selected_path
                                        if sep_fallback_used:
                                            sep_run = preprocessed_run
                                elif raw_solved:
                                    # The auxiliary path found no valid
                                    # pattern; retain both the raw pointing and
                                    # the overlay that belongs to that solve.
                                    sep_shadow._last_overlay = raw_overlay
                                    if async_preprocess_active:
                                        solution = preprocess_bias.apply(solution)
                                else:
                                    preprocessed_fast_trusted = False

                                if not async_preprocess_active and (
                                    selected_path or not raw_solved
                                ):
                                    used_fullframe = True
                                    centroids = preprocessed_centroids
                                    ff_frame_hw = preprocessed_run.frame_hw
                                    sep_count = preprocessed_count
                                    ff_in_crop_count = _count_in_crop(
                                        preprocessed_centroids,
                                        ff_frame_hw,
                                        fullframe_geometry["crop_width_px"],
                                    )
                                logger.debug(
                                    "Solver preprocessing frame %s: window=%d "
                                    "detector=%s candidates=%d selected=%s",
                                    preprocess_metadata.get("frame_id"),
                                    preprocessed_run.diagnostics.frame_count,
                                    preprocessed_run.detection.backend,
                                    preprocessed_count,
                                    selected_path or "none",
                                )
                                if timing_debug_wanted:
                                    raw_preprocessed_separation = None
                                    preprocess_raw_diagnostic = raw_solution_diagnostic
                                    if (
                                        preprocess_context is not None
                                        and preprocess_context.get("raw_solution")
                                    ):
                                        raw_snapshot = preprocess_context[
                                            "raw_solution"
                                        ]
                                        preprocess_raw_diagnostic = {
                                            "ra": float(raw_snapshot["RA"]),
                                            "dec": float(raw_snapshot["Dec"]),
                                            "path": "raw",
                                        }
                                    if preprocess_raw_diagnostic and selected_path:
                                        raw_preprocessed_separation = (
                                            angular_separation_deg(
                                                preprocess_raw_diagnostic["ra"],
                                                preprocess_raw_diagnostic["dec"],
                                                float(preprocessed_solution["RA"]),
                                                float(preprocessed_solution["Dec"]),
                                            )
                                        )
                                    logger.debug(
                                        "Solver stage timing frame %s: "
                                        "raw_cascade=%.1fms preprocess_detect=%.1fms "
                                        "through_preprocess=%.1fms raw_solved=%s "
                                        "raw_path=%s raw_pre_sep_deg=%s",
                                        preprocess_metadata.get("frame_id"),
                                        raw_cascade_ms,
                                        preprocess_ms,
                                        (precision_timestamp() - t0) * 1000.0,
                                        preprocess_raw_diagnostic is not None,
                                        (
                                            preprocess_raw_diagnostic["path"]
                                            if preprocess_raw_diagnostic
                                            else "none"
                                        ),
                                        (
                                            f"{raw_preprocessed_separation:.5f}"
                                            if raw_preprocessed_separation is not None
                                            else "none"
                                        ),
                                    )
                            else:
                                if async_preprocess_active:
                                    if raw_solved:
                                        solution = preprocess_bias.apply(solution)
                                    worker_stats = async_preprocess_worker.stats()
                                    _publish_solver_preprocess_status(
                                        shared_state,
                                        enabled=True,
                                        state="background_processing",
                                        frame_count=preprocess_bias.status().accepted_samples,
                                        frame_id=last_image_metadata.get("frame_id"),
                                        clear_frame=False,
                                    )
                                    if timing_debug_wanted:
                                        logger.debug(
                                            "Async preprocessing busy frame %s: "
                                            "submitted=%d completed=%d skipped=%d "
                                            "raw_solved=%s",
                                            last_image_metadata.get("frame_id"),
                                            worker_stats.submitted,
                                            worker_stats.completed,
                                            worker_stats.skipped,
                                            raw_solved,
                                        )
                                else:
                                    preprocessed_fast_trusted = False
                                    preprocess_status = sep_shadow.preprocess_status()
                                    _publish_solver_preprocess_status(
                                        shared_state,
                                        enabled=True,
                                        state=str(
                                            preprocess_status.get("state") or "warming"
                                        ),
                                        frame_count=int(
                                            preprocess_status.get("frame_count") or 0
                                        ),
                                        frame_id=last_image_metadata.get("frame_id"),
                                        reset_reason=preprocess_status.get(
                                            "reset_reason"
                                        ),
                                        error=preprocess_status.get("error"),
                                        clear_frame=True,
                                    )
                    elif solver_preprocess_enabled:
                        preprocessed_fast_trusted = False
                        _publish_solver_preprocess_status(
                            shared_state,
                            enabled=True,
                            state="waiting_for_raw",
                            frame_id=last_image_metadata.get("frame_id"),
                            clear_frame=True,
                        )

                    if sep_emergency_enabled:

                        def emergency_filter(cents, frame_hw):
                            if not horizon_mask_wanted or not len(cents):
                                return cents
                            return horizon_mask.filter_ground_centroids(
                                cents,
                                frame_hw,
                                fullframe_geometry["rotation_deg"],
                                imu_sample,
                                fullframe_geometry["screen_direction"],
                                fullframe_geometry["crop_width_px"],
                            )[0]

                        emergency_solution, emergency_path, emergency_run = (
                            _solve_sep_emergency(
                                t3,
                                sep_shadow,
                                shared_state,
                                primary_solution=solution,
                                raw_entry=ff_entry,
                                preprocessed_run=emergency_preprocessed_run,
                                expected_frame_id=last_image_metadata.get("frame_id"),
                                moving=frame_moving,
                                center_first=center_first_wanted,
                                # A trusted sync fast path may have skipped RAW
                                # solves. Its failure clears trust; let the next
                                # exposure run the full MFDS cascade before SEP.
                                primary_paths_complete=not prefer_preprocessed_fast,
                                target_sky_coord=(
                                    [[align_ra, align_dec]]
                                    if align_ra != 0 and align_dec != 0
                                    else None
                                ),
                                filter_centroids=emergency_filter,
                                trace=capture_stages,
                            )
                        )
                        if emergency_path:
                            solution, solve_path = emergency_solution, emergency_path
                            sep_run = emergency_run
                            sep_fallback_used = True
                            used_fullframe = True
                            centroids = emergency_run.detection.centroids
                            ff_frame_hw = emergency_run.frame_hw
                            sep_count = len(centroids)
                            ff_in_crop_count = _count_in_crop(
                                centroids,
                                ff_frame_hw,
                                fullframe_geometry["crop_width_px"],
                            )
                            if capture_token is not None:
                                capture_counts["emergency_sep"] = sep_count

                    # A single native wide-field pattern must never become
                    # pointing truth by itself. Cold full-frame locks and
                    # >5° jumps need an independent confirmation. With solver
                    # preprocessing enabled, stationary fine jumps and raw
                    # fallback transitions are confirmed too; the allowance
                    # includes sidereal drift since the trusted frame.
                    if capture_token is not None:
                        capture_candidate = dict(solution or {})
                    if solution and solution.get("RA") is not None:
                        continuity = solve_continuity.evaluate(
                            solution,
                            solve_path,
                            last_solve_attempt,
                            stationary=not frame_moving,
                            prefer_preprocessed=(
                                solver_preprocess_enabled and not fast_raw_after_motion
                            ),
                        )
                        capture_continuity = continuity
                        if continuity.accepted and continuity.reason in {
                            "confirmed_jump",
                            "confirmed_stationary_change",
                        }:
                            logger.info(
                                "Confirmed %s solution on consecutive frames "
                                "(RA=%.4f Dec=%.4f agreement=%.2f°)",
                                solve_path,
                                float(solution["RA"]),
                                float(solution["Dec"]),
                                float(continuity.separation_deg or 0.0),
                            )
                        elif not continuity.accepted:
                            logger.warning(
                                "Held %s solution for confirmation: %s "
                                "(RA=%.4f Dec=%.4f separation=%s)",
                                solve_path,
                                continuity.reason,
                                float(solution["RA"]),
                                float(solution["Dec"]),
                                (
                                    f"{continuity.separation_deg:.2f}°"
                                    if continuity.separation_deg is not None
                                    else "cold"
                                ),
                            )
                            if sep_shadow is not None:
                                sep_shadow.clear_matched_overlay()
                                # The pattern solved successfully. A publication
                                # hold needs the next independent RAW frame, so
                                # it must not arm the failed-pattern backoff.
                                # Scheduling handles repeated publication holds.
                            solution = {}
                            sep_fallback_used = False

                    published_solution = bool(
                        solution and solution.get("RA") is not None
                    )
                    if (
                        solver_preprocess_enabled
                        and not frame_moving
                        and not fast_raw_after_motion
                    ):
                        solve_scheduling.record_publication(accepted=published_solution)
                        if solve_scheduling.reason == "raw_publication_stalled":
                            preprocess_bias.reset()
                    _publish_solver_scheduling_status(
                        {
                            **solve_scheduling.status(),
                            "updated": time.time(),
                            "frame_id": last_image_metadata.get("frame_id"),
                            "exposure_end": last_solve_attempt,
                            "preprocessing_enabled": solver_preprocess_enabled,
                            "frame_moving": frame_moving,
                            "fast_raw_after_motion": fast_raw_after_motion,
                            "async_active": async_preprocess_mode_active,
                            "raw_solved": raw_solution_diagnostic is not None,
                            "accepted": published_solution,
                            "solve_path": solve_path,
                            "processing_ms": (precision_timestamp() - t0) * 1000.0,
                            "bias_ready": preprocess_bias.ready,
                            "generation": async_preprocess_generation,
                        }
                    )

                    # Consume full-frame matched coordinates while they still
                    # exist.  Published pointing keeps its existing 512-space
                    # contract; only this compact AE summary crosses processes.
                    if (
                        used_fullframe
                        and ff_frame is not None
                        and solution
                        and solution.get("RA") is not None
                        and solution.get("matched_centroids") is not None
                    ):
                        try:
                            matched = np.asarray(
                                solution["matched_centroids"], dtype=np.float64
                            )
                            _, matched_canvas = sfm.rotate_centroids(
                                np.empty((0, 2)),
                                ff_frame_hw,
                                fullframe_geometry["rotation_deg"],
                            )
                            matched_raw, _ = sfm.rotate_centroids(
                                matched,
                                matched_canvas,
                                (360.0 - fullframe_geometry["rotation_deg"]) % 360.0,
                            )
                            exposure_quality = matched_star_exposure_quality(
                                ff_frame,
                                matched_raw,
                                frame_id=last_image_metadata.get("frame_id"),
                                candidate_stars=(
                                    len(sep_run.detection.centroids)
                                    if sep_fallback_used and sep_run is not None
                                    else len(centroids)
                                ),
                                bit_depth=get_camera_profile(
                                    shared_state.camera_type()
                                ).bit_depth,
                                source="peripheral_full",
                                rmse=solution.get("RMSE"),
                            )
                        except Exception:
                            logger.exception("Auto(Star) matched-star quality failed")
                    if exposure_quality is None and used_fullframe:
                        exposure_quality = {
                            "frame_id": last_image_metadata.get("frame_id"),
                            "source": "peripheral_full",
                            "region_ids": (),
                            "matched_stars": 0,
                            "candidate_stars": max(
                                value or 0
                                for value in (
                                    cedar_gated_count,
                                    cedar_raw_count,
                                    sep_count,
                                )
                            ),
                            "snr_p25": None,
                            "snr_median": None,
                            "rmse": solution.get("RMSE") if solution else None,
                            "solve_success": False,
                            "center_contaminated": bool(center_contaminated_for_ae),
                        }

                    if sep_fallback_used:
                        # SEP per-centroid outputs are in full-frame space;
                        # never let them reach 512-space SQM photometry.
                        solution.pop("matched_centroids", None)
                        solution.pop("matched_stars", None)
                        solution.pop("matched_catID", None)
                        logger.debug(
                            "Full-frame solve SUCCESS - detector=%s candidates=%d, RMSE %.1f",
                            sep_run.detection.backend,
                            len(sep_run.detection.centroids),
                            solution.get("RMSE") or -1.0,
                        )
                    elif used_fullframe and solution and solution.get("RA") is not None:
                        # Native full-frame coordinates share the SEP canvas;
                        # retain matches only for the overlay, then strip them
                        # before the 512-space SQM path.
                        ff_matched_for_overlay = solution.get("matched_centroids")
                        solution.pop("matched_centroids", None)
                        solution.pop("matched_stars", None)
                        solution.pop("matched_catID", None)

                    if "matched_centroids" in solution:
                        if sqm_calculator is None:
                            sqm_calculator = create_sqm_calculator(shared_state)
                            sqm_wing_estimator.reset()
                            profile = sqm_calculator.profile
                            sqm_cloud_estimator = CloudEstimator(
                                clear_zero_point=profile.clear_zero_point,
                                clear_sky_brightness=profile.clear_sky_brightness,
                            )
                            sqm_black_level = BlackLevelTracker(profile.bias_offset)

                        # Expensive stellar photometry is diagnostic-only in the
                        # radiometer-first path and remains limited to 10 seconds.
                        exposure_sec = (
                            last_image_metadata["exposure_time"] / 1_000_000.0
                        )
                        # Topocentric altitude is computed later by the
                        # integrator. Do not mislabel an unavailable value as
                        # zenith; the published SQM remains uncorrected and the
                        # optional comparison diagnostic stays absent.
                        altitude_for_sqm = None

                        diagnostic_now = time.time()
                        if (
                            diagnostic_now - last_stellar_diagnostic
                            >= SQM_STELLAR_DIAGNOSTIC_INTERVAL_SECONDS
                        ):
                            update_sqm(
                                shared_state=shared_state,
                                sqm_calculator=sqm_calculator,
                                centroids=centroids,
                                solution=solution,
                                exposure_sec=exposure_sec,
                                altitude_deg=altitude_for_sqm,
                                calculation_interval_seconds=SQM_CALCULATION_INTERVAL_SECONDS,
                                wing_estimator=sqm_wing_estimator,
                                cloud_estimator=sqm_cloud_estimator,
                                black_level_tracker=sqm_black_level,
                                publish=False,
                            )
                            last_stellar_diagnostic = diagnostic_now

                        # Don't clutter printed solution with these fields (use pop to safely remove)
                        solution.pop("pattern_centroids", None)
                        solution.pop("epoch_equinox", None)
                        solution.pop("epoch_proper_motion", None)
                        solution.pop("cache_hit_fraction", None)

                    if solution and solution.get("RA") is not None:
                        if solve_fail_streak > 1:
                            logger.info(
                                "Solving recovered after %d failed attempts",
                                solve_fail_streak,
                            )
                        solve_fail_streak = 0
                        last_solve_success = last_solve_attempt
                        alignment_context = None
                        if not frame_moving:
                            try:
                                alignment_context = projection_context(
                                    shared_state, _sep_cfg
                                )
                            except Exception:
                                logger.debug(
                                    "Alignment projection context unavailable",
                                    exc_info=True,
                                )
                        if sep_shadow is not None and not sep_fallback_used:
                            # Production solve: sky is workable, clear the
                            # fallback backoff so the next RAW failure gets
                            # an immediate rescue try.
                            sep_shadow.note_solved()
                        solve_result = _build_successful_solve(
                            solution=solution,
                            last_image_metadata=last_image_metadata,
                            last_solve_attempt=last_solve_attempt,
                            last_solve_success=last_solve_success,
                            # A fallback solve's real star count is SEP's --
                            # publishing it keeps auto-exposure's solve-hold
                            # engaged on the exposure that actually solved.
                            # Native full-frame publishes the in-crop count so
                            # auto-exposure keeps its 512-crop semantics.
                            centroid_count=(
                                len(sep_run.detection.centroids)
                                if sep_fallback_used and sep_run is not None
                                else (
                                    ff_in_crop_count
                                    if used_fullframe
                                    else len(centroids)
                                )
                            ),
                            solve_path=solve_path,
                            cedar_raw_centroids=cedar_raw_count,
                            cedar_gated_centroids=cedar_gated_count,
                            cedar_center_centroids=cedar_center_count,
                            sep_centroids=sep_count,
                            frame_id=last_image_metadata.get("frame_id"),
                            exposure_quality=exposure_quality,
                            alignment_context=alignment_context,
                        )
                        # Popped only now: _build_successful_solve above needs
                        # it for the Gaia-G reference band.
                        solution.pop("matched_catID", None)

                        total_tetra_time = t_extract + (solution.get("T_solve") or 0)
                        if total_tetra_time > 1000:
                            console_queue.put(f"SLV: Long: {total_tetra_time}")
                            logger.warning("Long solver time: %i", total_tetra_time)

                        logger.debug(
                            f"Solve SUCCESS - {len(centroids)} centroids → "
                            f"{solve_result.diagnostics.Matches} matches, "
                            f"RMSE: {solve_result.diagnostics.RMSE:.1f}px"
                        )

                        # See if we are waiting for alignment
                        if align_ra != 0 and align_dec != 0:
                            if solve_result.alignment.is_set():
                                align_result_queue.put(
                                    AlignedResult(
                                        y_target=solve_result.alignment.y_target,
                                        x_target=solve_result.alignment.x_target,
                                    )
                                )
                                logger.debug(
                                    "Align target_pixel=(%s, %s)",
                                    solve_result.alignment.y_target,
                                    solve_result.alignment.x_target,
                                )
                            align_ra = 0
                            align_dec = 0
                            # Clear alignment fields from the message now that
                            # the result has been consumed.
                            solve_result.alignment = AlignmentResult()

                        solver_queue.put(solve_result)
                    else:
                        if solution:
                            solve_fail_streak += 1
                            if solve_fail_streak == 1:
                                logger.warning(
                                    f"Solve FAILED - {len(centroids)} centroids detected but "
                                    f"pattern match failed "
                                    f"({'full-frame native FOV' if used_fullframe else 'FOV est: 12.0°, max err: 4.0°'}) "
                                    f"(logged once per failure streak)"
                                )
                        solver_queue.put(
                            _build_failed_solve(
                                last_solve_attempt=last_solve_attempt,
                                last_solve_success=last_solve_success,
                                t_extract_ms=t_extract,
                                centroid_count=(
                                    ff_in_crop_count
                                    if used_fullframe
                                    else len(centroids)
                                ),
                                solve_path=solve_path,
                                cedar_raw_centroids=cedar_raw_count,
                                cedar_gated_centroids=cedar_gated_count,
                                cedar_center_centroids=cedar_center_count,
                                sep_centroids=sep_count,
                                frame_id=last_image_metadata.get("frame_id"),
                                exposure_quality=exposure_quality,
                            )
                        )

                    field_capture.finish(
                        capture_token,
                        {
                            "input_ready_monotonic_ns": capture_input_ready_ns,
                            "queue_put_return_monotonic_ns": time.monotonic_ns(),
                            "accepted": published_solution,
                            "solve_path": solve_path,
                            "candidate": capture_candidate,
                            "continuity": capture_continuity,
                            "raw_cascade": raw_solution_diagnostic,
                            "raw_cascade_ms": raw_cascade_ms,
                            "raw_extract_ms": capture_primary_extract_ms,
                            "raw_sep_wait_ms": capture_sep_wait_ms,
                            "stages": capture_stages,
                            "candidate_counts": {
                                "raw_cedar": 0,  # retired detector; legacy schema
                                "raw_cedar_center": cedar_center_count,
                                "raw_sep": sep_count,
                                **capture_counts,
                            },
                            "preprocess_detect_ms": preprocess_ms,
                            "preprocess_frame_id": (
                                preprocess_context["metadata"].get("frame_id")
                                if preprocess_context is not None
                                else last_image_metadata.get("frame_id")
                            ),
                            "preprocess_background": async_preprocess_mode_active,
                            "scheduling": solve_scheduling.status(),
                            "bias": preprocess_bias.status(),
                            "generation": async_preprocess_generation,
                            "frame_moving": frame_moving,
                            "fast_raw_after_motion": fast_raw_after_motion,
                            "target_pixel": target_pixel_key,
                            "optics": {
                                key: (fullframe_geometry or {}).get(key)
                                for key in (
                                    "rotation_deg",
                                    "crop_width_px",
                                    "base_fov_degrees",
                                    "distortion_coefficients",
                                )
                            },
                        }
                        if capture_token is not None
                        else {},
                        raw_entry=solver_raw_entry,
                        image=np_image,
                    )
                    capture_token = None

                    # Calibration runs on its own tetra3 instance. The normal
                    # pointing result above is never delayed by the fit; while
                    # one sample is running, intermediate frames are dropped
                    # and the newest available frame is submitted next.
                    if (
                        distortion_calibration_future is not None
                        and distortion_calibration_future.done()
                    ):
                        try:
                            (
                                completed_request_id,
                                completed_source,
                                calibration_observation,
                            ) = distortion_calibration_future.result()
                            distortion_calibration_future = None
                            latest_status = (
                                shared_state.distortion_calibration_status() or {}
                            )
                            if (
                                distortion_calibration_session is None
                                or completed_request_id
                                != distortion_calibration_session.request_id
                                or latest_status.get("state") in {"cancelled", "reset"}
                                or shared_state.camera_type()
                                != distortion_calibration_session.camera_type
                                or calibration_lens_key(
                                    str(shared_state.camera_lens() or ""),
                                    manual_focal_from_state(shared_state),
                                )
                                != distortion_calibration_session.lens_key
                            ):
                                logger.info(
                                    "Discarding completed distortion fit after "
                                    "session cancel/reset"
                                )
                            else:
                                distortion_calibration_session.add(
                                    calibration_observation
                                )
                                logger.info(
                                    "Distortion calibration %s (%s, candidates=%d, "
                                    "accepted=%d/5; %s)",
                                    calibration_observation.reason,
                                    completed_source,
                                    calibration_observation.candidates,
                                    len(distortion_calibration_session.samples),
                                    calibration_observation.diagnostics,
                                )
                                if distortion_calibration_session.ready():
                                    coefficients, fit_summary = (
                                        distortion_calibration_session.profile_values()
                                    )
                                    candidate = CalibrationProfileStore(
                                        _sep_cfg
                                    ).save_auto_sky(
                                        distortion_calibration_session.camera_type,
                                        distortion_calibration_session.lens_key,
                                        get_camera_profile(
                                            distortion_calibration_session.camera_type
                                        ),
                                        coefficients,
                                        fit_summary,
                                    )
                                    shared_state.set_distortion_calibration_status(
                                        {
                                            "state": "completed",
                                            "request_id": distortion_calibration_session.request_id,
                                            "camera_type": distortion_calibration_session.camera_type,
                                            "lens_key": distortion_calibration_session.lens_key,
                                            "accepted_frames": len(
                                                distortion_calibration_session.samples
                                            ),
                                            "required_frames": 5,
                                            "profile_id": candidate["id"],
                                            "k1": coefficients["k1"],
                                            "last_reason": "saved",
                                        }
                                    )
                                    logger.info(
                                        "Distortion calibration saved: %s k1=%.6f",
                                        candidate["id"],
                                        coefficients["k1"],
                                    )
                                    distortion_calibration_session = None
                                else:
                                    shared_state.set_distortion_calibration_status(
                                        distortion_calibration_session.status(
                                            candidates=calibration_observation.candidates
                                        )
                                    )
                        except Exception:
                            distortion_calibration_future = None
                            logger.exception("Distortion calibration worker failed")
                            shared_state.set_distortion_calibration_status(
                                {
                                    "state": "error",
                                    "accepted_frames": (
                                        len(distortion_calibration_session.samples)
                                        if distortion_calibration_session is not None
                                        else 0
                                    ),
                                    "required_frames": 5,
                                    "last_reason": "internal_error",
                                }
                            )
                            distortion_calibration_session = None

                    lens_measurement.observe(
                        distortion_calibration_input,
                        last_image_metadata.get("frame_id"),
                        frame_moving,
                    )

                    if (
                        distortion_calibration_session is not None
                        and distortion_calibration_future is None
                    ):
                        current_camera = str(shared_state.camera_type() or "")
                        current_lens = calibration_lens_key(
                            str(
                                getattr(shared_state, "camera_lens", lambda: "")() or ""
                            ),
                            manual_focal_from_state(shared_state),
                        )
                        if (
                            current_camera != distortion_calibration_session.camera_type
                            or current_lens != distortion_calibration_session.lens_key
                        ):
                            shared_state.set_distortion_calibration_status(
                                {
                                    "state": "error",
                                    "accepted_frames": len(
                                        distortion_calibration_session.samples
                                    ),
                                    "required_frames": 5,
                                    "last_reason": "camera_or_lens_changed",
                                }
                            )
                            distortion_calibration_session = None
                        elif frame_moving:
                            distortion_calibration_session.last_reason = "frame_moving"
                            shared_state.set_distortion_calibration_status(
                                distortion_calibration_session.status()
                            )
                        elif distortion_calibration_input is None:
                            distortion_calibration_session.last_reason = (
                                "waiting_full_frame"
                            )
                            shared_state.set_distortion_calibration_status(
                                distortion_calibration_session.status()
                            )
                        else:
                            distortion_calibration_session.last_reason = (
                                "measuring_frame"
                            )
                            shared_state.set_distortion_calibration_status(
                                distortion_calibration_session.status(
                                    state="measuring",
                                    candidates=len(
                                        distortion_calibration_input["centroids"]
                                    ),
                                )
                            )
                            distortion_calibration_future = (
                                distortion_calibration_executor.submit(
                                    _measure_distortion_task,
                                    distortion_calibration_session.request_id,
                                    distortion_calibration_input,
                                )
                            )

                    if sep_shadow is not None:
                        # Overlay ships once per attempt, after the solve
                        # outcome, so the confirmed/candidate split is never
                        # overwritten by the next detect (race fixed).
                        # A production solve contributes its matched
                        # stars too -- green means "confirmed by whichever
                        # solver succeeded".
                        if (
                            solution
                            and solution.get("RA") is not None
                            and not sep_fallback_used
                        ):
                            if used_fullframe:
                                # Native full-frame matched stars are already
                                # in the rotated canvas (same space as a SEP
                                # solve's); stashed before the SQM strip.
                                if ff_matched_for_overlay is not None:
                                    sep_shadow.attach_canvas_matched(
                                        ff_matched_for_overlay
                                    )
                            else:
                                sep_shadow.attach_production_matched(solution)
                        sep_shadow.publish_overlay(shared_state)
                        sep_shadow.log_attempt(
                            exposure_us=last_image_metadata.get("exposure_time"),
                            gain=last_image_metadata.get("gain"),
                            cedar_count=len(centroids),
                            matches=solution.get("Matches") if solution else None,
                            solved=bool(solution and solution.get("RA") is not None),
                            run=sep_run,
                            fallback_used=sep_fallback_used,
                            fallback_rmse=(
                                solution.get("RMSE")
                                if sep_fallback_used and solution
                                else None
                            ),
                        )
                except Exception as e:
                    field_capture.finish(
                        capture_token,
                        {"accepted": False, "exception": f"{type(e).__name__}: {e}"},
                    )
                    logger.error(
                        f"Exception during solve attempt: {e.__class__.__name__}: {str(e)}"
                    )
                    logger.exception(e)
                    last_solve_attempt = last_image_metadata["exposure_end"]
                    solver_queue.put(
                        _build_failed_solve(
                            last_solve_attempt=last_solve_attempt,
                            last_solve_success=last_solve_success,
                            t_extract_ms=0.0,
                        )
                    )
        except EOFError as eof:
            logger.error(f"Main process no longer running for solver: {eof}")
            logger.exception(eof)
            logger.error(
                f"Last solve attempt: {last_solve_attempt}, last success: {last_solve_success}"
            )
        except Exception as e:
            logger.error(f"Exception in Solver: {e.__class__.__name__}: {str(e)}")
            logger.exception(e)
            logger.error(f"Current process ID: {os.getpid()}")
            logger.error(f"Current thread: {threading.current_thread().name}")
            try:
                logger.error(
                    f"Active threads: {[t.name for t in threading.enumerate()]}"
                )
            except Exception:
                pass  # Don't let diagnostic logging fail
