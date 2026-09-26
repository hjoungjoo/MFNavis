from __future__ import annotations
import json
from datetime import datetime, timezone
import time
from multiprocessing import Queue
from types import SimpleNamespace

import pytest

from PiFinder import sys_utils
from PiFinder import indi_backlash_calibration as ibc
from PiFinder import mountcontrol_indi as mci
from PiFinder.mountcontrol_indi import (
    MountControlIndi,
    radec_separation_arcmin,
    shortest_ra_delta_deg,
)


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated_motion_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(mci.config.utils, "data_dir", tmp_path)
    monkeypatch.setattr(mci.config.utils, "runtime_dir", tmp_path)
    monkeypatch.setattr(mci, "STATUS_FILE", tmp_path / "mount_control_status.json")
    monkeypatch.setattr(
        sys_utils,
        "get_indi_profile_drivers",
        lambda **kwargs: {"profile": "", "drivers": []},
    )


class DummyMountControl(MountControlIndi):
    def __init__(self, shared_state=None):
        super().__init__(Queue(), Queue(), shared_state)
        self.applied_properties = []
        self.sync_calls = []
        self.goto_calls = []
        self.location_sync_calls = []
        self.mount_align_start_calls = []
        self.mount_align_accept_calls = []
        self.events = []

    def _apply_indi_properties(
        self,
        properties,
        success_state,
        success_message,
        failure_state,
    ):
        self.applied_properties.append(list(properties))
        return {"ok": True}

    def _apply_indi_backlash(self, backlash_ra, backlash_de):
        self.applied_properties.append(
            [
                f"LX200 OnStepX.Backlash.Backlash RA={backlash_ra}",
                f"LX200 OnStepX.Backlash.Backlash DEC={backlash_de}",
            ]
        )
        return {"ok": True}

    def sync_mount(self, ra_deg, dec_deg, sync_context=None):
        self.events.append(("sync_mount", ra_deg, dec_deg))
        self.sync_calls.append((ra_deg, dec_deg))
        return True

    def _sync_multipoint_location_time(self, session):
        self.events.append(("sync_location_time", True, True))
        self.location_sync_calls.append((True, True))
        session["location_time_synced"] = True
        return True

    def _read_current_position(self):
        return (10.0, 20.0)

    def _current_pifinder_pointing_for_align(self):
        return ("test", 10.0, 20.0)

    def start_mount_alignment_session(self, points):
        self.events.append(("start_mount_alignment_session", points))
        self.mount_align_start_calls.append(points)
        return True

    def accept_mount_alignment_point(self):
        self.events.append(("accept_mount_alignment_point",))
        self.mount_align_accept_calls.append(True)
        return True

    def _radec_to_altaz(self, ra_deg, dec_deg):
        return (45.0, 180.0)

    def goto_target(
        self,
        ra_deg,
        dec_deg,
        refine_after_goto=False,
        refine_accuracy_arcmin=None,
    ):
        self.goto_calls.append(
            (ra_deg, dec_deg, refine_after_goto, refine_accuracy_arcmin)
        )
        return True


class DummyCommandQueue:
    def __init__(self):
        self.commands = []

    def put(self, command):
        self.commands.append(command)


class DummyPointing:
    def __init__(self, ra, dec):
        self.RA = ra
        self.Dec = dec


class DummyAligned:
    def __init__(self, ra, dec):
        self.solve = DummyPointing(ra, dec)


class DummyPointingMatrix:
    def __init__(self, ra, dec):
        self.aligned = DummyAligned(ra, dec)


class DummySolution:
    def __init__(self, ra, dec, solve_time):
        self.pointing = DummyPointingMatrix(ra, dec)
        self.last_solve_success = solve_time


class DummySharedState:
    def __init__(self, solution):
        self._solution = solution

    def solution(self):
        return self._solution

    def location(self):
        return DummyLocation()

    def datetime(self):
        return datetime(2026, 9, 14, 13, tzinfo=timezone.utc)


class DummyLocation:
    lock = True
    lat = 37.52704
    lon = 127.10936
    altitude = 30


class DummySharedStateWithLocation:
    def location(self):
        return DummyLocation()

    def datetime(self):
        return "2026-07-01T14:45:00+00:00"


class DummyConnectedMount(MountControlIndi):
    def __init__(self):
        super().__init__(Queue(), Queue(), None)
        self.client = DummyIndiClient()
        self.device = DummyIndiDevice()
        self.connected = True
        self.statuses = []
        self.accept_goto_target = True
        self.auto_ack_guide = True

    def _set_guide_rate(self, rate):
        accepted = super()._set_guide_rate(rate)
        if accepted and self.auto_ack_guide:
            self.receive_sync_property(
                "GUIDE_RATE",
                "ok",
                {"GUIDE_RATE_WE": rate, "GUIDE_RATE_NS": rate},
                self._client_generation,
            )
        return accepted

    def _write_controller_status(self, state, message="", **extra):
        self.statuses.append((state, message, self._status_fields(state, **extra)))

    def _goto_target_accepted(self, ra_deg, dec_deg):
        return self.accept_goto_target


class DummyIndiDevice:
    def getDeviceName(self):
        return "LX200 OnStep"

    def isConnected(self):
        return True


class DummyIndiClient:
    def __init__(self):
        self.switches = []
        self.numbers = []

    def isServerConnected(self):
        return True

    def set_switch(self, device, property_name, element_name):
        self.switches.append((device.getDeviceName(), property_name, element_name))
        return True

    def set_number(self, device, property_name, values):
        self.numbers.append((device.getDeviceName(), property_name, dict(values)))
        return True


def _verified_goto_test_mount(monkeypatch):
    mount = DummyConnectedMount()
    mount.moves = []
    monkeypatch.setattr(
        mount, "goto_target", lambda ra, dec: mount.moves.append((ra, dec)) or True
    )
    command = {
        "type": "sync_and_goto",
        "request_id": "first",
        "sync_ra": 132.0,
        "sync_dec": 49.5,
        "ra": 140.0,
        "dec": 45.0,
        "origin": "pifinder_goto",
    }
    return mount, command


def _sync_ack(mount, name, values, state="ok", generation=None):
    mount.receive_sync_property(
        name,
        state,
        values,
        mount._client_generation if generation is None else generation,
    )
    mount._check_pending_sync_goto()


def test_sync_goto_requires_new_mode_coordinate_and_slew_ack(monkeypatch):
    mount, command = _verified_goto_test_mount(monkeypatch)
    # Previously cached successful values cannot satisfy this new request.
    _sync_ack(mount, "ON_COORD_SET", {"SYNC": True})
    _sync_ack(mount, "EQUATORIAL_EOD_COORD", {"RA": 8.8, "DEC": 49.5})
    assert mount.begin_sync_and_goto(command)
    mount._check_pending_sync_goto()
    assert mount.client.numbers == []
    _sync_ack(mount, "ON_COORD_SET", {"SYNC": True}, state="busy")
    _sync_ack(mount, "ON_COORD_SET", {"SLEW": True})
    assert mount.client.numbers == []
    _sync_ack(mount, "ON_COORD_SET", {"SYNC": True})
    assert len(mount.client.numbers) == 1
    assert mount.moves == []
    _sync_ack(mount, "EQUATORIAL_EOD_COORD", {"RA": 8.8, "DEC": 49.5}, state="busy")
    assert mount._coordinate_sync is None
    _sync_ack(mount, "EQUATORIAL_EOD_COORD", {"RA": 1.0, "DEC": 49.5})
    assert mount.moves == []
    assert mount._coordinate_sync is None
    _sync_ack(mount, "EQUATORIAL_EOD_COORD", {"RA": 8.8, "DEC": 49.5})
    assert mount._coordinate_sync["synced"] is True
    assert mount._sync_goto_status["verified_error_arcmin"] < 0.001
    assert mount.moves == []
    _sync_ack(mount, "ON_COORD_SET", {"SLEW": True})
    assert mount.moves == [(140.0, 45.0)]
    assert mount._sync_goto_status["state"] == "goto_sent"
    mount._check_pending_sync_goto()
    assert len(mount.moves) == 1


@pytest.mark.parametrize(
    "failure", ["alert", "timeout", "disconnect", "stop", "manual", "exception"]
)
def test_pending_sync_failure_or_cancel_never_sends_target(monkeypatch, failure):
    mount, command = _verified_goto_test_mount(monkeypatch)
    assert mount.begin_sync_and_goto(command)
    _sync_ack(mount, "ON_COORD_SET", {"SYNC": True})
    if failure == "alert":
        _sync_ack(
            mount, "EQUATORIAL_EOD_COORD", {"RA": 8.8, "DEC": 49.5}, state="alert"
        )
    elif failure == "timeout":
        mount._pending_sync_goto["deadline"] = 0.0
        mount._check_pending_sync_goto()
    elif failure == "disconnect":
        mount.mark_disconnected("test")
    elif failure in {"stop", "manual"}:
        monkeypatch.setattr(mount, "_apply_indi_properties", lambda *args: True)
        if failure == "stop":
            mount.stop_mount()
        else:
            mount.manual_move("north")
    else:
        monkeypatch.setattr(
            mount,
            "_record_coordinate_sync",
            lambda *args: (_ for _ in ()).throw(RuntimeError("test")),
        )
        _sync_ack(mount, "EQUATORIAL_EOD_COORD", {"RA": 8.8, "DEC": 49.5})
    assert mount._pending_sync_goto is None
    assert mount._sync_goto_status["state"] == "failed"
    _sync_ack(mount, "EQUATORIAL_EOD_COORD", {"RA": 8.8, "DEC": 49.5})
    _sync_ack(mount, "ON_COORD_SET", {"SLEW": True})
    assert mount.moves == []


def test_sync_goto_initial_send_exception_cancels_late_ack(monkeypatch):
    mount, command = _verified_goto_test_mount(monkeypatch)

    def failing_send(*args):
        raise RuntimeError("send failed")

    monkeypatch.setattr(mount.client, "set_switch", failing_send)
    assert not mount.begin_sync_and_goto(command)
    _sync_ack(mount, "ON_COORD_SET", {"SYNC": True})
    _sync_ack(mount, "EQUATORIAL_EOD_COORD", {"RA": 8.8, "DEC": 49.5})
    _sync_ack(mount, "ON_COORD_SET", {"SLEW": True})
    assert mount._pending_sync_goto is None
    assert mount._sync_goto_status["state"] == "failed"
    assert mount.moves == []


def test_sync_goto_stop_after_coordinates_verified_cancels_move(monkeypatch):
    mount, command = _verified_goto_test_mount(monkeypatch)
    assert mount.begin_sync_and_goto(command)
    _sync_ack(mount, "ON_COORD_SET", {"SYNC": True})
    _sync_ack(mount, "EQUATORIAL_EOD_COORD", {"RA": 8.8, "DEC": 49.5})
    assert mount._pending_sync_goto["stage"] == "waiting_slew_mode"
    monkeypatch.setattr(mount, "_apply_indi_properties", lambda *args: True)
    mount.stop_mount()
    _sync_ack(mount, "ON_COORD_SET", {"SLEW": True})
    assert mount.moves == []
    assert mount._sync_goto_status["state"] == "failed"


def test_sync_goto_ignores_previous_connection_ack(monkeypatch):
    mount, command = _verified_goto_test_mount(monkeypatch)
    assert mount.begin_sync_and_goto(command)
    _sync_ack(mount, "ON_COORD_SET", {"SYNC": True}, generation=-1)
    assert mount.client.numbers == []


def test_sync_goto_accepts_ra_wrap_within_readback_tolerance(monkeypatch):
    mount, command = _verified_goto_test_mount(monkeypatch)
    command.update(sync_ra=359.999, sync_dec=20.0)
    assert mount.begin_sync_and_goto(command)
    _sync_ack(mount, "ON_COORD_SET", {"SYNC": True})
    _sync_ack(mount, "EQUATORIAL_EOD_COORD", {"RA": 0.00001, "DEC": 20.0})
    assert mount._pending_sync_goto["stage"] == "waiting_slew_mode"


@pytest.mark.skipif(mci.PyIndi is None, reason="requires installed INDI bindings")
def test_real_indi_local_switch_mutation_is_not_a_driver_ack(monkeypatch):
    indi = mci.PyIndi
    receipts = []
    owner = SimpleNamespace(
        _indi_device_name=lambda: "LX200 OnStepX",
        receive_sync_property=lambda *args: receipts.append(args),
        receive_current_position=lambda *args: None,
    )
    client = mci.PiFinderIndiClient(owner, generation=7)
    prop = indi.PropertySwitch(2)
    prop.setDeviceName("LX200 OnStepX")
    prop.setName("ON_COORD_SET")
    prop.setState(indi.IPS_OK)
    prop[0].setName("SYNC")
    prop[1].setName("SLEW")
    device = SimpleNamespace(getSwitch=lambda _: prop)
    monkeypatch.setattr(client, "_wait_for_property", lambda *args: True)
    monkeypatch.setattr(client, "sendNewSwitch", lambda _: None)
    assert client.set_switch(device, "ON_COORD_SET", "SYNC")
    assert receipts == []
    client.updateProperty(prop)
    assert receipts == [("ON_COORD_SET", "ok", {"SYNC": True, "SLEW": False}, 7)]
    prop.setDeviceName("Other telescope")
    client.updateProperty(prop)
    assert len(receipts) == 1


@pytest.mark.skipif(mci.PyIndi is None, reason="requires installed INDI bindings")
def test_real_indi_number_callback_snapshots_values_and_state():
    indi = mci.PyIndi
    receipts = []
    owner = SimpleNamespace(
        _indi_device_name=lambda: "LX200 OnStepX",
        receive_sync_property=lambda *args: receipts.append(args),
        receive_current_position=lambda *args: None,
    )
    client = mci.PiFinderIndiClient(owner, generation=7)
    prop = indi.PropertyNumber(2)
    prop.setDeviceName("LX200 OnStepX")
    prop.setName("EQUATORIAL_EOD_COORD")
    prop.setState(indi.IPS_BUSY)
    prop[0].setName("RA")
    prop[0].setValue(8.8)
    prop[1].setName("DEC")
    prop[1].setValue(49.5)
    client.updateProperty(prop)
    prop[0].setValue(1.0)
    assert receipts == [("EQUATORIAL_EOD_COORD", "busy", {"RA": 8.8, "DEC": 49.5}, 7)]


def test_manual_motion_deadman_sends_stop_after_expired_lease():
    mount = DummyMountControl()

    assert mount.manual_move("north", lease_seconds=0.3)
    mount._manual_motion_deadline = time.monotonic() - 0.01
    mount._check_manual_motion_deadline()

    assert mount._manual_motion_direction is None
    assert all("=Off" in prop for prop in mount.applied_properties[-1])
    assert not any("ABORT" in prop for prop in mount.applied_properties[-1])


def test_manual_motion_keepalive_extends_matching_motion():
    mount = DummyMountControl()

    assert mount.manual_move("east", lease_seconds=0.3)
    original_deadline = mount._manual_motion_deadline
    assert mount.manual_motion_keepalive("east", lease_seconds=1.2)

    assert mount._manual_motion_deadline is not None
    assert original_deadline is not None
    assert mount._manual_motion_deadline > original_deadline


@pytest.mark.parametrize("tracking", [False, True])
def test_direction_release_preserves_tracking_without_global_abort(
    monkeypatch, tracking
):
    mount = DummyMountControl()
    monkeypatch.setattr(mount, "_cached_tracking_enabled", lambda: tracking)
    assert mount.manual_move("northeast")
    assert mount.stop_mount()
    stops = mount.applied_properties[-1]
    assert len(stops) == 2
    assert all("TELESCOPE_MOTION_" in prop and "=Off" in prop for prop in stops)
    assert not any("TRACK_STATE" in prop or "ABORT" in prop for prop in stops)


