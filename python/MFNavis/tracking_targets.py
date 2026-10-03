"""Target-aware measurements sharing the existing bounded pulse controller.

Local anchors carry no catalog identity and never publish absolute pointing.
Body centres observe two axes only; field stars observe the camera rotation.
"""

from dataclasses import asdict
from collections import deque
import math
import time

import numpy as np
from scipy import ndimage

from PiFinder import solver_frame_map as sfm
from PiFinder.tracking_contracts import (
    CaptureTiming,
    TrackingContext,
    TrackingMeasurement,
    fingerprint,
)
from PiFinder.tracking_quality import (
    ARCSEC,
    centroid,
    corrected_points,
    native_points,
    spatial_quality,
)
from PiFinder.visual_tracking import (
    CameraGeometry,
    TrackingLimits,
    fit_star_pose,
    plate_basis,
    rotation_between,
    vector_radec,
)
from PiFinder.visual_tracking_images import measure_moon
from PiFinder.visual_tracking_target import TrackingTarget


def publish_seed(shared, metadata, info, raw, run, *, moving, success, confirming):
    """Reuse the existing RAW detector; never extract stars a second time."""
    timing = metadata.get("tracking_timing") or {}
    if not timing or metadata.get("synthetic") or moving:
        return
    shared.tracking_alignment(
        "attempt",
        dict(
            start_mono=timing["start_min"],
            end_mono=timing["end_max"],
            success=success,
            terminal=not success and not confirming,
        ),
    )
    if raw is None or info is None or raw.get("frame_id") != metadata.get("frame_id"):
        return
    points = []
    if run is not None and run.frame_id == metadata.get("frame_id"):
        points = np.asarray(run.detection.centroids, dtype=float)[:128].tolist()
    shared.tracking_alignment(
        "seed",
        dict(
            metadata=metadata,
            raw_shape=tuple(raw["frame"].shape),
            info={k: v for k, v in info.items() if k != "warm_map"},
            points=points,
        ),
    )


def astronomical_time(request, wall):
    return request["astronomical_time"] + wall - request["wall_time"]


def local_optical_candidate(shared, cfg):
    """Read-only optical snapshot for equipment-profile review; never arm it."""
    from PiFinder.alignment_projection import current_solved_target_pixel
    from PiFinder.smooth_tracking_runtime import optics_identity

    ref = shared.smooth_tracking()["reference"]
    if not ref or tuple(ref["target_pixel"]) != tuple(shared.target_pixel()):
        return None
    plate = getattr(shared.solution(), "alignment_projection", None) or {}
    if ref["timing"] != plate.get("tracking_timing"):
        return None
    geometry = CameraGeometry(**ref["geometry"])
    pose = np.asarray(ref["pose"])
    aligned = vector_radec(geometry.rays([geometry.target_yx])[0] @ pose)
    try:
        ledger = shared.tracking_alignment()
        if ledger["correction_moving"] or ledger["pose_after"] > time.monotonic():
            return None
        current_solved_target_pixel(
            shared,
            cfg,
            *aligned,
            motion=dict(ledger["motion"], pose_after=ledger["pose_after"]),
        )
    except (LookupError, ValueError, TypeError, KeyError):
        return None
    camera = vector_radec(pose[0])
    axes = plate_basis(*camera, 0)
    roll = math.degrees(math.atan2(float(pose[1] @ axes[2]), float(pose[1] @ axes[1])))
    return dict(
        verified=False,
        optics=optics_identity(cfg, shared),
        raw_shape=ref["raw_shape"],
        info=ref["info"],
        fov_deg=geometry.fov_deg,
        roll_deg=roll,
        bound_arcsec=ref["absolute_bound"],
        roll_target=aligned,
        roll_timestamp=shared.datetime().timestamp()
        - time.time()
        + ref["timing"]["wall_midpoint"],
    )


