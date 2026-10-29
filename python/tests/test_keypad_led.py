"""A0 register protocol, safe failure, and legacy board selection."""

from unittest.mock import Mock

import pytest

from PiFinder import keypad_led

pytestmark = pytest.mark.unit


class FakeBus:
    def __init__(self, chip_id=0x23):
        self.chip_id = chip_id
        self.registers = {}
        self.events = []
        self.locked = False
        self.busy = False
        self.fail = False

    def try_lock(self):
        if self.busy:
            return False
        assert not self.locked
        self.locked = True
        return True

    def unlock(self):
        assert self.locked
        self.locked = False

    def writeto_then_readfrom(self, address, out, into):
        assert self.locked and address == 0x5B and out == b"\x10"
        self.events.append("id")
        into[0] = self.chip_id

    def writeto(self, address, data):
        assert self.locked and address == 0x5B
        if self.fail:
            raise OSError("disconnected")
        self.events.append(bytes(data))
        for offset, value in enumerate(data[1:]):
            self.registers[data[0] + offset] = value
        # No output may enter LED mode with an unbounded/default current.
        if self.registers.get(0x12) == 0 or self.registers.get(0x13) == 0:
            assert self.registers[0x11] == 3
            assert all(self.registers[i] <= 128 for i in range(0x20, 0x30))


class FakeReset:
    def __init__(self):
        self.history = []
        self.deinitialized = False

    @property
    def value(self):
        return self.history[-1]

    @value.setter
    def value(self, value):
        self.history.append(value)

    def deinit(self):
        self.deinitialized = True


@pytest.fixture
def led(monkeypatch):
    monkeypatch.setattr(keypad_led.time, "sleep", lambda seconds: None)
    bus, reset = FakeBus(), FakeReset()
    return keypad_led.AW9523Keypad(bus, reset), bus, reset


def test_initialize_dark_with_current_limit_before_led_mode(led):
    driver, bus, reset = led
    assert reset.history == [False, True]
    assert bus.events[0] == "id"
    assert bus.registers[0x06] == bus.registers[0x07] == 255
    assert bus.registers[0x12] == bus.registers[0x13] == 0
    assert all(bus.registers[i] == 0 for i in range(0x20, 0x30))
    assert not bus.locked
    driver.close()
    driver.close()
    assert reset.history == [False, True, False]
    assert reset.deinitialized


@pytest.mark.parametrize(
    "percentage,dim",
    [
        (0, 0),
        (-10, 0),
        (0.01, 1),
        (10, 26),
        (25.5, 65),
        (100, 128),
        (200, 128),
        (float("nan"), 0),
        (float("inf"), 0),
    ],
)
def test_brightness_clamping_and_all_sixteen_channels(led, percentage, dim):
    driver, bus, _ = led
    driver.set_brightness(percentage)
    assert [bus.registers[i] for i in range(0x20, 0x30)] == [dim] * 16
    count = len(bus.events)
    driver.set_brightness(percentage)
    assert len(bus.events) == count  # no needless I2C writes each UI frame
    driver.set_brightness(0)
    assert [bus.registers[i] for i in range(0x20, 0x30)] == [0] * 16


def test_bad_identity_does_not_configure_outputs(monkeypatch):
    monkeypatch.setattr(keypad_led.time, "sleep", lambda seconds: None)
    bus, reset = FakeBus(chip_id=0), FakeReset()
    with pytest.raises(keypad_led.AW9523NotFound, match="unexpected ID"):
        keypad_led.AW9523Keypad(bus, reset)
    assert bus.events == ["id"]
    assert not reset.value and reset.deinitialized
    assert not bus.locked


def test_write_failure_shuts_down_via_reset_even_when_bus_is_broken(led):
    driver, bus, reset = led
    driver.set_brightness(10)
    bus.fail = True
    with pytest.raises(OSError):
        driver.set_brightness(20)
    assert driver.closed and not reset.value and reset.deinitialized
    assert not bus.locked
    driver.set_brightness(100)  # failed device stays disabled


