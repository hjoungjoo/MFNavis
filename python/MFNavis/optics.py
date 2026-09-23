"""Pure optical-train calculations for PiFinder.

An angular field of view belongs to the sensor *and* the lens.  This module is
resolved by runtime consumers so a declared lens is not represented by
separate, drifting constants.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from PiFinder.mf_manual_lens import MANUAL_LENS_KEY, normalise_manual_focal_length
from PiFinder.mf_wide_lens import MF_WIDE_LENS_SPECS
from PiFinder.sqm.camera_profiles import CameraProfile, get_camera_profile


logger = logging.getLogger("Optics")


# A stated lens can use a tight +/-15% tetra3 FOV gate.  This is a policy
# value only; no solver reads it until the night-validated integration stage.
FOV_GATE_MARGIN = 0.15
LENS_IDENTIFY_TOLERANCE = 0.05
SOLVER_IMAGE_PIXELS = 512
FALLBACK_CAMERA_TYPE = "imx296"


@dataclass(frozen=True)
class Lens:
    """A supported finder-camera lens, keyed by its barrel label."""

    key: str
    nominal_focal_length_mm: float
    effective_focal_length_mm: float
    f_number: float = 2.0
    calibration_required: bool = False
    default_calibration_id: str = "none"

    @property
    def menu_label(self) -> str:
        return f"{self.nominal_focal_length_mm:g}mm"


# Effective focal length, rather than the printed nominal value, is used for
# angular calculations.  These values reproduce the existing calibrated
# 16-mm / HQ field widths; no SQM calibration is changed by this addition.
LENSES: Dict[str, Lens] = {
    "12mm": Lens("12mm", 12.0, 13.04),
    "16mm": Lens("16mm", 16.0, 15.61),
    "25mm": Lens("25mm", 25.0, 26.0),
    **{
        spec.key: Lens(
            spec.key,
            spec.nominal_focal_length_mm,
            spec.effective_focal_length_mm,
            calibration_required=True,
        )
        for spec in MF_WIDE_LENS_SPECS
    },
}


def get_lens(lens_key: str) -> Lens:
    """Return a registered lens or raise ``ValueError`` for an invalid key."""
    try:
        return LENSES[lens_key]
    except KeyError as exc:
        raise ValueError(f"Unknown lens: {lens_key}") from exc


def lens_is_stated(lens_key: Optional[str]) -> bool:
    """Whether configuration explicitly names a supported lens."""
    return bool(lens_key) and lens_key in LENSES


def active_focal_length_mm(
    lens_key: str | None, manual_focal_length_mm: object = None
) -> float | None:
    """Return the selected focal length, preferring a valid manual override."""

    try:
        manual = normalise_manual_focal_length(manual_focal_length_mm, measured=True)
    except ValueError:
        manual = None
    if manual is not None:
        return manual
    if lens_is_stated(lens_key):
        return get_lens(str(lens_key)).nominal_focal_length_mm
    return None


def resolve_lens(
    profile: CameraProfile,
    lens_key: Optional[str] = None,
    manual_focal_length_mm: Optional[float] = None,
) -> Lens:
    """Use the configured lens if valid, otherwise the profile's safe default."""
    manual_focal = normalise_manual_focal_length(manual_focal_length_mm, measured=True)
    if manual_focal is not None:
        return Lens(
            MANUAL_LENS_KEY,
            manual_focal,
            manual_focal,
            calibration_required=True,
        )
    if lens_is_stated(lens_key):
        return get_lens(str(lens_key))
    return get_lens(profile.default_lens_key)


def resolve_camera_profile(camera_type: str) -> CameraProfile:
    """Resolve a live camera type without allowing an invalid value to stop UI."""
    try:
        return get_camera_profile(camera_type)
    except ValueError:
        logger.warning(
            "Unknown camera type %r; deriving optics from %s instead",
            camera_type,
            FALLBACK_CAMERA_TYPE,
        )
        return get_camera_profile(FALLBACK_CAMERA_TYPE)


