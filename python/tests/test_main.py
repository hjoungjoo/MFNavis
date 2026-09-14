from __future__ import annotations
import pytest

from PiFinder import main


@pytest.mark.smoke
def test_smoke():
    """
    If we get here, all the imports in main work
    """
    assert True


class _Location:
    def __init__(self, source="None", error_in_m=0):
        self.source = source
        self.error_in_m = error_in_m


def test_user_location_can_replace_previous_web_location():
    assert main.should_apply_location_fix(
        _Location(source="WEB", error_in_m=0),
        {"source": "WEB", "error_in_m": 0},
    )


def test_gps_does_not_replace_user_loaded_location():
    assert not main.should_apply_location_fix(
        _Location(source="WEB", error_in_m=0),
        {"source": "GPS", "error_in_m": 1},
    )


def test_config_location_can_replace_previous_manual_location():
    assert main.should_apply_location_fix(
        _Location(source="MANUAL", error_in_m=0),
        {"source": "CONFIG: Home", "error_in_m": 0},
    )


class _PowerSharedState:
    """Minimal stand-in for the SharedState manager proxy."""

    def __init__(self, livecam_settings=None, power_state=0):
        self._livecam_settings = livecam_settings
        self._power_state = power_state
        self.imu_value = None

    def livecam_settings(self):
        if self._livecam_settings is None:
            raise RuntimeError("livecam settings unavailable")
        return self._livecam_settings

    def power_state(self):
        return self._power_state

    def set_power_state(self, value):
        self._power_state = value

    def imu(self):
        return self.imu_value


class _Cfg:
    def __init__(self, options):
        self._options = options

    def get_option(self, option, default=None):
        return self._options.get(option, default)


def _power_manager(shared_state, sleep_timeout="30s"):
    manager = main.PowerManager(
        _Cfg({"sleep_timeout": sleep_timeout, "display_brightness": 128}),
        shared_state,
        display_device=None,
    )
    # wake_screen/sleep_screen drive real hardware.
    manager.wake_screen = lambda: None
    manager.sleep_screen = lambda: None
    return manager


def test_livecam_processing_holds_the_unit_awake():
    # The camera loop captures once per 30 s while asleep, which makes LiveCam
    # unusable; web activity never registers as user activity.
    shared_state = _PowerSharedState({"processing_enabled": True}, power_state=0)
    manager = _power_manager(shared_state)

    assert manager.livecam_holds_wake()
    manager.update()
    assert shared_state.power_state() == 1


def test_livecam_off_lets_the_unit_sleep_normally():
    shared_state = _PowerSharedState({"processing_enabled": False}, power_state=1)
    manager = _power_manager(shared_state)
    manager.last_activity = 0.0  # long idle

    assert not manager.livecam_holds_wake()
    manager.update()
    assert shared_state.power_state() == 0


def test_livecam_wake_check_survives_shared_state_errors():
    # Power management must never take down the main loop.
    shared_state = _PowerSharedState(livecam_settings=None, power_state=1)
    manager = _power_manager(shared_state)

    assert manager.livecam_holds_wake() is False


def test_livecam_wake_check_is_throttled():
    shared_state = _PowerSharedState({"processing_enabled": True}, power_state=1)
    manager = _power_manager(shared_state)

    assert manager.livecam_holds_wake() is True
    # update() runs every main-loop pass, so the proxy read must be cached.
    shared_state._livecam_settings = {"processing_enabled": False}
    assert manager.livecam_holds_wake() is True
    manager._livecam_checked_at = 0.0
    assert manager.livecam_holds_wake() is False


@pytest.mark.parametrize(
    "status_name", ["lens_measurement_status", "distortion_calibration_status"]
)
def test_active_measurement_keeps_progress_awake_until_completion(status_name):
    shared_state = _PowerSharedState({"processing_enabled": False}, power_state=0)
    status = {"state": "measuring"}
    setattr(shared_state, status_name, lambda: status)
    manager = _power_manager(shared_state)
    manager.update()
    assert shared_state.power_state() == 1
    status["state"] = "completed"
    manager._measurement_checked_at = 0.0
    manager.last_activity = 0.0
    manager.update()
    assert shared_state.power_state() == 0
