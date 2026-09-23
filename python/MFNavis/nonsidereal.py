#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Non-sidereal tracking-frequency helpers
=======================================

Converts sky-frame RA drift rates of solar-system targets into the LX200
tracking frequency (Hz) that OnStepX accepts via the INDI
``Tracking Frequency.trackFreq`` property (driver sends ``:ST<Hz>#``).

Model (Meade LX200 protocol): a 60.0 Hz synchronous motor turns the RA axis
once per 24 h, so sidereal tracking is 60.16427 Hz and the frequency is
almost exactly 4x the tracking rate expressed in arcsec/s.

Verified on OnStepX 10.28q (Alt/Az mount, 2026-07-19/20):
- Frequencies 54-80 Hz are accepted; 120 Hz is rejected, so values are
  clamped to a safe window here.
- The frequency survives GoTo slews; it is only reset by an actual track-mode
  change (e.g. the ``:TQ#`` a driver reconnect triggers), so restoring
  sidereal must be done by writing the sidereal frequency, not by
  re-asserting an already-on TRACK_SIDEREAL switch.

This module is pure math (no INDI / skyfield imports) so it can be used from
any process and unit-tested in isolation.
"""

from typing import Optional, Tuple

# Sidereal tracking constants (Meade/LX200 convention)
SIDEREAL_FREQ_HZ = 60.16427
SIDEREAL_RATE_ARCSEC_S = 15.0410671787

# Frequency window measured as accepted by OnStepX 10.28q. 54-80 Hz were
# confirmed on hardware; stay inside that window.
MIN_FREQ_HZ = 54.0
MAX_FREQ_HZ = 80.0


def hz_from_rate(ra_rate_arcsec_s: float) -> float:
    """Tracking frequency for an absolute sky RA rate (arcsec/s).

    ``ra_rate_arcsec_s`` is the full RA-coordinate tracking rate the mount
    should run at (sidereal is 15.041), not an offset.
    """
    return SIDEREAL_FREQ_HZ * (ra_rate_arcsec_s / SIDEREAL_RATE_ARCSEC_S)


def rate_from_hz(freq_hz: float) -> float:
    """Inverse of :func:`hz_from_rate` (returns arcsec/s)."""
    return SIDEREAL_RATE_ARCSEC_S * (freq_hz / SIDEREAL_FREQ_HZ)


def hz_from_offset(dra_dt_arcsec_s: float) -> float:
    """Tracking frequency for a target drifting relative to the stars.

    ``dra_dt_arcsec_s`` is the target's own apparent motion dRA/dt in
    RA-coordinate arcsec/s (positive = moving eastward, toward larger RA).
    Comets are typically within +/-0.1; the Moon is about +0.55.

    Sign (verified on hardware 2026-07-19): running the clock FASTER than
    sidereal makes the pointed RA DECREASE, so tracking a target whose RA
    increases needs a SLOWER clock:

        Hz = sidereal_Hz * (1 - dRA/dt / sidereal_rate)

    Sanity check: Moon (+0.55"/s) -> 57.96 Hz, the classic lunar rate.
    """
    return hz_from_rate(SIDEREAL_RATE_ARCSEC_S - dra_dt_arcsec_s)


def clamp_hz(freq_hz: float) -> Tuple[float, bool]:
    """Clamp a frequency into the firmware-accepted window.

    Returns ``(clamped_value, was_clamped)``.
    """
    clamped = min(MAX_FREQ_HZ, max(MIN_FREQ_HZ, float(freq_hz)))
    return clamped, clamped != float(freq_hz)


def ra_rate_from_positions(
    ra1_deg: float,
    ra2_deg: float,
    dt_seconds: float,
) -> Optional[float]:
    """Finite-difference dRA/dt (RA-coordinate arcsec/s) from two ephemeris
    positions ``dt_seconds`` apart. Handles the 0/360 wrap. Returns None for
    a non-positive interval.
    """
    if dt_seconds <= 0:
        return None
    dra = (ra2_deg - ra1_deg + 180.0) % 360.0 - 180.0
    return dra * 3600.0 / dt_seconds


def track_freq_for_target(
    ra1_deg: float,
    ra2_deg: float,
    dt_seconds: float,
) -> Optional[Tuple[float, float, bool]]:
    """Frequency for a moving target given two ephemeris RA samples.

    Returns ``(freq_hz, dra_dt_arcsec_s, was_clamped)`` or None if the rate
    cannot be computed.
    """
    dra_dt = ra_rate_from_positions(ra1_deg, ra2_deg, dt_seconds)
    if dra_dt is None:
        return None
    freq, was_clamped = clamp_hz(hz_from_offset(dra_dt))
    return freq, dra_dt, was_clamped
