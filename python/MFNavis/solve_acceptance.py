"""Plate-solve quality and temporal-continuity safety gates.

Tetra3's statistical match threshold is necessary but not sufficient when a
wide urban frame contains point-like building lights.  This module keeps the
policy independent from the solver loop so field thresholds and jump handling
can be replay-tested without camera or multiprocessing state.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, cast


# 2026-09-02, IMX462 + 6 mm urban field: correct SEP solves had 7--10
# matches, RMSE 78--234 arcsec and Prob 3.7e-8--1.3e-5.  Marginal six-match
# solutions repeatedly landed at Prob 9.54e-5, immediately below tetra3's
# 1e-4 built-in threshold.  The limits below retain the stable correct group
# while rejecting those one-pattern edge cases and the worst distorted fit.
SEP_MIN_MATCHES = 7
FULLFRAME_MIN_MATCHES = 6
FULLFRAME_MAX_RMSE_ARCSEC = 180.0
FULLFRAME_MAX_FALSE_PROBABILITY = 5.0e-5

# A valid solve can move slowly as the sky drifts.  A deliberate telescope
# slew may jump anywhere, so it is not forbidden: it becomes trusted after a
# second independent solve agrees.  This costs one solve interval after a
# large move while preventing a single accidental urban-light pattern from
# becoming pointing truth.
TRUSTED_JUMP_DEG = 5.0
CONFIRM_AGREEMENT_DEG = 2.0
CONFIRM_MAX_AGE_S = 15.0

# When the IMU says the instrument is stationary, consecutive pointings may
# still move at the sidereal rate because a fixed Alt/Az direction sweeps
# across RA/Dec.  Allow that physical rate plus a small measurement floor;
# larger changes must agree on the next independent frame before replacing
# pointing truth.  This suppresses one-frame centroid/fallback excursions
# without freezing a fixed terrestrial instrument's legitimate sky drift.
STATIONARY_BASE_ALLOWANCE_DEG = 0.025  # 1.5 arcmin
SIDEREAL_RATE_DEG_PER_SECOND = 360.0 / 86164.0905
STATIONARY_RATE_MARGIN = 1.25


@dataclass(frozen=True)
class SolveAcceptanceDecision:
    accepted: bool
    reason: str
    separation_deg: float | None = None


def angular_separation_deg(
    ra1_deg: float, dec1_deg: float, ra2_deg: float, dec2_deg: float
) -> float:
    """Great-circle separation with stable behaviour at RA wrap/poles."""

    if not all(math.isfinite(v) for v in (ra1_deg, dec1_deg, ra2_deg, dec2_deg)):
        return math.inf
    if not (-90 <= dec1_deg <= 90 and -90 <= dec2_deg <= 90):
        return math.inf
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1_deg, dec1_deg, ra2_deg, dec2_deg))
    cos_sep = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(
        dec2
    ) * math.cos(ra1 - ra2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


def solution_coordinates(
    solution: Mapping[str, Any], ra_key: str = "RA", dec_key: str = "Dec"
) -> tuple[float, float] | None:
    """Validate a complete coordinate pair before normalization or calibration."""
    try:
        ra, dec = float(solution[ra_key]), float(solution[dec_key])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(ra) or not math.isfinite(dec) or not -90 <= dec <= 90:
        return None
    return ra % 360.0, dec


def solution_quality_decision(
    solution: Mapping[str, object] | None, solve_path: str
) -> SolveAcceptanceDecision:
    """Reject weak native-full-frame matches before they reach pointing.

    The established 512 Cedar path is unchanged.  Native full-frame paths
    have a much larger combinatorial field and, for 6-mm optics, significant
    unmodelled edge distortion; they therefore need explicit match, residual,
    and false-probability bounds in addition to tetra3's internal pattern
    threshold.
    """

    if not solution or solution.get("RA") is None:
        return SolveAcceptanceDecision(False, "no_solution")
    if solution_coordinates(solution) is None:
        return SolveAcceptanceDecision(False, "invalid_coordinates")
    if any(solution.get(key) is not None for key in ("RA_target", "Dec_target")):
        if solution_coordinates(solution, "RA_target", "Dec_target") is None:
            return SolveAcceptanceDecision(False, "invalid_target_coordinates")
    native_fullframe_path = solve_path in {
        "sep_center",
        "sep_full",
        "cedar_center",
        "cedar_full",
    } or solve_path.startswith("preprocessed_")
    if not native_fullframe_path:
        return SolveAcceptanceDecision(True, "established_path")
    try:
        matches = int(cast(Any, solution.get("Matches") or 0))
        rmse = float(cast(Any, solution.get("RMSE")))
        probability = float(cast(Any, solution.get("Prob")))
    except (TypeError, ValueError, OverflowError):
        return SolveAcceptanceDecision(False, "missing_quality_metrics")
    if not all(math.isfinite(value) for value in (rmse, probability)):
        return SolveAcceptanceDecision(False, "nonfinite_quality_metrics")
    min_matches = SEP_MIN_MATCHES if "sep" in solve_path else FULLFRAME_MIN_MATCHES
    if matches < min_matches:
        return SolveAcceptanceDecision(False, f"matches_below_{min_matches}")
    if rmse > FULLFRAME_MAX_RMSE_ARCSEC:
        return SolveAcceptanceDecision(False, "rmse_too_high")
    if probability > FULLFRAME_MAX_FALSE_PROBABILITY:
        return SolveAcceptanceDecision(False, "false_probability_too_high")
    return SolveAcceptanceDecision(True, "quality_ok")


class SolveContinuityGate:
    """Require confirmation for cold native-full-frame locks and large jumps."""

    def __init__(
        self,
        *,
        trusted_jump_deg: float = TRUSTED_JUMP_DEG,
        confirm_agreement_deg: float = CONFIRM_AGREEMENT_DEG,
        confirm_max_age_s: float = CONFIRM_MAX_AGE_S,
        stationary_base_allowance_deg: float = STATIONARY_BASE_ALLOWANCE_DEG,
    ) -> None:
        self.trusted_jump_deg = float(trusted_jump_deg)
        self.confirm_agreement_deg = float(confirm_agreement_deg)
        self.confirm_max_age_s = float(confirm_max_age_s)
        self.stationary_base_allowance_deg = float(stationary_base_allowance_deg)
        self._trusted: tuple[float, float] | None = None
        self._trusted_time: float | None = None
        self._trusted_path: str | None = None
        self._pending: tuple[float, float, float] | None = None
        self._pending_kind: str | None = None

    @staticmethod
    def _coordinates(solution: Mapping[str, object]) -> tuple[float, float] | None:
        return solution_coordinates(solution)

    def evaluate(
        self,
        solution: Mapping[str, object],
        solve_path: str,
        timestamp: float,
        *,
        stationary: bool = False,
        prefer_preprocessed: bool = False,
    ) -> SolveAcceptanceDecision:
        coords = self._coordinates(solution)
        if coords is None or not math.isfinite(timestamp):
            return SolveAcceptanceDecision(False, "invalid_coordinates")
        ra, dec = coords

        # The small, established production crop is allowed to establish the
        # first anchor immediately. Native full-frame matches need a second
        # frame because they are the path exposed to urban-light patterns.
        established_path = solve_path in {"cedar_512", "cedar_center"}
        if (
            self._trusted is None
            and established_path
            and not (stationary and prefer_preprocessed)
        ):
            self._accept(coords, solve_path, timestamp)
            return SolveAcceptanceDecision(True, "initial_established_anchor")

        if self._trusted is not None:
            separation = angular_separation_deg(*self._trusted, ra, dec)
            if separation <= self.trusted_jump_deg:
                raw_fallback_transition = bool(
                    stationary
                    and prefer_preprocessed
                    and (self._trusted_path or "").startswith("preprocessed_")
                    and not solve_path.startswith("preprocessed_")
                )
                within_stationary_allowance = (
                    not stationary
                    or separation <= self._stationary_allowance(timestamp)
                )
                if within_stationary_allowance and not raw_fallback_transition:
                    self._accept(coords, solve_path, timestamp)
                    return SolveAcceptanceDecision(True, "near_trusted", separation)

                confirmed = self._confirm_pending(
                    coords,
                    solve_path,
                    timestamp,
                    kind="stationary",
                )
                if confirmed is not None:
                    return confirmed
                self._set_pending(coords, timestamp, "stationary")
                reason = (
                    "raw_fallback_confirmation"
                    if raw_fallback_transition
                    else "stationary_change_confirmation"
                )
                return SolveAcceptanceDecision(False, reason, separation)
        else:
            separation = None

        if stationary and prefer_preprocessed and self._trusted is None:
            confirmed = self._confirm_pending(
                coords,
                solve_path,
                timestamp,
                kind="stationary",
            )
            if confirmed is not None:
                return confirmed
            self._set_pending(coords, timestamp, "stationary")
            return SolveAcceptanceDecision(
                False, "initial_preferred_confirmation", separation
            )

        confirmed = self._confirm_pending(
            coords,
            solve_path,
            timestamp,
            kind="jump",
        )
        if confirmed is not None:
            return confirmed

        self._set_pending(coords, timestamp, "jump")
        reason = (
            "initial_fullframe_confirmation"
            if self._trusted is None
            else "jump_confirmation"
        )
        return SolveAcceptanceDecision(False, reason, separation)

    def _stationary_allowance(self, timestamp: float) -> float:
        if self._trusted_time is None:
            return self.stationary_base_allowance_deg
        age = max(0.0, float(timestamp) - self._trusted_time)
        return self.stationary_base_allowance_deg + (
            SIDEREAL_RATE_DEG_PER_SECOND * STATIONARY_RATE_MARGIN * age
        )

    def _pending_agreement(self, timestamp: float, kind: str) -> float:
        if kind != "stationary" or self._pending is None:
            return self.confirm_agreement_deg
        age = max(0.0, float(timestamp) - self._pending[2])
        return self.stationary_base_allowance_deg + (
            SIDEREAL_RATE_DEG_PER_SECOND * STATIONARY_RATE_MARGIN * age
        )

    def _confirm_pending(
        self,
        coords: tuple[float, float],
        solve_path: str,
        timestamp: float,
        *,
        kind: str,
    ) -> SolveAcceptanceDecision | None:
        if self._pending is None or self._pending_kind != kind:
            return None
        pending_ra, pending_dec, pending_time = self._pending
        age = float(timestamp) - pending_time
        agreement = angular_separation_deg(*coords, pending_ra, pending_dec)
        if (
            0.0 <= age <= self.confirm_max_age_s
            and agreement <= self._pending_agreement(timestamp, kind)
        ):
            self._accept(coords, solve_path, timestamp)
            reason = (
                "confirmed_stationary_change"
                if kind == "stationary"
                else "confirmed_jump"
            )
            return SolveAcceptanceDecision(True, reason, agreement)
        return None

    def _set_pending(
        self,
        coords: tuple[float, float],
        timestamp: float,
        kind: str,
    ) -> None:
        self._pending = (*coords, float(timestamp))
        self._pending_kind = kind

    def _accept(
        self,
        coords: tuple[float, float],
        solve_path: str,
        timestamp: float,
    ) -> None:
        self._trusted = coords
        self._trusted_time = float(timestamp)
        self._trusted_path = solve_path
        self._pending = None
        self._pending_kind = None
