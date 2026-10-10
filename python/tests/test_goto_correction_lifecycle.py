"""Service/queue/executor integration; only driver I/O and observations are fake."""

from queue import Empty, Queue

import pytest

from PiFinder import indi_goto_guide_service as policy
from PiFinder import mountcontrol_indi as executor
from PiFinder.tracking_commands import PriorityMountQueue
from test_mountcontrol_indi import DummyConnectedMount, _sync_ack

pytestmark = pytest.mark.unit


class Lifecycle:
    def __init__(self, monkeypatch, tmp_path):
        self.now = 1000.0
        monkeypatch.setattr(policy.time, "time", lambda: self.now)
        monkeypatch.setattr(policy.time, "monotonic", lambda: self.now)
        monkeypatch.setattr(executor.config.utils, "data_dir", tmp_path)
        monkeypatch.setattr(executor.config.utils, "runtime_dir", tmp_path)
        monkeypatch.setattr(
            executor.sys_utils, "get_indi_profile_drivers", lambda **kw: {}
        )
        self.mount = DummyConnectedMount()
        self.queue = PriorityMountQueue()
        # Keep real cancellation epochs, with deterministic in-process FIFO.
        # A frozen clock cannot drive multiprocessing's timed pipe polling.
        self.queue.queue.close()
        self.queue.queue = Queue()
        self.mount.mount_queue = self.queue
        self.tracking = True
        self.commands = []
        self.properties = []
        self.observation = None
        self.pointing = {}
        monkeypatch.setattr(self.mount, "connect", lambda **kw: True)
        monkeypatch.setattr(
            self.mount, "_read_current_position", lambda **kw: (110, 30)
        )
        monkeypatch.setattr(
            self.mount, "_cached_tracking_enabled", lambda: self.tracking
        )
        monkeypatch.setattr(
            self.mount,
            "_confirm_tracking_state",
            lambda enabled: self.tracking == enabled,
        )
        monkeypatch.setattr(self.mount, "_apply_indi_properties", self.apply)
        monkeypatch.setattr(self.mount, "_guide_pulse_supported", lambda: True)
        monkeypatch.setattr(
            self.mount, "_select_guide_rate_for_error", lambda error: True
        )
        monkeypatch.setattr(
            self.mount, "_guide_pulse_inversions", lambda: (False, False)
        )
        monkeypatch.setattr(
            self.mount, "_current_plate_solve", lambda: self.observation
        )
        self.mount._confirmed_guide_rates = (1.0, 1.0)
        self.service = policy.IndiGotoGuideService(Queue(), self.queue, None)
        self.service.config_values = {
            "indi_goto_method": "mfnavis",
            "mount_control": True,
            "indi_tracking_guide_enabled": True,
            "indi_goto_refine_accuracy_arcmin": 1.0,
            "indi_tracking_guide_settle_seconds": 1.0,
        }
        monkeypatch.setattr(self.service, "_mount_status_summary", self.status)
        monkeypatch.setattr(
            self.service, "_refresh_pointing_status", self.pointing_status
        )
        monkeypatch.setattr(self.service, "_write_status", lambda **kw: None)
        self.solve(29)

    def apply(self, props, *args):
        self.properties.extend(props)
        if any("TRACK_OFF=On" in prop for prop in props):
            self.tracking = False
        if any("TRACK_ON=On" in prop for prop in props):
            self.tracking = True
        return True

    def status(self):
        return {
            **self.mount._status_fields("connected"),
            "available": True,
            "updated": self.now,
            "state": "connected",
            "sync_goto": self.mount._sync_goto_status,
        }

    def pointing_status(self):
        self.service.pointing_status = self.pointing
        return self.pointing

    def solve(self, dec=30):
        self.observation = (110, dec, self.now)
        self.pointing = {
            "fresh": True,
            "usable_for_goto": True,
            "current": {
                "valid": True,
                "source": "solve",
                "quality": "high",
                "ra": 110,
                "dec": dec,
                "timestamp": self.now,
                "metadata": {
                    "last_solve_success": self.now,
                    "last_solve_attempt": self.now,
                },
            },
        }

    def fail(self):
        self.observation = None
        self.pointing["usable_for_goto"] = False
        self.pointing["current"]["metadata"]["last_solve_attempt"] = self.now

    def flush(self):
        while True:
            try:
                command = self.queue.get_nowait()
            except Empty:
                return
            self.commands.append(command)
            self.mount.handle_command(command)

    def tick(self, seconds=1):
        self.now += seconds
        self.mount._check_motion_limits()
        self.service._tick_state_machine()
        self.service._tick_tracking_guide_states()
        self.flush()
        self.mount._check_guide_correction()

    def start(self):
        self.service.handle_command({"type": "goto_target", "ra": 110, "dec": 30})
        self.flush()
        self.acknowledge()

    def acknowledge(self):
        assert self.mount._sync_goto_status["state"] == "waiting_sync_mode"
        transaction = dict(self.mount._pending_sync_goto)
        _sync_ack(self.mount, "ON_COORD_SET", {"SYNC": True})
        _sync_ack(
            self.mount,
            "EQUATORIAL_EOD_COORD",
            {"RA": transaction["sync_ra"] / 15, "DEC": transaction["sync_dec"]},
        )
        assert self.mount._goto_motion is None
        _sync_ack(self.mount, "ON_COORD_SET", {"SLEW": True})
        assert self.mount._goto_motion is not None
        assert self.mount._sync_goto_status["state"] == "goto_sent"

    def arrive(self, dec=29.9):
        self.now += 10
        # Inject a physical stop; callback/stability verification is covered
        # separately in test_mountcontrol_indi. No real hardware is contacted.
        self.mount._complete_goto_motion()
        self.solve(dec)
        self.tick(0)

    def complete(self):
        self.start()
        self.arrive()
        assert self.service.phase == "pifinder_pulse_align"
        assert any("TIMED_GUIDE" in prop for _, prop, _ in self.mount.client.numbers)
        self.now += 4
        self.solve()
        self.tick(0)
        assert self.service.phase == "complete"
        assert self.service.optical_arrival_confirmed
        self.tick(2)
        assert self.mount._guide_continue_on_solve_loss


