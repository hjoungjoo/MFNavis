"""Catalog-whitelisted RAW ROI measurements for smooth tracking."""

from dataclasses import asdict
import math

import numpy as np
from scipy.spatial import ConvexHull, QhullError

from PiFinder import solver_frame_map as sfm
from PiFinder.mf_wide_distortion import (
    distort_global_centroids,
    undistort_global_centroids,
)
from PiFinder.tracking_contracts import (
    CaptureTiming,
    TrackingContext,
    TrackingMeasurement,
    fingerprint,
)
from PiFinder.visual_tracking import (
    CameraGeometry,
    TrackingLimits,
    fit_star_pose,
    plate_basis,
    sky_vector,
    vector_radec,
)

ARCSEC = 180 * 3600 / math.pi


def tangent_error(current, target):
    """Positive means motion required toward target, in fixed target east/north."""
    basis = plate_basis(*target, 0)
    vector = sky_vector(*current)
    forward = float(vector @ basis[0])
    if forward <= 0:
        raise ValueError("target outside local tangent plane")
    return tuple(-np.arctan2(vector @ basis[1:].T, forward) * ARCSEC)


def corrected_points(points, shape, info):
    coefficients = info.get("distortion_coefficients")
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    if coefficients:
        points = undistort_global_centroids(points, shape, coefficients)
    return sfm.rotate_centroids(points, shape, info["rotation_deg"])[0]


def native_points(points, shape, canvas, info):
    points, _ = sfm.rotate_centroids(points, canvas, -info["rotation_deg"])
    coefficients = info.get("distortion_coefficients")
    return (
        distort_global_centroids(points, shape, coefficients)
        if coefficients
        else points
    )


def spatial_quality(points, target, shape, profile):
    points = np.asarray(points)
    if len(points) < profile.min_stars:
        return "too_few_stars"
    singular = np.linalg.svd(points - points.mean(axis=0), compute_uv=False)
    if singular[-1] <= 0 or singular[0] / singular[-1] > profile.max_condition:
        return "poor_spatial_rank"
    regions = {(int(y >= shape[0] / 2), int(x >= shape[1] / 2)) for y, x in points}
    if len(regions) < profile.min_regions:
        return "poor_spatial_distribution"
    try:
        hull = ConvexHull(points)
        outside = hull.equations[:, :2] @ np.asarray(target) + hull.equations[:, 2]
        if np.max(outside) > min(shape) * 0.05:
            return "target_extrapolation"
    except QhullError:
        return "poor_spatial_rank"
    return ""


