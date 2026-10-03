"""Sensor time conversion with explicit backend semantics; no guessed freshness."""

import math
import time
import uuid

from PiFinder.tracking_contracts import CaptureTiming, fingerprint


def capture_timing(
    metadata, profile, *, mono=None, wall=None, boot=None, clock_epoch=None
):
    mono = time.monotonic() if mono is None else mono
    wall = time.time() if wall is None else wall
    boot = time.clock_gettime(time.CLOCK_BOOTTIME) if boot is None else boot
    policy = profile or {}
    epoch = clock_epoch or fingerprint(
        {
            "wall_offset": round(wall - mono),
            "boot_offset": round(boot - mono),
            "policy": policy,
        }
    )
    unknown = CaptureTiming(mono, mono, mono, 0, wall, False, epoch)
    try:
        if not policy.get("verified") or metadata.get("synthetic", False):
            return unknown
        if policy.get("camera") != metadata.get("camera_type") or policy.get(
            "backend"
        ) != metadata.get("capture_backend"):
            return unknown
        sensor = float(metadata["sensor_timestamp_ns"]) / 1e9
        exposure = float(metadata["actual_exposure_us"]) / 1e6
        uncertainty = float(policy["uncertainty_s"])
        skew = float(policy["rolling_skew_bound_s"])
        if not all(math.isfinite(v) for v in (sensor, exposure, uncertainty, skew)):
            return unknown
        if min(sensor, exposure) <= 0 or min(uncertainty, skew) < 0:
            return unknown
        clock = policy["clock"]
        if clock not in {"boottime", "monotonic"}:
            return unknown
        stamp = sensor + (mono - boot if clock == "boottime" else 0)
        if policy["timestamp_semantics"] == "first_row_readout":
            start = stamp - exposure
        elif policy["timestamp_semantics"] == "first_row_exposure_start":
            start = stamp
        else:
            return unknown
        end = start + exposure + skew
        midpoint = (start + end) / 2
        # Impossible future intervals are never silently clamped to 'now'.
        if end > mono + uncertainty or start > end:
            return unknown
        return CaptureTiming(
            start - uncertainty,
            end + uncertainty,
            midpoint,
            uncertainty + skew / 2,
            wall + midpoint - mono,
            True,
            epoch,
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return unknown


class CaptureClock:
    """Stable generation under clock jitter; invalidate on a clock discontinuity."""

    def __init__(self):
        self.offsets = None
        self.policy_id = None
        self.epoch = None

    def measure(self, metadata, policy):
        policy = policy if isinstance(policy, dict) else {}
        mono, wall = time.monotonic(), time.time()
        boot = time.clock_gettime(time.CLOCK_BOOTTIME)
        offsets = (wall - mono, boot - mono)
        policy_id = fingerprint(policy)
        if (
            self.offsets is None
            or policy_id != self.policy_id
            or any(abs(a - b) > 0.05 for a, b in zip(offsets, self.offsets))
        ):
            self.offsets, self.policy_id = offsets, policy_id
            self.epoch = uuid.uuid4().hex
        return capture_timing(
            metadata, policy, mono=mono, wall=wall, boot=boot, clock_epoch=self.epoch
        )
