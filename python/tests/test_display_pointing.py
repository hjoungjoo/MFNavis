"""GOTO display motion must not depend on the IMU wake threshold."""

import datetime
import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
import quaternion

from PiFinder import calc_utils
from PiFinder.display_pointing import DisplayPointing
from PiFinder.pointing_coordinate_service import PointingCoordinateService
from PiFinder.pointing_model import quaternion_transforms as qt
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
from PiFinder.types.positioning import (
    ImuSample,
    Pointing,
    PointingAxis,
    PointingEstimate,
    PointingMatrix,
    SolveSource,
)

pytestmark = pytest.mark.unit
NOW = 1000.0


@pytest.fixture
def scene(monkeypatch):
    monkeypatch.setattr("time.time", lambda: NOW)
    camera = Pointing(RA=120, Dec=20, Roll=30)
    aligned = Pointing(RA=120.2, Dec=20.1, Roll=30)
    solution = PointingEstimate(
        pointing=PointingMatrix(
            camera=PointingAxis(solve=camera, estimate=camera),
            aligned=PointingAxis(solve=aligned, estimate=aligned),
        ),
        imu_anchor=quaternion.quaternion(1, 0, 0, 0),
        estimate_time=NOW - 10,
        last_solve_success=NOW - 10,
        solve_source=SolveSource.CAMERA,
    )
    location = SimpleNamespace(lock=True, lat=37.5, lon=127.0, altitude=30.0)
    state = SimpleNamespace(
        solution=lambda: solution,
        location=lambda: location,
        datetime=lambda: datetime.datetime(2026, 9, 17, tzinfo=datetime.timezone.utc),
    )
    return solution, state, {"updated": NOW, "mount_motion_active": True}


def sample_at_ra(solution, ra, timestamp=NOW):
    """An IMU orientation for a camera at a known RA with unchanged Dec/roll."""
    camera = solution.pointing.camera.solve
    q_start = qt.radec2q_eq(*np.deg2rad([camera.RA, camera.Dec, camera.Roll]))
    q_end = qt.radec2q_eq(*np.deg2rad([ra, camera.Dec, camera.Roll]))
    body = ImuDeadReckoning._q_imu2cam("right")
    q = body * q_start.conj() * q_end * body.conj()
    return ImuSample(q, timestamp, status=3, moving=False)


def test_slow_goto_continues_display_without_changing_control_solution(scene):
    solution, _, status = scene
    display = DisplayPointing()
    for ra, timestamp in [(121, NOW - 0.2), (121.001, NOW - 0.1), (121.002, NOW)]:
        result = display.solution(
            solution, sample_at_ra(solution, ra, timestamp), "right", status
        )
        assert result.pointing.camera.estimate.RA == pytest.approx(ra)
        assert result.pointing.aligned.estimate.RA == pytest.approx(ra + 0.2)
        assert result.estimate_time == timestamp
        assert result.pointing.camera.solve is solution.pointing.camera.solve
        assert result.pointing.aligned.solve is solution.pointing.aligned.solve
    assert solution.pointing.camera.estimate.RA == 120
    assert solution.pointing.aligned.estimate.RA == 120.2
    assert solution.solve_source == SolveSource.CAMERA
    assert solution.estimate_time == NOW - 10


def test_stop_and_failed_solve_hold_display_until_new_solve(scene):
    solution, _, status = scene
    display = DisplayPointing()
    moving = display.solution(
        solution, sample_at_ra(solution, 122, NOW - 0.1), "right", status
    )
    failed = replace(solution, solve_source=SolveSource.CAMERA_FAILED)
    stopped = display.solution(failed, sample_at_ra(solution, 123), "right", {})
    assert stopped.pointing.aligned.estimate == moving.pointing.aligned.estimate
    assert stopped.estimate_time == NOW - 0.1
    fresh = replace(solution, last_solve_success=NOW, estimate_time=NOW)
    assert display.solution(fresh, sample_at_ra(solution, 123), "right", {}) is fresh


