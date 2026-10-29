"""MFNavis_A0 BNO086 adapter (I2C1, 0x4B).

Uses the pinned Adafruit 1.3.3 decoder, with independent SHTP transmit
sequences, channel routing and FIFO batch processing. Import only when A0
has been identified: importing Blinka can access GPIO on a Raspberry Pi.
"""

import logging
import math
import struct
import time

from adafruit_bno08x import Packet, PacketError, _separate_batch, parse_sensor_id
from adafruit_bno08x.i2c import BNO08X_I2C

logger = logging.getLogger("IMU.bno086")

ACCEL, GYRO, MAG, LINEAR_ACCEL, ROTATION, GAME_ROTATION = 1, 2, 3, 4, 5, 8
REPORT_INTERVAL_US = 33333
REPORT_TIMEOUT = 1.0
HEADING_STARTUP_TIMEOUT = 5.0


def magnetic_yaw_offset(quat, magnetic):
    """Yaw that maps the tilt-compensated magnetic field to world +Y (north).

    Game RV maps native sensor vectors to its gravity-aligned world frame.
    Only its arbitrary yaw is corrected; pitch/roll and subsequent gyro motion
    remain unchanged. This is approximate magnetic north, not true north.
    """
    if not all(math.isfinite(v) for v in (*quat, *magnetic)):
        return None
    norm = math.sqrt(sum(v * v for v in quat))
    field = math.sqrt(sum(v * v for v in magnetic))
    if not 0.8 <= norm <= 1.2 or not 10 <= field <= 100:
        return None
    w, x, y, z = (v / norm for v in quat)
    mx, my, mz = magnetic
    east = (
        (1 - 2 * (y * y + z * z)) * mx
        + 2 * (x * y - w * z) * my
        + 2 * (x * z + w * y) * mz
    )
    north = (
        2 * (x * y + w * z) * mx
        + (1 - 2 * (x * x + z * z)) * my
        + 2 * (y * z - w * x) * mz
    )
    if math.hypot(east, north) < 5:
        return None
    return math.atan2(east, north)


