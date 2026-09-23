#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Star-count controller for solver-driven auto-exposure.

An alternative to the match-count controller
(``auto_exposure.ExposurePIDController``), selected with the Camera Exp
menu's "Star" item (``camera_exp = "auto_star"``). The feedback signal is a
conservative full-frame consensus of gated Cedar and SEP detections (falling
back to ``SolveDiagnostics.Centroids``) rather than the number of stars tetra3
matched against the catalog. That distinction is the point:

* 0 detected -> exposure/optics problem -> zero-match recovery ladder
* N>0 detected but 0 matched -> solver-side problem -> the ladder does
  NOT run (the match-count controller cannot tell these apart)

When sky glow makes the response non-monotonic, the controller remembers the
recent per-exposure median detection yield. If a longer exposure loses the
candidates a shorter exposure retained, it holds the empirical best for 90
seconds instead of repeatedly hunting into saturation, then permits a fresh
scan so changing sky conditions can be learned.

The control law and defaults follow cedar-server's field-proven exposure
servo (https://github.com/smroid/cedar-server -- calibrator.rs /
detect_engine.rs): detectable star count is modelled as roughly
proportional to exposure, so a single division step converges within a
few solves. Instead of cedar's one-shot calibration, the "anchor"
exposure is learned while running: any exposure that lands inside the
deadband becomes the anchor, which bounds excursions (+/- 3 stops) and
serves as the fallback when the frame is unusable (slewing, clouds,
bright sky).

