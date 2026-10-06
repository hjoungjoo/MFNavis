"""Synthetic RAW, loss/reacquisition, calibration and dispatch integration."""

from dataclasses import asdict, replace
from types import SimpleNamespace
from concurrent.futures import Future
import time
import numpy as np
import pytest
from PiFinder.tracking_calibration import CalibrationController
from PiFinder.tracking_contracts import (
    CaptureTiming,
    CorrectionPlan,
    CorrectionReceipt,
    TrackingPermission,
)
from PiFinder.tracking_control import TrackingController
from PiFinder.tracking_mailbox import TrackingMailbox
from PiFinder.tracking_mount_adapter import IndiTrackingAdapter
from PiFinder.tracking_quality import (
    StarTracker,
    build_reference,
    corrected_points,
    extract_rois,
    native_points,
    tangent_error,
)
from PiFinder.visual_tracking import CameraGeometry, plate_basis, vector_radec
from PiFinder import solver_frame_map as sfm
from test_smooth_tracking import profile, context, measurement, snapshot

pytestmark = pytest.mark.unit


def reference_scene(rotation=0):
    shape = (480, 640)
    info = dict(
        rotation_deg=rotation,
        crop_width_px=480,
        saturation_level=4095,
        distortion_coefficients=None,
    )
    native = np.array([(y, x) for y in (100, 240, 380) for x in (100, 320, 540)])
    points = corrected_points(native, shape, info)
    _, canvas = sfm.rotate_centroids([], shape, rotation)
    geo = CameraGeometry(*canvas, 4, (canvas[0] / 2, canvas[1] / 2), "sim")
    basis = plate_basis(40, 20, 12)
    stars = np.array([vector_radec(v) for v in geo.rays(points) @ basis])
    timing = CaptureTiming(99.7, 99.9, 99.8, 0.001, 1099.8, True, "clock")
    meta = dict(
        capture_epoch="capture", capture_sequence=1, tracking_timing=asdict(timing)
    )
    solution = dict(
        RA=40,
        Dec=20,
        Roll=12,
        FOV=4,
        RMSE=0.1,
        epoch_equinox=2000,
        matched_centroids=points,
        matched_stars=stars,
        matched_catID=list(range(len(points))),
        _alignment_frame=canvas,
    )
    p = profile(max_error_bound_arcsec=30)
    ref = build_reference(solution, meta, info, shape, (270, 290), "sim", p)
    target = vector_radec(
        CameraGeometry(**ref["geometry"]).rays([ref["geometry"]["target_yx"]])[0]
        @ basis
    )
    request = dict(
        session="session",
        connection=1,
        control=2,
        target=target,
        mode="active",
        started_mono=99.5,
    )
    return ref, request, p


