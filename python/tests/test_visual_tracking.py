import copy
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import numpy as np
import pytest

from PiFinder.visual_tracking import (
    CameraGeometry,
    TrackingSession,
    TrackingLimits,
    correction_proposal,
    plate_basis,
    sky_vector,
)
from PiFinder.visual_tracking_experiment import demo_events, main, replay
from PiFinder.visual_tracking_images import detect_test_stars, measure_moon
from PiFinder.visual_tracking_runtime import create_shadow, read_manifest, write_request
from PiFinder.visual_tracking_target import TargetEphemeris, TrackingTarget

pytestmark = pytest.mark.unit


@pytest.fixture
def geometry():
    return CameraGeometry(512, 512, 10, (256, 256), "test-optics")


@pytest.fixture
def points():
    return np.array(
        [[70, 90], [100, 400], [260, 140], [380, 80], [400, 390]], dtype=float
    )


def observation(session, points, index=1, pose=None, solved=None, **kwargs):
    return session.observe(
        generation=session.generation,
        frame_id=index,
        timestamp=1000.0 + index,
        expected_basis=pose if pose is not None else plate_basis(120, 30, 10),
        centroids=points,
        solved_basis=solved,
        **kwargs,
    )


def anchored(geometry, points):
    session = TrackingSession(geometry)
    session.align("fixed", 1000, plate_basis(120, 30, 10), points)
    return session


def test_geometry_matches_existing_plate_projection(geometry, points):
    from PiFinder.alignment_projection import _plate_rotation

    basis = plate_basis(359.99, 85, -120)
    np.testing.assert_allclose(
        basis, _plate_rotation({"RA": 359.99, "Dec": 85, "Roll": -120})
    )
    np.testing.assert_allclose(
        geometry.project(geometry.rays(points) @ basis, basis), points, atol=1e-9
    )


def test_off_center_user_alignment():
    geometry = CameraGeometry(512, 512, 10, (201, 299), "test")
    basis = geometry.aligned_basis(0.01, 89, 70)
    actual = geometry.rays([geometry.target_yx])[0] @ basis
    np.testing.assert_allclose(actual, sky_vector(0.01, 89), atol=1e-12)


def test_stationary_and_fixed_reference_drift(geometry, points):
    session = anchored(geometry, points)
    first = observation(session, points)
    assert first["state"] == "tracking_visual"
    assert first["last_solve_time"] is None
    np.testing.assert_allclose(first["residual_yx_px"], [0, 0], atol=1e-6)
    for i in range(2, 6):
        result = observation(session, points + [0, i], index=i)
    # It is cumulative drift, not the last one-pixel inter-frame step.
    assert result["residual_yx_px"][1] == pytest.approx(5, abs=0.08)


def test_moving_target_and_field_rotation_have_zero_residual(geometry, points):
    session = anchored(geometry, points)
    world = session.world.copy()
    expected = plate_basis(120.02, 30.01, 10.2)
    current = geometry.project(world, expected)
    result = observation(session, current, pose=expected)
    assert result["state"] == "tracking_visual"
    np.testing.assert_allclose(result["residual_yx_px"], [0, 0], atol=1e-6)


def test_clouds_recover_without_realigning(geometry, points):
    session = anchored(geometry, points)
    observation(session, points)
    cloud = observation(session, [], 2)
    assert cloud["state"] == "tracking_predicted"
    assert cloud["last_visual_time"] == 1001
    partial = observation(session, points[:3], 3)
    assert partial["state"] == "tracking_visual"
    solved = observation(session, points, 4, solved=plate_basis(120, 30, 10))
    assert solved["last_solve_time"] == 1004
    assert solved["anchor_source"] == "solve"
    failed_again = observation(session, points[:3], 5)
    assert failed_again["last_solve_time"] == 1004
    assert failed_again["state"] == "tracking_visual"
    assert session.generation == 1


@pytest.mark.parametrize("count", [0, 1, 2])
def test_insufficient_stars_do_not_invent_roll(geometry, points, count):
    result = observation(anchored(geometry, points), points[:count])
    assert result["state"] == "tracking_predicted"
    assert result["last_visual_time"] is None


def test_outlier_rejection(geometry, points):
    session = anchored(geometry, points)
    changed = points.copy()
    changed[0] += [8, 8]
    result = observation(session, changed)
    assert result["state"] == "tracking_visual"
    assert result["matches"] == 4
    np.testing.assert_allclose(result["residual_yx_px"], [0, 0], atol=1e-6)


def test_duplicate_points_are_not_independent_evidence(geometry, points):
    result = observation(anchored(geometry, points), np.repeat(points[:1], 4, axis=0))
    assert result["state"] == "tracking_predicted"