Design doc: docs/mf_dev/mf_auto_exposure_plan_ko.md.
"""

import logging
import time
from collections import deque
from statistics import median
from typing import Optional

from PiFinder.auto_exposure import ZeroMatchRecovery

logger = logging.getLogger("AutoExposure.StarCount")


def full_frame_star_count(
    production_crop_count: int,
    cedar_gated_count: Optional[int],
    cedar_raw_count: Optional[int] = None,
    sep_count: Optional[int] = None,
) -> int:
    """Choose the reliable widest-field detection count for exposure control.

    ``SolveDiagnostics.Centroids`` intentionally retains the historical
    production-crop count even when the solver detects on the full sensor.
    That is the wrong signal for exposure: a Moon or obstruction in the
    centre can leave the crop empty while usable stars remain around it.
    Prefer the full-frame Cedar count *after* warm-pixel/horizon/shape gates.
    Also admit a conservative count-level consensus between the independent
    Cedar and SEP detectors: no more candidates than the smaller detector saw.
    This recovers real peripheral stars that a geometry gate rejected without
    letting Cedar-only warm pixels or SEP-only noise make high gain look useful.
    Keep the crop count as a compatibility fallback and defensive lower bound.
    """
    crop_count = max(0, int(production_crop_count or 0))
    gated_count = max(0, int(cedar_gated_count or 0))
    consensus_count = 0
    if cedar_raw_count is not None and sep_count is not None:
        consensus_count = min(max(0, int(cedar_raw_count)), max(0, int(sep_count)))
    return max(crop_count, gated_count, consensus_count)


class ExposureStarCountController:
    """
    Drive exposure so cedar-detect keeps finding a target number of stars.

    Same call pattern as the match-count controller: ``update()`` once per
    new solve attempt, returning a new exposure in microseconds or None.
    """

    def __init__(
        self,
        target_stars: int = 20,
        ema_alpha: float = 0.5,
        deadband_low: float = 0.8,
        deadband_high: float = 1.6,
        min_stars_for_control: int = 4,
        anchor_stops: int = 8,
        min_exposure: int = 25000,
        max_exposure: int = 1000000,
        bright_sky_mean: float = 240.0,
        bright_clear_mean: float = 120.0,
        initial_anchor: int = 400000,
        reanchor_after: int = 3,
        low_star_escape_after: int = 4,
        anchor_trust_s: float = 90.0,
        trusted_zero_limit: int = 8,
        empirical_hold_s: float = 90.0,
        recovery: Optional[ZeroMatchRecovery] = None,
    ):
        """
        Initialize the star-count controller.

        Args:
            target_stars: Detected-centroid count to steer toward.
            ema_alpha: Smoothing factor for the detected-count EMA.
            deadband_low: Act only when count/target falls below this...
            deadband_high: ...or rises above this (asymmetric: shortfall
                is acted on quickly, excess stars are tolerated).
            min_stars_for_control: Below this count the frame is treated
                as slewing/blocked -- return to anchor instead of adjusting.
            anchor_stops: Clamp adjustments to anchor/stops..anchor*stops.
            min_exposure: Absolute exposure floor in microseconds.
            max_exposure: Absolute exposure ceiling in microseconds.
            bright_sky_mean: Center-ROI mean (8-bit) above which exposure
                is not raised -- more light will not add star contrast --
                and is stepped down instead.
            bright_clear_mean: Center-ROI mean below which a bright-sky
                ceiling is retired. Well under bright_sky_mean on purpose:
                the gap is the hysteresis that stops the servo climbing
                straight back into the sky glow it just left.
            initial_anchor: Anchor before any deadband hit (shipped
                default exposure, also the recovery ladder's first rung).
            reanchor_after: Consecutive adjustments clamped by the anchor
                bound in the same direction before the anchor follows the
                bound. Keeps the bound meaningful while letting the servo
                walk to a working exposure outside it.
            low_star_escape_after: Consecutive low-star (but nonzero)
                attempts at the anchor before the transient hypothesis
                (slew/blockage) expires and the servo searches instead.
            anchor_trust_s: For this long after a successful solve, the
                controller HOLDS the solved anchor through failed
                attempts (passing cloud) instead of hunting -- the
                exposure that solved seconds ago is a better bet than a
                search. Zero-detection streaks beyond
                ``trusted_zero_limit`` still break the hold (the sky is
                really gone); a bright frame still steps down.
            trusted_zero_limit: Consecutive zero-detection attempts the
                trust window absorbs before the recovery ladder engages.
            empirical_hold_s: How long an unsolved exposure that empirically
                beats longer exposures is held before allowing a fresh scan.
            recovery: Zero-match recovery ladder; here it triggers on
                zero *detected* stars, not zero matches.
        """
        self.target_stars = target_stars
        self.ema_alpha = ema_alpha
        self.deadband_low = deadband_low
        self.deadband_high = deadband_high
        self.min_stars_for_control = min_stars_for_control
        self.anchor_stops = anchor_stops
        self.min_exposure = min_exposure
        self.max_exposure = max_exposure
        self.bright_sky_mean = bright_sky_mean
        self.bright_clear_mean = bright_clear_mean
        self.reanchor_after = reanchor_after
        self.low_star_escape_after = low_star_escape_after
        self.anchor_trust_s = anchor_trust_s
        self.trusted_zero_limit = trusted_zero_limit
        self.empirical_hold_s = empirical_hold_s

        self._anchor = initial_anchor
        self._initial_anchor = initial_anchor
        self._ema: Optional[float] = None
        self._zero_count = 0
        self._clamp_streak = 0
        self._clamp_direction = 0
        self._bright_ceiling: Optional[int] = None
        self._low_star_streak = 0
        self._low_star_escaped = False
        self._anchor_solved_time: Optional[float] = None
        self._detection_history: dict[int, deque[int]] = {}
        self._empirical_anchor: Optional[int] = None
        self._empirical_score = 0.0
        self._detection_ceiling: Optional[int] = None
        self._detection_ceiling_time: Optional[float] = None
        self._recovery = recovery or ZeroMatchRecovery()

        logger.info(
            f"AutoExposure StarCount: target={target_stars}, "
            f"deadband=[{deadband_low}, {deadband_high}], "
            f"min_stars={min_stars_for_control}, anchor={initial_anchor}µs "
            f"(±{anchor_stops}x), range=[{min_exposure}, {max_exposure}]µs, "
            f"bright_sky_mean={bright_sky_mean}"
        )

    def reset(self) -> None:
        self._anchor = self._initial_anchor
        self._ema = None
        self._zero_count = 0
        self._clamp_streak = 0
        self._clamp_direction = 0
        self._bright_ceiling = None
        self._low_star_streak = 0
        self._low_star_escaped = False
        self._anchor_solved_time = None
        self._clear_empirical_search()
        self._recovery.reset()
        logger.debug("StarCount controller reset")

    def update(
        self,
        centroid_count: int,
        current_exposure: int,
        center_mean: Optional[float] = None,
        solve_success: bool = False,
    ) -> Optional[int]:
        """
        Update exposure from the latest solve attempt's detected-star count.

        Args:
            centroid_count: Centroids detected in the last solve attempt.
            current_exposure: Current exposure time in microseconds.
            center_mean: Mean pixel value of the frame's center ROI
                (8-bit), or None to skip the bright-sky guard.
            solve_success: Whether this solve attempt produced a plate
                solve. A solving exposure is held even when the star
                count falls short of target (ADR m0022).

        Returns:
            New exposure time in microseconds, or None if no change needed.
        """
        self._expire_empirical_search()
        self._record_detection(current_exposure, centroid_count)

        # Exception path: nothing detected at all -- exposure may be badly
        # wrong. Delegate to the recovery ladder (same ladder as the
        # match-count controller, but triggered on detections, not matches).
        # Inside the anchor trust window (a solve seconds/minutes ago) a
        # short zero streak is a passing cloud, not a wrong exposure: hold
        # the solved anchor and let the sky come back, engaging the ladder
        # only when the streak outlives ``trusted_zero_limit``.
        if centroid_count == 0:
            self._zero_count += 1
            if self._empirical_anchor is not None:
                if current_exposure != self._empirical_anchor:
                    # A longer/other exposure lost detections that a recent
                    # exposure retained. Return to the measured best instead
                    # of restarting the blind recovery ladder.
                    self._set_detection_ceiling(self._empirical_anchor)
                    return self._empirical_anchor
                if self._zero_count <= self.trusted_zero_limit:
                    # Passing cloud at the empirical best: hold briefly. If
                    # it stays empty the block below clears the stale evidence
                    # and resumes the full recovery search.
                    return None
                self._clear_empirical_search()
            if (
                self._anchor_trusted()
                and self._zero_count <= self.trusted_zero_limit
                and not self._is_bright(center_mean)
            ):
                logger.debug(
                    f"StarCount: zero detections {self._zero_count}/"
                    f"{self.trusted_zero_limit} inside anchor trust, holding"
                )
                return self._return_to_anchor(current_exposure)
            return self._recovery.handle(
                current_exposure,
                self._zero_count,
                bright=self._is_bright(center_mean),
            )

        if self._recovery.is_active():
            logger.debug(
                f"Recovery successful! Detected {centroid_count} stars at "
                f"{current_exposure}µs, resuming star-count control"
            )
            self._recovery.reset()
            # The recovery excursion must not bias the next adjustment.
            self._ema = None
            # The ladder owns the search during recovery; start the low-star
            # bookkeeping fresh on the exposure it found.
            self._low_star_streak = 0
            self._low_star_escaped = False
        self._zero_count = 0

        # A clearly dark frame retires the bright ceiling: the sky it was
        # measured against is gone (clouds moved off, dusk ended, the scope
        # swung away from a streetlight). Deliberately hysteretic -- the
        # ceiling is set above bright_sky_mean and only released well below it,
        # so a frame that merely dipped under the guard threshold cannot start
        # the climb-and-guard oscillation again (ADR m0021).
        if (
            self._bright_ceiling is not None
            and center_mean is not None
            and center_mean < self.bright_clear_mean
        ):
            logger.debug(
                f"StarCount: center mean {center_mean:.0f} < "
                f"{self.bright_clear_mean:.0f}, retiring bright ceiling "
                f"{self._bright_ceiling}µs"
            )
            self._bright_ceiling = None

        # Too few stars to trust as a control signal: probably slewing or
        # partially blocked. Hold at the anchor rather than chasing noise --
        # unless the frame is bright: a near-saturated frame with 1-3
        # "detections" (noise/hot pixels on a white field) is overexposure,
        # not blockage, and returning to a bright anchor pins the exposure on
        # a saturated sky forever (observed: all-white frames held at 500 ms).
        # Step down like the bright-sky guard instead.
        #
        # The transient hypothesis (slew, passing cloud) also expires: after
        # ``low_star_escape_after`` consecutive low-star attempts AT the
        # anchor, this is simply what the sky looks like here, and parking
        # forever finds nothing (observed: 1-3 stars through cloud held at
        # 400 ms indefinitely). Escape to the servo, which searches with the
        # low count -- safe now that raises are headroom-capped -- and stay
        # escaped until the count recovers, so the next low-star frame does
        # not snap back to the anchor and undo the search.
        if centroid_count < self.min_stars_for_control:
            if self._is_bright(center_mean):
                self._bright_ceiling = max(self.min_exposure, current_exposure // 2)
                logger.debug(
                    f"StarCount: {centroid_count} stars on a bright frame "
                    f"(mean {center_mean:.0f}), stepping down "
                    f"(ceiling {self._bright_ceiling}µs)"
                )
                return self._apply_clamps(current_exposure, current_exposure // 2)
            if self._anchor_trusted():
                # A solve moments ago: 1-3 stars through cloud is a
                # transient by definition -- hold the solved anchor, no
                # escape bookkeeping.
                self._low_star_streak = 0
                return self._return_to_anchor(current_exposure)
            if not self._low_star_escaped:
                if current_exposure != self._effective_anchor():
                    self._low_star_streak = 0
                    return self._return_to_anchor(current_exposure)
                self._low_star_streak += 1
                if self._low_star_streak < self.low_star_escape_after:
                    logger.debug(
                        f"StarCount: only {centroid_count} stars "
                        f"(<{self.min_stars_for_control}), holding at anchor "
                        f"({self._low_star_streak}/{self.low_star_escape_after})"
                    )
                    return None
                self._low_star_escaped = True
                logger.info(
                    f"StarCount: {self._low_star_streak} consecutive low-star "
                    f"attempts at the anchor -- escaping to servo control"
                )
            # escaped: fall through and let the servo act on the low count
        else:
            self._low_star_streak = 0
            self._low_star_escaped = False

        if self._ema is None:
            self._ema = float(centroid_count)
        else:
            self._ema = (
                self.ema_alpha * centroid_count + (1.0 - self.ema_alpha) * self._ema
            )
        star_fraction = self._ema / self.target_stars

        # Solving is the point of this controller, not the star count -- a
        # successful solve overrides a shortfall. Under heavy light pollution
        # the reachable count tops out below target_stars, and past the sweet
        # spot MORE exposure means FEWER detections (sky glow eats the star
        # contrast), so "short of target -> raise" walks straight out of the
        # only regime that solves. Measured in Seoul (2026-07-26, imx462):
        # 100-200 ms solved 16/18 attempts at 9-14 stars; 400 ms+ solved
        # almost never. Hold the solving exposure and learn it as the anchor.
        # Excess stars (f above the deadband) still step down: shortening a
        # solving exposure keeps the solve and reduces motion blur (ADR m0022).
        if solve_success and star_fraction <= self.deadband_high:
            self._anchor = self._clamp_absolute(current_exposure)
            self._bright_ceiling = None
            self._anchor_solved_time = time.time()
            self._clear_empirical_search()
            return None

        # Bright-sky guard: short of stars but the background is already
        # bright -- more exposure adds sky glow, not star contrast, so step
        # down instead and remember that this exposure was too long.
        #
        # Returning to the anchor here (what this did originally) produced an
        # endless loop under a light-polluted sky: guard fires at 1s -> anchor
        # 400ms -> nothing detected -> recovery climbs to 800ms -> too few
        # stars -> raise to 1s -> guard. Observed in the field; the exposure
        # that actually solves at that site is 25ms, and nothing in the cycle
        # ever walked down to it (ADR m0021).
        if star_fraction < 1.0 and self._is_bright(center_mean):
            self._bright_ceiling = max(self.min_exposure, current_exposure // 2)
            logger.debug(
                f"StarCount: bright sky (center mean {center_mean:.0f} > "
                f"{self.bright_sky_mean:.0f}) at {current_exposure}µs, "
                f"stepping down (ceiling now {self._bright_ceiling}µs)"
            )
            return self._apply_clamps(current_exposure, current_exposure // 2)

        # Deadband: close enough. Learn this exposure as the known-good
        # anchor and hold still. A working exposure also retires the bright
        # ceiling -- the sky it was measured against is gone.
        if self.deadband_low <= star_fraction <= self.deadband_high:
            self._anchor = self._clamp_absolute(current_exposure)
            self._bright_ceiling = None
            self._clear_empirical_search()
            return None

        # Inside the anchor trust window a shortfall does not justify
        # leaving the exposure that just solved -- thin cloud is eating
        # stars, not the exposure. Hold; excess stars (f above the
        # deadband) still fall through to the step-down below.
        if self._anchor_trusted() and star_fraction < 1.0:
            logger.debug(
                f"StarCount: shortfall (f={star_fraction:.2f}) inside anchor "
                f"trust, holding at anchor"
            )
            return self._return_to_anchor(current_exposure)

        # Star count ~ proportional to exposure, so one division step.
        requested = int(current_exposure / star_fraction)

        # Brightness headroom cap on raises: the pipeline is linear up to the
        # 8-bit clip, so raising exposure by R multiplies the background mean
        # by ~R. Cap the raise so the predicted mean stays at or below the
        # bright-sky threshold -- without this, a marginal sky (few stars at
        # 50-400 ms under fast-moving cloud glow) asked for 3-20x in one step,
        # landed saturated, collapsed to zero detections and cycled through
        # recovery instead of settling (observed in the field, 2026-07-26).
        if requested > current_exposure and center_mean is not None and center_mean > 0:
            headroom = self.bright_sky_mean / center_mean
            max_raise = int(current_exposure * max(1.0, headroom))
            if requested > max_raise:
                logger.debug(
                    f"StarCount: raise capped by brightness headroom "
                    f"(mean {center_mean:.0f}): {requested}µs → {max_raise}µs"
                )
                requested = max_raise

        new_exposure = self._apply_clamps(current_exposure, requested)

        if new_exposure == current_exposure:
            return None

        logger.debug(
            f"StarCount: ema {self._ema:.1f} / target {self.target_stars} "
            f"= {star_fraction:.2f} → {current_exposure}µs → {new_exposure}µs"
        )
        return new_exposure

    def _is_bright(self, center_mean: Optional[float]) -> bool:
        """Whether the frame is already sky-glow limited (None = unknown)."""
        return center_mean is not None and center_mean > self.bright_sky_mean

    def _anchor_trusted(self) -> bool:
        """Whether the anchor solved recently enough to hold through
        failed attempts instead of hunting."""
        return (
            self._anchor_solved_time is not None
            and time.time() - self._anchor_solved_time < self.anchor_trust_s
        )

    def _clamp_absolute(self, exposure: int) -> int:
        """Bound an exposure to the absolute [min_exposure, max_exposure]."""
        return max(self.min_exposure, min(self.max_exposure, exposure))

    def _apply_clamps(self, current_exposure: int, requested: int) -> int:
        """
        Bound a requested exposure by the anchor, the bright ceiling and the
        absolute range, in that order.

        The bright ceiling ratchets down while the guard keeps firing: without
        it the servo raises straight back into the exposure that just proved
        to be sky glow, which is the loop this controller used to sit in.
        """
        new_exposure = self._clamp_to_anchor(requested)
        if self._bright_ceiling is not None:
            new_exposure = min(new_exposure, self._bright_ceiling)
        if self._detection_ceiling is not None:
            new_exposure = min(new_exposure, self._detection_ceiling)
        return self._clamp_absolute(new_exposure)

    def _clamp_to_anchor(self, requested: int) -> int:
        """
        Bound an adjustment to anchor/stops..anchor*stops, following the anchor
        when the bound keeps binding.

        The bound stops a single bad frame from flinging the exposure, but the
        anchor starts as a shipped guess (400ms) and is only relearned inside
        the deadband. Where the real working exposure lies outside the bound --
        heavy light pollution puts it at 25ms, well under 400ms/8 -- the servo
        asks to go further every frame and is pinned at the boundary forever,
        so the deadband is never reached and the anchor never updates. After
        ``reanchor_after`` consecutive clamps in the same direction the ask is
        no longer noise: move the anchor to the boundary so the search
        continues from there (ADR m0021).

        The anchor itself must stay inside the absolute range: an anchor
        boundary can lie outside it (400ms * 8 = 3.2s > the 1s ceiling), and
        the low-star fallback returns the anchor verbatim -- an unclamped
        re-anchor put a 3.2s exposure on the sensor in the field.
        """
        low = self._anchor // self.anchor_stops
        high = self._anchor * self.anchor_stops
        clamped = max(low, min(high, requested))
        if clamped == requested:
            self._clamp_streak = 0
            self._clamp_direction = 0
            return clamped

        direction = -1 if requested < low else 1
        if direction == self._clamp_direction:
            self._clamp_streak += 1
        else:
            self._clamp_direction = direction
            self._clamp_streak = 1

        if self._clamp_streak >= self.reanchor_after:
            new_anchor = self._clamp_absolute(clamped)
            logger.info(
                f"StarCount: anchor {self._anchor}µs clamped {self._clamp_streak}x "
                f"toward {'shorter' if direction < 0 else 'longer'} exposures, "
                f"re-anchoring to {new_anchor}µs"
            )
            self._anchor = new_anchor
            self._clamp_streak = 0
            self._clamp_direction = 0
            low = self._anchor // self.anchor_stops
            high = self._anchor * self.anchor_stops
            clamped = max(low, min(high, requested))

        return clamped

    def _effective_anchor(self) -> int:
        """The anchor as it may actually be applied: inside the absolute
        range and under any active bright ceiling -- returning to an anchor
        the ceiling just ruled out would re-enter the glow it stepped away
        from."""
        anchor = self._clamp_absolute(
            self._empirical_anchor
            if self._empirical_anchor is not None
            else self._anchor
        )
        if self._bright_ceiling is not None:
            anchor = min(anchor, self._bright_ceiling)
        if self._detection_ceiling is not None:
            anchor = min(anchor, self._detection_ceiling)
        return anchor

    def _record_detection(self, exposure: int, count: int) -> None:
        """Track robust recent detection yield for each attempted exposure."""
        exposure = self._clamp_absolute(exposure)
        history = self._detection_history.setdefault(exposure, deque(maxlen=8))
        history.append(max(0, int(count)))

        candidates = []
        for tried_exposure, samples in self._detection_history.items():
            if len(samples) < 2:
                continue
            score = float(median(samples))
            if score > 0:
                candidates.append((score, tried_exposure))
        if not candidates:
            return

        # Highest robust count wins; for equal counts prefer the shorter
        # exposure because it reduces motion blur and control latency.
        best_score = max(score for score, _ in candidates)
        best_exposure = min(
            tried_exposure
            for score, tried_exposure in candidates
            if score == best_score
        )
        self._empirical_anchor = best_exposure
        self._empirical_score = best_score

        current_score = float(median(history))
        if (
            exposure > best_exposure
            and len(history) >= 2
            and current_score + 1.0 <= best_score
        ):
            self._set_detection_ceiling(best_exposure)

    def _set_detection_ceiling(self, exposure: int) -> None:
        ceiling = self._clamp_absolute(exposure)
        if self._detection_ceiling is None or ceiling < self._detection_ceiling:
            self._detection_ceiling = ceiling
        self._detection_ceiling_time = time.time()

    def _expire_empirical_search(self) -> None:
        if (
            self._detection_ceiling_time is not None
            and time.time() - self._detection_ceiling_time >= self.empirical_hold_s
        ):
            self._clear_empirical_search()

    def _clear_empirical_search(self) -> None:
        self._detection_history = {}
        self._empirical_anchor = None
        self._empirical_score = 0.0
        self._detection_ceiling = None
        self._detection_ceiling_time = None

    def _return_to_anchor(self, current_exposure: int) -> Optional[int]:
        # Clamp on the way out too: this value goes straight to the sensor,
        # so no anchor state -- however it was arrived at -- may put an
        # exposure outside the absolute range on the camera.
        anchor = self._effective_anchor()
        if current_exposure != anchor:
            return anchor
        return None

    def get_status(self) -> dict:
        return {
            "target_stars": self.target_stars,
            "ema": self._ema,
            "anchor": self._anchor,
            "zero_count": self._zero_count,
            "clamp_streak": self._clamp_streak,
            "bright_ceiling": self._bright_ceiling,
            "low_star_streak": self._low_star_streak,
            "low_star_escaped": self._low_star_escaped,
            "anchor_trusted": self._anchor_trusted(),
            "empirical_anchor": self._empirical_anchor,
            "empirical_score": self._empirical_score,
            "detection_ceiling": self._detection_ceiling,
            "recovery_active": self._recovery.is_active(),
            "deadband": (self.deadband_low, self.deadband_high),
            "min_exposure": self.min_exposure,
            "max_exposure": self.max_exposure,
        }