def test_failed_axis_stop_falls_back_to_abort_and_restores_tracking(monkeypatch):
    mount = DummyMountControl()
    assert mount.manual_move("north")
    monkeypatch.setattr(mount, "_cached_tracking_enabled", lambda: True)
    events = []

    def apply(properties, *args):
        events.append(properties)
        return "ABORT" in properties[0]

    monkeypatch.setattr(mount, "_apply_indi_properties", apply)
    monkeypatch.setattr(
        mount, "set_tracking", lambda enabled: events.append(enabled) or True
    )
    assert mount.stop_mount()
    assert "MOTION_NS" in events[0][0]
    assert "ABORT" in events[1][0]
    assert events[2] is True
    assert mount._manual_motion_direction is None


def test_manual_motion_keepalive_ignores_other_direction():
    mount = DummyMountControl()

    assert mount.manual_move("east", lease_seconds=0.3)
    original_deadline = mount._manual_motion_deadline
    assert not mount.manual_motion_keepalive("west", lease_seconds=1.2)

    assert mount._manual_motion_deadline == original_deadline


def test_manual_motion_east_west_are_reversed_for_onstep_guide_axis():
    mount = DummyMountControl()

    assert mount.manual_move("east", lease_seconds=0.3)
    assert any(
        "TELESCOPE_MOTION_WE.MOTION_WEST=On" in prop
        for prop in mount.applied_properties[-1]
    )

    assert mount.manual_move("west", lease_seconds=0.3)
    assert any(
        "TELESCOPE_MOTION_WE.MOTION_EAST=On" in prop
        for prop in mount.applied_properties[-1]
    )


