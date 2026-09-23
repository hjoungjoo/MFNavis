"""On-sky optical scale measurement, isolated from published plate solutions."""

from __future__ import annotations

import math
import logging
import time
from concurrent.futures import Future
from typing import Any

import numpy as np

from PiFinder.mf_manual_lens import calibration_lens_key
from PiFinder.sqm.camera_profiles import get_camera_profile

logger = logging.getLogger("LensMeasurement")

REQUIRED_FRAMES = 5


def measure_lens_frame(t3, payload, camera_type) -> dict[str, Any]:
    """Blind-solve the native central crop, without a previous lens correction."""
    profile = get_camera_profile(camera_type)
    side = min(profile.crop_size)
    h, w = payload["frame_hw"]
    origin = np.array([(h - side) / 2, (w - side) / 2])
    points = np.asarray(payload["centroids"], dtype=float).reshape(-1, 2) - origin
    points = points[np.all((points >= 0) & (points < side), axis=1)]
    result: dict[str, Any] = {
        "candidates": len(points),
        "reason": "not_enough_candidates",
    }
    if len(points) < 8:
        return result
    solution = (
        t3.solve_from_centroids(
            points,
            (side, side),
            fov_estimate=None,
            fov_max_error=None,
            match_max_error=0.005,
            solve_timeout=1500,
        )
        or {}
    )
    if solution.get("RA") is None:
        return {**result, "reason": "no_pattern_match"}
    fov = float(solution.get("FOV") or 0)
    if not (0 < fov < 120) or not (
        int(solution.get("Matches") or 0) >= 8
        and float(solution.get("RMSE", math.inf)) < 90
        and float(solution.get("Prob", math.inf)) < 1e-6
    ):
        return {**result, "reason": "low_quality"}
    focal = side * profile.pixel_pitch_um / 1000 / (2 * math.tan(math.radians(fov / 2)))
    if not 0.1 <= focal <= 99.9:
        return {**result, "reason": "invalid_focal_length"}
    return {
        **result,
        "reason": "accepted",
        "focal_length_mm": focal,
        "fov_deg": fov,
        "ra": float(solution["RA"]),
        "dec": float(solution["Dec"]),
        "rmse": float(solution["RMSE"]),
    }


class LensMeasurement:
    """A cancellable session; only the solver thread may commit its result."""

    def __init__(self, cfg, shared_state, submit) -> None:
        self.cfg = cfg
        self.state = shared_state
        self.submit = submit
        self.active = False
        self.future: Future | None = None
        self.samples: list[dict[str, Any]] = []
        self.seen: set[Any] = set()
        self.request_id = 0
        self.camera_type = ""
        self.started = 0.0
        self.context = ""

    def _context(self) -> str:
        return calibration_lens_key(
            str(self.state.camera_lens() or ""),
            self.state.camera_lens_focal_length_mm(),
        )

    def _status(self, state="collecting", reason="accepted", **extra) -> None:
        self.state.set_lens_measurement_status(
            {
                "state": state,
                "request_id": self.request_id,
                "accepted_frames": len(self.samples),
                "required_frames": REQUIRED_FRAMES,
                "last_reason": reason,
                **extra,
            }
        )

    def start(self, command) -> None:
        self.request_id = command.request_id
        self.camera_type = command.camera_type
        self.samples = []
        self.seen = set()
        self.started = time.monotonic()
        self.context = self._context()
        self.active = True
        # An old worker may finish, but its tagged result will be discarded.
        self._status("requested", "waiting_stars")
        logger.info(
            "Auto lens measurement started: %s request=%s",
            self.camera_type,
            self.request_id,
        )

    def cancel(self, request_id=None) -> None:
        if request_id is None or request_id == self.request_id:
            self.active = False
            self._status("cancelled", "cancelled")

    def observe(self, payload, frame_id, moving) -> None:
        if not self.active:
            return
        current = self.state.lens_measurement_status()
        if (
            current.get("request_id") != self.request_id
            or current.get("state") == "cancelled"
        ):
            self.active = False
            return
        if (
            self.state.camera_type() != self.camera_type
            or self._context() != self.context
        ):
            self.active = False
            self._status("error", "camera_or_lens_changed")
            return
        if time.monotonic() - self.started > 180:
            self.active = False
            self._status("error", "measurement_timeout")
            return
        if moving:
            # A fit from before movement cannot count toward a stationary run.
            self.samples = []
            if self.future is not None:
                self.future.cancel()
                self.future = None
            self._status("waiting_stars", "frame_moving")
            return
        if self.future is not None:
            if not self.future.done():
                return
            future, self.future = self.future, None
            try:
                request_id, sample = future.result()
            except Exception:
                self.active = False
                self._status("error", "internal_error")
                return
            if request_id == self.request_id:
                if sample["reason"] == "accepted":
                    if self.samples:
                        median = float(
                            np.median([s["focal_length_mm"] for s in self.samples])
                        )
                        previous = self.samples[-1]
                        separation = math.hypot(
                            ((sample["ra"] - previous["ra"] + 180) % 360 - 180)
                            * math.cos(math.radians(sample["dec"])),
                            sample["dec"] - previous["dec"],
                        )
                        if (
                            abs(sample["focal_length_mm"] / median - 1) > 0.01
                            or separation > 0.5
                        ):
                            self.samples = []
                    self.samples.append(sample)
                self._status(
                    reason=sample["reason"], last_candidates=sample["candidates"]
                )
                if len(self.samples) >= REQUIRED_FRAMES:
                    focal = round(
                        float(np.median([s["focal_length_mm"] for s in self.samples])),
                        4,
                    )
                    profile = get_camera_profile(self.camera_type)
                    fov = math.degrees(
                        2
                        * math.atan(
                            profile.crop_size[0]
                            * profile.pixel_pitch_um
                            / 1000
                            / (2 * focal)
                        )
                    )
                    # Config write is atomic; consumers retain measured precision.
                    self.cfg.set_options(
                        {"camera_lens": "manual", "camera_lens_focal_length_mm": focal}
                    )
                    self.state.set_camera_lens_focal_length_mm(focal)
                    self.state.set_camera_lens("manual")
                    self.active = False
                    logger.info(
                        "Auto lens saved: manual %.4f mm, crop FOV %.4f deg", focal, fov
                    )
                    self._status(
                        "completed", "saved", focal_length_mm=focal, fov_deg=fov
                    )
                    return
        if payload is None:
            self._status("waiting_stars", "waiting_full_frame")
        elif frame_id is not None and frame_id not in self.seen:
            self.seen.add(frame_id)
            self._status(
                "measuring",
                "measuring_frame",
                last_candidates=len(payload["centroids"]),
            )
            self.future = self.submit(self.request_id, payload, self.camera_type)
