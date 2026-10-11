"""Low-count, low-contrast, no-star and false-source tests for offline prototype."""

import numpy as np
import pytest

from PiFinder.visual_tracking import CameraGeometry
from PiFinder.visual_tracking_images import detect_test_stars
from scripts.benchmark_visual_fallback import RelativeReplay
from scripts.benchmark_weak_star_fallback import (
    POINTS,
    WeakStarReplay,
    render,
    roi_centroid,
    truth_scene,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def setup():
    rng = np.random.default_rng(129)
    geometry = CameraGeometry(512, 512, 12, (256, 256), "weak-test")
    image = render(POINTS, rng, peak=100)
    candidate = WeakStarReplay(geometry)
    assert candidate.align(image, 0, 0)
    return candidate, rng, image


@pytest.mark.parametrize("count", [3, 4])
def test_sparse_faint_stars_track_without_five_star_requirement(setup, count):
    candidate, rng, reference = setup
    baseline = RelativeReplay(candidate.geometry)
    assert baseline.align(detect_test_stars(reference), 0, 0)
    successes = 0
    for i in range(1, 11):
        points, truth = truth_scene(i, count)
        frame = render(points, rng, peak=25, index=i)
        old = baseline.measure(detect_test_stars(frame), i, i * 0.1)
        new = candidate.measure(frame, i, i * 0.1)
        assert not old["valid"]
        if new["valid"]:
            successes += 1
            assert np.linalg.norm(np.array(new["residual_yx_px"]) - truth) < 0.5
    assert successes >= 8


@pytest.mark.parametrize("count", [0, 1, 2])
def test_insufficient_stars_cannot_invent_rotation(setup, count):
    candidate, rng, _ = setup
    for i in range(1, 9):
        points, _ = truth_scene(i, count)
        result = candidate.measure(render(points, rng, peak=60, index=i), i, i * 0.1)
        assert not result["valid"]
        assert not result["roll_measured"]
    assert candidate.last_valid == 0
    np.testing.assert_array_equal(candidate.pose, np.eye(3))


@pytest.mark.parametrize("kind", ["hot", "broad_cloud", "noise"])
def test_nonstellar_sources_at_expected_positions_do_not_drive_tracking(setup, kind):
    candidate, rng, _ = setup
    yy, xx = np.indices((512, 512))
    for i in range(1, 6):
        image = render([], rng, index=i)
        for y, x in POINTS:
            if kind == "hot":
                image[int(y), int(x)] += 800
            elif kind == "broad_cloud":
                image += 150 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * 7**2))
        result = candidate.measure(image, i, i * 0.1)
        assert not result["valid"]
    assert candidate.last_valid == 0


def test_cold_sparse_reference_can_be_built_without_solve():
    rng = np.random.default_rng(817)
    geometry = CameraGeometry(512, 512, 12, (256, 256), "cold")
    images = [render(POINTS[:3], rng, peak=25) for _ in range(3)]
    candidate = WeakStarReplay(geometry)
    assert candidate.align(images, 3, 0.3)
    result = candidate.measure(render(POINTS[:3], rng, peak=25), 4, 0.4)
    assert result["valid"]
    assert np.linalg.norm(result["residual_yx_px"]) < 0.5


def test_cold_motion_does_not_become_a_blurred_reference():
    rng = np.random.default_rng(21)
    geometry = CameraGeometry(512, 512, 12, (256, 256), "cold")
    images = [render(POINTS + offset, rng, peak=60) for offset in [-4, 0, 4]]
    assert not WeakStarReplay(geometry).align(images, 3, 0.3)


def test_gap_and_stop_do_not_reset_fixed_target(setup):
    candidate, rng, _ = setup
    world = candidate.world.copy()
    points, _ = truth_scene(1, 4)
    assert candidate.measure(render(points, rng, peak=60), 1, 0.1)["valid"]
    assert not candidate.measure(render([], rng), 2, 0.2)["valid"]
    recovered = candidate.measure(render(points, rng, peak=60), 3, 0.3)
    assert recovered["valid"]
    np.testing.assert_array_equal(candidate.world, world)
    assert candidate.measure(render(points, rng), 4, 6)["reason"] == "gap_exceeded"
    candidate.stop()
    assert (
        candidate.measure(render(points, rng, peak=100), 5, 6.1)["reason"]
        == "not_aligned"
    )


def test_old_frame_and_geometry_cannot_move_reference(setup):
    candidate, rng, _ = setup
    result = candidate.measure(render(POINTS, rng), 0, 0)
    assert result["reason"] == "stale_frame"
    result = candidate.measure(np.zeros((128, 128)), 1, 0.1)
    assert result["reason"] == "geometry_changed"
    assert candidate.last_valid == 0


def test_close_competing_peak_is_rejected():
    rng = np.random.default_rng(81)
    image = render([[250, 250], [250, 255]], rng, peak=80)
    point, reason = roi_centroid(image, [250, 250])
    assert point is None
    assert reason == "ambiguous_peak"


def test_collinear_stars_cannot_establish_rotation_reference():
    rng = np.random.default_rng(62)
    geometry = CameraGeometry(512, 512, 12, (256, 256), "line")
    image = render([[120, 250], [250, 250], [400, 250]], rng, peak=100)
    assert not WeakStarReplay(geometry).align(image, 0, 0)


def test_coadd_cannot_confirm_stars_that_disappeared_from_current_frame(setup):
    candidate, rng, _ = setup
    pose = candidate.pose.copy()
    assert not candidate._confirm_current(render([], rng), pose)
    assert candidate._confirm_current(render(POINTS[:3], rng, peak=25), pose)


def test_temporal_integration_reports_actual_observation_age(setup):
    candidate, rng, _ = setup
    combined = 0
    for i in range(1, 61):
        points, _ = truth_scene(i, 4)
        result = candidate.measure(render(points, rng, peak=15, index=i), i, i * 0.1)
        if result["valid"] and result["coadded"]:
            combined += 1
            assert result["age_s"] == pytest.approx(0.1)
            assert result["measurement_time"] == pytest.approx(i * 0.1 - 0.1)
            assert result["source_frame_ids"] == [i - 2, i - 1, i]
            _, truth = truth_scene(i - 1, 4)
            assert np.linalg.norm(np.asarray(result["residual_yx_px"]) - truth) < 0.6
    assert combined > 0


def test_temporal_buffer_cannot_bridge_a_long_capture_interval(setup):
    candidate, rng, _ = setup
    candidate.measure(render([], rng), 1, 0.1)
    candidate.measure(render([], rng), 2, 0.2)
    candidate.measure(render([], rng), 3, 0.7)
    assert len(candidate.pending) == 1
    candidate.stop()
    assert not candidate.pending


def test_gain_and_background_changes_do_not_change_target(setup):
    candidate, rng, _ = setup
    for i, gain in enumerate([0.5, 1.8, 0.7, 1.2], 1):
        points, truth = truth_scene(i, 4)
        frame = render(points, rng, peak=60, index=i) * gain + 100 * i
        result = candidate.measure(frame, i, i * 0.1)
        assert result["valid"]
        assert np.linalg.norm(np.asarray(result["residual_yx_px"]) - truth) < 0.3
