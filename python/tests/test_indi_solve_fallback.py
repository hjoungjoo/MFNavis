"""GoTo lifecycle across indoor operation and repeated camera outages."""

from queue import Queue

import pytest

from PiFinder import indi_goto_guide_service as mod

pytestmark = pytest.mark.unit


@pytest.fixture
def rig(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(mod.time, "time", lambda: clock[0])
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])
    service = mod.IndiGotoGuideService(Queue(), Queue(), None)
    service.config_values = {
        "indi_goto_method": "pifinder",
        "mount_control": True,
        "indi_tracking_guide_enabled": False,
        "indi_goto_allow_unaligned_imu": True,
    }
    mount = {
        "available": True,
        "tracking_enabled": True,
        "state": "connected",
        "mount_motion_active": False,
    }
    pointing = {
        "fresh": True,
        "usable_for_goto": False,
        "current": {},
        "solved": {},
        "imu": {
            "valid": True,
            "source": "imu_fallback",
            "ra": 100.0,
            "dec": 20.0,
            "timestamp": clock[0],
            "metadata": {"uses_magnetometer": False},
        },
    }

    def refresh():
        service.pointing_status = pointing
        return pointing

    monkeypatch.setattr(service, "_refresh_pointing_status", refresh)
    monkeypatch.setattr(service, "_mount_status_summary", lambda: mount)
    monkeypatch.setattr(service, "_tracking_target_altitude_deg", lambda: 45.0)
    monkeypatch.setattr(service, "_write_status", lambda **kw: None)
    return service, clock, mount, pointing


def commands(service):
    result = []
    while not service.mountcontrol_queue.empty():
        result.append(service.mountcontrol_queue.get_nowait())
    return result


def solve(rig, ra=110.0, dec=30.0, timestamp=None):
    _, clock, _, pointing = rig
    timestamp = clock[0] if timestamp is None else timestamp
    pointing.update(
        usable_for_goto=True,
        fresh=True,
        current={
            "valid": True,
            "source": "solve",
            "quality": "high",
            "ra": ra,
            "dec": dec,
            "timestamp": timestamp,
            "metadata": {
                "last_solve_attempt": timestamp,
                "last_solve_success": timestamp,
            },
        },
    )


def start(rig, optical=False):
    service, _, _, _ = rig
    if optical:
        solve(rig)
    service.handle_command({"type": "goto_target", "ra": 110.0, "dec": 30.0})
    return commands(service)[-1]


def acknowledge(rig):
    service, clock, mount, _ = rig
    mount["sync_goto"] = {
        "request_id": service.sync_goto_request_id,
        "state": "goto_sent",
        "goto_sent_monotonic": clock[0],
    }
    service._tick_state_machine()
    clock[0] += 2
    service._tick_state_machine()
    clock[0] += 2
    service._tick_state_machine()


def test_initial_indoor_goto_uses_provisional_imu_and_verified_transaction(rig):
    service, clock, _, _ = rig
    command = start(rig)
    assert command["type"] == "sync_and_goto"
    assert (command["sync_ra"], command["sync_dec"]) == (100.0, 20.0)
    assert command["pointing_source"] == "imu_provisional"
    assert service.phase == "native_goto"
    clock[0] += 3
    service._tick_state_machine()
    assert service.phase == "native_goto"  # Never assume an unacknowledged slew ended.
    acknowledge(rig)
    assert service.phase == "native_tracking"
    for _ in range(10):
        clock[0] += 1
        service._tick_state_machine()
        service._tick_tracking_guide()
    assert not commands(service)  # No repeated Sync, GoTo, or tracking toggles.
    assert service.solve_fallback_armed


@pytest.mark.parametrize(
    "change",
    [
        {"valid": False},
        {"ra": float("nan")},
        {"dec": 91.0},
        {"timestamp": 990.0},
        {"timestamp": 1001.0},
        {"source": "mount_imu_fused"},
        {"timestamp": None},
    ],
)
def test_invalid_imu_cannot_start_motion(rig, change):
    service, _, _, pointing = rig
    pointing["imu"].update(change)
    service.handle_command({"type": "goto_target", "ra": 110.0, "dec": 30.0})
    assert not commands(service)
    assert not service.solve_fallback_armed


