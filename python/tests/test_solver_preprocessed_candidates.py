"""Regression coverage for native calibration input and the active solve stages."""

from types import SimpleNamespace

import numpy as np
import pytest

from PiFinder.lens_measurement import measure_lens_frame
from PiFinder.sep_shadow import PreprocessedRun, SepRun, SepShadowRunner
from PiFinder.solver import _calibration_input_from_run, _solve_preprocessed_run

pytestmark = pytest.mark.unit
GEOMETRY = {
    "rotation_deg": 90,
    "crop_width_px": 980,
    "base_fov_degrees": 12.0,
}
POINTS = np.array([(400 + i * 10, 700 + i * 13) for i in range(40)], dtype=float)


def run_with(points=POINTS, frame_id=12, backend="mf"):
    return PreprocessedRun(
        frame=np.zeros((1, 1)),
        detection=SimpleNamespace(
            centroids=np.array(points).reshape(-1, 2), backend=backend
        ),
        diagnostics=None,
        frame_hw=(1080, 1920),
        frame_id=frame_id,
    )


def payload(run, **kwargs):
    return _calibration_input_from_run(
        run, GEOMETRY, expected_frame_id=12, source="preprocessed", **kwargs
    )


@pytest.mark.parametrize("backend", ["mf", "sep"])
def test_calibration_preserves_native_coordinates_and_owns_snapshot(backend):
    run = run_with(backend=backend)
    result = payload(run)
    assert result["source"] == f"preprocessed_{backend}"
    assert result["frame_id"] == 12
    assert result["frame_hw"] == (1080, 1920)
    assert result["rotation_deg"] == 90
    np.testing.assert_array_equal(result["centroids"], POINTS)
    run.detection.centroids[:] = 0
    np.testing.assert_array_equal(result["centroids"], POINTS)


@pytest.mark.parametrize("points", [[], POINTS[:7], POINTS[:39]])
def test_insufficient_distortion_candidates_keep_raw(points):
    previous = payload(run_with())
    assert (
        payload(run_with(points), previous=previous, minimum_candidates=40) is previous
    )


def test_usable_preprocessing_replaces_raw():
    previous = payload(run_with())
    result = payload(run_with(POINTS + 0.25), previous=previous, minimum_candidates=40)
    assert result is not previous
    np.testing.assert_array_equal(result["centroids"], POINTS + 0.25)


@pytest.mark.parametrize("frame_id", [None, 11, 13])
def test_neighbouring_or_unknown_frame_cannot_replace_raw(frame_id):
    previous = payload(run_with())
    assert payload(run_with(frame_id=frame_id), previous=previous) is previous


def test_nonfinite_coordinates_cannot_replace_raw():
    previous = payload(run_with())
    assert payload(run_with([[np.nan, 3]]), previous=previous) is previous


def test_lens_requires_enough_stars_inside_the_sensor_crop():
    previous = payload(run_with())
    edge_points = np.array([(100 + i, 100 + i) for i in range(40)])
    assert (
        payload(
            run_with(edge_points),
            previous=previous,
            minimum_candidates=8,
            central_crop=True,
        )
        is previous
    )


def test_raw_detection_supplies_calibration_even_without_preprocessing():
    run = SepRun(run_with().detection, (1080, 1920), 100000, 1, frame_id=12)
    result = _calibration_input_from_run(
        run, GEOMETRY, expected_frame_id=12, source="raw"
    )
    assert result["source"] == "raw_mf"
    np.testing.assert_array_equal(result["centroids"], POINTS)


def test_real_lens_measurement_receives_preprocessed_candidates():
    class T3:
        def solve_from_centroids(self, points, frame_hw, **kwargs):
            assert len(points) == 40
            assert frame_hw == (980, 980)
            np.testing.assert_array_equal(points, POINTS - [50, 470])
            return {
                "RA": 10,
                "Dec": 20,
                "FOV": 12,
                "Matches": 40,
                "RMSE": 20,
                "Prob": 1e-9,
            }

    result = measure_lens_frame(T3(), payload(run_with()), "imx462")
    assert result["reason"] == "accepted"
    assert result["candidates"] == 40


class Runner:
    min_fallback_stars = 5

    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def solve(self, t3, run, state, **kwargs):
        self.calls.append(kwargs)
        return next(self.results)


def solve(runner, points, center_first=True):
    return _solve_preprocessed_run(
        None,
        runner,
        run_with(points),
        None,
        centroids=points,
        center_first=center_first,
        target_sky_coord=[[10, 20]],
    )


def test_identical_central_and_full_candidates_are_solved_once():
    runner = Runner([{}])
    result, path = solve(runner, POINTS)
    assert result == {} and path == ""
    assert len(runner.calls) == 1
    assert runner.calls[0]["solve_path"] == "preprocessed_sep_full"


def test_center_failure_tries_full_actual_candidates():
    points = np.vstack((POINTS, [[100, 100]]))
    runner = Runner([{}, {"RA": 10}])
    result, path = solve(runner, points)
    assert result["RA"] == 10 and path == "preprocessed_sep_full"
    assert [len(call["centroids_override"]) for call in runner.calls] == [40, 41]
    assert all(call["target_sky_coord"] == [[10, 20]] for call in runner.calls)


def test_center_success_does_not_attempt_full_frame():
    runner = Runner([{"RA": 10}])
    _, path = solve(runner, np.vstack((POINTS, [[100, 100]])))
    assert path == "preprocessed_sep_center"
    assert len(runner.calls) == 1


def test_disabled_center_first_only_solves_full_frame():
    runner = Runner([{}])
    solve(runner, np.vstack((POINTS, [[100, 100]])), center_first=False)
    assert len(runner.calls) == 1
    assert len(runner.calls[0]["centroids_override"]) == 41


def test_insufficient_candidates_do_not_invoke_solver():
    runner = Runner([])
    assert solve(runner, POINTS[:4]) == ({}, "")
    assert runner.calls == []


def test_raw_runner_retains_verified_frame_id(monkeypatch):
    import time
    from PiFinder import star_detect

    detection = SimpleNamespace(
        centroids=POINTS,
        backend="mf",
        fallback_reason=None,
        masked_count=0,
        saturated_count=0,
        cloud_gate_active=False,
        cloud_gated_count=0,
        cloud_contrast=0,
        cloud_directional_coherence=0,
    )
    monkeypatch.setattr(star_detect, "detect_stars", lambda *a, **k: detection)
    state = SimpleNamespace(
        solver_raw=lambda: {
            "frame": np.zeros((1080, 1920), dtype=np.uint16),
            "frame_id": 12,
            "timestamp": time.time(),
        }
    )
    runner = SepShadowRunner(False, True, 4.0, 90, 980)
    try:
        run = runner.detect(state, expected_frame_id=12)
        assert run is not None and run.frame_id == 12
        assert len(payload(run)["centroids"]) == 40
        assert runner.detect(state, expected_frame_id=13) is None
    finally:
        runner._star_only.close()
