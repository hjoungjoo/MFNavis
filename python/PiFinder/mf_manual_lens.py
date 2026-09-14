"""Manual focal lengths, with precision retained for measured optical scales."""

from __future__ import annotations

from typing import Final


MANUAL_LENS_KEY: Final[str] = "manual"
MIN_FOCAL_LENGTH_MM: Final[float] = 0.1
MAX_FOCAL_LENGTH_MM: Final[float] = 99.9


def normalise_manual_focal_length(value, *, measured=False) -> float | None:
    """Validate mm; retain four decimals for measured values, one for legacy input."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        focal_length = round(float(value), 4 if measured else 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("Manual lens focal length must be a number") from exc
    if not MIN_FOCAL_LENGTH_MM <= focal_length <= MAX_FOCAL_LENGTH_MM:
        raise ValueError(
            f"Manual lens focal length must be {MIN_FOCAL_LENGTH_MM:.1f}–{MAX_FOCAL_LENGTH_MM:.1f} mm"
        )
    return focal_length


def manual_focal_from_state(shared_state) -> float | None:
    """Read and validate the optional override without breaking legacy state."""

    getter = getattr(shared_state, "camera_lens_focal_length_mm", None)
    if not callable(getter):
        return None
    try:
        return normalise_manual_focal_length(getter(), measured=True)
    except (TypeError, ValueError):
        return None


def calibration_lens_key(lens_key: str, focal_length=None) -> str:
    """Separate distortion calibrations for each manual optical scale."""
    if str(lens_key).startswith("manual-"):
        return str(lens_key)
    focal = normalise_manual_focal_length(focal_length, measured=True)
    return f"manual-{focal:.4f}mm" if focal is not None else str(lens_key or "")
