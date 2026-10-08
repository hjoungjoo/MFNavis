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


@pytest.mark.parametrize("source", ["solve", "pifinder_imu_estimate"])
def test_stationary_anchored_imu_remains_usable_without_fresh_camera_solve(rig, source):
    service, _, _, pointing = rig
    service.config_values["indi_goto_allow_unaligned_imu"] = False
    pointing["solved"] = {
        **pointing["imu"],
        "ra": 105.0,
        "source": source,
        "timestamp": 700.0,
        "metadata": {"has_plate_anchor": True, "imu_observed_time": 1000.0},
    }
    command = start(rig)
    assert command["sync_ra"] == 105.0
    assert command["pointing_source"] == "pifinder_imu_estimate"
    assert service.phase == "native_goto"
    assert pointing["solved"]["timestamp"] == 700.0
    assert not service._is_recent_solve(pointing["solved"])
    acknowledge(rig)
    assert service.phase == "native_tracking"
    assert not commands(service)  # An IMU observation is not optical recovery.


@pytest.mark.parametrize("observed", [None, 990.0, 1001.0, float("nan")])
def test_stale_anchored_coordinate_requires_recent_integrator_observation(
    rig, observed
):
    service, _, _, pointing = rig
    service.config_values["indi_goto_allow_unaligned_imu"] = False
    pointing["solved"] = {
        **pointing["imu"],
        "source": "pifinder_imu_estimate",
        "timestamp": 700.0,
        "metadata": {"has_plate_anchor": True, "imu_observed_time": observed},
    }
    service.handle_command({"type": "goto_target", "ra": 110.0, "dec": 30.0})
    assert not commands(service)
    assert service.phase == "pifinder_goto_blocked"
    assert not service.solve_fallback_armed


def test_initial_wait_retries_imu_when_observation_arrives(rig):
    service, clock, _, pointing = rig
    service.config_values["indi_goto_allow_unaligned_imu"] = False
    solve(rig)
    pointing["current"].update(source="pifinder_imu_estimate", timestamp=700.0)
    pointing["current"]["metadata"]["has_plate_anchor"] = True
    service.handle_command({"type": "goto_target", "ra": 110.0, "dec": 30.0})
    assert not commands(service)
    assert service.initial_goto_deadline is not None
    clock[0] += 1
    pointing["current"]["metadata"]["imu_observed_time"] = clock[0]
    service._tick_state_machine()
    assert commands(service)[-1]["origin"] == "imu_goto_fallback"
    assert service.phase == "native_goto"
    assert service.initial_goto_deadline is None


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


def test_fresh_solve_uses_arrival_error_for_fine_alignment(rig):
    service, clock, _, _ = rig
    start(rig)
    acknowledge(rig)
    clock[0] += 1
    solve(rig, dec=30.2)
    service._tick_state_machine()
    cmd = commands(service)[-1]
    assert service.phase == "pifinder_pulse_align"
    assert cmd["type"] == "toggle_guide_correction"
    assert "manual_approach" not in cmd
    assert "manual_fallback" not in cmd
    assert service.correction_count == 1
    solve(rig)
    service._tick_state_machine()
    assert service.phase == "complete"
    assert commands(service)[-1]["origin"] == "pifinder_final_sync"


def test_recovered_solve_keeps_goto_batch_count(rig):
    service, clock, _, _ = rig
    start(rig)
    acknowledge(rig)
    service.correction_count = 4
    clock[0] += 1
    solve(rig, dec=32.0)
    service._tick_state_machine()
    assert service.phase == "pifinder_goto"
    assert service.correction_count == 5
    cmd = commands(service)[-1]
    assert cmd["type"] == "sync_and_goto"
    assert cmd["sync_dec"] == 32.0
    assert cmd["dec"] == 30.0


def test_recovered_solve_at_batch_limit_waits_instead_of_slewing(rig):
    service, clock, _, _ = rig
    start(rig)
    acknowledge(rig)
    service.correction_count = service._max_gotos()
    clock[0] += 1
    solve(rig, dec=32.0)
    service._tick_state_machine()
    assert not commands(service)
    assert service.last_action == "waiting for fresh solve before retry"
    assert service.solve_anchor_required_after_wall > clock[0]