class BNO086(BNO08X_I2C):
    """Cached scalar-first orientation and BNO055-compatible status tuple.

    ``refresh`` alone polls the bus. Properties never consume additional
    packets, so quaternion, accuracy and receipt epoch refer to one report.
    SH-2 accuracy levels are not BNO055 offset-calibration levels.
    """

    def __init__(self, i2c, *, use_magnetometer=False):
        self.use_magnetometer = use_magnetometer
        self.orientation_report = ROTATION if use_magnetometer else GAME_ROTATION
        self.fusion_mode = (
            "rotation_vector" if use_magnetometer else "game_rotation_vector"
        )
        self._features = (ACCEL, GYRO, LINEAR_ACCEL, self.orientation_report)
        if use_magnetometer:
            self._features += (MAG,)
        self._tx_sequences = [0] * 6
        self._samples = {}
        self._responses = {}
        self._booting = True
        self._reset_seen = False
        self._last_published = None
        self._pending_header = None
        self._backlog_started = None
        self.product_id = None
        self.heading_reference = "magnetic" if use_magnetometer else "relative"
        self.startup_heading_status = "not_requested"
        self._heading_yaw = 0.0
        try:
            super().__init__(i2c, address=0x4B)
            self._booting = False
            self._configure()
        except Exception:
            self.close()
            raise
        logger.info(
            "BNO086 at 0x4B, product=%s, mode=%s", self.product_id, self.fusion_mode
        )

    def soft_reset(self):
        self._pending_header = None
        self._tx_sequences = [0] * 6
        super().soft_reset()
        self._tx_sequences = [0] * 6
        self._samples.clear()
        self._responses.clear()
        self._last_published = None

    def _parse_sensor_id(self):
        part = super()._parse_sensor_id()
        if part is not None:
            self.product_id = parse_sensor_id(self._data_buffer[4:20])
        return part

    def _send_packet(self, channel, data):
        sequence = self._tx_sequences[channel]
        frame = struct.pack("<HBB", len(data) + 4, channel, sequence) + bytes(data)
        with self.bus_device_obj as bus:
            bus.write(frame)
        self._tx_sequences[channel] = (sequence + 1) & 0xFF
        return self._tx_sequences[channel]

    @property
    def _data_ready(self):
        if self._pending_header is not None:
            return True
        header = self._read_header()
        # All-ones is the idle response seen while this I2C sensor boots.
        if header.packet_byte_count in (0, 4, 0x7FFF):
            return False
        if not 4 < header.packet_byte_count < 0x7FFF or header.channel_number > 5:
            raise OSError("Invalid BNO086 SHTP header")
        self._pending_header = header
        return True

    def _read_packet(self):
        # Reuse the readiness header. Re-reading it a second time can race
        # the sensor on RP1 I2C, returning an empty header during ID startup.
        if not self._data_ready:
            raise PacketError("No packet available")
        header, self._pending_header = self._pending_header, None
        self._read(header.packet_byte_count - 4)
        packet = Packet(self._data_buffer)
        if packet.header.packet_byte_count == 0:
            raise PacketError("No packet available")
        if (
            packet.header.packet_byte_count != header.packet_byte_count
            or packet.channel_number != header.channel_number
        ):
            raise OSError("BNO086 packet changed during read")
        return packet

    def _wait_for_packet(self, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._data_ready:
                try:
                    return self._read_packet()
                except PacketError:
                    pass
            time.sleep(0.001)
        raise TimeoutError("Timed out waiting for BNO086 packet")

    def _check_id(self):
        try:
            return super()._check_id()
        except Exception:
            logger.warning("BNO086 product identification failed", exc_info=True)
            raise

    def _handle_packet(self, packet):
        channel, data = packet.channel_number, packet.data
        if channel == 0:
            # Advertisement (0) and error list (1) are not sensor reports.
            if data and data[0] == 1 and any(data[1:]):
                raise OSError(f"BNO086 SHTP errors: {bytes(data[1:]).hex()}")
            return
        if channel == 1:
            if data and data[0] == 1:
                self._reset_seen = True
                if not self._booting:
                    raise OSError("BNO086 unexpectedly reset")
            return
        if channel not in (2, 3, 4):
            raise OSError(f"Unexpected BNO086 channel {channel}")
        reports = []
        _separate_batch(packet, reports)
        # The upstream LIFO handler can overwrite a new reading with an old one.
        for report_id, report in reports:
            self._process_report(report_id, report)

    def _process_report(self, report_id, data):
        if report_id == 0xF1:
            self._responses[(data[2], data[3])] = data[5]
        super()._process_report(report_id, data)
        if report_id in self._features:
            old = self._samples.get(report_id)
            if old is not None and old[0] == data[1]:
                return  # Repeated sensor sequence must not renew freshness.
            self._samples[report_id] = (
                data[1],
                tuple(self._readings[report_id]),
                data[2] & 3,
                time.monotonic(),
                time.time(),
            )

    def _process_available_packets(self, max_packets=32):
        deadline = time.monotonic() + 0.025
        for _ in range(max_packets or 32):
            if not self._data_ready:
                return True
            try:
                packet = self._read_packet()
            except PacketError:
                return True  # Sensor became empty between header reads.
            self._handle_packet(packet)
            if time.monotonic() >= deadline:
                break
        return not self._data_ready

    def _command(self, command, params=(), *, response=True):
        sequence = self._get_report_seq_id(0xF2)
        request = bytearray(12)
        request[:3] = bytes((0xF2, sequence, command))
        request[3 : 3 + len(params)] = bytes(params)
        key = (command, sequence)
        self._responses.pop(key, None)
        self._send_packet(2, request)
        self._increment_report_seq(0xF2)
        if not response:
            return
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            self._process_available_packets()
            if key in self._responses:
                status = self._responses.pop(key)
                if status:
                    raise RuntimeError(f"BNO086 command {command:#x}: status {status}")
                return
            time.sleep(0.005)
        raise TimeoutError(f"BNO086 command {command:#x} response timed out")

    def _configure(self):
        self._samples.clear()
        self._last_published = None
        self._backlog_started = None
        self._heading_yaw = 0.0
        self.heading_reference = "magnetic" if self.use_magnetometer else "relative"
        # Manage flash writes explicitly, once per run or by a manual save.
        self._command(9, (1,), response=False)  # Disable firmware DCD auto-save.
        self._command(7, (1, 1, int(self.use_magnetometer)))
        for feature in self._features:
            self._send_packet(
                2, self._get_feature_enable_report(feature, REPORT_INTERVAL_US)
            )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            self._process_available_packets()
            if all(feature in self._samples for feature in self._features):
                break
            time.sleep(0.005)
        else:
            raise TimeoutError("BNO086 did not start all requested reports")
        if not self.use_magnetometer:
            self._seed_magnetic_heading()

    def _seed_magnetic_heading(self):
        """Acquire a startup-only compass reference without resetting Game RV.

        Uncalibrated magnetic vectors can still provide a rough compass. Do
        not label this a calibrated absolute heading or wait for accuracy 3.
        Require a stable field while stationary, and bound the startup delay.
        No orientation is published until this acquisition finishes.
        """
        self.startup_heading_status = "pending"
        self._features += (MAG,)
        start = time.monotonic()
        angles = []
        last_sequence = None
        window_start = start
        try:
            self._command(7, (1, 1, 1))
            self._send_packet(2, self._get_feature_enable_report(MAG, 50000))
            while time.monotonic() - start < HEADING_STARTUP_TIMEOUT:
                drained = self._process_available_packets()
                now = time.monotonic()
                if drained and now - start >= 1.0:
                    mag = self._samples.get(MAG)
                    game = self._samples.get(GAME_ROTATION)
                    gyro = self._samples.get(GYRO)
                    if mag and game and gyro and mag[0] != last_sequence:
                        last_sequence = mag[0]
                        angle = None
                        if (
                            max(now - s[3] for s in (mag, game, gyro)) < 0.15
                            and abs(mag[3] - game[3]) < 0.1
                            and game[2] >= 2
                            and math.sqrt(sum(v * v for v in gyro[1])) < 0.15
                        ):
                            x, y, z, w = game[1]
                            angle = magnetic_yaw_offset((w, x, y, z), mag[1])
                        if angle is None:
                            angles.clear()
                        else:
                            if not angles:
                                window_start = now
                            angles.append(angle)
                            sx = sum(math.sin(a) for a in angles)
                            cx = sum(math.cos(a) for a in angles)
                            mean = math.atan2(sx, cx)
                            spread = max(
                                abs(math.atan2(math.sin(a - mean), math.cos(a - mean)))
                                for a in angles
                            )
                            if spread > math.radians(5):
                                angles.clear()
                            elif len(angles) >= 8 and now - window_start >= 0.5:
                                self._heading_yaw = mean
                                self.heading_reference = "startup_magnetic"
                                self.startup_heading_status = "acquired"
                                break
                time.sleep(0.005)
            else:
                self.startup_heading_status = "unavailable"
        finally:
            # Never leave magnetic tracking active after success or timeout.
            self._send_packet(2, self._get_feature_enable_report(MAG, 0))
            self._command(7, (1, 1, 0))
            self._features = tuple(f for f in self._features if f != MAG)
            self._samples.pop(MAG, None)
        logger.info(
            "BNO086 startup compass: %s, yaw offset %.1f deg; Game RV active",
            self.startup_heading_status,
            math.degrees(self._heading_yaw),
        )

    def refresh(self):
        if not self._process_available_packets():
            now = time.monotonic()
            if self._backlog_started is None:
                self._backlog_started = now
            elif now - self._backlog_started > REPORT_TIMEOUT:
                raise TimeoutError("BNO086 report backlog did not drain")
            # A busy camera/solver can consume this loop's scheduling budget.
            # Keep the last published epoch; partial draining is not fresh data.
            return False
        self._backlog_started = None
        now = time.monotonic()
        stale = [
            f for f in self._features if now - self._samples[f][3] > REPORT_TIMEOUT
        ]
        if stale:
            raise TimeoutError(f"BNO086 sensor reports stopped: {stale}")
        sample = self._samples[self.orientation_report]
        if sample[3] == self._last_published:
            return False
        self._last_published = sample[3]
        return True

    @property
    def sample_time(self):
        return self._samples[self.orientation_report][4]

    @property
    def quaternion(self):
        x, y, z, w = self._samples[self.orientation_report][1]
        c, s = math.cos(self._heading_yaw / 2), math.sin(self._heading_yaw / 2)
        return c * w - s * z, c * x - s * y, c * y + s * x, c * z + s * w

    @property
    def calibration_status(self):
        return tuple(
            self._samples[f][2] if f in self._samples else 0
            for f in (self.orientation_report, GYRO, ACCEL, MAG)
        )

    @property
    def gyro(self):
        return self._samples[GYRO][1]

    @property
    def linear_acceleration(self):
        return self._samples[LINEAR_ACCEL][1]

    def save_calibration(self):
        self._command(6)  # Save Dynamic Calibration Data in the sensor flash.

    def load_calibration(self):
        # SH-2 loads its persisted DCD during initialization, not from the
        # BNO055 host offset file. There is no "saved DCD exists" status bit.
        self._booting = True
        try:
            self.initialize()
        finally:
            self._booting = False
        self._configure()

    def clear_calibration(self):
        # SH-2 0x0B clears DCD in RAM and resets; it does not erase flash DCD.
        # Keep that distinction visible in the command's user-facing result.
        self._reset_seen = False
        self._booting = True
        try:
            self._command(0x0B, response=False)
            deadline = time.monotonic() + 3.0
            while not self._reset_seen and time.monotonic() < deadline:
                self._process_available_packets()
                time.sleep(0.005)
            if not self._reset_seen:
                raise TimeoutError("BNO086 calibration reset not acknowledged")
            self._tx_sequences = [0] * 6
            self._two_ended_sequence_numbers.clear()
            self._responses.clear()
        finally:
            self._booting = False
        self._configure()

    def close(self):
        if not hasattr(self, "bus_device_obj"):
            return
        for feature in self._features:
            try:
                self._send_packet(2, self._get_feature_enable_report(feature, 0))
            except Exception:
                logger.debug(
                    "Could not disable BNO086 report %s", feature, exc_info=True
                )
