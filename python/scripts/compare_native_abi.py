"""Check native optimization against a frozen ABI library on identical frames."""

import argparse
import ctypes
import json
from pathlib import Path

import numpy as np
from PIL import Image


def load(path):
    lib = ctypes.CDLL(str(path))
    fn = lib.mfds_detect_u16
    fn.argtypes = [
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
    fn.restype = ctypes.c_int
    return fn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    frames = []
    root = Path.home()
    for folder, pattern in [
        (
            root / "MFNavis_data/captures/mf_replay/20260903_cloud_coordinate_jitter",
            "raw_*.tiff",
        ),
        (root / "MFNavis_data/test_data/cache/cloud", "*.npy"),
        (root / "MFNavis_data/test_data/corpora/20260915_fixed_lights", "raw_*.tiff"),
        (root / "MFNavis_data/test_data/cache/current", "*.npy"),
    ]:
        files = sorted(folder.glob(pattern))
        for index in np.linspace(0, len(files) - 1, 6, dtype=int):
            path = files[index]
            if path.suffix == ".npy":
                a, maximum = np.load(path), 65535
            else:
                a = np.rot90(np.asarray(Image.open(path)), -1)
                maximum = 4095
            frames.append(
                (str(path), np.ascontiguousarray(a, dtype=np.uint16), maximum)
            )
    functions = [load(args.before), load(args.after)]
    rows = []
    max_xy = 0.0
    max_flux = 0.0
    for index, (path, frame, maximum) in enumerate(frames):
        outputs = {}
        for repeat in range(4):
            for mode in [0, 1] if (index + repeat) % 2 else [1, 0]:
                output = np.zeros((128, 3), dtype=np.float32)
                elapsed = ctypes.c_double()
                count = functions[mode](
                    frame.ctypes.data_as(ctypes.POINTER(ctypes.c_uint16)),
                    frame.shape[1],
                    frame.shape[0],
                    frame.shape[1],
                    maximum,
                    2,
                    4.5,
                    output.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    128,
                    ctypes.byref(elapsed),
                )
                assert count >= 0
                outputs[mode] = output[:count].copy()
                if repeat:
                    rows.append(
                        {
                            "file": path,
                            "mode": mode,
                            "ms": elapsed.value,
                            "count": count,
                        }
                    )
            assert outputs[0].shape == outputs[1].shape, path
            if len(outputs[0]):
                delta = np.abs(outputs[0] - outputs[1])
                max_xy = max(max_xy, float(delta[:, :2].max()))
                max_flux = max(max_flux, float(delta[:, 2].max()))
        print(Path(path).name, "checked", flush=True)
    summary = {
        "frames": len(frames),
        "max_xy_delta_px": max_xy,
        "max_flux_delta": max_flux,
    }
    for mode in [0, 1]:
        values = [r["ms"] for r in rows if r["mode"] == mode]
        summary[str(mode)] = {
            "p50_ms": float(np.median(values)),
            "p95_ms": float(np.percentile(values, 95)),
        }
    args.output.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(json.dumps(summary), flush=True)
    assert max_xy <= 0.001, summary


if __name__ == "__main__":
    main()
