"""On-sky radial-distortion calibration for a selected camera/lens pair.

The LCD only arms/cancels a session.  Actual fitting runs in the solver after
the normal pointing result has already been queued, so camera capture remains
continuous.  A profile is returned only after several full-frame solves agree
and matched stars cover the centre, middle and edge of the sensor.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Any, Mapping

import numpy as np

from PiFinder import solver_frame_map as sfm
from PiFinder.mf_wide_distortion import undistort_global_centroids
from PiFinder.solve_acceptance import angular_separation_deg


MIN_CANDIDATES = 40
MIN_MATCHES = 18
MIN_CENTRAL_MATCHES = 3
MIN_MID_MATCHES = 6
MIN_EDGE_MATCHES = 3
REQUIRED_FRAMES = 5
MAX_SESSION_SAMPLES = 12
MAX_RMSE_ARCSEC = 180.0
MIN_RMSE_IMPROVEMENT = 0.03
MAX_K1_MAD = 0.015
CALIBRATION_SOLVE_TIMEOUT_MS = 600
# Search directly in the Brown model that production applies. A tetra3
# variable-distortion range can expand one pattern into a huge hash search
# before its timeout check; scalar zero-distortion replays stay bounded.
BROWN_K1_SEARCH = (
    -0.35,
    -0.28,
    -0.22,
    -0.18,
    -0.15,
    -0.12,
    -0.10,
    -0.08,
    -0.05,
    0.0,
    0.05,
)


@dataclass(frozen=True)
class DistortionFrameMeasurement:
    k1: float
    candidates: int
    matches: int
    radial_bins: dict[str, int]
    rmse_before_arcsec: float | None
    rmse_after_arcsec: float
    fitted_rmse_arcsec: float
    ra: float
    dec: float


@dataclass(frozen=True)
class DistortionObservation:
    accepted: bool
    reason: str
    candidates: int
    measurement: DistortionFrameMeasurement | None = None
    diagnostics: str = ""


def _radial_bin_counts(
    matched_centroids: np.ndarray, canvas_hw: tuple[int, int]
) -> dict[str, int]:
    points = np.asarray(matched_centroids, dtype=np.float64).reshape(-1, 2)
    height, width = map(float, canvas_hw)
    centre = np.array([(height - 1.0) / 2.0, (width - 1.0) / 2.0])
    corner_radius = math.hypot(height / 2.0, width / 2.0)
    radii = np.linalg.norm(points - centre, axis=1) / max(corner_radius, 1.0)
    return {
        "central": int(np.count_nonzero(radii < 0.33)),
        "mid": int(np.count_nonzero((radii >= 0.33) & (radii < 0.66))),
        "edge": int(np.count_nonzero(radii >= 0.66)),
    }


def _solved(solution: Mapping[str, Any] | None, minimum_matches: int) -> bool:
    if not solution or solution.get("RA") is None or solution.get("Dec") is None:
        return False
    try:
        rmse = solution.get("RMSE")
        if rmse is None:
            return False
        rmse_value = float(rmse)
        return (
            int(solution.get("Matches") or 0) >= minimum_matches
            and math.isfinite(rmse_value)
            and rmse_value <= MAX_RMSE_ARCSEC
        )
    except (TypeError, ValueError):
        return False


def measure_distortion_frame(
    t3,
    centroids_yx,
    frame_hw: tuple[int, int],
    *,
    rotation_deg: float,
    crop_width_px: int,
    base_fov_degrees: float,
) -> DistortionObservation:
    """Fit and independently replay-check one full-frame star field."""

    centroids = np.asarray(centroids_yx, dtype=np.float64).reshape(-1, 2)
    if len(centroids) < MIN_CANDIDATES:
        return DistortionObservation(False, "not_enough_candidates", len(centroids))

    _, canvas = sfm.rotate_centroids(centroids, frame_hw, rotation_deg)
    fov = sfm.fov_estimate_deg(
        canvas[1], crop_width_px, base_fov_degrees=base_fov_degrees
    )
    solve_kwargs = {
        "fov_estimate": fov,
        "fov_max_error": fov / 3.0,
        "match_max_error": 0.005,
        "return_matches": True,
        "solve_timeout": CALIBRATION_SOLVE_TIMEOUT_MS,
    }
    replayed: list[tuple[float, Mapping[str, Any], dict[str, int]]] = []
    baseline = None
    solved_without_coverage = False
    diagnostics: list[str] = []
    for candidate_k1 in BROWN_K1_SEARCH:
        coefficients = {
            "k1": candidate_k1,
            "k2": 0.0,
            "k3": 0.0,
            "p1": 0.0,
            "p2": 0.0,
        }
        corrected = undistort_global_centroids(centroids, frame_hw, coefficients)
        corrected_rotated, corrected_canvas = sfm.rotate_centroids(
            corrected, frame_hw, rotation_deg
        )
        if corrected_canvas != canvas:
            continue
        checked_candidate = t3.solve_from_centroids(
            corrected_rotated, canvas, distortion=0.0, **solve_kwargs
        )
        if _solved(checked_candidate, MIN_MATCHES):
            if candidate_k1 == 0.0:
                baseline = checked_candidate
            matched_value = checked_candidate.get("matched_centroids")
            matched = np.asarray(
                [] if matched_value is None else matched_value, dtype=np.float64
            )
            bins = _radial_bin_counts(matched, canvas)
            diagnostics.append(
                f"{candidate_k1:+.3f}:{float(checked_candidate['RMSE']):.1f}/"
                f"{int(checked_candidate['Matches'])}/"
                f"{bins['central']}-{bins['mid']}-{bins['edge']}"
            )
            if (
                bins["central"] >= MIN_CENTRAL_MATCHES
                and bins["mid"] >= MIN_MID_MATCHES
                and bins["edge"] >= MIN_EDGE_MATCHES
            ):
                replayed.append((candidate_k1, checked_candidate, bins))
            else:
                solved_without_coverage = True
        else:
            diagnostics.append(f"{candidate_k1:+.3f}:fail")
    diagnostic_text = ",".join(diagnostics)
    if not replayed:
        reason = (
            "not_enough_field_coverage"
            if solved_without_coverage
            else "distortion_fit_failed"
        )
        return DistortionObservation(
            False, reason, len(centroids), diagnostics=diagnostic_text
        )

    k1, checked, bins = min(replayed, key=lambda item: float(item[1]["RMSE"]))
    if k1 in {BROWN_K1_SEARCH[0], BROWN_K1_SEARCH[-1]}:
        return DistortionObservation(
            False,
            "unsafe_distortion",
            len(centroids),
            diagnostics=diagnostic_text,
        )

    coordinate_confirmed = any(
        other_solution is not checked
        and angular_separation_deg(
            float(checked["RA"]),
            float(checked["Dec"]),
            float(other_solution["RA"]),
            float(other_solution["Dec"]),
        )
        <= 0.25
        for _, other_solution, _ in replayed
    )
    if not coordinate_confirmed:
        return DistortionObservation(
            False,
            "corrected_coordinate_mismatch",
            len(centroids),
            diagnostics=diagnostic_text,
        )

    rmse_before = None
    if baseline is not None and _solved(baseline, MIN_MATCHES):
        rmse_before = float(baseline["RMSE"])
    rmse_after = float(checked["RMSE"])
    if rmse_before is not None and rmse_after > rmse_before * (
        1.0 - MIN_RMSE_IMPROVEMENT
    ):
        return DistortionObservation(
            False,
            "no_rmse_improvement",
            len(centroids),
            diagnostics=diagnostic_text,
        )

    measurement = DistortionFrameMeasurement(
        k1=k1,
        candidates=len(centroids),
        matches=int(checked["Matches"]),
        radial_bins=bins,
        rmse_before_arcsec=rmse_before,
        rmse_after_arcsec=rmse_after,
        fitted_rmse_arcsec=rmse_after,
        ra=float(checked["RA"]),
        dec=float(checked["Dec"]),
    )
    return DistortionObservation(
        True,
        "accepted",
        len(centroids),
        measurement,
        diagnostics=diagnostic_text,
    )


class DistortionCalibrationSession:
    """Accumulate stable per-frame measurements into one stored profile."""

    def __init__(self, camera_type: str, lens_key: str, request_id: int):
        self.camera_type = str(camera_type)
        self.lens_key = str(lens_key)
        self.request_id = int(request_id)
        self.samples: list[DistortionFrameMeasurement] = []
        self.last_reason = "requested"

    def add(self, observation: DistortionObservation) -> None:
        self.last_reason = observation.reason
        if observation.accepted and observation.measurement is not None:
            self.samples.append(observation.measurement)
            del self.samples[:-MAX_SESSION_SAMPLES]

    def ready(self) -> bool:
        if len(self.samples) < REQUIRED_FRAMES:
            return False
        values = [sample.k1 for sample in self.samples]
        median = statistics.median(values)
        mad = statistics.median(abs(value - median) for value in values)
        return mad <= MAX_K1_MAD

    def profile_values(self) -> tuple[dict[str, float], dict[str, Any]]:
        if not self.ready():
            raise ValueError("distortion calibration is not stable yet")
        samples = self.samples
        values = [sample.k1 for sample in samples]
        before = [
            sample.rmse_before_arcsec
            for sample in samples
            if sample.rmse_before_arcsec is not None
        ]
        after = [sample.rmse_after_arcsec for sample in samples]
        bins = {
            name: sum(sample.radial_bins[name] for sample in samples)
            for name in ("central", "mid", "edge")
        }
        coefficients = {
            "k1": statistics.median(values),
            "k2": 0.0,
            "k3": 0.0,
            "p1": 0.0,
            "p2": 0.0,
        }
        summary: dict[str, Any] = {
            "frames": len(samples),
            "radial_bins": bins,
            "matches_median": statistics.median(sample.matches for sample in samples),
            "k1_mad": statistics.median(
                abs(value - coefficients["k1"]) for value in values
            ),
            "median_rmse_after_arcsec": statistics.median(after),
            "method": "brown_k1_grid_search_v1",
        }
        if before:
            summary["median_rmse_before_arcsec"] = statistics.median(before)
            summary["rmse_improvement_fraction"] = 1.0 - (
                summary["median_rmse_after_arcsec"]
                / summary["median_rmse_before_arcsec"]
            )
        return coefficients, summary

    def status(
        self, *, state: str | None = None, candidates: int = 0
    ) -> dict[str, Any]:
        return {
            "state": state or ("collecting" if self.samples else "waiting_stars"),
            "request_id": self.request_id,
            "camera_type": self.camera_type,
            "lens_key": self.lens_key,
            "accepted_frames": len(self.samples),
            "required_frames": REQUIRED_FRAMES,
            "last_reason": self.last_reason,
            "last_candidates": int(candidates),
            "minimum_candidates": MIN_CANDIDATES,
        }