def test_invalid_tracking_frame_keeps_star_counts_and_exclusion_evidence():
    ref, request, p = reference_scene()
    tracker = StarTracker(ref, request, p)
    rois = tracker.roi_request()
    yy, xx = np.indices(ref["raw_shape"])
    raw = np.full(ref["raw_shape"], 50.0)
    for i, (y, x) in enumerate(rois["centers"]):
        if i == 3:
            raw[round(y), round(x)] = 1000  # A hot pixel is not a star.
        else:
            amplitude = 5000 if i < 3 else 1 if i == 4 else 1000
            raw += amplitude * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / 3)
    frame = {
        "reference": ref["id"],
        "patches": extract_rois(raw, rois["centers"], 12),
        "metadata": {
            "capture_epoch": ref["capture_epoch"],
            "capture_sequence": 2,
            "actual_exposure_us": 100000,
            "actual_gain": 8,
            "tracking_timing": asdict(
                CaptureTiming(100.7, 100.9, 100.8, 0.001, 1100.8, True, "clock")
            ),
        },
    }
    result = tracker.measure(frame, 101)
    assert not result.valid
    assert result.reason == "stars_lost_or_ambiguous"
    assert result.stars == 4
    assert result.roi_counts == {
        "saturated": 3,
        "invalid_shape": 1,
        "low_signal": 1,
        "accepted": 4,
    }
    # Diagnostics do not relax the measurement approval criteria.
    controller = TrackingController(p)
    controller.arm(result.context)
    assert controller.tick(snapshot(result, 101), 101, request["control"]) is None


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_raw_to_reference_to_measurement_without_another_solve(rotation):
    ref, request, p = reference_scene(rotation)
    tracker = StarTracker(ref, request, p)
    geo = tracker.geometry
    pose = plate_basis(40.0005, 20.0003, 12.003)
    native = native_points(
        geo.project(ref["world"], pose),
        ref["raw_shape"],
        (geo.height, geo.width),
        ref["info"],
    )
    yy, xx = np.indices(ref["raw_shape"])
    raw = np.full(ref["raw_shape"], 50.0)
    for y, x in native:
        raw += 1000 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * 1.3**2))
    for seq in range(2, 8):
        now = 100 + seq * 0.5
        rois = tracker.roi_request()
        frame = dict(
            reference=ref["id"],
            patches=extract_rois(raw, rois["centers"], 12),
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
        )
        result = tracker.measure(frame, now)
        assert result.valid, result.reason
        expected = vector_radec(geo.rays([geo.target_yx])[0] @ pose)
        assert result.error == pytest.approx(
            tangent_error(expected, request["target"]), abs=2
        )
        assert result.camera_radec_roll[2] == pytest.approx(12.003, abs=0.01)
        assert result.context.reference == ref["id"]
        assert not result.absolute


def test_permission_revoke_requires_a_new_frame():
    box = TrackingMailbox()
    box.arm({"session": "session"})
    first = measurement(1, 10)
    box.publish(first)
    box.revoke("mount readback missing")
    permission = TrackingPermission(first.context, 20, box.revision)
    assert not box.grant(permission)
    box.publish(measurement(2, 10.5))
    assert box.grant(replace(permission, quality_floor=box.revision))


def test_bounded_prediction_during_star_loss_and_reconfirmation():
    p = profile(
        coast_verified=True,
        coast_max_s=1.5,
        coast_error_bound_arcsec=10,
        min_pulse_ms=10,
        coast_travel_arcsec=1,
    )
    controller = TrackingController(p)
    controller.arm(context())
    controller.coast_anchor = measurement(20, 10, error=(0.2, 0))
    controller.coast_drift = np.array([4.0, 0])
    loss = measurement(21, 10.1, quality="invalid", reason="stars_lost_or_ambiguous")
    s = snapshot(
        loss, 10.1, permission=TrackingPermission(context(), 12, 21, purpose="coast")
    )
    plan = controller.tick(s, 10.1, 2)
    assert plan and plan.kind == "coast" and plan.predicted
    assert controller.validate_dispatch(plan, s, 10.11, 2)
    assert not controller.validate_dispatch(plan, s, 10.11, 3)
    controller.acknowledge(
        plan, CorrectionReceipt(plan.command_id, "accepted", 10.1, 10.2)
    )
    assert controller.tick(s, 10.5, 2) is None
    assert controller.tick(s, 12, 2) is None
    for seq, now in [(22, 12.1), (23, 12.4)]:
        good = measurement(seq, now)
        assert controller.tick(snapshot(good, now), now, 2) is None
    assert controller.confirmations == 2


@pytest.mark.parametrize(
    "reason", ["clock_epoch_changed", "exposure_transition", "inconsistent_star_motion"]
)
def test_prediction_never_crosses_invalid_context(reason):
    controller = TrackingController(profile(coast_verified=True))
    controller.arm(context())
    controller.coast_anchor = measurement(1, 10)
    controller.coast_drift = np.array([4.0, 0])
    bad = measurement(2, 10.1, quality="invalid", reason=reason)
    s = snapshot(
        bad, 10.1, permission=TrackingPermission(context(), 12, 2, purpose="coast")
    )
    assert controller.tick(s, 10.1, 2) is None


