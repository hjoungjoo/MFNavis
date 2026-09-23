#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tracking-frequency policy for GoTo / push targets
=================================================

Shared decision logic for "what tracking frequency fits this target":

- Solar-system targets (obj_type ``Pla``) get an ephemeris feed-forward
  rate (finite-difference dRA/dt over 10 minutes -> :ST frequency).
- Static targets track at sidereal: if a non-sidereal frequency is
  currently active on the mount it is reset, otherwise nothing is sent.

Used by the LCD GoTo key (ui/base.py, keypad 5) so it behaves exactly like
the web catalog's "Push to PiFinder". Comets are not special-cased yet;
they fall into the reset path (their rates are far smaller than the Moon's).
"""

import json
import logging
import math
from datetime import timedelta
from typing import Any, Dict, Optional

from PiFinder import nonsidereal, utils

logger = logging.getLogger("TrackFreqPolicy")

PLANET_RATE_SAMPLE_SECONDS = 600.0

# A SkySafari GoTo carries no object identity, so a solar-system target can
# only be recognised by where it is. The LX200 target commands quantise to
# 1s of RA (15") and 1" of Dec, and SkySafari's ephemeris differs from
# Skyfield's by a few arcsec, so the match has to be loose -- but the Moon,
# the widest body, is only 30' across, making 6' both generous and unable to
# collide with a neighbouring catalog object.
PLANET_MATCH_TOLERANCE_DEG = 0.1
# Log (without matching) anything this close, so a systematic offset stays
# visible as repeated near-misses instead of silence. This is how the
# J2000/JNow mismatch was meant to surface; it caught nothing because the
# logger sits at ERROR by default (raise it via logconf_indi.json).
PLANET_MATCH_DIAGNOSTIC_DEG = 1.0


def _mount_status() -> Dict[str, Any]:
    try:
        with open(
            utils.runtime_dir / "mount_control_status.json", "r", encoding="utf-8"
        ) as status_in:
            return json.load(status_in)
    except (OSError, ValueError):
        return {}


def _observation_time(shared_state):
    dt = None
    if shared_state is not None:
        try:
            dt = shared_state.datetime()
        except Exception:
            dt = None
    if dt is None:
        from datetime import datetime, timezone

        dt = datetime.now(timezone.utc)
    return dt


def _ephemeris(shared_state):
    """The Skyfield helper with an observer location set, or None when the
    ephemeris is unavailable or PiFinder does not know where it is yet."""
    try:
        from PiFinder.calc_utils import sf_utils
    except Exception:
        return None

    if sf_utils.observer_loc is None and shared_state is not None:
        try:
            location = shared_state.location()
            if location is not None:
                sf_utils.set_location(
                    location.lat,
                    location.lon,
                    getattr(location, "altitude", 0.0) or 0.0,
                )
        except Exception:
            return None
    return sf_utils if sf_utils.observer_loc is not None else None


def _angular_separation_deg(
    ra1_deg: float, dec1_deg: float, ra2_deg: float, dec2_deg: float
) -> float:
    ra1, dec1, ra2, dec2 = (
        math.radians(value) for value in (ra1_deg, dec1_deg, ra2_deg, dec2_deg)
    )
    cos_sep = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(
        dec2
    ) * math.cos(ra1 - ra2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


def planet_positions_of_date(shared_state) -> Dict[str, Any]:
    """Apparent RA/Dec of every solar-system body in the **equinox of date**.

    Matching-only counterpart to ``sf_utils.calc_planets()``, which returns
    J2000 (``radec()`` with no epoch). LX200 clients speak the mount's frame:
    SkySafari and OnStep are both on equinox-of-date, so comparing their
    coordinates against J2000 positions is off by precession -- 22' in 2026,
    far outside the match tolerance (measured 2026-07-20, see
    mf_web_catalogs_dev_ko P6-2).

    This deliberately does not convert the *incoming* coordinate: per
    mf_coordinate_helper_plan, a requested RA/Dec is used as given and never
    reinterpreted by epoch name. Only the ephemeris side is moved to meet it.

    Positions are topocentric, so an unusable observer location shifts the
    Moon by up to ~1 deg (parallax) and will make it miss the tolerance.
    """
    sf_utils = _ephemeris(shared_state)
    if sf_utils is None:
        return {}
    dt = _observation_time(shared_state)
    positions: Dict[str, Any] = {}
    observer = sf_utils.observer_loc.at(sf_utils.ts.from_datetime(dt))
    for name, planet in zip(sf_utils.planet_names, sf_utils.planets):
        ra, dec, _ = observer.observe(planet).apparent().radec(epoch="date")
        positions[name] = (ra._degrees, dec.degrees)
    return positions


def planet_at_coordinates(
    ra_deg: float,
    dec_deg: float,
    shared_state,
    tolerance_deg: float = PLANET_MATCH_TOLERANCE_DEG,
) -> Optional[str]:
    """Name of the solar-system body sitting at these coordinates, or None.

    SkySafari sends bare RA/Dec with no object type, so comparing against the
    ephemeris is the only way to tell a planet GoTo from a static one.
    """
    try:
        planets = planet_positions_of_date(shared_state)
    except Exception:
        logger.exception("Planet lookup failed for RA %.4f Dec %.4f", ra_deg, dec_deg)
        return None

    nearest_name: Optional[str] = None
    nearest_sep: Optional[float] = None
    for name, radec in planets.items():
        separation = _angular_separation_deg(ra_deg, dec_deg, radec[0], radec[1])
        if nearest_sep is None or separation < nearest_sep:
            nearest_name, nearest_sep = name, separation

    if nearest_name is None or nearest_sep is None:
        return None
    if nearest_sep <= tolerance_deg:
        logger.info(
            "GoTo target identified as %s (%.1f arcmin away)",
            nearest_name,
            nearest_sep * 60.0,
        )
        return nearest_name
    if nearest_sep <= PLANET_MATCH_DIAGNOSTIC_DEG:
        logger.info(
            "GoTo target is near %s (%.1f arcmin) but outside the %.1f arcmin "
            "match tolerance; treating it as a sidereal target",
            nearest_name,
            nearest_sep * 60.0,
            tolerance_deg * 60.0,
        )
    return None


def planet_dra_dt(name: str, shared_state) -> Optional[float]:
    """Finite-difference dRA/dt (RA-coordinate arcsec/s) for a solar-system
    body by name, or None if it cannot be computed.

    Uses J2000 positions: a *rate* is barely affected by the equinox choice
    (precession adds ~1.5e-6 arcsec/s, against 0.0095 for Jupiter), so unlike
    the position match this needs no equinox-of-date treatment.
    """
    sf_utils = _ephemeris(shared_state)
    if sf_utils is None:
        return None

    key = name.strip().upper()
    if not key:
        return None
    dt = _observation_time(shared_state)

    try:
        first = sf_utils.calc_planets(dt).get(key)
        second = sf_utils.calc_planets(
            dt + timedelta(seconds=PLANET_RATE_SAMPLE_SECONDS)
        ).get(key)
    except Exception:
        logger.exception("Planet rate computation failed for %s", key)
        return None
    if first is None or second is None:
        return None
    return nonsidereal.ra_rate_from_positions(
        first["radec"][0], second["radec"][0], PLANET_RATE_SAMPLE_SECONDS
    )


def _planet_command(name: str, shared_state) -> Optional[Dict[str, Any]]:
    rate = planet_dra_dt(name, shared_state)
    if rate is None:
        # Rate unavailable: leave the mount's current frequency untouched.
        return None
    hz, was_clamped = nonsidereal.clamp_hz(nonsidereal.hz_from_offset(rate))
    if was_clamped:
        logger.warning("Track frequency for %s clamped to %.5f Hz", name, hz)
    return {"type": "set_track_freq", "hz": hz, "label": name.capitalize()}


def _reset_command_if_non_sidereal() -> Optional[Dict[str, Any]]:
    if _mount_status().get("track_freq_hz") is not None:
        return {"type": "reset_track_freq"}
    return None


def track_freq_command_for_target(
    target_object, shared_state
) -> Optional[Dict[str, Any]]:
    """The mount-control command that sets the right tracking frequency for
    a target about to be GoTo'd, or None when nothing needs to change.

    Same policy as the web catalog push path. The caller knows the object's
    identity here, so this never falls back to identifying it by position:
    a planet and a star can share coordinates (occultation, conjunction) and
    the declared type is always the correct answer.
    """
    if target_object is not None and getattr(target_object, "obj_type", "") == "Pla":
        names = getattr(target_object, "names", None) or []
        name = str(names[0]) if names else ""
        return _planet_command(name, shared_state)

    return _reset_command_if_non_sidereal()


def track_freq_command_for_coordinates(
    ra_deg: float, dec_deg: float, shared_state, identify_planets: bool = True
) -> Optional[Dict[str, Any]]:
    """Same policy for a target known only by position (a SkySafari GoTo).

    The object type is unavailable, so with ``identify_planets`` the ephemeris
    decides: a target sitting on a solar-system body gets that body's feed
    forward rate, anything else is treated as sidereal. Identification is a
    guess -- a star occulted by a planet shares its coordinates -- so it is
    optional; with it off every target here is treated as sidereal.
    """
    if identify_planets:
        name = planet_at_coordinates(ra_deg, dec_deg, shared_state)
        if name is not None:
            return _planet_command(name, shared_state)

    return _reset_command_if_non_sidereal()
