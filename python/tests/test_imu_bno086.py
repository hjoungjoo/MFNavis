"""Exercise real SH-2 decoding with synthetic packets; never open GPIO/I2C."""

import struct
import math
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import quaternion
from PiFinder import imu_pi

# Upstream imports these for annotations, but Blinka opens GPIO on import.
# Stub only that boundary; run the actual pinned packet parser in these tests.
with pytest.MonkeyPatch.context() as import_patch:
    import_patch.setitem(sys.modules, "digitalio", SimpleNamespace(DigitalInOut=object))
    import_patch.setitem(sys.modules, "busio", SimpleNamespace(I2C=object))
    from adafruit_bno08x import Packet
    from PiFinder.imu_bno086 import BNO086, GAME_ROTATION, GYRO, ROTATION
    from PiFinder import imu_bno086

pytestmark = pytest.mark.unit


def bare_sensor():
    sensor = object.__new__(BNO086)
    sensor._tx_sequences = [0] * 6
    sensor._sequence_number = [0] * 6
    sensor._two_ended_sequence_numbers = {}
    sensor._features = (1, 2, 4, 8)
    sensor.orientation_report = GAME_ROTATION
    sensor._samples = {}
    sensor._readings = {}
    sensor._responses = {}
    sensor._debug = False
    sensor._booting = False
    sensor._reset_seen = False
    sensor._last_published = None
    sensor._pending_header = None
    sensor._backlog_started = None
    sensor._heading_yaw = 0.0
    sensor.heading_reference = "relative"
    sensor._dcd_saved_at = -1
    sensor._me_calibration_started_at = -1
    return sensor


def packet(channel, payload):
    return Packet(
        bytearray(struct.pack("<HBB", len(payload) + 4, channel, 12) + payload)
    )


def report(feature=8, seq=1, accuracy=3, values=(0, 0, 0, 16384)):
    return bytes((feature, seq, accuracy, 0)) + struct.pack(
        "<" + "h" * len(values), *values
    )


def fill_reports(sensor):
    for feature in (1, 2, 4):
        sensor._process_report(feature, report(feature, values=(0, 0, 0)))
    sensor._process_report(8, report())


def test_transmit_sequences_are_independent_of_received_sequences():
    sensor = bare_sensor()
    frames = []

    class Bus:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def write(self, frame):
            frames.append(frame)

    sensor.bus_device_obj = Bus()
    sensor._sequence_number[2] = 250
    sensor._send_packet(2, b"a")
    sensor._sequence_number[2] = 31
    sensor._send_packet(2, b"b")
    sensor._send_packet(1, b"c")
    assert [f[3] for f in frames] == [0, 1, 0]
    sensor._tx_sequences[2] = 255
    sensor._send_packet(2, b"d")
    assert sensor._tx_sequences[2] == 0


def test_fifo_batch_keeps_latest_quaternion_and_converts_scalar_first():
    sensor = bare_sensor()
    sensor._handle_packet(
        packet(3, b"\xfb\0\0\0\0" + report() + report(seq=2, values=(16384, 0, 0, 0)))
    )
    assert sensor.quaternion == (0, 1, 0, 0)
    assert sensor.calibration_status == (3, 0, 0, 0)


def test_repeated_report_and_feature_response_do_not_refresh_sample():
    sensor = bare_sensor()
    sensor._process_report(8, report())
    before = sensor._samples[8]
    sensor._process_report(8, report())
    feature_response = bytearray(17)
    feature_response[:2] = bytes((0xFC, 8))
    sensor._process_report(0xFC, feature_response)
    assert sensor._samples[8] is before
    assert sensor.quaternion == (1, 0, 0, 0)


def test_transport_error_and_unexpected_reset_are_not_sensor_data():
    sensor = bare_sensor()
    sensor._handle_packet(packet(0, b"\0advertisement"))
    with pytest.raises(OSError, match="SHTP errors: 0e"):
        sensor._handle_packet(packet(0, b"\x01\x0e"))
    with pytest.raises(OSError, match="unexpectedly reset"):
        sensor._handle_packet(packet(1, b"\x01"))
    sensor._booting = True
    sensor._handle_packet(packet(1, b"\x01"))
    assert sensor._reset_seen


@pytest.mark.parametrize(
    "length,channel,expected",
    [(0, 0, False), (4, 3, False), (16, 3, True), (0x7FFF, 5, False), (16, 7, None)],
)
def test_header_readiness(length, channel, expected):
    sensor = bare_sensor()
    sensor._read_header = lambda: SimpleNamespace(
        packet_byte_count=length, channel_number=channel
    )
    if expected is None:
        with pytest.raises(OSError, match="header"):
            _ = sensor._data_ready
    else:
        assert sensor._data_ready is expected