def initial_reference(seed, request, profile, ephemeris, catalog=None):
    """A fresh accepted plate or a separately verified local optical model."""
    metadata, info, shape = seed["metadata"], seed["info"], seed["raw_shape"]
    timing = CaptureTiming(**metadata["tracking_timing"])
    if timing.start_min < request["started_mono"]:
        raise LookupError("waiting_post_alignment_frame")
    pixel = request["target_pixel"]
    _, canvas = sfm.rotate_centroids([], shape, info["rotation_deg"])
    distorted = sfm.map_target_pixel_to_frame(pixel, canvas, info["crop_width_px"])
    native, _ = sfm.rotate_centroids([distorted], canvas, -info["rotation_deg"])
    target_yx = corrected_points(native, shape, info)[0]
    key = fingerprint(
        dict(info=info, shape=shape, target=pixel, camera=request["camera"])
    )
    target = TrackingTarget(**request["tracking_target"])
    stamp = astronomical_time(request, timing.wall_midpoint)
    current_target = ephemeris.position(target, stamp)
    accepted = bool(
        catalog
        and catalog["capture_epoch"] == metadata["capture_epoch"]
        and (
            catalog["timing"]["start_min"] >= request["started_mono"]
            or catalog["id"] == request.get("accepted_reference_id")
        )
        and tuple(catalog["raw_shape"]) == tuple(shape)
        and catalog["info"] == info
        and 0 <= timing.midpoint - catalog["timing"]["midpoint"] <= profile.max_age_s
    )
    if accepted:
        fov = catalog["geometry"]["fov_deg"]
        pose = np.asarray(catalog["pose"])
        camera = vector_radec(pose[0])
        axes = plate_basis(*camera, 0)
        roll = math.degrees(
            math.atan2(float(pose[1] @ axes[2]), float(pose[1] @ axes[1]))
        )
        bound = catalog["absolute_bound"]
        world, points = catalog["world"], catalog["points"]
    else:
        local = profile.local_reference
        if not local.get("verified"):
            raise LookupError("verified_local_optics_required")
        if local.get("optics") != request["optics"]:
            raise ValueError("local_optics_changed")
        if tuple(local.get("raw_shape", ())) != tuple(shape):
            raise ValueError("local_sensor_mode_changed")
        if local.get("info") != info:
            raise ValueError("local_projection_changed")
        fov, roll = float(local["fov_deg"]), float(local["roll_deg"])
        bound = float(local["bound_arcsec"])
        if not math.isfinite(bound) or not 0 < bound <= profile.max_error_bound_arcsec:
            raise ValueError("invalid_local_reference_bound")
        if profile.mount_type == "Alt/Az":
            baseline = local["roll_target"]
            roll += ephemeris._horizon_roll(
                *current_target, stamp
            ) - ephemeris._horizon_roll(*baseline, float(local["roll_timestamp"]))
        points = corrected_points(seed["points"], shape, info).tolist()
        world = None
    geometry = CameraGeometry(*canvas, fov, tuple(target_yx), fingerprint(info))
    nominal = geometry.aligned_basis(*current_target, roll)
    if not accepted:
        if target.body:
            # Moving bodies are never part of the fixed background-ray list.
            radius = geometry.focal * math.tan(ephemeris.angular_radius(target, stamp))
            points = [
                p
                for p in points
                if np.linalg.norm(np.asarray(p) - target_yx)
                > max(radius * 1.5, profile.roi_radius_px * 2)
            ]
        if not target.body and spatial_quality(points, target_yx, canvas, profile):
            raise LookupError("waiting_distributed_stars")
        pose = nominal
        world = (geometry.rays(points) @ pose).tolist()
    if request["mode"] == "active" and key != profile.geometry:
        raise ValueError("equipment_or_geometry_changed")
    return dict(
        id=fingerprint(
            [
                request["session"],
                metadata["capture_epoch"],
                metadata["capture_sequence"],
            ]
        ),
        kind="catalog_solve" if accepted else "user_star_anchor",
        capture_epoch=metadata["capture_epoch"],
        sequence=metadata["capture_sequence"],
        timing=asdict(timing),
        geometry=asdict(geometry),
        geometry_key=key,
        raw_shape=tuple(shape),
        info=info,
        target_pixel=tuple(pixel),
        camera=request["camera"],
        pose=pose.tolist(),
        world=world,
        points=points,
        absolute_bound=bound,
        alignment_roll=roll,
        alignment_timestamp=stamp,
    )


