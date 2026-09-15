"""Coordinate provenance and recording regressions, without hardware."""

import json
from types import SimpleNamespace

import pytest
from flask import Flask

from PiFinder.api_extensions import register_api_routes
from PiFinder.observation import observation_snapshot, target_key
from PiFinder.telemetry import TelemetryRecorder
from PiFinder.types.positioning import (
    Pointing,
    PointingAxis,
    PointingEstimate,
    PointingMatrix,
    SolveDiagnostics,
)

pytestmark = pytest.mark.unit


def state():
    target = SimpleNamespace(object_id=7, display_name="test", ra=359.9, dec=-10)
    sol = PointingEstimate(
        pointing=PointingMatrix(
            camera=PointingAxis(solve=Pointing(1, 2, 3), estimate=Pointing(4, 5, 6)),
            aligned=PointingAxis(
                solve=Pointing(7, 8, 9), estimate=Pointing(10, 11, 12)
            ),
        ),
        last_solve_success=100.5,
        estimate_time=102.0,
        diagnostics=SolveDiagnostics(FrameId=12),
    )
    return SimpleNamespace(
        ui_state=lambda: SimpleNamespace(target=lambda: target),
        solution=lambda: sol,
        solve_state=lambda: True,
        target_pixel=lambda: [250, 251],
    ), target


def test_axis_and_epoch_are_kept_separate_and_snapshot_is_frozen():
    shared, target = state()
    snapshot = observation_snapshot(shared)
    target.ra = 0.1
    assert snapshot["target"]["ra_deg"] == 359.9
    assert snapshot["pointing"]["camera"]["solve"]["ra_deg"] == 1
    assert snapshot["pointing"]["aligned"]["estimate"]["ra_deg"] == 10
    assert snapshot["pointing"]["camera"]["solve"]["epoch_unix_s"] == 100.5
    assert snapshot["pointing"]["aligned"]["estimate"]["epoch_unix_s"] == 102
    assert snapshot["solve_frame_id"] == 12
    assert snapshot["coordinate_frame"] == "J2000"
    json.dumps(snapshot, allow_nan=False)


def test_no_target_or_pointing_is_not_fabricated():
    shared = SimpleNamespace(ui_state=lambda: SimpleNamespace(target=lambda: None))
    snapshot = observation_snapshot(shared)
    assert snapshot["target"] is None
    assert snapshot["pointing"] is None
    assert "pointing" in snapshot["unavailable"]


def test_target_remains_available_after_failed_solve():
    shared, _ = state()
    shared.solve_state = lambda: False
    app = Flask(__name__)
    register_api_routes(app, SimpleNamespace(shared_state=shared))
    response = app.test_client().get("/api/observation")
    assert response.status_code == 200
    assert response.json["target"]["ra_deg"] == 359.9
    assert response.json["solve_state"] is False


def test_same_id_coordinate_changes_and_clear_are_recorded():
    _, target = state()
    rec = TelemetryRecorder()
    rec.enabled = True
    rec.record_target(target)
    old = target_key(target)
    target.ra = 0.1
    assert target_key(target) != old
    rec.record_target(target)
    rec.record_target(target)
    rec.record_target(None)
    rows = [json.loads(line) for line in rec._buffer]
    assert [r["ra"] for r in rows] == [359.9, 0.1, None]


def test_nan_coordinates_are_null():
    shared, target = state()
    target.ra = float("nan")
    snapshot = observation_snapshot(shared)
    assert snapshot["target"]["ra_deg"] is None
    json.dumps(snapshot, allow_nan=False)
