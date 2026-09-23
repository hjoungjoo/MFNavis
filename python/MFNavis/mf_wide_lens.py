"""MF-wide-angle lens declarations and runtime-safe selection helpers.

This module deliberately has no dependency on the solver, UI, camera, or
configuration implementation.  ``optics.py`` imports the declarations to keep
the established optical-train registry authoritative while the MF additions
remain isolated.  A lens change is represented by its key only; callers must
resolve it again for every configuration change rather than caching geometry
from a previous lens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class MFWideLensSpec:
    """A wide M12 lens before a lens-specific on-sky calibration exists."""

    key: str
    nominal_focal_length_mm: float
    # The initial value is intentionally nominal.  It is a display/planning
    # value only until a calibration profile replaces it with a measured one.
    effective_focal_length_mm: float


MF_WIDE_LENS_SPECS: Final[tuple[MFWideLensSpec, ...]] = (
    MFWideLensSpec("4mm", 4.0, 4.0),
    MFWideLensSpec("6mm", 6.0, 6.0),
    MFWideLensSpec("8mm", 8.0, 8.0),
    MFWideLensSpec("10mm", 10.0, 10.0),
)

MF_WIDE_LENS_KEYS: Final[frozenset[str]] = frozenset(
    spec.key for spec in MF_WIDE_LENS_SPECS
)


def is_mf_wide_lens(lens_key: str | None) -> bool:
    """Whether ``lens_key`` needs the MF calibration policy."""

    return lens_key in MF_WIDE_LENS_KEYS