def test_manual_motion_publishes_mount_readback_while_active(monkeypatch):
    mount = DummyConnectedMount()
    clock = [100.0]
    positions = [(101.25, -12.5), (101.5, -12.4)]
    cached_reads = []

    def fake_monotonic():
        return clock[0]

    def fake_apply(properties, success_state, success_message, failure_state):
        return True

    def fake_cached_position(write_status=True):
        cached_reads.append(write_status)
        position = positions[min(len(cached_reads) - 1, len(positions) - 1)]
        mount.current_ra, mount.current_dec = position
        return position

    monkeypatch.setattr(mci.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(mount, "_apply_indi_properties", fake_apply)
    monkeypatch.setattr(mount, "_read_cached_current_position", fake_cached_position)

    assert mount.manual_move("north", lease_seconds=1.2)

    assert cached_reads == [False]
    assert mount.statuses[-1][0] == "manual_motion"
    assert mount.statuses[-1][1] == "Manual north motion in progress"
    assert mount.statuses[-1][2]["manual_motion_direction"] == "north"
    assert mount.statuses[-1][2]["manual_motion_origin"] == "user"
    assert mount.statuses[-1][2]["mount_motion_active"] is True
    assert mount.statuses[-1][2]["mount_motion_type"] == "manual"
    assert mount.statuses[-1][2]["mount_readback_priority"] is True
    assert mount.statuses[-1][2]["ra"] == 101.25
    assert mount.statuses[-1][2]["dec"] == -12.5

    clock[0] += mci.POSITION_STATUS_MIN_INTERVAL + 0.1
    mount._publish_manual_motion_progress()

    assert cached_reads == [False, False]
    assert mount.statuses[-1][0] == "manual_motion"
    assert mount.statuses[-1][2]["ra"] == 101.5
    assert mount.statuses[-1][2]["dec"] == -12.4
    assert mount.statuses[-1][2]["mount_motion_active"] is True
    assert mount.statuses[-1][2]["mount_motion_type"] == "manual"
    assert mount.statuses[-1][2]["mount_readback_priority"] is True


def test_set_backlash_sends_indi_backlash_properties():
    mount = DummyMountControl()

    assert mount.set_backlash(12, 34)

    assert any(
        "Backlash.Backlash RA=12" in prop for prop in mount.applied_properties[-1]
    )
    assert any(
        "Backlash.Backlash DEC=34" in prop for prop in mount.applied_properties[-1]
    )
    assert mount.backlash_ra == 12
    assert mount.backlash_de == 34


def test_auto_backlash_requires_solved_pointing():
    mount = DummyMountControl(shared_state=object())
    mount._current_solved_pointing = lambda **kwargs: None

    assert not mount.auto_calculate_backlash()

    assert mount._backlash_auto is not None
    assert mount._backlash_auto["auto_mode"] == ibc.BACKLASH_AUTO_MODE_COMPASS_GOTO
    assert mount._backlash_auto["state"] == "waiting_for_solved"


def test_auto_backlash_uses_solved_goto_loop():
    mount = DummyMountControl(shared_state=object())
    mount._current_solved_pointing = lambda **kwargs: {
        "ra": 10.0,
        "dec": 20.0,
        "timestamp": time.time(),
        "source": "solve",
    }
    tracking_writes = []
    mount.connect = lambda: True
    mount.stop_mount = lambda: True
    mount._read_tracking_enabled = lambda: True
    mount.set_tracking = lambda enabled: tracking_writes.append(enabled) or True

    assert mount.auto_calculate_backlash(mode="compass_goto_loop")

    assert mount._backlash_auto is not None
    assert mount._backlash_auto["axis"] == "Mount frame"
    assert mount._backlash_auto["auto_mode"] == ibc.BACKLASH_AUTO_MODE_COMPASS_GOTO
    assert mount._backlash_auto["state"] == "ready"
    assert mount._backlash_auto["repeats"] == ibc.BACKLASH_COMPASS_GOTO_REPEATS
    assert mount._backlash_auto["solved_status"]["valid"] is True
    assert mount._backlash_auto["original_tracking"] is True
    assert tracking_writes == [False]


def test_auto_backlash_accepts_repeat_count():
    mount = DummyMountControl(shared_state=object())
    calls = {}

    def fake_start(repeats=ibc.BACKLASH_COMPASS_GOTO_REPEATS, offset_deg=2.0):
        calls["repeats"] = repeats
        calls["offset_deg"] = offset_deg
        return True

    mount.start_backlash_compass_goto_loop = fake_start

    assert mount.auto_calculate_backlash(mode="compass_goto_loop", repeats="7")

    assert calls["repeats"] == 7


def test_backlash_stop_request_aborts_motion_test(monkeypatch, tmp_path):
    stop_request = tmp_path / "mount_control_stop_request.json"
    stop_request.write_text(json.dumps({"requested_at": 1234.0}), encoding="utf-8")
    monkeypatch.setattr(mci, "STOP_REQUEST_FILE", stop_request)
    mount = DummyMountControl(shared_state=object())
    mount._backlash_auto = {
        "auto_mode": ibc.BACKLASH_AUTO_MODE_COMPASS_GOTO,
        "state": "running",
    }
    stop_calls = []
    tracking_writes = []
    mount.stop_mount = lambda: stop_calls.append(True) or True
    mount.set_tracking = lambda enabled: tracking_writes.append(enabled) or True

    assert mount._abort_backlash_if_requested("test phase")

    assert stop_calls == [True]
    assert tracking_writes == [False]
    assert mount._backlash_auto["state"] == "stopped"
    assert "test phase" in mount._backlash_auto["message"]
    assert not stop_request.exists()


def test_backlash_goto_wait_requires_target_reached(monkeypatch):
    mount = DummyMountControl(shared_state=object())
    clock = [0.0]
    stop_calls = []

    def fake_monotonic():
        clock[0] += 1.0
        return clock[0]

    monkeypatch.setattr(mci.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(mci.time, "sleep", lambda seconds: None)
    mount._backlash_auto = {}
    mount._indi_mount_is_busy = lambda: False
    mount._read_current_position = lambda: (0.0, 0.0)
    mount.stop_mount = lambda: stop_calls.append(True) or True

    assert not mount._goto_target_and_wait(30.0, 30.0, "blocked", timeout=2.0)

    assert stop_calls == [True]
    assert mount._backlash_auto["state"] == "failed"
    assert "target was not reached" in mount._backlash_auto["message"]


def test_backlash_goto_waits_for_onstep_final_no_goto(monkeypatch):
    mount = DummyMountControl(shared_state=object())
    clock = [0.0]
    onstep_states = [False, True, True, True]

    def fake_monotonic():
        return clock[0]

    def fake_sleep(seconds):
        clock[0] += seconds

    def fake_onstep_complete():
        return onstep_states.pop(0) if onstep_states else True

    monkeypatch.setattr(mci.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(mci.time, "sleep", fake_sleep)
    mount._backlash_auto = {}
    mount._indi_mount_is_busy = lambda: False
    mount._read_current_position = lambda: (30.0, 30.0)
    monkeypatch.setattr(mount, "_onstep_goto_complete", fake_onstep_complete)

    assert mount._goto_target_and_wait(30.0, 30.0, "settle", timeout=10.0)

    assert clock[0] >= mci.GOTO_COMPLETE_STABLE_SECONDS
    assert mount._backlash_auto["state"] == "running"


def test_compass_goto_loop_records_initial_offset_and_repeats():
    mount = DummyMountControl(shared_state=object())
    mount._backlash_auto = {
        "auto_mode": ibc.BACKLASH_AUTO_MODE_COMPASS_GOTO,
        "repeats": 2,
        "offset_deg": 3.0,
    }
    current_position = [10.0, 20.0]
    goto_calls = []

    mount.connect = lambda: True
    mount._current_solved_pointing = lambda **kwargs: {
        "ra": current_position[0],
        "dec": current_position[1],
        "timestamp": time.time(),
        "source": "solve",
    }
    mount._wait_for_solved_pointing = (
        lambda label,
        min_timestamp=None,
        timeout=ibc.BACKLASH_SOLVED_WAIT_SECONDS: mount._current_solved_pointing()
    )
    mount._home_park_status_fields = lambda: {"park_state": "Unparked"}
    mount._read_tracking_enabled = lambda: False
    mount._read_current_position = lambda: (current_position[0], current_position[1])
    mount._backlash_mount_model = lambda: "eq"
    mount.set_tracking = lambda enabled: True
    mount.sync_mount = (
        lambda ra, dec: current_position.__setitem__(slice(None), [ra % 360.0, dec])
        or True
    )
    mount.stop_mount = lambda: True
    mount._backlash_cancelable_sleep = lambda seconds, label: True

    def fake_goto(
        ra_deg, dec_deg, phase_label, timeout=ibc.BACKLASH_AUTO_GOTO_TIMEOUT_SECONDS
    ):
        goto_calls.append((phase_label, round(ra_deg % 360.0, 3), round(dec_deg, 3)))
        current_position[0] = ra_deg % 360.0
        current_position[1] = dec_deg
        return True

    mount._goto_target_and_wait = fake_goto

    assert mount.continue_backlash_compass_goto_loop()

    records = mount._backlash_auto["coordinate_records"]
    assert [record["label"] for record in records] == [
        "initial RA",
        "offset initial RA",
        "return 1 RA",
        "offset 1 RA",
        "return 2 RA",
        "offset 2 RA",
        "initial DEC",
        "offset initial DEC",
        "return 1 DEC",
        "offset 1 DEC",
        "return 2 DEC",
        "offset 2 DEC",
    ]
    assert goto_calls == [
        ("init RA", 7.0, 20.0),
        ("offset initial RA", 10.0, 20.0),
        ("return 1 RA", 7.0, 20.0),
        ("offset 1 RA", 10.0, 20.0),
        ("return 2 RA", 7.0, 20.0),
        ("offset 2 RA", 10.0, 20.0),
        ("init DEC", 10.0, 17.0),
        ("offset initial DEC", 10.0, 20.0),
        ("return 1 DEC", 10.0, 17.0),
        ("offset 1 DEC", 10.0, 20.0),
        ("return 2 DEC", 10.0, 17.0),
        ("offset 2 DEC", 10.0, 20.0),
    ]
    assert records[0]["mount_ra"] == 7.0
    assert records[0]["active_axis"] == "ra"
    assert records[6]["active_axis"] == "dec"
    assert records[-1]["mount_ra"] == 10.0
    assert records[-1]["mount_dec"] == 20.0
    assert mount.applied_properties == []
    assert records[0]["pifinder_solved_valid"] is True
    assert records[0]["pifinder_solved_source"] == "solve"
    analysis = mount._backlash_auto["directional_analysis"]
    assert len(analysis["legs"]) == 10
    assert analysis["direction_stats"]["offset"]["sample_count"] == 4
    assert analysis["direction_stats"]["return"]["sample_count"] == 4
    axis_direction_stats = analysis["axis_direction_stats"]
    assert axis_direction_stats["ra_positive"]["display_label"] == "RA+"
    assert axis_direction_stats["ra_positive"]["sample_count"] == 2
    assert axis_direction_stats["ra_negative"]["display_label"] == "RA-"
    assert axis_direction_stats["ra_negative"]["sample_count"] == 2
    assert axis_direction_stats["dec_positive"]["display_label"] == "DEC+"
    assert axis_direction_stats["dec_positive"]["sample_count"] == 2
    assert axis_direction_stats["dec_negative"]["display_label"] == "DEC-"
    assert axis_direction_stats["dec_negative"]["sample_count"] == 2
    assert mount._backlash_auto["state"] == "complete"


def test_backlash_goto_command_disables_tracking_after_goto(monkeypatch):
    mount = DummyMountControl(shared_state=object())
    monkeypatch.setattr(
        mount, "_backlash_cancelable_sleep", lambda seconds, label: True
    )
    goto_calls = []
    tracking_writes = []
    mount._backlash_auto = {}

    def fake_goto(
        ra_deg, dec_deg, phase_label, timeout=ibc.BACKLASH_AUTO_GOTO_TIMEOUT_SECONDS
    ):
        goto_calls.append((ra_deg, dec_deg, phase_label, timeout))
        return True

    mount._goto_target_and_wait = fake_goto
    mount._read_tracking_enabled = lambda: True
    mount.set_tracking = lambda enabled: tracking_writes.append(enabled) or True

    assert mount._backlash_goto_command_and_wait(
        {"target_ra": 12.3, "target_dec": -4.5},
        "goto phase",
        "ra",
    )
    assert goto_calls == [
        (12.3, -4.5, "goto phase", ibc.BACKLASH_COMPASS_GOTO_TIMEOUT_SECONDS)
    ]
    assert tracking_writes == [False]


def test_compass_goto_loop_plan_uses_altaz_offset_for_altaz_mount():
    mount = DummyMountControl(shared_state=object())
    mount._backlash_mount_model = lambda: "altaz"
    mount._radec_to_altaz = lambda ra, dec: (40.0, 50.0)

    def fake_altaz_to_radec(alt, az):
        return (az + 100.0, alt - 10.0)

    mount._altaz_to_radec = fake_altaz_to_radec

    plan = mount._compass_goto_loop_plan(10.0, 20.0, 3.0, active_axis="az")

    assert plan is not None
    assert plan["movement_frame"] == "altaz"
    assert plan["active_axis"] == "az"
    assert plan["start_altitude"] == 40.0
    assert plan["start_azimuth"] == 50.0
    assert plan["target_altitude"] == 40.0
    assert plan["target_azimuth"] == 53.0

    start_command = mount._compass_goto_loop_command(plan, "start")
    target_command = mount._compass_goto_loop_command(plan, "target")

    assert start_command["target_ra"] == 150.0
    assert start_command["target_dec"] == 30.0
    assert target_command["target_ra"] == 153.0
    assert target_command["target_dec"] == 30.0
    assert target_command["target_altitude"] == 40.0
    assert target_command["target_azimuth"] == 53.0

    alt_plan = mount._compass_goto_loop_plan(10.0, 20.0, 3.0, active_axis="alt")
    assert alt_plan is not None
    assert alt_plan["active_axis"] == "alt"
    assert alt_plan["target_altitude"] == 43.0
    assert alt_plan["target_azimuth"] == 50.0
    alt_target_command = mount._compass_goto_loop_command(alt_plan, "target")
    assert alt_target_command["target_ra"] == 150.0
    assert alt_target_command["target_dec"] == 33.0


def test_compass_goto_loop_analysis_uses_actual_pre_goto_mount_start():
    mount = DummyMountControl(shared_state=object())
    records = [
        {
            "sequence": 1,
            "label": "initial",
            "mount_ra": 100.0,
            "mount_dec": 10.0,
            "mount_altitude": 10.1,
            "mount_azimuth": 20.2,
            "pifinder_solved_ra": 101.0,
            "pifinder_solved_dec": 11.0,
            "pifinder_solved_altitude": 11.0,
            "pifinder_solved_azimuth": 21.0,
            "pifinder_solved_valid": True,
        },
        {
            "sequence": 2,
            "label": "offset initial",
            "mount_ra": 103.0,
            "mount_dec": 12.9,
            "mount_altitude": 12.9,
            "mount_azimuth": 23.1,
            "pifinder_solved_ra": 103.1,
            "pifinder_solved_dec": 13.1,
            "pifinder_solved_altitude": 13.1,
            "pifinder_solved_azimuth": 24.9,
            "pifinder_solved_valid": True,
            "command_start_ra": 100.0,
            "command_start_dec": 10.0,
            "command_start_altitude": 10.0,
            "command_start_azimuth": 20.0,
            "target_ra": 103.0,
            "target_dec": 13.0,
            "target_altitude": 13.0,
            "target_azimuth": 23.0,
            "movement_frame": "altaz",
        },
    ]

    analysis = mount._compass_goto_loop_directional_analysis(records)
    leg = analysis["legs"][0]

    assert leg["command_start_altitude"] == 10.0
    assert leg["command_start_azimuth"] == 20.0
    assert round(leg["mount_start_altitude"], 1) == 10.1
    assert round(leg["mount_start_azimuth"], 1) == 20.2
    assert round(leg["mount_delta_altitude"], 1) == 2.8
    assert round(leg["mount_delta_azimuth"], 1) == 2.9
    assert round(leg["pifinder_solved_delta_alt"], 1) == 2.1
    assert round(leg["pifinder_solved_delta_az"], 1) == 3.9
    assert leg["motion_difference_alt_arcsec"] == 2520
    assert leg["motion_difference_az_arcsec"] == -3600
    assert leg["motion_backlash_alt_arcsec"] == 2520
    assert leg["motion_backlash_az_arcsec"] == 3600


def test_compass_goto_loop_analysis_groups_altaz_values_by_axis_direction():
    mount = DummyMountControl(shared_state=object())
    records = [
        {
            "sequence": 1,
            "label": "initial",
            "mount_ra": 100.0,
            "mount_dec": 10.0,
            "mount_altitude": 10.0,
            "mount_azimuth": 20.0,
            "pifinder_solved_ra": 100.0,
            "pifinder_solved_dec": 10.0,
            "pifinder_solved_altitude": 10.0,
            "pifinder_solved_azimuth": 20.0,
            "pifinder_solved_valid": True,
        },
        {
            "sequence": 2,
            "label": "offset 1",
            "mount_ra": 103.0,
            "mount_dec": 13.0,
            "mount_altitude": 13.0,
            "mount_azimuth": 23.0,
            "pifinder_solved_ra": 102.9,
            "pifinder_solved_dec": 12.9,
            "pifinder_solved_altitude": 12.9,
            "pifinder_solved_azimuth": 22.8,
            "pifinder_solved_valid": True,
            "target_altitude": 13.0,
            "target_azimuth": 23.0,
            "movement_frame": "altaz",
        },
        {
            "sequence": 3,
            "label": "return 1",
            "mount_ra": 100.0,
            "mount_dec": 10.0,
            "mount_altitude": 10.0,
            "mount_azimuth": 20.0,
            "pifinder_solved_ra": 100.2,
            "pifinder_solved_dec": 10.2,
            "pifinder_solved_altitude": 10.2,
            "pifinder_solved_azimuth": 20.4,
            "pifinder_solved_valid": True,
            "target_altitude": 10.0,
            "target_azimuth": 20.0,
            "movement_frame": "altaz",
        },
    ]

    analysis = mount._compass_goto_loop_directional_analysis(records)
    axis_direction_stats = analysis["axis_direction_stats"]

    assert axis_direction_stats["alt_positive"]["display_label"] == "ALT+"
    assert axis_direction_stats["alt_positive"]["sample_count"] == 1
    assert axis_direction_stats["az_positive"]["display_label"] == "AZ+"
    assert axis_direction_stats["az_positive"]["sample_count"] == 1
    assert axis_direction_stats["alt_negative"]["display_label"] == "ALT-"
    assert axis_direction_stats["alt_negative"]["sample_count"] == 1
    assert axis_direction_stats["az_negative"]["display_label"] == "AZ-"
    assert axis_direction_stats["az_negative"]["sample_count"] == 1


def test_compass_backlash_filter_uses_middle_40_percent_mean():
    mount = DummyMountControl(shared_state=object())

    stats = mount._filter_compass_backlash_values(
        [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    )

    assert stats["values"] == [40, 50, 60, 70]
    assert stats["excluded_values"] == [10, 20, 30, 80, 90, 100]
    assert stats["trim_low_count"] == 3
    assert stats["trim_high_count"] == 3
    assert stats["trimmed_mean"] == 55.0


def test_compass_goto_loop_restores_tracking_after_test():
    mount = DummyMountControl(shared_state=object())
    mount._backlash_auto = {
        "auto_mode": ibc.BACKLASH_AUTO_MODE_COMPASS_GOTO,
        "repeats": 1,
        "offset_deg": 3.0,
    }
    current_position = [10.0, 20.0]
    tracking_writes = []
    goto_calls = []

    mount.connect = lambda: True
    mount._current_solved_pointing = lambda **kwargs: {
        "ra": current_position[0],
        "dec": current_position[1],
        "timestamp": time.time(),
        "source": "solve",
    }
    mount._wait_for_solved_pointing = (
        lambda label,
        min_timestamp=None,
        timeout=ibc.BACKLASH_SOLVED_WAIT_SECONDS: mount._current_solved_pointing()
    )
    mount._home_park_status_fields = lambda: {"park_state": "Unparked"}
    mount._read_tracking_enabled = lambda: True
    mount.set_tracking = lambda enabled: tracking_writes.append(enabled) or True
    mount._read_current_position = lambda: (current_position[0], current_position[1])
    mount._backlash_mount_model = lambda: "eq"
    mount.sync_mount = (
        lambda ra, dec: current_position.__setitem__(slice(None), [ra % 360.0, dec])
        or True
    )
    mount.stop_mount = lambda: True
    mount._backlash_cancelable_sleep = lambda seconds, label: True

    def fake_goto(
        ra_deg, dec_deg, phase_label, timeout=ibc.BACKLASH_AUTO_GOTO_TIMEOUT_SECONDS
    ):
        goto_calls.append((phase_label, round(ra_deg % 360.0, 3), round(dec_deg, 3)))
        current_position[0] = ra_deg % 360.0
        current_position[1] = dec_deg
        return True

    mount._goto_target_and_wait = fake_goto

    assert mount.continue_backlash_compass_goto_loop()

    assert len(goto_calls) == 8
    assert tracking_writes[:2] == [False, False]
    assert tracking_writes[-1] is True
    assert tracking_writes.count(False) == 10
    assert mount._backlash_auto["state"] == "complete"


def test_read_tracking_enabled_retries_after_empty_property_snapshot(monkeypatch):
    mount = DummyMountControl()
    snapshots = [
        {},
        {"LX200 OnStepX.TELESCOPE_TRACK_STATE.TRACK_OFF": "On"},
    ]

    def fake_get_properties(**kwargs):
        return snapshots.pop(0) if snapshots else {}

    monkeypatch.setattr(sys_utils, "get_indi_onstep_properties", fake_get_properties)
    monkeypatch.setattr(mci.time, "sleep", lambda seconds: None)

    assert mount._read_tracking_enabled() is False


def test_read_tracking_enabled_treats_onstep_idle_as_off(monkeypatch):
    mount = DummyMountControl()
    monkeypatch.setattr(mount, "_device_switch_on", lambda *args: None)
    monkeypatch.setattr(mount, "_read_tracking_enabled_from_properties", lambda: None)
    monkeypatch.setattr(
        mount,
        "_device_text_value",
        lambda property_name, element_name: "Idle"
        if property_name == "OnStep Status" and element_name == "Tracking"
        else "",
    )

    assert mount._read_tracking_enabled() is False


def test_set_tracking_accepts_desired_readback_after_command_failure(monkeypatch):
    mount = DummyMountControl()
    mount.connected = True
    mount._apply_indi_properties = lambda *args, **kwargs: False
    monkeypatch.setattr(mount, "_confirm_tracking_state", lambda enabled: not enabled)

    assert mount.set_tracking(False)
    assert mount.applied_properties == []


def test_multipoint_align_manual_start_selects_star_without_goto():
    mount = DummyMountControl()

    assert mount.start_multipoint_align("manual", 2, "Vega")

    assert mount._multipoint_align is not None
    assert mount._multipoint_align["active"]
    assert mount._multipoint_align["total_points"] == 2
    assert mount._multipoint_align["current_star"]["name"] == "Vega"
    assert mount._multipoint_align["state"] == "adjust"
    assert mount.goto_calls == []
    assert mount.mount_align_start_calls == []
    assert mount._multipoint_align["mount_align_started"] is False
    assert mount._multipoint_align["mount_align_deferred"] is True


def test_multipoint_align_explicit_goto_moves_to_selected_star():
    mount = DummyMountControl()

    assert mount.start_multipoint_align("manual", 2)
    assert mount.select_multipoint_align_star("Vega", goto=True)

    assert mount._multipoint_align is not None
    assert mount._multipoint_align["current_star"]["name"] == "Vega"
    assert mount.goto_calls[-1][0] == 279.234735
    assert mount.goto_calls[-1][1] == 38.783689


def test_multipoint_align_rejects_stars_above_overhead_limit():
    mount = DummyMountControl()
    mount._radec_to_altaz = lambda ra, dec: (85.0, 180.0)

    assert mount.start_multipoint_align("manual", 2)
    assert not mount.select_multipoint_align_star("Vega", goto=True)

    assert mount.goto_calls == []
    assert mount._multipoint_align is not None
    assert mount._multipoint_align["active"]
    assert mount._multipoint_align["state"] == "waiting"
    assert mount._multipoint_align["current_star"] is None
    assert "above" in mount._multipoint_align["message"]


def test_multipoint_align_goto_failure_clears_current_star():
    mount = DummyMountControl()
    mount.goto_target = lambda *args, **kwargs: False

    assert mount.start_multipoint_align("manual", 2)
    assert not mount.select_multipoint_align_star("Vega", goto=True)

    assert mount._multipoint_align is not None
    assert mount._multipoint_align["active"]
    assert mount._multipoint_align["state"] == "waiting"
    assert mount._multipoint_align["current_star"] is None
    assert "select another star" in mount._multipoint_align["message"]


def test_multipoint_align_clear_target_keeps_session_active():
    mount = DummyMountControl()

    assert mount.start_multipoint_align("manual", 2)
    assert mount.select_multipoint_align_star("Vega", goto=True)
    assert mount.clear_multipoint_align_target()

    assert mount._multipoint_align is not None
    assert mount._multipoint_align["active"]
    assert mount._multipoint_align["state"] == "waiting"
    assert mount._multipoint_align["current_star"] is None


def test_multipoint_align_confirm_advances_until_complete():
    mount = DummyMountControl()

    assert mount.start_multipoint_align("manual", 1)
    assert mount.select_multipoint_align_star("Altair", goto=True)
    assert mount.confirm_multipoint_align(source="web")

    assert mount.sync_calls == [(10.0, 20.0), (297.695827, 8.868322)]
    assert mount.mount_align_accept_calls == []
    assert mount._multipoint_align is not None
    assert not mount._multipoint_align["active"]
    assert mount._multipoint_align["state"] == "complete"
    assert mount._multipoint_align["completed_points"] == 1
    assert mount._multipoint_align["completed"][0]["mount_align_started"] is False
    assert mount._multipoint_align["completed"][0]["mount_align_command"] == "sync"


def test_multipoint_align_skysafari_confirm_requires_prior_goto_target():
    mount = DummyMountControl()

    assert mount.start_multipoint_align("manual", 1)
    assert not mount.confirm_multipoint_align(10.0, 20.0, source="skysafari")

    assert mount.sync_calls == [(10.0, 20.0)]
    assert mount.mount_align_accept_calls == []
    assert mount._multipoint_align is not None
    assert mount._multipoint_align["state"] == "failed"
    assert "GoTo" in mount._multipoint_align["message"]


def test_multipoint_align_syncs_location_time_and_large_mount_offset_before_start():
    mount = DummyMountControl()
    positions = [(50.0, -10.0), (10.0, 20.0), (10.0, 20.0)]
    mount._read_current_position = (
        lambda: positions.pop(0) if positions else (10.0, 20.0)
    )

    assert mount.start_multipoint_align("manual", 2)

    assert mount.location_sync_calls[-1] == (True, True)
    assert mount.sync_calls == [(10.0, 20.0)]
    assert mount.events == [
        ("sync_location_time", True, True),
        ("sync_mount", 10.0, 20.0),
    ]
    assert mount._multipoint_align is not None
    assert mount._multipoint_align["pifinder_mount_synced"] is True
    assert mount._multipoint_align["pifinder_mount_verified"] is True
    assert mount._multipoint_align["mount_align_started"] is False
    assert mount._multipoint_align["mount_align_deferred"] is True


def test_multipoint_align_defers_native_start_to_preserve_pifinder_sync():
    mount = DummyMountControl()

    assert mount.start_multipoint_align("manual", 2)

    assert mount.sync_calls == [(10.0, 20.0)]
    assert mount.mount_align_start_calls == []
    assert mount._multipoint_align is not None
    assert mount._multipoint_align["active"]
    assert mount._multipoint_align["mount_align_started"] is False
    assert mount._multipoint_align["mount_align_deferred"] is True
    assert "deferred" in mount._multipoint_align["mount_align_message"]


def test_multipoint_align_syncs_mount_to_pifinder_before_native_align_start():
    mount = DummyMountControl()

    assert mount.start_multipoint_align("manual", 2)

    assert mount.sync_calls == [(10.0, 20.0)]
    assert mount._multipoint_align is not None
    assert mount._multipoint_align["pifinder_mount_synced"] is True
    assert mount._multipoint_align["pifinder_mount_separation_arcmin"] == 0.0
    assert mount.events == [
        ("sync_location_time", True, True),
        ("sync_mount", 10.0, 20.0),
    ]


def test_multipoint_align_resets_stale_onstep_native_alignment(monkeypatch):
    mount = DummyMountControl()
    reset_calls = []

    monkeypatch.setattr(
        mount,
        "_onstep_connection_config",
        lambda: {
            "connection_type": "network",
            "network_host": "",
            "network_port": 9999,
            "serial_port": "",
            "serial_baud": 9600,
            "direct_location_time_sync": False,
        },
    )
    monkeypatch.setattr(mount, "_onstep_native_alignment_active", lambda: True)
    monkeypatch.setattr(mount, "disconnect", lambda: reset_calls.append("disconnect"))
    monkeypatch.setattr(mount, "connect", lambda: reset_calls.append("connect") or True)
    monkeypatch.setattr(
        sys_utils,
        "reset_onstep_alignment_exclusive",
        lambda **kwargs: reset_calls.append(kwargs) or {"ok": True},
    )

    assert mount.start_multipoint_align("manual", 2)

    assert reset_calls[0]["connection_type"] == "network"
    assert reset_calls[1:] == ["disconnect", "connect"]
    assert mount._multipoint_align is not None
    assert mount._multipoint_align["onstep_native_align_reset"] is True
    assert mount.sync_calls == [(10.0, 20.0)]


def test_multipoint_align_confirm_keeps_latest_selected_goto_target():
    mount = DummyMountControl()

    assert mount.start_multipoint_align("manual", 1)
    assert mount.select_multipoint_align_star("Vega", goto=True)
    assert mount.confirm_multipoint_align(10.0, 20.0, source="skysafari")

    assert mount.sync_calls == [(10.0, 20.0), (279.234735, 38.783689)]
    assert mount.mount_align_accept_calls == []
    assert mount._multipoint_align is not None
    assert mount._multipoint_align["completed"][0]["name"] == "Vega"


def test_multipoint_align_skysafari_goto_target_becomes_confirm_target():
    mount = DummyMountControl()

    assert mount.start_multipoint_align("manual", 1)
    assert mount.select_multipoint_align_target(10.0, 20.0, "SkySafari Target")
    assert mount.confirm_multipoint_align(99.0, -20.0, source="skysafari")

    assert mount.goto_calls[-1][0] == 10.0
    assert mount.goto_calls[-1][1] == 20.0
    assert mount.sync_calls == [(10.0, 20.0), (10.0, 20.0)]
    assert mount.mount_align_accept_calls == []
    assert mount._multipoint_align is not None
    assert mount._multipoint_align["completed"][0]["name"] == "SkySafari Target"


def test_sync_location_time_sends_provisional_time_while_clock_untrusted(monkeypatch):
    mount = DummyMountControl(DummySharedStateWithLocation())
    monkeypatch.setattr(mci.gps_time_sync, "clock_is_trusted", lambda **kwargs: False)
    applied = []
    monkeypatch.setattr(
        sys_utils,
        "apply_indi_onstep_location_time",
        lambda **kwargs: applied.append(kwargs) or {"ok": True},
    )
    monkeypatch.setattr(sys_utils, "write_onstep_location_cache", lambda *args: None)
    statuses = []
    monkeypatch.setattr(
        mount,
        "_write_controller_status",
        lambda state, message="", **extra: statuses.append((state, message)),
    )

    # An untrusted clock no longer blocks the send: a mount with no time
    # refuses every slew, so the current PiFinder time goes out as a
    # provisional value (A5 re-sends once the clock becomes trusted).
    assert mount.sync_location_time() is True

    assert len(applied) == 1
    assert applied[0]["utc_datetime"] == "2026-07-01T14:45:00+00:00"
    assert mount._time_sync_provisional is True
    assert "provisional" in statuses[-1][1]


def test_guide_cycles_leave_selector_until_manual_speed_requested(monkeypatch):
    mount = DummyConnectedMount()
    mount.slew_rate = 6
    mount._guide_correction_accuracy_arcmin = 3.0
    monkeypatch.setattr(mount, "_current_guide_rate_x", lambda: (0.5, 0.5))
    monkeypatch.setattr(mount, "_guide_pulse_inversions", lambda: (False, False))
    mount._slew_rate_polluted = True
    mount._apply_guide_pulse(297.0, 8.9, 297.0, 9.0, 6.0)
    assert mount._slew_rate_reassert_at is None
    mount._check_slew_rate_reassert()
    assert mount.client.switches == []
    assert mount.slew_rate == 6


def test_manual_move_reasserts_slew_rate_when_polluted():
    mount = DummyMountControl()
    mount.client = DummyIndiClient()
    mount.device = DummyIndiDevice()
    mount.slew_rate = 6
    mount._slew_rate_polluted = True

    assert mount.manual_move("north", lease_seconds=0.3)

    assert ("LX200 OnStep", "TELESCOPE_SLEW_RATE", "6") in mount.client.switches
    assert mount._slew_rate_polluted is False


def test_guide_fallback_manual_move_keeps_polluted_guide_rate():
    mount = DummyMountControl()
    mount.client = DummyIndiClient()
    mount.device = DummyIndiDevice()
    mount.slew_rate = 6
    mount._slew_rate_polluted = True

    # The guide-correction fallback nudge opts out: its duration was computed
    # for the slow guide rate, so the user rate must NOT come back first.
    assert mount.manual_move(
        "north",
        lease_seconds=1.0,
        reassert_slew_rate=False,
        origin="guide_correction",
    )

    assert ("LX200 OnStep", "TELESCOPE_SLEW_RATE", "6") not in mount.client.switches
    assert mount._slew_rate_polluted is True
    assert mount._manual_motion_origin == "guide_correction"


def test_set_slew_rate_clears_pending_reassert():
    mount = DummyMountControl()
    mount._slew_rate_polluted = True
    mount._slew_rate_reassert_at = time.monotonic() + 5.0

    assert mount.set_slew_rate(4)

    assert mount._slew_rate_reassert_at is None
    assert mount._slew_rate_polluted is False


def test_multipoint_align_location_time_requires_trusted_clock(monkeypatch):
    mount = DummyMountControl(DummySharedStateWithLocation())
    monkeypatch.setattr(mci.gps_time_sync, "clock_is_trusted", lambda **kwargs: False)
    sync_calls = []
    monkeypatch.setattr(
        mount, "sync_location_time", lambda **kwargs: sync_calls.append(kwargs) or True
    )
    statuses = []
    monkeypatch.setattr(
        mount,
        "_align_session_status",
        lambda state, message: statuses.append((state, message)),
    )

    # Alignment bakes the LST into its model, so it keeps the hard gate the
    # plain location/time sync dropped.
    result = mci.MountControlIndi._sync_multipoint_location_time(mount, {})

    assert result is False
    assert sync_calls == []
    assert statuses[-1][0] == mci.STATE_FAILED
    assert "synchronized clock" in statuses[-1][1]


def test_sync_location_time_allows_manual_time_over_trust_gate(monkeypatch):
    class ManualTimeSharedState(DummySharedStateWithLocation):
        def datetime_is_manual(self):
            return True

    mount = DummyMountControl(ManualTimeSharedState())
    monkeypatch.setattr(mci.gps_time_sync, "clock_is_trusted", lambda **kwargs: False)
    applied = []
    monkeypatch.setattr(
        sys_utils,
        "apply_indi_onstep_location_time",
        lambda **kwargs: applied.append(kwargs) or {"ok": True},
    )
    monkeypatch.setattr(sys_utils, "write_onstep_location_cache", lambda *args: None)
    monkeypatch.setattr(
        mount, "_write_controller_status", lambda state, message="", **extra: None
    )

    assert mount.sync_location_time() is True

    # The manual PiFinder time is exactly what got sent to the mount.
    assert len(applied) == 1
    assert applied[0]["utc_datetime"] == "2026-07-01T14:45:00+00:00"


def test_sync_location_time_uses_direct_lx200_for_onstep(monkeypatch):
    mount = DummyMountControl(DummySharedStateWithLocation())
    direct_calls = []
    cache_calls = []

    monkeypatch.setattr(mci.gps_time_sync, "clock_is_trusted", lambda **kwargs: True)
    monkeypatch.setattr(
        mount,
        "_onstep_connection_config",
        lambda: {
            "connection_type": "network",
            "network_host": "10.10.10.12",
            "network_port": 9999,
            "serial_port": "",
            "direct_location_time_sync": True,
        },
    )
    monkeypatch.setattr(
        sys_utils,
        "sync_onstep_location_time_exclusive",
        lambda **kwargs: direct_calls.append(kwargs) or {"ok": True},
    )
    monkeypatch.setattr(
        sys_utils,
        "write_onstep_location_cache",
        lambda *args: cache_calls.append(args),
    )

    assert mount.sync_location_time()

    assert mount.applied_properties == []
    assert direct_calls == [
        {
            "connection_type": "network",
            "latitude": 37.52704,
            "longitude": 127.10936,
            "elevation": 30.0,
            "utc_datetime": "2026-07-01T14:45:00+00:00",
            "network_host": "10.10.10.12",
            "network_port": 9999,
            "serial_port": "",
            "serial_baud": 9600,
            "server_host": "localhost",
            "server_port": 7624,
        }
    ]
    assert cache_calls == [(37.52704, 127.10936, 30.0, "2026-07-01T14:45:00+00:00")]


def test_radec_separation_arcmin_handles_small_offsets():
    sep = radec_separation_arcmin(10.0, 20.0, 10.0, 20.1)

    assert 5.9 < sep < 6.1


def test_shortest_ra_delta_wraps_at_zero_hours():
    assert shortest_ra_delta_deg(1.0, 359.0) == 2.0
    assert shortest_ra_delta_deg(359.0, 1.0) == -2.0


def test_goto_refine_syncs_fresh_solve_then_sends_one_regoto():
    solve_time = time.time()
    mount = DummyMountControl(DummySharedState(DummySolution(9.9, 20.0, solve_time)))
    mount._pending_goto_refine = {
        "target_ra": 10.0,
        "target_dec": 20.0,
        "accuracy_arcmin": 1.0,
        "requested_wall": solve_time - 1.0,
        "ready_at": time.monotonic() - 1.0,
        "timeout_at": time.monotonic() + 10.0,
    }

    mount._check_pending_goto_refine()

    assert mount._pending_goto_refine is None
    assert mount.sync_calls == [(9.9, 20.0)]
    assert mount.goto_calls == [(10.0, 20.0, False, None)]


def test_goto_target_uses_slew_mode_for_onstep():
    mount = DummyConnectedMount()

    assert mount.goto_target(132.0, 49.5)

    assert ("LX200 OnStep", "ON_COORD_SET", "SLEW") in mount.client.switches
    assert mount.client.numbers == [
        (
            "LX200 OnStep",
            "EQUATORIAL_EOD_COORD",
            {"RA": 132.0 / 15.0, "DEC": 49.5},
        )
    ]
    assert mount._goto_motion is not None
    assert mount.statuses[-1][0] == "slewing"


def test_sync_mount_records_coordinate_sync_for_position_service():
    mount = DummyConnectedMount()

    assert mount.sync_mount(132.0, 49.5)

    assert ("LX200 OnStep", "ON_COORD_SET", "SYNC") in mount.client.switches
    assert ("LX200 OnStep", "ON_COORD_SET", "TRACK") in mount.client.switches
    assert (
        "LX200 OnStep",
        "TELESCOPE_TRACK_STATE",
        "TRACK_ON",
    ) in mount.client.switches
    assert mount._coordinate_sync is not None
    assert mount._coordinate_sync["active"] is True
    assert mount._coordinate_sync["ra"] == 132.0
    assert mount._coordinate_sync["dec"] == 49.5
    assert mount._status_fields()["coordinate_sync"]["synced"] is True


def test_sync_mount_records_sync_context_fields():
    mount = DummyConnectedMount()

    assert mount.sync_mount(
        132.0,
        49.5,
        sync_context={
            "origin": "tracking_recovery",
            "pointing_source": "mount_imu_delta",
            "solve_age_seconds": 42.0,
        },
    )

    sync = mount._coordinate_sync
    assert sync["origin"] == "tracking_recovery"
    assert sync["pointing_source"] == "mount_imu_delta"
    assert sync["solve_age_seconds"] == 42.0


def test_sync_command_passes_context_to_sync_mount(monkeypatch):
    mount = DummyConnectedMount()
    calls = []
    monkeypatch.setattr(
        mount,
        "sync_mount",
        lambda ra, dec, sync_context=None: calls.append((ra, dec, sync_context))
        or True,
    )

    mount.handle_command(
        {
            "type": "sync",
            "ra": 10.0,
            "dec": 20.0,
            "origin": "skysafari_align",
            "pointing_source": "skysafari_target",
        }
    )

    assert calls == [
        (
            10.0,
            20.0,
            {"origin": "skysafari_align", "pointing_source": "skysafari_target"},
        )
    ]


def test_disconnected_mount_clears_coordinate_sync_anchor():
    mount = DummyConnectedMount()
    assert mount.sync_mount(132.0, 49.5)

    mount.mark_disconnected("test disconnect")

    assert mount._coordinate_sync is None
    assert "coordinate_sync" not in mount._status_fields()


def test_connection_reconcile_imports_live_indi_into_pifinder_mirror(
    monkeypatch, tmp_path
):
    data_dir = tmp_path / "PiFinder_data"
    data_dir.mkdir()
    (data_dir / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mci.config.utils, "data_dir", data_dir)
    device = "LX200 OnStepX"
    live_properties = {
        f"{device}.CONNECTION_MODE.CONNECTION_SERIAL": "On",
        f"{device}.CONNECTION_MODE.CONNECTION_TCP": "Off",
        f"{device}.DEVICE_PORT.PORT": "/dev/serial/by-id/onstep",
        f"{device}.DEVICE_BAUD_RATE.115200": "On",
    }
    monkeypatch.setattr(mci.sys_utils, "get_indi_profile_device_name", lambda: device)
    monkeypatch.setattr(
        mci.sys_utils,
        "get_indi_onstep_properties",
        lambda **_kwargs: live_properties,
    )
    monkeypatch.setattr(
        mci.sys_utils,
        "read_saved_indi_onstep_connection_config",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        mci.sys_utils,
        "apply_indi_onstep_connection",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("live INDI settings must not be reapplied")
        ),
    )
    mount = DummyConnectedMount()

    assert mount.reconcile_onstep_connection_config()

    saved = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    assert saved["onstep_connection_type"] == "usb"
    assert saved["onstep_serial_port"] == "/dev/serial/by-id/onstep"
    assert saved["onstep_serial_baud"] == 115200
    assert saved["mount_control_indi_host"] == "localhost"
    assert saved["mount_control_indi_port"] == 7624
    assert mount._connection_config_status["connection_config_reconciled"] is True
    assert mount._connection_config_status["connection_config_source"] == "indi_live"


def test_connection_reconcile_uses_pifinder_only_when_indi_is_missing(
    monkeypatch, tmp_path
):
    data_dir = tmp_path / "PiFinder_data"
    data_dir.mkdir()
    (data_dir / "config.json").write_text(
        json.dumps(
            {
                "onstep_connection_type": "usb",
                "onstep_serial_port": "/dev/serial/by-id/onstep",
                "onstep_serial_baud": 115200,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mci.config.utils, "data_dir", data_dir)
    device = "LX200 OnStepX"
    verified_properties = {
        f"{device}.CONNECTION_MODE.CONNECTION_SERIAL": "On",
        f"{device}.CONNECTION_MODE.CONNECTION_TCP": "Off",
        f"{device}.DEVICE_PORT.PORT": "/dev/serial/by-id/onstep",
        f"{device}.DEVICE_BAUD_RATE.115200": "On",
    }
    property_reads = iter(({}, verified_properties))
    apply_calls = []
    monkeypatch.setattr(mci.sys_utils, "get_indi_profile_device_name", lambda: device)
    monkeypatch.setattr(
        mci.sys_utils,
        "get_indi_onstep_properties",
        lambda **_kwargs: next(property_reads),
    )
    monkeypatch.setattr(
        mci.sys_utils,
        "read_saved_indi_onstep_connection_config",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        mci.sys_utils,
        "apply_indi_onstep_connection",
        lambda **kwargs: apply_calls.append(kwargs) or {"ok": True},
    )
    mount = DummyConnectedMount()

    assert mount.reconcile_onstep_connection_config()

    assert len(apply_calls) == 1
    assert apply_calls[0]["connection_type"] == "usb"
    assert apply_calls[0]["serial_baud"] == 115200
    assert mount._connection_config_status["connection_config_source"] == "indi_live"


def test_serial_discovery_saves_unique_verified_port_after_fresh_telemetry(
    monkeypatch, tmp_path
):
    data_dir = tmp_path / "PiFinder_data"
    data_dir.mkdir()
    (data_dir / "config.json").write_text(
        json.dumps(
            {
                "onstep_connection_type": "usb",
                "onstep_serial_port": "/dev/serial/by-id/old",
                "onstep_serial_baud": 9600,
                "gps_port": "/dev/ttyAMA0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mci.config.utils, "data_dir", data_dir)
    device = "LX200 OnStep"
    live_properties = {
        f"{device}.CONNECTION.CONNECT": "On",
        f"{device}.CONNECTION_MODE.CONNECTION_SERIAL": "On",
        f"{device}.CONNECTION_MODE.CONNECTION_TCP": "Off",
        f"{device}.DEVICE_PORT.PORT": "/dev/serial/by-id/old",
        f"{device}.DEVICE_BAUD_RATE.9600": "On",
    }
    events = []
    mount = DummyConnectedMount()
    monkeypatch.setattr(mci.sys_utils, "get_indi_profile_device_name", lambda: device)
    monkeypatch.setattr(
        mci.sys_utils,
        "get_indi_onstep_properties",
        lambda **_kwargs: live_properties,
    )
    monkeypatch.setattr(
        mci.sys_utils,
        "read_saved_indi_onstep_connection_config",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        mci.sys_utils,
        "list_onstep_serial_ports",
        lambda excluded_paths=None: [
            {
                "path": "/dev/serial/by-id/onstep",
                "resolved": "/dev/ttyUSB0",
                "label": "OnStep",
            }
        ],
    )
    monkeypatch.setattr(
        mci.sys_utils,
        "discover_onstep_serial",
        lambda **_kwargs: {
            "ok": True,
            "state": "found",
            "candidate_count": 1,
            "verified_count": 1,
            "selected": {
                "stable_path": "/dev/serial/by-id/onstep",
                "baud": 115200,
                "product": "On-Step",
                "version": "10.24c",
            },
        },
    )
    monkeypatch.setattr(
        mount,
        "_capture_usb_recovery_snapshot",
        lambda: {
            "park_state": "Unparked",
            "tracking_enabled": True,
            "slew_rate": 5,
            "track_freq_hz": None,
        },
    )
    monkeypatch.setattr(
        mount,
        "_disconnect_indi_device_for_serial_discovery",
        lambda: events.append("disconnect") or True,
    )

    def apply_connection(**kwargs):
        events.append(("apply", kwargs))
        return {"ok": True}

    monkeypatch.setattr(mci.sys_utils, "apply_indi_onstep_connection", apply_connection)
    monkeypatch.setattr(
        mount,
        "_verify_serial_discovery_telemetry",
        lambda _baseline, _expected: events.append("fresh_telemetry") or True,
    )
    monkeypatch.setattr(
        mount,
        "_restore_mount_state_snapshot",
        lambda _snapshot, _reason: events.append("restore_state") or True,
    )
    monkeypatch.setattr(
        mci.sys_utils,
        "apply_indi_onstep_properties",
        lambda properties, **_kwargs: events.append(("save", list(properties)))
        or {"ok": True},
    )
    monkeypatch.setattr(mci.os.path, "exists", lambda _path: True)

    assert mount.discover_onstep_serial_connection()

    apply_event = next(
        event for event in events if isinstance(event, tuple) and event[0] == "apply"
    )
    assert apply_event[1]["serial_port"] == "/dev/serial/by-id/onstep"
    assert apply_event[1]["serial_baud"] == 115200
    assert apply_event[1]["save_config"] is False
    assert events.index("fresh_telemetry") < events.index("restore_state")
    save_index = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, tuple) and event[0] == "save"
    )
    assert events.index("restore_state") < save_index
    saved = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    assert saved["onstep_serial_port"] == "/dev/serial/by-id/onstep"
    assert saved["onstep_serial_baud"] == 115200
    assert mount._serial_discovery_status["serial_discovery_state"] == "success"


def test_serial_discovery_ambiguous_result_rolls_back_without_saving(monkeypatch):
    mount = DummyConnectedMount()
    device = "LX200 OnStep"
    live_properties = {
        f"{device}.CONNECTION.CONNECT": "On",
        f"{device}.CONNECTION_MODE.CONNECTION_SERIAL": "On",
        f"{device}.CONNECTION_MODE.CONNECTION_TCP": "Off",
        f"{device}.DEVICE_PORT.PORT": "/dev/serial/by-id/old",
        f"{device}.DEVICE_BAUD_RATE.115200": "On",
    }
    monkeypatch.setattr(mci.sys_utils, "get_indi_profile_device_name", lambda: device)
    monkeypatch.setattr(
        mci.sys_utils,
        "get_indi_onstep_properties",
        lambda **_kwargs: live_properties,
    )
    monkeypatch.setattr(
        mci.sys_utils,
        "read_saved_indi_onstep_connection_config",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        mci.sys_utils,
        "list_onstep_serial_ports",
        lambda excluded_paths=None: [
            {"path": "/dev/one", "resolved": "/dev/ttyUSB0"},
            {"path": "/dev/two", "resolved": "/dev/ttyUSB1"},
        ],
    )
    monkeypatch.setattr(
        mci.sys_utils,
        "discover_onstep_serial",
        lambda **_kwargs: {
            "ok": False,
            "state": "ambiguous",
            "candidate_count": 2,
            "verified_count": 2,
        },
    )
    monkeypatch.setattr(
        mount, "_capture_usb_recovery_snapshot", lambda: {"park_state": "Unparked"}
    )
    monkeypatch.setattr(
        mount, "_disconnect_indi_device_for_serial_discovery", lambda: True
    )
    rollback_calls = []
    monkeypatch.setattr(
        mount,
        "_rollback_serial_discovery",
        lambda *args: rollback_calls.append(args) or True,
    )
    monkeypatch.setattr(
        mci.sys_utils,
        "apply_indi_onstep_properties",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ambiguous discovery must not save settings")
        ),
    )

    assert not mount.discover_onstep_serial_connection()
    assert len(rollback_calls) == 1
    assert mount._serial_discovery_status["serial_discovery_state"] == "failed"
    assert (
        "Multiple verified" in mount._serial_discovery_status["serial_discovery_error"]
    )


def test_serial_discovery_refuses_to_interrupt_manual_movement(monkeypatch):
    mount = DummyConnectedMount()
    mount._manual_motion_direction = "east"
    monkeypatch.setattr(
        mci.sys_utils,
        "list_onstep_serial_ports",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("busy discovery must stop before port enumeration")
        ),
    )

    assert not mount.discover_onstep_serial_connection()
    assert mount._serial_discovery_status["serial_discovery_state"] == "failed"
    assert (
        "Manual mount movement"
        in mount._serial_discovery_status["serial_discovery_error"]
    )


def test_serial_discovery_live_readback_covers_missed_pyindi_callback(monkeypatch):
    mount = DummyConnectedMount()
    device = "LX200 OnStep"
    expected = mci.sys_utils.normalize_onstep_connection_config(
        {
            "connection_type": "usb",
            "serial_port": "/dev/serial/by-id/onstep",
            "serial_baud": 115200,
        }
    )
    properties = {
        f"{device}.CONNECTION.CONNECT": "On",
        f"{device}.CONNECTION_MODE.CONNECTION_SERIAL": "On",
        f"{device}.CONNECTION_MODE.CONNECTION_TCP": "Off",
        f"{device}.DEVICE_PORT.PORT": "/dev/serial/by-id/onstep",
        f"{device}.DEVICE_BAUD_RATE.115200": "On",
        f"{device}.EQUATORIAL_EOD_COORD.RA": "5.25",
        f"{device}.EQUATORIAL_EOD_COORD.DEC": "52.18",
        f"{device}.OnStep Status.:GU# return": "NpvAT190",
    }
    monkeypatch.setattr(mount, "_wait_for_device_connected", lambda _timeout: True)
    monkeypatch.setattr(
        mci.sys_utils,
        "get_indi_onstep_properties",
        lambda **_kwargs: properties,
    )
    mount.connected = False
    baseline = (
        mount._position_update_generation,
        mount._onstep_status_generation,
    )

    assert mount._verify_serial_discovery_telemetry(baseline, expected)
    assert mount.connected is True


def test_usb_reinsert_recovers_once_after_stable_by_id_return(monkeypatch):
    mount = DummyConnectedMount()
    present = {"value": True}
    monkeypatch.setattr(mci.os.path, "exists", lambda _path: present["value"])
    monkeypatch.setattr(
        mount,
        "_capture_usb_recovery_snapshot",
        lambda: {
            "park_state": "Unparked",
            "tracking_enabled": True,
            "slew_rate": 5,
            "track_freq_hz": None,
        },
    )
    recovery_calls = []

    def recover_once():
        recovery_calls.append(True)
        mount.connected = True
        mount._usb_absent_latched = False
        mount._usb_recovery_status["connection_health"] = "healthy"
        return True

    monkeypatch.setattr(mount, "_recover_usb_serial_once", recover_once)
    mount._configure_usb_serial_monitor(
        {
            "connection_type": "usb",
            "serial_port": "/dev/serial/by-id/onstep",
        }
    )

    present["value"] = False
    mount._check_usb_serial_reinsert(now=1.0)
    assert mount.connected is False
    assert mount._usb_recovery_status["connection_health"] == "usb_absent"
    assert recovery_calls == []
    assert not mount._usb_auto_connect_allowed()

    present["value"] = True
    mount._check_usb_serial_reinsert(now=2.0)
    assert mount._usb_recovery_status["connection_health"] == "return_debounce"
    mount._check_usb_serial_reinsert(now=3.0)
    assert recovery_calls == []
    mount._check_usb_serial_reinsert(now=4.0)
    mount._check_usb_serial_reinsert(now=8.0)

    assert recovery_calls == [True]
    assert mount._usb_reconnect_used is True
    assert mount._usb_auto_connect_allowed()


def test_usb_monitor_initial_absent_allows_normal_connect_when_device_appears(
    monkeypatch,
):
    mount = DummyConnectedMount()
    present = {"value": False}
    monkeypatch.setattr(mci.os.path, "exists", lambda _path: present["value"])
    recovery_calls = []
    monkeypatch.setattr(
        mount,
        "_recover_usb_serial_once",
        lambda: recovery_calls.append(True) or True,
    )

    mount._configure_usb_serial_monitor(
        {
            "connection_type": "usb",
            "serial_port": "/dev/serial/by-id/onstep",
        }
    )
    assert not mount._usb_auto_connect_allowed()

    present["value"] = True
    mount._check_usb_serial_reinsert(now=1.0)

    assert recovery_calls == []
    assert mount._usb_recovery_status["connection_health"] == "healthy"
    assert mount._usb_auto_connect_allowed()


def test_usb_recovery_resets_device_session_once_without_driver_restart(monkeypatch):
    mount = DummyConnectedMount()
    mount._usb_recovery_snapshot = {
        "park_state": "Unparked",
        "tracking_enabled": True,
        "slew_rate": 5,
        "track_freq_hz": None,
    }
    applied = []
    connect_calls = []
    monkeypatch.setattr(
        mci.sys_utils,
        "apply_indi_onstep_properties",
        lambda properties, **kwargs: applied.append((properties, kwargs))
        or {"ok": True},
    )
    monkeypatch.setattr(mount, "_wait_for_indi_device_disconnected", lambda _t: True)

    def connect(**kwargs):
        connect_calls.append(kwargs)
        mount.connected = True
        return True

    monkeypatch.setattr(mount, "connect", connect)
    monkeypatch.setattr(mount, "_restore_usb_recovery_snapshot", lambda: True)

    assert mount._recover_usb_serial_once()

    assert applied[0][0] == ["LX200 OnStep.CONNECTION.DISCONNECT=On"]
    assert connect_calls == [
        {
            "announce": False,
            "sync_on_connect": False,
            "preserve_mount_state": True,
            "require_fresh_telemetry": True,
            "publish_connected": False,
        }
    ]
    assert mount._usb_recovery_status["connection_health"] == "healthy"
    assert mount._usb_recovery_status["recovery_attempt"] == 1


def test_usb_recovery_failure_does_not_fall_through_to_auto_connect(monkeypatch):
    mount = DummyConnectedMount()
    mount._usb_serial_path = "/dev/serial/by-id/onstep"
    mount._usb_serial_present = True
    mount._usb_absent_latched = True
    mount._usb_reconnect_used = True
    monkeypatch.setattr(
        mci.sys_utils,
        "apply_indi_onstep_properties",
        lambda *_args, **_kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        mount, "_wait_for_indi_device_disconnected", lambda _timeout: False
    )

    assert not mount._recover_usb_serial_once()

    assert mount._usb_recovery_status["connection_health"] == "recovery_failed"
    assert not mount._usb_auto_connect_allowed()


def test_usb_recovery_exception_is_latched_and_not_retried(monkeypatch):
    mount = DummyConnectedMount()
    mount._usb_serial_path = "/dev/serial/by-id/onstep"
    mount._usb_serial_present = True
    mount._usb_absent_latched = True
    mount._usb_reconnect_used = True

    def raise_disconnect(*_args, **_kwargs):
        raise RuntimeError("indi_setprop unavailable")

    monkeypatch.setattr(
        mci.sys_utils,
        "apply_indi_onstep_properties",
        raise_disconnect,
    )

    assert not mount._recover_usb_serial_once()

    assert mount._usb_recovery_status["connection_health"] == "recovery_failed"
    assert "indi_setprop unavailable" in mount._usb_recovery_status["recovery_error"]
    assert not mount._usb_auto_connect_allowed()


@pytest.mark.parametrize("preserve_options", [{}, {"preserve_mount_state": True}])
def test_connect_preserves_mount_state_by_default_and_during_recovery(
    monkeypatch, preserve_options
):
    class RecoveryDevice:
        def getDeviceName(self):
            return "LX200 OnStepX"

        def isConnected(self):
            return True

    class RecoveryClient:
        instances = []

        def __init__(self, mount_control, generation=0):
            self.mount_control = mount_control
            self.generation = generation
            self.device = RecoveryDevice()
            self.unpark_calls = 0
            self.tracking_calls = 0
            self.__class__.instances.append(self)

        def setServer(self, _host, _port):
            return None

        def connectServer(self):
            return True

        def get_telescope_device(self):
            return self.device

        def _wait_for_property(self, _device, _name, timeout=5.0):
            return True

        def isServerConnected(self):
            return True

        def unpark_mount(self, _device):
            self.unpark_calls += 1
            return True

        def enable_tracking(self, _device):
            self.tracking_calls += 1
            return True

    mount = DummyMountControl()
    sync_calls = []
    fresh_calls = []
    monkeypatch.setattr(mci, "PyIndi", object())
    monkeypatch.setattr(mci, "PiFinderIndiClient", RecoveryClient)
    monkeypatch.setattr(mount, "_use_direct_onstep_location_time_sync", lambda: False)
    monkeypatch.setattr(
        mount, "sync_location_time", lambda **kwargs: sync_calls.append(kwargs) or True
    )
    monkeypatch.setattr(
        mount,
        "_wait_for_fresh_telemetry",
        lambda position, status, timeout: fresh_calls.append(
            (position, status, timeout)
        )
        or True,
    )

    assert mount.connect(
        announce=False,
        sync_on_connect=False,
        require_fresh_telemetry=True,
        publish_connected=False,
        **preserve_options,
    )

    client = RecoveryClient.instances[-1]
    assert sync_calls == []
    assert client.unpark_calls == 0
    assert client.tracking_calls == 0
    assert fresh_calls == [(0, 0, mci.USB_SERIAL_FRESH_TELEMETRY_WAIT_SECONDS)]


def test_stale_indi_client_disconnect_callback_is_ignored():
    mount = DummyConnectedMount()
    mount._client_generation = 5
    status_count = len(mount.statuses)

    mount.mark_disconnected("old callback", client_generation=4)

    assert mount.connected is True
    assert mount.device is not None
    assert len(mount.statuses) == status_count


def test_late_position_callback_does_not_overwrite_disconnected_status():
    mount = DummyConnectedMount()
    mount.connected = False
    status_count = len(mount.statuses)

    mount.receive_current_position(120.0, 45.0)

    assert mount._position_update_generation == 1
    assert mount.current_ra == 120.0
    assert mount.current_dec == 45.0
    assert len(mount.statuses) == status_count


def test_goto_target_fails_when_indi_target_is_not_accepted():
    mount = DummyConnectedMount()
    mount.accept_goto_target = False

    assert not mount.goto_target(132.0, 49.5)

    assert mount.client.numbers == [
        (
            "LX200 OnStep",
            "EQUATORIAL_EOD_COORD",
            {"RA": 132.0 / 15.0, "DEC": 49.5},
        ),
        (
            "LX200 OnStep",
            "EQUATORIAL_EOD_COORD",
            {"RA": 132.0 / 15.0, "DEC": 49.5},
        ),
    ]
    assert mount._goto_motion is None
    assert mount._last_goto_target is None
    assert mount.statuses[-1][0] == "goto_failed"


def test_start_mount_alignment_session_uses_onstep_align_properties():
    mount = DummyConnectedMount()

    assert mount.start_mount_alignment_session(3)

    assert mount.client.switches == [
        ("LX200 OnStep", "AlignStars", "3"),
        ("LX200 OnStep", "NewAlignStar", "0"),
    ]


def test_accept_mount_alignment_point_uses_onstep_align_add_property():
    mount = DummyConnectedMount()

    assert mount.accept_mount_alignment_point()

    assert mount.client.switches == [
        ("LX200 OnStep", "NewAlignStar", "1"),
    ]


def test_goto_motion_completes_after_stable_idle(monkeypatch):
    mount = DummyConnectedMount()
    clock = [100.0]

    def fake_monotonic():
        return clock[0]

    monkeypatch.setattr(mci.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(mount, "_read_current_position", lambda: None)
    monkeypatch.setattr(mount, "_indi_mount_is_busy", lambda: False)

    assert mount.goto_target(132.0, 49.5)
    mount._goto_motion["started_at"] = clock[0] - 2.0
    mount._check_goto_motion()

    assert mount._goto_motion is not None

    clock[0] += mci.GOTO_COMPLETE_STABLE_SECONDS + 0.1
    mount._check_goto_motion()

    assert mount._goto_motion is None
    assert mount.statuses[-1][0] == "connected"
    assert mount.statuses[-1][1] == "GoTo complete"


def test_goto_motion_waits_for_stable_position(monkeypatch):
    mount = DummyConnectedMount()
    clock = [100.0]
    current_position = [(132.0, 49.5)]

    def fake_monotonic():
        return clock[0]

    def fake_position():
        return current_position[-1]

    monkeypatch.setattr(mci.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(mount, "_read_current_position", fake_position)
    monkeypatch.setattr(mount, "_indi_mount_is_busy", lambda: False)

    assert mount.goto_target(132.0, 49.5)
    mount._goto_motion["started_at"] = clock[0] - 2.0
    mount._check_goto_motion()

    assert mount._goto_motion is not None

    clock[0] += mci.GOTO_COMPLETE_STABLE_SECONDS + 0.1
    current_position.append((132.08, 49.5))
    mount._check_goto_motion()

    assert mount._goto_motion is not None

    clock[0] += mci.GOTO_COMPLETE_STABLE_SECONDS + 0.1
    mount._check_goto_motion()

    assert mount._goto_motion is not None

    clock[0] += mci.GOTO_COMPLETE_STABLE_SECONDS + 0.1
    mount._check_goto_motion()

    assert mount._goto_motion is None
    assert mount.statuses[-1][1] == "GoTo complete"


def test_goto_motion_waits_while_indi_state_is_busy(monkeypatch):
    mount = DummyConnectedMount()
    monkeypatch.setattr(mount, "_indi_mount_is_busy", lambda: True)

    assert mount.goto_target(132.0, 49.5)
    mount._goto_motion["started_at"] = time.monotonic() - 2.0
    mount._check_goto_motion()

    assert mount._goto_motion is not None
    assert mount.statuses[-1][0] == "slewing"


def test_goto_motion_publishes_mount_readback_while_busy(monkeypatch):
    mount = DummyConnectedMount()
    clock = [100.0]
    cached_reads = []

    def fake_monotonic():
        return clock[0]

    def fake_cached_position(write_status=True):
        cached_reads.append(write_status)
        mount.current_ra = 101.25
        mount.current_dec = -12.5
        return (mount.current_ra, mount.current_dec)

    monkeypatch.setattr(mci.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(mount, "_indi_mount_is_busy", lambda: True)
    monkeypatch.setattr(mount, "_read_cached_current_position", fake_cached_position)

    assert mount.goto_target(132.0, 49.5)
    mount._goto_motion["started_at"] = clock[0] - 2.0
    mount._check_goto_motion()

    assert cached_reads == [False]
    assert mount._goto_motion is not None
    assert mount.statuses[-1][0] == "slewing"
    assert mount.statuses[-1][1] == "GoTo in progress"
    assert mount.statuses[-1][2]["ra"] == 101.25
    assert mount.statuses[-1][2]["dec"] == -12.5
    assert mount.statuses[-1][2]["target_ra"] == 132.0
    assert mount.statuses[-1][2]["target_dec"] == 49.5
    assert mount.statuses[-1][2]["target_error_deg"] > 0.0
    assert mount.statuses[-1][2]["mount_motion_active"] is True
    assert mount.statuses[-1][2]["mount_motion_type"] == "goto"
    assert mount.statuses[-1][2]["mount_readback_priority"] is True


def test_goto_motion_waits_for_onstep_no_goto_after_active(monkeypatch):
    mount = DummyConnectedMount()
    clock = [100.0]
    onstep_states = [False, True, True]

    def fake_monotonic():
        return clock[0]

    def fake_onstep_complete():
        return onstep_states.pop(0) if onstep_states else True

    monkeypatch.setattr(mci.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(mount, "_read_current_position", lambda: None)
    monkeypatch.setattr(mount, "_indi_mount_is_busy", lambda: False)
    monkeypatch.setattr(mount, "_onstep_goto_complete", fake_onstep_complete)

    assert mount.goto_target(132.0, 49.5)
    mount._goto_motion["started_at"] = clock[0] - 5.0
    mount._check_goto_motion()

    assert mount._goto_motion is not None
    assert mount._goto_motion["onstep_seen_goto_active"]

    clock[0] += mci.GOTO_COMPLETE_STABLE_SECONDS + 0.1
    mount._check_goto_motion()

    assert mount._goto_motion is not None

    clock[0] += mci.GOTO_COMPLETE_STABLE_SECONDS + 0.1
    mount._check_goto_motion()

    assert mount._goto_motion is None
    assert mount.statuses[-1][1] == "GoTo complete"


def test_goto_refine_completes_without_regoto_inside_accuracy():
    solve_time = time.time()
    mount = DummyMountControl(DummySharedState(DummySolution(10.0, 20.0, solve_time)))
    mount._pending_goto_refine = {
        "target_ra": 10.0,
        "target_dec": 20.0,
        "accuracy_arcmin": 1.0,
        "requested_wall": solve_time - 1.0,
        "ready_at": time.monotonic() - 1.0,
        "timeout_at": time.monotonic() + 10.0,
    }

    mount._check_pending_goto_refine()

    assert mount._pending_goto_refine is None
    assert mount.sync_calls == []
    assert mount.goto_calls == []


def test_guide_correction_requires_a_target():
    mount = DummyMountControl()

    assert not mount.toggle_guide_correction(enabled=True)
    assert not mount._guide_correction_enabled


def _manual_approach_mount(monkeypatch, axis_errors=(0.2, 0.03)):
    clock = [1000.0]
    observation = [999.9]
    monkeypatch.setattr(mci.time, "time", lambda: clock[0])
    monkeypatch.setattr(mci.time, "monotonic", lambda: clock[0])
    mount = DummyConnectedMount()
    mount.shared_state = DummySharedState(DummySolution(10.1, 20.0, 999.9))
    monkeypatch.setattr(
        mount, "_current_plate_solve", lambda: (10.1, 20.0, observation[0])
    )
    errors = list(axis_errors)
    monkeypatch.setattr(mci.calc_utils, "pointing_axis_errors", lambda *args: errors)
    motions = []
    monkeypatch.setattr(
        mount,
        "_apply_indi_properties",
        lambda props, *args: motions.append(props) or True,
    )
    pulses = []
    monkeypatch.setattr(mount, "_guide_pulse_supported", lambda: True)
    monkeypatch.setattr(mount, "_apply_guide_pulse", lambda *args: pulses.append(args))
    assert mount.toggle_guide_correction(True, 10.0, 20.0, 1.5, manual_approach=True)
    return mount, clock, observation, errors, motions, pulses


def _approach_ack(mount, rate, state="ok"):
    mount.receive_sync_property(
        "TELESCOPE_SLEW_RATE", state, {str(rate): True}, mount._client_generation
    )


def test_goto_approach_waits_for_speed_ack_and_uses_physical_altaz(monkeypatch):
    mount, clock, _observation, _errors, motions, pulses = _manual_approach_mount(
        monkeypatch
    )
    saved_rate = mount.slew_rate
    _approach_ack(mount, 6)  # Cached matching state is not an acknowledgement.
    mount._check_guide_correction()
    assert mount.client.switches[-1][1:] == ("TELESCOPE_SLEW_RATE", "6")
    assert not motions and not pulses
    _approach_ack(mount, 6, "busy")
    mount._check_guide_correction()
    assert not motions
    _approach_ack(mount, 6)
    mount._check_guide_correction()
    # Target RA is lower, but target azimuth is higher: physical east, not west.
    assert mount._manual_motion_direction == "east"
    assert mount._manual_motion_origin == "guide_correction"
    assert motions[-1] == ["LX200 OnStep.TELESCOPE_MOTION_WE.MOTION_WEST=On"]
    assert mount._manual_motion_deadline - clock[0] <= 1.0
    assert mount.slew_rate == saved_rate
    assert not pulses


@pytest.mark.parametrize("failure", ["alert", "timeout", "disconnect"])
def test_goto_approach_speed_failure_never_starts_motion(monkeypatch, failure):
    mount, clock, _observation, _errors, motions, pulses = _manual_approach_mount(
        monkeypatch
    )
    mount._check_guide_correction()
    if failure == "alert":
        _approach_ack(mount, 6, "alert")
    elif failure == "timeout":
        clock[0] += 5.1
    else:
        mount.mark_disconnected("test disconnect")
    mount._check_guide_correction()
    assert not motions and not pulses
    assert not mount._guide_correction_enabled
    assert mount._guide_correction_mode == "failed"


def test_goto_approach_stops_and_waits_for_post_stop_solve_before_pulse(monkeypatch):
    mount, clock, observation, errors, motions, pulses = _manual_approach_mount(
        monkeypatch, axis_errors=(0.02, -0.12)
    )
    mount._check_guide_correction()
    _approach_ack(mount, 5)
    mount._check_guide_correction()
    assert mount._manual_motion_direction == "south"
    clock[0] += 1.1
    mount._check_manual_motion_deadline()
    assert mount._manual_motion_direction is None
    assert all("=Off" in prop for prop in motions[-1])
    assert not any("ABORT" in prop for prop in motions[-1])
    assert mount._guide_correction_mode == "settling"
    clock[0] += 0.6
    # Newer than the previous solve, but still taken during the approach.
    observation[0] = 1000.8
    mount._check_guide_correction()
    assert not pulses and len(motions) == 2
    errors[:] = [0.02, -0.03]
    monkeypatch.setattr(mount, "_current_plate_solve", lambda: (10.02, 20.0, clock[0]))
    mount._check_guide_correction()
    assert len(pulses) == 1
    assert mount._guide_correction_mode == "pulse"
    assert mount._confirmed_guide_rates == (0.5, 0.5)
    assert mount.client.numbers[-1][1] == "GUIDE_RATE"


@pytest.mark.parametrize("when", ["waiting_speed", "moving"])
def test_disabling_goto_approach_cancels_pending_or_active_move(monkeypatch, when):
    mount, _clock, _observation, _errors, motions, pulses = _manual_approach_mount(
        monkeypatch
    )
    mount._check_guide_correction()
    if when == "moving":
        _approach_ack(mount, 6)
        mount._check_guide_correction()
    mount.toggle_guide_correction(False)
    _approach_ack(mount, 6)
    mount._check_guide_correction()
    assert mount._manual_motion_direction is None
    assert mount._approach_rate_request is None
    assert mount._guide_correction_mode == "off"
    assert len(motions) == (2 if when == "moving" else 0)
    assert not pulses


def test_goto_approach_requests_recovery_after_three_moves_without_progress(
    monkeypatch,
):
    mount, clock, observation, _errors, motions, _pulses = _manual_approach_mount(
        monkeypatch
    )
    for _ in range(4):
        observation[0] = clock[0]
        mount._check_guide_correction()
        _approach_ack(mount, 6)
        mount._check_guide_correction()
        clock[0] += 1.1
        mount._check_manual_motion_deadline()
        clock[0] += 0.6
    assert not mount._guide_correction_enabled
    assert not mount._guide_manual_approach
    assert mount._guide_correction_mode == "reacquire"
    observation[0] = clock[0]
    mount._check_guide_correction()
    assert not _pulses
    assert len(motions) == 6  # Three bounded moves, each followed by stop.


def test_tracking_guide_does_not_enable_manual_approach(monkeypatch):
    mount, _clock, _observation, _errors, motions, pulses = _manual_approach_mount(
        monkeypatch
    )
    mount.toggle_guide_correction(True, 10.0, 20.0, 1.5)
    mount._check_guide_correction()
    assert not mount._guide_manual_approach
    assert not motions and len(pulses) == 1


def test_final_manual_approach_slows_down_before_two_arcmin_band(monkeypatch):
    mount, _clock, _observation, _errors, motions, pulses = _manual_approach_mount(
        monkeypatch, axis_errors=(0.0, 0.04)
    )
    monkeypatch.setattr(mount, "_current_plate_solve", lambda: (10.01, 20.0, 999.9))
    mount._check_guide_correction()
    assert mount.client.switches[-1][1:] == ("TELESCOPE_SLEW_RATE", "4")
    _approach_ack(mount, 4)
    mount._check_guide_correction()
    assert mount._manual_motion_direction == "north"
    assert len(motions) == 1 and not pulses


def test_guide_correction_pulses_toward_target_on_fresh_solve(monkeypatch):
    solve_time = time.time()
    mount = DummyMountControl(DummySharedState(DummySolution(9.9, 20.0, solve_time)))
    mount._last_goto_target = (10.0, 20.0)
    monkeypatch.setattr(mount, "_select_guide_rate_for_error", lambda error: True)

    assert mount.toggle_guide_correction(enabled=True, accuracy_arcmin=1.0)
    mount._guide_correction_next_at = time.monotonic() - 1.0
    mount._check_guide_correction()

    assert mount._manual_motion_direction == "east"
    assert mount._guide_correction_last_solve_time == solve_time


def test_guide_correction_does_not_pulse_inside_accuracy():
    solve_time = time.time()
    mount = DummyMountControl(DummySharedState(DummySolution(10.0, 20.0, solve_time)))
    mount._last_goto_target = (10.0, 20.0)

    assert mount.toggle_guide_correction(enabled=True, accuracy_arcmin=1.0)
    mount._guide_correction_next_at = time.monotonic() - 1.0
    mount._check_guide_correction()

    assert mount._manual_motion_direction is None


@pytest.mark.parametrize("solve_time", [980.0, 1001.0, float("nan"), float("inf")])
def test_guide_correction_rejects_old_or_invalid_solve_then_resumes(
    monkeypatch, solve_time
):
    monkeypatch.setattr(mci.time, "time", lambda: 1000.0)
    state = DummySharedState(DummySolution(9.9, 20.0, solve_time))
    mount = DummyMountControl(state)
    mount._last_goto_target = (10.0, 20.0)
    monkeypatch.setattr(mount, "_select_guide_rate_for_error", lambda error: True)
    assert mount.toggle_guide_correction(enabled=True, accuracy_arcmin=1.0)
    mount._guide_correction_next_at = 0.0
    mount._check_guide_correction()
    assert mount._manual_motion_direction is None
    assert mount._guide_correction_last_solve_time == 0.0

    state._solution = DummySolution(9.9, 20.0, 999.0)
    mount._check_guide_correction()
    assert mount._manual_motion_direction == "east"
    assert mount._guide_correction_last_solve_time == 999.0


def test_pulse_event_preserves_each_axis_and_distinguishes_rejected_send(caplog):
    mount = DummyConnectedMount()
    mount._guide_correction_observation = {"frame_id": 42, "exposure_end": 1000.0}
    mount._guide_correction_target = (10.0, 20.0)
    with caplog.at_level("INFO", logger=mci.logger.name):
        assert mount._send_guide_pulse("north", 2500)
        mount.client.set_number = lambda *args: False
        assert not mount._send_guide_pulse("west", 200)
    events = [
        json.loads(r.message.split("Guide pulse event ", 1)[1])
        for r in caplog.records
        if r.message.startswith("Guide pulse event ")
    ]
    assert [e["direction"] for e in events] == ["north", "west"]
    assert events[0]["observation"]["frame_id"] == 42
    assert events[0]["expected_end_monotonic"] == pytest.approx(
        events[0]["returned_monotonic"] + 2.5
    )
    assert events[1]["expected_end_monotonic"] is None
    assert all(e["end_confirmed"] is False for e in events)


def test_retained_solve_is_not_labelled_with_newer_failed_frame():
    solution = DummySolution(9.9, 20.0, 999.0)
    solution.last_solve_attempt = 1000.0
    solution.diagnostics = SimpleNamespace(FrameId=43, solve_path="cedar_512")
    mount = DummyMountControl(DummySharedState(solution))
    assert mount._current_plate_solve() == (9.9, 20.0, 999.0)
    assert mount._guide_correction_observation["frame_id"] is None
    assert mount._guide_correction_observation["solve_path"] is None

    solution.last_solve_attempt = 999.0
    assert mount._current_plate_solve() == (9.9, 20.0, 999.0)
    assert mount._guide_correction_observation["frame_id"] == 43


def test_guide_rate_boosts_to_fast_for_large_error(monkeypatch):
    mount = DummyConnectedMount()
    mount._guide_correction_accuracy_arcmin = 6.0
    monkeypatch.setattr(mount, "_current_guide_rate_x", lambda: (0.5, 0.5))

    mount._select_guide_rate_for_error(60.0)

    assert mount.client.numbers[-1] == (
        "LX200 OnStep",
        "GUIDE_RATE",
        {
            "GUIDE_RATE_WE": mci.GUIDE_RATE_FAST_X,
            "GUIDE_RATE_NS": mci.GUIDE_RATE_FAST_X,
        },
    )
    assert mount._guide_rate_boosted
    assert mount._guide_rate_writable is True


def test_three_arcmin_refine_uses_fast_rate_for_observed_near_error(monkeypatch):
    """A roughly 0.1-degree miss should no longer enter the slow fine band."""
    mount = DummyConnectedMount()
    mount._guide_correction_accuracy_arcmin = 3.0
    monkeypatch.setattr(mount, "_current_guide_rate_x", lambda: (0.5, 0.5))

    mount._select_guide_rate_for_error(8.0)

    assert mount.client.numbers[-1][2] == {
        "GUIDE_RATE_WE": mci.GUIDE_RATE_FAST_X,
        "GUIDE_RATE_NS": mci.GUIDE_RATE_FAST_X,
    }
    assert mount._guide_rate_boosted


def test_guide_rate_drops_to_fine_inside_fast_band(monkeypatch):
    mount = DummyConnectedMount()
    mount._guide_correction_accuracy_arcmin = 6.0
    mount._guide_rate_boosted = True
    monkeypatch.setattr(mount, "_current_guide_rate_x", lambda: (1.0, 1.0))

    # 10' error is above the 6' accuracy but inside the 12' fast band.
    mount._select_guide_rate_for_error(10.0)

    assert mount.client.numbers[-1][2] == {
        "GUIDE_RATE_WE": mci.GUIDE_RATE_FINE_X,
        "GUIDE_RATE_NS": mci.GUIDE_RATE_FINE_X,
    }
    assert not mount._guide_rate_boosted


def test_guide_rate_not_rewritten_when_already_at_desired(monkeypatch):
    mount = DummyConnectedMount()
    mount._guide_correction_accuracy_arcmin = 6.0
    mount._guide_rate_needs_reassert = False
    mount._confirmed_guide_rates = (1.0, 1.0)
    monkeypatch.setattr(mount, "_current_guide_rate_x", lambda: (1.0, 1.0))

    mount._select_guide_rate_for_error(60.0)

    assert mount.client.numbers == []
    assert mount._guide_rate_boosted


def test_guide_disable_does_not_change_in_flight_pulse_speed():
    mount = DummyConnectedMount()
    mount._guide_rate_boosted = True

    assert mount.toggle_guide_correction(enabled=False)

    assert mount.client.numbers == []
    assert not mount._guide_rate_boosted


def test_guide_rate_write_rejection_stops_future_attempts(monkeypatch):
    mount = DummyConnectedMount()
    mount._guide_correction_accuracy_arcmin = 6.0
    monkeypatch.setattr(mount, "_current_guide_rate_x", lambda: (0.5, 0.5))
    monkeypatch.setattr(mount.client, "set_number", lambda *args, **kwargs: False)

    mount._select_guide_rate_for_error(60.0)

    assert mount._guide_rate_writable is False
    assert not mount._guide_rate_boosted

    attempts = []
    monkeypatch.setattr(
        mount, "_set_guide_rate", lambda rate: attempts.append(rate) or True
    )
    mount._select_guide_rate_for_error(60.0)
    mount._guide_rate_boosted = True
    mount._restore_fine_guide_rate()

    assert attempts == []


def test_manual_and_guide_profiles_survive_restart_independently():
    mount = DummyMountControl()
    assert mount.set_slew_rate(7)
    assert mount.set_guide_rate(1.0)
    restored = DummyMountControl()
    assert (restored.slew_rate, restored.guide_rate_we, restored.guide_rate_ns) == (
        7,
        1.0,
        1.0,
    )
    assert restored.set_slew_rate(6)
    assert restored.set_guide_rate(0.5)
    again = DummyMountControl()
    assert (again.slew_rate, again.guide_rate_we, again.guide_rate_ns) == (6, 0.5, 0.5)


def test_manual_then_guide_reasserts_even_when_guide_cache_matches(monkeypatch):
    mount = DummyConnectedMount()
    mount.slew_rate = 7
    monkeypatch.setattr(mount, "_current_guide_rate_x", lambda: (0.5, 0.5))
    assert mount._select_guide_rate_for_error(0.0)
    assert mount._slew_rate_polluted
    assert mount._reassert_slew_rate()
    assert mount._guide_rate_needs_reassert
    assert mount._select_guide_rate_for_error(0.0)
    assert len(mount.client.numbers) == 2
    assert mount.client.switches[-1][-1] == "7"
    assert mount.slew_rate == 7
    # A second guide-only cycle may reuse the known selector.
    assert mount._select_guide_rate_for_error(0.0)
    assert len(mount.client.numbers) == 2


def test_automatic_guide_boost_does_not_persist_over_fine_profile(monkeypatch):
    mount = DummyConnectedMount()
    assert mount.set_guide_rate(0.25)
    monkeypatch.setattr(mount, "_current_guide_rate_x", lambda: (0.25, 0.25))
    assert mount._select_guide_rate_for_error(60.0)
    assert mount.client.numbers[-1][2] == {"GUIDE_RATE_WE": 1.0, "GUIDE_RATE_NS": 1.0}
    restored = DummyMountControl()
    assert (restored.guide_rate_we, restored.guide_rate_ns) == (0.25, 0.25)


def test_speed_refresh_ignores_temporary_driver_guide_selector(monkeypatch):
    mount = DummyConnectedMount()
    mount.slew_rate = 7
    monkeypatch.setattr(mount, "_read_driver_slew_rate", lambda: 1)
    assert mount.refresh_slew_rate() == 7
    monkeypatch.setattr(mount, "_device_is_connected", lambda: True)
    monkeypatch.setattr(mount, "_read_cached_current_position", lambda: None)
    mount._last_status_heartbeat_at = 0.0
    mount._write_status_heartbeat()
    assert mount.slew_rate == 7


def test_manual_speed_change_during_pulse_is_saved_and_deferred():
    mount = DummyConnectedMount()
    mount._guide_pulse_until = time.monotonic() + 2.5
    assert mount.set_slew_rate(6)
    assert mount.client.switches == []
    assert DummyMountControl().slew_rate == 6
    mount._check_slew_rate_reassert()
    assert mount.client.switches == []
    mount._guide_pulse_until = 0.0
    mount._slew_rate_reassert_at = 0.0
    mount._check_slew_rate_reassert()
    assert mount.client.switches[-1][-1] == "6"


def test_guide_setting_during_manual_move_only_saves():
    mount = DummyConnectedMount()
    mount._manual_motion_direction = "east"
    mount._manual_motion_origin = "user"
    assert mount.set_guide_rate(0.25)
    assert mount.client.numbers == []
    assert mount.client.switches == []
    assert not mount._select_guide_rate_for_error(50.0)
    assert DummyMountControl().guide_rate_we == 0.25


@pytest.mark.parametrize("reject", ["none", "abort", "speed"])
def test_manual_takeover_orders_abort_speed_then_motion(monkeypatch, reject):
    mount = DummyConnectedMount()
    mount._guide_pulse_until = time.monotonic() + 2.5
    events = []

    def apply(properties, *args):
        is_abort = any("ABORT" in p for p in properties)
        events.append("abort" if is_abort else "motion")
        return not (reject == "abort" and is_abort)

    def switch(*args):
        events.append("speed")
        return reject != "speed"

    monkeypatch.setattr(mount, "_apply_indi_properties", apply)
    monkeypatch.setattr(mount.client, "set_switch", switch)
    monkeypatch.setattr(mount, "_publish_manual_motion_progress", lambda **kwargs: None)
    assert mount.manual_move("east") is (reject == "none")
    expected = {
        "none": ["abort", "speed", "motion"],
        "abort": ["abort"],
        "speed": ["abort", "speed"],
    }
    assert events == expected[reject]


def test_short_user_move_disables_tracking_correction_before_service_tick(monkeypatch):
    mount = DummyConnectedMount()
    monkeypatch.setattr(mount, "_apply_indi_properties", lambda *args: True)
    mount._guide_correction_enabled = True
    mount._guide_correction_target = (10.0, 20.0)
    mount._guide_manual_approach = False
    monkeypatch.setattr(mount, "_publish_manual_motion_progress", lambda **kwargs: None)
    assert mount.manual_move("north")
    assert not mount._guide_correction_enabled
    assert mount.stop_mount()
    # Releasing a key must not wake correction toward the pre-move target,
    # even before the slower guide-service process can consume the event.
    monkeypatch.setattr(
        mount, "_current_plate_solve", lambda: pytest.fail("old target resumed")
    )
    mount._check_guide_correction()


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), 0, -1, 241])
def test_invalid_guide_settings_do_not_replace_saved_profile(rate):
    mount = DummyMountControl()
    assert mount.set_guide_rate(0.5)
    assert not mount.set_guide_rate(rate)
    assert DummyMountControl().guide_rate_we == 0.5


def test_rejected_guide_rate_prevents_pulse(monkeypatch):
    mount = DummyConnectedMount()
    mount._guide_correction_enabled = True
    mount._guide_correction_target = (10.0, 20.0)
    monkeypatch.setattr(mount, "_current_plate_solve", lambda: (9.9, 20.0, time.time()))
    monkeypatch.setattr(mount, "_guide_pulse_supported", lambda: True)
    monkeypatch.setattr(mount, "_current_guide_rate_x", lambda: (0.5, 0.5))
    monkeypatch.setattr(mount, "_set_guide_rate", lambda rate: False)
    pulses = []
    monkeypatch.setattr(mount, "_apply_guide_pulse", lambda *args: pulses.append(args))
    mount._check_guide_correction()
    assert pulses == []


def test_pulse_waits_for_fresh_guide_readback_without_consuming_solve(monkeypatch):
    mount = DummyConnectedMount()
    mount.auto_ack_guide = False
    mount._guide_correction_enabled = True
    mount._guide_correction_target = (10.0, 20.0)
    mount._guide_correction_accuracy_arcmin = 1.0
    solve_time = time.time()
    monkeypatch.setattr(mount, "_current_plate_solve", lambda: (9.9, 20.0, solve_time))
    monkeypatch.setattr(mount, "_guide_pulse_supported", lambda: True)
    pulses = []
    monkeypatch.setattr(mount, "_apply_guide_pulse", lambda *args: pulses.append(args))
    mount.receive_sync_property(
        "GUIDE_RATE",
        "ok",
        {"GUIDE_RATE_WE": 1.0, "GUIDE_RATE_NS": 1.0},
        mount._client_generation,
    )
    mount._check_guide_correction()
    assert not pulses
    assert mount._guide_correction_last_solve_time == 0.0
    # A cached matching value and a busy acknowledgement cannot start motion.
    mount._check_guide_correction()
    mount.receive_sync_property(
        "GUIDE_RATE",
        "busy",
        {"GUIDE_RATE_WE": 1.0, "GUIDE_RATE_NS": 1.0},
        mount._client_generation,
    )
    mount._check_guide_correction()
    assert not pulses
    mount.receive_sync_property(
        "GUIDE_RATE",
        "ok",
        {"GUIDE_RATE_WE": 1.0, "GUIDE_RATE_NS": 1.0},
        mount._client_generation,
    )
    mount._check_guide_correction()
    assert len(pulses) == 1
    assert mount._guide_correction_last_solve_time == solve_time
    mount._check_guide_correction()
    assert len(pulses) == 1


@pytest.mark.parametrize(
    "failure", ["alert", "timeout", "mismatch", "disconnect", "manual"]
)
def test_guide_confirmation_failure_or_takeover_blocks_late_pulse(monkeypatch, failure):
    mount = DummyConnectedMount()
    mount.auto_ack_guide = False
    assert not mount._select_guide_rate_for_error(0.0)
    if failure in {"alert", "mismatch"}:
        mount.receive_sync_property(
            "GUIDE_RATE",
            "alert" if failure == "alert" else "ok",
            {"GUIDE_RATE_WE": 1.0, "GUIDE_RATE_NS": 1.0},
            mount._client_generation,
        )
    if failure in {"timeout", "mismatch"}:
        mount._pending_guide_rate["deadline"] = 0.0
    if failure == "disconnect":
        mount.mark_disconnected("test")
    elif failure == "manual":
        monkeypatch.setattr(mount, "_apply_indi_properties", lambda *args: True)
        monkeypatch.setattr(
            mount, "_publish_manual_motion_progress", lambda **kwargs: None
        )
        assert mount.manual_move("east")
    else:
        assert mount._finish_guide_rate_request() is False
    mount.receive_sync_property(
        "GUIDE_RATE",
        "ok",
        {"GUIDE_RATE_WE": 0.5, "GUIDE_RATE_NS": 0.5},
        mount._client_generation,
    )
    assert not mount._select_guide_rate_for_error(0.0)


def test_mount_failure_reaches_lcd_even_when_heartbeat_replaces_status():
    import queue

    mount = DummyMountControl()
    alerts = queue.Queue()
    mount.error_notifier.queue = alerts
    mount._write_controller_status("sync_failed", "Driver rejected coordinates")
    mount._write_controller_status("connected", "Mount position updated")
    mount._write_controller_status("sync_failed", "Driver rejected coordinates")
    assert alerts.qsize() == 1
    alert = alerts.get_nowait()
    assert alert["type"] == "operation_error"
    assert alert["code"] == "sync_failed"
    assert alert["message"] == "Driver rejected coordinates"


def _initial_site_mount(monkeypatch):
    mount = DummyConnectedMount()
    clock = [100.0]
    monkeypatch.setattr(mci.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(mount, "_use_direct_onstep_location_time_sync", lambda: False)
    monkeypatch.setattr(
        mount,
        "_shared_location_time_values",
        lambda *a, **kw: (37.5, 127.0, 30.0, "2026-07-01T14:45:00+00:00"),
    )
    monkeypatch.setattr(mount, "_sync_location_time_once", lambda *a, **kw: True)
    monkeypatch.setattr(
        mount.client, "unpark_mount", lambda device: True, raising=False
    )
    monkeypatch.setattr(mount, "set_tracking", lambda enabled: True)
    assert mount.sync_location_time()
    return mount, clock


def _site_ack(mount, state="ok", lat=37.5, lon=127.0):
    mount.receive_sync_property(
        "GEOGRAPHIC_COORD", state, {"LAT": lat, "LONG": lon}, mount._client_generation
    )
    mount.receive_sync_property(
        "TIME_UTC", state, {"UTC": "2026-07-01T14:45:00"}, mount._client_generation
    )


def test_initial_site_sync_verifies_real_ack_and_tracking(monkeypatch):
    mount, _clock = _initial_site_mount(monkeypatch)
    reboots = []
    monkeypatch.setattr(mount, "reboot_mount", lambda: reboots.append(True) or True)
    mount._check_initial_location_sync()
    assert not mount._initial_site_complete
    _site_ack(mount)
    mount._check_initial_location_sync()
    assert mount._initial_site_complete
    assert not reboots


@pytest.mark.parametrize(
    "failure", ["send", "alert", "timeout", "wrong_location", "tracking"]
)
def test_initial_site_failure_resets_once_then_resyncs_selected_location(
    monkeypatch, failure
):
    mount, clock = _initial_site_mount(monkeypatch)
    # The web Location choice can differ from the old shared-state position.
    assert mount.sync_location_time(latitude=35.0, longitude=-120.0, elevation=50.0)
    if failure == "send":
        mount._initial_site_write_ok = False
    elif failure == "alert":
        _site_ack(mount, state="alert")
    elif failure == "wrong_location":
        _site_ack(mount)  # Reply is fresh but not the selected location.
        clock[0] += 9
    elif failure == "tracking":
        _site_ack(mount, lat=35.0, lon=240.0)
        monkeypatch.setattr(mount, "set_tracking", lambda enabled: False)
    else:
        clock[0] += 9
    reboots = []

    def reboot():
        reboots.append(True)
        # The real reboot reconnects and invokes this without explicit coords.
        mount.sync_location_time()
        _site_ack(mount, lat=35.0, lon=240.0)
        monkeypatch.setattr(mount, "set_tracking", lambda enabled: True)
        return True

    monkeypatch.setattr(mount, "reboot_mount", reboot)
    mount._check_initial_location_sync()
    mount._check_initial_location_sync()
    assert reboots == [True]
    assert mount._initial_site_complete
    assert mount._initial_site_request == {
        "latitude": 35.0,
        "longitude": -120.0,
        "elevation": 50.0,
    }


def test_initial_site_failed_reset_stops_retry_loop_and_reports_failure(monkeypatch):
    mount, clock = _initial_site_mount(monkeypatch)
    clock[0] += 9
    calls = []
    monkeypatch.setattr(mount, "reboot_mount", lambda: calls.append(True) or True)
    mount._check_initial_location_sync()
    mount._check_initial_location_sync()
    mount._check_initial_location_sync()
    assert calls == [True]
    assert mount._initial_site_failed
    assert mount.statuses[-1][0] == "initialization_failed"


@pytest.mark.parametrize("blocked", ["disconnected", "manual", "goto", "no_location"])
def test_initial_site_does_not_reset_missing_or_moving_mount(monkeypatch, blocked):
    mount, clock = _initial_site_mount(monkeypatch)
    clock[0] += 9
    calls = []
    monkeypatch.setattr(mount, "reboot_mount", lambda: calls.append(True) or True)
    if blocked == "disconnected":
        mount.connected = False
    elif blocked == "manual":
        mount._manual_motion_direction = "north"
    elif blocked == "goto":
        mount._goto_motion = {"target_ra": 10.0}
    else:
        mount._initial_site_request = None
    mount._check_initial_location_sync()
    assert not calls


def test_initial_site_does_not_accept_stale_ack(monkeypatch):
    mount, _clock = _initial_site_mount(monkeypatch)
    _site_ack(mount)
    mount.sync_location_time()
    mount._check_initial_location_sync()
    assert not mount._initial_site_complete
    assert not mount._initial_site_reset_attempted


def test_connection_ready_is_announced_once_after_validated_connect():
    import queue

    mount = DummyMountControl()
    mount.console_queue = queue.Queue()
    mount._announce_connection_ready()
    mount._announce_connection_ready()
    assert mount.console_queue.qsize() == 1
    assert mount.console_queue.get_nowait()["type"] == "mount_ready"


def test_startup_failure_can_be_reported_again_after_connection():
    import queue

    mount = DummyMountControl()
    alerts = queue.Queue()
    mount.error_notifier.queue = alerts
    mount._write_controller_status("disconnected", "Connection lost")
    mount._announce_connection_ready()
    mount._write_controller_status("disconnected", "Connection lost")
    assert alerts.qsize() == 2


def test_initial_sync_only_hides_recoverable_errors():
    import queue

    mount = DummyMountControl()
    alerts = queue.Queue()
    mount.error_notifier.queue = alerts
    mount._initial_site_request = {"latitude": 37.5, "longitude": 127.0}
    mount._write_controller_status("sync_failed", "Location rejected")
    assert alerts.empty()
    mount._write_controller_status("disconnected", "USB unplugged")
    assert alerts.get_nowait()["code"] == "disconnected"
    mount._initial_site_recovering = True
    mount._write_controller_status("reboot_failed", "Reset failed")
    assert alerts.empty()
    mount._initial_site_recovering = False
    mount._initial_site_failed = True
    mount._write_controller_status("initialization_failed", "Reset failed")
    assert alerts.get_nowait()["code"] == "initialization_failed"


@pytest.mark.parametrize("raises", [False, True])
def test_initial_reset_failure_reports_error_without_retry(monkeypatch, raises):
    mount, clock = _initial_site_mount(monkeypatch)
    clock[0] += 9
    calls = []

    def reboot():
        calls.append(True)
        if raises:
            raise RuntimeError("Controller unavailable")
        return False

    monkeypatch.setattr(mount, "reboot_mount", reboot)
    mount._check_initial_location_sync()
    mount._check_initial_location_sync()
    assert calls == [True]
    assert mount._initial_site_failed
    assert not mount._initial_site_recovering
    assert mount.statuses[-1][0] == "initialization_failed"


def test_diverging_pulses_request_recovery_from_distinct_fresh_solves(monkeypatch):
    mount, clock, observation, errors, _motions, pulses = _manual_approach_mount(
        monkeypatch, axis_errors=(0.1, 0.0)
    )
    mount._guide_manual_approach = False
    monkeypatch.setattr(mount, "_select_guide_rate_for_error", lambda *args: True)
    mount._check_guide_correction()
    assert len(pulses) == 1
    for i in range(3):
        clock[0] += 4
        observation[0] = clock[0]
        errors[0] = (10 + i) / 60
        mount._check_guide_correction()
        # Re-reading the same observation must not count as more evidence.
        for _ in range(3):
            mount._check_guide_correction()
        if i < 2:
            assert mount._guide_correction_enabled
    assert mount._guide_correction_mode == "reacquire"
    assert not mount._guide_correction_enabled
    assert len(pulses) == 3  # No fourth worsening pulse.
    assert mount._guide_correction_target == (10.0, 20.0)


class ElevationLimitDevice(DummyIndiDevice):
    def __init__(self, low=5.0, high=88.0):
        self.connected = True
        self.limits = [
            SimpleNamespace(name="maxAlt", value=high),
            SimpleNamespace(name="minAlt", value=low),
        ]

    def isConnected(self):
        return self.connected

    def getNumber(self, name):
        assert name == "Slew elevation Limit"
        return self.limits


def test_alignment_limits_follow_driver_updates_and_clear_on_disconnect():
    mount = DummyMountControl()
    mount.device = ElevationLimitDevice()
    assert mount._alignment_altitude_limits() == (5.0, 88.0)
    status = mount._status_fields()
    assert status["alignment_min_altitude"] == 5.0
    assert status["alignment_max_altitude"] == 88.0
    mount.device.limits[1].value = -10.0
    assert mount._alignment_altitude_limits() == (-10.0, 88.0)
    mount.device.connected = False
    assert mount._alignment_altitude_limits() == (20.0, 78.0)
    mount.device = None
    assert mount._alignment_altitude_limits() == (20.0, 78.0)


@pytest.mark.parametrize(
    "low,high",
    [(None, 88), (5, float("nan")), (float("inf"), 88), (80, 10), (-91, 90), (0, 91)],
)
def test_invalid_driver_alignment_limits_use_legacy_range(low, high):
    mount = DummyMountControl()
    mount.device = ElevationLimitDevice(low, high)
    assert mount._alignment_altitude_limits() == (20.0, 78.0)


@pytest.mark.parametrize("limits", [[], [SimpleNamespace(name="minAlt", value=0)]])
def test_missing_driver_alignment_limits_use_legacy_range(limits):
    mount = DummyMountControl()
    mount.device = ElevationLimitDevice()
    mount.device.limits = limits
    assert mount._alignment_altitude_limits() == (20.0, 78.0)


@pytest.mark.parametrize(
    "altitude,allowed",
    [(4.9, False), (5, True), (10, True), (85, True), (88, True), (88.1, False)],
)
def test_alignment_goto_uses_driver_limits(altitude, allowed):
    mount = DummyMountControl()
    mount.device = ElevationLimitDevice()
    mount._radec_to_altaz = lambda ra, dec: (altitude, 180.0)
    assert mount.start_multipoint_align("manual", 2)
    assert mount.select_multipoint_align_star("Vega", goto=True) is allowed
    assert bool(mount.goto_calls) is allowed


def test_auto_alignment_selects_star_within_driver_limits(monkeypatch):
    mount = DummyMountControl()
    mount.device = ElevationLimitDevice(5, 15)
    mount._shared_location_time_values = lambda **kw: (
        37.0,
        127.0,
        0.0,
        datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    stars = [
        {"name": "Low", "ra": 1.0, "dec": 0.0},
        {"name": "Allowed", "ra": 2.0, "dec": 0.0},
        {"name": "High", "ra": 3.0, "dec": 0.0},
    ]
    monkeypatch.setattr(mci, "BRIGHT_ALIGN_STARS", stars)
    monkeypatch.setattr(mci.calc_utils.sf_utils, "set_location", lambda *args: None)
    monkeypatch.setattr(
        mci.calc_utils.sf_utils,
        "radec_to_altaz",
        lambda ra, dec, dt: ({1: 4, 2: 10, 3: 30}[ra], 180),
    )
    assert mount._align_auto_star({})["name"] == "Allowed"


def test_late_alignment_limits_publish_without_heartbeat_and_preserve_motion():
    mount = DummyMountControl()
    mount.device = ElevationLimitDevice()
    mount.device.limits = []
    mount._write_controller_status("slewing", "Moving to Vega", target_ra=279.0)
    assert json.loads(mci.STATUS_FILE.read_text())["alignment_min_altitude"] == 20

    mount.device.limits = ElevationLimitDevice(0, 89).limits
    mount.refresh_alignment_limits(
        mount._client_generation, {"minAlt": 0, "maxAlt": 89}
    )
    status = json.loads(mci.STATUS_FILE.read_text())
    assert (status["alignment_min_altitude"], status["alignment_max_altitude"]) == (
        0,
        89,
    )
    assert status["state"] == "slewing"
    assert status["message"] == "Moving to Vega"
    assert status["target_ra"] == 279.0
    assert status["mount_motion_active"]
    assert mount._alignment_altitude_limits() == (0, 89)


def test_late_mount_connection_and_disconnect_refresh_alignment_limits():
    mount = DummyMountControl()
    mount.device = ElevationLimitDevice(-5, 87)
    mount.device.connected = False
    mount._write_controller_status("connecting", "Waiting for mount")
    mount.device.connected = True
    mount.refresh_alignment_limits(mount._client_generation)
    status = json.loads(mci.STATUS_FILE.read_text())
    assert (status["alignment_min_altitude"], status["alignment_max_altitude"]) == (
        -5,
        87,
    )
    mount.device.connected = False
    mount.refresh_alignment_limits(mount._client_generation)
    status = json.loads(mci.STATUS_FILE.read_text())
    assert (status["alignment_min_altitude"], status["alignment_max_altitude"]) == (
        20,
        78,
    )


def test_alignment_limit_event_rejects_stale_client_and_suppresses_unchanged_write():
    mount = DummyMountControl()
    mount.device = ElevationLimitDevice()
    mount._write_controller_status("connected", "Ready")
    original = mci.STATUS_FILE.read_text()
    mount.refresh_alignment_limits(
        mount._client_generation - 1, {"minAlt": 0, "maxAlt": 90}
    )
    assert mci.STATUS_FILE.read_text() == original
    mount.refresh_alignment_limits(
        mount._client_generation, {"minAlt": 5, "maxAlt": 88}
    )
    assert mci.STATUS_FILE.read_text() == original


@pytest.mark.skipif(mci.PyIndi is None, reason="requires installed INDI bindings")
def test_indi_alignment_limit_definition_update_removal_and_connection_callbacks():
    indi = mci.PyIndi
    mount = DummyMountControl()
    mount.device = ElevationLimitDevice()
    mount._write_controller_status("connected", "Ready")
    client = mci.PiFinderIndiClient(mount, generation=mount._client_generation)
    prop = indi.PropertyNumber(2)
    prop.setDeviceName(mount._indi_device_name())
    prop.setName("Slew elevation Limit")
    prop[0].setName("minAlt")
    prop[0].setValue(-10)
    prop[1].setName("maxAlt")
    prop[1].setValue(89)
    client.newProperty(prop)
    status = json.loads(mci.STATUS_FILE.read_text())
    assert (status["alignment_min_altitude"], status["alignment_max_altitude"]) == (
        -10,
        89,
    )
    prop[0].setValue(0)
    client.updateProperty(prop)
    assert json.loads(mci.STATUS_FILE.read_text())["alignment_min_altitude"] == 0
    prop.setDeviceName("Other mount")
    prop[0].setValue(15)
    client.updateProperty(prop)
    assert json.loads(mci.STATUS_FILE.read_text())["alignment_min_altitude"] == 0
    prop.setDeviceName(mount._indi_device_name())
    client.removeProperty(prop)
    assert json.loads(mci.STATUS_FILE.read_text())["alignment_min_altitude"] == 20

    connection = indi.PropertySwitch(1)
    connection.setName("CONNECTION")
    connection.setDeviceName(mount._indi_device_name())
    client.updateProperty(connection)
    assert json.loads(mci.STATUS_FILE.read_text())["alignment_min_altitude"] == 5
    mount.device.connected = False
    client.updateProperty(connection)
    assert json.loads(mci.STATUS_FILE.read_text())["alignment_min_altitude"] == 20


@pytest.mark.skipif(mci.PyIndi is None, reason="requires installed INDI bindings")
def test_legacy_indi_alignment_number_and_connection_callbacks():
    class Vector(list):
        pass

    mount = DummyMountControl()
    mount.device = ElevationLimitDevice()
    mount._write_controller_status("connected", "Ready")
    client = mci.PiFinderIndiClient(mount, generation=mount._client_generation)
    vector = Vector(
        [
            SimpleNamespace(name="minAlt", value=0),
            SimpleNamespace(name="maxAlt", value=90),
        ]
    )
    vector.name = "Slew elevation Limit"
    vector.device = mount._indi_device_name()
    client.newNumber(vector)
    assert json.loads(mci.STATUS_FILE.read_text())["alignment_min_altitude"] == 0
    mount.device.connected = False
    client.newSwitch(
        SimpleNamespace(name="CONNECTION", device=mount._indi_device_name())
    )
    assert json.loads(mci.STATUS_FILE.read_text())["alignment_min_altitude"] == 20
