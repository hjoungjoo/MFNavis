#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Small startup hardware probes.

The current automatic display selection uses the Rev-4 BQ25895 charger ACK as
the board marker for the 176x176 SSD1333 panel.  This module is intentionally
import-safe: on systems without Blinka/board/I2C it simply reports no match so
older PiFinder hardware keeps the SSD1351 default.
"""

import logging

try:
    from PiFinder.i2c_bus import get_i2c
except Exception:
    get_i2c = None  # type: ignore[assignment]


logger = logging.getLogger("HardwareDetect")

BQ25895_ADDRESS = 0x6A


def i2c_present(address: int) -> bool:
    """Return True when an I2C address ACKs on the board I2C bus."""
    if get_i2c is None:
        raise RuntimeError("blinka / board unavailable; no I2C bus")

    i2c = get_i2c()
    locked = False
    try:
        while not i2c.try_lock():
            pass
        locked = True
        return address in i2c.scan()
    finally:
        if locked:
            i2c.unlock()


def detect_ssd1333_display() -> bool:
    """Detect whether this MFNavis should default to the SSD1333 display."""
    try:
        return i2c_present(BQ25895_ADDRESS)
    except Exception as e:
        logger.debug("SSD1333 display marker probe unavailable (%s)", e)
        return False


def default_display_hardware() -> str:
    """Return the default physical display driver for this hardware."""
    return "ssd1333" if detect_ssd1333_display() else "ssd1351"
