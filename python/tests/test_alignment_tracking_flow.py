"""The observed SkySafari -> alignment -> LCD -> continuous guide contract."""

import datetime
import queue
from types import SimpleNamespace

import pytest
import quaternion

from PiFinder import calc_utils, pos_server
from PiFinder.alignment_projection import make_projection, project_target
from PiFinder.indi_goto_guide_service import IndiGotoGuideService
from PiFinder.integrator import _apply_successful_solve, _realign_estimate
from PiFinder.pointing_coordinate_service import PointingCoordinateService
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
from PiFinder.types.positioning import (
    ImuSample,
    Pointing,
    PointingAxis,
    PointingEstimate,
    SuccessfulSolve,
    SolveDiagnostics,
    SolveSource,
)

pytestmark = pytest.mark.unit
DT = datetime.datetime(2026, 9, 14, 12, 53, tzinfo=datetime.timezone.utc)
LOCATION = SimpleNamespace(lock=True, lat=37.52704, lon=127.10936, altitude=30.0)


class Commands:
    def __init__(self):
        self.commands = []

    def put(self, command):
        self.commands.append(command)


class Config:
    def __init__(self):
        self.options = {"mount_control": True, "indi_goto_method": "pifinder"}

    def get_option(self, key, default=None):
        return self.options.get(key, default)

    def set_option(self, key, value):
        self.options[key] = value


def make_state():
    camera = Pointing(RA=13.92, Dec=2.0, Roll=51.5)
    estimate = PointingEstimate(
        estimate_time=DT.timestamp(),
        last_solve_success=DT.timestamp(),
        solve_source=SolveSource.CAMERA,
        imu_anchor=quaternion.quaternion(1, 0, 0, 0),
    )
    estimate.pointing.camera = PointingAxis(solve=camera, estimate=camera)
    estimate.pointing.aligned = PointingAxis(solve=camera, estimate=camera)
    estimate.alignment_projection = make_projection(
        {
            "RA": camera.RA,
            "Dec": camera.Dec,
            "Roll": camera.Roll,
            "FOV": 17.0,
            "_alignment_frame": (980, 980, 980),
        },
        DT.timestamp(),
        ("optics",),
    )
    objects = []
    ui = SimpleNamespace(
        add_recent=objects.append, set_new_pushto=lambda _: None, target=lambda: None
    )
    state = SimpleNamespace(
        solution=lambda: estimate,
        location=lambda: LOCATION,
        datetime=lambda: DT,
        imu=lambda: ImuSample(
            quat=estimate.imu_anchor, timestamp=DT.timestamp(), status=3
        ),
        ui_state=lambda: ui,
        pixel=(256.0, 256.0),
    )
    state.set_target_pixel = lambda pixel: setattr(state, "pixel", pixel)
    state.target_pixel = lambda: state.pixel
    return state, objects


def test_skysafari_alignment_zeroes_lcd_and_reports_same_position(monkeypatch):
    state, objects = make_state()
    mount, guide, ui = Commands(), Commands(), queue.Queue()
    monkeypatch.setattr(pos_server, "pos_server_config", Config())
    monkeypatch.setattr(pos_server, "mountcontrol_queue", mount)
    monkeypatch.setattr(pos_server, "goto_guide_queue", guide)
    monkeypatch.setattr(pos_server, "ui_queue", ui, raising=False)
    monkeypatch.setattr(pos_server, "console_queue", None)
    monkeypatch.setattr(pos_server, "_mount_control_status", lambda: {})
    monkeypatch.setattr(pos_server, "projection_context", lambda *_: ("optics",))
    monkeypatch.setattr(pos_server, "_get_config_option", Config().get_option)
    monkeypatch.setattr(pos_server, "is_stellarium", False)
    monkeypatch.setattr(pos_server, "sr_result", (0, 51, 20))
    monkeypatch.setattr(pos_server, "sd_result", (1, 2, 34, 58))
    monkeypatch.setattr(pos_server.time, "time", lambda: DT.timestamp())
    monkeypatch.setattr(pos_server, "_coordinate_service", PointingCoordinateService())

    assert pos_server.handle_sync_command(state, ":CM#") == "Coordinates matched."
    target = objects[-1]
    # Actual Saturn incident: the target must be near catalog 12.49/2.44,
    # rather than treating wire 12.833/2.583 as catalog coordinates.
    assert target.ra == pytest.approx(12.49, abs=0.01)
    assert target.dec == pytest.approx(2.44, abs=0.01)
    command = guide.commands[-1]
    assert (command["ra"], command["dec"]) == (target.ra, target.dec)
    assert mount.commands[0] == {"type": "toggle_guide_correction", "enabled": False}

    estimate = state.solution()
    old_time = estimate.estimate_time
    idr = ImuDeadReckoning("flat3")
    assert _realign_estimate(estimate, state.target_pixel(), idr)
    assert estimate.estimate_time == old_time  # no fabricated fresh solve
    assert estimate.last_solve_success == old_time
    assert calc_utils.aim_degrees(state, "Alt/Az", "flat3", target) == pytest.approx(
        (0, 0), abs=1e-9
    )
    sample = pos_server._coordinate_service.solved_sample(state, DT)
    monkeypatch.setattr(
        pos_server._coordinate_service,
        "get_state",
        lambda: SimpleNamespace(
            current=sample,
            radec=sample.radec,
        ),
    )
    ra, dec = pos_server._current_pointing(state)
    assert ra == pytest.approx(12.833333333333, abs=1e-8)
    assert dec == pytest.approx(2 + 34 / 60 + 58 / 3600, abs=1e-8)


