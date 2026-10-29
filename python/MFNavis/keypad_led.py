"""Keypad illumination: MFNavis_A0 AW9523B, or legacy GPIO13 PWM.

A0: AD1=AD0=1 (0x5b), RSTN=GPIO12, all 16 outputs are LED sinks.
Register definitions/timing: AW9523B datasheet V2.4, sections 8 and 9.
"""

from contextlib import contextmanager
import errno
import logging
import math
import time

from PiFinder.board_config import A0_MODE, LEGACY_MODE, get_pwm_chip

logger = logging.getLogger(__name__)


class AW9523NotFound(Exception):
    """The addressed device did not ACK or did not identify as AW9523B."""


class AW9523Keypad:
    ADDRESS = 0x5B
    # ISEL=3 selects 37 mA / 4. Cap DIM as well, to approximately 4.64 mA
    # per LED (typical), pending thermal/brightness qualification of A0.
    MAX_DIM = 128
    LOCK_TIMEOUT = 0.1

    def __init__(self, i2c, reset, on_detected=None):
        self.i2c = i2c  # Shared with the IMU; never deinit this bus.
        self.reset = reset
        self.closed = False
        self._dim = None
        try:
            self.reset.value = False
            time.sleep(0.001)
            self.reset.value = True
            time.sleep(0.005)
            with self._locked():
                chip_id = bytearray(1)
                for attempt in range(3):
                    try:
                        self.i2c.writeto_then_readfrom(self.ADDRESS, b"\x10", chip_id)
                        break
                    except OSError as exc:
                        if exc.errno not in (
                            errno.ENXIO,
                            errno.EREMOTEIO,
                            errno.ENODEV,
                        ):
                            raise
                        if attempt == 2:
                            raise AW9523NotFound("No AW9523B response at 0x5b") from exc
                        time.sleep(0.01)
                if chip_id[0] != 0x23:
                    raise AW9523NotFound(
                        f"AW9523B at 0x5b: unexpected ID 0x{chip_id[0]:02x}"
                    )
                if on_detected is not None:
                    on_detected()
                # Keep outputs high-impedance while installing the current limit.
                self._write(0x04, b"\xff\xff")
                self._write(0x06, b"\xff\xff")  # interrupts unused
                self._write(0x11, b"\x03")  # ISEL=1/4, reserved bits zero
                self._write(0x20, bytes(16))  # extinguish before LED mode
                self._write(0x12, b"\x00\x00")
            self._dim = 0
        except Exception:
            self.close()
            raise

    @contextmanager
    def _locked(self):
        deadline = time.monotonic() + self.LOCK_TIMEOUT
        while not self.i2c.try_lock():
            if time.monotonic() >= deadline:
                raise TimeoutError("AW9523B I2C bus lock timed out")
            time.sleep(0.001)
        try:
            yield
        finally:
            self.i2c.unlock()

    def _write(self, register, values):
        self.i2c.writeto(self.ADDRESS, bytes([register]) + values)

    def set_brightness(self, percentage):
        if self.closed:
            return
        percentage = float(percentage)
        if not math.isfinite(percentage):
            percentage = 0
        percentage = max(0, min(100, percentage))
        dim = min(self.MAX_DIM, round(255 * percentage / 100))
        # Keep the dimmest non-zero menu levels visible; Off is exactly zero.
        if percentage > 0:
            dim = max(1, dim)
        if dim == self._dim:
            return
        try:
            with self._locked():
                # DIM0..DIM15 are write-only; do not verify via readback.
                # Auto-increment follows schematic LED1..LED16.
                self._write(0x20, bytes([dim]) * 16)
            self._dim = dim
        except Exception:
            # RSTN also shuts down the sinks if I2C itself has failed.
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.reset.value = False
        finally:
            self.reset.deinit()


class PWMKeypad:
    def __init__(self):
        from rpi_hardware_pwm import HardwarePWM

        self.pwm = HardwarePWM(pwm_channel=1, hz=120, chip=get_pwm_chip())
        self.pwm.start(0)

    def set_brightness(self, percentage):
        self.pwm.change_duty_cycle(max(0, min(100, percentage)))

    def close(self):
        self.pwm.stop()


def _save_board_mode(cfg, mode):
    if cfg is not None and cfg.get_stored_option("board_mode") != mode:
        cfg.set_option("board_mode", mode)
    logger.info("Detected board mode: %s", mode)


def create_keypad_led(cfg=None):
    """Probe the actual carrier each startup, then persist a confirmed identity.

    A confirmed missing chip selects legacy, even after a prior A0 detection.
    Bus/permission faults remain errors; they are not evidence of absence.
    Only board_mode is saved: existing user settings stay intact.
    """
    import board
    import digitalio
    from PiFinder.i2c_bus import get_i2c

    i2c = get_i2c()
    reset = digitalio.DigitalInOut(board.D12)
    try:
        reset.switch_to_output(value=False)
    except Exception:
        reset.deinit()
        raise
    try:
        return AW9523Keypad(
            i2c, reset, on_detected=lambda: _save_board_mode(cfg, A0_MODE)
        )
    except AW9523NotFound:
        _save_board_mode(cfg, LEGACY_MODE)
        return PWMKeypad()
