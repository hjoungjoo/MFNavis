#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Model-aware I2C bus factory.

Raspberry Pi 5 (and Compute Module 5) drive I2C through the RP1 controller,
which honours clock stretching correctly, so those boards use the hardware
I2C bus at full speed.

Raspberry Pi 4 and earlier use the BCM2835/BCM2711 I2C block, which has a
well-documented clock-stretching bug: when a slave stretches the clock the
controller can emit a too-short SCL pulse and corrupt the transfer.  The
BNO055 IMU stretches the clock routinely, so on those boards PiFinder uses a
software (bit-banged) i2c-gpio bus on ``/dev/i2c-3`` instead, which respects
clock stretching.  ``pifinder_setup.sh`` provisions that overlay at install
time; this module simply selects the matching bus at runtime.
"""

import logging
from typing import Optional

logger = logging.getLogger("I2C")

# Bus number provisioned by the i2c-gpio overlay in pifinder_setup.sh.
SOFTWARE_I2C_BUS = 3


def _board_model() -> str:
    """Return the device-tree model string, or "" when unavailable."""
    try:
        with open("/proc/device-tree/model", "rb") as handle:
            return handle.read().decode("utf-8", "replace").rstrip("\x00").strip()
    except OSError:
        return ""


def uses_hardware_i2c(model: Optional[str] = None) -> bool:
    """Return True when this board should use the hardware I2C bus (Pi 5)."""
    if model is None:
        model = _board_model()
    return "Raspberry Pi 5" in model or "Compute Module 5" in model


def get_i2c():
    """Return an I2C bus object appropriate for this board.

    Pi 5 uses the hardware bus via ``board.I2C()``; earlier boards use the
    software i2c-gpio bus (``/dev/i2c-3``) via ``adafruit_extended_bus`` to
    work around the BCM2835/BCM2711 clock-stretching bug.
    """
    if uses_hardware_i2c():
        import board

        logger.debug("Using hardware I2C bus (board.I2C)")
        return board.I2C()

    from adafruit_extended_bus import ExtendedI2C  # type: ignore

    logger.debug("Using software i2c-gpio bus /dev/i2c-%d", SOFTWARE_I2C_BUS)
    return ExtendedI2C(SOFTWARE_I2C_BUS)
