"""Wide-lens Focus-screen helpers isolated from the legacy 512px path.

At focal lengths below 10mm, compact stars can disappear when the established
980px camera crop is interpolated down to the solver's 512px image.  Focus is a
visual/measurement tool rather than a plate-solver input, so it may retain the
native crop.  HFD is measured on a linear 8-bit conversion; contrast stretching
is applied only to the small rendered star cutouts.
"""

from __future__ import annotations

from typing import Final, Iterable, Sequence

import numpy as np
from PIL import Image

from PiFinder.optics import active_focal_length_mm


WIDE_FOCUS_MAX_FOCAL_LENGTH_MM: Final[float] = 10.0
WIDE_FOCUS_SIGMA_K: Final[float] = 3.5


def wide_focus_enabled(
    lens_key: str | None, manual_focal_length_mm: object = None
) -> bool:
    """Whether Focus should retain native pixels for the optical train."""

    focal_length = active_focal_length_mm(lens_key, manual_focal_length_mm)
    return focal_length is not None and focal_length < WIDE_FOCUS_MAX_FOCAL_LENGTH_MM


def native_focus_frame(
    raw_frame: np.ndarray,
    *,
    bias_offset: float,
    bit_depth: int,
) -> np.ndarray:
    """Convert native sensor ADU to the camera pipeline's linear 8-bit scale."""

    raw = np.asarray(raw_frame)
    if raw.ndim != 2 or raw.size == 0:
        raise ValueError("Focus RAW frame must be a non-empty 2D array")
    denominator = float(2 ** int(bit_depth)) - float(bias_offset) - 1.0
    if denominator <= 0.0:
        raise ValueError("Focus camera profile has an invalid ADU range")
    scaled = (raw.astype(np.float32) - float(bias_offset)) * (255.0 / denominator)
    return np.clip(scaled, 0.0, 255.0).astype(np.uint8)


def stretch_star_crop(
    crop: Image.Image,
    *,
    background: float,
    peak: float,
) -> Image.Image:
    """Make one detected star visible without changing its HFD input frame."""

    values = np.asarray(crop.convert("L"), dtype=np.float32)
    low = float(background)
    high = max(float(peak), low + 4.0)
    scaled = (values - low) * (255.0 / (high - low))
    return Image.fromarray(np.clip(scaled, 0.0, 255.0).astype(np.uint8), mode="L")


def scale_solver_centroids(
    centroids: Iterable[Sequence[float]],
    *,
    native_hw: tuple[int, int],
    solver_hw: tuple[int, int] = (512, 512),
) -> list[tuple[float, float]]:
    """Map solver ``(y, x)`` positions onto the native Focus crop."""

    native_height, native_width = native_hw
    solver_height, solver_width = solver_hw
    if min(native_height, native_width, solver_height, solver_width) <= 0:
        raise ValueError("Focus centroid dimensions must be positive")
    y_scale = native_height / solver_height
    x_scale = native_width / solver_width
    return [
        (float(point[0]) * y_scale, float(point[1]) * x_scale) for point in centroids
    ]
