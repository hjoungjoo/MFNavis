#!/usr/bin/python
# -*- coding:utf-8 -*-
"""BNO055 calibration persistence helpers.

The Adafruit BNO055 driver exposes calibration offsets/radii as properties on
the sensor object. Keep the file handling in this hardware-light module so the
logic is easy to test without importing Blinka/GPIO.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PiFinder import utils


CALIBRATION_FILE = utils.data_dir / "imu_bno055_calibration.json"
CALIBRATION_VERSION = 1

_FIELDS = (
    "offsets_accelerometer",
    "offsets_magnetometer",
    "offsets_gyroscope",
    "radius_accelerometer",
    "radius_magnetometer",
)


def tracking_calibration_level(calibration_status) -> int:
    """Return the BNO055 calibration level required for IMU tracking.

    BNO055 reports (system, gyro, accel, magnetometer). PiFinder's short-term
    dead-reckoning is driven by gyro/fusion orientation, so partial
    accel/magnetometer calibration must not make the IMU appear frozen. The
    full component tuple is still displayed separately and is required before
    calibration offsets are auto-saved.
    """
    return int(calibration_status[1])


def _as_list(value: Any) -> list[int]:
    if isinstance(value, (list, tuple)):
        return [int(v) for v in value]
    return [int(value)]


def snapshot_from_sensor(sensor) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    snapshot: dict[str, Any] = {
        "version": CALIBRATION_VERSION,
        "sensor": "BNO055",
        "fields": fields,
    }
    for field in _FIELDS:
        fields[field] = _as_list(getattr(sensor, field))
    return snapshot


def apply_snapshot_to_sensor(sensor, snapshot: dict[str, Any]) -> None:
    if snapshot.get("sensor") != "BNO055":
        raise ValueError("Unsupported IMU calibration sensor")
    fields = snapshot.get("fields")
    if not isinstance(fields, dict):
        raise ValueError("Invalid IMU calibration fields")

    for field in _FIELDS:
        if field not in fields:
            raise ValueError(f"Missing IMU calibration field: {field}")
        setattr(sensor, field, tuple(int(v) for v in fields[field]))


def load_snapshot(path: Path = CALIBRATION_FILE) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as snapshot_in:
        return json.load(snapshot_in)


def save_snapshot(snapshot: dict[str, Any], path: Path = CALIBRATION_FILE) -> None:
    utils.create_path(path.parent)
    with open(path, "w", encoding="utf-8") as snapshot_out:
        json.dump(snapshot, snapshot_out, indent=2, sort_keys=True)


def clear_snapshot(path: Path = CALIBRATION_FILE) -> bool:
    if not path.exists():
        return False
    path.unlink()
    return True