@pytest.mark.parametrize("mount_type", ["EQ", "Alt/Az"])
def test_completion_checks_lcd_axes_even_when_spherical_error_passes(mount_type):
    state, _ = make_state()
    if mount_type == "EQ":
        current, target = (100.0, 80.0), (100.1, 80.0)
    else:
        calc_utils.sf_utils.set_location(LOCATION.lat, LOCATION.lon, LOCATION.altitude)
        current = calc_utils.sf_utils.observed_altaz_to_radec(80.0, 100.0, DT)
        target = calc_utils.sf_utils.observed_altaz_to_radec(80.0, 100.1, DT)
    state.solution().pointing.aligned.estimate = Pointing(
        RA=current[0], Dec=current[1], Roll=0
    )
    service = IndiGotoGuideService(Commands(), Commands(), state)
    service.config_values = {"mount_type": mount_type}
    assert service._angular_error_arcmin(*current, *target) < 3
    assert service._target_error_arcmin(*current, *target) == pytest.approx(
        6.0, abs=1e-5
    )
    assert service._target_error_arcmin(*current, *current) == pytest.approx(
        0.0, abs=1e-4
    )


def test_alignment_replaces_active_guide_target_and_waits_for_publication(monkeypatch):
    state, _ = make_state()
    mount = Commands()
    service = IndiGotoGuideService(Commands(), mount, state)
    service.config_values = {
        "indi_goto_method": "pifinder",
        "indi_tracking_guide_enabled": True,
    }
    service.tracking_guide_active_sent = True
    service.tracking_guide_accuracy_arcmin = 3.0
    service.tracking_target_ra, service.tracking_target_dec = 100, 20
    service.phase = "complete"
    pixel = project_target(state.solution().alignment_projection, 12.49, 2.44)
    command = {
        "type": "set_tracking_target",
        "ra": 12.49,
        "dec": 2.44,
        "alignment_target_pixel": pixel,
    }
    service.handle_command(command)
    assert not service.tracking_guide_active_sent
    assert service.phase == "tracking"
    assert mount.commands == [{"type": "toggle_guide_correction", "enabled": False}]
    monkeypatch.setattr(service, "_refresh_pointing_status", lambda: {"current": {}})
    service._tick_tracking_guide_states()
    assert service.tracking_guide_state == "settling"
    assert len(mount.commands) == 1
    _realign_estimate(state.solution(), pixel, ImuDeadReckoning("flat3"))
    # Publication must catch up too; a reprojected shared solution alone is
    # not permission to start recovery from the old service snapshot.
    service._tick_tracking_guide_states()
    assert service.alignment_target_pixel is not None
    monkeypatch.setattr(
        service,
        "_refresh_pointing_status",
        lambda: {
            "usable_for_goto": True,
            "current": {
                "ra": 12.49,
                "dec": 2.44,
                "source": "solve",
                "quality": "high",
                "metadata": {"target_pixel": pixel},
            },
        },
    )
    monkeypatch.setattr(service, "_mount_status_summary", lambda: {"available": True})
    monkeypatch.setattr(service, "_tracking_target_altitude_deg", lambda: 45.0)
    service.config_values["indi_tracking_guide_settle_seconds"] = 0.0
    service._tick_tracking_guide_states()
    assert service.alignment_target_pixel is None
    assert mount.commands[-1]["target_ra"] == 12.49
    assert mount.commands[-1]["target_dec"] == 2.44


def test_old_inflight_solve_cannot_restore_previous_alignment():
    state, _ = make_state()
    estimate = state.solution()
    plate = estimate.alignment_projection
    pixel = project_target(plate, 12.49, 2.44)
    old_camera = estimate.pointing.camera.solve
    old_result = SuccessfulSolve(
        camera=old_camera,
        aligned=old_camera,
        imu_anchor=estimate.imu_anchor,
        last_solve_attempt=DT.timestamp(),
        last_solve_success=DT.timestamp(),
        diagnostics=SolveDiagnostics(AlignmentProjection=plate),
    )
    idr = ImuDeadReckoning("flat3")
    _realign_estimate(estimate, pixel, idr)
    _apply_successful_solve(estimate, old_result, idr)
    _realign_estimate(estimate, pixel, idr)
    pointing = estimate.pointing.aligned.estimate
    assert (pointing.RA, pointing.Dec) == pytest.approx((12.49, 2.44), abs=1e-9)


def test_alignment_resets_coordinate_average():
    state, _ = make_state()
    service = PointingCoordinateService()
    service.solved_sample(state, DT)
    service._solve_average_samples = [object()]
    pixel = project_target(state.solution().alignment_projection, 12.49, 2.44)
    _realign_estimate(state.solution(), pixel, ImuDeadReckoning("flat3"))
    sample = service.solved_sample(state, DT)
    assert service._solve_average_samples == []
    assert sample.radec() == pytest.approx((12.49, 2.44), abs=1e-9)