def build_reference(solution, metadata, info, raw_shape, target_pixel, camera, profile):
    """Called only after solve acceptance, before the solver strips match arrays."""
    if not solution or not info or metadata.get("synthetic"):
        raise ValueError("no physical accepted solve")
    info = {key: value for key, value in info.items() if key != "warm_map"}
    if float(solution.get("epoch_equinox") or 0) != 2000:
        raise ValueError("unverified catalog equinox")
    points = np.asarray(solution.get("matched_centroids"), dtype=float)
    stars = np.asarray(solution.get("matched_stars"), dtype=float)
    ids = solution.get("matched_catID")
    if (
        points.ndim != 2
        or points.shape[1] != 2
        or stars.ndim != 2
        or stars.shape[1] < 2
        or ids is None
        or len(points) != len(stars)
        or len(ids) != len(points)
    ):
        raise ValueError("missing catalog correspondence")
    identities = [fingerprint(v) for v in ids]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate catalog identities")
    if not np.isfinite(points).all() or not np.isfinite(stars).all():
        raise ValueError("nonfinite catalog correspondence")
    _, canvas = sfm.rotate_centroids([], raw_shape, info["rotation_deg"])
    if tuple(solution.get("_alignment_frame", ())[:2]) != tuple(canvas):
        raise ValueError("solver canvas mismatch")
    # target_pixel lives in distorted rotated-512 space; apply exactly the
    # sensor->ray mapping used for the matched stars.
    target_rotated = sfm.map_target_pixel_to_frame(
        target_pixel, canvas, info["crop_width_px"]
    )
    target_native, _ = sfm.rotate_centroids(
        [target_rotated], canvas, -info["rotation_deg"]
    )
    target_corrected = corrected_points(target_native, raw_shape, info)[0]
    geometry = CameraGeometry(
        *canvas, float(solution["FOV"]), tuple(target_corrected), fingerprint(info)
    )
    # Select a bounded, spatially distributed subset rather than brightest-only.
    order = sorted(range(len(points)), key=lambda i: (identities[i]))[
        : profile.max_stars
    ]
    points, stars = points[order], stars[order]
    identities = [identities[i] for i in order]
    reason = spatial_quality(points, target_corrected, canvas, profile)
    if reason:
        raise ValueError(reason)
    basis = plate_basis(solution["RA"], solution["Dec"], solution["Roll"])
    world = np.asarray([sky_vector(*row[:2]) for row in stars])
    limits = TrackingLimits(
        search_px=profile.roi_radius_px, residual_px=profile.max_rmse_px
    )
    fitted, matches, rmse = fit_star_pose(world, points, basis, geometry, limits)
    if fitted is None or matches < profile.min_stars:
        raise ValueError("catalog ray fit rejected")
    key = fingerprint(
        {"info": info, "shape": raw_shape, "target": target_pixel, "camera": camera}
    )
    return {
        "id": fingerprint(
            [metadata["capture_epoch"], metadata["capture_sequence"], identities]
        ),
        "capture_epoch": metadata["capture_epoch"],
        "sequence": metadata["capture_sequence"],
        "timing": metadata["tracking_timing"],
        "capture_identity": {
            key: metadata.get(key)
            for key in (
                "camera_type",
                "capture_backend",
                "sensor_timestamp_ns",
                "actual_exposure_us",
                "actual_gain",
            )
        },
        "geometry": asdict(geometry),
        "geometry_key": key,
        "raw_shape": tuple(raw_shape),
        "info": dict(info),
        "target_pixel": tuple(target_pixel),
        "camera": camera,
        "world": world.tolist(),
        "points": points.tolist(),
        "ids": identities,
        "pose": fitted.tolist(),
        "rmse_px": rmse,
        "absolute_bound": max(
            float(solution.get("RMSE") or 0), profile.reference_bound_arcsec
        ),
        "catalog_epoch": 2000,
    }


def extract_rois(raw, centers, radius):
    """Copy only bounded patches before manager serialization."""
    frame = np.asarray(raw)
    if frame.ndim != 2:
        raise ValueError("monochrome RAW required")
    patches = []
    for y, x in centers:
        if not np.isfinite([y, x]).all():
            patches.append(None)
            continue
        cy, cx = round(y), round(x)
        y0, x0 = cy - radius, cx - radius
        if (
            y0 < 0
            or x0 < 0
            or cy + radius >= frame.shape[0]
            or cx + radius >= frame.shape[1]
        ):
            patches.append(None)
            continue
        patches.append(
            {
                "origin": (y0, x0),
                "pixels": frame[y0 : cy + radius + 1, x0 : cx + radius + 1].copy(),
            }
        )
    return patches


