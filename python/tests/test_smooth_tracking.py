"""Indoor contract and closed-loop tests. No camera, GPIO or INDI connection."""

import numpy as np
import pytest

from PiFinder.tracking_capture import capture_timing
from PiFinder.tracking_commands import PriorityMountQueue
from PiFinder.tracking_contracts import (
    CaptureTiming,
    CorrectionReceipt,
    TrackingContext,
    TrackingMeasurement,
    TrackingPermission,
    TrackingProfile,
)
from PiFinder.tracking_control import RecoveryBudget, TrackingController
from PiFinder.tracking_mailbox import TrackingMailbox
from PiFinder.tracking_quality import (
    centroid,
    extract_rois,
    spatial_quality,
    tangent_error,
)

pytestmark = pytest.mark.unit


def profile(**changes):
    values = dict(
        verified=True,
        profile_id="sim",
        device="sim",
        driver="sim:1",
        camera="sim",
        geometry="geometry",
        response=((0, 0, 0.02, -0.018), (0.02, -0.022, 0, 0)),
        model_target=(40.0, 20.0),
        max_age_s=3,
        deadband_arcsec=1,
        max_error_bound_arcsec=5,
        reference_bound_arcsec=0.1,
        ramp_s=0.5,
        start_delay_bound_s=0.01,
        settle_s=0.01,
        prediction_horizon_s=2,
        timing={
            "verified": True,
            "camera": "sim",
            "backend": "sim",
            "clock": "boottime",
            "timestamp_semantics": "first_row_readout",
            "uncertainty_s": 0.001,
            "rolling_skew_bound_s": 0,
        },
    )
    return TrackingProfile(**(values | changes))


def context():
    return TrackingContext("session", "geometry", "capture", 1, 2, "ref", (40.0, 20.0))


def measurement(seq, now, error=(30.0, 0.0), **changes):
    return TrackingMeasurement(
        **(
            dict(
                context=context(),
                sequence=seq,
                timing=CaptureTiming(
                    now - 0.1, now - 0.01, now - 0.05, 0.001, now + 1000, True, "clock"
                ),
                error=error,
                bound_arcsec=0.1,
                quality="valid",
                reason="test",
                stars=8,
                camera_radec_roll=(40, 20, 0),
                aligned_radec=(40, 20),
            )
            | changes
        )
    )


def snapshot(m, now, **changes):
    return (
        dict(
            measurement=m,
            permission=TrackingPermission(m.context, now + 2, 0),
            quality_revision=m.sequence,
            invalid_revision=0,
            fault="",
        )
        | changes
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"response": ((1, -1, 0, 0), (0, 0, 0, 0))},
        {"max_pulse_ms": 0},
        {"max_duty": float("nan")},
        {"min_stars": 3},
        {"max_age_s": -1},
        {"stop_bound_s": 0.01},
        {"timing": {}},
        {"mount_type": "EQ", "pier_side": ""},
        {"geometry": ""},
    ],
)
def test_profile_rejects_unverified_contract(changes):
    with pytest.raises(ValueError):
        profile(**changes)


def test_sensor_readout_and_clock_domains():
    meta = {
        "sensor_timestamp_ns": 110_000_000_000,
        "actual_exposure_us": 500_000,
        "camera_type": "sim",
        "capture_backend": "sim",
    }
    timing = capture_timing(meta, profile().timing, mono=100.1, wall=1100.1, boot=110.1)
    assert timing.midpoint == pytest.approx(99.75)
    assert timing.wall_midpoint == pytest.approx(1099.75)
    assert timing.start_min == pytest.approx(99.499)
    assert timing.usable(100.1, 2, 0.01)
    assert not capture_timing(meta, {}, mono=100.1, wall=1100.1, boot=110.1).verified


@pytest.mark.parametrize(
    "patch",
    [
        {"synthetic": True},
        {"sensor_timestamp_ns": None},
        {"actual_exposure_us": float("nan")},
        {"sensor_timestamp_ns": 999_000_000_000},
    ],
)
def test_bad_frame_timing_cannot_authorize(patch):
    meta = {
        "sensor_timestamp_ns": 100_000_000_000,
        "actual_exposure_us": 500_000,
    } | patch
    assert not capture_timing(
        meta, profile().timing, mono=100, wall=1100, boot=100
    ).verified


def test_mailbox_invalid_wins_over_late_and_duplicate_valid():
    mailbox = TrackingMailbox()
    mailbox.arm({"session": "session"})
    assert mailbox.publish(measurement(101, 10))
    assert mailbox.publish(measurement(102, 11, quality="invalid", reason="cloud"))
    before = mailbox.snapshot()["quality_revision"]
    assert not mailbox.publish(measurement(101, 10))
    assert not mailbox.publish(measurement(102, 11))
    assert mailbox.snapshot()["quality_revision"] == before
    assert not mailbox.grant(TrackingPermission(context(), 15, 1))
    assert mailbox.publish(measurement(103, 12))
    assert mailbox.grant(TrackingPermission(context(), 15, mailbox.revision))
    mailbox.fail("worker_dead")
    mailbox.publish(measurement(104, 13))
    assert not mailbox.grant(TrackingPermission(context(), 15, mailbox.revision))


