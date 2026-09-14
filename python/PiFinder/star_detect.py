"""Cedar-free detector selection; SEP is the test branch default.

The optional native library is loaded only with PIFINDER_DETECTOR=mf.
Both backends return full sensor (y, x). SEP ranks by flux; native defaults
to detection response (MF_DETECT_RANKING=flux restores flux ranking). Native morphology
is followed by PiFinder's geometric/saturation gates. No sockets or camera
access are needed.
"""

import ctypes
import os
from pathlib import Path
import time

import numpy as np

from PiFinder import sep_detect

_library = None


def _native_library():
    global _library
    if _library is None:
        path = Path(
            os.environ.get(
                "MF_DETECT_LIBRARY",
                str(Path.home() / "mf_detect_star_test/build/libmf_detect_star.so"),
            )
        )
        lib = ctypes.CDLL(str(path))
        if lib.mfds_abi_version() != 1:
            raise RuntimeError("unsupported mf_detect_star ABI")
        lib.mfds_detect_u16.argtypes = [
            ctypes.POINTER(ctypes.c_uint16),
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_float,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_double),
        ]
        lib.mfds_detect_u16.restype = ctypes.c_int
        if hasattr(lib, "mfds_detect_u16_refined"):
            lib.mfds_detect_u16_refined.argtypes = lib.mfds_detect_u16.argtypes
            lib.mfds_detect_u16_refined.restype = ctypes.c_int
        _library = lib
    return _library


def detect_stars(raw_frame, **kwargs):
    backend = os.environ.get("PIFINDER_DETECTOR", "sep")
    if backend == "sep":
        return sep_detect.detect_stars(raw_frame, **kwargs)
    if backend != "mf":
        raise ValueError(f"unknown detector: {backend}")
    started = time.perf_counter()
    arr = np.ascontiguousarray(raw_frame, dtype=np.uint16)
    if arr.ndim != 2:
        raise ValueError("native detector requires a 2D RAW frame")
    capacity = 128
    output = np.empty((capacity, 3), dtype=np.float32)
    elapsed = ctypes.c_double()
    lib = _native_library()
    detect = (
        lib.mfds_detect_u16_refined
        if os.environ.get("MF_DETECT_REFINE", "0") == "1"
        else lib.mfds_detect_u16
    )
    count = detect(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_uint16)),
        arr.shape[1],
        arr.shape[0],
        arr.shape[1],
        int(kwargs.get("saturation_level") or 65535),
        int(os.environ.get("MF_DETECT_BINNING", "2")),
        float(os.environ.get("MF_DETECT_SIGMA", "4.5")),
        output.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        capacity,
        ctypes.byref(elapsed),
    )
    if count < 0:
        raise RuntimeError(f"native detector failed: {count}")
    points = output[:count, :2].astype(np.float64)
    flux = output[:count, 2].astype(np.float64)
    order = (
        np.arange(len(flux))
        if os.environ.get("MF_DETECT_RANKING", "response") == "response"
        else np.argsort(-flux, kind="stable")
    )
    points, flux = points[order], flux[order]
    # Reuse project-owned point-source/warm/saturation/cluster gates.
    filtered = sep_detect.filter_plain_centroids(
        points,
        arr,
        saturation_level=kwargs.get("saturation_level"),
        warm_pixel_map=kwargs.get("warm_pixel_map"),
    )
    filtered = np.asarray(filtered, dtype=np.float64).reshape(-1, 2)
    keep = np.asarray(
        [np.any(np.all(filtered == point, axis=1)) for point in points], dtype=bool
    )
    points, flux = points[keep], flux[keep]
    if kwargs.get("cloud_window_gate", False) and len(points):
        from PiFinder.mf_cloud_gate import select_clear_window_candidates
        from PiFinder.mf_star_only_preprocess import _robust_cell_background

        background = _robust_cell_background(sep_detect.bin2x2(arr), 32)
        selection = select_clear_window_candidates(
            background, (points - 0.5) / 2, enabled=True
        )
        points, flux = points[selection.keep], flux[selection.keep]
    max_stars = int(os.environ.get("MF_DETECT_MAX_STARS", kwargs.get("max_stars", 48)))
    return sep_detect.SepDetection(
        centroids=points[:max_stars],
        fluxes=flux[:max_stars],
        background_median=0.0,
        background_rms=0.0,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
    )