def centroid(patch, profile, saturation, *, counts=None):
    """Measure a clean star and optionally count why a bounded ROI was rejected."""

    def counted(reason, result=None):
        if counts is not None:
            counts[reason] = counts.get(reason, 0) + 1
        return result

    if patch is None:
        return counted("outside_frame")
    image = np.asarray(patch["pixels"], dtype=float)
    if not np.isfinite(image).all():
        return counted("invalid_pixels")
    if image.max() >= saturation:
        return counted("saturated")
    edge = np.concatenate([image[0], image[-1], image[1:-1, 0], image[1:-1, -1]])
    background = np.median(edge)
    noise = max(1.0, 1.4826 * np.median(np.abs(edge - background)))
    peak = np.unravel_index(np.argmax(image), image.shape)
    if min(*peak, image.shape[0] - 1 - peak[0], image.shape[1] - 1 - peak[1]) < 3:
        return counted("edge_peak")
    yy, xx = np.indices(image.shape)
    region = (yy - peak[0]) ** 2 + (xx - peak[1]) ** 2 <= 16
    weight = np.where(region, np.maximum(image - background - 2 * noise, 0), 0)
    flux = weight.sum()
    if flux <= 0 or (image[peak] - background) / noise < profile.min_snr:
        return counted("low_signal")
    center = np.array([(weight * yy).sum(), (weight * xx).sum()]) / flux
    dy, dx = yy - center[0], xx - center[1]
    cov = (
        np.array(
            [
                [(weight * dy * dy).sum(), (weight * dy * dx).sum()],
                [(weight * dy * dx).sum(), (weight * dx * dx).sum()],
            ]
        )
        / flux
    )
    values = np.linalg.eigvalsh(cov)
    if (
        values[0] < 0.15
        or values[-1] > profile.max_width_px**2
        or values[-1] / values[0] > profile.max_elongation**2
    ):
        return counted("invalid_shape")
    # Competing bright points elsewhere in the ROI invalidate identity.
    if np.any(
        (~region)
        & (image > background + max(6 * noise, (image[peak] - background) * 0.6))
    ):
        return counted("competing_sources")
    return counted("accepted", center + patch["origin"])