def test_solve_recovery_does_not_reenable_unconverged_pulses(rig):
    service, clock, _, _ = rig
    start(rig)
    acknowledge(rig)
    service.pulse_alignment_unreliable = True
    clock[0] += 1
    solve(rig, dec=30.2)
    service._tick_state_machine()
    assert service.pulse_alignment_unreliable
    assert service.phase == "pifinder_pulse_align"
    assert not commands(service)


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
    assert commands(service)[-1]["origin"] == "pifinder_final_sync"


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
    assert not any(c["type"] == "sync_and_goto" for c in cmd)
    assert service.phase == "native_pending"
    clock[0] += mod.MFNAVIS_SOLVE_OUTAGE_GRACE_SECONDS + 0.1
    service._tick_state_machine()
    cmd = commands(service)
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
        assert service.phase == "complete"
        recovered_commands = commands(service)
        assert not recovered_commands  # Tracking resumes without another Sync.
        assert (service.tracking_target_ra, service.tracking_target_dec) == (
            110.0,
            30.0,
        )


@pytest.mark.parametrize("diverged", [False, True])
def test_tracking_outage_preserves_recovery_budget_and_completed_phase(rig, diverged):
    service, clock, _, pointing = rig
    start(rig, optical=True)
    service.phase = "complete"
    service.final_sync_sent = True
    service.tracking_recovery_attempts = 4
    service.tracking_guide_recovery_count = 4
    service.pulse_alignment_unreliable = diverged
    service.tracking_target_ra, service.tracking_target_dec = 110.0, 30.0
    clock[0] += 1
    pointing["current"]["metadata"]["last_solve_attempt"] = clock[0]
    service._tick_state_machine()
    commands(service)
    clock[0] += 2
    solve(rig, dec=30.08)  # Outside arrival accuracy, inside tracking pulse range.
    service._tick_state_machine()
    assert service.phase == "complete"
    assert service.tracking_recovery_attempts == 4
    assert service.tracking_guide_recovery_count == 4
    assert service.pulse_alignment_unreliable is diverged
    assert service.final_sync_sent
    assert not commands(service)


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
    if command["type"] == "set_tracking_target":
        assert service.solve_fallback_armed
        assert (service.active_target_ra, service.active_target_dec) == (120.0, 40.0)
    else:
        assert not service.solve_fallback_armed


@pytest.mark.parametrize("change", ["park", "mode", "mount_off", "manual"])
def test_state_changes_cancel_recovery(rig, change):
    service, clock, mount, _ = rig
    start(rig)
    acknowledge(rig)
    if change == "park":
        mount["park_state"] = "Parked"
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


@pytest.mark.parametrize("tracking_enabled", [True, False])
def test_outage_during_tracking_recovery_keeps_receipt_and_slew(rig, tracking_enabled):
    service, clock, mount, pointing = rig
    start(rig, optical=True)
    service.phase = "complete"
    service.tracking_recovery_state = "goto_wait"
    service.tracking_recovery_goto_sent_at = 999.0
    request_id = service.sync_goto_request_id
    mount["mount_motion_active"] = True
    mount["tracking_enabled"] = tracking_enabled
    clock[0] = 1001.0
    pointing["current"]["metadata"]["last_solve_attempt"] = clock[0]
    service._tick_state_machine()
    assert service.phase == "native_goto"
    assert service.sync_goto_request_id == request_id
    assert service.final_goto_sent_at == 999.0
    assert not commands(service)


def test_recovery_slew_tracking_off_keeps_target_and_resumes_guide(rig):
    service, clock, mount, _ = rig
    start(rig, optical=True)
    service.config_values["indi_tracking_guide_enabled"] = True
    service.phase = "complete"
    service.tracking_target_ra, service.tracking_target_dec = 110.0, 30.0
    service._begin_tracking_recovery_goto(110.0, 30.1)
    commands(service)
    mount.update(
        tracking_enabled=False,
        mount_motion_active=True,
        sync_goto={
            "request_id": service.sync_goto_request_id,
            "state": "goto_sent",
            "goto_sent_monotonic": clock[0],
        },
    )
    clock[0] += 2
    solve(rig)
    service._tick_state_machine()
    service._tick_tracking_guide()
    assert service.solve_fallback_armed
    assert (service.tracking_target_ra, service.tracking_target_dec) == (110.0, 30.0)
    assert service.tracking_guide_state == "recovering_goto"
    assert not commands(service)

    mount.update(tracking_enabled=True, mount_motion_active=False)
    for _ in range(8):
        clock[0] += 2
        solve(rig)
        service._tick_state_machine()
        service._tick_tracking_guide()
    assert service.phase == "complete"
    assert service.tracking_recovery_state == "idle"
    assert service.tracking_guide_state == "enabled"
    assert service.tracking_guide_active_sent
    assert any(
        c["type"] == "toggle_guide_correction" and c["enabled"]
        for c in commands(service)
    )


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


