"""Detector contract and native ABI regressions on independently defined stars."""

import ctypes
from pathlib import Path

import numpy as np
import pytest

from PiFinder import star_detect

pytestmark = pytest.mark.unit


def star_field():
    yy, xx = np.indices((400, 500))
    rng = np.random.default_rng(42)
    frame = 500 + 0.1 * xx + rng.normal(0, 3, xx.shape)
    stars = [(100.3, 120.7), (240.8, 310.2), (130.2, 400.5)]
    for y, x in stars:
        frame += 450 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * 1.4**2))
    frame[300, 100] = 4095
    return frame.astype(np.uint16), np.asarray(stars)


@pytest.mark.parametrize("backend", ["sep", "mf"])
@pytest.mark.parametrize("refine", ["0", "1"])
@pytest.mark.parametrize("ranking", ["response", "flux"])
def test_real_centroids_and_hot_pixel_rejection(monkeypatch, backend, refine, ranking):
    monkeypatch.setenv("MF_DETECT_REFINE", refine)
    monkeypatch.setenv("MF_DETECT_RANKING", ranking)
    if (
        backend == "mf"
        and not (
            Path.home() / "mf_detect_star_test/build/libmf_detect_star.so"
        ).exists()
    ):
        pytest.skip("build native test library first")
    monkeypatch.setenv("PIFINDER_DETECTOR", backend)
    frame, truth = star_field()
    result = star_detect.detect_stars(frame, sigma=4.0, saturation_level=4095)
    for point in truth:
        assert np.linalg.norm(result.centroids - point, axis=1).min() < 0.6
    assert np.linalg.norm(result.centroids - [300, 100], axis=1).min() > 4
    if backend == "sep" or ranking == "flux":
        assert np.all(np.diff(result.fluxes) <= 0)


def test_unknown_backend_fails_explicitly(monkeypatch):
    monkeypatch.setenv("PIFINDER_DETECTOR", "invalid")
    with pytest.raises(ValueError, match="unknown detector"):
        star_detect.detect_stars(np.zeros((128, 128), dtype=np.uint16))


def test_native_abi_rejects_null_input():
    if not (Path.home() / "mf_detect_star_test/build/libmf_detect_star.so").exists():
        pytest.skip("build native test library first")
    lib = star_detect._native_library()
    data = (ctypes.c_float * 3)()
    elapsed = ctypes.c_double()
    assert (
        lib.mfds_detect_u16(None, 2, 2, 2, 4095, 2, 4.5, data, 1, ctypes.byref(elapsed))
        < 0
    )