class StarTracker:
    def __init__(self, reference, request, profile):
        self.reference, self.request, self.profile = reference, request, profile
        self.geometry = CameraGeometry(**reference["geometry"])
        self.pose = np.asarray(reference["pose"])
        self.context = TrackingContext(
            request["session"],
            reference["geometry_key"],
            reference["capture_epoch"],
            request["connection"],
            request["control"],
            reference["id"],
            tuple(request["target"]),
        )
        self.last_sequence = -1
        self.last_exposure = None
        self.local_world = None
        self.local_indices = None
        self.local_bound = None

    def roi_request(self):
        corrected = self.geometry.project(
            self.reference["world"] if self.local_world is None else self.local_world,
            self.pose,
        )
        centers = native_points(
            corrected,
            self.reference["raw_shape"],
            (self.geometry.height, self.geometry.width),
            self.reference["info"],
        )
        return {
            "session": self.context.session,
            "reference": self.context.reference,
            "centers": centers.tolist(),
            "radius": self.profile.roi_radius_px,
            "capture_epoch": self.context.capture_epoch,
        }

    def measure(self, frame, now):
        metadata = frame["metadata"]
        timing = CaptureTiming(**metadata["tracking_timing"])
        seq = int(metadata["capture_sequence"])
        base = dict(
            context=self.context,
            sequence=seq,
            timing=timing,
            error=(0.0, 0.0),
            bound_arcsec=self.profile.max_error_bound_arcsec,
            quality="invalid",
            reason="unknown",
        )

        def reject(reason):
            return TrackingMeasurement(**{**base, "reason": reason})

        if metadata["capture_epoch"] != self.context.capture_epoch:
            return reject("capture_epoch_changed")
        if (
            frame.get("raw_shape", self.reference["raw_shape"])
            != self.reference["raw_shape"]
        ):
            return reject("sensor_mode_changed")
        if metadata.get("synthetic"):
            return reject("synthetic_frame")
        if (
            self.request["mode"] == "active"
            and self.profile.camera != self.reference["camera"]
        ):
            return reject("camera_profile_changed")
        if seq <= self.last_sequence:
            return reject("stale_frame")
        self.last_sequence = seq
        ref_time = CaptureTiming(**self.reference["timing"])
        if not 0 <= now - ref_time.midpoint <= self.profile.reference_valid_s:
            return reject("absolute_reference_expired")
        if timing.clock_epoch != ref_time.clock_epoch:
            return reject("clock_epoch_changed")
        if self.request["mode"] == "active" and not timing.usable(
            now, self.profile.max_age_s, self.profile.max_timing_uncertainty_s
        ):
            return reject("timing_unknown_or_stale")
        if timing.start_min < self.request["started_mono"]:
            return reject("pre_session_exposure")
        exposure = (metadata.get("actual_exposure_us"), metadata.get("actual_gain"))
        if any(v is None or not math.isfinite(float(v)) for v in exposure):
            return reject("exposure_unknown")
        changed = self.last_exposure is not None and exposure != self.last_exposure
        self.last_exposure = exposure
        if changed:
            return reject("exposure_transition")
        if frame.get("reference") != self.context.reference:
            return reject("roi_reference_changed")
        points, indices = [], []
        counts = {}
        for i, patch in enumerate(frame["patches"]):
            if self.local_indices is not None and i not in self.local_indices:
                continue
            measured = centroid(
                patch,
                self.profile,
                self.reference["info"]["saturation_level"],
                counts=counts,
            )
            if measured is not None:
                points.append(measured)
                indices.append(i)
        base.update(stars=len(points), roi_counts=counts)
        if len(points) < self.profile.min_stars:
            return reject("stars_lost_or_ambiguous")
        points = corrected_points(
            points, self.reference["raw_shape"], self.reference["info"]
        )
        reason = spatial_quality(
            points,
            self.geometry.target_yx,
            (self.geometry.height, self.geometry.width),
            self.profile,
        )
        if reason:
            return reject(reason)
        world = np.asarray(
            self.reference["world"] if self.local_world is None else self.local_world
        )[indices]
        limits = TrackingLimits(
            search_px=self.profile.roi_radius_px, residual_px=self.profile.max_rmse_px
        )
        pose, count, rmse = fit_star_pose(
            world, points, self.pose, self.geometry, limits
        )
        if pose is None or count < self.profile.min_stars:
            return reject("inconsistent_star_motion")
        # Reject poor INLIER distribution as well as input distribution.
        residual = np.linalg.norm(self.geometry.project(world, pose) - points, axis=1)
        inliers = points[residual <= self.profile.max_rmse_px]
        reason = spatial_quality(
            inliers,
            self.geometry.target_yx,
            (self.geometry.height, self.geometry.width),
            self.profile,
        )
        if reason:
            return reject(reason)
        aligned = vector_radec(self.geometry.rays([self.geometry.target_yx])[0] @ pose)
        camera = vector_radec(pose[0])
        base_axes = plate_basis(*camera, 0)
        roll = math.degrees(
            math.atan2(float(pose[1] @ base_axes[2]), float(pose[1] @ base_axes[1]))
        )
        scale = ARCSEC / self.geometry.focal
        bound = (
            self.reference["absolute_bound"]
            if self.local_bound is None
            else self.local_bound
        ) + max(0.1, rmse) * scale
        if bound > self.profile.max_error_bound_arcsec:
            return reject("uncertainty_exceeds_budget")
        self.pose = pose
        relative_bound = None
        if self.profile.robust_tracking:
            # Anchor only catalog-confirmed inliers, using the same RAW
            # centroid method as subsequent video. Catalog/lens offsets stay
            # in the absolute bound instead of changing with each star subset.
            if self.local_world is None:
                mask = residual <= self.profile.max_rmse_px
                self.local_world = np.asarray(self.reference["world"]).copy()
                selected = np.asarray(indices)[mask]
                self.local_world[selected] = self.geometry.rays(points[mask]) @ pose
                self.local_indices = set(selected.tolist())
                self.local_bound = bound
            relative_bound = max(0.5, 3 * max(0.05, rmse) * scale / math.sqrt(count))
        expected_stars = (
            len(self.local_indices)
            if self.local_indices is not None
            else len(self.reference["world"])
        )
        degraded = (
            count < expected_stars * 0.75 or rmse > self.profile.max_rmse_px * 0.7
        )
        return TrackingMeasurement(
            **{
                **base,
                "error": tangent_error(aligned, self.context.target),
                "bound_arcsec": bound,
                "quality": "degraded" if degraded else "valid",
                "reason": "reduced_star_confidence" if degraded else "catalog_stars",
                "camera_radec_roll": (*camera, roll),
                "aligned_radec": aligned,
                "stars": count,
                "rmse_px": rmse,
                "exposure": exposure,
                "relative_bound_arcsec": relative_bound,
            },
        )
