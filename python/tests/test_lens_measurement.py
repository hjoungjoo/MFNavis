"""Optical-scale fitting, cancellation, precision and manual calibration isolation."""

from concurrent.futures import Future
import math

import numpy as np
import pytest

from PiFinder.lens_measurement import LensMeasurement, measure_lens_frame
from PiFinder.mf_wide_calibration import CalibrationProfileStore
from PiFinder.optics import build_optical_train
from PiFinder.sqm.camera_profiles import get_camera_profile
from PiFinder.types.positioning import StartLensMeasurement

pytestmark = pytest.mark.unit


class Config:
    def __init__(self):
        self.values = {"camera_lens": "8mm", "camera_lens_focal_length_mm": None}

    def get_option(self, key, default=None):
        return self.values.get(key, default)

    def set_options(self, values):
        self.values.update(values)

    def set_option(self, key, value):
        self.values[key] = value


class State:
    def __init__(self):
        self.lens = "8mm"
        self.focal = None
        self.status = {}

    def camera_type(self):
        return "imx462_color"

    def camera_lens(self):
        return self.lens

    def camera_lens_focal_length_mm(self):
        return self.focal

    def set_camera_lens(self, value):
        self.lens = value

    def set_camera_lens_focal_length_mm(self, value):
        self.focal = value

    def lens_measurement_status(self):
        return self.status

    def set_lens_measurement_status(self, value):
        self.status = value


def sample(focal=10.5234):
    return dict(
        reason="accepted",
        candidates=18,
        focal_length_mm=focal,
        fov_deg=15.38,
        ra=250.0,
        dec=-8.0,
        rmse=30.0,
    )


@pytest.fixture
def session():
    cfg, state = Config(), State()
    pending = []

    def submit(request_id, payload, camera):
        f = Future()
        pending.append((f, request_id))
        return f

    session = LensMeasurement(cfg, state, submit)
    session.start(StartLensMeasurement(state.camera_type(), 123))
    return session, pending


def feed(session, pending, frame_id, result=None):
    session.observe({"centroids": np.zeros((18, 2))}, frame_id, False)
    f, request_id = pending[-1]
    f.set_result((request_id, result or sample()))
    session.observe(None, frame_id, False)


def test_five_fresh_consistent_frames_apply_precise_manual_lens(session):
    s, pending = session
    for i in range(4):
        feed(s, pending, i)
        assert s.cfg.values["camera_lens"] == "8mm"
    feed(s, pending, 4)
    assert s.state.status["state"] == "completed"
    assert s.cfg.values["camera_lens"] == "manual"
    assert s.state.focal == 10.5234
    train = build_optical_train(s.state.camera_type(), "manual", s.state.focal)
    assert train.lens.effective_focal_length_mm == 10.5234
    assert train.fov_degrees == pytest.approx(s.state.status["fov_deg"])


def test_duplicate_frames_do_not_advance_measurement(session):
    s, pending = session
    feed(s, pending, 1)
    s.observe({"centroids": []}, 1, False)
    assert len(pending) == 1
    assert len(s.samples) == 1


@pytest.mark.parametrize("change", ["cancel", "lens", "motion", "timeout"])
def test_stale_worker_result_cannot_apply_after_context_change(session, change):
    s, pending = session
    for i in range(4):
        feed(s, pending, i)
    s.observe({"centroids": []}, 4, False)
    f, request_id = pending[-1]
    f.set_running_or_notify_cancel()
    if change == "cancel":
        s.state.status["state"] = "cancelled"
    elif change == "lens":
        s.state.focal = 9.2
    elif change == "timeout":
        s.started -= 181
    else:
        s.observe(None, 5, True)
    f.set_result((request_id, sample()))
    s.observe(None, 6, False)
    assert s.cfg.values["camera_lens"] == "8mm"


def test_inconsistent_focal_length_restarts_confirmation(session):
    s, pending = session
    for i in range(4):
        feed(s, pending, i)
    feed(s, pending, 4, sample(12.0))
    assert len(s.samples) == 1
    assert s.active


def test_low_quality_result_does_not_count(session):
    s, pending = session
    feed(s, pending, 0, dict(reason="low_quality", candidates=18))
    assert s.samples == []


def test_blind_measurement_uses_physical_central_crop_and_no_old_fov():
    class T3:
        def solve_from_centroids(self, points, shape, **kwargs):
            assert shape == (980, 980)
            assert len(points) == 9  # Exclude the out-of-crop detection.
            assert kwargs["fov_estimate"] is None
            assert kwargs["fov_max_error"] is None
            return dict(RA=250, Dec=-8, FOV=15.4, Matches=9, RMSE=30, Prob=1e-20)

    points = np.array([[500 + i * 10, 900 + i * 10] for i in range(9)] + [[0, 0]])
    result = measure_lens_frame(
        T3(), {"centroids": points, "frame_hw": (1080, 1920)}, "imx462_color"
    )
    assert result["reason"] == "accepted"
    assert result["focal_length_mm"] == pytest.approx(
        2.842 / (2 * math.tan(math.radians(15.4 / 2)))
    )


def test_manual_distortion_is_saved_reloaded_and_isolated_by_precise_focal_length():
    cfg = Config()
    cfg.set_options({"camera_lens": "manual", "camera_lens_focal_length_mm": 10.5234})
    profile = get_camera_profile("imx462_color")
    store = CalibrationProfileStore(cfg)
    saved = store.save_auto_sky(
        "imx462_color", "manual", profile, {"k1": -0.05}, {"frames": 5}
    )
    assert "manual-10.5234mm" in saved["id"]
    assert (
        CalibrationProfileStore(cfg).load_active("imx462_color", "manual", profile)
        == saved
    )
    cfg.set_option("camera_lens_focal_length_mm", 10.5267)
    assert store.load_active("imx462_color", "manual", profile) is None
    assert store.clear("imx462_color", "manual", profile) == 0
    cfg.set_option("camera_lens_focal_length_mm", 10.5234)
    assert store.clear("imx462_color", "manual", profile) == 1
