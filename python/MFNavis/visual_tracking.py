"""Experimental visual tracking, independent of the operational pointing writer.

Coordinates follow tetra3: pixels are (y, x), camera rays are (forward, east,
north), and sky vectors use catalog equatorial axes. Input centroids must be
in one calibrated, undistorted canvas. This module never sends mount commands.
"""

from dataclasses import dataclass, field
import math

import numpy as np
from scipy.optimize import linear_sum_assignment


def unit(values):
    values = np.asarray(values, dtype=float)
    norms = np.linalg.norm(values, axis=-1, keepdims=True)
    if not np.isfinite(values).all() or np.any(norms < 1e-12):
        raise ValueError("invalid direction")
    return values / norms


def sky_vector(ra, dec):
    if not math.isfinite(ra) or not math.isfinite(dec) or not -90 <= dec <= 90:
        raise ValueError("invalid RA/Dec")
    ra, dec = np.radians([ra, dec])
    return np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])


def vector_radec(vector):
    x, y, z = unit(vector)
    return float(np.degrees(np.arctan2(y, x)) % 360), float(
        np.degrees(np.arcsin(np.clip(z, -1, 1)))
    )


def plate_basis(ra, dec, roll):
    forward = sky_vector(ra, dec)
    if not math.isfinite(roll):
        raise ValueError("invalid roll")
    ra, dec, roll = np.radians([ra, dec, roll])
    east = np.array([-np.sin(ra), np.cos(ra), 0.0])
    north = np.cross(forward, east)
    return np.array(
        [
            forward,
            np.cos(roll) * east + np.sin(roll) * north,
            -np.sin(roll) * east + np.cos(roll) * north,
        ]
    )


def rotation_between(source, destination):
    source, destination = unit(source), unit(destination)
    axis = np.cross(source, destination)
    cosine = float(np.dot(source, destination))
    if cosine < -0.999999:
        raise ValueError("ambiguous antipodal rotation")
    x, y, z = axis
    skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + skew + skew @ skew / (1 + cosine)


def validate_basis(basis):
    basis = np.asarray(basis, dtype=float)
    if (
        basis.shape != (3, 3)
        or not np.isfinite(basis).all()
        or not np.allclose(basis @ basis.T, np.eye(3), atol=1e-6)
        or not np.isclose(np.linalg.det(basis), 1, atol=1e-6)
    ):
        raise ValueError("pose must be a proper rotation")
    return basis


@dataclass(frozen=True)
class CameraGeometry:
    height: int
    width: int
    fov_deg: float
    target_yx: tuple[float, float]
    calibration_id: str

    def __post_init__(self):
        if (
            self.height < 2
            or self.width < 2
            or not self.calibration_id
            or not math.isfinite(self.fov_deg)
            or not 0 < self.fov_deg < 120
            or len(self.target_yx) != 2
            or not np.isfinite(self.target_yx).all()
            or not 0 <= self.target_yx[0] < self.height
            or not 0 <= self.target_yx[1] < self.width
        ):
            raise ValueError("invalid calibrated geometry")

    @property
    def focal(self):
        return self.width / (2 * math.tan(math.radians(self.fov_deg) / 2))

    def rays(self, pixels):
        pixels = np.asarray(pixels, dtype=float).reshape(-1, 2)
        return unit(
            np.column_stack(
                (
                    np.ones(len(pixels)),
                    (self.width / 2 - pixels[:, 1]) / self.focal,
                    (self.height / 2 - pixels[:, 0]) / self.focal,
                )
            )
        )

    def project(self, world, basis):
        camera = np.asarray(world, dtype=float).reshape(-1, 3) @ basis.T
        valid = camera[:, 0] > 1e-6
        result = np.full((len(camera), 2), np.nan)
        result[valid, 0] = (
            self.height / 2 - self.focal * camera[valid, 2] / camera[valid, 0]
        )
        result[valid, 1] = (
            self.width / 2 - self.focal * camera[valid, 1] / camera[valid, 0]
        )
        return result

    def aligned_basis(self, ra, dec, roll):
        basis = plate_basis(ra, dec, roll)
        current = self.rays([self.target_yx])[0] @ basis
        return basis @ rotation_between(current, sky_vector(ra, dec)).T


