"""Video correction with jitter, partial response and insufficient capacity."""

from dataclasses import asdict, replace

import numpy as np
import pytest

from PiFinder.tracking_contracts import CaptureTiming, CorrectionReceipt
from PiFinder.tracking_control import TrackingController
from PiFinder.tracking_motion import MotionHistory
from PiFinder.tracking_quality import StarTracker, extract_rois, native_points
from PiFinder.visual_tracking import plate_basis
from test_smooth_tracking import context, measurement, profile, snapshot
from test_smooth_tracking_runtime import reference_scene

pytestmark = pytest.mark.unit


def test_small_pulses_reduce_large_error_despite_absolute_reference_uncertainty():
    controller = TrackingController(
        profile(max_error_bound_arcsec=200, reference_bound_arcsec=100)
    )
    controller.arm(context())
    error = np.array([600.0, 0.0])
    sent = 0
    for seq in range(20):
        now = 100 + seq
        m = measurement(seq, now, error=tuple(error), bound_arcsec=100)
        plan = controller.tick(snapshot(m, now), now, 2)
        if plan:
            assert np.linalg.norm(plan.expected_delta) < m.bound_arcsec
            assert controller.validate_dispatch(plan, snapshot(m, now), now, 2)
            error -= plan.expected_delta
            controller.acknowledge(
                plan, CorrectionReceipt(plan.command_id, "accepted", now, now + 0.26)
            )
            sent += 1
    assert sent >= 5
    assert error[0] < 575
    # The same pulse must still be withheld near an uncertain target.
    assert not controller._beneficial((100, 0), (5, 0), 100)


@pytest.mark.parametrize("interval", [0.05, 0.25, 0.5])
def test_jitter_filter_retains_time_span_and_recovers_persistent_drift(interval):
    history = MotionHistory(robust=True)
    rng = np.random.default_rng(18)
    drift = np.array([-9.5, 1.0])
    for t in np.arange(0, 10, interval):
        mode, estimate = history.observe(
            t,
            drift * t + rng.normal(0, 1, 2),
            (0, 0),
            10,
            20,
            relative_bound=2,
        )
    assert mode == "persistent_drift"
    assert estimate == pytest.approx(drift, abs=0.8)
    assert history.filtered_error == pytest.approx(drift * t, abs=2)
    assert history.samples[-1][0] - history.samples[0][0] >= 2
    history.reset()
    for i in range(24):
        mode, estimate = history.observe(
            i * 0.25,
            (np.sin(i) * 2, np.cos(i) * 2),
            (0, 0),
            10,
            20,
            relative_bound=2,
        )
    assert mode == "jitter_filtered"
    assert estimate is None


def test_partial_model_corrects_only_observed_axis_and_directions():
    p = profile(
        response=((0, 0, 0, 0), (0.02, -0.022, 0, 0)),
        response_axes=(1,),
        response_directions=("north", "south"),
        robust_tracking=True,
    )
    controller = TrackingController(p)
    controller.arm(context())
    plans = []
    for seq in range(12):
        now = 100 + seq
        m = measurement(seq, now, error=(1000, -30))
        plan = controller.tick(snapshot(m, now), now, 2)
        if plan:
            plans.append(plan)
            controller.acknowledge(
                plan, CorrectionReceipt(plan.command_id, "accepted", now, now + 0.26)
            )
    assert plans
    assert all(p.direction == "south" and p.expected_delta[0] == 0 for p in plans)
    with pytest.raises(ValueError, match="unobservable"):
        replace(p, response_axes=(0, 1))
    with pytest.raises(ValueError, match="cannot coast"):
        replace(p, coast_verified=True)


@pytest.mark.parametrize(
    "budget",
    [
        {"best_effort_s": 12},
        {
            "best_effort_s": 60,
            "best_effort_travel_arcsec": 25,
        },
    ],
)
def test_capacity_limited_correction_reduces_drift_with_finite_budget(budget):
    p = profile(max_drift_arcsec_s=20, **budget)
    controller = TrackingController(p)
    controller.arm(context())
    error = np.array([100.0, 0.0])
    plans = []
    states = []
    for seq in range(40):
        now = 100 + seq
        m = measurement(seq, now, error=tuple(error))
        plan = controller.tick(snapshot(m, now), now, 2)
        states.append(controller.state)
        if plan:
            assert controller.validate_dispatch(plan, snapshot(m, now), now, 2)
            plans.append((now, plan))
            error -= np.asarray(plan.expected_delta) * (1 + p.response_fractional_bound)
            controller.acknowledge(
                plan, CorrectionReceipt(plan.command_id, "accepted", now, now + 0.26)
            )
        error += (8, 0)
    assert len(plans) >= 3
    assert controller.state == "LIMITED"
    assert controller.reason == "best_effort_budget_exhausted"
    assert "CAPACITY_LIMITED_TRACKING" in states
    assert error[0] < 100 + 40 * 8
    assert 100 + 40 * 8 - error[0] <= p.best_effort_travel_arcsec
    assert controller.command_travel <= p.best_effort_travel_arcsec
    assert all(
        now + p.start_delay_bound_s + plan.duration_ms / 1000
        < controller.best_effort_started + p.best_effort_s
        for now, plan in plans[1:]
    )