@pytest.mark.parametrize(
    "allow,metadata,accepted",
    [
        (False, {}, False),
        (False, {"uses_magnetometer": True}, True),
        (False, {"alignment_applied": True}, True),
        (True, {}, True),
    ],
)
def test_unaligned_reference_requires_explicit_setting(rig, allow, metadata, accepted):
    service, _, _, pointing = rig
    service.config_values["indi_goto_allow_unaligned_imu"] = allow
    pointing["imu"]["metadata"] = metadata
    service.handle_command({"type": "goto_target", "ra": 110.0, "dec": 30.0})
    assert bool(commands(service)) is accepted


def test_plate_anchored_imu_preferred_over_raw_heading(rig):
    _, _, _, pointing = rig
    pointing["solved"] = {
        **pointing["imu"],
        "ra": 105.0,
        "source": "pifinder_imu_estimate",
        "metadata": {"has_plate_anchor": True},
    }
    command = start(rig)
    assert command["sync_ra"] == 105.0
    assert command["pointing_source"] == "pifinder_imu_estimate"


@pytest.mark.parametrize(
    "change",
    [{"park_state": "Parked"}, {"mount_motion_active": True}, {"available": False}],
)
def test_initial_native_goto_respects_mount_state(rig, change):
    service, _, mount, _ = rig
    mount.update(change)
    service.handle_command({"type": "goto_target", "ra": 110.0, "dec": 30.0})
    assert not commands(service)


def test_stale_status_cannot_supply_fresh_looking_imu(rig):
    service, _, _, pointing = rig
    pointing["fresh"] = False
    service.handle_command({"type": "goto_target", "ra": 110.0, "dec": 30.0})
    assert not commands(service)


def test_fresh_solve_restarts_normal_goto_then_fine_alignment(rig):
    service, clock, _, _ = rig
    start(rig)
    acknowledge(rig)
    clock[0] += 1
    solve(rig, dec=30.2)
    service._tick_state_machine()
    cmd = commands(service)[-1]
    assert service.phase == "pifinder_goto"
    assert cmd["origin"] == "pifinder_goto"
    assert cmd["sync_dec"] == 30.2
    assert service.correction_count == 1
    acknowledge(rig)
    solve(rig, dec=30.2)
    service._tick_state_machine()
    assert service.phase == "pifinder_pulse_align"
    assert commands(service)[-1]["manual_approach"] is True
    solve(rig)
    service._tick_state_machine()
    assert service.phase == "complete"
    assert commands(service)[-1]["origin"] == "pifinder_final_sync"


def test_solve_during_slew_is_not_a_recovery_anchor(rig):
    service, clock, mount, _ = rig
    start(rig)
    mount["mount_motion_active"] = True
    acknowledge(rig)
    solve(rig)
    service._tick_state_machine()
    mount["mount_motion_active"] = False
    clock[0] += 1
    service._tick_state_machine()
    clock[0] += 2
    service._tick_state_machine()
    assert not commands(service)
    solve(rig)
    service._tick_state_machine()
    assert commands(service)[-1]["origin"] == "pifinder_goto"


def test_failed_frame_mid_goto_keeps_existing_native_slew(rig):
    service, clock, mount, pointing = rig
    start(rig, optical=True)
    mount["mount_motion_active"] = True
    pointing["current"]["metadata"]["last_solve_attempt"] = 1001.0
    clock[0] = 1001.0
    service._tick_state_machine()
    assert service.phase == "native_goto"
    assert not commands(service)
    assert service.sync_goto_request_id is not None


def test_imu_updates_between_successful_frames_are_not_outages(rig):
    service, _, _, pointing = rig
    start(rig, optical=True)
    pointing["current"].update(source="pifinder_imu_estimate", quality="medium")
    service._tick_state_machine()
    assert service.phase == "pifinder_goto"
    assert not commands(service)


def test_failure_during_fine_alignment_finishes_with_native_goto(rig):
    service, clock, _, pointing = rig
    start(rig, optical=True)
    service.sync_goto_request_id = None
    service._begin_pulse_align()
    commands(service)
    pointing["current"]["metadata"]["last_solve_attempt"] = 1001.0
    clock[0] = 1001.0
    service._tick_state_machine()
    cmd = commands(service)
    assert cmd[0] == {"type": "toggle_guide_correction", "enabled": False}
    assert cmd[-1]["type"] == "sync_and_goto"
    assert service.phase == "native_goto"


