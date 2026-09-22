"""MFDS package options reach foreground and background preprocessing safely."""

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from PiFinder import mf_star_only_preprocess as pre
from PiFinder import sep_shadow
from PiFinder.sep_shadow import SepShadowRunner, _preprocess_backend_options
from PiFinder.solver import _make_async_preprocess_worker

pytestmark = pytest.mark.unit


def config(values=None):
    return SimpleNamespace(get_option=(values or {}).get)


@pytest.fixture(autouse=True)
def clean_backend_environment(monkeypatch):
    monkeypatch.delenv("MF_PREPROCESS_ACCELERATOR", raising=False)
    monkeypatch.delenv("MF_PREPROCESS_REDUCTION", raising=False)


@pytest.mark.parametrize(
    "accelerator,reduction", [("cpu", "auto"), ("auto", "numpy"), ("gpu", "neon")]
)
def test_saved_options_pass_through_factory_and_clone(
    monkeypatch, tmp_path, accelerator, reduction
):
    monkeypatch.setattr(sep_shadow, "WARM_MAP_PATH", tmp_path / "missing.npy")
    monkeypatch.setattr(
        sep_shadow,
        "get_camera_profile",
        lambda _: SimpleNamespace(
            raw_size=(1920, 1080),
            crop_x=(0, 0),
            bit_depth=12,
        ),
    )
    monkeypatch.setattr(
        sep_shadow,
        "CalibrationProfileStore",
        lambda _: SimpleNamespace(
            load_active=lambda *args: None,
        ),
    )
    runner = SepShadowRunner.create_if_enabled(
        config(
            {
                "screen_direction": "right",
                "solver_preprocess_accelerator": accelerator,
                "solver_preprocess_reduction": reduction,
            }
        ),
        "test-camera",
        force_create=True,
    )
    assert runner is not None
    # A clone must retain the original resolved choices, even if the environment changes.
    monkeypatch.setenv("MF_PREPROCESS_ACCELERATOR", "cpu")
    monkeypatch.setenv("MF_PREPROCESS_REDUCTION", "numpy")
    clone = runner.preprocessing_clone()
    try:
        for current in (runner, clone):
            assert current._star_only.point_backend.mode == accelerator
            assert current._star_only.reduction_backend.mode == reduction
        assert clone._star_only is not runner._star_only
    finally:
        runner.close_preprocessor()
        clone.close_preprocessor()


def test_defaults_environment_and_invalid_options(monkeypatch, caplog):
    assert _preprocess_backend_options(config()) == {
        "preprocess_accelerator": "cpu",
        "preprocess_reduction": "auto",
    }
    cfg = config(
        {"solver_preprocess_accelerator": "gpu", "solver_preprocess_reduction": "neon"}
    )
    monkeypatch.setenv("MF_PREPROCESS_ACCELERATOR", " CPU ")
    monkeypatch.setenv("MF_PREPROCESS_REDUCTION", "numpy")
    assert _preprocess_backend_options(cfg) == {
        "preprocess_accelerator": "cpu",
        "preprocess_reduction": "numpy",
    }
    monkeypatch.setenv("MF_PREPROCESS_ACCELERATOR", "typo")
    monkeypatch.setenv("MF_PREPROCESS_REDUCTION", "typo")
    assert _preprocess_backend_options(cfg) == {
        "preprocess_accelerator": "cpu",
        "preprocess_reduction": "auto",
    }
    assert len(caplog.records) == 2


def test_auto_fallback_is_reported_and_raw_runner_stays_usable(monkeypatch):
    def unavailable():
        raise OSError("backend absent")

    monkeypatch.setattr(pre, "_NativeGPU", unavailable)
    monkeypatch.setattr(pre, "_NativeTemporalReduction", unavailable)
    monkeypatch.setattr(sep_shadow, "detect_primary_stars", lambda *a, **k: None)
    runner = SepShadowRunner(
        False,
        True,
        4.0,
        0.0,
        980,
        preprocess_accelerator="auto",
        preprocess_reduction="auto",
    )
    try:
        frame = np.full((96, 100), 500, np.uint16)
        for _ in range(2):
            runner.preprocess_frame(frame, fingerprint="same")
        status = runner.preprocess_status()
        assert status["accelerator"] == "cpu"
        assert status["reduction"] == "numpy"
        assert status["accelerator_fallback"] == "backend absent"
        assert status["reduction_fallback"] == "backend absent"
        assert status["state"] == "waiting_for_stars"
        assert status["error"] is None and status["frame_count"] == 2
    finally:
        runner.close_preprocessor()


def test_retired_async_runner_closes_gpu_on_owning_thread(monkeypatch):
    events = []

    class FakeGPU:
        renderer = "V3D test double"

        def __init__(self):
            events.append(("created", threading.get_ident()))

        def dog(self, residual, period):
            return np.zeros_like(residual)

        def close(self):
            events.append(("closed", threading.get_ident()))

    monkeypatch.setattr(pre, "_NativeGPU", FakeGPU)
    runner = SepShadowRunner(
        False,
        True,
        4.0,
        0.0,
        980,
        preprocess_accelerator="gpu",
        preprocess_reduction="numpy",
    )
    worker = _make_async_preprocess_worker(runner)
    try:
        worker.exchange(
            {
                "frame": np.full((96, 100), 500, np.uint16),
                "fingerprint": "same",
                "metadata": {"frame_id": 1},
            }
        )
        result = worker._future.result(timeout=5)
        assert result.error is None
        assert runner.preprocess_status()["accelerator"] == "gpu"
    finally:
        worker.close()
    assert events[0][0] == "created" and events[1][0] == "closed"
    assert len(events) == 2 and events[0][1] == events[1][1]
    assert runner._star_only.frame_count == 0
    assert runner._star_only._scale_executor is None
    assert runner._star_only.point_backend._executor is None