def measure_planet(patch, expected, profile, saturation):
    """A compact, symmetric target; reject moons, clipping and bright ambiguity.

    Compare centres at independent brightness thresholds. A clipped saturated
    core may be usable only when its surrounding shape remains symmetric.
    """
    if patch is None:
        return None
    image = np.asarray(patch["pixels"], dtype=float)
    if not np.isfinite(image).all():
        return None
    edge = np.r_[image[0], image[-1], image[:, 0], image[:, -1]]
    background = float(np.median(edge))
    noise = max(1.0, float(1.4826 * np.median(np.abs(edge - background))))
    signal = np.maximum(image - background, 0)
    if signal.max() < profile.min_snr * noise:
        return None
    centers = []
    for fraction in (0.2, 0.4, 0.7):
        mask = signal > max(6 * noise, signal.max() * fraction)
        labels, count = ndimage.label(mask)
        sizes = np.bincount(labels.ravel())
        if count < 1:
            return None
        sizes[0] = 0
        largest = int(np.argmax(sizes))
        # An unresolved satellite outside the principal blob is ambiguous.
        if sizes[largest] < 4 or sum(sizes > max(2, sizes[largest] * 0.1)) != 1:
            return None
        yy, xx = np.nonzero(labels == largest)
        if min(yy.min(), xx.min()) < 2 or (
            yy.max() >= image.shape[0] - 2 or xx.max() >= image.shape[1] - 2
        ):
            return None
        center = np.array([yy.mean(), xx.mean()])
        offsets = np.column_stack((yy, xx)) - center
        singular = np.linalg.svd(offsets, compute_uv=False)
        if singular[-1] <= 0 or singular[0] / singular[-1] > 3:
            return None
        reflected = np.rint(2 * center - np.column_stack((yy, xx))).astype(int)
        if np.any(reflected < 0) or np.any(reflected >= image.shape):
            return None
        if np.mean(mask[reflected[:, 0], reflected[:, 1]]) < 0.9:
            return None
        centers.append(center)
    center = np.mean(centers, axis=0) + patch["origin"]
    scatter = float(
        np.max(np.linalg.norm(np.asarray(centers) - np.mean(centers, axis=0), axis=1))
    )
    if scatter > 0.5 or np.linalg.norm(center - expected) > profile.roi_radius_px:
        return None
    return dict(center_yx=center, rmse_px=max(0.25, scatter))


