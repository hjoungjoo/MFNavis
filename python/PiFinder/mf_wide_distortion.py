"""Centroid-space Brown--Conrady correction for native sensor detections.

Detectors work on the original RAW data. This module corrects their measured
centroids in the full sensor coordinate system without resampling the image.
The common optical centre is fixed by the transform, so the existing
target-pixel mapping remains valid.
"""

from __future__ import annotations

from typing import Mapping

import numpy as np


def active_coefficients(profile: object) -> dict[str, float] | None:
    """Return a complete finite Brown--Conrady coefficient set, or None."""

    if not isinstance(profile, Mapping) or profile.get("model") != "brown_conrady":
        return None
    raw = profile.get("coefficients")
    if not isinstance(raw, Mapping):
        return None
    try:
        result = {
            key: float(raw.get(key, 0.0)) for key in ("k1", "k2", "k3", "p1", "p2")
        }
    except (TypeError, ValueError):
        return None
    return result if all(np.isfinite(value) for value in result.values()) else None


def distort_global_centroids(
    centroids_yx: np.ndarray,
    frame_hw: tuple[int, int],
    coefficients: Mapping[str, float],
) -> np.ndarray:
    """Map corrected solver coordinates back onto the original sensor image.

    Use the same centre and corner-radius normalisation as undistortion.
    LiveCam displays unrectified pixels, so matched stars need this forward
    Brown--Conrady mapping after undoing the solver canvas rotation.
    """
    points = np.asarray(centroids_yx, dtype=np.float64).reshape(-1, 2)
    if len(points) == 0:
        return points
    h, w = float(frame_hw[0]), float(frame_hw[1])
    scale = np.hypot(h / 2.0, w / 2.0)
    if scale <= 0:
        return points.copy()
    cy, cx = (h - 1.0) / 2.0, (w - 1.0) / 2.0
    y, x = (points[:, 0] - cy) / scale, (points[:, 1] - cx) / scale
    k1, k2, k3 = (float(coefficients.get(key, 0.0)) for key in ("k1", "k2", "k3"))
    p1, p2 = (float(coefficients.get(key, 0.0)) for key in ("p1", "p2"))
    r2 = x * x + y * y
    radial = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
    xd = x * radial + 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x)
    yd = y * radial + p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y
    distorted = np.column_stack((yd * scale + cy, xd * scale + cx))
    return distorted if np.all(np.isfinite(distorted)) else points.copy()


def undistort_global_centroids(
    centroids_yx: np.ndarray,
    frame_hw: tuple[int, int],
    coefficients: Mapping[str, float],
    *,
    iterations: int = 8,
) -> np.ndarray:
    """Invert Brown--Conrady distortion while retaining full-frame pixels.

    Coefficients use the frame-corner radius as one normalised unit.  That is
    also the convention used by the manual TV baseline, so a smaller sensor
    footprint does not accidentally apply a lens-image-circle value at full
    strength.  Fixed-point inversion is sufficient for the provisional and
    measured ranges accepted by the profile validator; non-finite inputs are
    returned unchanged rather than destabilising a solve attempt.
    """

    points = np.asarray(centroids_yx, dtype=np.float64).reshape(-1, 2)
    if len(points) == 0:
        return points
    h, w = float(frame_hw[0]), float(frame_hw[1])
    scale = np.hypot(h / 2.0, w / 2.0)
    if scale <= 0:
        return points.copy()
    cy, cx = (h - 1.0) / 2.0, (w - 1.0) / 2.0
    yd, xd = (points[:, 0] - cy) / scale, (points[:, 1] - cx) / scale
    yu, xu = yd.copy(), xd.copy()
    k1, k2, k3 = (float(coefficients.get(key, 0.0)) for key in ("k1", "k2", "k3"))
    p1, p2 = (float(coefficients.get(key, 0.0)) for key in ("p1", "p2"))
    for _ in range(max(1, int(iterations))):
        r2 = xu * xu + yu * yu
        radial = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
        x_model = xu * radial + 2.0 * p1 * xu * yu + p2 * (r2 + 2.0 * xu * xu)
        y_model = yu * radial + p1 * (r2 + 2.0 * yu * yu) + 2.0 * p2 * xu * yu
        xu += xd - x_model
        yu += yd - y_model
    corrected = np.column_stack((yu * scale + cy, xu * scale + cx))
    return corrected if np.all(np.isfinite(corrected)) else points.copy()
