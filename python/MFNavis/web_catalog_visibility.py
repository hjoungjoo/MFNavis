"""Approximate visual-observing priority for the nearby catalog list."""

import math
import time
from datetime import datetime

import pydeepskylog as pds
from pydeepskylog.exceptions import InvalidParameterError

from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.config import Config
from PiFinder.sky_quality import bortle_to_sqm, sqm_to_bortle

SQM_MAX_AGE_SECONDS = 60
POINT_TYPES = {"*", "D*", "***", "Pla"}
EXTENDED_TYPES = {"Gx", "OC", "C+N", "Gb", "Nb", "PN", "Kt", "CM"}
VISIBILITY_LABELS = ("Favorable", "Challenging", "Unlikely", "Unknown")


def _number(value):
    try:
        number = float(value)
        return number if not isinstance(value, bool) and math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def sky_conditions(shared_state):
    """Read fresh SQM and optional filter.bortle without changing settings.

    Both sources present: use the brighter sky (lower SQM) conservatively.
    The unmeasured SQM state's default value must never count as a reading.
    """
    config = Config()
    configured = _number(config.get_option("filter.bortle"))
    configured_sqm = bortle_to_sqm(configured)
    if configured_sqm is None:
        configured = None
    measured = None
    measurement_state = "unavailable"
    try:
        sample = shared_state.sqm()
        value = _number(sample.value)
        timestamp = datetime.fromisoformat(sample.last_update)
        # The device publishes timez.local_now().isoformat(): an intentionally
        # naive host-local timestamp. timestamp() handles that convention as
        # well as explicit UTC/offset timestamps from other SQM producers.
        age = time.time() - timestamp.timestamp()
        if (
            value is not None
            and 0 < value <= 22
            and sample.source not in (None, "None", "")
        ):
            measurement_state = "stale"
            if 0 <= age <= SQM_MAX_AGE_SECONDS:
                measured = value
                measurement_state = "available"
    except (AttributeError, TypeError, ValueError, OverflowError):
        pass

    values = [value for value in (configured_sqm, measured) if value is not None]
    effective = min(values) if values else None
    equipment = config.equipment
    telescope = equipment.active_telescope
    aperture = _number(getattr(telescope, "aperture_mm", None))
    magnification = None
    if telescope is not None and equipment.active_eyepiece is not None:
        try:
            magnification = _number(equipment.calc_magnification())
        except (ValueError, TypeError, ZeroDivisionError):
            pass
    enabled = bool(
        effective is not None
        and aperture
        and aperture > 0
        and magnification
        and magnification > 0
    )
    limiting_mag = None
    if enabled:
        # Approximate point-source limit from the sky's naked-eye limit and
        # collecting-area gain relative to a 7 mm pupil. Account for an exit
        # pupil larger than the eye. This estimates detection, not double-star
        # separation or planetary detail.
        effective_aperture = min(aperture, magnification * 7)
        limiting_mag = pds.sqm_to_nelm(effective) + 5 * math.log10(
            effective_aperture / 7
        )
        configured_mag = _number(config.get_option("filter.magnitude"))
        if configured_mag is not None:
            limiting_mag = min(limiting_mag, configured_mag)
    return {
        "enabled": enabled,
        "configured_bortle": configured,
        "measured_bortle": sqm_to_bortle(measured),
        "measured_sqm": measured,
        "measurement_state": measurement_state,
        "sqm": effective,
        "bortle": sqm_to_bortle(effective),
        "aperture_mm": aperture,
        "magnification": magnification,
        "limiting_mag": limiting_mag,
        "source": "both"
        if len(values) == 2
        else "measured"
        if measured is not None
        else "configured"
        if configured is not None
        else "none",
    }


def visibility(obj_type, magnitude, size_json, sky):
    """Comparable coarse tiers; angular distance orders each tier."""
    if not sky["enabled"]:
        return {"rank": 0, "label": "—"}
    rank = 3
    mag = _number(magnitude)
    if mag is None or mag == MagnitudeObject.UNKNOWN_MAG:
        return {"rank": rank, "label": VISIBILITY_LABELS[rank]}
    if obj_type in POINT_TYPES:
        margin = sky["limiting_mag"] - mag
        rank = 0 if margin >= 1 else 1 if margin >= 0 else 2
    elif obj_type in EXTENDED_TYPES:
        size = SizeObject.from_json(size_json)
        if size.extents and not size.is_vertices and not size.is_segments:
            major = _number(size.extents[0])
            minor = _number(size.extents[1]) if len(size.extents) > 1 else major
            if major is not None and minor is not None and min(major, minor) > 0:
                try:
                    reserve = _number(
                        pds.contrast_reserve(
                            sqm=sky["sqm"],
                            telescope_diameter=sky["aperture_mm"],
                            magnification=sky["magnification"],
                            surf_brightness=None,
                            magnitude=mag,
                            object_diameter1=major,
                            object_diameter2=minor,
                        )
                    )
                    if reserve is not None:
                        rank = 0 if reserve >= 0.5 else 1 if reserve >= -0.2 else 2
                except (ValueError, TypeError, InvalidParameterError, OverflowError):
                    pass
    return {"rank": rank, "label": VISIBILITY_LABELS[rank]}
