#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
IMU horizon mask: drop detections that look at the ground.

Ground light sources (apartment windows, streetlights) are point-like
enough for cedar-detect to report them as stars; a frame edge full of
them feeds tetra3 dozens of centroids that can never pattern-match
(observed 2026-08-04 00:52, Seoul: 28-33 "centroids" from one building,
0 matches). Their one invariant property is *where they are*: at or
below the horizon.

The IMU's roll/pitch are gravity-referenced (absolute without any
alignment), so each frame's metadata carries enough orientation to
compute the altitude every pixel is looking at: rotate the per-pixel
camera ray into the world frame with the same imu->camera quaternion the
dead-reckoning chain uses, and read the elevation. Detections below
``MIN_ALT_DEG`` are dropped before the solve.

Camera-frame convention (validated against a real frame with a known
building position, 2026-08-04): for a pixel at (row v, col u) of the
ROTATED solver canvas, the camera-frame ray is ``(+u_ang, -v_ang, 1)``
with the boresight on +z -- i.e. x right, y up in canvas orientation.
The small-angle pinhole model is used; at the frame corners (~12 deg
off-axis) the altitude error stays well under the threshold margin.

Config: ``solver_horizon_mask`` (default OFF -- the altitude worth
masking depends on the observing site's skyline, so enable it per
location). The mask silently passes everything through when the IMU
sample is missing or uncalibrated.
"""

import logging
import math
from typing import Optional, Tuple

import numpy as np
import quaternion

from PiFinder import solver_frame_map as sfm
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning

logger = logging.getLogger("Solver.HorizonMask")

# Detections looking below this altitude are dropped. The validated
# building frame put every window light at -0.2..3.8 deg; genuine
# observing targets sit above the mount's own min-altitude limits.
MIN_ALT_DEG = 5.0


def centroid_altitudes(
    centroids_yx,
    frame_hw: Tuple[int, int],
    rotation_deg: float,
    imu_quat: quaternion.quaternion,
    screen_direction: str,
    crop_width_px: int,
) -> Optional[np.ndarray]:
    """Altitude (deg) each raw-frame centroid is looking at, or None.

    ``centroids_yx`` are (y, x) positions on the RAW frame; they are
    mapped into the rotated solver canvas first so the camera-frame
    convention above applies.
    """
    try:
        pts = np.asarray(centroids_yx, dtype=np.float64)
        if pts.ndim != 2 or len(pts) == 0:
            return None
        q_cam = (imu_quat * ImuDeadReckoning._q_imu2cam(screen_direction)).normalized()
        if not np.isfinite(quaternion.as_float_array(q_cam)).all():
            return None
        rot = quaternion.as_rotation_matrix(q_cam)

        cents, canvas = sfm.rotate_centroids(pts, frame_hw, rotation_deg)
        ch, cw = canvas
        scale = math.radians(sfm.SOLVER_FOV_DEG) / float(crop_width_px)
        u_ang = (cents[:, 1] - (cw - 1) / 2.0) * scale
        v_ang = (cents[:, 0] - (ch - 1) / 2.0) * scale

        rays = np.stack([u_ang, -v_ang, np.ones_like(u_ang)], axis=1)
        rays /= np.linalg.norm(rays, axis=1, keepdims=True)
        world = rays @ rot.T  # ENU
        up = np.clip(world[:, 2], -1.0, 1.0)
        return np.degrees(np.arcsin(up))
    except Exception:
        logger.exception("Horizon-mask altitude computation failed")
        return None


def filter_ground_centroids(
    centroids_yx,
    frame_hw: Tuple[int, int],
    rotation_deg: float,
    imu_sample,
    screen_direction: str,
    crop_width_px: int,
    min_alt_deg: float = MIN_ALT_DEG,
):
    """Drop centroids looking below ``min_alt_deg``.

    Returns ``(kept_centroids, dropped_count)``. Passes everything
    through (dropped 0) when the IMU sample is unavailable or
    uncalibrated -- the mask must never cost a solve on missing data.
    """
    if (
        imu_sample is None
        or getattr(imu_sample, "quat", None) is None
        or not imu_sample.orientation_valid()
    ):
        return centroids_yx, 0
    alts = centroid_altitudes(
        centroids_yx,
        frame_hw,
        rotation_deg,
        imu_sample.quat,
        screen_direction,
        crop_width_px,
    )
    if alts is None:
        return centroids_yx, 0
    keep = alts >= min_alt_deg
    dropped = int((~keep).sum())
    if dropped == 0:
        return centroids_yx, 0
    kept = np.asarray(centroids_yx, dtype=np.float64)[keep]
    return kept, dropped