@pytest.mark.parametrize("camera_recovers", [True, False])
def test_timed_pulse_outage_waits_for_completion_and_new_exposures(
    rig, camera_recovers
):
    service, clock, mount, pointing = rig
    start(rig, optical=True)
    service.sync_goto_request_id = None
    service._begin_pulse_align()
    commands(service)
    clock[0] = 1001.0
    pointing["current"]["metadata"]["last_solve_attempt"] = clock[0]
    mount.update(mount_motion_active=False, guide_pulse_until_wall=1003.5)
    service._tick_state_machine()
    assert service.phase == "native_pending"
    assert commands(service) == [{"type": "toggle_guide_correction", "enabled": False}]
    clock[0] = 1002.0
    service._tick_state_machine()
    assert not commands(service)
    clock[0] = 1004.0
    service._tick_state_machine()
    assert not commands(service)
    assert service.tracking_target_ra == 110.0

    if camera_recovers:
        solve(rig)
        service._tick_state_machine()
        clock[0] += 2
        solve(rig)
        service._tick_state_machine()
        assert service.phase == "complete"
        assert not any(c["type"] == "sync_and_goto" for c in commands(service))
    else:
        clock[0] = 1003.5 + mod.MFNAVIS_SOLVE_OUTAGE_GRACE_SECONDS + 0.1
        pointing["imu"]["timestamp"] = clock[0]
        service._tick_state_machine()
        assert service.phase == "native_goto"
        assert commands(service)[-1]["type"] == "sync_and_goto"


def test_recovery_after_guide_pulse_uses_new_camera_solve(rig):
    service, clock, mount, pointing = rig
    start(rig, optical=True)
    service.sync_goto_request_id = None
    service._begin_pulse_align()
    commands(service)
    clock[0] += 1
    pointing["current"]["metadata"]["last_solve_attempt"] = clock[0]
    mount.update(guide_pulse_until_wall=clock[0] + 0.5)
    service._tick_state_machine()
    assert service.phase == "native_pending"
    assert commands(service) == [{"type": "toggle_guide_correction", "enabled": False}]
    clock[0] += 1
    solve(rig)
    service._tick_state_machine()
    clock[0] += 2
    solve(rig)
    service._tick_state_machine()
    assert service.phase == "complete"
    assert commands(service)[-1]["origin"] == "pifinder_final_sync"


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
    assert service.phase == "native_pending"
    clock[0] += mod.MFNAVIS_SOLVE_OUTAGE_GRACE_SECONDS + 0.1
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


def test_tracking_off_at_native_arrival_retains_target_for_resume(rig):
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
    assert service.solve_fallback_armed
    assert service.resume_pending
    assert service.phase == "waiting_solve_resume"


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


@pytest.mark.parametrize("upper,accepted", [(80.0, False), (85.0, True)])
def test_native_sync_uses_live_indi_altitude_limit_not_a_fixed_80(rig, upper, accepted):
    service, _, mount, pointing = rig
    pointing["imu"]["alt"] = 81.4
    mount.update(alignment_min_altitude=-10.0, alignment_max_altitude=upper)
    service.handle_command({"type": "goto_target", "ra": 110.0, "dec": 30.0})
    assert bool(commands(service)) is accepted
    if not accepted:
        assert service.phase == "error"
        assert "81.4" in service.wait_reason
        assert "80.0" in service.wait_reason
        assert not service.solve_fallback_armed


def test_mount_limit_change_applies_to_next_goto_without_restart(rig):
    service, _, mount, pointing = rig
    pointing["imu"]["alt"] = 81.4
    mount.update(alignment_min_altitude=-10.0, alignment_max_altitude=80.0)
    service.handle_command({"type": "goto_target", "ra": 110.0, "dec": 30.0})
    assert not commands(service)
    mount["alignment_max_altitude"] = 85.0
    service.handle_command({"type": "goto_target", "ra": 110.0, "dec": 30.0})
    assert commands(service)[-1]["type"] == "sync_and_goto"