@dataclass(frozen=True)
class TrackingLimits:
    search_px: float = 12.0
    residual_px: float = 1.5
    min_baseline_px: float = 20.0
    max_gap_s: float = 120.0
    recovery_arcsec: float = 300.0
    confirmation_arcsec: float = 30.0
    max_points: int = 128

    def __post_init__(self):
        values = (
            self.search_px,
            self.residual_px,
            self.min_baseline_px,
            self.max_gap_s,
            self.recovery_arcsec,
            self.confirmation_arcsec,
        )
        if not all(math.isfinite(v) and v > 0 for v in values) or self.max_points < 3:
            raise ValueError("invalid tracking limits")


def clean_centroids(points, geometry, limit=128):
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    good = np.isfinite(points).all(axis=1)
    good &= (points[:, 0] >= 0) & (points[:, 0] < geometry.height)
    good &= (points[:, 1] >= 0) & (points[:, 1] < geometry.width)
    # Detector order is retained; repeated positions are not independent stars.
    points = points[good]
    if len(points):
        _, indices = np.unique(points, axis=0, return_index=True)
        points = points[np.sort(indices)]
    return points[:limit].copy()


def fit_star_pose(world, points, predicted, geometry, limits):
    """Fit a rotation from predicted unique pairs, rejecting inconsistent stars.

    No scale/shear is fitted. Three independent correspondences and a spatial
    baseline are required before publishing a pose. Fewer stars remain useful
    as a diagnostic but cannot silently determine the unobserved roll.
    """
    if len(world) == 0 or len(points) == 0:
        return None, 0, None
    expected = geometry.project(world, predicted)
    visible = np.isfinite(expected).all(axis=1)
    world, expected = world[visible], expected[visible]
    if not len(world):
        return None, 0, None
    distances = np.linalg.norm(expected[:, None] - points[None, :], axis=2)
    rows, cols = linear_sum_assignment(distances)
    keep = distances[rows, cols] <= limits.search_px
    # Reject ambiguous pairs in either direction, including close doubles.
    for index, (row, col) in enumerate(zip(rows, cols)):
        alternatives = np.concatenate(
            (np.delete(distances[row], col), np.delete(distances[:, col], row))
        )
        if len(alternatives) and alternatives.min() <= distances[row, col] + 2:
            keep[index] = False
    rows, cols = rows[keep], cols[keep]
    if len(rows) < 3:
        return None, len(rows), None
    selected, rays = world[rows], geometry.rays(points[cols])
    # Deterministic RANSAC over a bounded set of triples.
    rng = np.random.default_rng(0)
    samples = [np.arange(len(rows))]
    samples += [rng.choice(len(rows), 3, replace=False) for _ in range(48)]
    best = None
    for sample in samples:
        u, _, vh = np.linalg.svd(rays[sample].T @ selected[sample])
        correction = np.diag([1.0, 1.0, np.linalg.det(u @ vh)])
        pose = u @ correction @ vh
        projected = geometry.project(selected, pose)
        errors = np.linalg.norm(projected - points[cols], axis=1)
        mask = errors <= limits.residual_px
        score = (int(mask.sum()), -float(np.median(errors)))
        if best is None or score > best[0]:
            best = score, mask
    mask = best[1]
    count = int(mask.sum())
    if count < 3:
        return None, count, None
    observed = points[cols][mask]
    if np.linalg.norm(np.ptp(observed, axis=0)) < limits.min_baseline_px:
        return None, count, None
    u, _, vh = np.linalg.svd(rays[mask].T @ selected[mask])
    pose = u @ np.diag([1.0, 1.0, np.linalg.det(u @ vh)]) @ vh
    error = geometry.project(selected[mask], pose) - observed
    rmse = float(np.sqrt(np.mean(np.sum(error**2, axis=1))))
    return (pose if rmse <= limits.residual_px else None), count, rmse


def pose_distance_arcsec(first, second):
    relative = first @ second.T
    return float(
        np.degrees(np.arccos(np.clip((np.trace(relative) - 1) / 2, -1, 1))) * 3600
    )