def test_contended_bus_has_a_deadline_and_turns_leds_off(led, monkeypatch):
    driver, bus, reset = led
    driver.set_brightness(10)
    bus.busy = True
    ticks = iter([0.0, 0.05, 0.2])
    monkeypatch.setattr(keypad_led.time, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError):
        driver.set_brightness(20)
    assert driver.closed and not reset.value
    assert not bus.locked


def test_initialization_write_failure_releases_reset(monkeypatch):
    monkeypatch.setattr(keypad_led.time, "sleep", lambda seconds: None)
    bus, reset = FakeBus(), FakeReset()
    bus.fail = True
    with pytest.raises(OSError):
        keypad_led.AW9523Keypad(bus, reset)
    assert reset.deinitialized and not reset.value and not bus.locked


class SavedConfig:
    def __init__(self, mode=None):
        self.mode = mode
        self.writes = []

    def get_stored_option(self, key):
        assert key == "board_mode"
        return self.mode

    def set_option(self, key, value):
        assert key == "board_mode"
        self.mode = value
        self.writes.append(value)


@pytest.fixture
def hardware(monkeypatch):
    import sys
    import types
    from PiFinder import i2c_bus

    bus, reset = FakeBus(), FakeReset()
    reset.switch_to_output = Mock()
    make_pin = Mock(return_value=reset)
    pwm = Mock()
    monkeypatch.setitem(sys.modules, "board", types.SimpleNamespace(D12=12))
    monkeypatch.setitem(
        sys.modules, "digitalio", types.SimpleNamespace(DigitalInOut=make_pin)
    )
    monkeypatch.setattr(i2c_bus, "get_i2c", lambda: bus)
    monkeypatch.setattr(keypad_led, "PWMKeypad", pwm)
    monkeypatch.setattr(keypad_led.time, "sleep", lambda seconds: None)
    return bus, reset, make_pin, pwm


@pytest.mark.parametrize("previous", [None, "legacy", "MFNavis_A0"])
def test_a0_identification_persists_and_uses_gpio12(hardware, previous):
    bus, reset, make_pin, pwm = hardware
    cfg = SavedConfig(previous)
    driver = keypad_led.create_keypad_led(cfg)
    assert cfg.mode == "MFNavis_A0"
    assert cfg.writes == ([] if previous == "MFNavis_A0" else ["MFNavis_A0"])
    assert bus.events[0] == "id"  # reprobe even with a saved A0 identity
    make_pin.assert_called_once_with(12)
    reset.switch_to_output.assert_called_once_with(value=False)
    assert driver.i2c is bus
    driver.close()
    pwm.assert_not_called()


def test_wrong_id_selects_legacy_without_configuring_foreign_chip(hardware):
    bus, reset, _, pwm = hardware
    bus.chip_id = 0xFF
    cfg = SavedConfig()
    assert keypad_led.create_keypad_led(cfg) is pwm.return_value
    assert cfg.mode == "legacy"
    assert bus.events == ["id"]
    assert reset.deinitialized and not reset.value


@pytest.mark.parametrize("previous", [None, "legacy", "MFNavis_A0"])
def test_no_ack_retries_then_selects_legacy(hardware, previous):
    import errno

    bus, reset, _, pwm = hardware
    bus.writeto_then_readfrom = Mock(side_effect=OSError(errno.EREMOTEIO, "NACK"))
    cfg = SavedConfig(previous)
    assert keypad_led.create_keypad_led(cfg) is pwm.return_value
    assert bus.writeto_then_readfrom.call_count == 3
    assert cfg.mode == "legacy" and not reset.value


def test_transient_nack_still_detects_a0(hardware):
    import errno

    bus, _, _, pwm = hardware
    read = bus.writeto_then_readfrom
    calls = []

    def retry(*args):
        calls.append(True)
        if len(calls) < 3:
            raise OSError(errno.EREMOTEIO, "NACK")
        read(*args)

    bus.writeto_then_readfrom = retry
    cfg = SavedConfig()
    driver = keypad_led.create_keypad_led(cfg)
    assert cfg.mode == "MFNavis_A0" and len(calls) == 3
    pwm.assert_not_called()
    driver.close()


def test_saved_a0_switches_to_legacy_when_id_no_longer_matches(hardware):
    bus, reset, _, pwm = hardware
    bus.chip_id = 0
    cfg = SavedConfig("MFNavis_A0")
    assert keypad_led.create_keypad_led(cfg) is pwm.return_value
    assert cfg.mode == "legacy" and cfg.writes == ["legacy"]
    assert reset.deinitialized and not reset.value


