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

    def arrive(self, dec=29.97):
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
    # A centered holdover retains tracking without spending small solve noise.
    assert len(rig.mount.client.numbers) == before
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
    rig.arrive(29.97)
    assert rig.service.phase == "pifinder_pulse_align"
    assert rig.mount._guide_correction_enabled
    assert not rig.mount._guide_continue_on_solve_loss


@pytest.mark.parametrize("residual", [4.17, 6.0, 14.0])
def test_near_arrival_closes_large_residual_before_pulse_finish(lifecycle, residual):
    rig = lifecycle
    rig.start()
    rig.arrive(30 - residual / 60)
    assert rig.service.phase == "pifinder_goto"
    assert rig.service.correction_count == 2
    assert not rig.mount._guide_correction_enabled
    assert not any(
        "TIMED_GUIDE" in prop for _, prop, _ in rig.mount.client.numbers
    )  # No slow pulse before the second slew.
    rig.acknowledge()
    rig.arrive(29.97)
    assert rig.service.phase == "pifinder_pulse_align"
    assert rig.mount._guide_correction_enabled
    rig.now += 4
    rig.solve(30)
    rig.tick(0)
    assert rig.service.optical_arrival_confirmed


@pytest.mark.parametrize("residual", [4.17, 4.0, 5.0])
def test_small_goto_without_progress_falls_back_to_pulses(lifecycle, residual):
    rig = lifecycle
    rig.start()
    rig.arrive(30 - 4.17 / 60)
    rig.acknowledge()
    rig.arrive(30 - residual / 60)
    assert rig.service.phase == "pifinder_pulse_align"
    assert rig.service.correction_count == 2
    assert rig.mount._guide_correction_enabled
    # The wider pulse capacity remains valid after entering this fallback;
    # the next observation must not bounce back into another small GoTo.
    rig.now += 4
    rig.solve(30 - residual / 60)
    rig.tick(0)
    assert rig.service.phase == "pifinder_pulse_align"
    assert sum(c["type"] == "sync_and_goto" for c in rig.commands) == 2


@pytest.mark.parametrize("residual", [4.17, 6.0, 14.0])
@pytest.mark.parametrize("cadence", [3.0, 6.0])
@pytest.mark.parametrize("remaining", [0.25, 0.95])
def test_approach_timing_with_simulated_mount(tmp_path, residual, cadence, remaining):
    """Compare policies, not hardware: a slew+solve costs 10 s in this model.

    The ideal axis executes actual executor pulse durations at 1x sidereal.
    Small slews either remove 75% of the residual or barely help (5%).
    """
    results = {}
    for mode, multiple in (
        ("before", 15.0),
        ("after", policy.MFNAVIS_PULSE_ENTRY_ACCURACY_MULTIPLE),
    ):
        with pytest.MonkeyPatch.context() as patch:
            data = tmp_path / mode
            data.mkdir()
            rig = Lifecycle(patch, data)
            patch.setattr(policy, "MFNAVIS_PULSE_ENTRY_ACCURACY_MULTIPLE", multiple)
            rig.start()
            rig.arrive(30 - residual / 60)
            started, error = rig.now, residual
            for _ in range(120):
                if rig.service.phase == "complete":
                    break
                if rig.mount._pending_sync_goto:
                    rig.acknowledge()
                    error *= remaining
                    rig.arrive(30 - error / 60)
                else:
                    active = rig.mount._guide_active_pulses.get(
                        "TELESCOPE_TIMED_GUIDE_NS"
                    )
                    if active:
                        direction, end = active
                        duration = min(cadence, max(0, end - rig.now))
                        travel = duration * executor.SIDEREAL_ARCSEC_PER_SEC / 60
                        error -= travel if direction == "north" else -travel
                    rig.now += cadence
                    rig.solve(30 - error / 60)
                    rig.tick(0)
            assert rig.service.optical_arrival_confirmed
            assert abs(error) <= 1
            results[mode] = (rig.now - started, rig.service.correction_count)
    if remaining == 0.25:
        assert results["after"][0] < results["before"][0]
    else:
        # An ineffective small GoTo costs at most one extra slew; it must
        # yield to pulses instead of repeatedly exhausting the batch budget.
        assert results["after"][1] == 2
        assert results["after"][0] <= results["before"][0] + 10


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


