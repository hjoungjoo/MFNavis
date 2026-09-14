#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Unit tests for the SEP fallback backoff (SepShadowRunner).

A failed fallback solve costs up to solve_timeout (1 s) of solver CPU;
on persistently unsolvable scenes (indoors, thick cloud) that recurs on
every attempt. The backoff skips a growing number of attempts after
consecutive failures, but must re-arm immediately when the SEP count
jumps -- a cloud gap opening on real stars must not wait out a backoff
window.
"""

import numpy as np
import pytest

from PiFinder import solver_frame_map as sfm
from PiFinder.mf_wide_distortion import undistort_global_centroids
from PiFinder.sep_detect import SepDetection
from PiFinder.sep_shadow import SepRun, SepShadowRunner


class DummyShared:
    def __init__(self):
        self._overlay = None

    def sep_overlay(self):
        return self._overlay

    def set_sep_overlay(self, v):
        self._overlay = v


class DummyRawShared:
    def __init__(self, entry):
        self._entry = entry

    def solver_raw(self):
        return self._entry


class DummySolveShared:
    def target_pixel(self):
        return (255.5, 255.5)


class DummyT3:
    def __init__(self, solution):
        self.solution = solution
        self.calls = []

    def solve_from_centroids(self, centroids, canvas, **kwargs):
        self.calls.append((np.asarray(centroids), canvas, kwargs))
        return dict(self.solution)


def _runner(tmp_path):
    return SepShadowRunner(
        shadow_enabled=False,
        fallback_enabled=True,
        sigma=3.5,
        rotation_deg=90.0,
        crop_width_px=980,
        csv_path=tmp_path / "shadow.csv",
    )


def _tick(runner, n=1):
    """Advance the per-attempt counter the way detect() does."""
    runner._attempt_counter += n


@pytest.mark.unit
class TestOverlayPublish:
    """The overlay ships once per attempt AFTER the solve outcome, so the
    confirmed/candidate split is never clobbered by the next detect."""

    def test_publish_carries_matched_in_frame_space(self, tmp_path):
        runner = _runner(tmp_path)  # rotation 90
        frame_hw = (64, 48)
        star = np.array([[20.0, 30.0]])
        runner._last_overlay = {
            "centroids": star.tolist(),
            "frame_hw": list(frame_hw),
            "masked": 0,
            "sigma": 4.0,
            "timestamp": 1.0,
        }
        rotated, _ = sfm.rotate_centroids(star, frame_hw, 90.0)
        runner._attach_matched_overlay(
            {"RA": 1.0, "matched_centroids": rotated.tolist()}
        )
        shared = DummyShared()
        runner.publish_overlay(shared)
        entry = shared.sep_overlay()
        assert entry is not None
        my, mx = entry["matched"][0]
        assert abs(my - 20.0) < 1e-6 and abs(mx - 30.0) < 1e-6

        # entry is consumed: a second publish must not re-ship stale data
        shared.set_sep_overlay(None)
        runner.publish_overlay(shared)
        assert shared.sep_overlay() is None

    def test_production_matched_maps_512_space_to_frame_space(self, tmp_path):
        """Cedar matched centroids (rotated-512) land on the overlay in
        frame space: the 512 centre must map to the frame centre."""
        runner = _runner(tmp_path)  # rotation 90, crop 980
        frame_hw = (1080, 1920)
        runner._last_overlay = {
            "centroids": [[0.0, 0.0]],
            "frame_hw": list(frame_hw),
            "masked": 0,
            "sigma": 4.0,
            "timestamp": 1.0,
        }
        c512 = (512 - 1) / 2.0
        runner.attach_production_matched(
            {"RA": 1.0, "matched_centroids": [[c512, c512]]}
        )
        my, mx = runner._last_overlay["matched"][0]
        assert abs(my - (1080 - 1) / 2.0) < 1e-6
        assert abs(mx - (1920 - 1) / 2.0) < 1e-6

    def test_failed_solve_publishes_candidates_only(self, tmp_path):
        runner = _runner(tmp_path)
        runner._last_overlay = {
            "centroids": [[20.0, 30.0]],
            "frame_hw": [64, 48],
            "masked": 0,
            "sigma": 4.0,
            "timestamp": 1.0,
        }
        runner._attach_matched_overlay({"RA": None})
        shared = DummyShared()
        runner.publish_overlay(shared)
        assert "matched" not in shared.sep_overlay()


@pytest.mark.unit
def test_detect_rejects_full_raw_from_a_neighbouring_frame(tmp_path):
    runner = _runner(tmp_path)
    shared = DummyRawShared(
        {"frame_id": 101, "frame": np.zeros((16, 16), dtype=np.uint16)}
    )

    assert runner.detect(shared, expected_frame_id=102) is None


@pytest.mark.unit
def test_solver_preprocessor_requires_two_matching_frames(monkeypatch, tmp_path):
    runner = _runner(tmp_path)
    detected_frames = []

    def fake_detect(frame, **kwargs):
        detected_frames.append((np.asarray(frame).copy(), kwargs))
        return SepDetection(
            centroids=np.asarray([[40.0, 50.0]]),
            fluxes=np.asarray([100.0]),
            background_median=64.0,
            background_rms=1.0,
            elapsed_ms=1.0,
        )

    monkeypatch.setattr("PiFinder.sep_shadow.star_detect.detect_stars", fake_detect)
    frame = np.zeros((128, 128), dtype=np.uint16)

    assert runner.preprocess_frame(frame, fingerprint=("same",), frame_id=1) is None
    assert runner.preprocess_status()["state"] == "warming"
    assert runner.preprocess_status()["frame_count"] == 1
    run = runner.preprocess_frame(frame, fingerprint=("same",), frame_id=2)

    assert run is not None
    assert run.diagnostics.frame_count == 2
    assert runner.preprocess_status()["state"] == "ready"
    assert run.frame_id == 2
    assert detected_frames[0][1]["cloud_window_gate"] is False
    assert detected_frames[0][1]["saturation_level"] is None
    assert detected_frames[0][1]["overlay_max_stars"] == 128
    runner.use_preprocessed_overlay(run)
    assert runner._last_overlay["preprocessed"] is True
    assert runner._last_overlay["preprocess_frames"] == 2
    assert runner._last_overlay["frame_id"] == 2

    # A changed exposure/lens/etc. fingerprint must start a fresh window.
    assert runner.preprocess_frame(frame, fingerprint=("changed",), frame_id=3) is None
    assert runner.preprocess_status()["reset_reason"] == "fingerprint_changed"


@pytest.mark.unit
def test_solver_preprocessor_exposes_error_and_reset_state(monkeypatch, tmp_path):
    runner = _runner(tmp_path)
    monkeypatch.setattr(
        runner._star_only,
        "add",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad frame")),
    )

    assert (
        runner.preprocess_frame(
            np.zeros((8, 8), dtype=np.uint16), fingerprint=("same",), frame_id=1
        )
        is None
    )
    assert runner.preprocess_status()["state"] == "error"
    assert "bad frame" in runner.preprocess_status()["error"]

    runner.reset_preprocessor("reset_moving")
    assert runner.preprocess_status()["state"] == "reset_moving"
    assert runner.preprocess_status()["frame_count"] == 0


@pytest.mark.unit
class TestFallbackBackoff:
    def test_first_attempt_always_allowed(self, tmp_path):
        runner = _runner(tmp_path)
        _tick(runner)
        assert runner.fallback_should_attempt(28) is True

    def test_failures_open_growing_skip_windows(self, tmp_path):
        runner = _runner(tmp_path)
        _tick(runner)
        runner.record_fallback_result(False, 28)
        # streak 1 -> skip 2 attempts
        _tick(runner)
        assert runner.fallback_should_attempt(28) is False
        _tick(runner)
        assert runner.fallback_should_attempt(28) is True
        runner.record_fallback_result(False, 28)
        # streak 2 -> skip 4 attempts
        _tick(runner, 3)
        assert runner.fallback_should_attempt(28) is False
        _tick(runner)
        assert runner.fallback_should_attempt(28) is True

    def test_skip_window_caps_at_eight_attempts(self, tmp_path):
        runner = _runner(tmp_path)
        for _ in range(10):  # streak far past the cap
            _tick(runner)
            runner.record_fallback_result(False, 28)
        _tick(runner, 8)
        assert runner.fallback_should_attempt(28) is True

    def test_sep_count_jump_rearms_immediately(self, tmp_path):
        """Cloud gap opens on stars: masked count jumps 5 -> 30. The
        rescue solve must run right away, not wait out the window."""
        runner = _runner(tmp_path)
        _tick(runner)
        runner.record_fallback_result(False, 20)
        _tick(runner)
        assert runner.fallback_should_attempt(20) is False
        assert runner.fallback_should_attempt(30) is True  # >= 1.5x

    def test_success_and_production_solve_clear_the_streak(self, tmp_path):
        runner = _runner(tmp_path)
        _tick(runner)
        runner.record_fallback_result(False, 28)
        runner.record_fallback_result(True, 28)
        _tick(runner)
        assert runner.fallback_should_attempt(28) is True

        runner.record_fallback_result(False, 28)
        runner.note_solved()
        _tick(runner)
        assert runner.fallback_should_attempt(28) is True


@pytest.mark.unit
class TestSolveSafety:
    @staticmethod
    def _run(centroids):
        return SepRun(
            detection=SepDetection(
                centroids=np.asarray(centroids, dtype=np.float64),
                fluxes=np.ones(len(centroids)),
                background_median=100.0,
                background_rms=3.0,
                elapsed_ms=1.0,
            ),
            frame_hw=(1080, 1920),
            exposure_us=100_000,
            gain=30.0,
        )

    def test_solve_undistorts_centroids_before_rotation(self, tmp_path):
        coefficients = {
            "k1": -0.04,
            "k2": 0.0,
            "k3": 0.0,
            "p1": 0.0,
            "p2": 0.0,
        }
        runner = SepShadowRunner(
            shadow_enabled=False,
            fallback_enabled=True,
            sigma=4.0,
            rotation_deg=0.0,
            crop_width_px=980,
            csv_path=tmp_path / "shadow.csv",
            distortion_coefficients=coefficients,
        )
        source = np.asarray([(80.0, 120.0), (540.0, 960.0)])
        fake = DummyT3(
            {"RA": 10.0, "Dec": 20.0, "Matches": 7, "RMSE": 90.0, "Prob": 1e-6}
        )
        solution = runner.solve(fake, self._run(source), DummySolveShared())
        assert solution is not None
        expected = undistort_global_centroids(source, (1080, 1920), coefficients)
        assert fake.calls[0][0] == pytest.approx(expected)

    def test_solve_rejects_observed_six_match_false_pattern(self, tmp_path):
        runner = _runner(tmp_path)
        fake = DummyT3(
            {
                "RA": 120.0,
                "Dec": 30.0,
                "Matches": 6,
                "RMSE": 80.5,
                "Prob": 9.542e-5,
            }
        )
        solution = runner.solve(
            fake,
            self._run([(100.0 + i * 30, 200.0 + i * 40) for i in range(8)]),
            DummySolveShared(),
            solve_path="sep_center",
        )
        assert solution is None

    def test_clear_matched_overlay_keeps_candidates(self, tmp_path):
        runner = _runner(tmp_path)
        runner._last_overlay = {
            "centroids": [[1.0, 2.0]],
            "matched": [[1.0, 2.0]],
        }
        runner.clear_matched_overlay()
        assert runner._last_overlay == {"centroids": [[1.0, 2.0]]}
