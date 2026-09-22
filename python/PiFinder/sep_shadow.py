#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Full-frame RAW and star-only preprocessing runner.

Both image paths use MFDS in the live solver. SEP is invoked explicitly only
after the primary solve cascade has failed. The historical
SepShadowRunner name, sep_* solve paths and CSV columns remain compatible
with recorded comparison datasets. They do not identify the active detector;
use detection.backend and detector_backend diagnostics for that purpose.

Native coordinates are mapped through solver_frame_map for tetra3 and back
to the 512-space target pixel consumed by alignment and pointing.

All entry points are defensive: any exception is logged and swallowed,
so the experiment can never take down the production solver.

Config keys (restart to apply): ``solver_shadow_detect``,
``solver_sep_fallback``, ``solver_sep_sigma``, ``solver_sep_emergency``,
``solver_preprocess_accelerator``, ``solver_preprocess_reduction``.
The legacy solver_sep_fallback switch enables the full-frame MFDS solve tier;
it does not enable early SEP extraction in the live solver.

CSV: ``solver_shadow_log.csv`` in the tmpfs log dir (one row per solve
attempt -- steady small appends belong in RAM, not on the SD card, per
the same policy as the app logs). The web Logs page's "Save to SD"
snapshot includes it; like the logs, it is lost on power-off unless
saved.
"""

import csv
import logging
import os
import time
from dataclasses import dataclass, replace
from typing import Any, Optional

import numpy as np

from PiFinder import sep_detect, star_detect
from PiFinder import utils
from PiFinder import solver_frame_map as sfm
from PiFinder.mf_cloud_gate import wide_cloud_gate_enabled
from PiFinder.mf_manual_lens import manual_focal_from_state
from PiFinder.mf_star_only_preprocess import (
    MFStarOnlyAccumulator,
    MFStarOnlyConfig,
    MFStarOnlyDiagnostics,
)
from PiFinder.mf_wide_calibration import CalibrationProfileStore
from PiFinder.mf_wide_distortion import (
    active_coefficients,
    distort_global_centroids,
    undistort_global_centroids,
)
from PiFinder.sep_detect import SepDetection
from PiFinder.solve_acceptance import solution_quality_decision
from PiFinder.sqm.camera_profiles import get_camera_profile

logger = logging.getLogger("Solver.SepShadow")


def configure_runtime_detection():
    """Disable detector-level SEP fallback in the live solver and its workers.

    Explicit offline comparison tools can still select their own backend.
    Set once before worker creation, never around individual threaded calls.
    """
    os.environ["PIFINDER_DETECTOR"] = "mf"
    os.environ["MF_DETECT_SEP_FALLBACK"] = "0"


def detect_primary_stars(frame, **kwargs):
    """Keep native failure local so preprocessing and final recovery can run."""
    try:
        return star_detect.detect_stars(frame, **kwargs)
    except (OSError, RuntimeError, AttributeError) as exc:
        logger.warning("MFDS unavailable: %s", exc)
        return SepDetection(
            centroids=np.empty((0, 2)),
            fluxes=np.empty(0),
            background_median=0.0,
            background_rms=0.0,
            elapsed_ms=0.0,
            backend="mf",
            primary_candidates=0,
            fallback_reason=f"native_error:{type(exc).__name__}",
        )


CSV_FIELDS = [
    "timestamp",
    "exposure_us",
    "gain",
    "cedar_centroids",
    "matches",
    "solved",
    "sep_centroids",
    "sep_top_flux",
    "sep_bkg",
    "sep_rms",
    "sep_ms",
    "fallback_used",
    "fallback_rmse",
    "sep_masked",
    "sep_saturated",
]

# A solver_raw older than this no longer matches the attempt being logged
# (camera wedged, SEP path disabled mid-run); skip rather than mislabel.
MAX_FRAME_AGE_S = 15.0
# Fallback solve timeout. A 500 ms cap was field-tried 2026-08-04 but the
# A/B window was confounded by a scene change (SEP detections 17 -> 13,
# thin cloud); no solve-rate evidence either way, so the conservative 1 s
# stays until a same-frame offline A/B decides (field-test report).
FALLBACK_SOLVE_TIMEOUT_MS = 1000

# Warm-pixel map: (N, 2) int (y, x) in solver_raw orientation, built by
# ``python -m PiFinder.sep_warm_map`` from stage-dump corpora. Optional --
# missing file just means no masking. Regenerate when the sensor ages or
# after long temperature shifts (warm pixels grow over both).
WARM_MAP_PATH = utils.data_dir / "sep_warm_pixels.npy"


@dataclass
class SepRun:
    """One MFDS/SEP detection over the freshest full-frame RAW."""

    detection: SepDetection
    frame_hw: tuple
    exposure_us: Optional[float]
    gain: Optional[float]
    frame_id: Optional[int] = None


@dataclass
class PreprocessedRun:
    """Star-only full frame and detector result in unchanged RAW coordinates."""

    frame: np.ndarray
    detection: SepDetection
    diagnostics: MFStarOnlyDiagnostics
    frame_hw: tuple[int, int]
    frame_id: Optional[int]


def _preprocess_backend_options(cfg) -> dict[str, str]:
    """Persisted defaults with explicit MFDS environment overrides for experiments."""
    options = {}
    for name, env, default, choices in (
        ("accelerator", "MF_PREPROCESS_ACCELERATOR", "cpu", {"cpu", "auto", "gpu"}),
        ("reduction", "MF_PREPROCESS_REDUCTION", "auto", {"auto", "numpy", "neon"}),
    ):
        value = os.environ.get(env) or cfg.get_option(
            f"solver_preprocess_{name}", default
        )
        value = str(value if value is not None else default).strip().lower()
        if value not in choices:
            logger.warning(
                "Invalid preprocessing %s %r; using %s", name, value, default
            )
            value = default
        options[f"preprocess_{name}"] = value
    return options


class SepShadowRunner:
    def __init__(
        self,
        shadow_enabled: bool,
        fallback_enabled: bool,
        sigma: float,
        rotation_deg: float,
        crop_width_px: int,
        # 5, paired with sigma 4.5: the 2026-07-28 live-sky sweep showed
        # half the genuine rescues carry only 5-7 detections at that
        # threshold (the old gate of 8 was calibrated for sigma 3.5's
        # junk-inflated counts). No observed solve had fewer than 5.
        min_fallback_stars: int = 5,
        saturation_level: Optional[float] = None,
        csv_path=None,
        warm_pixel_map: Optional[np.ndarray] = None,
        base_fov_degrees: float = sfm.SOLVER_FOV_DEG,
        distortion_coefficients: Optional[dict[str, float]] = None,
        preprocess_scale_workers: int = 3,
        preprocess_accelerator: Optional[str] = None,
        preprocess_reduction: Optional[str] = None,
    ):
        self.shadow_enabled = shadow_enabled
        self.fallback_enabled = fallback_enabled
        self.sigma = sigma
        self.rotation_deg = rotation_deg
        self.crop_width_px = crop_width_px
        # Default preserves the current production calibration.  The future
        # optical-train integration will pass a night-validated crop FOV here.
        self.base_fov_degrees = base_fov_degrees
        self.min_fallback_stars = min_fallback_stars
        self._emergency_failures = 0
        self._emergency_skip = 0
        self.saturation_level = saturation_level
        self.csv_path = csv_path or (utils.log_dir / "solver_shadow_log.csv")
        self.warm_pixel_map = warm_pixel_map
        self.distortion_coefficients = distortion_coefficients
        # Fallback backoff state (see fallback_should_attempt): a fallback
        # solve on unsolvable input burns up to solve_timeout (1 s) of solver
        # CPU per attempt -- indoors/under cloud that is every attempt.
        self._attempt_counter = 0
        self._fallback_fail_streak = 0
        self._fallback_skip_until = 0
        self._last_failed_sep_count: Optional[int] = None
        # Overlay entry for the in-flight attempt (see publish_overlay)
        self._last_overlay: Optional[dict] = None
        # Test branch contract: scale calculations remain parallel even when
        # RAW failure/alignment requires waiting for this frame's result.
        self.preprocess_scale_workers = max(2, min(4, int(preprocess_scale_workers)))
        self._star_only = MFStarOnlyAccumulator(
            MFStarOnlyConfig(
                parallel_scale_workers=self.preprocess_scale_workers,
                accelerator=preprocess_accelerator,
                reduction_backend=preprocess_reduction,
            )
        )
        # Freeze the resolved options so a background clone uses the same modes.
        self.preprocess_accelerator = self._star_only.point_backend.mode
        self.preprocess_reduction = self._star_only.reduction_backend.mode
        self._last_preprocess_backends: Optional[tuple[Any, ...]] = None
        self._preprocess_status: dict = {
            "state": "idle",
            "frame_count": 0,
            "reset_reason": None,
            "error": None,
        }
        logger.info(
            "SEP shadow runner: shadow=%s fallback=%s sigma=%.1f "
            "rotation=%.0f° crop_width=%dpx warm_pixels=%d distortion=%s "
            "preprocess_workers=%d accelerator=%s reduction=%s log=%s",
            shadow_enabled,
            fallback_enabled,
            sigma,
            rotation_deg,
            crop_width_px,
            0 if warm_pixel_map is None else len(warm_pixel_map),
            "active" if distortion_coefficients is not None else "off",
            self.preprocess_scale_workers,
            self.preprocess_accelerator,
            self.preprocess_reduction,
            self.csv_path,
        )

    @classmethod
    def create_if_enabled(
        cls,
        cfg,
        camera_type: Optional[str],
        base_fov_degrees: float = sfm.SOLVER_FOV_DEG,
        lens_key: Optional[str] = None,
        force_create: bool = False,
    ):
        """Build a runner from config, or None when the path is disabled
        or the camera profile (crop geometry) is not resolvable yet."""
        try:
            shadow = bool(cfg.get_option("solver_shadow_detect"))
            fallback = bool(cfg.get_option("solver_sep_fallback"))
            if not (shadow or fallback or force_create):
                return None
            if not camera_type:
                return None
            profile = get_camera_profile(camera_type)
            crop_width = int(
                profile.raw_size[0] - profile.crop_x[0] - profile.crop_x[1]
            )
            rotation = sfm.stage5_rotation_deg(
                cfg.get_option("screen_direction"),
                cfg.get_option("camera_rotation"),
            )
            sigma = float(cfg.get_option("solver_sep_sigma") or 4.0)
            warm_map = None
            try:
                if WARM_MAP_PATH.exists():
                    warm_map = np.asarray(np.load(WARM_MAP_PATH), dtype=np.int32)
                    logger.info(
                        "Loaded %d warm pixels from %s", len(warm_map), WARM_MAP_PATH
                    )
            except Exception:
                logger.exception("Warm-pixel map load failed; continuing unmasked")
                warm_map = None
            calibration = CalibrationProfileStore(cfg).load_active(
                camera_type,
                str(lens_key or ""),
                profile,
            )
            backends = _preprocess_backend_options(cfg)
            return cls(
                shadow_enabled=shadow,
                fallback_enabled=fallback,
                sigma=sigma,
                rotation_deg=rotation,
                crop_width_px=crop_width,
                saturation_level=float(2**profile.bit_depth - 1),
                warm_pixel_map=warm_map,
                base_fov_degrees=base_fov_degrees,
                distortion_coefficients=active_coefficients(calibration),
                preprocess_scale_workers=int(
                    cfg.get_option("solver_preprocess_scale_workers", 3) or 3
                ),
                preprocess_accelerator=backends["preprocess_accelerator"],
                preprocess_reduction=backends["preprocess_reduction"],
            )
        except Exception:
            logger.exception("SEP shadow runner init failed; disabled")
            return None

    def fallback_should_attempt(self, sep_count: int) -> bool:
        """Backoff gate for the fallback solve.

        A failed fallback solve costs up to solve_timeout (1 s) of solver
        CPU. When the scene is persistently unsolvable (indoors, thick
        cloud) the SEP count passes the star gate every attempt and that
        cost recurs forever. After each consecutive failure we skip the
        next ``min(2**streak, 8)`` attempts -- but re-arm IMMEDIATELY when
        the SEP count rises to 1.5x the last failed attempt, which is what
        a cloud gap opening on real stars looks like. Rescue solves in a
        star window are therefore not delayed (2026-07-27 field: counts
        jumped from <=5 masked to ~30 when stars appeared).
        """
        if self._fallback_fail_streak == 0:
            return True
        if (
            self._last_failed_sep_count is not None
            and sep_count >= 1.5 * self._last_failed_sep_count
        ):
            return True
        return self._attempt_counter >= self._fallback_skip_until

    def preprocessing_clone(self):
        """Return an isolated runner whose mutable state belongs to a worker."""

        return type(self)(
            shadow_enabled=False,
            fallback_enabled=self.fallback_enabled,
            sigma=self.sigma,
            rotation_deg=self.rotation_deg,
            crop_width_px=self.crop_width_px,
            min_fallback_stars=self.min_fallback_stars,
            saturation_level=self.saturation_level,
            csv_path=self.csv_path,
            warm_pixel_map=self.warm_pixel_map,
            base_fov_degrees=self.base_fov_degrees,
            distortion_coefficients=self.distortion_coefficients,
            preprocess_scale_workers=self.preprocess_scale_workers,
            preprocess_accelerator=self.preprocess_accelerator,
            preprocess_reduction=self.preprocess_reduction,
        )

    def record_fallback_result(self, solved: bool, sep_count: int) -> None:
        """Record an attempted pattern solve, never a publication-only hold."""
        if solved:
            self._fallback_fail_streak = 0
            self._last_failed_sep_count = None
            return
        self._fallback_fail_streak += 1
        self._last_failed_sep_count = sep_count
        self._fallback_skip_until = self._attempt_counter + min(
            2**self._fallback_fail_streak, 8
        )

    def note_solved(self) -> None:
        """A production solve succeeded: the sky is workable, so the next
        cedar failure deserves an immediate fallback try again."""
        self._fallback_fail_streak = 0
        self._last_failed_sep_count = None

    def detect(
        self, shared_state, expected_frame_id=None, *, raw_entry=None, emergency=False
    ) -> Optional[SepRun]:
        """Detect from the frozen RAW pair, or read RAW for legacy callers."""
        self._attempt_counter += 1
        try:
            entry = raw_entry if raw_entry is not None else shared_state.solver_raw()
            if not entry or "frame" not in entry:
                return None
            if (
                expected_frame_id is not None
                and entry.get("frame_id") != expected_frame_id
            ):
                # Camera publication is latest-wins.  A new full RAW may land
                # while the solver still owns the previous 512 frame; never
                # combine those neighbouring frames.
                return None
            if time.time() - float(entry.get("timestamp") or 0) > MAX_FRAME_AGE_S:
                return None
            frame = np.asarray(entry["frame"])
            lens_key = getattr(shared_state, "camera_lens", lambda: "")()
            options: dict[str, Any] = {
                "sigma": self.sigma,
                "saturation_level": self.saturation_level,
                "warm_pixel_map": self.warm_pixel_map,
                "cloud_window_gate": wide_cloud_gate_enabled(
                    lens_key, manual_focal_from_state(shared_state)
                ),
            }
            detection = (
                sep_detect.detect_stars(frame, **options)
                if emergency
                else detect_primary_stars(frame, **options)
            )
            if detection is None:
                return None
            if emergency:
                detection.fallback_reason = "all_mfds_solve_paths_failed"
            # LiveCam overlay entry: NOT published here -- solve() attaches
            # the tetra3-matched subset and publish_overlay() (called once
            # per attempt from the solver, after the outcome is known)
            # publishes the final entry. Publishing candidates-only from
            # here raced the matched republish: the next attempt's detect
            # overwrote it, so the confirmed/candidate split almost never
            # reached the screen.
            self._last_overlay = {
                "detector_backend": detection.backend,
                "detector_fallback_reason": detection.fallback_reason,
                "centroids": detection.centroids.tolist(),
                "frame_hw": [int(frame.shape[0]), int(frame.shape[1])],
                "frame_id": entry.get("frame_id"),
                "masked": detection.masked_count,
                "saturated": detection.saturated_count,
                "sigma": self.sigma,
                "cloud_gate_active": detection.cloud_gate_active,
                "cloud_gated": detection.cloud_gated_count,
                "cloud_contrast": detection.cloud_contrast,
                "cloud_directional_coherence": (detection.cloud_directional_coherence),
                "timestamp": time.time(),
            }
            return SepRun(
                detection=detection,
                frame_hw=(frame.shape[0], frame.shape[1]),
                exposure_us=entry.get("exposure_us"),
                gain=entry.get("gain"),
                frame_id=entry.get("frame_id"),
            )
        except Exception:
            logger.exception("SEP shadow detect failed")
            return None

    def reset_preprocessor(self, reason: str = "reset") -> None:
        """Discard temporal evidence after motion or when the UI switch is off."""

        self._star_only.reset()
        self._preprocess_status = {
            "state": reason,
            "frame_count": 0,
            "reset_reason": reason,
            "error": None,
        }

    def close_preprocessor(self, reason: str = "inactive") -> None:
        """Release retired runner history, scale threads and optional GPU resources."""
        self.reset_preprocessor(reason)
        self._star_only.close()

    def preprocess_status(self) -> dict:
        return {
            **self._preprocess_status,
            "accelerator": self._star_only.point_backend.active_backend,
            "reduction": self._star_only.reduction_backend.active_backend,
            "accelerator_fallback": self._star_only.point_backend.fallback_reason,
            "reduction_fallback": self._star_only.reduction_backend.fallback_reason,
        }

    def _log_preprocess_backends(self) -> None:
        status = self.preprocess_status()
        backends = tuple(
            status[key]
            for key in (
                "accelerator",
                "reduction",
                "accelerator_fallback",
                "reduction_fallback",
            )
        )
        if backends != self._last_preprocess_backends:
            logger.info(
                "MFDS preprocessing backends: filter=%s reduction=%s "
                "filter_fallback=%s reduction_fallback=%s",
                *backends,
            )
            self._last_preprocess_backends = backends

    def preprocess_frame(
        self,
        frame,
        *,
        fingerprint,
        frame_id: Optional[int] = None,
    ) -> Optional[PreprocessedRun]:
        """Build a star-only frame and detect stars in unchanged RAW coordinates.

        The first frame only warms the temporal accumulator.  Requiring a
        second observation is the main protection against hot pixels and
        one-frame cloud glints being promoted into solver stars.
        """

        try:
            arr = np.asarray(frame)
            result = self._star_only.add(
                arr,
                saturation_level=float(
                    self.saturation_level or np.iinfo(arr.dtype).max
                ),
                fingerprint=fingerprint,
            )
            self._preprocess_status = {
                "state": ("warming" if result.diagnostics.frame_count < 2 else "ready"),
                "frame_count": result.diagnostics.frame_count,
                "reset_reason": result.diagnostics.reset_reason,
                "error": None,
            }
            if result.diagnostics.frame_count < 2:
                return None
            detection = detect_primary_stars(
                result.frame,
                sigma=self.sigma,
                # Keep tetra3's proven brightest-48 input unchanged while
                # allowing LiveCam to show genuine filtered stars farther
                # down the flux ranking in a strongly graded sky.
                overlay_max_stars=128,
                # Sensor-saturated extended structures were hard-masked before
                # temporal synthesis. Summing repeated real stars can still
                # clip the synthetic 12-bit output; that is evidence, not a
                # newly saturated sensor source, so do not reject it again.
                saturation_level=None,
                warm_pixel_map=self.warm_pixel_map,
                # Broad cloud structure was removed already. Reapplying the
                # directional cloud gate can reject the compact residuals the
                # preprocessing was specifically designed to preserve.
                cloud_window_gate=False,
            )
            if detection is None:
                self._preprocess_status["state"] = "waiting_for_stars"
                return None
            return PreprocessedRun(
                frame=result.frame,
                detection=detection,
                diagnostics=result.diagnostics,
                frame_hw=(int(arr.shape[0]), int(arr.shape[1])),
                frame_id=frame_id,
            )
        except Exception as exc:
            logger.exception("Star-only solver preprocessing failed")
            self._star_only.reset()
            self._preprocess_status = {
                "state": "error",
                "frame_count": 0,
                "reset_reason": "processing_error",
                "error": f"{exc.__class__.__name__}: {exc}",
            }
            return None
        finally:
            self._log_preprocess_backends()

    def emergency_should_attempt(self, *, primary_solved, moving):
        if primary_solved:
            self._emergency_failures = 0
            self._emergency_skip = 0
            return False
        if moving:
            return False
        if self._emergency_skip:
            self._emergency_skip -= 1
            return False
        return True

    def record_emergency_result(self, solved):
        if solved:
            self._emergency_failures = 0
            self._emergency_skip = 0
        else:
            self._emergency_failures += 1
            self._emergency_skip = min(2 ** min(self._emergency_failures, 3), 8)

    def detect_emergency_preprocessed(self, run):
        """Reuse the same synthesized frame; never preprocess it a second time."""
        detection = sep_detect.detect_stars(
            run.frame,
            sigma=self.sigma,
            overlay_max_stars=128,
            saturation_level=None,
            warm_pixel_map=self.warm_pixel_map,
            cloud_window_gate=False,
        )
        if detection is None:
            return None
        detection.fallback_reason = "all_mfds_solve_paths_failed"
        return replace(run, detection=detection)

    def use_preprocessed_overlay(self, run: PreprocessedRun) -> None:
        """Show the candidates from the frame that is actually being solved."""

        detection = run.detection
        overlay_centroids = detection.overlay_centroids
        if overlay_centroids is None:
            overlay_centroids = detection.centroids
        self._last_overlay = {
            "detector_backend": detection.backend,
            "detector_fallback_reason": detection.fallback_reason,
            "centroids": overlay_centroids.tolist(),
            "solver_centroids": len(detection.centroids),
            "frame_hw": [int(run.frame_hw[0]), int(run.frame_hw[1])],
            "frame_id": run.frame_id,
            "masked": detection.masked_count,
            "saturated": detection.saturated_count,
            "sigma": self.sigma,
            "cloud_gate_active": detection.cloud_gate_active,
            "cloud_gated": detection.cloud_gated_count,
            "cloud_contrast": detection.cloud_contrast,
            "cloud_directional_coherence": detection.cloud_directional_coherence,
            "preprocessed": True,
            "preprocess_frames": run.diagnostics.frame_count,
            "timestamp": time.time(),
        }

    def solve(
        self,
        t3,
        run: SepRun,
        shared_state,
        target_sky_coord=None,
        centroids_override=None,
        solve_path: str = "sep_full",
    ) -> Optional[dict]:
        """Solve from SEP centroids in the rotated full frame.

        Rotation, canvas size, fov and target_pixel are all mapped so the
        resulting RA/Dec/Roll -- and the aligned pointing at target_pixel
        -- carry the exact semantics of the production 512-frame solve
        (see solver_frame_map).

        ``target_sky_coord`` resolves an alignment target on the same frame.
        Its y/x_target is mapped back into rotated-512 space for the normal
        AlignedResult and persisted target_pixel chain.

        ``centroids_override`` solves from a subset (still full-frame
        (y, x) coordinates) instead of the run's full detection list --
        the centre-first cascade passes the centre-square subset here.
        """
        try:
            source = (
                run.detection.centroids
                if centroids_override is None
                else np.asarray(centroids_override, dtype=np.float64)
            )
            if self.distortion_coefficients is not None:
                source = undistort_global_centroids(
                    source,
                    run.frame_hw,
                    self.distortion_coefficients,
                )
            cents, canvas = sfm.rotate_centroids(
                source, run.frame_hw, self.rotation_deg
            )
            target_pixel = sfm.map_target_pixel_to_frame(
                shared_state.target_pixel(), canvas, self.crop_width_px
            )
            fov = sfm.fov_estimate_deg(
                canvas[1],
                self.crop_width_px,
                base_fov_degrees=self.base_fov_degrees,
            )
            solution = t3.solve_from_centroids(
                cents,
                canvas,
                fov_estimate=fov,
                fov_max_error=fov / 3.0,
                match_max_error=0.005,
                return_matches=True,
                target_pixel=target_pixel,
                target_sky_coord=target_sky_coord,
                solve_timeout=FALLBACK_SOLVE_TIMEOUT_MS,
            )
            quality = solution_quality_decision(solution, solve_path)
            if not quality.accepted:
                if solution and solution.get("RA") is not None:
                    logger.warning(
                        "Rejected %s solution: %s (matches=%s RMSE=%s Prob=%s)",
                        solve_path,
                        quality.reason,
                        solution.get("Matches"),
                        solution.get("RMSE"),
                        solution.get("Prob"),
                    )
                return None
            if (
                solution
                and solution.get("RA") is not None
                and solution.get("y_target") is not None
                and solution.get("x_target") is not None
            ):
                ty, tx = sfm.map_frame_pixel_to_target(
                    (float(solution["y_target"]), float(solution["x_target"])),
                    canvas,
                    self.crop_width_px,
                )
                solution["y_target"], solution["x_target"] = ty, tx
            solution["_alignment_frame"] = (*canvas, self.crop_width_px)
            self._attach_matched_overlay(solution)
            return solution
        except Exception:
            logger.exception("SEP fallback solve failed")
            return None

    def clear_matched_overlay(self) -> None:
        """Remove a provisional match rejected by the continuity gate."""

        if self._last_overlay is not None:
            self._last_overlay.pop("matched", None)

    def _rotate_csv_on_schema_change(self) -> None:
        """Sideline a CSV written with an older field list, once.

        Mixed-width rows break offline analysis; the sidelined file keeps
        its data under ``<name>.old``.
        """
        if getattr(self, "_csv_schema_checked", False):
            return
        self._csv_schema_checked = True
        if not self.csv_path.exists():
            return
        with open(self.csv_path, newline="") as f:
            header = f.readline().strip()
        if header != ",".join(CSV_FIELDS):
            old = self.csv_path.with_suffix(self.csv_path.suffix + ".old")
            self.csv_path.replace(old)
            logger.info("Shadow CSV schema changed; previous file moved to %s", old)

    def _attach_matched_overlay(self, solution) -> None:
        """Attach the tetra3-matched subset to the pending overlay entry.

        Matched centroids come back in the rotated, distortion-corrected
        solver canvas. Undo rotation first, then map them back through the
        lens distortion to the original sensor pixels used by both LiveCam
        and the candidate list. publish_overlay() ships the combined entry
        once per attempt. Best-effort like every overlay path.
        """
        try:
            overlay = getattr(self, "_last_overlay", None)
            if (
                overlay is None
                or not solution
                or solution.get("RA") is None
                or solution.get("matched_centroids") is None
            ):
                return
            matched = np.asarray(solution["matched_centroids"], dtype=np.float64)
            if matched.ndim != 2 or len(matched) == 0:
                return
            _, canvas = sfm.rotate_centroids(
                np.empty((0, 2)), tuple(overlay["frame_hw"]), self.rotation_deg
            )
            unrot, _ = sfm.rotate_centroids(
                matched, canvas, (360.0 - self.rotation_deg) % 360.0
            )
            if self.distortion_coefficients is not None:
                unrot = distort_global_centroids(
                    unrot, tuple(overlay["frame_hw"]), self.distortion_coefficients
                )
            overlay["matched"] = unrot.tolist()
        except Exception:
            logger.exception("SEP matched-overlay attach failed")

    def attach_canvas_matched(self, matched_centroids) -> None:
        """Overlay hook for the full-frame cedar primary path.

        Its matched centroids live in the same rotated canvas as a SEP
        solve's, so rotation and lens distortion are restored identically;
        the solver hands the
        array separately because the solution message itself is stripped
        of full-frame arrays before SQM sees it."""
        self._attach_matched_overlay(
            {"RA": 0.0, "matched_centroids": matched_centroids}
        )

    def attach_production_matched(self, solution) -> None:
        """Cedar solved this frame: mark its matched stars on the overlay.

        Without this, cedar-solved attempts carried no matched info and
        the overlay showed all-orange exactly when the sky is GOOD (cedar
        priority working as designed -- field report 2026-07-28 night).
        Cedar's matched centroids are in rotated-512 space; each maps to
        the rotated full-frame canvas (map_target_pixel_to_frame, the
        proven centre-scale relation) and is then un-rotated to frame
        space, the same space as the SEP matched path.
        """
        try:
            overlay = self._last_overlay
            if (
                overlay is None
                or not solution
                or solution.get("RA") is None
                or solution.get("matched_centroids") is None
            ):
                return
            m512 = np.asarray(solution["matched_centroids"], dtype=np.float64)
            if m512.ndim != 2 or len(m512) == 0:
                return
            _, canvas = sfm.rotate_centroids(
                np.empty((0, 2)), tuple(overlay["frame_hw"]), self.rotation_deg
            )
            mapped = np.array(
                [
                    sfm.map_target_pixel_to_frame((y, x), canvas, self.crop_width_px)
                    for y, x in m512
                ]
            )
            unrot, _ = sfm.rotate_centroids(
                mapped, canvas, (360.0 - self.rotation_deg) % 360.0
            )
            overlay["matched"] = unrot.tolist()
        except Exception:
            logger.exception("production matched overlay attach failed")

    def publish_overlay(self, shared_state) -> None:
        """Publish this attempt's overlay entry (candidates + any matched
        subset) exactly once, after the solve outcome is known."""
        overlay = getattr(self, "_last_overlay", None)
        if overlay is None or not hasattr(shared_state, "set_sep_overlay"):
            return
        try:
            shared_state.set_sep_overlay(dict(overlay))
        except Exception:
            logger.exception("SEP overlay publish failed")
        self._last_overlay = None

    def log_attempt(
        self,
        exposure_us,
        gain,
        cedar_count: int,
        matches,
        solved: bool,
        run: Optional[SepRun],
        fallback_used: bool = False,
        fallback_rmse=None,
    ) -> None:
        """Append one attempt-comparison row; never raises."""
        if not self.shadow_enabled:
            return
        try:
            row = {
                "timestamp": f"{time.time():.3f}",
                "exposure_us": exposure_us,
                "gain": gain,
                "cedar_centroids": cedar_count,
                "matches": matches,
                "solved": int(bool(solved)),
                "sep_centroids": len(run.detection.centroids) if run else "",
                "sep_top_flux": (
                    f"{run.detection.fluxes[0]:.0f}"
                    if run and len(run.detection.fluxes)
                    else ""
                ),
                "sep_bkg": f"{run.detection.background_median:.1f}" if run else "",
                "sep_rms": f"{run.detection.background_rms:.2f}" if run else "",
                "sep_ms": f"{run.detection.elapsed_ms:.0f}" if run else "",
                "fallback_used": int(bool(fallback_used)),
                "fallback_rmse": (
                    f"{fallback_rmse:.2f}" if fallback_rmse is not None else ""
                ),
                "sep_masked": run.detection.masked_count if run else "",
                "sep_saturated": run.detection.saturated_count if run else "",
            }
            self._rotate_csv_on_schema_change()
            write_header = not self.csv_path.exists()
            with open(self.csv_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            logger.exception("SEP shadow CSV append failed")