def test_read_packet_reuses_header_and_reads_payload_once():
    sensor = bare_sensor()
    wire = bytearray(struct.pack("<HBB", 16, 3, 17) + report())
    header = Packet.header_from_buffer(wire)
    sensor._read_header = Mock(return_value=header)

    def read_payload(length):
        assert length == 12
        sensor._data_buffer = wire

    sensor._read = Mock(side_effect=read_payload)
    assert sensor._data_ready
    assert sensor._data_ready
    received = sensor._read_packet()
    assert received.data == report()
    sensor._read_header.assert_called_once()
    sensor._read.assert_called_once_with(12)
    assert sensor._pending_header is None


def test_wait_for_packet_retries_transient_empty_read(monkeypatch):
    from adafruit_bno08x import PacketError

    sensor = bare_sensor()
    monkeypatch.setattr(BNO086, "_data_ready", property(lambda self: True))
    expected = packet(2, bytes((0xF8,)) + bytes(15))
    sensor._read_packet = Mock(side_effect=[PacketError("empty"), expected])
    assert sensor._wait_for_packet() is expected
    assert sensor._read_packet.call_count == 2


def test_freshness_requires_new_orientation_and_all_reports_alive():
    sensor = bare_sensor()
    fill_reports(sensor)
    sensor._process_available_packets = lambda: True
    assert sensor.refresh() is True
    stamp = sensor.sample_time
    assert sensor.refresh() is False
    assert sensor.sample_time == stamp
    entry = list(sensor._samples[GYRO])
    entry[3] = time.monotonic() - 2
    sensor._samples[GYRO] = tuple(entry)
    with pytest.raises(TimeoutError, match="reports stopped"):
        sensor.refresh()


def test_backlog_does_not_publish_old_orientation_as_fresh():
    sensor = bare_sensor()
    fill_reports(sensor)
    sensor._process_available_packets = lambda: False
    assert sensor.refresh() is False
    assert sensor._last_published is None
    sensor._backlog_started = time.monotonic() - 2
    with pytest.raises(TimeoutError, match="backlog"):
        sensor.refresh()
    assert sensor._last_published is None


def test_short_backlog_recovers_without_false_sensor_error():
    sensor = bare_sensor()
    fill_reports(sensor)
    sensor._process_available_packets = Mock(side_effect=[False, True])
    assert sensor.refresh() is False
    assert sensor.refresh() is True
    assert sensor._backlog_started is None


def test_packet_poll_has_hard_count_bound(monkeypatch):
    sensor = bare_sensor()
    monkeypatch.setattr(BNO086, "_data_ready", property(lambda self: True))
    sensor._read_packet = Mock(return_value=packet(0, b"\0"))
    assert sensor._process_available_packets(max_packets=3) is False
    assert sensor._read_packet.call_count == 3


@pytest.mark.parametrize("mag,expected", [(False, GAME_ROTATION), (True, ROTATION)])
def test_initialization_configures_requested_mode_without_host_calibration(
    monkeypatch, mag, expected
):
    from adafruit_bno08x.i2c import BNO08X_I2C

    monkeypatch.setattr(BNO08X_I2C, "__init__", lambda self, bus, **kwargs: None)
    monkeypatch.setattr(BNO086, "_configure", lambda self: None)
    sensor = BNO086(object(), use_magnetometer=mag)
    assert sensor.orientation_report == expected
    assert (3 in sensor._features) is mag
    assert (8 in sensor._features) is not mag


def test_command_requires_matching_acknowledgement():
    sensor = bare_sensor()
    sensor._send_packet = Mock()

    def respond():
        # An unrelated command response must not satisfy the save operation.
        sensor._process_report(0xF1, bytearray((0xF1, 0, 7, 0, 0, 0) + (0,) * 10))
        sensor._process_report(0xF1, bytearray((0xF1, 0, 6, 0, 0, 0) + (0,) * 10))

    sensor._process_available_packets = respond
    sensor.save_calibration()
    assert sensor._send_packet.call_args.args[1][:3] == bytes((0xF2, 0, 6))
    assert sensor._get_report_seq_id(0xF2) == 1