@pytest.mark.parametrize("guide_enabled", [True, False])
def test_repeated_outages_and_recovery_while_tracking(rig, guide_enabled):
    service, clock, _, pointing = rig
    service.config_values["indi_tracking_guide_enabled"] = guide_enabled
    start(rig, optical=True)
    for _ in range(3):
        service.phase = "complete"
        service.sync_goto_request_id = None
        service.tracking_target_ra, service.tracking_target_dec = 110.0, 30.0
        service.tracking_guide_active_sent = guide_enabled
        clock[0] += 1
        pointing["current"]["metadata"]["last_solve_attempt"] = clock[0]
        service._tick_state_machine()
        assert service.phase == "native_tracking"
        assert all(c["type"] == "toggle_guide_correction" for c in commands(service))
        clock[0] += 2
        service._tick_state_machine()
        solve(rig)
        service._tick_state_machine()
        assert service.phase == "pifinder_goto"
        assert commands(service)[-1]["ra"] == 110.0


@pytest.mark.parametrize(
    "command",
    [
        {"type": "stop_movement"},
        {"type": "clear_tracking_target"},
        {"type": "suspend_tracking_guide"},
        {"type": "set_goto_method", "goto_method": "off"},
        {"type": "set_tracking_target", "ra": 120.0, "dec": 40.0},
    ],
)
def test_user_action_cancels_later_automatic_return(rig, command):
    service, clock, _, _ = rig
    start(rig)
    acknowledge(rig)
    service.handle_command(command)
    commands(service)
    clock[0] += 5
    solve(rig)
    service._tick_state_machine()
    assert not commands(service)
    assert not service.solve_fallback_armed


@pytest.mark.parametrize(
    "change", ["park", "tracking_off", "mode", "mount_off", "manual"]
)
def test_state_changes_cancel_recovery(rig, change):
    service, clock, mount, _ = rig
    start(rig)
    acknowledge(rig)
    if change == "park":
        mount["park_state"] = "Parked"
    elif change == "tracking_off":
        mount["tracking_enabled"] = False
    elif change == "mode":
        service.config_values["indi_goto_method"] = "indi_mount"
    elif change == "mount_off":
        service.config_values["mount_control"] = False
    else:
        mount.update(
            manual_motion_direction="north",
            manual_motion_origin="user",
            mount_motion_active=True,
        )
    clock[0] += 2
    solve(rig)
    service._tick_state_machine()
    assert not commands(service)
    assert not service.solve_fallback_armed


def test_sync_rejection_does_not_retry_on_camera_recovery(rig):
    service, clock, mount, _ = rig
    start(rig)
    mount["sync_goto"] = {"request_id": service.sync_goto_request_id, "state": "failed"}
    service._tick_state_machine()
    assert service.phase == "error"
    assert not service.solve_fallback_armed
    commands(service)
    clock[0] += 3
    solve(rig)
    service._tick_state_machine()
    assert not commands(service)


def test_recovery_below_altitude_limit_is_canceled(rig, monkeypatch):
    service, clock, _, _ = rig
    start(rig)
    acknowledge(rig)
    monkeypatch.setattr(service, "_tracking_target_altitude_deg", lambda: -5.0)
    clock[0] += 1
    solve(rig)
    service._tick_state_machine()
    assert not commands(service)
    assert not service.solve_fallback_armed


def test_outage_during_tracking_recovery_keeps_receipt_and_slew(rig):
    service, clock, mount, pointing = rig
    start(rig, optical=True)
    service.phase = "complete"
    service.tracking_recovery_state = "goto_wait"
    service.tracking_recovery_goto_sent_at = 999.0
    request_id = service.sync_goto_request_id
    mount["mount_motion_active"] = True
    clock[0] = 1001.0
    pointing["current"]["metadata"]["last_solve_attempt"] = clock[0]
    service._tick_state_machine()
    assert service.phase == "native_goto"
    assert service.sync_goto_request_id == request_id
    assert service.final_goto_sent_at == 999.0
    assert not commands(service)


