"""Tracking-guide settle/recovery behavior of the INDI GoTo/Guide service."""

from multiprocessing import Queue

import pytest

import PiFinder.indi_goto_guide_service as iggs
from PiFinder.indi_goto_guide_service import IndiGotoGuideService


pytestmark = pytest.mark.unit


class DummyMountQueue:
    def __init__(self):
        self.commands = []

    def put(self, command):
        self.commands.append(command)


def _make_service(monkeypatch, clock):
    monkeypatch.setattr(iggs.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(iggs.time, "time", lambda: clock[0])
    service = IndiGotoGuideService(Queue(), DummyMountQueue(), None)
    service.config_values = {
        # B4: the tracking guide only runs in pifinder mode.
        "indi_goto_method": "pifinder",
        "indi_tracking_guide_enabled": True,
        "indi_tracking_guide_settle_seconds": 4.0,
        "indi_tracking_guide_motion_arcmin": 15.0,
        "indi_tracking_guide_threshold_arcmin": 10.0,
        "indi_tracking_guide_goto_recovery_enabled": True,
        "indi_tracking_guide_goto_threshold_deg": 0.5,
        "indi_tracking_guide_manual_retarget_enabled": False,
    }
    # Disturbed position 2 deg north of the tracking target: well above the
    # 0.5 deg GoTo recovery threshold.
    service.tracking_target_ra = 100.0
    service.tracking_target_dec = 20.0
    monkeypatch.setattr(
        service,
        "_mount_status_summary",
        lambda: {"available": True, "state": "connected"},
    )
    service._pointing = {
        "usable_for_goto": True,
        # A fresh plate solve: the recovery goto's sync anchor requires
        # source=solve / quality=high (solve-anchor gate, 2026-08-03).
        "current": {"ra": 100.0, "dec": 22.0, "source": "solve", "quality": "high"},
        "imu": {"metadata": {"moving": False}},
    }
    monkeypatch.setattr(
        service,
        "_refresh_pointing_status",
        lambda: {
            **service._pointing,
            "current": {"timestamp": clock[0], **service._pointing["current"]},
        },
    )
    monkeypatch.setattr(service, "_write_status", lambda **kwargs: None)
    return service


def _set_imu_moving(service, moving):
    service._pointing["imu"]["metadata"]["moving"] = moving


def test_runtime_goto_type_changes_without_config_write(monkeypatch):
    service = _make_service(monkeypatch, [1000.0])

    service.handle_command({"type": "set_goto_method", "goto_method": "indi_mount"})

    assert service.runtime_goto_method == "indi_mount"
    assert service.config_values["indi_goto_method"] == "indi_mount"


def test_pulse_align_threshold_is_capped_to_reachable_error(monkeypatch):
    service = _make_service(monkeypatch, [1000.0])
    service.config_values["indi_pifinder_goto_near_threshold_deg"] = 1.0
    service.config_values["indi_goto_refine_accuracy_arcmin"] = 6.0

    assert (
        service._pulse_align_threshold_arcmin()
        == iggs.PIFINDER_PULSE_ALIGN_MAX_ERROR_ARCMIN
    )


def test_refine_accuracy_falls_back_to_three_arcmin(monkeypatch):
    service = _make_service(monkeypatch, [1000.0])

    assert service._final_accuracy_arcmin() == pytest.approx(3.0)


def test_lower_configured_pulse_align_threshold_is_preserved(monkeypatch):
    service = _make_service(monkeypatch, [1000.0])
    service.config_values["indi_pifinder_goto_near_threshold_deg"] = 0.2
    service.config_values["indi_goto_refine_accuracy_arcmin"] = 6.0

    assert service._pulse_align_threshold_arcmin() == pytest.approx(12.0)


def test_arrival_solve_must_be_captured_after_mount_became_idle(monkeypatch):
    service = _make_service(monkeypatch, [1000.0])
    service.solve_anchor_required_after_wall = 999.0

    stale = {
        "source": "solve",
        "quality": "high",
        "timestamp": 998.9,
    }
    fresh = {
        "source": "solve",
        "quality": "high",
        "timestamp": 999.1,
    }

    assert service._is_fresh_arrival_solve(stale) is False
    assert service._is_fresh_arrival_solve(fresh) is True


def test_persistent_config_reload_clears_runtime_goto_type(monkeypatch):
    service = _make_service(monkeypatch, [1000.0])
    service.runtime_goto_method = "off"
    service.config_values["indi_goto_method"] = "off"
    reloaded = []
    monkeypatch.setattr(
        service, "_reload_config_if_needed", lambda: reloaded.append(True)
    )

    service.handle_command({"type": "reload_config"})

    assert service.runtime_goto_method is None
    assert reloaded == [True]


def test_recovery_starts_after_settle_when_motion_ends(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service.pointing_status = {
        "current": {"source": "mount_imu_delta"},
        "solved": {"valid": False},
    }

    # First tick baselines the coordinate and opens a fresh settle window.
    service._tick_tracking_guide()
    assert service.tracking_guide_state == "settling"

    # Stationary, IMU quiet: settle completes after 4 s, recovery fires.
    for _ in range(5):
        clock[0] += 1.0
        service._tick_tracking_guide()

    assert service.tracking_guide_state == "recovering_goto"
    commands = service.mountcontrol_queue.commands
    assert [c["type"] for c in commands] == ["sync_and_goto"]
    assert commands[-1]["ra"] == 100.0
    assert commands[-1]["dec"] == 20.0
    # B5 visibility: the recovery sync is tagged with its origin and the
    # coordinate source that fed the value.
    sync_command = commands[-1]
    assert sync_command["origin"] == "tracking_recovery"
    assert sync_command["pointing_source"] == "mount_imu_delta"


def test_goto_waits_for_matching_sync_ack_before_arrival_checks(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service.pointing_status = service._refresh_pointing_status()
    service._handle_goto_target({"type": "goto_target", "ra": 100.0, "dec": 20.0})
    command = service.mountcontrol_queue.commands[-1]
    assert command["type"] == "sync_and_goto"
    assert command["sync_ra"] == 100.0
    assert command["sync_dec"] == 22.0
    assert command["request_id"] == service.sync_goto_request_id
    clock[0] += 10.0
    service._tick_goto_wait()
    assert service.final_goto_idle_since == 0.0
    assert service.last_action == "waiting for mount sync verification"
    receipt = {"request_id": "old", "state": "goto_sent", "goto_sent_monotonic": 1001.0}
    assert not service._verified_sync_goto_ready({"sync_goto": receipt}, recovery=False)
    receipt.update(request_id=command["request_id"], goto_sent_monotonic=1009.0)
    assert service._verified_sync_goto_ready({"sync_goto": receipt}, recovery=False)
    assert service.final_goto_sent_at == 1009.0


def test_sync_failure_stops_goto_and_suspends_automatic_recovery(monkeypatch):
    service = _make_service(monkeypatch, [1000.0])
    service.pointing_status = service._refresh_pointing_status()
    service._handle_goto_target({"type": "goto_target", "ra": 100.0, "dec": 20.0})
    receipt = {
        "request_id": service.sync_goto_request_id,
        "state": "failed",
        "reason": "coordinate mismatch",
    }
    assert not service._verified_sync_goto_ready({"sync_goto": receipt}, recovery=False)
    assert service.phase == "error"
    assert service.wait_reason == "coordinate mismatch"
    assert service.tracking_guide_suspended is True
    assert service.mountcontrol_queue.commands[-1]["type"] == "stop_movement"


@pytest.mark.parametrize(
    "source,quality,timestamp",
    [("pifinder_imu_estimate", "medium", 999.0), ("solve", "high", 900.0)],
)
def test_first_goto_requires_recent_camera_anchor(
    monkeypatch, source, quality, timestamp
):
    service = _make_service(monkeypatch, [1000.0])
    service._pointing["current"].update(
        source=source, quality=quality, timestamp=timestamp
    )
    service._handle_goto_target({"type": "goto_target", "ra": 100.0, "dec": 20.0})
    assert service.phase == "pifinder_goto_blocked"
    assert not any(
        c["type"] == "sync_and_goto" for c in service.mountcontrol_queue.commands
    )


def _wait_for_initial_anchor(monkeypatch, clock):
    service = _make_service(monkeypatch, clock)
    service._pointing["current"].update(
        source="pifinder_imu_estimate", quality="medium"
    )

    # Match the production refresh's snapshot update as well as its return value.
    def refresh():
        service.pointing_status = {
            **service._pointing,
            "current": {"timestamp": clock[0], **service._pointing["current"]},
        }
        return service.pointing_status

    monkeypatch.setattr(service, "_refresh_pointing_status", refresh)
    service.handle_command({"type": "goto_target", "ra": 110.0, "dec": 30.0})
    return service


def test_initial_goto_resumes_once_with_new_optical_snapshot(monkeypatch):
    clock = [1000.0]
    service = _wait_for_initial_anchor(monkeypatch, clock)
    assert service.initial_goto_deadline == 1012.0
    assert service.tracking_target_ra is None
    service._tick_state_machine()
    assert not service.mountcontrol_queue.commands
    service._pointing["current"].update(source="solve", quality="high", ra=101.0)
    clock[0] += 1
    service._tick_state_machine()
    commands = service.mountcontrol_queue.commands
    assert [c["type"] for c in commands] == ["sync_and_goto"]
    assert commands[0]["sync_ra"] == 101.0
    assert commands[0]["ra"] == 110.0
    assert service.initial_goto_deadline is None
    service._tick_state_machine()
    assert len(commands) == 1


def test_initial_goto_expiry_never_authorizes_a_late_solve(monkeypatch):
    clock = [1000.0]
    service = _wait_for_initial_anchor(monkeypatch, clock)
    clock[0] = 1012.0
    service._pointing["current"].update(source="solve", quality="high")
    service._tick_state_machine()
    assert service.initial_goto_deadline is None
    assert "timed out" in service.wait_reason
    service._tick_state_machine()
    assert not service.mountcontrol_queue.commands


@pytest.mark.parametrize("timestamp", [900.0, 1002.0])
def test_initial_goto_wait_does_not_use_stale_or_future_optical_anchor(
    monkeypatch, timestamp
):
    service = _wait_for_initial_anchor(monkeypatch, [1000.0])
    service._pointing["current"].update(
        source="solve", quality="high", timestamp=timestamp
    )
    service._tick_state_machine()
    assert service.initial_goto_deadline == 1012.0
    assert not service.mountcontrol_queue.commands


def test_initial_goto_wait_is_canceled_by_config_mode_change(monkeypatch):
    service = _wait_for_initial_anchor(monkeypatch, [1000.0])
    service.config_values["indi_goto_method"] = "off"
    service._pointing["current"].update(source="solve", quality="high")
    service._tick_state_machine()
    service.config_values["indi_goto_method"] = "pifinder"
    service._tick_state_machine()
    assert service.initial_goto_deadline is None
    assert not service.mountcontrol_queue.commands


@pytest.mark.parametrize(
    "command",
    [
        {"type": "stop_movement"},
        {"type": "clear_tracking_target"},
        {"type": "suspend_tracking_guide"},
        {"type": "set_goto_method", "goto_method": "indi_mount"},
        {"type": "set_tracking_target", "ra": 100.0, "dec": 20.0},
    ],
)
def test_initial_goto_canceled_by_user_action(monkeypatch, command):
    clock = [1000.0]
    service = _wait_for_initial_anchor(monkeypatch, clock)
    service.handle_command(command)
    service._pointing["current"].update(source="solve", quality="high")
    service._tick_state_machine()
    assert service.initial_goto_deadline is None
    assert not any(
        c["type"] == "sync_and_goto" for c in service.mountcontrol_queue.commands
    )


def test_new_goto_replaces_waiting_target(monkeypatch):
    clock = [1000.0]
    service = _wait_for_initial_anchor(monkeypatch, clock)
    clock[0] += 2
    service.handle_command({"type": "goto_target", "ra": 120.0, "dec": 40.0})
    service._pointing["current"].update(source="solve", quality="high")
    service._tick_state_machine()
    commands = service.mountcontrol_queue.commands
    assert len(commands) == 1
    assert commands[0]["ra"] == 120.0
    assert commands[0]["dec"] == 40.0


@pytest.mark.parametrize(
    "mount",
    [
        {"park_state": "Parked"},
        {"state": "slewing"},
        {"mount_motion_active": True, "manual_motion_direction": "north"},
    ],
)
def test_initial_goto_canceled_when_mount_state_changes(monkeypatch, mount):
    service = _wait_for_initial_anchor(monkeypatch, [1000.0])
    monkeypatch.setattr(
        service, "_mount_status_summary", lambda: {"available": True, **mount}
    )
    service._pointing["current"].update(source="solve", quality="high")
    service._tick_state_machine()
    assert service.initial_goto_deadline is None
    assert not service.mountcontrol_queue.commands


def test_lingering_imu_flag_cannot_delay_recovery_indefinitely(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    _set_imu_moving(service, True)

    service._tick_tracking_guide()
    assert service.tracking_guide_state == "disturbed"

    # Coordinate is perfectly still but the IMU flag stays set (micro-sway):
    # the flag blocks recovery only up to 2x the settle window (8 s here).
    for _ in range(7):
        clock[0] += 1.0
        service._tick_tracking_guide()
        assert service.tracking_guide_state == "disturbed"

    clock[0] += 1.0
    service._tick_tracking_guide()

    assert service.tracking_guide_state == "recovering_goto"
    assert service.tracking_imu_flag_overridden is True


def test_coordinate_motion_still_blocks_recovery(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service._tick_tracking_guide()

    # The coordinate keeps jumping >15' per tick: recovery must stay blocked
    # no matter how long it goes on (this is a real ongoing push).
    for i in range(20):
        clock[0] += 1.0
        service._pointing["current"]["dec"] = 22.5 + (0.5 if i % 2 else 0.0)
        service._tick_tracking_guide()
        assert service.tracking_guide_state == "disturbed"


def test_short_imu_flag_episode_extends_settle_normally(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service._tick_tracking_guide()

    # IMU flag set for 2 s, then clears: recovery waits 4 s from the LAST
    # IMU-moving tick, not from the coordinate baseline.
    for _ in range(2):
        clock[0] += 1.0
        _set_imu_moving(service, True)
        service._tick_tracking_guide()
        assert service.tracking_guide_state == "disturbed"

    _set_imu_moving(service, False)
    for _ in range(3):
        clock[0] += 1.0
        service._tick_tracking_guide()
        assert service.tracking_guide_state == "settling"

    clock[0] += 1.0
    service._tick_tracking_guide()
    assert service.tracking_guide_state == "recovering_goto"


def test_target_below_altitude_limit_abandons_without_slew(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    monkeypatch.setattr(service, "_tracking_target_altitude_deg", lambda: 5.0)

    service._tick_tracking_guide()

    assert service.tracking_guide_state == "failed"
    assert service.tracking_target_ra is None
    assert service.tracking_target_dec is None
    commands = [c["type"] for c in service.mountcontrol_queue.commands]
    assert "goto_target" not in commands
    assert "stop_movement" in commands


def test_target_above_altitude_limit_recovers_normally(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    monkeypatch.setattr(service, "_tracking_target_altitude_deg", lambda: 45.0)

    service._tick_tracking_guide()
    for _ in range(4):
        clock[0] += 1.0
        service._tick_tracking_guide()

    assert service.tracking_guide_state == "recovering_goto"


def test_large_recovery_error_still_recovers(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    # Current position 15 deg away from the target (e.g. a large hand-slew):
    # recovery has no error cap, only the target-altitude guard.
    service._pointing["current"]["dec"] = 35.0

    service._tick_tracking_guide()
    for _ in range(4):
        clock[0] += 1.0
        service._tick_tracking_guide()

    assert service.tracking_guide_state == "recovering_goto"
    assert service.tracking_target_ra is not None


def test_user_manual_move_retargets_even_when_guide_was_enabled(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service.config_values["indi_tracking_guide_manual_retarget_enabled"] = True
    # Reproduce normal tracking: correction is armed before the user presses a
    # keypad/keyboard/joystick/web direction control.
    service.tracking_guide_active_sent = True
    mount_status = {
        "available": True,
        "state": "manual_motion",
        "manual_motion_direction": "north",
        "manual_motion_origin": "user",
    }
    monkeypatch.setattr(service, "_mount_status_summary", lambda: mount_status)

    service._tick_tracking_guide()

    assert service.manual_retarget_pending is True
    assert service.tracking_guide_state == "manual_move"

    mount_status.clear()
    mount_status.update({"available": True, "state": "connected"})
    for _ in range(5):
        clock[0] += 1.0
        service._tick_tracking_guide()

    assert service.manual_retarget_pending is False
    assert service.tracking_target_ra == 100.0
    assert service.tracking_target_dec == 22.0
    assert service.tracking_guide_state == "enabled"
    assert service.manual_retarget_count == 1
    assert not any(
        command["type"] == "goto_target"
        for command in service.mountcontrol_queue.commands
    )


def test_guide_fallback_motion_never_retargets(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service.config_values["indi_tracking_guide_manual_retarget_enabled"] = True
    mount_status = {
        "available": True,
        "state": "guide_correction",
        "manual_motion_direction": "north",
        "manual_motion_origin": "guide_correction",
    }
    monkeypatch.setattr(service, "_mount_status_summary", lambda: mount_status)

    service._tick_tracking_guide()

    assert service.manual_retarget_pending is False
    assert service.tracking_target_ra == 100.0
    assert service.tracking_target_dec == 20.0


def test_external_disturbance_recovers_with_manual_retarget_enabled(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service.config_values["indi_tracking_guide_manual_retarget_enabled"] = True

    service._tick_tracking_guide()
    for _ in range(4):
        clock[0] += 1.0
        service._tick_tracking_guide()

    assert service.manual_retarget_pending is False
    assert service.tracking_guide_state == "recovering_goto"
    assert service.tracking_target_ra == 100.0
    assert service.tracking_target_dec == 20.0


def test_indi_mount_mode_deactivates_tracking_guide_entirely(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service.config_values["indi_goto_method"] = "indi_mount"
    # Simulate a previously armed correction that must be switched off.
    service.tracking_guide_active_sent = True

    # A full settle window with a 2 deg error: in pifinder mode this fires a
    # sync + GoTo recovery, in indi_mount mode nothing may move the mount.
    service._tick_tracking_guide()
    for _ in range(5):
        clock[0] += 1.0
        service._tick_tracking_guide()

    assert service.tracking_guide_state == "off"
    assert "indi_mount mode" in service.tracking_guide_last_action
    # The armed target is dropped so a later mode switch starts clean.
    assert service.tracking_target_ra is None
    assert service.tracking_target_dec is None
    # The only mount command allowed is switching the guide correction OFF.
    commands = [c["type"] for c in service.mountcontrol_queue.commands]
    assert commands == ["toggle_guide_correction"]
    assert service.mountcontrol_queue.commands[0]["enabled"] is False


def test_indi_mount_goto_does_not_arm_tracking_target(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service.config_values["indi_goto_method"] = "indi_mount"
    service.tracking_target_ra = None
    service.tracking_target_dec = None
    monkeypatch.setattr(service, "_forward_to_mountcontrol", lambda command: True)

    service._handle_goto_target({"type": "goto_target", "ra": 120.0, "dec": 10.0})

    assert service.phase == "indi_mount_goto"
    assert service.tracking_target_ra is None
    assert service.tracking_target_dec is None


def test_clear_tracking_target_command(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)

    assert service.handle_command({"type": "clear_tracking_target"}) is True

    assert service.tracking_target_ra is None
    assert service.tracking_target_dec is None
    service._tick_tracking_guide()
    assert service.tracking_guide_state == "waiting_target"


def test_set_tracking_target_rearms_recovery(monkeypatch):
    service = _make_service(monkeypatch, [1000.0])
    service.tracking_guide_suspended = True
    service.manual_retarget_pending = True

    assert service.handle_command(
        {"type": "set_tracking_target", "ra": 123.0, "dec": -22.0}
    )

    assert service.tracking_target_ra == 123.0
    assert service.tracking_target_dec == -22.0
    assert service.tracking_guide_suspended is False
    assert service.manual_retarget_pending is False


def test_suspend_blocks_corrections_until_new_goto(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)

    assert service.handle_command({"type": "suspend_tracking_guide"}) is True
    assert service.tracking_guide_suspended is True

    # Stationary through a full settle window: no recovery or pulse commands
    # may be issued while suspended.
    service._tick_tracking_guide()
    for _ in range(5):
        clock[0] += 1.0
        service._tick_tracking_guide()

    assert service.tracking_guide_state == "suspended"
    assert service.mountcontrol_queue.commands == []

    # A new GoTo lifts the suspension.
    service._handle_goto_target({"type": "goto_target", "ra": 100.0, "dec": 20.0})
    assert service.tracking_guide_suspended is False


def test_suspend_lifts_after_manual_move_settles(monkeypatch):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service.handle_command({"type": "suspend_tracking_guide"})

    # Baseline tick, then a user manual move ends (the motion branch arms this
    # flag in production; set it directly here) and the coordinate settles.
    service._tick_tracking_guide()
    service.manual_retarget_pending = True
    for _ in range(5):
        clock[0] += 1.0
        service._tick_tracking_guide()

    assert service.tracking_guide_suspended is False
    # Manual re-target is disabled in this config, so after the suspension
    # lifts the 2 deg error goes straight to GoTo recovery.
    assert service.tracking_guide_state == "recovering_goto"


def test_recovery_waits_for_solve_anchor_then_recovers(monkeypatch):
    # An IMU-estimate anchor must not start the recovery goto immediately:
    # the gate holds until a recent camera solve arrives.
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service._pointing["current"]["source"] = "pifinder_imu_estimate"
    service._pointing["current"]["quality"] = "medium"

    service._tick_tracking_guide()
    for _ in range(4):
        clock[0] += 1.0
        service._tick_tracking_guide()

    assert service.tracking_guide_state == "settling"
    assert service.tracking_guide_last_action == "recovery waiting for solve anchor"
    commands = [c["type"] for c in service.mountcontrol_queue.commands]
    assert "goto_target" not in commands

    # A solve arriving during the wait starts the recovery right away.
    service._pointing["current"]["source"] = "solve"
    service._pointing["current"]["quality"] = "high"
    clock[0] += 1.0
    service._tick_tracking_guide()
    assert service.tracking_guide_state == "recovering_goto"


@pytest.mark.parametrize(
    "sample",
    [
        {"source": "pifinder_imu_estimate", "quality": "medium"},
        {"source": "solve", "quality": "high", "timestamp": 900.0},
        {"source": "solve", "quality": "high", "timestamp": 1100.0},
        {"source": "solve", "quality": "high", "timestamp": None},
    ],
)
def test_recovery_does_not_use_untrusted_anchor_after_timeout(monkeypatch, sample):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service._pointing["current"].update(sample)
    service.tracking_guide_active_sent = True

    service._tick_tracking_guide()
    for _ in range(4):
        clock[0] += 1.0
        service._tick_tracking_guide()
    assert service.tracking_guide_state == "settling"

    clock[0] += iggs.PIFINDER_SOLVE_ANCHOR_WAIT_SECONDS + 1.0
    service._tick_tracking_guide()
    assert service.tracking_guide_state == "waiting_coordinate"
    assert service.tracking_guide_last_action == "recovery waiting: no fresh solve"
    clock[0] += 20.0
    service._tick_tracking_guide()
    assert service.tracking_guide_state == "waiting_coordinate"
    commands = service.mountcontrol_queue.commands
    assert {"type": "toggle_guide_correction", "enabled": False} in commands
    assert not any(c["type"] in {"goto_target", "sync"} for c in commands)

    # The existing recovery proceeds immediately when a real solve returns.
    service._pointing["current"].update(
        source="solve", quality="high", timestamp=clock[0]
    )
    service._tick_tracking_guide()
    assert service.tracking_guide_state == "recovering_goto"


@pytest.mark.parametrize(
    "source,quality", [("pifinder_imu_estimate", "medium"), ("solve", "high")]
)
def test_arrival_timeout_does_not_sync_estimate_or_pre_idle_solve(
    monkeypatch, source, quality
):
    clock = [1000.0]
    service = _make_service(monkeypatch, clock)
    service.active_target_ra = 100.0
    service.active_target_dec = 22.0
    service.phase = "pifinder_goto"
    service.final_goto_sent_at = 990.0
    service.final_goto_idle_since = 995.0
    service.solve_anchor_required_after_wall = 995.0
    service.solve_anchor_wait_since = 985.0
    service._pointing["current"].update(source=source, quality=quality, timestamp=994.0)
    service._tick_goto_wait()
    assert service.phase == "error"
    assert service.wait_reason == "No fresh plate solve after GoTo"
    assert service.final_sync_sent is False
    assert not any(
        c["type"] in {"goto_target", "sync"}
        for c in service.mountcontrol_queue.commands
    )


def test_recent_post_idle_solve_can_finish_goto_without_extra_wait(monkeypatch):
    service = _make_service(monkeypatch, [1000.0])
    service.active_target_ra = 100.0
    service.active_target_dec = 22.0
    service.phase = "pifinder_goto"
    service.final_goto_sent_at = 990.0
    service.final_goto_idle_since = 995.0
    service.solve_anchor_required_after_wall = 995.0
    service._pointing["current"]["timestamp"] = 999.0

    service._tick_goto_wait()

    assert service.phase == "complete"
    assert service.final_sync_sent is True
    assert [c["type"] for c in service.mountcontrol_queue.commands] == ["sync"]