def test_continuous_guiding_restarts_pulses_when_lcd_axis_leaves_tolerance(monkeypatch):
    from PiFinder import mountcontrol_indi as mci

    state, _ = make_state()
    estimate = state.solution()
    estimate.pointing.aligned.solve = Pointing(RA=100.0, Dec=80.0, Roll=0)
    mount = mci.MountControlIndi(Commands(), Commands(), state)
    mount._guide_mount_type = "EQ"
    mount._guide_correction_enabled = True
    mount._guide_correction_target = (100.0, 80.0)
    mount._guide_correction_accuracy_arcmin = 3.0
    mount._confirmed_guide_rates = (0.5, 0.5)
    clock = [DT.timestamp()]
    monkeypatch.setattr(mci.time, "time", lambda: clock[0])
    monkeypatch.setattr(mci.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(mount, "_guide_pulse_supported", lambda: True)
    monkeypatch.setattr(mount, "_select_guide_rate_for_error", lambda _: True)
    monkeypatch.setattr(mount, "_restore_fine_guide_rate", lambda: None)
    monkeypatch.setattr(mount, "_write_controller_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(mount, "_guide_pulse_inversions", lambda: (False, False))
    pulses = []
    monkeypatch.setattr(
        mount, "_send_guide_pulse", lambda d, ms: pulses.append((d, ms)) or True
    )

    mount._check_guide_correction()
    assert pulses == []
    assert mount._guide_correction_enabled

    clock[0] += 5
    estimate.last_solve_success = clock[0]
    estimate.pointing.aligned.solve = Pointing(RA=100.1, Dec=80.0, Roll=0)
    # Spherical error is only ~1 arcmin, but LCD RA is 0.1 degrees off.
    mount._check_guide_correction()
    assert [d for d, _ in pulses] == ["west"]
    assert mount._guide_correction_enabled


def test_pulse_completion_waits_for_a_solve_after_the_last_pulse(monkeypatch):
    state, _ = make_state()
    mount = Commands()
    service = IndiGotoGuideService(Commands(), mount, state)
    service.config_values = {"mount_type": "EQ"}
    service.phase = "pifinder_pulse_align"
    service.pulse_align_sent = True
    service.pulse_align_started_at = DT.timestamp()
    p = state.solution().pointing.aligned.estimate
    service.active_target_ra, service.active_target_dec = p.RA, p.Dec
    current = {
        "ra": p.RA,
        "dec": p.Dec,
        "timestamp": DT.timestamp(),
        "source": "solve",
        "quality": "high",
    }
    monkeypatch.setattr(
        service,
        "_mount_status_summary",
        lambda: {
            "available": True,
            "guide_pulse_until_wall": DT.timestamp() + 2,
        },
    )
    monkeypatch.setattr(
        service,
        "_refresh_pointing_status",
        lambda: {
            "usable_for_goto": True,
            "current": current,
        },
    )
    from PiFinder import indi_goto_guide_service as iggs

    monkeypatch.setattr(iggs.time, "time", lambda: DT.timestamp() + 3)
    monkeypatch.setattr(iggs.time, "monotonic", lambda: DT.timestamp() + 3)

    service._tick_pulse_align()
    assert service.phase == "pifinder_pulse_align"
    assert not service.final_sync_sent
    current["timestamp"] = DT.timestamp() + 3
    service._tick_pulse_align()
    assert service.phase == "complete"
    assert service.final_sync_sent
    assert (service.tracking_target_ra, service.tracking_target_dec) == (p.RA, p.Dec)


@pytest.mark.parametrize(
    "error, state_name, expected",
    [
        (0.00, "enabled", "Tracking"),
        (0.05, "enabled", "Tracking"),
        (0.051, "enabled", "Adjusting"),
        (0.40, "enabled", "Adjusting"),
        (0.00, "suspended", "Paused"),
        (0.00, "settling", "Settling"),
    ],
)
def test_lcd_status_uses_current_error_not_historical_complete(
    monkeypatch, error, state_name, expected
):
    import builtins
    from PiFinder.ui.object_details import UIObjectDetails

    monkeypatch.setattr(builtins, "_", lambda value: value, raising=False)
    monkeypatch.setattr(calc_utils, "aim_degrees", lambda *args: (error, 0.0))
    view = SimpleNamespace(
        shared_state=None,
        mount_type="EQ",
        screen_direction="flat3",
        object=SimpleNamespace(ra=12.49, dec=2.44),
        config_object=Config(),
    )
    guide = {
        "phase": "complete",
        "tracking_guide_state": state_name,
        "tracking_guide_enabled": True,
        "tracking_target_ra": 12.49,
        "tracking_target_dec": 2.44,
    }
    assert UIObjectDetails._tracking_status_label(view, guide) == expected
    guide["tracking_target_ra"] = 13.0
    if state_name == "enabled":
        assert UIObjectDetails._tracking_status_label(view, guide) == "Other target"