@pytest.fixture
def lifecycle(monkeypatch, tmp_path):
    rig = Lifecycle(monkeypatch, tmp_path)
    return rig


def test_start_fine_arrival_tracking_outage_recovery_and_explicit_stop(lifecycle):
    rig = lifecycle
    rig.complete()
    for _ in range(4):
        rig.now += 1
        rig.solve(29.99)
        rig.tick(0)
    before = len(rig.mount.client.numbers)
    rig.fail()
    for _ in range(20):
        rig.tick()
    assert len(rig.mount.client.numbers) > before
    assert rig.service.tracking_guide_state == "solve_holdover"
    assert rig.tracking
    assert rig.mount._guide_correction_enabled
    assert sum(c["type"] == "sync_and_goto" for c in rig.commands) == 1

    rig.now += 3600
    rig.solve()
    rig.tick(0)
    assert rig.mount._guide_correction_mode == "complete"
    rig.service.handle_command({"type": "stop_movement", "stop_tracking": True})
    rig.flush()
    rig.now += 1
    rig.solve()
    rig.tick(0)
    assert not rig.tracking and not rig.mount._guide_correction_enabled
    assert rig.service.phase == "idle"


def test_large_arrival_error_repeats_verified_goto_before_fine_correction(lifecycle):
    rig = lifecycle
    rig.start()
    rig.arrive(28)
    assert rig.service.phase == "pifinder_goto"
    assert rig.service.correction_count == 2
    rig.acknowledge()
    rig.arrive(29.9)
    assert rig.service.phase == "pifinder_pulse_align"
    assert rig.mount._guide_correction_enabled
    assert not rig.mount._guide_continue_on_solve_loss


def test_postarrival_large_error_uses_optical_recovery_without_changing_target(
    lifecycle,
):
    rig = lifecycle
    rig.complete()
    rig.now += 1
    rig.solve(29)
    rig.tick(0)
    rig.tick(2)
    assert rig.service.tracking_recovery_state == "goto_wait"
    assert not rig.mount._guide_correction_enabled
    rig.acknowledge()
    rig.arrive(30)
    rig.tick(2)
    rig.tick(2)
    assert rig.service.tracking_recovery_state == "idle"
    assert rig.mount._guide_continue_on_solve_loss
    assert rig.mount._guide_correction_target == (110, 30)


def test_prearrival_outage_waits_then_user_alignment_adopts_actual_position(lifecycle):
    rig = lifecycle
    rig.start()
    rig.arrive()
    rig.now += 15
    rig.fail()
    rig.tick(0)
    assert rig.service.phase == "native_pending"
    rig.tick(3600)
    assert rig.service.phase == "native_pending" and rig.tracking
    rig.mount._manual_motion_origin = "user"
    rig.mount._manual_motion_direction = "north"
    rig.mount._last_user_motion_started_wall = rig.now
    rig.tick()
    rig.mount.stop_mount()
    rig.tick(2)
    rig.service.handle_command({"type": "confirm_goto_arrival", "ra": 110, "dec": 30})
    rig.flush()
    assert rig.service.phase == "arrived_waiting_solve"
    rig.tick(3600)
    rig.solve(35)
    rig.tick(0)
    assert rig.service.tracking_target_dec == 35
    rig.tick(2)
    assert rig.mount._guide_correction_target == (110, 35)
    assert sum(c["type"] == "sync_and_goto" for c in rig.commands) == 1


@pytest.mark.parametrize("stage", ["goto", "pulse", "tracking", "outage"])
def test_limit_at_every_stage_stops_tracking_and_blocks_recovered_solve(
    lifecycle, stage
):
    rig = lifecycle
    if stage in {"tracking", "outage"}:
        rig.complete()
    else:
        rig.start()
        if stage == "pulse":
            rig.arrive()
    if stage == "outage":
        rig.fail()
        rig.tick(15)
    rig.mount._pending_motion_limit = "upper elevation limit"
    rig.tick()
    assert not rig.tracking
    assert rig.service.phase == "limit_exceeded"
    assert rig.mount._motion_limit["latched"]
    assert any("ABORT=On" in prop for prop in rig.properties)
    before = len(rig.mount.client.numbers)
    rig.now += 5
    rig.solve()
    rig.tick(0)
    assert len(rig.mount.client.numbers) == before
    assert not rig.mount._guide_correction_enabled