def test_solver_stall_falls_back_despite_fresh_imu_timestamps(rig):
    service, clock, _, pointing = rig
    start(rig, optical=True)
    service.phase = "complete"
    service.sync_goto_request_id = None
    clock[0] += 13
    pointing["current"].update(source="pifinder_imu_estimate", timestamp=clock[0])
    service._tick_state_machine()
    assert service.phase == "native_tracking"
    assert not commands(service)


def test_recovery_after_guide_motion_uses_new_camera_solve(rig):
    service, clock, mount, pointing = rig
    start(rig, optical=True)
    service.sync_goto_request_id = None
    service._begin_pulse_align()
    commands(service)
    clock[0] += 1
    pointing["current"]["metadata"]["last_solve_attempt"] = clock[0]
    mount.update(mount_motion_active=True, manual_motion_origin="guide_correction")
    service._tick_state_machine()
    assert service.phase == "native_pending"
    assert commands(service) == [{"type": "toggle_guide_correction", "enabled": False}]
    mount["mount_motion_active"] = False
    clock[0] += 1
    solve(rig)
    service._tick_state_machine()
    clock[0] += 2
    solve(rig)
    service._tick_state_machine()
    assert service.phase == "pifinder_goto"
    assert commands(service)[-1]["origin"] == "pifinder_goto"


def test_no_imu_during_fine_alignment_can_use_existing_mount_frame(rig):
    service, clock, _, pointing = rig
    start(rig, optical=True)
    service.sync_goto_request_id = None
    service._begin_pulse_align()
    commands(service)
    clock[0] += 1
    pointing["current"]["metadata"]["last_solve_attempt"] = clock[0]
    pointing["imu"]["valid"] = False
    pointing["mount"] = {
        "valid": True,
        "aligned": True,
        "source": "mount",
        "timestamp": clock[0],
        "ra": 110.0,
        "dec": 29.8,
    }
    service._tick_state_machine()
    assert service.phase == "native_goto"
    assert commands(service)[-1]["pointing_source"] == "mount"


def test_stale_mount_status_cannot_authorize_recovery(rig):
    service, clock, mount, _ = rig
    start(rig)
    acknowledge(rig)
    mount["updated"] = 990.0
    clock[0] += 2
    solve(rig)
    service._tick_state_machine()
    assert not commands(service)
    assert service.phase == "native_tracking"


def test_new_target_supersedes_native_recovery(rig):
    service, clock, _, _ = rig
    start(rig)
    acknowledge(rig)
    clock[0] += 2
    solve(rig)
    service.handle_command({"type": "goto_target", "ra": 130.0, "dec": 40.0})
    assert commands(service)[-1]["ra"] == 130.0
    service._tick_state_machine()
    assert not commands(service)


def test_unavailable_queue_does_not_arm_a_native_goto(rig):
    service, _, _, _ = rig
    service.mountcontrol_queue = None
    service.handle_command({"type": "goto_target", "ra": 110.0, "dec": 30.0})
    assert service.phase == "error"
    assert not service.solve_fallback_armed


def test_tracking_off_at_native_arrival_wins_over_new_solve(rig):
    service, clock, mount, _ = rig
    start(rig)
    mount["sync_goto"] = {
        "request_id": service.sync_goto_request_id,
        "state": "goto_sent",
        "goto_sent_monotonic": clock[0],
    }
    service._tick_state_machine()
    clock[0] += 2
    service._tick_state_machine()
    mount["tracking_enabled"] = False
    clock[0] += 2
    solve(rig)
    service._tick_state_machine()
    assert not commands(service)
    assert not service.solve_fallback_armed


@pytest.mark.parametrize(
    "command",
    [
        {"type": "clear_tracking_target"},
        {"type": "suspend_tracking_guide"},
        {"type": "set_goto_method", "goto_method": "indi_mount"},
    ],
)
def test_cancel_normal_goto_cannot_rearm_after_outage(rig, command):
    service, clock, _, pointing = rig
    start(rig, optical=True)
    service.handle_command(command)
    commands(service)
    clock[0] += 2
    pointing["current"]["metadata"]["last_solve_attempt"] = clock[0]
    service._tick_state_machine()
    solve(rig)
    service._tick_state_machine()
    assert not commands(service)
    assert not service.solve_fallback_armed
