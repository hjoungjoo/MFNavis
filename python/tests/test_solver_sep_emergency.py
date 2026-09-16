"""SEP is dormant until the MFDS solve cascade has no usable solution."""

import time
from types import SimpleNamespace

import numpy as np
import pytest

from PiFinder import sep_detect, star_detect
from PiFinder.sep_detect import SepDetection
from PiFinder.sep_shadow import (
    PreprocessedRun,
    SepShadowRunner,
    configure_runtime_detection,
    detect_primary_stars,
)
from PiFinder.solver import _solve_sep_emergency
from PiFinder.solve_acceptance import SolveContinuityGate

pytestmark = pytest.mark.unit
POINTS = np.array([[5 + i * 7, 6 + i * 6] for i in range(8)], dtype=float)
GOOD = {"RA": 120.0, "Dec": 20.0, "Roll": 0.0, "Matches": 8, "RMSE": 20.0, "Prob": 1e-9}


def detection(count=8, backend="mf"):
    return SepDetection(POINTS[:count].copy(), np.ones(count), 0, 0, 1, backend=backend)


@pytest.fixture
def setup(monkeypatch, tmp_path):
    # Configure the live policy while restoring the caller's environment later.
    monkeypatch.setenv("PIFINDER_DETECTOR", "sep")
    monkeypatch.setenv("MF_DETECT_SEP_FALLBACK", "1")
    configure_runtime_detection()
    runner = SepShadowRunner(False, True, 4.0, 0, 64, csv_path=tmp_path / "log.csv")
    raw = np.zeros((64, 64), dtype=np.uint16)
    entry = {"frame": raw, "frame_id": 10, "timestamp": time.time()}
    shared = SimpleNamespace(
        target_pixel=lambda: (255.5, 255.5), camera_lens=lambda: ""
    )
    calls = []

    def sep(frame, **kwargs):
        calls.append(frame)
        return detection(backend="sep")

    monkeypatch.setattr(sep_detect, "detect_stars", sep)
    monkeypatch.setattr(
        star_detect, "_detect_native", lambda *_args, **_kwargs: detection()
    )
    yield runner, shared, entry, calls
    runner._star_only.close()


def attempt(setup, result=GOOD, **kwargs):
    runner, shared, entry, _ = setup
    t3 = SimpleNamespace(solve_from_centroids=lambda *_args, **_kwargs: dict(result))
    return _solve_sep_emergency(
        t3,
        runner,
        shared,
        primary_solution=kwargs.pop("primary_solution", {}),
        raw_entry=entry,
        preprocessed_run=kwargs.pop("preprocessed_run", None),
        expected_frame_id=10,
        moving=kwargs.pop("moving", False),
        center_first=False,
        **kwargs,
    )


@pytest.mark.parametrize("count", [0, 3, 8])
def test_normal_raw_and_preprocessing_detection_never_call_sep(
    setup, monkeypatch, count
):
    runner, shared, entry, calls = setup
    monkeypatch.setattr(
        star_detect, "_detect_native", lambda *_args, **_kwargs: detection(count)
    )
    raw = runner.detect(shared, expected_frame_id=10, raw_entry=entry)
    assert raw.detection.backend == "mf"
    assert len(raw.detection.centroids) == count
    # Use a deterministic synthesized frame to exercise the real preprocessing
    # detection boundary independently of expensive image accumulation.
    monkeypatch.setattr(
        runner._star_only,
        "add",
        lambda *_args, **_kwargs: SimpleNamespace(
            frame=entry["frame"],
            diagnostics=SimpleNamespace(frame_count=2, reset_reason=None),
        ),
    )
    preprocessed = runner.preprocess_frame(entry["frame"], fingerprint=(), frame_id=10)
    assert preprocessed.detection.backend == "mf"
    assert calls == []


def test_native_error_does_not_trigger_sep_before_final_recovery(setup, monkeypatch):
    _, _, entry, calls = setup

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("worker unavailable")

    monkeypatch.setattr(star_detect, "_detect_native", unavailable)
    assert len(detect_primary_stars(entry["frame"]).centroids) == 0
    assert calls == []
    result, path, run = attempt(setup)
    assert result["RA"] == 120
    assert path == "sep_full"
    assert run.frame_id == 10
    assert run.detection.backend == "sep"
    assert run.detection.fallback_reason == "all_mfds_solve_paths_failed"
    assert len(calls) == 1