class TargetTracker:
    def __init__(self, reference, request, profile, ephemeris):
        self.reference, self.request, self.profile = reference, request, profile
        self.ephemeris = ephemeris
        self.target = TrackingTarget(**request["tracking_target"])
        self.geometry = CameraGeometry(**reference["geometry"])
        self.context = TrackingContext(
            request["session"],
            reference["geometry_key"],
            reference["capture_epoch"],
            request["connection"],
            request["control"],
            reference["id"],
            tuple(request["target"]),
        )
        self.axes = plate_basis(*self.context.target, 0)
        self.pose = np.asarray(reference["pose"])
        self.nominal = self.predict(reference["timing"]["wall_midpoint"])
        self.last_wall = reference["timing"]["wall_midpoint"]
        self.last_sequence = -1
        self.last_exposure = None
        self.last_valid = reference["timing"]["midpoint"]
        self.last_solve = (
            reference["sequence"] if reference["kind"] == "catalog_solve" else -1
        )
        self.solve_candidate = None
        self.measurement_source = None
        self.stars_ready = False
        self.pending_catalog = None
        self.source_candidate = None
        self.pose_history = deque(maxlen=64)
        self.pending_seed = None

    def predict(self, wall):
        return self.ephemeris.basis(
            self.target,
            astronomical_time(self.request, wall),
            self.geometry,
            mount_type=self.profile.mount_type,
            alignment_timestamp=self.reference["alignment_timestamp"],
            alignment_roll_deg=self.reference["alignment_roll"],
        )

    def roi_request(self):
        native = native_points(
            self.geometry.project(self.reference["world"], self.pose),
            self.reference["raw_shape"],
            (self.geometry.height, self.geometry.width),
            self.reference["info"],
        )
        body_center = native_points(
            [self.geometry.target_yx],
            self.reference["raw_shape"],
            (self.geometry.height, self.geometry.width),
            self.reference["info"],
        )[0]
        request = dict(
            session=self.context.session,
            reference=self.context.reference,
            capture_epoch=self.context.capture_epoch,
            centers=native[: self.profile.max_stars].tolist(),
            radius=self.profile.roi_radius_px,
        )
        if self.target.body:
            angular = self.ephemeris.angular_radius(
                self.target, astronomical_time(self.request, self.last_wall)
            )
            self.radius = self.geometry.focal * math.tan(angular)
            extent = math.ceil(self.radius * 1.2 + self.profile.roi_radius_px + 5)
            if not 2 <= extent <= 256:
                raise ValueError("body_roi_exceeds_budget")
            request.update(body_center=body_center.tolist(), body_radius=extent)
        return request

    def adopt_solve(self, catalog):
        # Keep the context and the user holding pixel. The new absolute rays
        # are adopted only after a temporally matching, consistent measurement.
        if catalog and catalog["sequence"] > self.last_solve:
            self.pending_catalog = catalog

    def offer_seed(self, seed):
        if seed and seed["metadata"].get("capture_epoch") == self.context.capture_epoch:
            self.pending_seed = seed

    def _acquire_background(self):
        """Anchor newly visible stars to a measured body pose at their exposure.

        A late detector result can use a bounded history of measured poses;
        it cannot assign the current pose to an older star exposure.
        """
        seed = self.pending_seed
        if self.stars_ready or not self.target.body or seed is None:
            return
        if (
            seed["info"] != self.reference["info"]
            or tuple(seed["raw_shape"]) != self.reference["raw_shape"]
        ):
            return
        key = seed["metadata"]["capture_sequence"]
        match = next((p for p in reversed(self.pose_history) if p[0] == key), None)
        if match is None:
            return
        points = corrected_points(
            seed["points"], self.reference["raw_shape"], self.reference["info"]
        )
        target_world = self.geometry.rays([self.geometry.target_yx])[0] @ self.predict(
            match[2]
        )
        target = self.geometry.project([target_world], match[1])[0]
        points = points[
            np.linalg.norm(points - target, axis=1)
            > max(self.radius * 1.5, self.profile.roi_radius_px * 2)
        ]
        reason = spatial_quality(
            points,
            self.geometry.target_yx,
            (self.geometry.height, self.geometry.width),
            self.profile,
        )
        if reason:
            return
        self.reference["world"] = (self.geometry.rays(points) @ match[1]).tolist()
        self.reference["absolute_bound"] = max(
            self.reference["absolute_bound"], match[3]
        )
        self.reference["kind"] = "user_star_anchor"
        self.pending_seed = None

    def error(self, pose, nominal):
        ray = self.geometry.rays([self.geometry.target_yx])[0]
        return tuple(((ray @ nominal - ray @ pose) @ self.axes[1:].T) * ARCSEC)

    def measure(self, frame, now):
        metadata = frame["metadata"]
        timing = CaptureTiming(**metadata["tracking_timing"])
        seq = int(metadata["capture_sequence"])
        base = dict(
            context=self.context,
            sequence=seq,
            timing=timing,
            error=(0.0, 0.0),
            quality="invalid",
            reason="unknown",
            bound_arcsec=self.profile.max_error_bound_arcsec,
            source="target_video",
            degrees_of_freedom=2,
        )

        def reject(reason):
            return TrackingMeasurement(**dict(base, reason=reason))

        if metadata["capture_epoch"] != self.context.capture_epoch:
            return reject("capture_epoch_changed")
        if tuple(frame["raw_shape"]) != self.reference["raw_shape"]:
            return reject("sensor_mode_changed")
        if metadata.get("synthetic") or seq <= self.last_sequence:
            return reject("synthetic_or_stale_frame")
        self.last_sequence = seq
        if timing.clock_epoch != self.reference["timing"]["clock_epoch"]:
            return reject("clock_epoch_changed")
        if (
            not timing.usable(
                now, self.profile.max_age_s, self.profile.max_timing_uncertainty_s
            )
            or timing.start_min < self.request["started_mono"]
        ):
            return reject("timing_unknown_or_stale")
        if frame["reference"] != self.context.reference:
            return reject("roi_reference_changed")
        exposure = metadata.get("actual_exposure_us"), metadata.get("actual_gain")
        if any(v is None or not math.isfinite(float(v)) for v in exposure):
            return reject("exposure_unknown")
        changed = self.last_exposure is not None and exposure != self.last_exposure
        self.last_exposure = exposure
        if changed:
            return reject("exposure_transition")
        if now - self.last_valid > self.profile.reference_valid_s:
            return reject("correspondence_gap_exceeded")
        nominal = self.predict(timing.wall_midpoint)
        predicted = self.pose @ self.nominal.T @ nominal
        candidates = []
        catalog = self.pending_catalog
        adopted = False
        if (
            catalog
            and catalog["capture_epoch"] == self.context.capture_epoch
            and (
                self.last_solve < catalog["sequence"] <= seq
                and catalog["geometry_key"] == self.context.geometry
                and catalog["timing"]["start_min"] >= self.request["started_mono"]
                and timing.clock_epoch == catalog["timing"]["clock_epoch"]
                and 0 <= now - catalog["timing"]["midpoint"] <= self.profile.max_age_s
            )
        ):
            solved_nominal = self.predict(catalog["timing"]["wall_midpoint"])
            predicted_then = self.pose @ self.nominal.T @ solved_nominal
            # Preserve visual progress after a late plate; do not roll the
            # current observation back to the plate's exposure epoch.
            pose = np.asarray(catalog["pose"]) @ predicted_then.T @ predicted
            discrepancy = np.linalg.norm(
                np.asarray(self.error(pose, nominal)) - self.error(predicted, nominal)
            )
            if discrepancy > self.profile.max_error_bound_arcsec:
                if (
                    self.solve_candidate is None
                    or np.linalg.norm(
                        np.asarray(self.error(pose, nominal)) - self.solve_candidate[1]
                    )
                    > self.profile.max_error_bound_arcsec
                ):
                    self.solve_candidate = (
                        catalog["sequence"],
                        np.asarray(self.error(pose, nominal)),
                    )
                    return reject("solve_jump_confirmation")
                if catalog["sequence"] == self.solve_candidate[0]:
                    return reject("solve_jump_confirmation")
            self.solve_candidate = None
            candidates.append(
                (
                    "catalog_solve",
                    pose,
                    catalog["absolute_bound"],
                    catalog.get("rmse_px", 0),
                    len(catalog["world"]),
                )
            )
            self.last_solve = seq
            self.pending_catalog = None
            self.reference["world"] = catalog["world"]
            self.reference["kind"] = "catalog_solve"
            adopted = True
        patches = [] if adopted else frame["patches"][: len(self.reference["world"])]
        points, indices = [], []
        for i, patch in enumerate(patches):
            point = centroid(
                patch, self.profile, self.reference["info"]["saturation_level"]
            )
            if point is not None:
                points.append(point)
                indices.append(i)
        points = corrected_points(
            points, self.reference["raw_shape"], self.reference["info"]
        )
        reason = spatial_quality(
            points,
            self.geometry.target_yx,
            (self.geometry.height, self.geometry.width),
            self.profile,
        )
        if not reason:
            world = np.asarray(self.reference["world"])[indices]
            pose, count, rmse = fit_star_pose(
                world,
                points,
                predicted,
                self.geometry,
                TrackingLimits(
                    search_px=self.profile.roi_radius_px,
                    residual_px=self.profile.max_rmse_px,
                ),
            )
            if pose is not None and count >= self.profile.min_stars:
                residuals = np.linalg.norm(
                    self.geometry.project(world, pose) - points, axis=1
                )
                reason = spatial_quality(
                    points[residuals <= self.profile.max_rmse_px],
                    self.geometry.target_yx,
                    (self.geometry.height, self.geometry.width),
                    self.profile,
                )
                if not reason:
                    bound = (
                        self.reference["absolute_bound"]
                        + max(0.1, rmse) * ARCSEC / self.geometry.focal
                    )
                    candidates.append(
                        (
                            "catalog_stars"
                            if self.reference["kind"] == "catalog_solve"
                            else "user_star_anchor",
                            pose,
                            bound,
                            rmse,
                            count,
                        )
                    )
                    self.stars_ready = True
        if self.target.body:
            patch = frame.get("body_patch")
            expected = native_points(
                [self.geometry.target_yx],
                self.reference["raw_shape"],
                (self.geometry.height, self.geometry.width),
                self.reference["info"],
            )[0]
            body = None
            if patch is not None:
                if self.target.body == "MOON":
                    # Correct every pixel in the limb ROI into a rectilinear
                    # sensor canvas before circle fitting, including distortion.
                    image = rectified_patch(
                        patch, self.reference["raw_shape"], self.reference["info"]
                    )
                    expected_corrected = corrected_points(
                        [expected], self.reference["raw_shape"], self.reference["info"]
                    )[0]
                    center = expected_corrected - image["origin"]
                    body = measure_moon(
                        image["pixels"],
                        center,
                        self.radius,
                        search_px=self.profile.roi_radius_px,
                    )
                    if body:
                        angles = np.linspace(0, 2 * np.pi, 72, endpoint=False)
                        rim = np.asarray(body["center_yx"])[:, None] + body[
                            "radius_px"
                        ] * np.array([np.sin(angles), np.cos(angles)])
                        valid = ndimage.map_coordinates(
                            image["valid"].astype(float),
                            rim,
                            order=0,
                            mode="constant",
                            cval=0,
                        )
                        outer = np.asarray(body["center_yx"])[:, None] + body[
                            "radius_px"
                        ] * 1.12 * np.array([np.sin(angles), np.cos(angles)])
                        brightness = ndimage.map_coordinates(
                            image["pixels"],
                            outer,
                            order=1,
                            mode="constant",
                            cval=self.reference["info"]["saturation_level"],
                        )
                        if np.any(valid < 1) or np.percentile(brightness, 90) >= (
                            self.reference["info"]["saturation_level"] * 0.95
                        ):
                            body = None
                        else:
                            body["center_yx"] = (
                                np.asarray(body["center_yx"]) + image["origin"]
                            )
                else:
                    body = measure_planet(
                        patch,
                        expected,
                        self.profile,
                        self.reference["info"]["saturation_level"],
                    )
                    if body:
                        body["center_yx"] = corrected_points(
                            [body["center_yx"]],
                            self.reference["raw_shape"],
                            self.reference["info"],
                        )[0]
            if body:
                observed = self.geometry.rays([body["center_yx"]])[0] @ nominal
                wanted = self.geometry.rays([self.geometry.target_yx])[0] @ nominal
                pose = nominal @ rotation_between(observed, wanted).T
                bound = (
                    self.reference["absolute_bound"]
                    + max(0.15, body["rmse_px"]) * ARCSEC / self.geometry.focal
                )
                candidates.append(
                    (
                        "moon_limb" if self.target.body == "MOON" else "planet_center",
                        pose,
                        bound,
                        body["rmse_px"],
                        0,
                    )
                )
        candidates = [
            c for c in candidates if c[2] <= self.profile.max_error_bound_arcsec
        ]
        if not candidates:
            return reject(
                "moon_limb_unavailable"
                if self.target.body == "MOON"
                else "target_video_unavailable"
            )
        if any(
            np.linalg.norm(
                np.asarray(self.error(c[1], nominal))
                - self.error(candidates[0][1], nominal)
            )
            > self.profile.max_error_bound_arcsec
            for c in candidates[1:]
        ):
            return reject("target_sources_disagree")
        # Accepted solve first; Moon limb next. Planets use their centre when
        # available, otherwise motion-aware background-star residuals.
        chosen = next((c for c in candidates if c[0] == "catalog_solve"), None)
        if chosen is None:
            chosen = next(
                (c for c in candidates if c[0] in {"moon_limb", "planet_center"}),
                candidates[0],
            )
        source, pose, bound, rmse, stars = chosen
        family = "body" if source in {"moon_limb", "planet_center"} else "stars"
        # An accepted plate can correct the current source without switching
        # its measurement family for one frame and switching straight back.
        if source == "catalog_solve" and self.measurement_source is not None:
            family = self.measurement_source
        if self.measurement_source is not None and family != self.measurement_source:
            if self.source_candidate is None or self.source_candidate[0] != family:
                self.source_candidate = family, 1
                return reject("measurement_source_transition")
            self.source_candidate = family, self.source_candidate[1] + 1
            if self.source_candidate[1] < 3:
                return reject("measurement_source_transition")
            self.measurement_source = family
            self.source_candidate = None
            self.pose, self.nominal = pose, nominal
            self.last_wall = timing.wall_midpoint
            return reject("measurement_source_transition")
        self.measurement_source = family
        self.source_candidate = None
        self.pose, self.nominal = pose, nominal
        self.last_wall, self.last_valid = timing.wall_midpoint, timing.midpoint
        self.pose_history.append((seq, pose.copy(), timing.wall_midpoint, bound))
        self._acquire_background()
        return TrackingMeasurement(
            **dict(
                base,
                error=self.error(pose, nominal),
                bound_arcsec=bound,
                quality="valid",
                reason=source,
                source=source,
                stars=stars,
                rmse_px=rmse,
                exposure=exposure,
                model_pointing=vector_radec(
                    self.geometry.rays([self.geometry.target_yx])[0] @ pose
                ),
                target_radec=self.ephemeris.position(
                    self.target, astronomical_time(self.request, timing.wall_midpoint)
                ),
                degrees_of_freedom=2 if stars == 0 else 3,
            )
        )