@dataclass
class TrackingSession:
    geometry: CameraGeometry
    limits: TrackingLimits = field(default_factory=TrackingLimits)
    generation: int = 0
    state: str = "idle"
    target_id: str | None = None
    last_frame_id: int = -1
    last_time: float = -math.inf
    last_visual_time: float | None = None
    last_solve_time: float | None = None
    anchor_time: float | None = None
    anchor_source: str | None = None
    pose: np.ndarray | None = None
    world: np.ndarray = field(default_factory=lambda: np.empty((0, 3)))
    offset: np.ndarray = field(default_factory=lambda: np.eye(3))
    pending_solve: tuple | None = None

    def align(self, target_id, timestamp, expected_basis, centroids=()):
        if not target_id or not math.isfinite(timestamp):
            raise ValueError("invalid alignment")
        pose = validate_basis(expected_basis).copy()
        self.generation += 1
        self.target_id = str(target_id)
        self.anchor_time = self.last_time = timestamp
        self.anchor_source = "user"
        self.last_frame_id = -1
        self.last_visual_time = self.last_solve_time = None
        self.pose, self.offset = pose, np.eye(3)
        points = clean_centroids(centroids, self.geometry, self.limits.max_points)
        self.world = self.geometry.rays(points) @ pose
        self.pending_solve = None
        self.state = "tracking_predicted"
        return self.generation

    def suspend(self, reason="manual_move"):
        self.generation += 1
        self.state = reason
        self.world = np.empty((0, 3))
        self.pending_solve = None
        self.last_visual_time = None

    def cancel(self):
        self.suspend("idle")
        self.target_id = None
        self.pose = None

    def observe(
        self,
        *,
        generation,
        frame_id,
        timestamp,
        expected_basis,
        centroids=(),
        solved_basis=None,
        moon_yx=None,
    ):
        if (
            generation != self.generation
            or frame_id <= self.last_frame_id
            or not math.isfinite(timestamp)
            or timestamp <= self.last_time
        ):
            return self.status("stale_observation")
        if self.state in {"idle", "manual_move", "geometry_changed", "mount_changed"}:
            return self.status("alignment_required")
        expected = validate_basis(expected_basis)
        points = clean_centroids(centroids, self.geometry, self.limits.max_points)
        predicted = expected @ self.offset
        self.last_frame_id, self.last_time = frame_id, timestamp
        since = timestamp - (
            self.last_visual_time
            if self.last_visual_time is not None
            else self.anchor_time
        )
        measurement, matches, rmse = None, 0, None
        source = "predicted"
        reason = "no_valid_visual_measurement"
        if solved_basis is not None:
            solved_basis = validate_basis(solved_basis)
            large = (
                pose_distance_arcsec(solved_basis, predicted)
                > self.limits.recovery_arcsec
            )
            confirmed = (
                self.pending_solve is not None
                and timestamp - self.pending_solve[0] <= 10
                and pose_distance_arcsec(expected @ self.pending_solve[1], solved_basis)
                <= self.limits.confirmation_arcsec
            )
            if not large or confirmed:
                measurement, source = solved_basis, "solve"
                self.last_solve_time = timestamp
                self.pending_solve = None
            else:
                self.pending_solve = timestamp, expected.T @ solved_basis
                reason = "confirming_solve_jump"
        else:
            self.pending_solve = None
        if measurement is None and since <= self.limits.max_gap_s:
            measurement, matches, rmse = fit_star_pose(
                self.world, points, predicted, self.geometry, self.limits
            )
            if measurement is not None:
                source = "stars"
            elif moon_yx is not None:
                moon = np.asarray(moon_yx, dtype=float)
                if (
                    moon.shape == (2,)
                    and np.isfinite(moon).all()
                    and np.linalg.norm(moon - self.geometry.target_yx)
                    <= self.limits.search_px
                ):
                    target_world = (
                        self.geometry.rays([self.geometry.target_yx])[0] @ expected
                    )
                    measured_world = self.geometry.rays([moon])[0] @ predicted
                    measurement = (
                        predicted @ rotation_between(measured_world, target_world).T
                    )
                    source = "moon"
        if measurement is not None:
            self.pose = measurement.copy()
            self.offset = expected.T @ measurement
            self.last_visual_time = timestamp
            self.state = "tracking_solved" if source == "solve" else "tracking_visual"
            if source == "solve":
                self.anchor_source, self.anchor_time = "solve", timestamp
                self.world = self.geometry.rays(points) @ measurement
            elif not len(self.world) and len(points) >= 3:
                self.world = self.geometry.rays(points) @ measurement
            reason = "observed"
        else:
            self.pose = predicted
            self.state = (
                "uncertain" if since > self.limits.max_gap_s else "tracking_predicted"
            )
            # Acquiring the first star reference after a blind alignment is a
            # prediction, never an independent confirmation of that alignment.
            if (
                not len(self.world)
                and len(points) >= 3
                and since <= self.limits.max_gap_s
            ):
                self.world = self.geometry.rays(points) @ predicted
                reason = "reference_acquired_unverified"
        target_world = self.geometry.rays([self.geometry.target_yx])[0] @ expected
        target_now = self.geometry.project([target_world], self.pose)[0]
        residual = target_now - np.asarray(self.geometry.target_yx)
        if not np.isfinite(residual).all():
            self.state, reason = "uncertain", "target_outside_projection"
        result = self.status(reason)
        result.update(
            source=source,
            matches=matches,
            rmse_px=rmse,
            residual_yx_px=residual.tolist() if np.isfinite(residual).all() else None,
            estimate_radec=list(
                vector_radec(
                    self.geometry.rays([self.geometry.target_yx])[0] @ self.pose
                )
            ),
            observation_age_s=(
                timestamp - self.last_visual_time
                if self.last_visual_time is not None
                else None
            ),
            roll_measured=source in {"solve", "stars"},
        )
        return result

    def status(self, reason=""):
        return {
            "generation": self.generation,
            "target_id": self.target_id,
            "state": self.state,
            "reason": reason,
            "frame_id": self.last_frame_id,
            "timestamp": self.last_time if math.isfinite(self.last_time) else None,
            "anchor_source": self.anchor_source,
            "anchor_time": self.anchor_time,
            "last_visual_time": self.last_visual_time,
            "last_solve_time": self.last_solve_time,
            "commands_sent": 0,
        }


