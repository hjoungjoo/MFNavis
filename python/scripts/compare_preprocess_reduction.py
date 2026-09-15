"""Verify streamed temporal arithmetic against the pre-change implementation."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image

from PiFinder import mf_star_only_preprocess as current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        "preprocess_reference", args.reference
    )
    reference = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = reference
    spec.loader.exec_module(reference)
    paths = sorted(
        (Path.home() / "PiFinder_test_data/corpora/20260915_fixed_lights").glob(
            "raw_*.tiff"
        )
    )[30:40]
    frames = [
        np.ascontiguousarray(
            np.rot90(np.asarray(Image.open(path), dtype=np.uint16), -1)
        )
        for path in paths
    ]
    accumulators = [reference.MFStarOnlyAccumulator(), current.MFStarOnlyAccumulator()]
    rows = []
    try:
        for index, frame in enumerate(frames):
            results = {}
            for mode in [0, 1] if index % 2 else [1, 0]:
                start = time.perf_counter()
                result = accumulators[mode].add(
                    frame, saturation_level=4095, fingerprint=("fixed",)
                )
                elapsed = (time.perf_counter() - start) * 1000
                results[mode] = result
                rows.append({"file": paths[index].name, "mode": mode, "ms": elapsed})
            np.testing.assert_array_equal(results[0].frame, results[1].frame)
            np.testing.assert_array_equal(results[0].evidence, results[1].evidence)
            assert vars(results[0].diagnostics) == vars(results[1].diagnostics)
            print(paths[index].name, "pixel-identical", flush=True)
    finally:
        for accumulator in accumulators:
            accumulator.close()
    summary = {"frames": len(frames), "pixel_identical": True}
    for mode in [0, 1]:
        values = [r["ms"] for r in rows[2:] if r["mode"] == mode]
        summary[str(mode)] = {
            "p50_ms": float(np.median(values)),
            "p95_ms": float(np.percentile(values, 95)),
        }
    args.output.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
