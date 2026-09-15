"""Safe calibration of fast RAW solutions against trusted preprocessing.

An asynchronous preprocessed solve is necessarily older than the newest RAW
solve.  Publishing it directly would move the pointing estimate backwards in
time.  This tracker instead learns the small same-frame RAW-to-preprocessed
offset and applies that bias only to future RAW solutions.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Callable, Mapping, Optional

from PiFinder.solve_acceptance import angular_separation_deg, solution_coordinates


def _short_delta_deg(target: float, source: float) -> float:
    return (float(target) - float(source) + 180.0) % 360.0 - 180.0


@dataclass(frozen=True)
class BiasStatus:
    accepted_samples: int
    rejected_samples: int
    ready: bool
    camera_ra_deg: float
    camera_dec_deg: float
    target_ra_deg: Optional[float]
    target_dec_deg: Optional[float]
    last_separation_deg: Optional[float]


class PreprocessBiasTracker:
    def __init__(
        self,
        *,
        max_agreement_deg: float = 0.12,
        required_samples: int = 2,
        alpha: float = 0.25,
        max_age_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_agreement_deg = float(max_agreement_deg)
        self.required_samples = max(1, int(required_samples))
        self.alpha = min(1.0, max(0.0, float(alpha)))
        if not math.isfinite(max_age_s) or max_age_s <= 0:
            raise ValueError("max_age_s must be positive and finite")
        self.max_age_s = float(max_age_s)
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        self._last_update: Optional[float] = None
        self._accepted = 0
        self._rejected = 0
        self._camera_ra = 0.0
        self._camera_dec = 0.0
        self._target_ra: Optional[float] = None
        self._target_dec: Optional[float] = None
        self._last_separation: Optional[float] = None

    @property
    def ready(self) -> bool:
        self._expire()
        return self._accepted >= self.required_samples

    def _expire(self) -> None:
        if self._last_update is not None:
            age = self._clock() - self._last_update
            if not 0 <= age <= self.max_age_s:
                self.reset()

    def _blend(self, current: float, sample: float) -> float:
        if self._accepted == 0:
            return float(sample)
        return float(current) + self.alpha * (float(sample) - float(current))

    def update(
        self,
        raw_solution: Mapping[str, Any],
        trusted_solution: Mapping[str, Any],
    ) -> bool:
        self._expire()
        raw = solution_coordinates(raw_solution)
        trusted = solution_coordinates(trusted_solution)
        raw_target = solution_coordinates(raw_solution, "RA_target", "Dec_target")
        trusted_target = solution_coordinates(
            trusted_solution, "RA_target", "Dec_target"
        )
        # Missing aligned axes are optional; a supplied malformed pair rejects
        # the entire sample before any camera/target bias can change.
        invalid_target = any(
            any(sol.get(key) is not None for key in ("RA_target", "Dec_target"))
            and coords is None
            for sol, coords in (
                (raw_solution, raw_target),
                (trusted_solution, trusted_target),
            )
        )
        if raw is None or trusted is None or invalid_target:
            self._rejected += 1
            return False
        raw_ra, raw_dec = raw
        trusted_ra, trusted_dec = trusted
        if raw_target is not None and trusted_target is not None:
            if (
                angular_separation_deg(*raw_target, *trusted_target)
                > self.max_agreement_deg
            ):
                self._rejected += 1
                return False

        separation = angular_separation_deg(
            raw_ra,
            raw_dec,
            trusted_ra,
            trusted_dec,
        )
        self._last_separation = separation
        if separation > self.max_agreement_deg:
            self._rejected += 1
            return False

        self._camera_ra = self._blend(
            self._camera_ra,
            _short_delta_deg(trusted_ra, raw_ra),
        )
        self._camera_dec = self._blend(
            self._camera_dec,
            trusted_dec - raw_dec,
        )

        if raw_target is not None and trusted_target is not None:
            raw_target_ra, raw_target_dec = raw_target
            trusted_target_ra, trusted_target_dec = trusted_target
            target_ra_sample = _short_delta_deg(trusted_target_ra, raw_target_ra)
            target_dec_sample = trusted_target_dec - raw_target_dec
            if self._target_ra is None or self._target_dec is None:
                self._target_ra = target_ra_sample
                self._target_dec = target_dec_sample
            else:
                self._target_ra = self._blend(self._target_ra, target_ra_sample)
                self._target_dec = self._blend(self._target_dec, target_dec_sample)

        else:
            # Do not extend the lifetime of an older aligned-axis calibration
            # when only the camera axis was refreshed.
            self._target_ra = self._target_dec = None

        self._last_update = self._clock()
        self._accepted += 1
        return True

    def apply(self, solution: Mapping[str, Any]) -> dict:
        corrected = dict(solution)
        if not self.ready:
            return corrected
        camera = solution_coordinates(solution)
        if camera is None:
            return corrected
        corrected["RA"] = (camera[0] + self._camera_ra) % 360.0
        corrected["Dec"] = camera[1] + self._camera_dec
        if solution_coordinates(corrected) is None:
            return dict(solution)
        target = solution_coordinates(solution, "RA_target", "Dec_target")
        if (
            target is not None
            and self._target_ra is not None
            and self._target_dec is not None
        ):
            corrected["RA_target"] = (target[0] + self._target_ra) % 360.0
            corrected["Dec_target"] = target[1] + self._target_dec
            if solution_coordinates(corrected, "RA_target", "Dec_target") is None:
                return dict(solution)
        return corrected

    def status(self) -> BiasStatus:
        self._expire()
        return BiasStatus(
            accepted_samples=self._accepted,
            rejected_samples=self._rejected,
            ready=self.ready,
            camera_ra_deg=self._camera_ra,
            camera_dec_deg=self._camera_dec,
            target_ra_deg=self._target_ra,
            target_dec_deg=self._target_dec,
            last_separation_deg=self._last_separation,
        )