@pytest.mark.parametrize("previous", [None, "legacy", "MFNavis_A0"])
def test_bus_error_is_not_a_legacy_identification(hardware, previous):
    import errno

    bus, reset, _, pwm = hardware
    bus.writeto_then_readfrom = Mock(side_effect=OSError(errno.EIO, "bus fault"))
    cfg = SavedConfig(previous)
    with pytest.raises(OSError):
        keypad_led.create_keypad_led(cfg)
    assert cfg.mode == previous and cfg.writes == []
    assert reset.deinitialized and not reset.value
    pwm.assert_not_called()


def test_valid_id_is_saved_even_if_led_configuration_fails(hardware):
    bus, _, _, pwm = hardware
    bus.fail = True
    cfg = SavedConfig()
    with pytest.raises(OSError):
        keypad_led.create_keypad_led(cfg)
    assert cfg.mode == "MFNavis_A0"
    pwm.assert_not_called()


def test_legacy_pwm_channel_remains_one(monkeypatch):
    import sys
    import types

    pwm = Mock()
    constructor = Mock(return_value=pwm)
    monkeypatch.setitem(
        sys.modules, "rpi_hardware_pwm", types.SimpleNamespace(HardwarePWM=constructor)
    )
    monkeypatch.setattr(keypad_led, "get_pwm_chip", lambda: 2)
    driver = keypad_led.PWMKeypad()
    constructor.assert_called_once_with(pwm_channel=1, hz=120, chip=2)
    pwm.start.assert_called_once_with(0)
    driver.set_brightness(12.75)
    pwm.change_duty_cycle.assert_called_once_with(12.75)
    driver.close()
    pwm.stop.assert_called_once()


def test_detected_mode_survives_config_reload_without_losing_settings(
    hardware, tmp_path, monkeypatch
):
    import json
    from PiFinder import config

    monkeypatch.setattr(config.utils, "data_dir", tmp_path)
    monkeypatch.setattr(config.utils, "runtime_dir", tmp_path / "runtime")
    (tmp_path / "config.json").write_text(json.dumps({"camera_exp": 123000}))
    cfg = config.Config()
    driver = keypad_led.create_keypad_led(cfg)
    driver.close()
    reloaded = config.Config()
    assert reloaded.get_stored_option("board_mode") == "MFNavis_A0"
    assert reloaded.get_stored_option("camera_exp") == 123000


@pytest.mark.parametrize(
    "saved,expected",
    [
        (None, "legacy"),
        ("legacy", "legacy"),
        ("MFNavis_A0", "MFNavis_A0"),
        ("invalid", "legacy"),
    ],
)
def test_shared_mode_accessor_defaults_to_legacy(saved, expected):
    from PiFinder.board_config import get_board_mode

    assert get_board_mode(SavedConfig(saved)) == expected


def test_board_changes_preserve_all_user_settings(hardware, tmp_path, monkeypatch):
    import json
    from PiFinder import config
    from PiFinder.board_config import get_board_mode

    monkeypatch.setattr(config.utils, "data_dir", tmp_path)
    monkeypatch.setattr(config.utils, "runtime_dir", tmp_path / "runtime")
    settings = {
        "camera_exp": 123000,
        "keypad_brightness": "-2",
        "display_brightness": 64,
        "gps_baud_rate": 9600,
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(settings))
    bus, _, _, pwm = hardware
    for chip_id, expected in [
        (0xFF, "legacy"),
        (0x23, "MFNavis_A0"),
        (0xFF, "legacy"),
        (0x23, "MFNavis_A0"),
    ]:
        bus.chip_id = chip_id
        bus.registers.clear()  # hardware reset on the newly connected carrier
        cfg = config.Config()
        driver = keypad_led.create_keypad_led(cfg)
        driver.close()
        stored = json.loads(config_file.read_text())
        assert stored == {
            **settings,
            "board_mode": expected,
            "source_version": config.get_source_version(),
        }
        assert get_board_mode(config.Config()) == expected
    assert pwm.call_count == 2
