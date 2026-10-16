"""Manual approach timing, coordinate frames, cancellation and speed ownership."""

import pytest

from PiFinder import mountcontrol_indi as executor
from PiFinder.goto_manual_approach import (
    MANUAL_APPROACH_SETTLE_SECONDS,
    manual_approach_motion,
    manual_approach_pulse_entry,
)
from PiFinder.tracking_commands import PriorityMountQueue
from test_mountcontrol_indi import (
    DummyConnectedMount,
    DummySharedState,
    DummySolution,
    _slew_rate_ack,
)


pytestmark = pytest.mark.unit


@pytest.fixture
def approach(monkeypatch):
    clock = [1000.0]
    sample = [10.2, 20.03, 999.9]
    errors = [0.2, 0.03]
    monkeypatch.setattr(executor.time, "time", lambda: clock[0])
    monkeypatch.setattr(executor.time, "monotonic", lambda: clock[0])
    mount = DummyConnectedMount()
    mount.shared_state = DummySharedState(DummySolution(*sample))
    mount.slew_rate = 7
    monkeypatch.setattr(mount, "_current_plate_solve", lambda: tuple(sample))
    monkeypatch.setattr(
        executor.calc_utils, "pointing_axis_errors", lambda *args: tuple(errors)
    )
    monkeypatch.setattr(mount, "_indi_mount_is_busy", lambda: False)
    monkeypatch.setattr(mount, "_cached_tracking_enabled", lambda: True)
    monkeypatch.setattr(mount, "_confirm_tracking_state", lambda enabled: True)
    motions, pulses = [], []
    monkeypatch.setattr(
        mount,
        "_apply_indi_properties",
        lambda props, *args: motions.append(props) or True,
    )
    monkeypatch.setattr(mount, "_guide_pulse_supported", lambda: True)
    monkeypatch.setattr(mount, "_select_guide_rate_for_error", lambda error: True)
    monkeypatch.setattr(mount, "_apply_guide_pulse", lambda *args: pulses.append(args))
    mount.toggle_guide_correction(True, 10.0, 20.0, 1.0, manual_approach=True)
    return mount, clock, sample, errors, motions, pulses


def start_burst(mount):
    mount._check_guide_correction()
    assert mount._manual_approach["stage"] == "waiting_rate"
    _slew_rate_ack(mount, mount._manual_approach["rate"])
    mount._check_guide_correction()
    assert mount._manual_approach["stage"] == "moving"


def test_burst_requires_speed_ack_then_stops_and_restores_original_rate(approach):
    mount, clock, sample, errors, motions, pulses = approach
    mount._check_guide_correction()
    assert not motions and not pulses
    assert mount.slew_rate == 7
    assert mount.client.switches[-1][1:] == ("TELESCOPE_SLEW_RATE", "6")
    _slew_rate_ack(mount, 4)
    mount._check_guide_correction()
    assert not motions
    _slew_rate_ack(mount, 6)
    mount._check_guide_correction()
    assert "MOTION_WEST=On" in motions[-1][0]
    assert mount._manual_motion_origin == "goto_approach"
    assert mount._last_user_motion_started_wall == 0
    assert 0.3 <= mount._manual_motion_deadline - clock[0] <= 1.2 + 1e-9
    clock[0] = mount._manual_motion_deadline
    mount._check_manual_motion_deadline()
    assert mount._manual_motion_direction is None
    assert mount._manual_approach is None
    assert mount.client.switches[-1][1:] == ("TELESCOPE_SLEW_RATE", "7")
    assert mount.slew_rate == 7
    assert mount._last_user_motion_stopped_wall == 0
    before = len(motions)
    mount._check_guide_correction()
    assert len(motions) == before and not pulses
    clock[0] += MANUAL_APPROACH_SETTLE_SECONDS + 0.1
    sample[:] = [10.02, 20.01, clock[0]]
    errors[:] = [0.02, 0.01]
    mount._check_guide_correction()
    assert not mount._guide_manual_approach
    assert pulses


def test_pulse_capacity_edge_stays_in_manual_until_well_inside(approach):
    mount, clock, sample, errors, _motions, pulses = approach
    sample[:] = [10.04, 20.0, clock[0]]
    errors[:] = [0.04, 0.0]
    start_burst(mount)
    assert not pulses
    assert mount._manual_approach["rate"] == 5


