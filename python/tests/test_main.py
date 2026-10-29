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


def test_keypad_menu_offsets_off_and_screen_brightness(monkeypatch):
    from unittest.mock import Mock

    led, display = Mock(), Mock()
    monkeypatch.setattr(main, "keypad_led", led)
    monkeypatch.setattr(main, "display_device", display)
    for option, expected in [("0", 5), ("+3", 10), ("-4", 0.65), ("Off", 0)]:
        main.set_brightness(100, _Cfg({"keypad_brightness": option}))
        led.set_brightness.assert_called_with(expected)
        display.set_brightness.assert_called_with(100)
    main.set_brightness(0, _Cfg({"keypad_brightness": "+3"}))
    led.set_brightness.assert_called_with(0)


def test_keypad_failure_does_not_break_ui_or_retry_each_frame(monkeypatch):
    from unittest.mock import Mock

    led = Mock()
    led.set_brightness.side_effect = OSError("disconnected")
    monkeypatch.setattr(main, "keypad_led", led)
    main.set_keypad_brightness(10)
    assert main.keypad_led is None
    led.close.assert_called_once()
    main.set_keypad_brightness(20)
    led.set_brightness.assert_called_once_with(10)


def test_missing_aw9523_does_not_fall_back_to_pwm(monkeypatch):
    from unittest.mock import Mock
    from PiFinder import keypad_led

    factory = Mock(side_effect=OSError("no AW9523"))
    monkeypatch.setattr(main, "keypad_led", None)
    monkeypatch.setattr(main, "hardware_platform", "Pi")
    monkeypatch.setattr(keypad_led, "create_keypad_led", factory)
    main.init_keypad_led(_Cfg({}))
    assert main.keypad_led is None
    factory.assert_called_once()


def test_fake_hardware_does_not_touch_led_bus(monkeypatch):
    from unittest.mock import Mock
    from PiFinder import keypad_led

    factory = Mock()
    monkeypatch.setattr(main, "keypad_led", None)
    monkeypatch.setattr(main, "hardware_platform", "Fake")
    monkeypatch.setattr(keypad_led, "create_keypad_led", factory)
    main.init_keypad_led(_Cfg({}))
    factory.assert_not_called()


def test_sleep_dim_and_wake_restore_keypad(monkeypatch):
    from unittest.mock import Mock

    led, display = Mock(), Mock()
    monkeypatch.setattr(main, "keypad_led", led)
    monkeypatch.setattr(main, "display_device", display)
    cfg = _Cfg({"display_brightness": 100, "keypad_brightness": "0"})
    manager = main.PowerManager(cfg, _PowerSharedState(), display)
    manager.sleep_screen()
    led.set_brightness.assert_called_with(1.25)
    manager.wake_screen()
    led.set_brightness.assert_called_with(5)