def make_imu(monkeypatch, mode="MFNavis_A0", mag=False):
    cfg = SimpleNamespace(
        get_stored_option=lambda key: mode,
        get_option=lambda key, default: mag
        if key == "imu_use_magnetometer"
        else default,
    )
    monkeypatch.setattr(imu_pi.config, "Config", lambda: cfg)
    monkeypatch.setattr(imu_pi, "get_i2c", lambda: object())
    sensor = SimpleNamespace(
        fusion_mode="rotation_vector" if mag else "game_rotation_vector",
        quaternion=(1, 0, 0, 0),
        calibration_status=(3, 3, 2, 0),
        sample_time=time.time(),
        refresh=lambda: True,
        gyro=(0, 0, 0),
        linear_acceleration=(0, 0, 0),
        save_calibration=Mock(),
        load_calibration=Mock(),
        clear_calibration=Mock(),
        close=Mock(),
    )
    monkeypatch.setattr(
        sys.modules["PiFinder.imu_bno086"], "BNO086", lambda *a, **kw: sensor
    )
    legacy = SimpleNamespace(
        BNO055_I2C=Mock(return_value=sensor), NDOF_MODE=12, IMUPLUS_MODE=8
    )
    monkeypatch.setitem(sys.modules, "adafruit_bno055", legacy)
    imu = imu_pi.Imu()
    imu.imu_sample_frequency = 0
    return imu, sensor, legacy


@pytest.mark.parametrize(
    "mode,model", [("MFNavis_A0", "BNO086"), ("legacy", "BNO055"), (None, "BNO055")]
)
def test_detected_carrier_selects_driver(monkeypatch, mode, model):
    imu, _, legacy = make_imu(monkeypatch, mode)
    assert imu.sensor_model == model
    assert legacy.BNO055_I2C.call_count == int(model == "BNO055")


def test_a0_failure_never_silently_selects_bno055(monkeypatch):
    _, _, legacy = make_imu(monkeypatch)
    monkeypatch.setattr(
        sys.modules["PiFinder.imu_bno086"],
        "BNO086",
        Mock(side_effect=OSError("offline")),
    )
    with pytest.raises(OSError, match="offline"):
        imu_pi.Imu()
    legacy.BNO055_I2C.assert_not_called()


def test_a0_sign_continuity_and_no_cached_timestamp_renewal(monkeypatch):
    imu, sensor, _ = make_imu(monkeypatch)
    imu.update()
    first = imu.last_read_time
    sensor.quaternion = (-1, 0, 0, 0)
    sensor.sample_time += 0.03
    imu.update()
    assert imu.avg_quat == (1, 0, 0, 0)
    assert not imu.moving()
    assert imu.last_read_time > first
    latest = imu.last_read_time
    sensor.refresh = lambda: False
    sensor.sample_time += 1
    imu.update()
    assert imu.last_read_time == latest


def test_a0_accuracy_gate_and_optional_raw_capture(monkeypatch):
    imu, sensor, _ = make_imu(monkeypatch)
    sensor.calibration_status = (0, 3, 2, 0)
    imu.update()
    assert imu.calibration == 0
    assert imu.last_read_time == 0
    sensor.calibration_status = (3, 3, 2, 0)
    imu.set_raw_capture(True)
    imu.update()
    assert imu.calibration == 3
    assert imu.gyro == sensor.gyro
    assert imu.accel == sensor.linear_acceleration


def test_a0_calibration_uses_sensor_storage_not_bno055_offset_file(monkeypatch):
    imu, sensor, _ = make_imu(monkeypatch)
    for name in (
        "load_snapshot",
        "save_snapshot",
        "clear_snapshot",
        "snapshot_from_sensor",
    ):
        monkeypatch.setattr(
            imu_pi.imu_calibration,
            name,
            Mock(side_effect=AssertionError("BNO055 file accessed")),
        )
    assert imu.save_calibration()
    assert imu.load_calibration()
    assert imu.clear_calibration()
    sensor.save_calibration.assert_called_once()
    sensor.load_calibration.assert_called_once()
    sensor.clear_calibration.assert_called_once()
    assert imu.last_read_time == 0


def test_auto_save_is_once_per_run_and_respects_disabled_option(monkeypatch):
    imu, sensor, _ = make_imu(monkeypatch)
    sensor.calibration_status = (3, 3, 3, 0)
    imu.auto_calibration_store = False
    imu.update()
    sensor.save_calibration.assert_not_called()
    imu.auto_calibration_store = True
    imu.update()
    imu.update()
    sensor.save_calibration.assert_called_once()