@pytest.mark.parametrize("action", ["user_move", "stop", "disable", "new_goto", "rate"])
def test_user_takeover_stops_approach_and_restores_speed_first(
    approach, monkeypatch, action
):
    mount, _clock, _sample, _errors, _motions, pulses = approach
    start_burst(mount)
    events = []
    original_switch = mount.client.set_switch

    def set_switch(device, name, element):
        events.append((name, element))
        return original_switch(device, name, element)

    monkeypatch.setattr(mount.client, "set_switch", set_switch)
    monkeypatch.setattr(
        mount,
        "_apply_indi_properties",
        lambda props, *args: events.append(tuple(props)) or True,
    )
    if action == "user_move":
        assert mount.manual_move("south")
        assert mount._manual_motion_origin == "user"
        restore = events.index(("TELESCOPE_SLEW_RATE", "7"))
        move = next(
            index
            for index, event in enumerate(events)
            if any("MOTION_SOUTH=On" in str(value) for value in event)
        )
        assert restore < move
    elif action == "stop":
        mount.handle_command({"type": "stop_movement", "stop_tracking": True})
    elif action == "disable":
        mount.toggle_guide_correction(False)
    elif action == "new_goto":
        monkeypatch.setattr(mount, "goto_target", lambda *args, **kwargs: True)
        mount.handle_command({"type": "goto_target", "ra": 30, "dec": 10})
    else:
        mount.set_slew_rate(6)
    assert mount._manual_approach is None
    assert ("TELESCOPE_SLEW_RATE", "7") in events
    assert mount.slew_rate == (6 if action == "rate" else 7)
    assert not pulses


def test_failed_speed_ack_never_moves_and_restores_user_rate(approach):
    mount, clock, _sample, _errors, motions, pulses = approach
    mount._check_guide_correction()
    clock[0] += 3.1
    mount._check_guide_correction()
    assert not motions and not pulses
    assert not mount._guide_correction_enabled
    assert mount._guide_correction_mode == "failed"
    assert mount.client.switches[-1][1:] == ("TELESCOPE_SLEW_RATE", "7")


def test_failed_axis_stop_does_not_restore_speed_under_motion(approach, monkeypatch):
    mount, clock, _sample, _errors, _motions, _pulses = approach
    start_burst(mount)
    monkeypatch.setattr(mount, "_apply_indi_properties", lambda *args: False)
    clock[0] = mount._manual_motion_deadline
    mount._check_manual_motion_deadline()
    assert mount._manual_motion_origin == "goto_approach"
    assert mount._manual_approach is not None
    assert mount.client.switches[-1][1:] == ("TELESCOPE_SLEW_RATE", "6")


@pytest.mark.parametrize(
    "mount_type,expected", [("Alt/Az", (720, 108)), ("Equatorial", (-720, 108))]
)
def test_manual_axis_frame_is_distinct_from_equatorial_pulse_frame(
    approach, mount_type, expected
):
    mount = approach[0]
    mount._guide_mount_type = mount_type
    assert mount._manual_approach_errors(10, 20, 11, 21) == pytest.approx(expected)


@pytest.mark.parametrize("accuracy,entry", [(0.1, 0.75), (1, 1.5), (2, 3), (12, 15)])
def test_handoff_has_room_for_minimum_manual_burst(accuracy, entry):
    assert manual_approach_pulse_entry(accuracy) == entry


@pytest.mark.parametrize("direction", [-1, 1])
@pytest.mark.parametrize(
    "arcmin,expected_rate,expected_multiplier",
    [
        (0.8, 4, 4),
        (1.6, 4, 4),
        (2.4, 5, 8),
        (4.17, 5, 8),
        (6, 6, 20),
        (12, 6, 20),
        (14, 7, 48),
        (45, 7, 48),
    ],
)
def test_distance_selects_faster_rate_without_spending_stopping_margin(
    direction, arcmin, expected_rate, expected_multiplier
):
    rate, multiplier, duration = manual_approach_motion(direction * arcmin * 60)
    assert (rate, multiplier) == (expected_rate, expected_multiplier)
    assert 0.3 <= duration <= 1.2
    assert duration * multiplier * 15.041 <= arcmin * 60 * 0.6 + 1e-9
    if rate != 4:
        assert duration >= 0.6