def correction_proposal(
    result,
    jacobian_yx_per_ms,
    *,
    mount_type,
    calibration_valid,
    tracking_enabled,
    now,
    max_age_s=2,
    max_pulse_ms=100,
    pier_side=None,
    calibrated_pier_side=None,
):
    """Return diagnostic axis durations only; caller has no mount queue here.

    A measured Jacobian supplies all axis signs. No Alt/Az or GEM sign is
    guessed. A different/unknown GEM side invalidates a side-specific calibration.
    """
    if mount_type not in {"Alt/Az", "EQ"}:
        return None
    if (
        not calibration_valid
        or not tracking_enabled
        or result.get("reason") != "observed"
        or result.get("state") not in {"tracking_visual", "tracking_solved"}
        or result.get("timestamp") is None
        or not 0 <= now - result["timestamp"] <= max_age_s
        or (calibrated_pier_side is not None and pier_side != calibrated_pier_side)
    ):
        return None
    jacobian = np.asarray(jacobian_yx_per_ms, dtype=float)
    residual = np.asarray(result.get("residual_yx_px"), dtype=float)
    if (
        jacobian.shape != (2, 2)
        or residual.shape != (2,)
        or not np.isfinite(jacobian).all()
        or not np.isfinite(residual).all()
        or np.linalg.cond(jacobian) > 100
        or not math.isfinite(max_pulse_ms)
        or max_pulse_ms <= 0
    ):
        return None
    pulse = np.linalg.solve(jacobian, -residual)
    pulse *= min(1, max_pulse_ms / max(np.max(np.abs(pulse)), 1e-12))
    return {
        "mount_type": mount_type,
        "axis_ms": pulse.tolist(),
        "diagnostic_only": True,
    }
