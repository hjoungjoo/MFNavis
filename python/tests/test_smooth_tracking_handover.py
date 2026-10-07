"""Correction ownership at legacy/optical handover; no hardware I/O."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from PiFinder.smooth_mount_runtime import SmoothMountRuntime
from PiFinder.smooth_tracking_runtime import start_session
from PiFinder.tracking_control import TrackingController
from PiFinder.tracking_calibration import CalibrationController
from PiFinder.tracking_mailbox import TrackingMailbox
from test_indi_goto_guide_service import _make_service
from test_mountcontrol_indi import DummyMountControl
from test_smooth_tracking import context, measurement, profile, snapshot

pytestmark = pytest.mark.unit


@pytest.fixture
def mount(monkeypatch, tmp_path):
    from PiFinder import config, mountcontrol_indi

    monkeypatch.setattr(config.utils, "data_dir", tmp_path)
    monkeypatch.setattr(config.utils, "runtime_dir", tmp_path)
    monkeypatch.setattr(mountcontrol_indi, "STATUS_FILE", tmp_path / "mount.json")
    result = DummyMountControl()
    result._smooth_runtime = SmoothMountRuntime(result)
    return result


def test_shadow_cancel_preserves_legacy_prediction(mount):
    mount._guide_correction_enabled = True
    mount._guide_predictive_tracking = True
    mount._smooth_runtime.controller = TrackingController(profile())
    mount._smooth_runtime.cancel("control_epoch_changed")
    assert mount._guide_correction_enabled
    assert mount._guide_predictive_tracking


@pytest.mark.parametrize("enabled", [True, False])
def test_delayed_legacy_toggle_cannot_change_rate_during_optical_pulse(mount, enabled):
    mount._smooth_runtime.claimed = True
    mount._restore_fine_guide_rate = Mock()
    mount.toggle_guide_correction(enabled, 40, 20)
    assert not mount._guide_correction_enabled
    mount._restore_fine_guide_rate.assert_not_called()


def setup_service(monkeypatch, mode):
    from PiFinder import config, smooth_tracking_runtime, visual_tracking_target

    service = _make_service(monkeypatch, [1000.0])
    box = TrackingMailbox()

    def smooth(action="snapshot", value=None):
        return box.snapshot() if action == "snapshot" else getattr(box, action)(value)

    service.shared_state = SimpleNamespace(
        smooth_tracking=smooth, solution=lambda: None
    )
    values = {
        "smooth_tracking_mode": mode,
        "smooth_tracking_profile": profile().to_dict(),
    }
    monkeypatch.setattr(
        config,
        "Config",
        lambda: SimpleNamespace(
            get_option=lambda key, default=None: values.get(key, default)
        ),
    )
    monkeypatch.setattr(smooth_tracking_runtime, "optics_identity", lambda *a: "sim")
    monkeypatch.setattr(
        visual_tracking_target.TargetEphemeris,
        "resolve",
        lambda *a, **kw: SimpleNamespace(ra=40, dec=20),
    )
    return service, box


def test_new_optical_session_still_enables_its_own_prediction(monkeypatch):
    service, _ = setup_service(monkeypatch, "active")
    request = start_session(
        service,
        {"type": "smooth_tracking_start", "frame": "catalog", "ra": 40, "dec": 20},
    )
    assert request["prediction"] is True


def test_default_active_still_requires_verified_profile_before_arming(monkeypatch):
    from PiFinder import config

    service, box = setup_service(monkeypatch, "active")
    values = {"smooth_tracking_profile": profile(verified=False).to_dict()}
    monkeypatch.setattr(
        config,
        "Config",
        lambda: SimpleNamespace(
            get_option=lambda key, default=None: values.get(key, default)
        ),
    )
    with pytest.raises(ValueError, match="has not been verified"):
        start_session(
            service,
            {"type": "smooth_tracking_start", "frame": "catalog", "ra": 40, "dec": 20},
        )
    assert box.snapshot()["request"] is None
    assert not service.mountcontrol_queue.commands


@pytest.mark.parametrize("lost", [False, True])
def test_optical_policy_preserves_prediction_and_bounded_coast(monkeypatch, lost):
    from PiFinder.smooth_tracking_runtime import tick_policy

    service = _make_service(monkeypatch, [1000.0])
    mount_status = {"available": True, "tracking_enabled": True, "connection_epoch": 1}
    monkeypatch.setattr(service, "_mount_status_summary", lambda: mount_status)
    monkeypatch.setattr(service, "_mount_status_fresh", lambda _: True)
    box = TrackingMailbox()
    box.arm(
        {
            "session": "session",
            "mode": "active",
            "control": 0,
            "connection": 1,
            "profile": profile(coast_verified=True).to_dict(),
            "prediction": True,
            "axis": False,
            "goto": False,
        }
    )
    box.publish(
        measurement(
            1,
            1000,
            quality="invalid" if lost else "valid",
            reason="stars_lost_or_ambiguous" if lost else "test",
        )
    )

    def smooth(action="snapshot", value=None):
        if action == "snapshot":
            return box.snapshot()
        if action == "permission":
            return box.grant(value)
        raise AssertionError(action)

    service.shared_state = SimpleNamespace(smooth_tracking=smooth)
    assert tick_policy(service)
    permission = box.snapshot()["permission"]
    assert permission and permission.allow_prediction
    assert permission.purpose == ("coast" if lost else "tracking")


def test_active_stop_does_not_silently_resume_legacy_recovery(monkeypatch):
    service, box = setup_service(monkeypatch, "active")
    start_session(
        service,
        {"type": "smooth_tracking_start", "frame": "catalog", "ra": 40, "dec": 20},
    )
    box.stop("settings_changed")
    service.config_values["indi_tracking_guide_settle_seconds"] = 0
    service._tick_solve_fallback = Mock(return_value=False)
    service._tick_state_machine()
    service._tick_tracking_guide_states()
    assert not service.mountcontrol_queue.commands
    service._tick_solve_fallback.assert_not_called()
    assert service.tracking_guide_state == "suspended"
    service.handle_command({"type": "resume_tracking_guide"})
    assert not service.smooth_tracking_legacy_suspended


def test_stopping_shadow_does_not_disable_existing_guide(monkeypatch):
    service, _ = setup_service(monkeypatch, "shadow")
    service.tracking_guide_active_sent = True
    start_session(
        service,
        {"type": "smooth_tracking_start", "frame": "catalog", "ra": 40, "dec": 20},
    )
    service.handle_command({"type": "smooth_tracking_stop"})
    assert service.tracking_guide_active_sent
    assert not service.tracking_guide_suspended
    assert not service.mountcontrol_queue.commands


def test_handover_waits_for_legacy_pulse_and_settle(mount, monkeypatch):
    monkeypatch.setattr("PiFinder.smooth_mount_runtime.time.monotonic", lambda: 100.0)
    runtime = mount._smooth_runtime
    runtime.controller = TrackingController(profile(settle_s=0.3))
    runtime.claimed = True
    mount._guide_pulse_until = 100.5
    runtime._suspend_legacy()
    assert runtime.drain_until >= 100.8


@pytest.mark.parametrize("kind", ["goto_target", "sync"])
def test_old_queued_motion_cannot_cross_optical_handover(mount, kind):
    runtime = mount._smooth_runtime
    runtime.claimed = True
    runtime.ownership_epoch = 2
    mount.set_slew_rate = Mock()
    mount.handle_command(
        {"type": kind, "_control_epoch": 1, "ra": 40, "dec": 20, "rate": 1}
    )
    assert not mount.goto_calls and not mount.sync_calls
    mount.set_slew_rate.assert_not_called()


def test_shadow_stop_does_not_cancel_unrelated_queued_goto():
    from PiFinder.tracking_commands import PriorityMountQueue, stale_command

    queue = PriorityMountQueue()
    try:
        queue.put({"type": "goto_target", "ra": 40, "dec": 20})
        goto = queue.get(timeout=1)
        queue.put({"type": "smooth_tracking_stop"})
        assert queue.control_epoch > goto["_control_epoch"]
        assert not stale_command(goto, queue)
        queue.get(timeout=1)
    finally:
        queue.queue.close()
        queue.queue.join_thread()


@pytest.mark.parametrize("cancel", [False, True])
def test_explicit_legacy_resume_waits_for_optical_drain(mount, monkeypatch, cancel):
    now = [100.0]
    monkeypatch.setattr("PiFinder.smooth_mount_runtime.time.monotonic", lambda: now[0])
    mount.mount_queue = SimpleNamespace(control_epoch=2)
    mount.shared_state = SimpleNamespace(
        smooth_tracking=lambda: {"request": None, "measurement": None}
    )
    runtime = mount._smooth_runtime
    runtime.claimed = runtime.canceled = True
    runtime.ownership_epoch = 1
    runtime.last_epoch = 2
    runtime.drain_until = 101.0
    mount.toggle_guide_correction = Mock()
    mount.handle_command(
        {
            "type": "toggle_guide_correction",
            "enabled": True,
            "target_ra": 40,
            "target_dec": 20,
        }
    )
    runtime.tick()
    mount.toggle_guide_correction.assert_not_called()
    if cancel:
        mount.mount_queue.control_epoch = 3
    now[0] = 101.1
    runtime.tick()
    assert mount.toggle_guide_correction.call_count == (0 if cancel else 1)
    runtime.tick()
    assert mount.toggle_guide_correction.call_count == (0 if cancel else 1)


def test_handover_rejects_frame_exposed_during_legacy_pulse(mount, monkeypatch):
    now = [101.0]
    monkeypatch.setattr("PiFinder.smooth_mount_runtime.time.monotonic", lambda: now[0])
    mount.mount_queue = SimpleNamespace(control_epoch=2)
    data = snapshot(
        measurement(1, 100.7),
        now[0],
        request={"mode": "active", "session": "session", "control": 2},
        reference=None,
    )
    mount.shared_state = SimpleNamespace(smooth_tracking=lambda *a: data)
    runtime = mount._smooth_runtime
    runtime.last_epoch = 2
    runtime.session = "session"
    runtime.claimed = True
    runtime.drain_until = 100.8
    runtime.controller = TrackingController(profile())
    runtime.recovery = SimpleNamespace(state="idle", observe_reference=Mock())
    runtime.adapter = SimpleNamespace(
        poll=lambda now: None,
        refresh=Mock(),
        ready=lambda *a, **kw: "",
        command_future=None,
    )
    runtime.tick()
    assert not runtime.controller.history.samples
    assert runtime.controller.reason == "waiting_post_command_exposure"
    data["measurement"] = measurement(2, 101.0)
    runtime.tick()
    assert len(runtime.controller.history.samples) == 1


@pytest.mark.parametrize("started", [None, 100.0])
def test_calibration_reference_refresh_can_rebind_only_before_baseline(
    mount, monkeypatch, started
):
    monkeypatch.setattr("PiFinder.smooth_mount_runtime.time.monotonic", lambda: 101.0)
    mount.mount_queue = SimpleNamespace(control_epoch=2)
    refreshed = replace(context(), reference="fresh-reference")
    data = snapshot(
        measurement(2, 101.0, context=refreshed),
        101.0,
        permission=None,
        request={
            "mode": "active",
            "session": "session",
            "control": 2,
            "purpose": "calibration",
        },
        reference=None,
    )
    mount.shared_state = SimpleNamespace(smooth_tracking=lambda *a: data)
    runtime = mount._smooth_runtime
    runtime.last_epoch = 2
    runtime.session = "session"
    runtime.claimed = True
    runtime.controller = CalibrationController(profile())
    runtime.controller.arm(context())
    runtime.controller.started = started
    runtime.recovery = SimpleNamespace(state="idle", observe_reference=Mock())
    runtime.adapter = SimpleNamespace(
        poll=lambda now: None,
        refresh=Mock(),
        ready=lambda *a, **kw: "",
        command_future=None,
    )
    runtime.tick()
    if started is None:
        assert runtime.controller.context == refreshed
        assert runtime.controller.started is None
        assert runtime.controller.state == "ACQUIRING"
    else:
        assert runtime.controller.context == context()
        assert runtime.controller.state == "LIMITED"
        assert runtime.controller.reason == "calibration_reference_changed"


def test_reference_refresh_preserves_best_effort_duty_and_response_backoff(
    mount, monkeypatch
):
    clock = [101.0]
    monkeypatch.setattr(
        "PiFinder.smooth_mount_runtime.time.monotonic", lambda: clock[0]
    )
    mount.mount_queue = SimpleNamespace(control_epoch=2)
    refreshed = replace(context(), reference="fresh-reference")
    data = snapshot(
        measurement(2, 101, context=refreshed),
        101,
        permission=None,
        request={"mode": "shadow", "session": "session", "control": 2},
        reference=None,
    )
    mount.shared_state = SimpleNamespace(smooth_tracking=lambda *a: data)
    runtime = mount._smooth_runtime
    runtime.last_epoch = 2
    runtime.session = "session"
    runtime.controller = TrackingController(profile(best_effort_s=12))
    runtime.controller.arm(context())
    runtime.controller.best_effort_started = 90
    runtime.controller.command_travel = 14
    runtime.controller.next_send = 104
    runtime.controller.feedback_gain = 0.5
    runtime.controller.direction_cooldowns = {"south": 110}
    runtime.controller.saturation.append((100, True, 30))
    runtime.recovery = SimpleNamespace(state="idle", observe_reference=Mock())
    runtime.tick()
    assert runtime.controller.context == refreshed
    assert runtime.controller.best_effort_started == 90
    assert runtime.controller.command_travel == 14
    assert runtime.controller.next_send == 104
    assert runtime.controller.feedback_gain == 0.5
    assert runtime.controller.direction_cooldowns == {"south": 110}
    assert list(runtime.controller.saturation) == [(100, True, 30)]
    clock[0] = 103
    data["measurement"] = measurement(
        3, 103, context=replace(refreshed, reference="newer")
    )
    runtime.tick()
    assert runtime.controller.state == "LIMITED"
    assert runtime.controller.reason == "best_effort_budget_exhausted"


def test_own_corrections_are_not_learned_as_external_drift():
    from PiFinder.tracking_motion import MotionHistory

    history = MotionHistory()
    for i in range(8):
        _, drift = history.observe(100 + i, (20 - 2 * i, 0), (2 * i, 0), 0.1, 5)
    assert drift is None
    history.reset()
    for i in range(8):
        _, drift = history.observe(
            100 + i, (20 - 2 * i + 0.5 * i, 0), (2 * i, 0), 0.1, 5
        )
    assert tuple(drift) == pytest.approx((0.5, 0))


def test_prediction_and_position_correction_share_one_pending_packet():
    from PiFinder.tracking_contracts import CorrectionReceipt, TrackingPermission

    controller = TrackingController(profile(deadband_arcsec=100))
    controller.arm(context())
    plan = None
    for seq in range(8):
        now = 100.0 + seq
        data = snapshot(
            measurement(seq, now, (seq * 5, 0)),
            now,
            permission=TrackingPermission(context(), now + 2, 0, allow_prediction=True),
        )
        plan = controller.tick(data, now, 2)
        if plan:
            break
    assert plan is not None and plan.predicted
    assert controller.tick(data, now, 2) is None
    controller.acknowledge(
        plan, CorrectionReceipt(plan.command_id, "accepted", now, now + 0.1)
    )
    newer = snapshot(measurement(seq + 1, now + 0.05, (150, 0)), now + 0.05)
    assert controller.tick(newer, now + 0.05, 2) is None


def test_user_ram_speed_change_does_not_take_optical_ownership(mount):
    mount._smooth_runtime.claimed = True
    mount._smooth_runtime.ownership_epoch = 2
    mount.handle_command({"type": "set_slew_rate", "_control_epoch": 1, "rate": 6})
    assert mount.user_manual_slew_rate == 6
    assert mount._smooth_runtime.claimed
    assert not mount._smooth_runtime.canceled
    assert not mount.goto_calls and not mount.sync_calls