@pytest.mark.parametrize("frame_interval", [0.03, 0.1, 0.2])
def test_video_calibration_retains_a_two_second_baseline(frame_interval):
    controller = CalibrationController(profile(verified=False, equipment_verified=True))
    controller.arm(context())
    for seq in range(int(4 / frame_interval)):
        now = 100 + seq * frame_interval
        m = measurement(seq, now, error=(20 + 0.1 * (now - 100), 20))
        data = snapshot(
            m,
            now,
            permission=TrackingPermission(
                context(), now + 2, seq, purpose="calibration"
            ),
        )
        plan = controller.tick(data, now, 2)
        if plan:
            break
    assert plan is not None
    assert plan.kind == "calibration"
    assert (
        controller.baseline[-1].timing.midpoint - controller.baseline[0].timing.midpoint
        >= 2
    )
    assert len(controller.baseline) <= 8


def test_calibration_respects_pulse_duty_between_probes():
    p = profile(verified=False, equipment_verified=True, max_duty=0.02)
    controller = CalibrationController(p)
    controller.arm(context())
    plan = None
    error = np.array([20.0, 20.0])
    for seq in range(8):
        now = 100 + seq * 0.5
        m = measurement(seq, now, error=tuple(error))
        data = snapshot(
            m,
            now,
            permission=TrackingPermission(
                context(), now + 2, seq, purpose="calibration"
            ),
        )
        plan = controller.tick(data, now, 2)
        if plan:
            break
    assert plan is not None
    sent_at = now
    error -= np.asarray(profile().response)[:, 0] * plan.duration_ms
    controller.acknowledge(
        plan, CorrectionReceipt(plan.command_id, "accepted", sent_at, sent_at + 0.26)
    )
    deadline = controller.next_send
    for seq in range(10, 60):
        now = sent_at + (seq - 9) * 0.5
        m = measurement(seq, now, error=tuple(error))
        data = snapshot(
            m,
            now,
            permission=TrackingPermission(
                context(), now + 2, seq, purpose="calibration"
            ),
        )
        next_plan = controller.tick(data, now, 2)
        if now < deadline:
            assert next_plan is None
        if next_plan:
            break
    assert next_plan is not None
    assert now >= deadline
    assert controller.probes == 1


def test_calibration_bootstraps_response_without_activating_model():
    p = profile(verified=False, equipment_verified=True, response=((0,) * 4, (0,) * 4))
    controller = CalibrationController(p)
    controller.arm(context())
    actual = np.asarray(profile().response)
    error = np.array([20.0, 20.0])
    direction = {"north": 0, "south": 1, "east": 2, "west": 3}
    for seq in range(140):
        now = 100 + seq * 0.5
        error += np.array([0.02, -0.01]) * 0.5
        m = measurement(seq, now, error=tuple(error))
        s = snapshot(
            m,
            now,
            permission=TrackingPermission(
                context(), now + 2, seq, purpose="calibration"
            ),
        )
        plan = controller.tick(s, now, 2)
        if plan:
            assert plan.kind == "calibration"
            assert controller.validate_dispatch(plan, s, now + 0.01, 2)
            error -= actual[:, direction[plan.direction]] * plan.duration_ms
            controller.acknowledge(
                plan, CorrectionReceipt(plan.command_id, "accepted", now, now + 0.26)
            )
        if controller.candidate:
            break
    assert controller.state == "CALIBRATION_COMPLETE", controller.status()
    assert controller.probes == 12
    assert not controller.candidate["verified"]
    assert np.array(controller.candidate["response"]) == pytest.approx(actual, abs=1e-6)