def test_stale_generation_and_frame_do_not_mutate(geometry, points):
    session = anchored(geometry, points)
    observation(session, points)
    before = session.status()
    stale = session.observe(
        generation=0,
        frame_id=99,
        timestamp=2000,
        expected_basis=plate_basis(120, 30, 10),
        centroids=points,
    )
    assert stale["reason"] == "stale_observation"
    assert session.status() == before
    observation(session, points + 5, index=1)
    assert session.status() == before


def test_manual_move_requires_new_alignment(geometry, points):
    session = anchored(geometry, points)
    session.suspend()
    result = observation(session, points)
    assert result["state"] == "manual_move"
    assert result["reason"] == "alignment_required"
    session.align("other", 1002, plate_basis(120, 30, 10), points)
    assert session.generation == 3
    assert observation(session, points, 3)["state"] == "tracking_visual"


def test_long_gap_requires_solve_or_alignment(geometry, points):
    session = anchored(geometry, points)
    session.limits = TrackingLimits(max_gap_s=2)
    assert observation(session, [], 4)["state"] == "uncertain"
    assert observation(session, points, 5)["state"] == "uncertain"
    result = observation(session, points, 6, solved=plate_basis(120, 30, 10))
    assert result["state"] == "tracking_solved"


def test_large_solve_jump_requires_independent_confirmation(geometry, points):
    session = anchored(geometry, points)
    wrong_user_anchor_correct_solve = plate_basis(121, 30, 10)
    pending = observation(session, [], solved=wrong_user_anchor_correct_solve)
    assert pending["last_solve_time"] is None
    assert pending["reason"] == "confirming_solve_jump"
    result = observation(session, points, 2, solved=wrong_user_anchor_correct_solve)
    assert result["state"] == "tracking_solved"
    assert result["last_solve_time"] == 1002


def test_confirmed_wrong_target_behind_camera_has_no_nan_residual(geometry, points):
    session = anchored(geometry, points)
    far = plate_basis(300, -30, 10)
    observation(session, [], solved=far)
    result = observation(session, [], 2, solved=far)
    assert result["state"] == "uncertain"
    assert result["reason"] == "target_outside_projection"
    assert result["residual_yx_px"] is None
    json.dumps(result, allow_nan=False)


def test_moon_measurement_keeps_unknown_roll_constrained(geometry):
    session = anchored(geometry, [])
    result = observation(session, [], moon_yx=[258, 253])
    assert result["source"] == "moon"
    np.testing.assert_allclose(result["residual_yx_px"], [2, -3], atol=0.02)
    assert result["last_solve_time"] is None


@pytest.mark.parametrize("mount_type", ["Alt/Az", "EQ"])
def test_axis_signs_are_from_calibration_and_proposal_is_bounded(
    geometry, points, mount_type
):
    result = observation(anchored(geometry, points), points + [2, -3])
    jacobian = np.array([[0, -0.02], [0.04, 0]])
    proposal = correction_proposal(
        result,
        jacobian,
        mount_type=mount_type,
        calibration_valid=True,
        tracking_enabled=True,
        now=1001,
    )
    assert proposal["diagnostic_only"]
    assert max(abs(v) for v in proposal["axis_ms"]) <= 100
    moved = jacobian @ proposal["axis_ms"]
    assert np.dot(moved, result["residual_yx_px"]) < 0
    assert (
        correction_proposal(
            result,
            jacobian,
            mount_type=mount_type,
            calibration_valid=True,
            tracking_enabled=True,
            now=1010,
        )
        is None
    )
    assert (
        correction_proposal(
            result,
            jacobian,
            mount_type=mount_type,
            calibration_valid=True,
            tracking_enabled=True,
            now=1001,
            pier_side="west",
            calibrated_pier_side="east",
        )
        is None
    )


def star_image(points, shape=(128, 128)):
    yy, xx = np.indices(shape)
    image = np.random.default_rng(4).normal(200, 1, shape) + xx * 0.3
    for y, x in points:
        image += 100 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / 2)
    return image


def test_background_extraction_rejects_hot_pixel():
    truth = np.array([[35.2, 40.1], [80.4, 91.3]])
    image = star_image(truth)
    image[15, 15] = 3000
    found = detect_test_stars(image)
    assert len(found) == 2
    distances = np.linalg.norm(found[:, None] - truth[None, :], axis=2)
    assert np.max(np.min(distances, axis=0)) < 0.15