def test_opposite_video_response_backs_off_and_cannot_be_learned_across_hold():
    p = profile(
        robust_tracking=True,
        max_drift_arcsec_s=20,
        max_pulse_ms=1000,
        min_pulse_ms=500,
        max_duty=0.5,
        stop_bound_s=2,
        ramp_s=3,
    )
    controller = TrackingController(p)
    controller.arm(context())
    accepted = None
    for seq in range(16):
        now = 100 + seq * 0.5
        m = measurement(seq, now, error=(100 + seq * 0.5, 0), relative_bound_arcsec=0.1)
        plan = controller.tick(snapshot(m, now), now, 2)
        if plan and controller.drift is not None:
            accepted = (now, m, plan)
            controller.acknowledge(
                plan, CorrectionReceipt(plan.command_id, "accepted", now, now + 1.01)
            )
            break
        if plan:
            controller.acknowledge(
                plan, CorrectionReceipt(plan.command_id, "rejected", now)
            )
    assert accepted is not None
    now, before, plan = accepted
    after = measurement(
        before.sequence + 1,
        now + 2,
        error=(before.error[0] + 22, 0),
        relative_bound_arcsec=0.1,
    )
    controller.tick(snapshot(after, now + 2), now + 2, 2)
    assert controller.feedback_gain == 0.5
    assert controller.direction_cooldowns[plan.direction] > now + 2
    controller.feedback_pending = (plan, before, np.array([1, 0]), 0.1)
    controller.hold("stars_lost")
    assert controller.feedback_pending is None


def test_local_video_anchor_reduces_catalog_residual_without_erasing_absolute_bound():
    ref, request, p = reference_scene()
    # Profiles created without an estimator option must use the field-tested
    # anchors too; this exercises the same default used by saved profiles.
    p = type(p).from_dict(
        {k: v for k, v in p.to_dict().items() if k != "robust_tracking"}
    )
    tracker = StarTracker(ref, request, p)
    geo = tracker.geometry
    native = native_points(
        geo.project(ref["world"], plate_basis(40, 20, 12)),
        ref["raw_shape"],
        (geo.height, geo.width),
        ref["info"],
    )
    native += np.array([(0.2 * np.sin(i), 0.3 * np.cos(i)) for i in range(len(native))])
    yy, xx = np.indices(ref["raw_shape"])
    raw = np.full(ref["raw_shape"], 50.0)
    for y, x in native:
        raw += 1000 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * 1.3**2))
    measurements = []
    for seq in range(2, 5):
        now = 100 + seq * 0.5
        roi = tracker.roi_request()
        measurements.append(
            tracker.measure(
                dict(
                    reference=ref["id"],
                    patches=extract_rois(raw, roi["centers"], 12),
                    metadata=dict(
                        capture_epoch="capture",
                        capture_sequence=seq,
                        actual_exposure_us=100000,
                        actual_gain=10,
                        tracking_timing=asdict(
                            CaptureTiming(
                                now - 0.2,
                                now - 0.05,
                                now - 0.1,
                                0.001,
                                now + 1000,
                                True,
                                "clock",
                            )
                        ),
                    ),
                ),
                now,
            )
        )
    first, last = measurements[0], measurements[-1]
    assert first.valid and last.valid
    assert last.rmse_px < first.rmse_px / 2
    assert last.bound_arcsec >= first.bound_arcsec
    assert last.relative_bound_arcsec < first.relative_bound_arcsec
    assert last.error == pytest.approx(first.error, abs=0.1)
    # Rejected catalog entries do not repeatedly reduce confidence in the
    # retained, spatially distributed video anchors.
    tracker.reference["world"] = list(ref["world"]) * 4
    now = 103
    roi = tracker.roi_request()
    result = tracker.measure(
        dict(
            reference=ref["id"],
            patches=extract_rois(raw, roi["centers"], 12),
            metadata=dict(
                capture_epoch="capture",
                capture_sequence=5,
                actual_exposure_us=100000,
                actual_gain=10,
                tracking_timing=asdict(
                    CaptureTiming(
                        now - 0.2,
                        now - 0.05,
                        now - 0.1,
                        0.001,
                        now + 1000,
                        True,
                        "clock",
                    )
                ),
            ),
        ),
        now,
    )
    assert result.quality == "valid"
