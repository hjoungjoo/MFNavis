from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from PiFinder.calc_utils import FastAltAz
from PiFinder.mount_motion_limits import MountMotionLimitsMixin, LIMIT_ERRORS

pytestmark = pytest.mark.unit


class Mount(MountMotionLimitsMixin):
    def __init__(self):
        self.raw = "nANo090"
        self.numbers = {}
        self.device = SimpleNamespace(
            getNumber=lambda name: [
                SimpleNamespace(name=k, value=v)
                for k, v in self.numbers.get(name, {}).items()
            ]
        )
        self.position = None
        self.dt = datetime(2026, 10, 10, tzinfo=timezone.utc)

    def _raw_onstep_status(self):
        return self.raw

    def _read_cached_current_position(self, **kwargs):
        return self.position

    def _shared_location_time_values(self):
        return 35, 127, 0, self.dt


@pytest.mark.parametrize("error", LIMIT_ERRORS)
def test_firmware_axis_switch_and_elevation_errors(error):
    mount = Mount()
    mount.raw = "nANo09" + chr(ord("0") + error) + "#"
    assert mount._motion_limit_reason() == LIMIT_ERRORS[error]


def test_live_elevation_limits_no_alignment_star_defaults():
    mount = Mount()
    mount.numbers["HORIZONTAL_COORD"] = {"ALT": -5}
    assert not mount._motion_limit_reason()
    mount.numbers["Slew elevation Limit"] = {"minAlt": -10, "maxAlt": 80}
    assert not mount._motion_limit_reason()
    mount.numbers["HORIZONTAL_COORD"]["ALT"] = -11
    assert "-11.00 < -10.00" in mount._motion_limit_reason()
    mount.numbers["HORIZONTAL_COORD"]["ALT"] = 81
    assert "81.00 > 80.00" in mount._motion_limit_reason()
    mount.numbers["Slew elevation Limit"]["maxAlt"] = 85
    assert not mount._motion_limit_reason()


def test_target_altitude_is_checked_even_while_current_mount_is_safe():
    mount = Mount()
    mount.numbers["Slew elevation Limit"] = {"minAlt": -10, "maxAlt": 80}
    mount.numbers["HORIZONTAL_COORD"] = {"ALT": 45}
    ra = FastAltAz(35, 127, mount.dt).local_siderial_time
    assert not mount._motion_limit_reason()
    assert "80.00" in mount._motion_limit_reason((ra, 35))


@pytest.mark.parametrize("side,ha", [("T", -6), ("W", 6)])
def test_meridian_limits_apply_to_current_gem_side_only(side, ha):
    mount = Mount()
    mount.numbers["Minutes Past Meridian"] = {"East": 20, "West": 20}
    ra = FastAltAz(35, 127, mount.dt).local_siderial_time - ha
    mount.position = (ra, 35)
    mount.raw = "nEN" + side + "090"
    assert "meridian limit" in mount._motion_limit_reason()
    assert not mount._motion_limit_reason(mount.position)
    mount.raw = "nANo090"
    assert not mount._motion_limit_reason()


def test_pulse_worker_defers_stop_and_refuses_command():
    mount = Mount()
    mount.raw = "nANo093"
    assert not mount._guard_motion(defer_stop=True)
    assert mount._pending_motion_limit == "hardware limit switch"


def test_controller_site_checks_limits_without_a_handheld_gps_lock():
    mount = Mount()
    mount._shared_location_time_values = lambda: (None, None, None, mount.dt)
    mount.numbers["GEOGRAPHIC_COORD"] = {"LAT": 35, "LONG": 127}
    mount.numbers["Slew elevation Limit"] = {"minAlt": -10, "maxAlt": 80}
    ra = FastAltAz(35, 127, mount.dt).local_siderial_time
    mount.position = (ra, 35)
    assert "80.00" in mount._motion_limit_reason()