def test_adapter_dispatch_checks_quality_and_zeros_opposite(monkeypatch):
    now, p, ctx = time.monotonic(), profile(), context()
    m = measurement(1, now)
    s = snapshot(m, now, request={"session": ctx.session})
    widgets = [
        SimpleNamespace(name=n, min=0, max=2500, value=123)
        for n in ("TIMED_GUIDE_N", "TIMED_GUIDE_S")
    ]
    sent = []
    mount = SimpleNamespace(
        shared_state=SimpleNamespace(smooth_tracking=lambda: s),
        mount_queue=SimpleNamespace(
            control_epoch=2, register_dispatch=lambda e: e == 2
        ),
        device=SimpleNamespace(getNumber=lambda _: widgets),
        client=SimpleNamespace(
            sendNewNumber=lambda vec: sent.append([w.value for w in vec])
        ),
    )
    adapter = IndiTrackingAdapter(mount, p)
    monkeypatch.setattr(adapter, "ready", lambda *a, **k: "")
    plan = CorrectionPlan("cmd", ctx, m.key, 1, "north", 100, now + 1, (0, 2))
    try:
        assert adapter._send(plan)
        assert sent == [[100.0, 0.0]]
        s["quality_revision"] = 2
        assert not adapter._send(plan)
        assert len(sent) == 1
        adapter.profile = replace(p, coast_verified=True)
        s["measurement"] = replace(
            m, quality="invalid", reason="stars_lost_or_ambiguous", aligned_radec=None
        )
        s["permission"] = TrackingPermission(ctx, now + 1, 2, purpose="coast")
        coast = replace(plan, quality_revision=2, kind="coast", model_pointing=(40, 20))
        assert adapter._send(coast)
        assert not adapter._send(replace(coast, model_pointing=(50, 20)))
        future = Future()
        adapter.command_future, adapter.command_plan, adapter.submitted = (
            future,
            plan,
            now,
        )
        assert adapter.poll(now + 2)[1].state == "unknown"
        assert adapter.poll(now + 3) is None
        future.set_result(True)
        assert adapter.poll(now + 4)[1].state == "unknown"
    finally:
        adapter.close()


def test_recovery_requires_two_fresh_solves_and_preserves_partial_sync():
    from PiFinder.tracking_recovery import RecoveryCoordinator
    from PiFinder.tracking_control import RecoveryBudget

    ref, request, p = reference_scene()
    p = replace(p, goto={"verified": True, "max_separation_deg": 1})
    recovery = RecoveryCoordinator(p, RecoveryBudget(p))
    target = request["target"]
    recovery.observe_reference(ref, target)
    ctx = replace(
        context(), geometry=ref["geometry_key"], reference=ref["id"], target=target
    )
    m = measurement(4, 100.2, error=(0, 0), context=ctx)
    permission = TrackingPermission(ctx, 102, 4, allow_goto=True)
    assert recovery.propose(m, permission, 100.2) is None
    # Move the target enough to require recovery, with both absolute anchors agreeing.
    target = (target[0] + 0.01, target[1])
    recovery = RecoveryCoordinator(p, RecoveryBudget(p))
    recovery.observe_reference(ref, target)
    second = {
        **ref,
        "id": "new-reference",
        "sequence": 2,
        "timing": asdict(CaptureTiming(99.95, 100.1, 100, 0.001, 1100, True, "clock")),
    }
    recovery.observe_reference(second, target)
    ctx = replace(ctx, target=target)
    m = replace(m, context=ctx, error=recovery.references[-1]["error"])
    permission = replace(permission, context=ctx)
    plan = recovery.propose(m, permission, 100.2)
    assert plan and plan["kind"] == "goto"
    recovery.progress(
        {
            "request_id": plan["request_id"],
            "state": "cancelled",
            "verified_monotonic": 100.3,
        },
        False,
        100.4,
    )
    assert recovery.state == "limited"
    assert recovery.reason == "sync_applied_goto_cancelled"
    assert recovery.propose(m, permission, 100.4) is None


