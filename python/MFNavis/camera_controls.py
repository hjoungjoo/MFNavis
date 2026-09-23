#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Lightweight helpers for the Web UI camera exposure/gain controls.

The Web LiveCam page drives the *same* camera as the on-device ``Camera Exp``
and ``Camera Gain`` menus -- there is one camera, and its frames feed plate
solving as well as the LiveCam preview. Both paths end up putting
``set_exp:``/``set_gain:`` commands on the camera command queue
(``camera_interface.CameraInterface.get_image_loop``), so validation and
command formatting live here instead of being duplicated in the web layer.

Like ``livecam_config``, this module deliberately imports nothing heavy so the
web process can use it without pulling in numpy/Pillow.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple, Union


EXPOSURE_AUTO = "auto"
EXPOSURE_AUTO_STAR = "auto_star"
AUTO_EXPOSURE_MODES = (EXPOSURE_AUTO, EXPOSURE_AUTO_STAR)

GAIN_PROFILE = "profile"

# Same values the on-device menus offer (see ui/menu_structure.py), so the two
# UIs stay comparable.
EXPOSURE_PRESETS_US = (25000, 50000, 100000, 200000, 400000, 800000, 1000000)
GAIN_PRESETS = (1, 2, 4, 8, 12, 15, 16, 20, 22, 24, 30)

# The Pi backend never sets FrameDurationLimits, so an exposure longer than the
# configured frame duration is silently clamped by picamera2 rather than
# honoured. Keep the accepted range where the existing pipeline is known to
# work: the on-device menu tops out at 1s and the auto-exposure controllers
# search 10ms..1s.
MIN_EXPOSURE_US = 1000
MAX_EXPOSURE_US = 1000000

# Highest analog gain any camera profile declares (imx462/imx290). Sensors with
# a lower ceiling clamp in the driver; the applied value shows up in the live
# frame metadata.
MIN_GAIN = 1.0
MAX_GAIN = 30.0

ExposureValue = Union[str, int]
GainValue = Union[str, float]


def normalize_exposure(value: Any) -> Tuple[ExposureValue, Optional[str]]:
    """Validate a requested exposure.

    Returns ``(normalized, note)`` where ``normalized`` is one of the auto mode
    strings or an integer microsecond value, and ``note`` describes a clamp if
    one happened (``None`` otherwise).

    Raises ``ValueError`` for values that are neither an auto mode nor numeric.
    """

    if isinstance(value, bool):
        raise ValueError(f"Invalid exposure value: {value!r}")
    if isinstance(value, str):
        text = value.strip().lower()
        if text in AUTO_EXPOSURE_MODES:
            return text, None
        value = text

    try:
        exposure_us = int(round(float(value)))
    except (TypeError, ValueError):
        raise ValueError(f"Invalid exposure value: {value!r}")

    clamped = max(MIN_EXPOSURE_US, min(MAX_EXPOSURE_US, exposure_us))
    if clamped != exposure_us:
        return clamped, (
            f"Exposure {exposure_us}us clamped to {clamped}us "
            f"(accepted {MIN_EXPOSURE_US}-{MAX_EXPOSURE_US}us)"
        )
    return clamped, None


def normalize_gain(value: Any) -> Tuple[GainValue, Optional[str]]:
    """Validate a requested gain.

    Returns ``(normalized, note)`` where ``normalized`` is ``"profile"`` or a
    float multiplier. Raises ``ValueError`` for non-numeric values.
    """

    if isinstance(value, bool):
        raise ValueError(f"Invalid gain value: {value!r}")
    if isinstance(value, str):
        text = value.strip().lower()
        if text == GAIN_PROFILE:
            return GAIN_PROFILE, None
        value = text

    try:
        gain = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid gain value: {value!r}")

    clamped = round(max(MIN_GAIN, min(MAX_GAIN, gain)), 3)
    if clamped != round(gain, 3):
        return clamped, (
            f"Gain {gain:g}x clamped to {clamped:g}x "
            f"(accepted {MIN_GAIN:g}-{MAX_GAIN:g}x)"
        )
    return clamped, None


def exposure_command(value: ExposureValue) -> str:
    """Camera queue command for an already normalized exposure."""

    if isinstance(value, str):
        return f"set_exp:{value}"
    # camera_interface parses manual exposures with int(), so never emit a
    # float repr here.
    return f"set_exp:{int(value)}"


def gain_command(value: GainValue) -> str:
    """Camera queue command for an already normalized gain."""

    if isinstance(value, str):
        return f"set_gain:{value}"
    return f"set_gain:{value:g}"


def exposure_mode(value: Any) -> str:
    """Report ``auto``/``auto_star``/``manual`` for a stored exposure value."""

    if isinstance(value, str) and value.strip().lower() in AUTO_EXPOSURE_MODES:
        return value.strip().lower()
    return "manual"
