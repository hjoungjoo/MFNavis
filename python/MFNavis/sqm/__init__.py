"""
SQM (Sky Quality Meter) module for calculating sky background brightness.

This module provides:
- SQM: Solved-frame stellar photometry/diagnostic calculator
- radiometer: Solve-independent production sky-brightness measurement
- NoiseFloorEstimator: Calibrated raw-sensor pedestal and noise diagnostics
- CameraProfile: Dataclass containing camera hardware and noise characteristics
- get_camera_profile: Lookup camera profile by type (e.g., "imx296", "hq")
- detect_camera_type: Map hardware IDs to profile names
- apply_variant: Reflect the configured mono/colour variant in a profile name
"""

from .sqm import SQM
from .noise_floor import NoiseFloorEstimator
from .camera_profiles import (
    apply_variant,
    detect_camera_type,
    get_camera_profile,
    CameraProfile,
)

__all__ = [
    "SQM",
    "NoiseFloorEstimator",
    "CameraProfile",
    "apply_variant",
    "get_camera_profile",
    "detect_camera_type",
]
