"""Image measurements for the experimental, command-free tracking runner."""

import numpy as np
from scipy import ndimage
from scipy.optimize import least_squares


def detect_test_stars(image, *, excluded=None, max_points=128):
    """Offline fallback extractor; live shadow uses existing MFDS detections.

    Subtract a smooth local background, require a multi-pixel PSF, and measure
    centroids on the background-subtracted input, not the detection response.
    """
    image = np.asarray(image, dtype=float)
    if image.ndim != 2 or not np.isfinite(image).all() or min(image.shape) < 9:
        raise ValueError("a finite monochrome image is required")
    signal = image - ndimage.gaussian_filter(image, 8)
    response = ndimage.gaussian_filter(signal, 1)
    median = np.median(response)
    sigma = max(1e-6, 1.4826 * np.median(np.abs(response - median)))
    peaks = (response == ndimage.maximum_filter(response, 7)) & (
        response > median + 6 * sigma
    )
    if excluded is not None:
        peaks &= ~np.asarray(excluded, dtype=bool)
    peaks[:4] = peaks[-4:] = False
    peaks[:, :4] = peaks[:, -4:] = False
    ys, xs = np.nonzero(peaks)
    order = np.argsort(response[ys, xs])[::-1]
    points = []
    for i in order:
        y, x = ys[i], xs[i]
        patch = np.maximum(signal[y - 3 : y + 4, x - 3 : x + 4], 0)
        flux = patch.sum()
        if flux <= 0 or patch.max() / flux > 0.65:
            continue  # single-pixel hot pixel
        yy, xx = np.indices(patch.shape)
        cy, cx = float((yy * patch).sum() / flux), float((xx * patch).sum() / flux)
        variance = float((((yy - cy) ** 2 + (xx - cx) ** 2) * patch).sum() / flux)
        if not 0.5 <= variance <= 9:
            continue
        points.append((y - 3 + cy, x - 3 + cx))
        if len(points) >= max_points:
            break
    return np.asarray(points, dtype=float).reshape(-1, 2)


def measure_moon(image, expected_yx, radius_px, search_px=12):
    """Fit the lunar outer limb in a bounded ROI, never its bright centroid.

    An independently supplied angular-size/optics radius is required. Reject
    a limb with less than 160 degrees of coverage, image-edge clipping, or
    insufficient radial agreement. Clouds/terminator can therefore cause a
    rejected observation rather than silently move the reference centre.
    """
    image = np.asarray(image, dtype=float)
    expected = np.asarray(expected_yx, dtype=float)
    if (
        image.ndim != 2
        or not np.isfinite(image).all()
        or expected.shape != (2,)
        or not np.isfinite(expected).all()
        or not np.isfinite(radius_px)
        or radius_px < 5
        or not np.isfinite(search_px)
        or search_px <= 0
    ):
        return None
    extent = int(np.ceil(radius_px * 1.15 + search_px + 3))
    y, x = np.rint(expected).astype(int)
    y0, x0 = max(0, y - extent), max(0, x - extent)
    roi = image[
        y0 : min(image.shape[0], y + extent + 1),
        x0 : min(image.shape[1], x + extent + 1),
    ]
    if min(roi.shape) < 7:
        return None
    smooth = ndimage.gaussian_filter(roi, 0.8)
    gy, gx = np.gradient(smooth)
    gradient = np.hypot(gy, gx)
    high = np.percentile(gradient, 90)
    if high < 1e-6:
        return None
    edges = gradient >= max(high, gradient.max() * 0.2)
    # Keep the ridge of the edge, not a thick brightness-dependent annulus.
    # Otherwise a crescent's long arc biases the fit toward a larger circle.
    yy, xx = np.indices(roi.shape, dtype=float)
    normal_y = gy / np.maximum(gradient, 1e-12)
    normal_x = gx / np.maximum(gradient, 1e-12)
    forward = ndimage.map_coordinates(gradient, [yy + normal_y, xx + normal_x], order=1)
    backward = ndimage.map_coordinates(
        gradient, [yy - normal_y, xx - normal_x], order=1
    )
    edges &= (gradient >= forward) & (gradient >= backward)
    coords = np.argwhere(edges).astype(float) + [y0, x0]
    if len(coords) < 25:
        return None
    rng = np.random.default_rng(0)
    if len(coords) > 1600:
        coords = coords[rng.choice(len(coords), 1600, replace=False)]
    local = (coords - [y0, x0]).astype(int)
    gradients = np.column_stack(
        (gy[local[:, 0], local[:, 1]], gx[local[:, 0], local[:, 1]])
    )
    gradient_norm = np.linalg.norm(gradients, axis=1)
    best = None
    for _ in range(160):
        a, b, c = coords[rng.choice(len(coords), 3, replace=False)]
        matrix = 2 * np.array([b - a, c - a])
        if abs(np.linalg.det(matrix)) < 1e-4:
            continue
        center = np.linalg.solve(matrix, [b @ b - a @ a, c @ c - a @ a])
        radius = np.linalg.norm(a - center)
        if (
            abs(radius - radius_px) > radius_px * 0.1
            or np.linalg.norm(center - expected) > search_px
        ):
            continue
        errors = np.abs(np.linalg.norm(coords - center, axis=1) - radius)
        radial = coords - center
        inward = np.sum(
            gradients * radial, axis=1
        ) < -0.7 * gradient_norm * np.linalg.norm(radial, axis=1)
        inliers = (errors < 1.25) & inward
        if best is None or inliers.sum() > best[0]:
            best = inliers.sum(), center, radius, inliers
    if best is None or best[0] < 25:
        return None
    selected = coords[best[3]]
    fit = least_squares(
        lambda p: np.linalg.norm(selected - p[:2], axis=1) - p[2],
        [*best[1], best[2]],
        loss="soft_l1",
    )
    center, radius = fit.x[:2], fit.x[2]
    delta = selected - center
    angles = np.sort(np.mod(np.arctan2(delta[:, 0], delta[:, 1]), 2 * np.pi))
    coverage = 2 * np.pi - np.diff(np.r_[angles, angles[0] + 2 * np.pi]).max()
    rmse = float(np.sqrt(np.mean(fit.fun**2)))
    if (
        coverage < np.radians(160)
        or rmse > 1
        or np.linalg.norm(center - expected) > search_px
        or abs(radius - radius_px) > radius_px * 0.1
        or np.any(center - radius < 1)
        or np.any(center + radius >= np.array(image.shape) - 1)
    ):
        return None
    return {
        "center_yx": center.tolist(),
        "radius_px": float(radius),
        "rmse_px": rmse,
        "coverage_deg": float(np.degrees(coverage)),
    }
