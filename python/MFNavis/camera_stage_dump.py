#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
One-shot dump of every camera pipeline stage feeding the solver.

The processed frame the solver sees is several steps removed from the
sensor: crop/rotate -> bias subtract -> digital gain -> 8-bit stretch ->
512x512 resize -> screen-direction rotation. When detection misbehaves,
"which stage lost the stars" is the question -- so each stage is written
losslessly to one directory for offline inspection:

* uint16 stages -> 16-bit grayscale PNG (values as captured, no stretch)
* float stages  -> .npy (bit-exact)
* uint8 stages  -> 8-bit grayscale PNG
* stats.json    -> per-stage shape/dtype/percentiles plus capture metadata

Armed with the ``save_stages`` camera command (POST /api/camera/stages);
the next captured frame is dumped. Stages 0-4 are written by the Pi
camera's ``capture()``, the final solver-input stage by the camera loop
after rotation.
"""

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger("Camera.StageDump")


def stage_stats(name: str, filename: Optional[str], arr: np.ndarray) -> dict:
    """Summary statistics for one pipeline stage."""
    finite = np.asarray(arr, dtype=np.float64)
    percentiles = np.percentile(finite, [1, 10, 50, 90, 99])
    return {
        "stage": name,
        "file": filename,
        "shape": list(arr.shape),
        "dtype": str(arr.dtype),
        "min": float(finite.min()),
        "p01": float(percentiles[0]),
        "p10": float(percentiles[1]),
        "p50": float(percentiles[2]),
        "p90": float(percentiles[3]),
        "p99": float(percentiles[4]),
        "max": float(finite.max()),
        "mean": float(finite.mean()),
    }


def save_stage(dump_dir: Path, index: int, name: str, arr: np.ndarray) -> dict:
    """Write one stage losslessly and return its stats entry."""
    dump_dir.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(arr)
    base = f"{index:02d}_{name}"
    if arr.dtype == np.uint16:
        filename = f"{base}.png"
        Image.fromarray(arr, mode="I;16").save(dump_dir / filename)
    elif arr.dtype == np.uint8:
        filename = f"{base}.png"
        Image.fromarray(arr, mode="L").save(dump_dir / filename)
    else:
        filename = f"{base}.npy"
        np.save(dump_dir / filename, arr)
    logger.debug("Stage dump: wrote %s", dump_dir / filename)
    return stage_stats(name, filename, arr)


def finalize(dump_dir: Path, stats: list, metadata: dict) -> None:
    """Write stats.json next to the stage files."""
    dump_dir.mkdir(parents=True, exist_ok=True)
    payload = {"metadata": metadata, "stages": stats}
    with open(dump_dir / "stats.json", "w") as f:
        json.dump(payload, f, indent=2)
    logger.info("Stage dump complete: %s (%d stages)", dump_dir, len(stats))


def prune_dumps(root: Path, keep: int = 30) -> int:
    """Delete the oldest ``stages_*`` dirs under ``root`` beyond ``keep``.

    Dumps live on tmpfs (utils.runtime_capture_dir); without a bound, a
    night of automatic corpus collection (~9 MB every 3 minutes) would
    fill /dev/shm and take the logs and cedar's shared memory with it.
    Returns the number of dumps removed.
    """
    import shutil

    if not root.exists():
        return 0
    dumps = sorted(d for d in root.glob("stages_*") if d.is_dir())
    removed = 0
    for stale in dumps[: max(0, len(dumps) - keep)]:
        try:
            shutil.rmtree(stale)
            removed += 1
        except OSError:
            logger.exception("Stage dump prune failed for %s", stale)
    if removed:
        logger.info("Pruned %d stage dump(s), keeping newest %d", removed, keep)
    return removed