@pytest.mark.parametrize("primary", [GOOD, {**GOOD, "_pending_confirmation": True}])
def test_mfds_success_including_pending_confirmation_keeps_sep_dormant(setup, primary):
    assert attempt(setup, primary_solution=primary) == ({}, "", None)
    assert setup[3] == []


def test_skipped_mfds_raw_path_must_run_before_sep(setup):
    assert attempt(setup, primary_paths_complete=False) == ({}, "", None)
    assert setup[3] == []
    assert attempt(setup, primary_paths_complete=True)[1] == "sep_full"


def test_preprocessed_emergency_success_skips_raw_sep(setup, monkeypatch):
    runner, _, entry, calls = setup
    frame = np.ones_like(entry["frame"])
    run = PreprocessedRun(
        frame, detection(), SimpleNamespace(frame_count=2), (64, 64), 10
    )
    monkeypatch.setattr(runner, "use_preprocessed_overlay", lambda *_args: None)
    result, path, selected = attempt(setup, preprocessed_run=run)
    assert result["RA"] == 120
    assert path == "preprocessed_sep_full"
    assert selected.frame is frame
    assert len(calls) == 1 and calls[0] is frame
    assert run.detection.backend == "mf"


def test_preprocessed_failure_tries_raw_from_same_exposure(setup, monkeypatch):
    runner, _, entry, calls = setup
    frame = np.ones_like(entry["frame"])
    run = PreprocessedRun(frame, detection(), None, (64, 64), 10)
    monkeypatch.setattr(runner, "use_preprocessed_overlay", lambda *_args: None)

    def sep(image, **kwargs):
        calls.append(image)
        return detection(0 if image is frame else 8, backend="sep")

    monkeypatch.setattr(sep_detect, "detect_stars", sep)
    assert attempt(setup, preprocessed_run=run)[1] == "sep_full"
    assert len(calls) == 2
    assert calls[0] is frame and calls[1] is entry["frame"]


@pytest.mark.parametrize("bad", ["old", "different_frame", "moving"])
def test_stale_mismatched_or_moving_input_never_starts_sep(setup, bad):
    if bad == "old":
        setup[2]["timestamp"] -= 20
    elif bad == "different_frame":
        setup[2]["frame_id"] = 9
    assert attempt(setup, moving=bad == "moving") == ({}, "", None)
    assert setup[3] == []


def test_old_async_preprocessing_is_not_reused_for_current_exposure(setup):
    frame = np.ones_like(setup[2]["frame"])
    old = PreprocessedRun(frame, detection(), None, (64, 64), 9)
    assert attempt(setup, preprocessed_run=old)[1] == "sep_full"
    assert len(setup[3]) == 1 and setup[3][0] is setup[2]["frame"]


def test_failed_emergency_backs_off_and_mfds_success_rearms(setup):
    assert attempt(setup, result={}) == ({}, "", None)
    assert len(setup[3]) == 1
    for _ in range(2):
        assert attempt(setup) == ({}, "", None)
    assert len(setup[3]) == 1
    assert attempt(setup, result={}) == ({}, "", None)
    assert len(setup[3]) == 2
    assert attempt(setup, primary_solution=GOOD) == ({}, "", None)
    assert attempt(setup)[1] == "sep_full"
    assert len(setup[3]) == 3


def test_quality_and_independent_frame_confirmation_still_required(setup):
    assert attempt(setup, result={**GOOD, "Matches": 3}) == ({}, "", None)
    attempt(setup, primary_solution=GOOD)  # clear retry backoff
    result, path, _ = attempt(setup)
    gate = SolveContinuityGate()
    first = gate.evaluate(result, path, 1000, stationary=True, prefer_preprocessed=True)
    assert not first.accepted
    assert gate.evaluate(
        result, path, 1001, stationary=True, prefer_preprocessed=True
    ).accepted
