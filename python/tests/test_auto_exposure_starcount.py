#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Unit tests for auto_exposure_starcount.py - the star-count controller.

The star-count controller is the opt-in alternative to the match-count
controller (camera_exp = "auto_star"): feedback comes from
detected centroids instead of catalog matches, with a bright-sky guard,
a slewing fallback, and an anchor learned in the deadband.
See docs/mf_dev/camera_ko.md.
"""

import pytest

from PiFinder.auto_exposure import RECOVERY_LADDER, ZeroMatchRecovery
from PiFinder.auto_exposure_starcount import (
    ExposureStarCountController,
    full_frame_star_count,
)
from PiFinder.types.positioning import SolveDiagnostics


@pytest.mark.unit
def test_full_frame_star_count_prefers_gated_peripheral_detections():
    assert full_frame_star_count(0, 5) == 5


@pytest.mark.unit
def test_full_frame_star_count_never_loses_crop_or_uses_missing_full_frame():
    assert full_frame_star_count(3, 2) == 3
    assert full_frame_star_count(3, None) == 3


@pytest.mark.unit
def test_full_frame_star_count_uses_conservative_detector_consensus():
    assert full_frame_star_count(0, 2, cedar_raw_count=11, sep_count=8) == 8
    assert full_frame_star_count(0, 2, cedar_raw_count=11, sep_count=0) == 2
    assert full_frame_star_count(0, 2, cedar_raw_count=None, sep_count=8) == 2


@pytest.mark.unit
class TestCentroidsDiagnostics:
    """The Centroids field the controller consumes."""

    def test_centroids_defaults_to_zero(self):
        """Centroids defaults to 0 like Matches (auto-exposure expects int)."""
        diagnostics = SolveDiagnostics()
        assert diagnostics.Centroids == 0
        assert diagnostics.Matches == 0

    def test_centroids_carries_count(self):
        diagnostics = SolveDiagnostics(Matches=0, Centroids=23)
        assert diagnostics.Centroids == 23


@pytest.mark.unit
class TestExposureStarCountController:
    """Tests for the star-count controller's control law."""

    def test_initialization_defaults(self):
        """Defaults follow cedar-server's field-proven servo values."""
        controller = ExposureStarCountController()
        assert controller.target_stars == 20
        assert controller.ema_alpha == 0.5
        assert controller.deadband_low == 0.8
        assert controller.deadband_high == 1.6
        assert controller.min_stars_for_control == 4
        assert controller.min_exposure == 25000
        assert controller.max_exposure == 1000000
        assert controller._anchor == 400000

    def test_deadband_holds_and_learns_anchor(self):
        """Inside the deadband: no adjustment, exposure becomes the anchor."""
        controller = ExposureStarCountController()
        # 20/20 = 1.0 -> inside [0.8, 1.6]
        assert controller.update(20, 300000) is None
        assert controller._anchor == 300000

    def test_deadband_is_asymmetric(self):
        """Excess stars are tolerated up to 1.6x; shortfall acts below 0.8x."""
        controller = ExposureStarCountController()
        # 30/20 = 1.5 -> still inside deadband (tolerated excess)
        assert controller.update(30, 400000) is None
        # Fresh controller: 15/20 = 0.75 -> below 0.8, acts
        controller = ExposureStarCountController()
        assert controller.update(15, 400000) is not None

    def test_increases_exposure_for_too_few_stars(self):
        """Division law: new = current / (ema/target)."""
        controller = ExposureStarCountController()
        # First update seeds EMA with the raw count: 10/20 = 0.5
        new_exposure = controller.update(10, 400000)
        assert new_exposure == int(400000 / 0.5)

    def test_decreases_exposure_for_too_many_stars(self):
        controller = ExposureStarCountController()
        # 80/20 = 4.0 -> divide exposure by 4
        new_exposure = controller.update(80, 400000)
        assert new_exposure == int(400000 / 4.0)

    def test_ema_smooths_counts(self):
        """Second update blends: ema = 0.5*count + 0.5*prev_ema."""
        controller = ExposureStarCountController()
        controller.update(20, 400000)  # seeds ema=20, in deadband
        new_exposure = controller.update(4, 400000)
        # ema = 0.5*4 + 0.5*20 = 12 -> f = 0.6 -> 400000/0.6
        assert new_exposure == int(400000 / 0.6)

    def test_anchor_stop_clamp(self):
        """Adjustments are clamped to anchor/8 .. anchor*8."""
        controller = ExposureStarCountController(
            initial_anchor=50000, max_exposure=10000000
        )
        # 4 == min_stars_for_control, so the servo (not the fallback) runs:
        # ema seeds at 4 -> f = 0.2 -> 50000/0.2 = 250000 < 50000*8, unclamped
        assert controller.update(4, 50000) == 250000
        # Now force a huge shortfall repeatedly to hit the anchor clamp:
        controller = ExposureStarCountController(
            initial_anchor=50000, max_exposure=10000000, min_stars_for_control=1
        )
        # f = 1/20 = 0.05 -> raw 50000/0.05 = 1000000 > anchor*8 = 400000
        assert controller.update(1, 50000) == 400000

    def test_reanchors_when_the_clamp_keeps_binding(self):
        """A working exposure outside the anchor bound must stay reachable.

        Under heavy light pollution the servo asks for a shorter exposure than
        anchor/8 on every frame. Pinning it at the boundary forever means the
        deadband is never reached, so the anchor never updates and the
        controller is stuck (ADR m0021).
        """
        controller = ExposureStarCountController(reanchor_after=3)
        # 160/20 = 8 -> raw 30000/8 = 3750, floored by anchor/8 = 50000.
        assert controller.update(160, 30000) == 50000
        assert controller._clamp_streak == 1
        # Pinned at the boundary: the ask is still 6250, the clamp still 50000,
        # so the controller reports "no change" -- this is the stuck state.
        assert controller.update(160, 50000) is None
        assert controller._clamp_streak == 2
        # Third consecutive clamp in the same direction: the anchor follows the
        # boundary, so the servo can carry on down.
        assert controller.update(160, 50000) == 25000
        assert controller._anchor == 50000

    def test_solve_success_holds_below_target(self):
        """A solving exposure is held even short of target_stars.

        Seoul field data (2026-07-26): the only exposures that solve at all
        yield 9-14 detections -- under target 20 -- and raising exposure from
        there loses stars to sky glow. Without this hold the shortfall walks
        the servo out of the solving regime every time (ADR m0022).
        """
        controller = ExposureStarCountController()
        # 12/20 = 0.6 < deadband_low: would normally raise, but it solved.
        assert controller.update(12, 200000, solve_success=True) is None
        assert controller._anchor == 200000
        # Same reading without a solve raises as before.
        controller = ExposureStarCountController()
        assert controller.update(12, 200000) == 333333

    def test_solve_success_learns_clamped_anchor(self):
        controller = ExposureStarCountController()
        controller._bright_ceiling = 100000
        assert controller.update(12, 200000, solve_success=True) is None
        assert controller._bright_ceiling is None

    def test_solve_success_with_excess_stars_still_steps_down(self):
        """Above the deadband a solving exposure is still shortened: the
        solve survives and motion blur shrinks."""
        controller = ExposureStarCountController(ema_alpha=1.0)
        # 160/20 = 8 > deadband_high -> step down even though it solved.
        assert controller.update(160, 400000, solve_success=True) == 50000

    def test_anchor_trust_holds_through_passing_cloud(self):
        """After a solve, failed attempts hold the solved exposure instead
        of hunting (field feedback: exposure jitter under moving cloud)."""
        controller = ExposureStarCountController()
        assert controller.update(12, 200000, solve_success=True) is None
        # zero detections (cloud): held at anchor, ladder does NOT engage
        for _ in range(controller.trusted_zero_limit):
            assert controller.update(0, 200000, center_mean=100.0) is None
        assert controller.get_status()["recovery_active"] is False
        # 1-3 stars: held, no escape
        assert controller.update(2, 200000, center_mean=100.0) is None
        # shortfall (>=4 stars but under target): held, no raise
        assert controller.update(6, 200000, center_mean=100.0) is None
        # off-anchor exposure snaps back to the solved anchor
        assert controller.update(2, 400000, center_mean=100.0) == 200000

    def test_anchor_trust_zero_streak_limit_engages_ladder(self):
        controller = ExposureStarCountController()
        controller.update(12, 200000, solve_success=True)
        for _ in range(controller.trusted_zero_limit):
            controller.update(0, 200000, center_mean=100.0)
        # streak beyond the limit: recovery takes over
        result = controller.update(0, 200000, center_mean=100.0)
        assert result is not None
        assert controller.get_status()["recovery_active"] is True

    def test_anchor_trust_expires(self):
        controller = ExposureStarCountController(anchor_trust_s=90.0)
        controller.update(12, 200000, solve_success=True)
        controller._anchor_solved_time -= 1000  # age the trust out
        # shortfall now adjusts again (headroom-capped raise)
        assert controller.update(6, 200000, center_mean=60.0) is not None

    def test_anchor_trust_still_steps_down_when_bright(self):
        """Trust never overrides the saturation defence."""
        controller = ExposureStarCountController()
        controller.update(12, 400000, solve_success=True)
        assert controller.update(2, 400000, center_mean=250.0) == 200000

    def test_reanchor_cannot_raise_anchor_past_absolute_max(self):
        """The anchor must never leave [min_exposure, max_exposure].

        Field failure (2026-07-26): a dark sky with a handful of detections
        asked for more than anchor*8 on every solve; after three clamps the
        anchor followed the bound to 400ms*8 = 3.2s, above the 1s absolute
        ceiling. The next <4-star frame then returned that anchor verbatim
        and the sensor ran a 3.2s exposure.
        """
        controller = ExposureStarCountController()
        exposure = 1000000  # pinned at the absolute ceiling, dark scene
        for _ in range(6):
            # 6 detections -> f ~ 0.3 -> asks for ~3.3s, above anchor*8
            new_exposure = controller.update(6, exposure, center_mean=10.0)
            if new_exposure is not None:
                exposure = new_exposure
        assert controller._anchor == 1000000
        # The low-star fallback holds at the (in-range) anchor.
        assert controller.update(2, exposure, center_mean=10.0) is None

    def test_reanchor_cannot_lower_anchor_past_absolute_min(self):
        """Walking the anchor down stops at min_exposure, not anchor/8 of it."""
        controller = ExposureStarCountController(ema_alpha=1.0)
        exposure = 30000
        for _ in range(10):
            # A sky drowning in detections: f = 8, asks below anchor/8
            new_exposure = controller.update(160, exposure, center_mean=10.0)
            if new_exposure is not None:
                exposure = new_exposure
        assert controller._anchor >= controller.min_exposure

    def test_low_star_fallback_clamps_an_out_of_range_anchor(self):
        """Defence in depth: the fallback output is clamped on the way out."""
        controller = ExposureStarCountController()
        controller._anchor = 3200000  # outside the absolute range
        assert controller.update(2, 400000) == 1000000

    def test_clamp_streak_resets_on_an_unclamped_step(self):
        """Only a sustained ask moves the anchor -- one odd frame does not."""
        controller = ExposureStarCountController(reanchor_after=3)
        controller.update(160, 30000)  # clamped low
        assert controller._clamp_streak == 1
        controller.update(20, 400000)  # inside deadband, no clamp
        assert controller._clamp_streak == 0
        assert controller._anchor == 400000

    def test_clamp_streak_resets_when_direction_flips(self):
        # ema_alpha=1.0 keeps each step readable (no smoothing across counts);
        # min_stars_for_control=1 lets a single star drive the servo instead of
        # falling back to the anchor.
        controller = ExposureStarCountController(
            reanchor_after=3,
            min_stars_for_control=1,
            ema_alpha=1.0,
            max_exposure=10000000,
        )
        controller.update(160, 30000)  # f=8 -> raw 3750 -> clamped low
        assert controller._clamp_direction == -1
        controller.update(1, 400000)  # f=0.05 -> raw 8000000 -> clamped high
        assert controller._clamp_direction == 1
        assert controller._clamp_streak == 1

    def test_absolute_clamps(self):
        """Absolute [min_exposure, max_exposure] clamp binds last."""
        controller = ExposureStarCountController()
        # Shortfall from 400000: raw = 400000/0.25=1600000 -> max 1000000
        new_exposure = controller.update(5, 400000)
        assert new_exposure == 1000000
        # Excess from 30000: raw = 30000/8=3750: anchor clamp floors at
        # 400000//8=50000 first, then min_exposure=25000 does not bind.
        controller = ExposureStarCountController()
        new_exposure = controller.update(160, 30000)
        assert new_exposure == 50000

    def test_few_stars_returns_to_anchor(self):
        """<4 stars = slewing/blocked: return to anchor, no servo step."""
        controller = ExposureStarCountController()
        controller.update(20, 300000)  # learn anchor 300000
        assert controller.update(2, 100000) == 300000
        # Already at anchor -> no change
        assert controller.update(2, 300000) is None

    def test_persistent_low_stars_escape_to_servo(self):
        """The slew/blockage hypothesis expires: a sky that only ever shows
        1-3 stars at the anchor must be searched, not parked on (field
        failure: 1-3 stars through cloud held at 400 ms indefinitely)."""
        controller = ExposureStarCountController(ema_alpha=1.0)
        # At the anchor, low counts hold for low_star_escape_after attempts.
        for _ in range(3):
            assert controller.update(3, 400000, center_mean=100.0) is None
        # 4th consecutive: escape -- servo raises, capped by headroom
        # (240/100 = 2.4x -> 960000).
        assert controller.update(3, 400000, center_mean=100.0) == 960000
        # Still escaped: the next low-star frame keeps servo control instead
        # of snapping back to the anchor.
        result = controller.update(3, 960000, center_mean=120.0)
        assert result != 400000
        # A healthy count clears the escape...
        controller.update(20, 200000, center_mean=50.0)
        assert controller.get_status()["low_star_escaped"] is False
        # ...so a later low-star frame returns to the (new) anchor again.
        assert controller.update(2, 100000, center_mean=50.0) == 200000

    def test_return_to_anchor_respects_bright_ceiling(self):
        """Returning to an anchor above an active bright ceiling would
        re-enter the glow the guard just stepped away from."""
        controller = ExposureStarCountController()
        controller.update(20, 400000)  # anchor 400000
        controller._bright_ceiling = 200000
        # mean 150: inside the hysteresis band (not bright, not clear), so
        # the ceiling stays active and caps the anchor return.
        assert controller.update(2, 100000, center_mean=150.0) == 200000

    def test_raise_capped_by_brightness_headroom(self):
        """A raise may not push the predicted background past the bright
        threshold. Field failure: 50 ms with a few stars asked for 20x in
        one step, landed saturated, and cycled instead of settling."""
        controller = ExposureStarCountController(ema_alpha=1.0)
        # 5/20 = 0.25 -> raw ask 200000. Mean 60 allows 240/60 = 4x = 200000:
        # exactly at the cap, so the ask goes through.
        assert controller.update(5, 50000, center_mean=60.0) == 200000
        # Mean 150 allows only 240/150 = 1.6x from 400000 -> 640000,
        # far below the raw ask of 1600000.
        controller = ExposureStarCountController(ema_alpha=1.0)
        assert controller.update(5, 400000, center_mean=150.0) == 640000
        # Without a mean the cap cannot apply (raw ask, absolute-clamped).
        controller = ExposureStarCountController(ema_alpha=1.0)
        assert controller.update(5, 400000) == 1000000
        # Downward steps are never capped.
        controller = ExposureStarCountController(ema_alpha=1.0)
        assert controller.update(160, 400000, center_mean=200.0) == 50000

    def test_few_stars_on_bright_frame_steps_down(self):
        """1-3 'detections' on a near-saturated frame are noise on a white
        field, not blockage: step down instead of pinning at a bright anchor
        (field failure: all-white sky held at 500 ms forever)."""
        controller = ExposureStarCountController()
        controller.update(20, 500000)  # learn anchor 500000
        assert controller.update(2, 500000, center_mean=250.0) == 250000
        assert controller._bright_ceiling == 250000
        # Dark low-star frames still return to the anchor.
        controller = ExposureStarCountController()
        controller.update(20, 300000)
        assert controller.update(2, 100000, center_mean=30.0) == 300000

    def test_bright_sky_guard_steps_down(self):
        """Short of stars + bright center ROI: halve, don't raise.

        Returning to the anchor here used to loop forever in the field: guard
        at 1s -> anchor 400ms -> nothing detected -> recovery climbs -> too few
        stars -> raise to 1s -> guard (ADR m0021).
        """
        controller = ExposureStarCountController()
        controller.update(20, 300000)  # anchor = 300000
        result = controller.update(10, 500000, center_mean=250.0)
        assert result == 250000  # one stop down, not the anchor or 500000/f
        assert controller._bright_ceiling == 250000

    def test_bright_ceiling_caps_later_raises(self):
        """Once a frame proved to be sky glow, don't climb back into it."""
        controller = ExposureStarCountController()
        controller.update(10, 800000, center_mean=250.0)  # ceiling 400000
        assert controller._bright_ceiling == 400000
        # A frame that merely dipped under the guard threshold is still short
        # of stars and would otherwise raise straight back into the glow.
        assert controller.update(5, 400000, center_mean=200.0) is None

    def test_clearly_dark_frame_retires_the_ceiling(self):
        """When the sky really does darken, the cap must not starve the servo."""
        controller = ExposureStarCountController()
        controller.update(10, 800000, center_mean=250.0)  # ceiling 400000
        # Well below bright_clear_mean: the bright sky is gone.
        assert controller.update(5, 400000, center_mean=20.0) is not None
        assert controller._bright_ceiling is None

    def test_deadband_retires_the_bright_ceiling(self):
        """A working exposure means the sky it was measured against is gone."""
        controller = ExposureStarCountController()
        controller.update(10, 800000, center_mean=250.0)
        assert controller._bright_ceiling is not None
        # ema = 0.5*30 + 0.5*10 = 20 -> exactly on target, inside the deadband
        controller.update(30, 200000)
        assert controller._bright_ceiling is None

    def test_bright_sky_walks_down_to_the_floor(self):
        """Repeated guard hits reach the fast end instead of oscillating."""
        controller = ExposureStarCountController()
        exposure = 1000000
        for _ in range(12):
            new_exposure = controller.update(10, exposure, center_mean=250.0)
            if new_exposure is None:
                break
            exposure = new_exposure
        assert exposure == controller.min_exposure

    def test_bright_sky_guard_ignored_when_dark(self):
        controller = ExposureStarCountController()
        new_exposure = controller.update(10, 400000, center_mean=20.0)
        assert new_exposure == int(400000 / 0.5)

    def test_bright_sky_guard_skipped_without_mean(self):
        """center_mean=None (no image available) skips the guard."""
        controller = ExposureStarCountController()
        assert controller.update(10, 400000, center_mean=None) == 800000

    def test_zero_detection_delegates_to_recovery(self):
        """0 detected -> recovery ladder after the trigger count."""
        controller = ExposureStarCountController()
        # First zero: below trigger count, no action
        assert controller.update(0, 400000) is None
        # Second zero: recovery activates, first rung
        assert controller.update(0, 400000) == RECOVERY_LADDER[0]
        assert controller._recovery.is_active()

    def test_detection_exits_recovery_and_resets_ema(self):
        """First nonzero detection ends recovery; EMA restarts clean."""
        controller = ExposureStarCountController()
        controller.update(20, 400000)  # seed ema
        controller.update(0, 400000)
        controller.update(0, 400000)  # recovery active
        assert controller._recovery.is_active()
        # Detection returns; 10/20=0.5 must use fresh EMA (10), not blend
        new_exposure = controller.update(10, 400000)
        assert not controller._recovery.is_active()
        assert controller._zero_count == 0
        assert new_exposure == int(400000 / 0.5)

    def test_low_but_nonzero_does_not_trigger_recovery(self):
        """1-3 detected stars is a fallback case, never the ladder."""
        controller = ExposureStarCountController()
        for _ in range(5):
            controller.update(1, 400000)
        assert not controller._recovery.is_active()

    def test_empirical_best_blocks_a_longer_exposure_that_loses_stars(self):
        controller = ExposureStarCountController(
            target_stars=10, low_star_escape_after=2
        )
        controller.update(3, 200000)
        controller.update(3, 200000)  # two samples establish robust best

        assert controller.update(0, 400000) == 200000
        status = controller.get_status()
        assert status["empirical_anchor"] == 200000
        assert status["empirical_score"] == 3.0
        assert status["detection_ceiling"] == 200000

        # Once back at the measured best, the low-count servo cannot fling
        # the exposure into the longer regime that already lost detections.
        for _ in range(4):
            assert controller.update(3, 200000) is None

    def test_empirical_best_eventually_reopens_search_when_it_turns_empty(self):
        controller = ExposureStarCountController(target_stars=10)
        controller.update(3, 200000)
        controller.update(3, 200000)

        for _ in range(controller.trusted_zero_limit):
            assert controller.update(0, 200000) is None
        assert controller.update(0, 200000) == RECOVERY_LADDER[0]
        assert controller.get_status()["empirical_anchor"] is None

    def test_deadband_replaces_empirical_search_with_working_anchor(self):
        controller = ExposureStarCountController(target_stars=10)
        controller.update(3, 200000)
        controller.update(3, 200000)

        assert controller.update(10, 200000) is None
        status = controller.get_status()
        assert status["anchor"] == 200000
        assert status["empirical_anchor"] is None
        assert status["detection_ceiling"] is None

    def test_custom_recovery_injected(self):
        recovery = ZeroMatchRecovery(trigger_count=1)
        controller = ExposureStarCountController(recovery=recovery)
        assert controller.update(0, 400000) == RECOVERY_LADDER[0]

    def test_reset_clears_state(self):
        controller = ExposureStarCountController()
        controller.update(20, 300000)  # anchor learned
        controller.update(0, 300000)
        controller.reset()
        assert controller._anchor == 400000
        assert controller._ema is None
        assert controller._zero_count == 0
        assert not controller._recovery.is_active()

    def test_excess_above_deadband_decreases(self):
        """f just above deadband_high still steps down by division."""
        controller = ExposureStarCountController()
        # 35/20 = 1.75 > 1.6 -> new = int(400000/1.75)
        assert controller.update(35, 400000) == int(400000 / 1.75)

    def test_get_status(self):
        controller = ExposureStarCountController()
        controller.update(20, 300000)
        status = controller.get_status()
        assert status["target_stars"] == 20
        assert status["ema"] == 20.0
        assert status["anchor"] == 300000
        assert status["zero_count"] == 0
        assert status["recovery_active"] is False
        assert status["deadband"] == (0.8, 1.6)