@pytest.mark.parametrize(
    "status",
    [
        {},
        {"updated": NOW - 6, "mount_motion_active": True},
        {"updated": float("nan"), "mount_motion_active": True},
        {"updated": NOW, "mount_motion_active": False},
    ],
)
def test_stationary_or_stale_status_does_not_start_prediction(scene, status):
    solution, _, _ = scene
    assert (
        DisplayPointing().solution(
            solution, sample_at_ra(solution, 122), "right", status
        )
        is solution
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"timestamp": NOW - 2},
        {"sensor_healthy": False},
        {"status": 0},
        {"quat": quaternion.quaternion(float("nan"), 0, 0, 0)},
    ],
)
def test_invalid_imu_cannot_advance_display(scene, changes):
    solution, _, status = scene
    imu = replace(sample_at_ra(solution, 122), **changes)
    assert DisplayPointing().solution(solution, imu, "right", status) is solution


def test_missing_anchor_and_reset_discard_display_prediction(scene):
    solution, _, status = scene
    display = DisplayPointing()
    imu = sample_at_ra(solution, 122)
    display.solution(solution, imu, "right", status)
    no_anchor = replace(solution, imu_anchor=None)
    assert display.solution(no_anchor, imu, "right", status) is no_anchor
    assert display.solution(solution, imu, "right", {}) is solution
    display.solution(solution, imu, "right", status)
    display.reset()
    assert display.solution(solution, imu, "right", {}) is solution


@pytest.mark.parametrize("mount_type", ["EQ", "Alt/Az"])
def test_push_and_skysafari_follow_same_slow_motion(scene, mount_type):
    from PiFinder.ui.object_details import UIObjectDetails

    solution, state, status = scene
    options = {
        "mount_control": True,
        "mount_type": mount_type,
        "screen_direction": "right",
    }
    config = SimpleNamespace(
        get_option=lambda key, default=None: options.get(key, default)
    )
    view = SimpleNamespace(
        shared_state=state,
        screen_direction="right",
        config_object=config,
        _push_mount_status=status,
    )
    service = PointingCoordinateService()
    target = SimpleNamespace(ra=123.2, dec=20.1)
    displayed_coordinates = []
    for ra, timestamp in [(121, NOW - 0.1), (122, NOW)]:
        imu = sample_at_ra(solution, ra, timestamp)
        state.imu = lambda: imu
        lcd = UIObjectDetails._push_display_solution(view)
        sky = service.current_state(
            state,
            state.datetime(),
            config_get=config.get_option,
            mount_status_provider=lambda: status,
        )
        displayed_coordinates.append(sky.display.radec())
        assert sky.display.radec() == pytest.approx((ra + 0.2, 20.1))
        assert sky.display.timestamp == timestamp
        assert sky.display.metadata["display_prediction"]
        assert sky.radec() == pytest.approx((120.2, 20.1))
        assert calc_utils.aim_degrees(
            state, mount_type, "right", target, solution=lcd
        ) == pytest.approx(
            calc_utils.pointing_axis_errors(
                *sky.display.radec(),
                target.ra,
                target.dec,
                mount_type,
                state.location(),
                state.datetime(),
            )
        )
    assert displayed_coordinates[0] != displayed_coordinates[1]
    assert UIObjectDetails._current_pointing_radec(view) == (120.2, 20.1)
    assert state.solution() is solution


def test_skysafari_protocol_uses_display_but_guide_status_keeps_control(
    scene, monkeypatch, tmp_path
):
    from PiFinder import pos_server

    solution, state, status = scene
    state.imu = lambda: sample_at_ra(solution, 122)
    service = PointingCoordinateService()
    coordinate = service.update_state(
        state,
        state.datetime(),
        config_get=lambda key, default=None: True
        if key == "mount_control"
        else default,
        mount_status_provider=lambda: status,
    )
    monkeypatch.setattr(pos_server, "_coordinate_service", service)
    monkeypatch.setattr(pos_server, "is_stellarium", False)
    expected = pos_server.catalog_to_equinox_of_date(122.2, 20.1, state.datetime())
    assert pos_server._current_pointing(state) == pytest.approx(expected)
    monkeypatch.setattr(pos_server, "is_stellarium", True)
    assert pos_server._current_pointing(state) == pytest.approx((122.2, 20.1))

    path = tmp_path / "pointing_coordinate_status.json"
    monkeypatch.setattr(pos_server, "_POINTING_STATUS_FILE", path)
    monkeypatch.setattr(pos_server.utils, "create_path", lambda *_args: None)
    pos_server._write_pointing_status(coordinate)
    payload = json.loads(path.read_text())
    assert payload["current"]["ra"] == pytest.approx(120.2)
    assert payload["solved"]["ra"] == pytest.approx(120.2)
    assert payload["display"]["ra"] == pytest.approx(122.2)