@pytest.mark.parametrize("crescent", [False, True])
def test_moon_uses_outer_limb_not_bright_centroid(crescent):
    yy, xx = np.indices((128, 128))
    center = np.array([66.0, 61.0])
    radius = 23
    disk = (yy - center[0]) ** 2 + (xx - center[1]) ** 2 < radius**2
    if crescent:
        disk &= (yy - center[0]) ** 2 + (xx - (center[1] - 12)) ** 2 > radius**2
    from scipy.ndimage import gaussian_filter

    image = 200 + 800 * gaussian_filter(disk.astype(float), 0.7)
    result = measure_moon(image, [64, 64], radius)
    assert result is not None
    np.testing.assert_allclose(result["center_yx"], center, atol=1)


def test_blank_and_wrong_radius_are_not_moon():
    assert measure_moon(np.ones((100, 100)), [50, 50], 20) is None
    image = star_image([[50, 50]], (100, 100))
    assert measure_moon(image, [50, 50], 20) is None


def test_shadow_default_does_not_read_environment(monkeypatch):
    monkeypatch.delenv("MFNAVIS_VISUAL_TRACKING_EXPERIMENT", raising=False)
    assert create_shadow(object()) is None


def manifest(tmp_path):
    return {
        "schema": 1,
        "mode": "shadow",
        "environment_confirmed": True,
        "mount_type": "Alt/Az",
        "camera_type": "imx296",
        "lens": "16mm",
        "calibration_id": "test",
        "output_dir": str(tmp_path / "results"),
        "expires_at": 9999999999,
        "max_frames": 100,
        "alignment_roll_deg": 0,
        "roll_confirmed": True,
        "raw_shape": [512, 512],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "active"},
        {"environment_confirmed": False},
        {"expires_at": 0},
        {"mount_type": "unknown"},
        {"roll_confirmed": False},
        {"max_frames": 10001},
    ],
)
def test_unconfirmed_environment_is_rejected(tmp_path, change):
    path = tmp_path / "environment.json"
    path.write_text(json.dumps({**manifest(tmp_path), **change}))
    with pytest.raises(ValueError):
        read_manifest(path)


def test_request_and_replay_cli(tmp_path):
    path = tmp_path / "environment.json"
    path.write_text(json.dumps(manifest(tmp_path)))
    request = write_request(path, "align", ra=10, dec=20, frame="catalog")
    assert request["command"] == "align"
    dataset, output = tmp_path / "demo.jsonl", tmp_path / "result.jsonl"
    assert main(["demo", "--output", str(dataset)]) == 0
    assert main(["replay", str(dataset), "--output", str(output)]) == 0
    results = [json.loads(row) for row in output.read_text().splitlines()]
    assert results[-1]["state"] == "tracking_visual"
    assert results[-1]["last_solve_time"] == 1006
    assert all(row["commands_sent"] == 0 for row in results)
    assert main(["replay", str(dataset), "--output", str(dataset)]) == 2


def test_replay_does_not_mutate_input():
    events = list(demo_events())
    original = copy.deepcopy(events)
    list(replay(events))
    assert events == original


class Observer:
    def location(self):
        return SimpleNamespace(lat=37.527, lon=127.109, altitude=30, lock=True)

    def datetime(self):
        return datetime(2026, 9, 28, tzinfo=timezone.utc)


def test_existing_planet_identification_is_reused(monkeypatch):
    from PiFinder import track_freq_policy

    calls = []

    def identify(ra, dec, state):
        calls.append((ra, dec))
        return "MOON"

    monkeypatch.setattr(track_freq_policy, "planet_at_coordinates", identify)
    ephemeris = TargetEphemeris(Observer())
    target = ephemeris.resolve(10, 20, frame="of_date", identify_planets=True)
    assert target.body == "MOON" and calls == [(10, 20)]
    # Explicit static selection doesn't become the nearby Moon.
    static = ephemeris.resolve(10, 20, frame="catalog", identify_planets=False)
    assert static.body is None and len(calls) == 1


def test_moon_position_uses_both_coordinates_and_observation_epoch():
    ephemeris = TargetEphemeris(Observer())
    target = TrackingTarget(0, 0, "MOON")
    stamp = Observer().datetime().timestamp()
    first, later = (
        ephemeris.position(target, stamp),
        ephemeris.position(target, stamp + 600),
    )
    assert abs(first[0] - later[0]) > 0.01
    assert abs(first[1] - later[1]) > 0.0001


def test_eq_prediction_does_not_use_altaz_roll(geometry, monkeypatch):
    ephemeris = TargetEphemeris(Observer())

    def forbidden(*args):
        raise AssertionError("EQ must not use the Alt/Az model")

    monkeypatch.setattr(ephemeris, "_horizon_roll", forbidden)
    pose = ephemeris.basis(
        TrackingTarget(120, 30),
        1001,
        geometry,
        mount_type="EQ",
        alignment_timestamp=1000,
        alignment_roll_deg=10,
    )
    np.testing.assert_allclose(pose, plate_basis(120, 30, 10), atol=1e-12)