def test_ping_and_unknown_command_do_not_cancel_accepted_tracking(rig):
    service, _, _, _ = rig
    start(rig)
    before = service.phase
    service.handle_command({"type": "ping"})
    service.handle_command({"type": "unknown_status_request"})
    assert service.phase == before
    assert service.solve_fallback_armed
    assert service.active_target_ra == 110.0
    assert not commands(service)


def test_temporary_tracking_off_resumes_on_fresh_solve_without_user_stop(rig):
    service, clock, mount, _pointing = rig
    start(rig)
    acknowledge(rig)
    mount["tracking_enabled"] = False
    service._tick_state_machine()
    assert service.resume_pending
    assert service.active_target_ra == 110.0
    service._tick_state_machine()
    assert not commands(service)  # No fresh optical solve yet.
    clock[0] += 1
    solve(rig, ra=110.02)
    service._tick_state_machine()
    assert commands(service) == [{"type": "set_tracking", "enabled": True}]
    mount["tracking_enabled"] = True
    service._tick_state_machine()
    assert not service.resume_pending
    assert service.solve_fallback_armed
    assert service.phase != "idle"


def test_restart_restores_target_but_waits_for_post_start_solve(
    rig, monkeypatch, tmp_path
):
    import json

    service, clock, _mount, _pointing = rig
    saved = tmp_path / "guide.json"
    saved.write_text(json.dumps({"resume_target": {"ra": 110.0, "dec": 30.0}}))
    monkeypatch.setattr(mod, "STATUS_FILE", saved)
    service._restore_tracking_intent()
    assert service.resume_pending
    solve(rig, timestamp=service.started_at)
    service._tick_state_machine()
    assert not commands(service)
    clock[0] += 1
    solve(rig, ra=110.02)
    service._tick_state_machine()
    assert not service.resume_pending
    assert service.solve_fallback_armed
    assert service.active_target_ra == 110.0


def test_explicit_stop_clears_persisted_resume_intent(rig, monkeypatch, tmp_path):
    import json

    service, clock, _, _ = rig
    saved = tmp_path / "guide.json"
    monkeypatch.setattr(mod, "STATUS_FILE", saved)
    start(rig)
    service.resume_pending = True
    # Exercise the real immediate status write used by the explicit Stop.
    monkeypatch.setattr(
        service,
        "_write_status",
        lambda **kw: saved.write_text(json.dumps(service._status_payload())),
    )
    service.handle_command({"type": "stop_movement"})
    assert json.loads(saved.read_text())["resume_target"] is None
    assert not service.resume_pending
    commands(service)
    service._restore_tracking_intent()
    clock[0] += 1
    solve(rig)
    service._tick_state_machine()
    assert service.phase == "idle"
    assert not commands(service)


@pytest.mark.parametrize("blocked", ["parked", "moving", "unavailable", "below_limit"])
def test_restored_target_waits_while_mount_or_altitude_blocks_motion(
    rig, monkeypatch, blocked
):
    service, clock, mount, _ = rig
    service.active_target_ra = service.tracking_target_ra = 110.0
    service.active_target_dec = service.tracking_target_dec = 30.0
    service.resume_pending = True
    clock[0] += 1
    solve(rig)
    if blocked == "parked":
        mount["park_state"] = "Parked"
    elif blocked == "moving":
        mount["mount_motion_active"] = True
    elif blocked == "unavailable":
        mount["available"] = False
    else:
        monkeypatch.setattr(service, "_tracking_target_altitude_deg", lambda: 0.0)
    service._tick_state_machine()
    assert service.resume_pending
    assert not commands(service)


def test_manual_retarget_is_saved_as_new_resume_target(rig):
    service, _, _, _ = rig
    service.handle_command(
        {"type": "set_tracking_target", "ra": 111, "dec": 31, "manual_retarget": True}
    )
    assert service.service_state == "running"
    assert service._status_payload()["resume_target"] == {"ra": 111, "dec": 31}


def test_explicit_mount_tracking_off_does_not_get_automatically_reenabled(rig):
    service, clock, mount, _ = rig
    start(rig)
    acknowledge(rig)
    clock[0] += 1
    mount.update(tracking_enabled=False, last_user_tracking_stopped_wall=clock[0])
    solve(rig)
    service._tick_state_machine()
    assert not service.resume_pending
    assert not service.solve_fallback_armed
    assert service.active_target_ra is None
    commands(service)
    service._tick_state_machine()
    assert not commands(service)
