"""Route unsolved user alignment to the active GoTo arrival lifecycle."""

import json
import math
import time

from PiFinder import utils


def queue_unsolved_arrival(guide_queue, shared_state, ra, dec):
    if guide_queue is None:
        return False
    try:
        with open(
            utils.runtime_dir / "indi_goto_guide_status.json", encoding="utf-8"
        ) as stream:
            status = json.load(stream)
        age = time.time() - float(status["updated"])
        if not 0 <= age <= 5 or status.get("goto_method") != "mfnavis":
            return False
        if status.get("phase") not in {
            "manual_retarget",
            "native_pending",
            "native_goto",
            "native_tracking",
            "pifinder_goto",
            "pifinder_pulse_align",
            "arrived_waiting_solve",
        }:
            return False
        ra, dec = float(ra), float(dec)
        if not math.isfinite(ra) or not math.isfinite(dec) or abs(dec) > 90:
            return False
        solution = shared_state.solution()
        success = getattr(solution, "last_solve_success", None)
        attempt = getattr(solution, "last_solve_attempt", None)
        if success and 0 <= time.time() - success <= 12 and (attempt or 0) <= success:
            return False
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False
    guide_queue.put(
        {
            "type": "confirm_goto_arrival",
            "ra": ra % 360,
            "dec": dec,
            "requested_wall": time.time(),
        }
    )
    return True
