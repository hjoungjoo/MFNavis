#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for IMU related functions

"""

import time
import queue
import math
from PiFinder import config, imu_calibration
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.types.positioning import ImuSample
from PiFinder.i2c_bus import get_i2c
import adafruit_bno055
import logging
import quaternion  # Numpy quaternion

logger = logging.getLogger("IMU.pi")

QUEUE_LEN = 10
IMU_REINITIALIZE_AFTER_ERRORS = 3
IMU_REINITIALIZE_INITIAL_DELAY_SECONDS = 1.0
IMU_REINITIALIZE_MAX_DELAY_SECONDS = 30.0


class Imu:
    """
    Previous version modified the IMU axes but the IMU now outputs the
    measurements using its native axes and the transformation from the IMU
    axes to the camera frame is done by the IMU dead-reckonig functionality.
    """

    def __init__(self):
        cfg = config.Config()
        i2c = get_i2c()
        self.sensor = adafruit_bno055.BNO055_I2C(i2c)
        self.use_magnetometer = bool(cfg.get_option("imu_use_magnetometer", False))
        self.auto_calibration_store = bool(
            cfg.get_option("imu_auto_calibration_store", True)
        )
        self.fusion_mode = "ndof" if self.use_magnetometer else "imuplus"
        if self.use_magnetometer:
            # NDOF mode uses accelerometer, gyroscope, magnetometer, and
            # fusion data. It improves absolute heading after calibration,
            # but needs a magnetically clean setup and calibration movement.
            self.sensor.mode = adafruit_bno055.NDOF_MODE
        else:
            # IMUPLUS mode: accelerometer + gyro + fusion data. This is the
            # legacy drift-limited relative mode and remains the default.
            self.sensor.mode = adafruit_bno055.IMUPLUS_MODE
        self.calibration_loaded = False
        self.calibration_saved_now = False
        self._calibration_saved_this_run = False
        self._last_calibration_status = None
        self._last_invalid_quat_log = 0.0
        if self.use_magnetometer and self.auto_calibration_store:
            self._load_saved_calibration()

        self.quat_history = [(0, 0, 0, 0)] * QUEUE_LEN
        self._flip_count = 0
        self.calibration = 0
        self.calibration_status = (0, 0, 0, 0)
        self.avg_quat = (0, 0, 0, 0)  # Scalar-first quaternion as float: (w, x, y, z)
        # Raw sensor readings taken alongside the quaternion, for telemetry
        self.gyro = None
        self.accel = None
        # Epoch of the last successful sensor read
        self.last_read_time = 0.0
        # Epoch of the last successful I2C interaction, including a calibration
        # status read before the sensor is ready to supply an orientation.
        self.last_io_time = 0.0
        self.__moving = False
        self.__reading_diff = 0.0

        self.last_sample_time = time.time()

        # Calibration settings
        self.imu_sample_frequency = 1 / 30

        # First value is delta to exceed between samples
        # to start moving, second is threshold to fall below
        # to stop moving.

        # Raw gyro/accel capture is opt-in: two extra I2C transactions per
        # sample on a bus the BNO055 is sensitive about, and only useful
        # for telemetry analysis.
        self._raw_telemetry_config = bool(cfg.get_option("telemetry_raw_imu", False))
        self._raw_capture_runtime = False
        self._raw_telemetry = self._raw_telemetry_config
        imu_threshold_scale = cfg.get_option("imu_threshold_scale", 1)
        self.__moving_threshold = (
            0.0005 * imu_threshold_scale,
            0.0003 * imu_threshold_scale,
        )

    def set_raw_capture(self, enabled: bool) -> None:
        self._raw_capture_runtime = bool(enabled)
        self._raw_telemetry = self._raw_telemetry_config or self._raw_capture_runtime

    def _load_saved_calibration(self) -> None:
        try:
            snapshot = imu_calibration.load_snapshot()
            if not snapshot:
                return
            imu_calibration.apply_snapshot_to_sensor(self.sensor, snapshot)
            self.calibration_loaded = True
            logger.info(
                "Loaded BNO055 calibration from %s", imu_calibration.CALIBRATION_FILE
            )
        except Exception:
            logger.exception("Could not load saved BNO055 calibration")

    def _save_current_calibration(self) -> None:
        if self._calibration_saved_this_run:
            return
        try:
            snapshot = imu_calibration.snapshot_from_sensor(self.sensor)
            imu_calibration.save_snapshot(snapshot)
            self._calibration_saved_this_run = True
            self.calibration_saved_now = True
            logger.info(
                "Saved BNO055 calibration to %s", imu_calibration.CALIBRATION_FILE
            )
        except Exception:
            logger.exception("Could not save BNO055 calibration")

    def save_calibration(self) -> bool:
        try:
            snapshot = imu_calibration.snapshot_from_sensor(self.sensor)
            imu_calibration.save_snapshot(snapshot)
            self._calibration_saved_this_run = True
            logger.info("Manually saved BNO055 calibration")
            return True
        except Exception:
            logger.exception("Could not manually save BNO055 calibration")
            return False

    def load_calibration(self) -> bool:
        try:
            snapshot = imu_calibration.load_snapshot()
            if not snapshot:
                logger.warning("No saved BNO055 calibration to load")
                return False
            imu_calibration.apply_snapshot_to_sensor(self.sensor, snapshot)
            self.calibration_loaded = True
            logger.info("Manually loaded BNO055 calibration")
            return True
        except Exception:
            logger.exception("Could not manually load BNO055 calibration")
            return False

    def clear_calibration(self) -> bool:
        try:
            cleared = imu_calibration.clear_snapshot()
            logger.info("Cleared BNO055 calibration file: %s", cleared)
            return cleared
        except Exception:
            logger.exception("Could not clear BNO055 calibration file")
            return False

    def moving(self):
        """
        Compares most recent reading
        with past readings
        """
        return self.__moving

    def update(self):
        # check for update frequency
        if time.time() - self.last_sample_time < self.imu_sample_frequency:
            return

        self.last_sample_time = time.time()

        # Throw out non-calibrated data
        status = self.sensor.calibration_status
        self.last_io_time = time.time()
        self.calibration_status = tuple(int(v) for v in status)
        if self.calibration_status != self._last_calibration_status:
            logger.info(
                "IMU calibration status sys=%s gyro=%s accel=%s mag=%s",
                *self.calibration_status,
            )
            self._last_calibration_status = self.calibration_status
        self.calibration = imu_calibration.tracking_calibration_level(
            self.calibration_status
        )
        if self.calibration == 0:
            logger.warning("NOIMU CAL %s", self.calibration_status)
            return True
        if (
            self.use_magnetometer
            and self.auto_calibration_store
            and min(self.calibration_status) == 3
        ):
            self._save_current_calibration()
        # adafruit_bno055 uses quaternion convention (w, x, y, z)
        quat = self.sensor.quaternion
        if quat[0] is None:
            logger.warning("IMU: Failed to get sensor values")
            return
        try:
            quat = tuple(float(value) for value in quat)
            quat_norm = math.sqrt(sum(value * value for value in quat))
        except (TypeError, ValueError):
            logger.warning("IMU: rejected unreadable quaternion %s", quat)
            return
        if not math.isfinite(quat_norm) or not 0.8 <= quat_norm <= 1.2:
            now = time.monotonic()
            if now - self._last_invalid_quat_log > 5.0:
                logger.warning(
                    "IMU: rejected non-unit quaternion norm=%.3f quat=%s",
                    quat_norm,
                    quat,
                )
                self._last_invalid_quat_log = now
            return

        # When enabled, read raw sensor data alongside the quaternion so
        # the telemetry sample is coherent (same instant, same I2C burst).
        if self._raw_telemetry:
            try:
                self.gyro = self.sensor.gyro
                self.accel = self.sensor.linear_acceleration
            except (OSError, RuntimeError):
                self.gyro = None
                self.accel = None
        self.last_read_time = time.time()

        _quat_diff = []
        for i in range(4):
            _quat_diff.append(abs(quat[i] - self.quat_history[-1][i]))

        self.__reading_diff = sum(_quat_diff)

        # This seems to be some sort of defect / side effect
        # of the integration system in the BNO055
        # When not moving quat output will vaccilate
        # by exactly this amount... so filter this out
        if self.__reading_diff == 0.0078125:
            self.__reading_diff = 0
            return

        # Sometimes the quat output will 'flip' and change by 2.0+
        # from one reading to another.  This is clearly noise or an
        # artifact, so filter them out
        #
        # NOTE: This is probably due to the double-cover property of quaternions
        # where +q and -q describe the same rotation?
        if self.__reading_diff > 1.5:
            self._flip_count += 1
            if self._flip_count > 10:
                # with the history initialized to 0,0,0,0 the unit
                # can get stuck seeing flips if the IMU starts
                # returning data. This count will reset history
                # to the current state if it exceeds 10
                self.quat_history = [quat] * QUEUE_LEN
                self.__reading_diff = 0
            else:
                self.__reading_diff = 0
                return
        else:
            # no flip
            self._flip_count = 0

        # avg_quat is the latest quaternion measurement, not the average
        self.avg_quat = quat
        # Write over the quat_hisotry queue FIFO:
        if len(self.quat_history) == QUEUE_LEN:
            self.quat_history = self.quat_history[1:]
        self.quat_history.append(quat)

        if self.__moving:
            if self.__reading_diff < self.__moving_threshold[1]:
                self.__moving = False
        else:
            if self.__reading_diff > self.__moving_threshold[0]:
                self.__moving = True

    def __str__(self):
        return (
            f"IMU Information:\n"
            f"Calibration Status: {self.calibration}\n"
            f"Calibration Components: {self.calibration_status}\n"
            f"Fusion Mode: {self.fusion_mode}\n"
            f"Quaternion History: {self.quat_history}\n"
            f"Average Quaternion: {self.avg_quat}\n"
            f"Moving: {self.moving()}\n"
            f"Reading Difference: {self.__reading_diff}\n"
            f"Flip Count: {self._flip_count}\n"
            f"Last Sample Time: {self.last_sample_time}\n"
            f"IMU Sample Frequency: {self.imu_sample_frequency}\n"
            f"Moving Threshold: {self.__moving_threshold}\n"
        )


def _handle_imu_command(imu, command, console_queue):
    command_type = command.get("type") if isinstance(command, dict) else command
    if command_type == "set_raw_capture":
        enabled = bool(command.get("enabled")) if isinstance(command, dict) else False
        if hasattr(imu, "set_raw_capture"):
            imu.set_raw_capture(enabled)
            console_queue.put("IMU: raw gyro on" if enabled else "IMU: raw gyro off")
        else:
            console_queue.put("IMU: raw gyro unsupported")
        return
    if not hasattr(imu, "save_calibration"):
        console_queue.put("IMU: calibration unsupported")
        return
    if command_type == "save_calibration":
        if imu.save_calibration():
            console_queue.put("IMU: calibration saved")
        else:
            console_queue.put("IMU: calibration save failed")
    elif command_type == "load_calibration":
        if imu.load_calibration():
            console_queue.put("IMU: calibration loaded")
        else:
            console_queue.put("IMU: no calibration loaded")
    elif command_type == "clear_calibration":
        if imu.clear_calibration():
            console_queue.put("IMU: calibration cleared")
        else:
            console_queue.put("IMU: no calibration file")
    else:
        logger.warning("Unknown IMU command: %s", command_type)


def _update_imu_safely(imu, imu_sample, consecutive_errors):
    """Run one sensor update without allowing an I2C error to kill the process.

    Returns ``(failed, consecutive_errors, recovered)``. A successful call only
    marks the sample healthy after the driver reports a new successful I2C
    transaction through ``last_io_time``; a throttled iteration changes no
    health state.
    """
    io_before = getattr(imu, "last_io_time", 0.0)
    try:
        imu.update()
    except Exception as error:
        consecutive_errors += 1
        imu_sample.sensor_healthy = False
        imu_sample.consecutive_errors = consecutive_errors
        imu_sample.last_error = f"{type(error).__name__}: {error}"
        imu_sample.moving = False
        logger.exception(
            "IMU sensor update failed (%d/%d)",
            consecutive_errors,
            IMU_REINITIALIZE_AFTER_ERRORS,
        )
        return True, consecutive_errors, False

    io_after = getattr(imu, "last_io_time", 0.0)
    recovered = False
    if io_after > io_before:
        recovered = not imu_sample.sensor_healthy
        consecutive_errors = 0
        imu_sample.sensor_healthy = True
        imu_sample.consecutive_errors = 0
        imu_sample.last_error = None
        imu_sample.last_success_time = io_after
    return False, consecutive_errors, recovered


def imu_monitor(shared_state, console_queue, log_queue, command_queue=None):
    MultiprocLogging.configurer(log_queue)
    logger.debug("Starting IMU")
    imu = None
    using_fake = False
    reinitialize_requested = False
    reinitialize_delay = IMU_REINITIALIZE_INITIAL_DELAY_SECONDS
    next_reinitialize = 0.0
    try:
        imu = Imu()
        if getattr(imu, "calibration_loaded", False):
            console_queue.put("IMU: saved calibration loaded")
    except Exception as e:
        logger.error(f"Error starting phyiscal IMU : {e}")
        logger.error("Falling back to fake IMU")
        console_queue.put("IMU: Error starting physical IMU, using fake IMU")
        console_queue.put("DEGRADED_OPS IMU")
        from PiFinder.imu_fake import Imu as ImuFake

        imu = ImuFake()
        using_fake = True
        reinitialize_requested = True
        next_reinitialize = time.monotonic() + reinitialize_delay

    imu_calibrated = False
    imu_sample = ImuSample(
        # Scalar-first numpy quaternion(w, x, y, z) - init to invalid quaternion
        quat=quaternion.quaternion(0, 0, 0, 0),
        timestamp=0.0,  # set together with quat below, at sample time
        status=0,  # IMU Status: 3=Calibrated
        moving=False,
        calibration_status=(0, 0, 0, 0),
        fusion_mode=getattr(imu, "fusion_mode", "unknown") if imu else "unknown",
        uses_magnetometer=getattr(imu, "use_magnetometer", False) if imu else False,
        sensor_healthy=not using_fake,
        consecutive_errors=0,
        last_error="physical IMU unavailable" if using_fake else None,
        last_success_time=None,
    )

    # update() already throttles the I2C reads to imu_sample_frequency (30 Hz),
    # but the loop body still runs every iteration — publishing the sample via
    # set_imu(), a Manager-proxy pickle. Without pacing this spins thousands/sec
    # (~19% CPU) and the per-publish pickle leaks. Capture the period once; the
    # fake-IMU fallback has no such attr (and self-throttles), hence the default.
    sample_period = getattr(imu, "imu_sample_frequency", 1 / 30)
    consecutive_errors = 0

    while True:
        if command_queue is not None:
            while True:
                try:
                    command = command_queue.get(block=False)
                except queue.Empty:
                    break
                _handle_imu_command(imu, command, console_queue)

        loop_start = time.monotonic()
        if reinitialize_requested and loop_start >= next_reinitialize:
            try:
                replacement = Imu()
            except Exception as error:
                next_delay = min(
                    reinitialize_delay * 2.0,
                    IMU_REINITIALIZE_MAX_DELAY_SECONDS,
                )
                logger.warning(
                    "Could not reinitialize physical IMU; retrying in %.1fs: %s",
                    next_delay,
                    error,
                )
                imu_sample.sensor_healthy = False
                imu_sample.last_error = f"{type(error).__name__}: {error}"
                reinitialize_delay = next_delay
                next_reinitialize = time.monotonic() + reinitialize_delay
            else:
                imu = replacement
                using_fake = False
                reinitialize_requested = False
                reinitialize_delay = IMU_REINITIALIZE_INITIAL_DELAY_SECONDS
                consecutive_errors = 0
                imu_calibrated = False
                sample_period = getattr(imu, "imu_sample_frequency", 1 / 30)
                # Do not call the sensor healthy until its first successful I2C
                # transaction. The freshly constructed Imu throttles its first
                # update, so this normally changes on the following loop.
                imu_sample.sensor_healthy = False
                imu_sample.consecutive_errors = 0
                imu_sample.last_error = "awaiting first sensor read after recovery"
                console_queue.put("IMU: physical sensor reinitialized")
                if getattr(imu, "calibration_loaded", False):
                    console_queue.put("IMU: saved calibration loaded")
                logger.info("Physical IMU reinitialized")

        update_failed, consecutive_errors, recovered = _update_imu_safely(
            imu, imu_sample, consecutive_errors
        )
        if recovered and not using_fake:
            console_queue.put("IMU: sensor healthy")
        if update_failed and consecutive_errors >= IMU_REINITIALIZE_AFTER_ERRORS:
            from PiFinder.imu_fake import Imu as ImuFake

            imu = ImuFake()
            using_fake = True
            reinitialize_requested = True
            next_reinitialize = time.monotonic() + reinitialize_delay
            imu_sample.status = 0
            imu_sample.calibration_status = (0, 0, 0, 0)
            imu_sample.fusion_mode = "unknown"
            imu_sample.uses_magnetometer = False
            imu_calibrated = False
            console_queue.put("IMU: sensor read failure, recovering")
            console_queue.put("DEGRADED_OPS IMU")

        imu_sample.status = imu.calibration
        imu_sample.calibration_status = getattr(imu, "calibration_status", None)
        imu_sample.fusion_mode = getattr(imu, "fusion_mode", "unknown")
        imu_sample.uses_magnetometer = getattr(imu, "use_magnetometer", False)
        if getattr(imu, "calibration_saved_now", False):
            console_queue.put("IMU: calibration saved")
            imu.calibration_saved_now = False

        # Raw data + read epoch are captured by imu.update() in the same
        # I2C burst as the quaternion; copy them onto the published sample.
        # The fresh timestamp per read keeps the telemetry recorder's
        # dedup-by-sample-epoch working while stationary.
        imu_sample.gyro = imu.gyro
        imu_sample.accel = imu.accel
        if imu.last_read_time:
            imu_sample.timestamp = imu.last_read_time
            # Keep the published orientation fresh even while the movement
            # detector is below its deadband. SkySafari's no-solve fallback
            # uses the absolute IMU orientation directly, while the integrator
            # still applies its own angular threshold before advancing solved
            # pointing estimates.
            imu_sample.quat = quaternion.from_float_array(imu.avg_quat)

        if imu.moving():
            if not imu_sample.moving:
                logger.debug("IMU: move start")
                imu_sample.moving = True
        else:
            if imu_sample.moving:
                # If we were moving and we now stopped
                logger.debug("IMU: move end")
                imu_sample.moving = False

        if not imu_calibrated:
            if imu_sample.uses_magnetometer:
                full_calibration = (
                    imu_sample.calibration_status is not None
                    and min(imu_sample.calibration_status) == 3
                )
            else:
                full_calibration = imu_sample.status == 3
            if full_calibration:
                imu_calibrated = True
                mode_name = "NDOF" if imu_sample.uses_magnetometer else "IMUPLUS"
                console_queue.put(f"IMU: {mode_name} Calibrated!")

        if shared_state is not None:
            shared_state.set_imu(imu_sample)

        # Pace the loop to the IMU sample rate: sleep only the remainder of the
        # sample period (period minus the work already done this iteration), so
        # the publish cadence tracks the sample rate instead of drifting to
        # period + work. The guard keeps the fake-IMU fallback (whose update()
        # already sleeps 0.1s) from sleeping a second time.
        sleep_remaining = sample_period - (time.monotonic() - loop_start)
        if sleep_remaining > 0:
            time.sleep(sleep_remaining)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    logger.info("Trying to read state from IMU")
    imu = None
    try:
        imu = Imu()
        for i in range(10):
            imu.update()
            print(imu)
            time.sleep(0.5)
    except Exception as e:
        logger.exception("Error starting phyiscal IMU", e)