def test_late_solve_cannot_rewind_visual_estimate(monkeypatch):
    from PiFinder.integrator import (
        _apply_visual_measurement,
        _apply_successful_solve,
        _apply_failed_solve,
    )
    from PiFinder.types.positioning import (
        PointingEstimate,
        Pointing,
        PointingAxis,
        SolveSource,
    )

    monkeypatch.setattr("PiFinder.integrator.time.monotonic", lambda: 20)
    estimate = PointingEstimate(estimate_time=1010, last_solve_success=1010)
    old = Pointing(40, 20, 0)
    estimate.pointing.camera = PointingAxis(solve=old, estimate=old)
    estimate.pointing.aligned = PointingAxis(solve=old, estimate=old)
    m = measurement(10, 20, camera_radec_roll=(40.1, 20, 0), aligned_radec=(40.1, 20))
    ref = {"id": "ref", "target_pixel": (256, 256)}
    assert _apply_visual_measurement(estimate, m, (256, 256), ref)
    late = SimpleNamespace(
        last_solve_success=1015,
        last_solve_attempt=1015,
        camera=old,
        aligned=old,
        alignment=None,
        diagnostics=SimpleNamespace(AlignmentProjection=None),
    )
    idr = SimpleNamespace(solve=lambda *args: pytest.fail("late solve reseeded IMU"))
    _apply_successful_solve(estimate, late, idr)
    assert estimate.pointing.camera.estimate.RA == 40.1
    assert estimate.last_solve_success == 1015
    assert estimate.solve_source == SolveSource.VISUAL
    failure = SimpleNamespace(
        last_solve_attempt=1012,
        last_solve_success=1010,
        diagnostics=None,
        imu_observed_time=None,
    )
    _apply_failed_solve(estimate, failure)
    assert estimate.last_solve_success == 1015
    assert estimate.pointing.camera.estimate.RA == 40.1


def test_clock_generation_ignores_small_jitter_and_invalidates_step(monkeypatch):
    from PiFinder.tracking_capture import CaptureClock

    mono = [100.1]
    wall = [1100.1]
    monkeypatch.setattr("PiFinder.tracking_capture.time.monotonic", lambda: mono[0])
    monkeypatch.setattr("PiFinder.tracking_capture.time.time", lambda: wall[0])
    monkeypatch.setattr(
        "PiFinder.tracking_capture.time.clock_gettime", lambda _: mono[0]
    )
    mapper = CaptureClock()
    meta = dict(
        camera_type="sim",
        capture_backend="sim",
        sensor_timestamp_ns=100_000_000_000,
        actual_exposure_us=100000,
    )
    first = mapper.measure(meta, profile().timing)
    wall[0] += 0.001
    assert mapper.measure(meta, profile().timing).clock_epoch == first.clock_epoch
    wall[0] += 0.2
    assert mapper.measure(meta, profile().timing).clock_epoch != first.clock_epoch
    meta["capture_backend"] = "changed"
    assert not mapper.measure(meta, profile().timing).verified


def _child_stop(queue):
    queue.put({"type": "stop_movement"})


def test_stop_epoch_crosses_processes_and_serialized_mailbox_is_disarmed():
    import multiprocessing
    import pickle
    from PiFinder.tracking_commands import PriorityMountQueue

    queue = PriorityMountQueue()
    process = multiprocessing.get_context("fork").Process(
        target=_child_stop, args=(queue,)
    )
    try:
        process.start()
        process.join(timeout=2)
        assert process.exitcode == 0
        assert queue.control_epoch == 1
        assert queue.get(timeout=1)["type"] == "stop_movement"
    finally:
        if process.is_alive():
            process.terminate()
            process.join()
        queue.queue.close()
        queue.queue.join_thread()
    box = TrackingMailbox()
    box.arm({"session": "session"})
    box.publish(measurement(1, 10))
    restored = pickle.loads(pickle.dumps(box)).snapshot()
    assert restored["request"] is None and restored["permission"] is None