@dataclass(frozen=True)
class OpticalTrain:
    """A camera profile paired with the lens mounted in front of it."""

    profile: CameraProfile
    lens: Lens
    lens_stated: bool = False

    @property
    def fov_degrees(self) -> float:
        """Horizontal edge-to-edge FOV of MFNavis's cropped image."""
        if self.profile.pixel_pitch_um <= 0:
            raise ValueError("Camera profile has no pixel pitch")
        width_mm = self.profile.crop_size[0] * self.profile.pixel_pitch_um / 1000.0
        return math.degrees(
            2.0 * math.atan2(width_mm / 2.0, self.lens.effective_focal_length_mm)
        )

    def plate_scale_arcsec(self, pixels_per_side: int) -> float:
        """Angular size of a pixel on an explicitly named square grid."""
        if pixels_per_side <= 0:
            raise ValueError("pixels_per_side must be positive")
        return self.fov_degrees * 3600.0 / pixels_per_side

    @property
    def solver_plate_scale_arcsec(self) -> float:
        return self.plate_scale_arcsec(SOLVER_IMAGE_PIXELS)

    def solver_fov_params(self) -> Tuple[float, float]:
        """Candidate ``(fov_estimate, fov_max_error)`` for a future tetra3 use.

        A stated lens yields a narrow gate.  An unstated lens spans every
        shipped lens, so legacy devices are not silently locked to one guess.
        This method is calculation-only until the hardware checklist passes.
        """
        candidates = self.profile.shipped_lens_keys or (self.lens.key,)
        if self.lens_stated or len(candidates) == 1:
            return self.fov_degrees, self.fov_degrees * FOV_GATE_MARGIN
        fields = [
            OpticalTrain(self.profile, get_lens(key), True).fov_degrees
            for key in candidates
        ]
        low = min(field * (1.0 - FOV_GATE_MARGIN) for field in fields)
        high = max(field * (1.0 + FOV_GATE_MARGIN) for field in fields)
        return (low + high) / 2.0, (high - low) / 2.0


def optical_train_for_profile(
    profile: CameraProfile,
    lens_key: Optional[str] = None,
    manual_focal_length_mm: Optional[float] = None,
) -> OpticalTrain:
    """Build a train from a loaded profile and an optional config value."""
    return OpticalTrain(
        profile,
        resolve_lens(profile, lens_key, manual_focal_length_mm),
        lens_is_stated(lens_key)
        or normalise_manual_focal_length(manual_focal_length_mm, measured=True)
        is not None,
    )


def build_optical_train(
    camera_type: str,
    lens_key: Optional[str] = None,
    manual_focal_length_mm: Optional[float] = None,
) -> OpticalTrain:
    """Build a train from the camera profile name used by current PiFinder."""
    return optical_train_for_profile(
        get_camera_profile(camera_type), lens_key, manual_focal_length_mm
    )


class OpticalTrainResolver:
    """Cache a train and rebuild it only when camera or lens state changes."""

    def __init__(self) -> None:
        self._key: Optional[Tuple[str, Optional[str], Optional[float]]] = None
        self._train: Optional[OpticalTrain] = None

    def resolve(
        self,
        camera_type: str,
        lens_key: Optional[str] = None,
        manual_focal_length_mm: Optional[float] = None,
    ) -> OpticalTrain:
        manual_focal = normalise_manual_focal_length(
            manual_focal_length_mm, measured=True
        )
        key = (camera_type, lens_key, manual_focal)
        if key != self._key or self._train is None:
            self._train = optical_train_for_profile(
                resolve_camera_profile(camera_type), lens_key, manual_focal
            )
            self._key = key
        return self._train


def identify_lens_from_fitted_fov(
    profile: CameraProfile, fitted_fov_degrees: Optional[float]
) -> Optional[str]:
    """Return a uniquely close shipped lens, or ``None`` for no safe match.

    This is deliberately a pure helper.  It does not write configuration and
    must not be connected to self-healing until repeated night solves verify
    the policy described in the integration document.
    """
    if not fitted_fov_degrees or fitted_fov_degrees <= 0:
        return None
    best_key: Optional[str] = None
    best_error: Optional[float] = None
    for key in profile.shipped_lens_keys:
        field = OpticalTrain(profile, get_lens(key), True).fov_degrees
        error = abs(fitted_fov_degrees - field) / field
        if best_error is None or error < best_error:
            best_key, best_error = key, error
    if best_error is None or best_error > LENS_IDENTIFY_TOLERANCE:
        return None
    return best_key