def rectified_patch(patch, shape, info):
    """Resample only the bounded ROI; fit the whole lunar limb after correction."""
    y, x = patch["origin"]
    h, w = patch["pixels"].shape
    corners = np.array([(y, x), (y + h - 1, x), (y, x + w - 1), (y + h - 1, x + w - 1)])
    corrected = corrected_points(corners, shape, info)
    low = np.floor(corrected.min(axis=0)).astype(int)
    high = np.ceil(corrected.max(axis=0)).astype(int)
    extent = high - low + 1
    if np.any(extent < 1) or np.any(extent > 1024):
        raise ValueError("unbounded rectified body ROI")
    yy, xx = np.indices(tuple(extent))
    grid = np.column_stack((yy.ravel() + low[0], xx.ravel() + low[1]))
    _, canvas = sfm.rotate_centroids([], shape, info["rotation_deg"])
    native = native_points(grid, shape, canvas, info) - patch["origin"]
    pixels = ndimage.map_coordinates(
        np.asarray(patch["pixels"], dtype=float),
        native.T,
        order=1,
        mode="constant",
        cval=0,
    ).reshape(tuple(extent))
    valid = ((native >= 1) & (native < np.asarray(patch["pixels"].shape) - 2)).all(
        axis=1
    )
    return dict(pixels=pixels, origin=low, valid=valid.reshape(tuple(extent)))