def test_optical_arrival_after_failed_pulses_reopens_tracking_baseline(lifecycle):
    rig = lifecycle
    rig.start()
    rig.arrive()
    rig.mount._guide_correction_enabled = False
    rig.mount._guide_correction_mode = "reacquire"
    rig.now += 4
    rig.solve(29.95)
    rig.tick(0)
    assert rig.service.phase == "pifinder_goto"
    assert rig.service.pulse_alignment_unreliable
    rig.acknowledge()
    rig.arrive(29.995)
    assert rig.service.optical_arrival_confirmed
    assert not rig.service.pulse_alignment_unreliable
    rig.tick(2)
    assert rig.mount._guide_correction_enabled
    assert rig.mount._guide_pulse_no_progress == 0
    assert sum(c.get("reset_convergence", False) for c in rig.commands) == 1
    before = sum(c["type"] == "sync_and_goto" for c in rig.commands)
    rig.now += 2
    rig.solve(29.97)
    rig.tick(0)
    assert rig.mount._guide_correction_mode == "settling"
    assert rig.mount._guide_correction_enabled
    rig.now += 1
    rig.solve(29.97)
    rig.tick(0)
    assert rig.mount._guide_correction_mode == "pulse"
    assert sum(c["type"] == "sync_and_goto" for c in rig.commands) == before
    rig.fail()
    rig.tick(15)
    assert rig.mount._guide_correction_enabled
    assert rig.mount._guide_continue_on_solve_loss
    assert rig.service.phase == "complete"
    assert sum(c.get("reset_convergence", False) for c in rig.commands) == 1
    rig.service.handle_command({"type": "stop_movement", "stop_tracking": True})
    rig.flush()
    rig.now += 5
    rig.solve(29.9)
    before = len(rig.mount.client.numbers)
    rig.tick(0)
    assert len(rig.mount.client.numbers) == before
    assert rig.service.active_target_ra is None
    assert not rig.tracking


@pytest.mark.parametrize("error", [0.5, 2.0, 8.0])
def test_tracking_recovery_reopens_pulses_only_after_fresh_near_arrival(
    lifecycle, error
):
    rig = lifecycle
    rig.complete()
    rig.service.pulse_alignment_unreliable = True
    rig.mount._guide_correction_enabled = False
    rig.mount._guide_correction_mode = "reacquire"
    rig.now += 2
    rig.solve(29.5)  # A real departure beyond the native recovery threshold.
    rig.tick(0)
    rig.tick(2)
    assert rig.service.tracking_recovery_state == "goto_wait"
    assert rig.service.pulse_alignment_unreliable
    rig.acknowledge()
    rig.fail()
    rig.tick(3)
    assert rig.service.pulse_alignment_unreliable
    rig.arrive(30 - error / 60)
    assert rig.service.tracking_recovery_state == ("goto_wait" if error > 3 else "idle")
    assert rig.service.pulse_alignment_unreliable is (error > 3)
    if error <= 3:
        assert rig.service.tracking_baseline_pending
        rig.tick(2)
        assert rig.mount._guide_correction_enabled
        assert sum(c.get("reset_convergence", False) for c in rig.commands) == 2


def test_cloud_during_tracking_recovery_preserves_acquisition_completion(lifecycle):
    rig = lifecycle
    rig.complete()
    completed = dict(rig.service.goto_timing)
    action = rig.service.last_action
    rig.now += 1
    rig.solve(29)
    rig.tick(0)
    rig.tick(2)
    assert rig.service.tracking_recovery_state == "goto_wait"
    rig.acknowledge()
    rig.fail()
    rig.tick(1)
    assert rig.service.phase == "complete"
    assert rig.service.goto_timing == completed
    assert rig.service.last_action == action
    rig.now += 10
    rig.mount._complete_goto_motion()
    rig.tick(0)
    rig.tick(15)
    assert rig.service.tracking_recovery_state == "goto_wait"
    assert rig.service.optical_arrival_confirmed
    assert rig.service.phase == "complete"
    rig.solve(30)
    rig.tick(0)
    assert rig.service.tracking_recovery_state == "idle"
    assert rig.service.goto_timing == completed
    assert sum(c["type"] == "sync" for c in rig.commands) == 1
