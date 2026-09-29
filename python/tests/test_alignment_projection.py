import math
from dataclasses import replace

import numpy as np
import pytest
import quaternion
from scipy.spatial.transform import Rotation
from tetra3.tetra3 import _compute_vectors

from PiFinder.alignment_projection import (
    cached_target_pixel,
    make_projection,
    project_target,
)
from PiFinder.solver_frame_map import map_frame_pixel_to_target
from PiFinder.types.positioning import ImuSample, Pointing, PointingEstimate

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("frame", [(512, 512, 512), (1920, 1080, 980), (980, 980, 980)])
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_projection_round_trips_tetra3_vectors_in_native_canvas(frame, seed):
    # Independent arbitrary rotation and tetra3's pixel -> vector conversion;
    # recover the published RA/Dec/Roll exactly as the solver does.
    rotation = Rotation.random(random_state=seed).as_matrix()
    ra = math.degrees(math.atan2(rotation[0, 1], rotation[0, 0])) % 360
    dec = math.degrees(math.atan2(rotation[0, 2], np.linalg.norm(rotation[1:3, 2])))
    roll = math.degrees(math.atan2(rotation[1, 2], rotation[2, 2])) % 360
    h, w, crop = frame
    # tetra3 quantizes input centroids to float32 internally.
    pixels = np.array(
        [[h / 2, w / 2], [h * 0.35, w * 0.6], [h * 0.65, w * 0.4]], dtype=np.float32
    )
    vectors = _compute_vectors(pixels, (h, w), math.radians(20)) @ rotation
    plate = {"RA": ra, "Dec": dec, "Roll": roll, "FOV": 20, "frame": frame}
    for pixel, vector in zip(pixels, vectors):
        target_ra = math.degrees(math.atan2(vector[1], vector[0])) % 360
        target_dec = math.degrees(math.asin(vector[2]))
        result = project_target(plate, target_ra, target_dec)
        assert result == pytest.approx(
            map_frame_pixel_to_target(pixel, (h, w), crop), abs=1e-9
        )


def _cached():
    plate = make_projection(
        {
            "RA": 359.9,
            "Dec": 45.0,
            "Roll": 280,
            "FOV": 12,
            "_alignment_frame": (980, 980, 980),
        },
        100.0,
        ("optics",),
    )
    estimate = PointingEstimate(
        last_solve_success=100.0,
        alignment_projection=plate,
        imu_anchor=quaternion.quaternion(1, 0, 0, 0),
    )
    imu = ImuSample(quat=estimate.imu_anchor, timestamp=101.0, status=3)
    return estimate, imu


def test_cached_projection_handles_ra_wrap_and_quaternion_sign():
    estimate, imu = _cached()
    pixel = cached_target_pixel(
        estimate, imu, 0.1, 45.0, now=101.0, context=("optics",)
    )
    assert all(0 < v < 512 for v in pixel)
    assert cached_target_pixel(
        estimate,
        replace(imu, quat=-imu.quat),
        0.1,
        45.0,
        now=101.0,
        context=("optics",),
    ) == pytest.approx(pixel)


@pytest.mark.parametrize("now", [103.0, 220.0])
def test_manual_motion_projects_through_current_imu_camera_pose(now):
    estimate, imu = _cached()
    original_plate = dict(estimate.alignment_projection)
    estimate.pointing.camera.estimate = Pointing(RA=1.0, Dec=44.0, Roll=279.0)
    estimate.estimate_time = now - 1.0
    estimate.imu_observed_time = now
    imu.timestamp = now
    imu.quat = quaternion.from_rotation_vector([0, 0, math.radians(1.0)])
    expected = project_target(
        {**original_plate, "RA": 1.0, "Dec": 44.0, "Roll": 279.0}, 0.1, 45.0
    )
    assert cached_target_pixel(
        estimate, imu, 0.1, 45.0, now=now, context=("optics",)
    ) == pytest.approx(expected)
    assert expected != pytest.approx(project_target(original_plate, 0.1, 45.0))
    assert estimate.alignment_projection == original_plate
    assert estimate.last_solve_success == 100.0