def test_stop_cancels_queued_motion_without_dropping_speed_then_move():
    from PiFinder.tracking_commands import PriorityMountQueue, stale_command

    mount = PriorityMountQueue()
    guide = PriorityMountQueue(mount.cancellation, mount.stop_epoch)
    try:
        mount.put({"type": "set_slew_rate", "rate": 2})
        mount.put({"type": "manual_movement", "direction": "east"})
        speed, move = mount.get(timeout=1), mount.get(timeout=1)
        assert not stale_command(speed, mount)
        assert not stale_command(move, mount)
        guide.put({"type": "stop_movement"})
        assert stale_command(move, mount)
        assert not stale_command(speed, mount)
        assert not stale_command(guide.get(timeout=1), mount)
    finally:
        for q in (mount, guide):
            q.queue.close()
            q.queue.join_thread()


@pytest.mark.parametrize("kind", ["sync_and_goto", "stop_movement", "set_track_freq"])
def test_guide_disable_survives_following_control_command(kind):
    from PiFinder.tracking_commands import PriorityMountQueue, stale_command

    commands = PriorityMountQueue()
    try:
        commands.put({"type": "toggle_guide_correction", "enabled": False})
        commands.put({"type": kind})
        disable = commands.get(timeout=1)
        assert disable["_control_epoch"] < commands.control_epoch
        assert not stale_command(disable, commands)
        commands.get(timeout=1)
    finally:
        commands.queue.close()
        commands.queue.join_thread()


def test_old_guide_enable_is_canceled_by_new_goto():
    from PiFinder.tracking_commands import PriorityMountQueue, stale_command

    commands = PriorityMountQueue()
    try:
        commands.put({"type": "toggle_guide_correction", "enabled": True})
        commands.put({"type": "sync_and_goto"})
        assert stale_command(commands.get(timeout=1), commands)
        commands.get(timeout=1)
    finally:
        commands.queue.close()
        commands.queue.join_thread()


def test_own_recovery_lease_survives_motion_frames_but_not_stop_or_timeout(monkeypatch):
    from PiFinder.smooth_mount_runtime import SmoothMountRuntime
    from PiFinder.tracking_recovery import RecoveryCoordinator

    now = [10.0]
    monkeypatch.setattr("PiFinder.smooth_mount_runtime.time.monotonic", lambda: now[0])
    m = measurement(2, 10, quality="invalid", reason="stars_lost_or_ambiguous")
    s = snapshot(
        m,
        10,
        request={"session": "session", "control": 2},
        permission=None,
        recovery_permission=TrackingPermission(
            context(), 12, 2, allow_goto=True, purpose="recovery"
        ),
    )
    queue = SimpleNamespace(control_epoch=2)
    mount = SimpleNamespace(
        mount_queue=queue,
        _client_generation=1,
        shared_state=SimpleNamespace(smooth_tracking=lambda: s),
    )
    runtime = SmoothMountRuntime(mount)
    runtime.controller = TrackingController(profile())
    runtime.recovery = RecoveryCoordinator(profile(), runtime.controller.budget)
    runtime.recovery.state = "moving"
    assert runtime.recovery_authorized()
    now[0] = 12.1
    assert not runtime.recovery_authorized()
    now[0] = 10.1
    queue.control_epoch = 3
    assert not runtime.recovery_authorized()


def test_insufficient_pulse_capacity_latches_limited():
    controller = TrackingController(profile())
    controller.arm(context())
    for seq in range(20):
        now = 100 + seq
        m = measurement(seq, now, error=(1000 + seq * 4, 0))
        plan = controller.tick(snapshot(m, now), now, 2)
        if plan:
            controller.acknowledge(
                plan, CorrectionReceipt(plan.command_id, "accepted", now, now + 0.26)
            )
        if controller.state == "LIMITED":
            break
    assert controller.state == "LIMITED"
    assert controller.reason == "pulse_capacity_insufficient"
    newer = measurement(40, 150)
    assert controller.tick(snapshot(newer, 150), 150, 2) is None