@pytest.mark.parametrize(
    "heading,game_yaw,roll,pitch",
    [
        (0, 90, 0, 0),
        (359, 1, 45, 60),
        (1, 359, 170, -70),
        (270, 10, -120, 80),
    ],
)
def test_compass_seed_preserves_tilt_and_recovers_heading(
    heading, game_yaw, roll, pitch
):
    def rotation(axis, degrees):
        a = math.radians(degrees) / 2
        v = [0.0] * 3
        v[axis] = math.sin(a)
        return quaternion.quaternion(math.cos(a), *v)

    tilt = rotation(0, roll) * rotation(1, pitch)
    true = rotation(2, heading) * tilt
    game = rotation(2, game_yaw) * tilt
    magnetic = quaternion.rotate_vectors(true.conj(), [0, 25, -40])
    offset = imu_bno086.magnetic_yaw_offset(quaternion.as_float_array(game), magnetic)
    sensor = bare_sensor()
    sensor._heading_yaw = offset
    w, x, y, z = quaternion.as_float_array(game)
    sensor._samples[8] = (1, (x, y, z, w), 3, 1, 1)
    corrected = quaternion.quaternion(*sensor.quaternion)
    assert abs(
        float(quaternion.as_float_array(corrected * true.conj())[0])
    ) == pytest.approx(1)
    # Later gyro motion retains the same world reference without magnetic input.
    delta = rotation(0, 23) * rotation(2, -35)
    later = game * delta
    w, x, y, z = quaternion.as_float_array(later)
    sensor._samples[8] = (2, (x, y, z, w), 3, 2, 2)
    expected = true * delta
    corrected = quaternion.quaternion(*sensor.quaternion)
    assert abs(
        float(quaternion.as_float_array(corrected * expected.conj())[0])
    ) == pytest.approx(1)


@pytest.mark.parametrize(
    "field", [(0, 0, 0), (0, 0, 50), (0, 1000, 0), (float("nan"), 25, 0)]
)
def test_invalid_or_vertical_field_has_no_startup_heading(field):
    assert imu_bno086.magnetic_yaw_offset((1, 0, 0, 0), field) is None


def compass_rig(monkeypatch, *, field=(25, 0, -40), moving=False, missing=False):
    sensor = bare_sensor()
    clock = [0.0]
    sequence = [0]
    monkeypatch.setattr(imu_bno086.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        imu_bno086.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + 0.05)
    )
    sensor._command = Mock()
    sensor._send_packet = Mock()

    def poll():
        sequence[0] += 1
        stamp = clock[0]
        sensor._samples[8] = (sequence[0], (0, 0, 0, 1), 3, stamp, stamp)
        sensor._samples[2] = (sequence[0], (1 if moving else 0, 0, 0), 3, stamp, stamp)
        if not missing:
            sensor._samples[3] = (sequence[0], field, 0, stamp, stamp)
        return True

    sensor._process_available_packets = poll
    return sensor, clock


def test_startup_uses_uncalibrated_compass_once_then_disables_it(monkeypatch):
    sensor, clock = compass_rig(monkeypatch)
    sensor._seed_magnetic_heading()
    assert 1.5 <= clock[0] < 5
    assert sensor.startup_heading_status == "acquired"
    assert sensor.heading_reference == "startup_magnetic"
    assert sensor._heading_yaw == pytest.approx(math.pi / 2)
    assert 3 not in sensor._features and 3 not in sensor._samples
    assert sensor._command.call_args.args == (7, (1, 1, 0))
    assert sensor._send_packet.call_args.args[1][1] == 3
    assert struct.unpack_from("<I", sensor._send_packet.call_args.args[1], 5)[0] == 0


@pytest.mark.parametrize(
    "kwargs", [{"missing": True}, {"moving": True}, {"field": (0, 0, 0)}]
)
def test_startup_timeout_keeps_relative_game_mode_and_disables_mag(monkeypatch, kwargs):
    sensor, clock = compass_rig(monkeypatch, **kwargs)
    sensor._seed_magnetic_heading()
    assert 5 <= clock[0] < 5.1
    assert sensor.startup_heading_status == "unavailable"
    assert sensor.heading_reference == "relative"
    assert sensor._heading_yaw == 0
    assert 3 not in sensor._features
    assert sensor._command.call_args.args == (7, (1, 1, 0))


def test_a0_ignores_legacy_continuous_magnetometer_option(monkeypatch):
    imu, _, _ = make_imu(monkeypatch, mag=True)
    assert imu.use_magnetometer is False


def test_legacy_continuous_magnetometer_setting_is_preserved(monkeypatch):
    monkeypatch.setattr(imu_pi.imu_calibration, "load_snapshot", lambda: None)
    imu, sensor, legacy = make_imu(monkeypatch, mode="legacy", mag=True)
    assert imu.use_magnetometer is True
    assert imu.fusion_mode == "ndof"
    assert sensor.mode == legacy.NDOF_MODE


def test_startup_io_error_still_attempts_to_disable_magnetic_reports(monkeypatch):
    sensor, _ = compass_rig(monkeypatch)
    sensor._process_available_packets = Mock(side_effect=OSError("bus failure"))
    with pytest.raises(OSError, match="bus failure"):
        sensor._seed_magnetic_heading()
    assert 3 not in sensor._features
    assert sensor._command.call_args.args == (7, (1, 1, 0))