@pytest.mark.parametrize(
    "change",
    [
        "no_observation",
        "old_observation",
        "future_observation",
        "nan_observation",
        "old_estimate",
        "future_estimate",
        "no_camera",
        "bad_camera",
        "moving",
        "stale_imu",
        "bad_imu",
        "optics",
        "epoch",
    ],
)
def test_imu_projection_still_requires_current_valid_state(change):
    estimate, imu = _cached()
    now, context = 220.0, ("optics",)
    estimate.pointing.camera.estimate = Pointing(RA=1.0, Dec=44.0, Roll=279.0)
    estimate.estimate_time = 219.0
    estimate.imu_observed_time = now
    imu.timestamp = now
    if change == "no_observation":
        estimate.imu_observed_time = None
    if change == "old_observation":
        estimate.imu_observed_time = 210.0
    if change == "future_observation":
        estimate.imu_observed_time = 221.0
    if change == "nan_observation":
        estimate.imu_observed_time = float("nan")
    if change == "old_estimate":
        estimate.estimate_time = 99.0
    if change == "future_estimate":
        estimate.estimate_time = 221.0
    if change == "no_camera":
        estimate.pointing.camera.estimate = None
    if change == "bad_camera":
        estimate.pointing.camera.estimate.RA = float("nan")
    if change == "moving":
        imu.moving = True
    if change == "stale_imu":
        imu.timestamp = 100.0
    if change == "bad_imu":
        imu.sensor_healthy = False
    if change == "optics":
        context = ("changed",)
    if change == "epoch":
        estimate.last_solve_success = 101.0
    with pytest.raises(ValueError):
        cached_target_pixel(estimate, imu, 0.1, 45.0, now=now, context=context)


@pytest.mark.parametrize(
    "change",
    ["old", "future", "moving", "moved", "bad_imu", "stale_imu", "optics", "epoch"],
)
def test_cached_projection_refuses_unsafe_reuse(change):
    estimate, imu = _cached()
    now, context = 101.0, ("optics",)
    if change == "old":
        now = 106.0
    if change == "future":
        now = 99.0
    if change == "moving":
        imu.moving = True
    if change == "moved":
        imu.quat = quaternion.from_rotation_vector([0, 0, math.radians(0.1)])
    if change == "bad_imu":
        imu.sensor_healthy = False
    if change == "stale_imu":
        imu.timestamp = 90.0
    if change == "optics":
        context = ("new optics",)
    if change == "epoch":
        estimate.last_solve_success = 99.0
    with pytest.raises(ValueError):
        cached_target_pixel(estimate, imu, 0.1, 45.0, now=now, context=context)


@pytest.mark.parametrize("target", [(179.9, -45), (90, 0), (float("nan"), 45), (0, 91)])
def test_projection_rejects_outside_field_and_invalid_coordinates(target):
    estimate, _ = _cached()
    with pytest.raises(ValueError):
        project_target(estimate.alignment_projection, *target)


def test_unsupported_geometry_is_not_guessed():
    assert make_projection({"RA": 0}, 100.0, ("optics",)) is None


def test_accepted_projection_survives_failed_attempt_without_changing_epoch():
    from types import SimpleNamespace
    from PiFinder.integrator import _apply_successful_solve, _apply_failed_solve
    from PiFinder.solver import _build_successful_solve
    from PiFinder.types.positioning import FailedSolve

    estimate, imu = _cached()
    result = _build_successful_solve(
        {
            "RA": 359.9,
            "Dec": 45.0,
            "Roll": 280.0,
            "FOV": 12.0,
            "_alignment_frame": (980, 980, 980),
        },
        {"imu": replace(imu, timestamp=100.0), "exposure_end": 100.0},
        last_solve_attempt=100.0,
        last_solve_success=100.0,
        alignment_context=("optics",),
    )
    _apply_successful_solve(estimate, result, SimpleNamespace(solve=lambda *args: None))
    _apply_failed_solve(
        estimate, FailedSolve(last_solve_attempt=101.0, last_solve_success=100.0)
    )
    assert estimate.alignment_projection["captured_at"] == 100.0
    assert cached_target_pixel(estimate, imu, 0.1, 45.0, now=101.0, context=("optics",))