def test_stop_is_visible_before_fifo_consumption():
    q = PriorityMountQueue()
    try:
        before = q.control_epoch
        q.put({"type": "stop_movement"})
        assert q.control_epoch == before + 1
        assert not q.register_dispatch(before)
        assert q.get(timeout=1)["type"] == "stop_movement"
    finally:
        q.queue.close()
        q.queue.join_thread()


def test_controller_rechecks_stop_quality_and_permission_at_dispatch():
    controller = TrackingController(profile())
    controller.arm(context())
    plan = None
    for seq in range(1, 6):
        now = 10 + seq
        current = snapshot(measurement(seq, now), now)
        plan = controller.tick(current, now, 2)
        if plan:
            break
    assert plan is not None
    assert controller.validate_dispatch(plan, current, now, 2)
    assert not controller.validate_dispatch(plan, current, now, 3)
    assert not controller.validate_dispatch(
        plan, current | {"quality_revision": 999}, now, 2
    )
    assert not controller.validate_dispatch(plan, current, now + 1, 2)
    controller.hold("cloud")
    assert controller.pending_plan is None
    assert np.linalg.norm(controller.position_remaining) == 0


def test_fresh_unverified_exposure_is_reported_without_authorizing_a_pulse():
    from dataclasses import replace

    controller = TrackingController(profile())
    controller.arm(context())
    m = measurement(1, 10)
    m = replace(m, timing=replace(m.timing, verified=False))
    assert controller.tick(snapshot(m, 10), 10, 2) is None
    assert controller.reason == "timing_unverified"
    assert controller.pending_plan is None
    old = measurement(2, 1)
    assert controller.tick(snapshot(old, 10), 10, 2) is None
    assert controller.reason == "stale_measurement"


def test_closed_loop_converges_and_never_bursts_after_cloud():
    controller = TrackingController(profile())
    controller.arm(context())
    error = np.array([70.0, -40.0])
    commands = []
    errors = []
    for seq in range(1, 241):
        now = seq + 10.0
        cloud = 75 <= seq < 85
        m = measurement(seq, now, tuple(error), quality="invalid" if cloud else "valid")
        s = snapshot(m, now)
        plan = controller.tick(s, now, 2)
        if cloud:
            assert plan is None
        if plan:
            assert controller.validate_dispatch(plan, s, now, 2)
            assert plan.duration_ms <= controller.profile.max_pulse_ms
            error -= plan.expected_delta
            controller.acknowledge(
                plan, CorrectionReceipt(plan.command_id, "accepted", now, now + 0.3)
            )
            commands.append((seq, plan.duration_ms))
        error += (0.08, -0.05)
        errors.append(np.linalg.norm(error))
    assert commands
    assert np.mean(errors[-20:]) < 8
    assert errors[-1] < errors[0] / 8
    assert all(duration <= 250 for _, duration in commands)


def test_missing_new_frame_does_not_reset_ramp_or_recount_observation():
    c = TrackingController(profile())
    c.arm(context())
    for seq in range(1, 4):
        s = snapshot(measurement(seq, 10 + seq, (0, 0)), 10 + seq)
        c.tick(s, 10 + seq, 2)
    started, count = c.ramp_started, c.confirmations
    for t in (13.1, 13.2, 13.3):
        assert c.tick(s, t, 2) is None
    assert c.ramp_started == started
    assert c.confirmations == count


def test_recovery_budget_survives_holds_and_requires_progress():
    p = profile(recovery_count=2)
    b = RecoveryBudget(p)
    assert b.reserve(10, ("c", 1), 100, 100)
    assert not b.reserve(11, ("c", 1), 90, 100)
    assert not b.reserve(11, ("c", 2), 110, 100)
    assert b.reserve(12, ("c", 3), 50, 100)
    assert not b.reserve(13, ("c", 4), 10, 100)


def test_roi_centroid_rejects_hotpixel_saturation_and_competing_lights():
    p = profile()
    yy, xx = np.indices((128, 128))
    image = 50 + 500 * np.exp(-((yy - 60.3) ** 2 + (xx - 70.7) ** 2) / 3)
    patch = extract_rois(image, [(60, 71)], 12)[0]
    result = centroid(patch, p, 4095)
    assert result == pytest.approx((60.3, 70.7), abs=0.15)
    image[60, 70] = 4095
    assert centroid(extract_rois(image, [(60, 71)], 12)[0], p, 4095) is None
    hot = np.full((25, 25), 50.0)
    hot[12, 12] = 800
    assert centroid({"origin": (0, 0), "pixels": hot}, p, 4095) is None


def test_distribution_and_ra_wrap():
    p = profile()
    assert spatial_quality(
        np.array([(20 + i, 20 + i) for i in range(8)]), (50, 50), (100, 100), p
    )
    error = tangent_error((359.999, 0), (0.001, 0))
    assert np.linalg.norm(error) == pytest.approx(7.2, abs=0.001)
    assert tangent_error((0.001, 0), (359.999, 0))[0] == pytest.approx(-error[0])