@pytest.mark.parametrize(
    "invalid", ["lost", "old", "future", "timestamp", "nan", "frame"]
)
def test_no_movement_with_invalid_observation_after_speed_ack(
    approach, monkeypatch, invalid
):
    mount, clock, sample, _errors, motions, pulses = approach
    mount._check_guide_correction()
    _slew_rate_ack(mount, mount._manual_approach["rate"])
    if invalid == "lost":
        monkeypatch.setattr(mount, "_current_plate_solve", lambda: None)
    elif invalid == "old":
        sample[2] = clock[0] - 30
    elif invalid == "future":
        sample[2] = clock[0] + 30
    elif invalid == "timestamp":
        sample[2] = None
    elif invalid == "nan":
        sample[0] = float("nan")
    else:
        monkeypatch.setattr(mount, "_manual_approach_errors", lambda *args: None)
    mount._check_guide_correction()
    assert not motions and not pulses
    assert mount._manual_approach is None
    assert mount.client.switches[-1][1:] == ("TELESCOPE_SLEW_RATE", "7")


def test_cancellation_epoch_stops_even_before_user_command_is_dequeued(approach):
    mount = approach[0]
    queue = PriorityMountQueue()
    mount.mount_queue = queue
    try:
        start_burst(mount)
        queue.put({"type": "manual_movement", "direction": "south"})
        mount._check_guide_correction()
        assert mount._manual_motion_direction is None
        assert mount._manual_approach is None
        assert not mount._guide_correction_enabled
        assert mount.client.switches[-1][1:] == ("TELESCOPE_SLEW_RATE", "7")
    finally:
        queue.queue.close()
        queue.queue.join_thread()


def test_no_progress_stops_after_four_measured_bursts(approach):
    mount, clock, sample, _errors, _motions, pulses = approach
    for _ in range(4):
        start_burst(mount)
        clock[0] = mount._manual_motion_deadline
        mount._check_manual_motion_deadline()
        clock[0] += 1
        sample[2] = clock[0]
    mount._check_guide_correction()
    assert mount._guide_correction_mode == "failed"
    assert not mount._guide_correction_enabled
    assert mount._manual_approach is None
    assert not pulses


def test_handoff_during_speed_selection_waits_for_restoration_boundary(approach):
    mount, clock, sample, errors, motions, pulses = approach
    mount._check_guide_correction()
    _slew_rate_ack(mount, mount._manual_approach["rate"])
    clock[0] += 0.1
    sample[:] = [10.02, 20.01, clock[0]]
    errors[:] = [0.02, 0.01]
    mount._check_guide_correction()
    assert mount._manual_approach is None
    assert not motions and not pulses
    assert not mount._guide_manual_approach
    mount._check_guide_correction()
    assert not pulses
    clock[0] += 0.6
    sample[2] = clock[0]
    mount._check_guide_correction()
    assert pulses


def test_user_takeover_waits_if_original_speed_cannot_be_restored(
    approach, monkeypatch
):
    mount, _clock, _sample, _errors, motions, _pulses = approach
    start_burst(mount)
    monkeypatch.setattr(mount, "_reassert_slew_rate", lambda: False)
    assert not mount.manual_move("south")
    assert mount._manual_motion_direction is None
    assert mount._manual_approach["stage"] == "restoring"
    assert not any("MOTION_SOUTH=On" in prop for batch in motions for prop in batch)
    monkeypatch.setattr(mount, "_reassert_slew_rate", lambda: True)
    mount._check_guide_correction()
    assert mount._manual_approach is None


def test_disconnect_stops_approach_before_restoring_and_closing(approach, monkeypatch):
    mount = approach[0]
    start_burst(mount)
    closed = []
    monkeypatch.setattr(
        mount.client, "disconnectServer", lambda: closed.append(True), raising=False
    )
    mount.disconnect()
    assert closed
    assert mount._manual_motion_direction is None
    assert mount._manual_approach is None
    assert mount.client.switches[-1][1:] == ("TELESCOPE_SLEW_RATE", "7")
