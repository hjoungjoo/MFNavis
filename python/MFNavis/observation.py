"""Small, explicit coordinate snapshots for saved observing evidence.

A selected target is an intention, never ground truth for a camera centre.
Shared-state reads are not atomic with a camera exposure; keep both epochs.
"""

import math
from numbers import Real, Integral
import time
from typing import Any


def finite(value):
    if not isinstance(value, (Real, str)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def target_coordinates(target):
    if target is None:
        return None
    object_id = getattr(target, "object_id", None)
    name = getattr(target, "display_name", None)
    return {
        "object_id": int(object_id) if isinstance(object_id, Integral) else None,
        "name": name if isinstance(name, str) else None,
        "ra_deg": finite(getattr(target, "ra", None)),
        "dec_deg": finite(getattr(target, "dec", None)),
        "source": "ui_state.target",
    }


def target_key(target):
    value = target_coordinates(target)
    return None if value is None else tuple(value.values())


def observation_snapshot(shared_state):
    """Best-effort snapshot, including target even when solving is unavailable."""
    result: dict[str, Any] = {
        "schema_version": 1,
        "coordinate_frame": "J2000",
        "angle_unit": "degree",
        "snapshot_unix_s": time.time(),
        "snapshot_monotonic_ns": time.monotonic_ns(),
        "binding": "shared_state_snapshot_not_atomic_with_exposure",
        "target": None,
        "pointing": None,
        "unavailable": [],
    }
    try:
        result["target"] = target_coordinates(shared_state.ui_state().target())
    except Exception:
        result["unavailable"].append("target")
    try:
        sol = shared_state.solution()
        matrix = {}
        for axis in ("camera", "aligned"):
            matrix[axis] = {}
            for state in ("solve", "estimate"):
                point = getattr(getattr(sol.pointing, axis), state)
                matrix[axis][state] = (
                    {
                        "ra_deg": finite(point.RA),
                        "dec_deg": finite(point.Dec),
                        "roll_deg": finite(point.Roll),
                        "epoch_unix_s": finite(
                            sol.last_solve_success
                            if state == "solve"
                            else sol.estimate_time
                        ),
                    }
                    if point is not None
                    else None
                )
        result["pointing"] = matrix
        frame_id = getattr(sol.diagnostics, "FrameId", None)
        result["solve_frame_id"] = (
            int(frame_id) if isinstance(frame_id, Integral) else None
        )
        result["last_solve_attempt_unix_s"] = finite(sol.last_solve_attempt)
        result["solve_state"] = bool(shared_state.solve_state())
    except Exception:
        result["unavailable"].append("pointing")
    try:
        result["target_pixel_yx"] = [
            finite(value) for value in shared_state.target_pixel()
        ]
    except Exception:
        result["unavailable"].append("target_pixel")
    result["snapshot_end_unix_s"] = time.time()
    return result
