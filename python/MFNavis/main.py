#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the main entry point for PiFinder it:
* Initializes the display
* Spawns keyboard process
* Sets up time/location via GPS
* Spawns camers/solver process
* then runs the UI loop

"""

from __future__ import annotations

import gettext

import os

# skyfield performance fix, see: https://rhodesmill.org/skyfield/accuracy-efficiency.html
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
import time
import queue
import datetime
import json
import uuid
import logging
import argparse
import pickle
import threading
from pathlib import Path
from PIL import Image, ImageOps
from multiprocessing import Process, Queue
from multiprocessing.managers import BaseManager

import PiFinder.i18n  # noqa: F401
from PiFinder import solver
from PiFinder import config
from PiFinder import pos_server
from PiFinder import utils
from PiFinder import server
from PiFinder import timez
from PiFinder import keyboard_interface
from PiFinder import gps_time_sync

from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.catalogs import CatalogBuilder, CatalogFilter, Catalogs
from PiFinder.calc_utils import sf_utils
from PiFinder.state_utils import sleep_for_framerate
from PiFinder.livecam_config import processing_enabled

from PiFinder.ui.console import UIConsole
from PiFinder.ui.menu_manager import MenuManager

from PiFinder.state import SharedStateObj, UIState

from PiFinder.image_util import subtract_background

from PiFinder.displays import DisplayBase, get_display

import PiFinder.manager_patch as patch

from typing import Any, TYPE_CHECKING

# Mypy i8n fix
if TYPE_CHECKING:

    def _(a) -> Any:
        return a


logger = logging.getLogger("main")

hardware_platform = "Pi"
display_hardware = "SSD1351"
display_device: DisplayBase = DisplayBase()
keypad_pwm = None
USER_LOCATION_SOURCES = {"WEB", "MANUAL"}
USER_LOCATION_PREFIXES = ("CONFIG:",)
SLEW_RATE_POPUP_LABELS = (
    "Off",
    "1/2",
    "1",
    "2",
    "4",
    "8",
    "20",
    "48",
    "1/2 MAX",
    "MAX",
)
# Throttle for the LiveCam wake check; update() runs every main-loop pass.
LIVECAM_WAKE_POLL_SECONDS = 1.0


def _is_user_location_source(source: str | None) -> bool:
    source = source or ""
    return source in USER_LOCATION_SOURCES or source.startswith(USER_LOCATION_PREFIXES)


def should_apply_location_fix(current_location: Any, gps_content: dict) -> bool:
    """Return True when a GPS queue fix should replace the current location."""
    new_source = str(gps_content.get("source") or "")
    if _is_user_location_source(new_source):
        return True

    current_source = str(getattr(current_location, "source", "") or "")
    if _is_user_location_source(current_source) or current_source == "replay":
        return False

    current_error = float(getattr(current_location, "error_in_m", 0) or 0)
    new_error = float(gps_content.get("error_in_m", 0) or 0)
    return current_error == 0 or new_error < current_error


def init_keypad_pwm():
    # TODO: Keypad pwm class that can be faked maybe?
    global keypad_pwm
    global hardware_platform
    if hardware_platform == "Pi":
        from PiFinder.board_config import get_pwm_chip

        # The keypad PWM lives on a different sysfs chip on the Pi 5 (RP1)
        # than on the Pi 1-4 SoC; pick it per board so brightness works on
        # both.  Requires rpi-hardware-pwm >= 0.2.1 for the `chip` argument.
        keypad_pwm = HardwarePWM(pwm_channel=1, hz=120, chip=get_pwm_chip())
        keypad_pwm.start(0)


def set_keypad_brightness(percentage: float):
    """
    keypad brightness between 0-100, although effective range seems 0-12
    """
    global keypad_pwm
    if percentage < 0 or percentage > 100:
        logger.error("Invalid percentage for keypad brightness")
        percentage = max(0, min(100, percentage))
    if keypad_pwm:
        keypad_pwm.change_duty_cycle(percentage)


def set_brightness(level, cfg):
    """
    Sets oled/keypad brightness
    0-255
    """
    global display_device
    display_device.set_brightness(level)

    if keypad_pwm:
        # determine offset for keypad
        keypad_offsets = {
            "+3": 2,
            "+2": 1.6,
            "+1": 1.3,
            "0": 1,
            "-1": 0.75,
            "-2": 0.5,
            "-3": 0.25,
            "-4": 0.13,
            "Off": 0,
        }
        keypad_brightness = cfg.get_option("keypad_brightness")
        set_keypad_brightness(level * 0.05 * keypad_offsets[keypad_brightness])


def setup_dirs():
    utils.create_path(Path(utils.data_dir))
    utils.create_path(Path(utils.data_dir, "captures"))
    utils.create_path(Path(utils.data_dir, "obslists"))
    utils.create_path(Path(utils.data_dir, "screenshots"))
    utils.create_path(Path(utils.data_dir, "solver_debug_dumps"))
    utils.create_path(Path(utils.data_dir, "logs"))
    utils.create_path(Path(utils.data_dir, "telemetry"))
    os.chmod(Path(utils.data_dir), 0o777)


patch.apply()


class StateManager(BaseManager):
    pass


StateManager.register("SharedState", SharedStateObj)
StateManager.register("UIState", UIState)
StateManager.register("NewImage", Image.new)


class PowerManager:
    def __init__(self, cfg, shared_state, display_device):
        self.cfg = cfg
        self.shared_state = shared_state
        self.display_device = display_device
        self.last_activity = time.time()
        self._livecam_checked_at = 0.0
        self._livecam_wake_cached = False
        self._measurement_checked_at = 0.0
        self._measurement_wake_cached = False

    def register_activity(self):
        """
        Resets idle counter, wakes up systems if needed
        returns True if activity caused wakeup
        """
        self.last_activity = time.time()

        # power states
        # 0 = Sleep
        # 1 = Wake
        if self.shared_state.power_state() < 1:
            # wake up
            self.wake_up()
            return True

        return False

    def wake_up(self):
        """
        Do all the wakeup things
        """
        self.last_activity = time.time()
        self.shared_state.set_power_state(1)
        self.wake_screen()

    def go_to_sleep(self):
        """
        Do all the sleep things
        """
        self.shared_state.set_power_state(0)
        self.sleep_screen()

    def livecam_holds_wake(self) -> bool:
        """
        True while LiveCam processing is on.

        The camera loop drops to one capture per 30 s in sleep mode, so a
        sleeping PiFinder makes LiveCam unusable: enabling processing shows
        nothing for up to half a minute, and the preview then updates that
        slowly. Web activity does not count as user activity, so a session
        driven purely from the web UI would always sleep.
        """
        if not hasattr(self.shared_state, "livecam_settings"):
            return False
        # update() runs every main-loop pass and shared_state is a manager
        # proxy, so this read is throttled rather than paid per frame.
        now = time.time()
        if now - self._livecam_checked_at < LIVECAM_WAKE_POLL_SECONDS:
            return self._livecam_wake_cached
        self._livecam_checked_at = now
        try:
            self._livecam_wake_cached = processing_enabled(
                self.shared_state.livecam_settings()
            )
        except Exception:
            # Never let a power-management read take down the main loop.
            self._livecam_wake_cached = False
        return self._livecam_wake_cached

    def measurement_holds_wake(self) -> bool:
        """Keep calibration progress visible and camera frames flowing."""
        now = time.time()
        if now - self._measurement_checked_at < LIVECAM_WAKE_POLL_SECONDS:
            return self._measurement_wake_cached
        self._measurement_checked_at = now
        self._measurement_wake_cached = False
        for name in ("lens_measurement_status", "distortion_calibration_status"):
            try:
                status = getattr(self.shared_state, name, lambda: {})() or {}
                if status.get("state") in {
                    "requested",
                    "waiting_stars",
                    "measuring",
                    "collecting",
                }:
                    self._measurement_wake_cached = True
            except Exception:
                pass
        return self._measurement_wake_cached

    def update(self):
        """
        Check IMU for activity
        go to sleep if needed
        if asleep, Introduce wait state
        """
        if self.livecam_holds_wake() or self.measurement_holds_wake():
            # Also wakes a sleeping unit, so turning processing on from the
            # web UI starts producing frames immediately.
            self.register_activity()
            return

        if self.get_sleep_timeout() <= 0:
            # Disabled
            self.register_activity()
            return

        if self.shared_state.power_state() > 0:
            # We are awake, should we sleep?
            if time.time() - self.last_activity > self.get_sleep_timeout():
                self.go_to_sleep()

        else:  # We are asleepd, should we wake up?
            _imu = self.shared_state.imu()
            if _imu:
                if _imu.is_usable() and _imu.moving:
                    self.wake_up()

    def get_sleep_timeout(self):
        """
        returns the sleep timeout amount
        """
        sleep_timeout_option = self.cfg.get_option("sleep_timeout")
        sleep_timeout = {
            "Off": -1,
            "10s": 10,
            "20s": 20,
            "30s": 30,
            "1m": 60,
            "2m": 120,
        }[sleep_timeout_option]
        return sleep_timeout

    def get_screen_off_timeout(self):
        """
        returns the screen off timeout amount
        """
        screen_off_option = self.cfg.get_option("screen_off_timeout")
        screen_off = {
            "Off": -1,
            "30s": 30,
            "1m": 60,
            "10m": 600,
            "30m": 1800,
        }[screen_off_option]
        return screen_off

    def wake_screen(self) -> None:
        screen_brightness = self.cfg.get_option("display_brightness")
        set_brightness(screen_brightness, self.cfg)
        self.display_device.device.show()

    def sleep_screen(self):
        screen_brightness = self.cfg.get_option("display_brightness")
        set_brightness(int(screen_brightness / 4), self.cfg)
        self.display_device.device.show()


def start_profiling():
    """Start profiling for performance analysis"""
    import cProfile

    profiler = cProfile.Profile()
    profiler.enable()
    startup_profile_start = time.time()
    return profiler, startup_profile_start


def stop_profiling(profiler, startup_profile_start):
    """Stop profiling and save results"""
    import pstats

    profiler.disable()
    startup_profile_time = time.time() - startup_profile_start
    profile_path = utils.data_dir / "startup_profile.prof"
    profiler.dump_stats(str(profile_path))

    logger = logging.getLogger("Main.Profiling")
    logger.info(f"=== Startup Profiling Complete ({startup_profile_time:.2f}s) ===")
    logger.info(f"Profile saved to: {profile_path}")
    logger.info("To analyze, run:")
    logger.info(
        f"  python -c \"import pstats; p = pstats.Stats('{profile_path}'); p.sort_stats('cumulative').print_stats(30)\""
    )

    summary_path = utils.data_dir / "startup_profile.txt"
    with open(summary_path, "w") as f:
        ps = pstats.Stats(profiler, stream=f)
        f.write(f"=== STARTUP PROFILING ({startup_profile_time:.2f}s) ===\n\n")
        f.write("Top 30 functions by cumulative time:\n")
        f.write("=" * 80 + "\n")
        ps.sort_stats("cumulative").print_stats(30)
        f.write("\n" + "=" * 80 + "\n")
        f.write("Top 30 functions by internal time:\n")
        f.write("=" * 80 + "\n")
        ps.sort_stats("time").print_stats(30)
    logger.info(f"Text summary saved to: {summary_path}")


def _build_pygame_keymaps():
    """
    Build the pygame key -> KeyboardInterface keycode maps used when a pygame
    display is active. Returns (key_map, ctrl_key_map).

    Ctrl+key produces the ALT_* keycodes, which emulate the hardware keypad's
    SQUARE-modifier chord (see keyboard_local.py). Pulled out of main() purely
    to keep the event loop readable; see docs/adr/0004 for why pygame keys are
    captured in the main process at all rather than in a keyboard_* subprocess.
    """
    import pygame
    from PiFinder.keyboard_interface import KeyboardInterface

    # +/= and - for PLUS/MINUS, Enter/Space/Z for SQUARE, M for LNG_SQUARE
    key_map = {
        pygame.K_LEFT: KeyboardInterface.LEFT,
        pygame.K_UP: KeyboardInterface.UP,
        pygame.K_DOWN: KeyboardInterface.DOWN,
        pygame.K_RIGHT: KeyboardInterface.RIGHT,
        pygame.K_EQUALS: KeyboardInterface.PLUS,
        pygame.K_PLUS: KeyboardInterface.PLUS,
        pygame.K_KP_PLUS: KeyboardInterface.PLUS,
        pygame.K_MINUS: KeyboardInterface.MINUS,
        pygame.K_KP_MINUS: KeyboardInterface.MINUS,
        pygame.K_RETURN: KeyboardInterface.SQUARE,
        pygame.K_KP_ENTER: KeyboardInterface.SQUARE,
        pygame.K_SPACE: KeyboardInterface.SQUARE,
        pygame.K_z: KeyboardInterface.SQUARE,
        pygame.K_m: KeyboardInterface.LNG_SQUARE,
        pygame.K_0: 0,
        pygame.K_1: 1,
        pygame.K_2: 2,
        pygame.K_3: 3,
        pygame.K_4: 4,
        pygame.K_5: 5,
        pygame.K_6: 6,
        pygame.K_7: 7,
        pygame.K_8: 8,
        pygame.K_9: 9,
    }

    ctrl_key_map = {
        pygame.K_EQUALS: KeyboardInterface.ALT_PLUS,
        pygame.K_PLUS: KeyboardInterface.ALT_PLUS,
        pygame.K_KP_PLUS: KeyboardInterface.ALT_PLUS,
        pygame.K_MINUS: KeyboardInterface.ALT_MINUS,
        pygame.K_KP_MINUS: KeyboardInterface.ALT_MINUS,
        pygame.K_LEFT: KeyboardInterface.ALT_LEFT,
        pygame.K_UP: KeyboardInterface.ALT_UP,
        pygame.K_DOWN: KeyboardInterface.ALT_DOWN,
        pygame.K_RIGHT: KeyboardInterface.ALT_RIGHT,
        pygame.K_0: KeyboardInterface.ALT_0,
    }

    return key_map, ctrl_key_map


def start_bluetooth_keyboard_autoreconnect() -> None:
    """
    Start non-blocking Bluetooth keyboard reconnection for paired devices.
    """
    if hardware_platform != "Pi":
        return

    try:
        from PiFinder import sys_utils

        reconnect_thread = threading.Thread(
            target=sys_utils.auto_reconnect_bluetooth_keyboards,
            kwargs={
                "attempts": 12,
                "delay_seconds": 5,
                "connect_timeout": 10,
            },
            name="BluetoothKeyboardReconnect",
            daemon=True,
        )
        reconnect_thread.start()
        logger.info("Bluetooth keyboard auto-reconnect started")
    except Exception as e:
        logger.warning("Could not start Bluetooth keyboard auto-reconnect: %s", e)


def main(
    log_helper: MultiprocLogging,
    script_name=None,
    show_fps=False,
    verbose=False,
    profile_startup=False,
) -> None:
    """
    Get this show on the road!
    """
    global display_device, display_hardware

    # init queues
    console_queue: Queue = Queue()
    keyboard_queue: Queue = Queue()
    gps_queue: Queue = Queue()
    gps_command_queue: Queue = Queue()
    imu_command_queue: Queue = Queue()
    camera_command_queue: Queue = Queue()
    solver_queue: Queue = Queue()
    alignment_command_queue: Queue = Queue()
    alignment_response_queue: Queue = Queue()
    ui_queue: Queue = Queue()
    mountcontrol_queue: Queue = Queue()
    goto_guide_queue: Queue = Queue()

    # init queues for logging
    keyboard_logqueue: Queue = log_helper.get_queue()
    gps_logqueue: Queue = log_helper.get_queue()
    camera_logqueue: Queue = log_helper.get_queue()
    solver_logqueue: Queue = log_helper.get_queue()
    server_logqueue: Queue = log_helper.get_queue()
    posserver_logqueue: Queue = log_helper.get_queue()
    integrator_logqueque: Queue = log_helper.get_queue()
    imu_logqueue: Queue = log_helper.get_queue()
    mountcontrol_logqueue: Queue = log_helper.get_queue()
    goto_guide_logqueue: Queue = log_helper.get_queue()

    # Refuse to start if another instance is already running. A second copy
    # would otherwise boot and let its subsystems (web/pos-server ports, cedar
    # shmem, hardware devices) silently collide with the live one.
    if not utils.acquire_single_instance_lock():
        return

    # Start log consolidation process first.
    log_helper.start()

    cfg = config.Config()
    # Optional SPI clock override (MHz). Lower values reduce display-bus EMI
    # into the GPS band; 0 keeps the per-driver default.
    display_spi_mhz = int(cfg.get_option("display_spi_speed_mhz", 0) or 0)
    display_device = get_display(
        display_hardware, spi_speed_hz=display_spi_mhz * 1_000_000
    )
    init_keypad_pwm()
    setup_dirs()

    from PiFinder.operation_errors import MountErrorGate

    mount_error_gate = MountErrorGate()

    def show_mount_process_error(error):
        if mount_error_gate.ready_at is not None:
            menu_manager.show_error(error)

    # Instantiate base keyboard class for keycode
    keyboard_base = keyboard_interface.KeyboardInterface()

    os_detail, platform, arch = utils.get_os_info()
    logger.info("MFNavis running on %s, %s, %s", os_detail, platform, arch)

    # init UI Modes
    integrator_command_queue: Queue = Queue()

    command_queues = {
        "camera": camera_command_queue,
        "console": console_queue,
        "ui_queue": ui_queue,
        "align_command": alignment_command_queue,
        "align_response": alignment_response_queue,
        "gps": gps_queue,
        "imu": imu_command_queue,
        "integrator": integrator_command_queue,
        "mountcontrol": mountcontrol_queue,
        "goto_guide": goto_guide_queue,
    }
    if gps_monitor.__name__ == "PiFinder.gps_ubx":
        command_queues["gps_command"] = gps_command_queue
    gps_time_monitor = gps_time_sync.GpsTimeSyncMonitor.from_config(cfg)
    gps_time_monitor.write_startup_status()

    # Joystick/gamepad input: libinput (keyboard_pi) ignores joystick-class
    # devices, so a paired controller needs its own evdev reader. Buttons the
    # user mapped in Settings > Advanced > Joystick become keypad keycodes or
    # direct mount commands (see PiFinder.joystick_input).
    try:
        from PiFinder import joystick_input

        joystick_input.manager().start(keyboard_queue, mountcontrol_queue, cfg)
    except Exception:
        logger.exception("Joystick input unavailable")

    # Physical-keyboard events arrive from keyboard_pi with their raw Linux
    # key identity. The main-process manager provides configurable mount
    # shortcuts plus the Settings > Advanced > Keyboard capture/test UI.
    from PiFinder import keyboard_mapping

    keyboard_mapping_manager = keyboard_mapping.manager()
    keyboard_mapping_manager.start(keyboard_queue, mountcontrol_queue, cfg)

    # init screen
    screen_brightness = cfg.get_option("display_brightness")
    set_brightness(screen_brightness, cfg)
    if cfg.get_option("screen_direction") == "as_bloom":
        display_device.device.rotate = 3

    # Set user interface language
    lang = cfg.get_option("language", "en")
    langXX = gettext.translation(
        "messages", "locale", languages=[lang], fallback=(lang == "en")
    )
    langXX.install()

    with StateManager() as manager:
        shared_state = manager.SharedState()  # type: ignore[attr-defined]
        location = shared_state.location()
        ui_state = manager.UIState()  # type: ignore[attr-defined]
        ui_state.set_show_fps(show_fps)
        ui_state.set_hint_timeout(cfg.get_option("hint_timeout"))
        shared_state.set_ui_state(ui_state)
        shared_state.set_arch(arch)  # Normal
        logger.debug("Ui state in main is" + str(shared_state.ui_state()))
        console = UIConsole(
            display_device, None, shared_state, command_queues, cfg, Catalogs([])
        )
        console.write("Starting....")
        console.update()
        logger.info("Starting ....")

        # spawn gps service....
        console.write("   GPS")
        console.update()
        logger.info("   GPS")
        gps_process = Process(
            name="GPS",
            target=gps_monitor.gps_monitor,
            kwargs=(
                {"command_queue": gps_command_queue}
                if gps_monitor.__name__ == "PiFinder.gps_ubx"
                else {}
            ),
            args=(
                gps_queue,
                console_queue,
                gps_logqueue,
            ),
        )
        gps_process.start()
        console.set_shared_state(shared_state)

        # spawn keyboard service....
        console.write("   Keyboard")
        logger.info("   Keyboard")
        console.update()
        keyboard_process = Process(
            name="Keyboard",
            target=keyboard.run_keyboard,
            args=(keyboard_queue, shared_state, keyboard_logqueue),
        )
        keyboard_process.start()
        if script_name:
            script_path = str(utils.pifinder_dir / "scripts" / f"{script_name}.pfs")
            p = Process(
                name="Script",
                target=keyboard_interface.KeyboardInterface.run_script,
                args=(script_path, keyboard_queue, keyboard_logqueue),
            )
            p.start()

        # Web server
        console.write("   Webserver")
        logger.info("   Webserver")
        console.update()

        server_process = Process(
            name="Webserver",
            target=server.run_server,
            args=(
                keyboard_queue,
                ui_queue,
                gps_queue,
                shared_state,
                server_logqueue,
                verbose,
                mountcontrol_queue,
                goto_guide_queue,
                camera_command_queue,  # For web camera exposure/gain control
            ),
        )
        server_process.start()

        console.write("   Camera")
        logger.info("   Camera")
        console.update()
        camera_image = manager.NewImage("RGB", (512, 512))  # type: ignore[attr-defined]
        image_process = Process(
            name="Camera",
            target=camera.get_images,
            args=(
                shared_state,
                camera_image,
                camera_command_queue,
                console_queue,
                camera_logqueue,
            ),
        )
        image_process.start()
        time.sleep(1)

        # IMU
        console.write("   IMU")
        logger.info("   IMU")
        console.update()
        imu_process = Process(
            name="IMU",
            target=imu.imu_monitor,
            args=(shared_state, console_queue, imu_logqueue, imu_command_queue),
        )
        imu_process.start()

        # Solver
        console.write("   Solver")
        logger.info("   Solver")
        console.update()
        solver_process = Process(
            name="Solver",
            target=solver.solver,
            args=(
                shared_state,
                solver_queue,
                camera_image,
                console_queue,
                solver_logqueue,
                alignment_command_queue,
                alignment_response_queue,
                camera_command_queue,  # For raw SQM capture
                verbose,
            ),
        )
        solver_process.start()

        # Integrator
        console.write("   Integrator")
        logger.info("   Integrator")
        console.update()
        integrator_process = Process(
            name="Integrator",
            target=integrator.integrator,
            args=(
                shared_state,
                solver_queue,
                console_queue,
                integrator_logqueque,
                verbose,
            ),
            kwargs={
                "command_queue": integrator_command_queue,
                "camera_command_queue": camera_command_queue,
            },
        )
        integrator_process.start()

        # Server
        console.write("  POS Server")
        logger.info("  POS Server")
        console.update()
        posserver_process = Process(
            name="SkySafariServer",
            target=pos_server.run_server,
            args=(
                shared_state,
                ui_queue,
                posserver_logqueue,
                mountcontrol_queue,
                goto_guide_queue,
                alignment_command_queue,
                alignment_response_queue,
                console_queue,
            ),
        )
        posserver_process.start()

        mountcontrol_enabled = cfg.get_option("mount_control", False)

        def start_mountcontrol_process():
            if not mountcontrol_enabled:
                return None
            console.write("   INDI Mount")
            logger.info("   INDI Mount")
            console.update()
            try:
                from PiFinder import mountcontrol_indi

                process = Process(
                    name="MountControl",
                    target=mountcontrol_indi.run,
                    args=(
                        mountcontrol_queue,
                        console_queue,
                        shared_state,
                        mountcontrol_logqueue,
                    ),
                    kwargs={
                        "imu_command_queue": imu_command_queue,
                        "indi_host": cfg.get_option(
                            "mount_control_indi_host", "localhost"
                        ),
                        "indi_port": int(
                            cfg.get_option("mount_control_indi_port", 7624)
                        ),
                    },
                )
                process.start()
                return process
            except Exception:
                logger.exception("Could not start INDI mount-control process")
                console.write("INDI mount failed")
                return None

        def start_goto_guide_process():
            if not mountcontrol_enabled:
                return None
            console.write("   INDI GoTo/Guide")
            logger.info("   INDI GoTo/Guide")
            console.update()
            try:
                from PiFinder import indi_goto_guide_service

                process = Process(
                    name="IndiGotoGuide",
                    target=indi_goto_guide_service.run,
                    args=(
                        goto_guide_queue,
                        mountcontrol_queue,
                        shared_state,
                        goto_guide_logqueue,
                        console_queue,
                    ),
                )
                process.start()
                return process
            except Exception:
                logger.exception("Could not start INDI GoTo/Guide service")
                console.write("INDI GoTo/Guide failed")
                return None

        mountcontrol_process = start_mountcontrol_process()
        goto_guide_process = start_goto_guide_process()
        next_mountcontrol_health_check = time.monotonic() + 5.0
        next_goto_guide_health_check = time.monotonic() + 5.0

        start_bluetooth_keyboard_autoreconnect()

        # Initialize Catalogs
        console.write("   Catalogs")
        logger.info("   Catalogs")
        console.update()

        # Start profiling (uncomment to enable performance analysis)
        # profiler, startup_profile_start = start_profiling()

        # Initialize Catalogs (pass ui_queue for background loading completion signal)
        catalogs: Catalogs = CatalogBuilder().build(shared_state, ui_queue)

        # Establish the common catalog filter object
        _new_filter = CatalogFilter(shared_state=shared_state)
        _new_filter.load_from_config(cfg)
        catalogs.set_catalog_filter(_new_filter)
        console.write("   Menus")
        console.update()

        # Initialize menu manager
        menu_manager = MenuManager(
            display_device,
            camera_image,
            shared_state,
            command_queues,
            cfg,
            catalogs,
        )

        # Initialize power manager
        power_manager = PowerManager(cfg, shared_state, display_device)

        # Start main event loop
        console.write("   Event Loop")
        logger.info("   Event Loop")
        console.update()

        # Stop profiling (uncomment to analyze startup performance)
        # stop_profiling(profiler, startup_profile_start)

        # Pygame can only read keyboard events from the process that owns the
        # display window, and pynput/PyHotKey (keyboard_local) can't read the
        # keyboard under Wayland. So when a pygame display is active we capture
        # keys here in the main loop; the spawned keyboard process is the no-op
        # keyboard_none. See docs/adr/0004-pygame-keyboard-in-main-loop.md.
        pygame_events_enabled = display_hardware.startswith("pg_")
        if pygame_events_enabled:
            import pygame

            logger.info("Pygame event polling enabled for keyboard input")
            pygame_key_map, pygame_ctrl_key_map = _build_pygame_keymaps()

        log_time = True
        # Start of main except handler / loop
        try:
            while True:
                # Poll pygame keyboard events
                if pygame_events_enabled:
                    for event in pygame.event.get():
                        if event.type == pygame.KEYDOWN:
                            ctrl_held = event.mod & pygame.KMOD_CTRL
                            if ctrl_held and event.key in pygame_ctrl_key_map:
                                keyboard_queue.put(pygame_ctrl_key_map[event.key])
                            elif event.key in pygame_key_map:
                                mapped_key = pygame_key_map[event.key]
                                if isinstance(mapped_key, int) and 1 <= mapped_key <= 9:
                                    keyboard_queue.put(
                                        keyboard_base.number_press_key(mapped_key)
                                    )
                                else:
                                    keyboard_queue.put(mapped_key)
                        elif event.type == pygame.KEYUP:
                            mapped_key = pygame_key_map.get(event.key)
                            if isinstance(mapped_key, int) and 1 <= mapped_key <= 9:
                                keyboard_queue.put(
                                    keyboard_base.number_release_key(mapped_key)
                                )
                        elif event.type == pygame.QUIT:
                            logger.info("Pygame window closed, exiting...")
                            raise KeyboardInterrupt

                # Console
                try:
                    console_msg = console_queue.get(block=False)
                    if isinstance(console_msg, dict) and console_msg.get("type") in {
                        "operation_error",
                        "mount_ready",
                    }:
                        if console_msg.get("type") == "operation_error":
                            console.write(
                                f"{console_msg['source']}: {console_msg['message']}"
                            )
                        if mount_error_gate.observe(console_msg):
                            menu_manager.show_error(console_msg)
                    elif (
                        isinstance(console_msg, tuple)
                        and len(console_msg) == 2
                        and console_msg[0] == "slew_rate_popup"
                    ):
                        rate = max(0, min(9, int(console_msg[1])))
                        menu_manager.message(
                            _("Speed: %(rate)s")
                            % {"rate": SLEW_RATE_POPUP_LABELS[rate]},
                            timeout=0.5,
                        )
                    elif console_msg.startswith("DEGRADED_OPS"):
                        menu_manager.message(_("Degraded\nCheck Status"), 5)
                        time.sleep(5)
                    else:
                        console.write(console_msg)
                except queue.Empty:
                    # Frame-rate-limit the main loop; sleep_for_framerate also
                    # handles power-save by sleeping longer when asleep.
                    sleep_for_framerate(shared_state)

                gps_time_monitor.poll()

                # GPS
                try:
                    while True:  # Consume from gps_queue until empty
                        gps_msg, gps_content = gps_queue.get(block=False)
                        if gps_msg == "fix":
                            location = shared_state.location()

                            if should_apply_location_fix(location, gps_content):
                                logger.debug(
                                    f"Updating GPS location: new content: {gps_content}, old content: {location}"
                                )
                                location.lat = gps_content["lat"]
                                location.lon = gps_content["lon"]
                                location.altitude = gps_content["altitude"]
                                location.source = gps_content["source"]
                                if "error_in_m" in gps_content:
                                    location.error_in_m = gps_content["error_in_m"]
                                if "lock" in gps_content:
                                    location.lock = gps_content["lock"]
                                if "lock_type" in gps_content:
                                    location.lock_type = gps_content["lock_type"]

                                # Update last_gps_lock timestamp when lock is set
                                if "lock" in gps_content and gps_content["lock"]:
                                    dt = shared_state.datetime()
                                    if dt is None:
                                        location.last_gps_lock = "--"
                                    else:
                                        location.last_gps_lock = dt.time().isoformat()[
                                            :8
                                        ]
                                    console.write(
                                        f"GPS: Location {location.lat} {location.lon} {location.altitude} {location.error_in_m}"
                                    )
                                    shared_state.set_location(location)
                                    sf_utils.set_location(
                                        location.lat,
                                        location.lon,
                                        location.altitude,
                                    )
                        if gps_msg in ("time", "time_force"):
                            if isinstance(gps_content, datetime.datetime):
                                gps_dt = gps_content
                            else:
                                gps_dt = gps_content["time"]
                            gps_time_monitor.observe_time(
                                gps_content, shared_state.datetime()
                            )
                            shared_state.set_datetime(
                                gps_dt, force=(gps_msg == "time_force")
                            )
                            if gps_msg == "time_force" and mountcontrol_enabled:
                                # A user-set manual time takes priority over
                                # the clock-trust gate: push it to the mount
                                # right away and drop the (now stale-framed)
                                # tracking target.
                                logger.info(
                                    "Manual time set; re-syncing mount "
                                    "site/time and clearing tracking target"
                                )
                                mountcontrol_queue.put({"type": "sync_location_time"})
                                goto_guide_queue.put({"type": "clear_tracking_target"})
                            if log_time:
                                logger.info("GPS Time (logged only once): %s", gps_dt)
                                log_time = False
                        if gps_msg == "time_sample":
                            gps_time_monitor.observe_time(
                                gps_content, shared_state.datetime()
                            )
                        if gps_msg == "reset":
                            location.reset()
                            shared_state.set_location(location)
                        if gps_msg == "reset_datetime":
                            shared_state.reset_datetime()
                            gps_time_monitor.note_reset()
                        if gps_msg == "satellites":
                            # logger.debug("Main: GPS nr sats seen: %s", gps_content)
                            shared_state.set_sats(gps_content)
                        if gps_msg == "version_status":
                            menu_manager.message(gps_content, 5)
                        if gps_msg == "comms":
                            # Stamp receipt in the UI process; GPS time changes
                            # must not make the elapsed time jump or go negative.
                            shared_state.set_gps_comms((gps_content, time.monotonic()))
                except queue.Empty:
                    pass

                # ui queue
                try:
                    ui_command = ui_queue.get(block=False)
                except queue.Empty:
                    ui_command = None
                if ui_command == "set_brightness":
                    set_brightness(screen_brightness, cfg)
                elif ui_command == "push_object":
                    menu_manager.jump_to_label("recent")
                elif ui_command == "reload_config":
                    cfg.load_config()
                    gps_time_monitor.update_config(cfg)
                elif ui_command == "clear_goto_method_override":
                    # This is intentionally session-only; the Web INDI form
                    # already saved its persistent GoTo Type separately.
                    cfg.set_option("session.indi_goto_method", None)
                elif ui_command == "catalogs_fully_loaded":
                    logger.info(
                        "All catalogs loaded - WDS and extended catalogs available"
                    )
                    # Mark the filter dirty so downstream consumers that cache
                    # off dirty_time (e.g. the chart's nearby-DSO spatial index)
                    # rebuild to include the newly available objects.
                    if catalogs.catalog_filter is not None:
                        catalogs.catalog_filter.mark_dirty()
                    menu_manager.message(_("Catalogs\nFully Loaded"), 2)
                elif ui_command == "test_mode":
                    dt = timez.utc(2025, 6, 28, 11, 0, 0)
                    shared_state.set_datetime(dt)
                    location.lat = 41.13
                    location.lon = -120.97
                    location.altitude = 1315
                    location.source = "test"
                    location.error_in_m = 5
                    location.lock = True
                    location.lock_type = 3
                    location.last_gps_lock = timez.local_now().time().isoformat()[:8]
                    console.write(
                        f"GPS: Location {location.lat} {location.lon} {location.altitude}"
                    )
                    shared_state.set_location(location)
                    sf_utils.set_location(
                        location.lat,
                        location.lon,
                        location.altitude,
                    )

                # Keyboard
                keycode = None
                try:
                    keycode = keyboard_queue.get(block=False)
                except queue.Empty:
                    pass

                if menu_manager.error_dialog is not None:
                    power_manager.register_activity()
                    keyboard_mapping_manager.suspend_for_error()
                else:
                    keyboard_mapping_manager.tick()
                keyboard_activity = keycode is not None
                if menu_manager.error_dialog is not None:
                    if keyboard_mapping.is_keyboard_event(keycode):
                        keycode = keyboard_mapping_manager.error_dialog_key(keycode)
                    menu_manager.consume_error_key(keycode)
                    keycode = None
                elif keyboard_mapping.is_keyboard_event(keycode):
                    keycode = keyboard_mapping_manager.handle_event(keycode)

                # Register activity here will return True if the power
                # state changes.  If so, we DO NOT process this keystroke
                if keyboard_activity and power_manager.register_activity() is False:
                    # ignore keystroke if we have been asleep
                    if keycode is None:
                        pass
                    elif keyboard_base.is_number_press_key(keycode):
                        menu_manager.key_number_press(
                            keyboard_base.number_from_press_keycode(keycode)
                        )

                    elif keyboard_base.is_number_release_key(keycode):
                        menu_manager.key_number_release(
                            keyboard_base.number_from_release_keycode(keycode)
                        )

                    elif keyboard_base.is_text_press_key(keycode):
                        menu_manager.key_text_press(
                            keyboard_base.text_from_press_keycode(keycode)
                        )

                    elif keyboard_base.is_text_release_key(keycode):
                        menu_manager.key_text_release(
                            keyboard_base.text_from_release_keycode(keycode)
                        )

                    elif keyboard_base.is_text_key(keycode):
                        menu_manager.key_text(keyboard_base.text_from_keycode(keycode))

                    elif keycode > 99:
                        # Long left is return to top
                        if keycode == keyboard_base.LNG_LEFT:
                            menu_manager.key_long_left()

                        # Long right is return to last observed object
                        if keycode == keyboard_base.LNG_RIGHT:
                            menu_manager.key_long_right()

                        # Long square is marking menu
                        if keycode == keyboard_base.LNG_SQUARE:
                            menu_manager.key_long_square()

                        # Special codes....
                        if (
                            keycode == keyboard_base.ALT_PLUS
                            or keycode == keyboard_base.ALT_MINUS
                        ):
                            if keycode == keyboard_base.ALT_PLUS:
                                screen_adjust = int(screen_brightness * 0.2)
                                if screen_adjust < 2:
                                    screen_adjust = 2

                                screen_brightness += screen_adjust
                                if screen_brightness > 255:
                                    screen_brightness = 255
                            else:
                                screen_adjust = int(screen_brightness * 0.1)
                                if screen_adjust < 1:
                                    screen_adjust = 1

                                screen_brightness -= screen_adjust
                                if screen_brightness < 0:
                                    screen_brightness = 0

                            set_brightness(screen_brightness, cfg)
                            cfg.set_option("display_brightness", screen_brightness)
                            console.write("Brightness: " + str(screen_brightness))
                            logger.info("Brightness: %s", screen_brightness)

                        if keycode == keyboard_base.ALT_0:
                            # screenshot
                            menu_manager.screengrab()
                            console.write("Screenshot saved")
                            logger.info("Screenshot saved")

                        if (
                            keycode == keyboard_base.ALT_LEFT
                            or keycode == keyboard_base.ALT_RIGHT
                        ):
                            # Image snapshot (ALT_LEFT) or Debug snapshot (ALT_RIGHT)
                            uid = str(uuid.uuid1()).split("-")[0]

                            # wait two seconds for any vibration from
                            # pressing the button to pass.
                            menu_manager.message("Saving: 2", 1)
                            time.sleep(1)
                            menu_manager.message("Saving: 1", 1)
                            time.sleep(1)
                            menu_manager.message("Saving...", 1)
                            time.sleep(1)
                            debug_image = camera_image.copy()

                            # Always save images for both ALT_LEFT and ALT_RIGHT
                            debug_image.save(f"{utils.debug_dump_dir}/{uid}_raw.png")
                            debug_image = subtract_background(debug_image)
                            debug_image = debug_image.convert("RGB")
                            debug_image = ImageOps.autocontrast(debug_image)
                            debug_image.save(f"{utils.debug_dump_dir}/{uid}_sub.png")

                            if keycode == keyboard_base.ALT_RIGHT:
                                # Additional debug information only for ALT_RIGHT
                                # current screen
                                ss = menu_manager.stack[-1].screen.copy()
                                debug_solution = shared_state.solution()
                                debug_location = shared_state.location()
                                debug_dt = shared_state.datetime()

                                ss.save(f"{utils.debug_dump_dir}/{uid}_screenshot.png")

                                with open(
                                    f"{utils.debug_dump_dir}/{uid}_solution.dbg", "w"
                                ) as f:
                                    f.write(str(debug_solution))

                                with open(
                                    f"{utils.debug_dump_dir}/{uid}_location.dgb", "w"
                                ) as f:
                                    f.write(str(debug_location))

                                if debug_dt is not None:
                                    with open(
                                        f"{utils.debug_dump_dir}/{uid}_datetime.json",
                                        "w",
                                    ) as f:
                                        json.dump(debug_dt.isoformat(), f, indent=4)

                                # Dump shared state
                                # shared_state.serialize(
                                #    f"{utils.debug_dump_dir}/{uid}_sharedstate.pkl"
                                # )

                                # Dump UI State
                                with open(
                                    f"{utils.debug_dump_dir}/{uid}_uistate.pkl", "wb"
                                ) as pkl_out:
                                    pickle.dump(ui_state, pkl_out)

                                console.write(f"Debug dump: {uid}")
                                logger.info(f"Debug dump: {uid}")
                                menu_manager.message("Debug Info Saved", timeout=1)
                            else:
                                # ALT_LEFT - just image saved
                                console.write(f"Image saved: {uid}")
                                logger.info(f"Image saved: {uid}")
                                menu_manager.message("Image Saved", timeout=1)

                    else:
                        if keycode < 10:
                            menu_manager.key_number(keycode)

                        elif keycode == keyboard_base.PLUS:
                            menu_manager.key_plus()

                        elif keycode == keyboard_base.MINUS:
                            menu_manager.key_minus()

                        elif keycode == keyboard_base.SQUARE:
                            menu_manager.key_square()

                        elif keycode == keyboard_base.LEFT:
                            menu_manager.key_left()

                        elif keycode == keyboard_base.UP:
                            menu_manager.key_up()

                        elif keycode == keyboard_base.DOWN:
                            menu_manager.key_down()

                        elif keycode == keyboard_base.RIGHT:
                            menu_manager.key_right()

                menu_manager.update()
                power_manager.update()

                if (
                    mountcontrol_enabled
                    and time.monotonic() >= next_mountcontrol_health_check
                ):
                    next_mountcontrol_health_check = time.monotonic() + 5.0
                    if mountcontrol_process is None:
                        logger.warning(
                            "INDI mount-control process is not running; restarting"
                        )
                        show_mount_process_error(
                            {
                                "source": "INDI Mount",
                                "code": "process_exited",
                                "message": _(
                                    "Mount control stopped. Restarting service."
                                ),
                            }
                        )
                        mountcontrol_process = start_mountcontrol_process()
                    elif not mountcontrol_process.is_alive():
                        exitcode = mountcontrol_process.exitcode
                        logger.warning(
                            "INDI mount-control process exited with code %s; "
                            "restarting",
                            exitcode,
                        )
                        mountcontrol_process.join(timeout=0)
                        show_mount_process_error(
                            {
                                "source": "INDI Mount",
                                "code": "process_exited",
                                "message": _(
                                    "Mount control stopped. Restarting service."
                                ),
                            }
                        )
                        mountcontrol_process = start_mountcontrol_process()

                if (
                    mountcontrol_enabled
                    and time.monotonic() >= next_goto_guide_health_check
                ):
                    next_goto_guide_health_check = time.monotonic() + 5.0
                    if goto_guide_process is None:
                        logger.warning(
                            "INDI GoTo/Guide service is not running; restarting"
                        )
                        show_mount_process_error(
                            {
                                "source": "GoTo / Guide",
                                "code": "process_exited",
                                "message": _("GoTo/Guide stopped. Restarting service."),
                            }
                        )
                        goto_guide_process = start_goto_guide_process()
                    elif not goto_guide_process.is_alive():
                        exitcode = goto_guide_process.exitcode
                        logger.warning(
                            "INDI GoTo/Guide service exited with code %s; restarting",
                            exitcode,
                        )
                        goto_guide_process.join(timeout=0)
                        show_mount_process_error(
                            {
                                "source": "GoTo / Guide",
                                "code": "process_exited",
                                "message": _("GoTo/Guide stopped. Restarting service."),
                            }
                        )
                        goto_guide_process = start_goto_guide_process()

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received: shutting down.")
            logger.info("SHUTDOWN")
            try:
                logger.debug("\tClearing console queue...")
                while True:
                    console_queue.get(block=False)
            except queue.Empty:
                pass

            logger.info("\tKeyboard...")
            try:
                while True:
                    keyboard_queue.get(block=False)
            except queue.Empty:
                keyboard_process.join()

            logger.info("\tServer...")
            server_process.join()

            logger.info("\tPos Server...")
            posserver_process.join()

            if goto_guide_process is not None:
                logger.info("\tINDI GoTo/Guide...")
                goto_guide_queue.put({"type": "shutdown"})
                goto_guide_process.join(timeout=3)
                if goto_guide_process.is_alive():
                    goto_guide_process.terminate()
                    goto_guide_process.join()

            if mountcontrol_process is not None:
                logger.info("\tINDI Mount...")
                mountcontrol_queue.put({"type": "shutdown"})
                mountcontrol_process.join(timeout=3)
                if mountcontrol_process.is_alive():
                    mountcontrol_process.terminate()
                    mountcontrol_process.join()

            logger.info("\tGPS...")
            gps_process.terminate()

            logger.info("\tImaging...")
            image_process.join()

            logger.info("\tIMU...")
            imu_process.join()

            logger.info("\tIntegrator...")
            integrator_process.join()

            logger.info("\tSolver...")
            solver_process.join()

            log_helper.join()
            exit()


if __name__ == "__main__":
    import sys

    # Ensure the active log config symlink exists, defaulting to logconf_default.json
    _logconf_link = Path("pifinder_logconf.json")
    if not _logconf_link.exists():
        _logconf_link.symlink_to("logconf_default.json")

    debug_no_file_logs = "--debug-no-file-logs" in sys.argv
    if debug_no_file_logs:
        os.environ["MFNAVIS_DEBUG_NO_FILE_LOGS"] = "1"

    print("Bootstrap logging configuration ...")
    logging.basicConfig(format="%(asctime)s BASIC %(name)s: %(levelname)s %(message)s")
    rlogger = logging.getLogger()
    rlogger.setLevel(logging.DEBUG if debug_no_file_logs else logging.INFO)

    if debug_no_file_logs:
        log_helper = MultiprocLogging(Path("pifinder_logconf.json"), console_only=True)
        MultiprocLogging.configurer(log_helper.get_queue())
    else:
        # Logs live on tmpfs (utils.log_dir); use the web Logs page "Save to
        # SD" action to persist a session worth keeping.
        utils.create_path(utils.log_dir)
        log_path = utils.log_dir / "mfnavis.log"
        try:
            log_helper = MultiprocLogging(
                Path("pifinder_logconf.json"),
                log_path,
            )
            MultiprocLogging.configurer(log_helper.get_queue())
        except FileNotFoundError:
            rlogger.warning(
                "Cannot find log configuration file, proceeding with basic configuration."
            )
            rlogger.warning("Logs will not be stored on disk, unless you use --log")
            logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)
            logging.getLogger("tetra3.Tetra3").setLevel(logging.WARNING)
            logging.getLogger("picamera2.picamera2").setLevel(logging.WARNING)

    rlogger.info("Starting MFNavis ...")
    parser = argparse.ArgumentParser(description="eFinder")
    parser.add_argument(
        "-fh",
        "--fakehardware",
        help="Use fake hardware for imu, gps",
        default=False,
        action="store_true",
        required=False,
    )
    parser.add_argument(
        "-c",
        "--camera",
        help="Specify which camera to use: pi, asi, debug or none",
        default=None,
        required=False,
    )
    parser.add_argument(
        "-g",
        "--gps",
        help="Specify which GPS to use: pi, fake",
        default="pi",
        required=False,
    )
    parser.add_argument(
        "-k",
        "--keyboard",
        help="Specify which keyboard to use: pi, local or server",
        default="pi",
        required=False,
    )
    parser.add_argument(
        "--script",
        help="Specify a testing script to run",
        default=None,
        required=False,
    )

    parser.add_argument(
        "-f",
        "--fps",
        help="Display FPS in title bar",
        default=False,
        action="store_true",
        required=False,
    )

    parser.add_argument(
        "--display",
        help="Display Hardware to use",
        default=None,
        required=False,
    )

    parser.add_argument(
        "-n",
        "--notmp",
        help="Don't use the /dev/shm temporary directory.\
                (usefull if not on pi)",
        default=False,
        action="store_true",
        required=False,
    )
    parser.add_argument(
        "-x", "--verbose", help="Set logging to debug mode", action="store_true"
    )
    parser.add_argument("-l", "--log", help="Log to file", action="store_true")
    parser.add_argument(
        "--debug-no-file-logs",
        help="Debug: log everything at DEBUG level to console only, bypassing log configuration and file output",
        action="store_true",
    )
    parser.add_argument(
        "--lang",
        help="Force user interface language (iso2 code). Changes configuration",
        type=str,
    )
    parser.add_argument(
        "--profile-startup",
        help="Profile startup performance (catalog/menu loading)",
        default=False,
        action="store_true",
        required=False,
    )
    args = parser.parse_args()
    # add the handlers to the logger
    if args.verbose:
        rlogger.setLevel(logging.DEBUG)

    import importlib

    if args.fakehardware:
        hardware_platform = "Fake"
        display_hardware = "pg_128"
        imu = importlib.import_module("PiFinder.imu_fake")
        integrator = importlib.import_module("PiFinder.integrator")
        gps_monitor = importlib.import_module("PiFinder.gps_fake")
    else:
        hardware_platform = "Pi"
        from PiFinder import hardware_detect

        display_hardware = hardware_detect.default_display_hardware()
        rlogger.info("using %s display", display_hardware)
        from rpi_hardware_pwm import HardwarePWM

        cfg = config.Config()
        imu = importlib.import_module("PiFinder.imu_pi")
        integrator = importlib.import_module("PiFinder.integrator")

        # verify and sync GPSD serial device and baud rate
        try:
            from PiFinder import sys_utils

            baud_rate = cfg.get_option(
                "gps_baud_rate", 9600
            )  # Default to 9600 if not set
            gps_port = cfg.get_option("gps_port", sys_utils.DEFAULT_GPSD_DEVICE)
            if sys_utils.check_and_sync_gpsd_config(baud_rate, gps_port):
                logger.info(
                    f"GPSD configuration updated to {gps_port} @ {baud_rate} baud"
                )
        except Exception as e:
            logger.warning(f"Could not check/sync GPSD configuration: {e}")

        gps_type = cfg.get_option("gps_type")
        if args.gps == "fake":
            gps_monitor = importlib.import_module("PiFinder.gps_fake")
        elif gps_type == "ublox":
            gps_monitor = importlib.import_module("PiFinder.gps_ubx")
        else:
            gps_monitor = importlib.import_module("PiFinder.gps_gpsd")

    if args.display is not None:
        display_hardware = args.display.lower()

    camera_type = args.camera.lower() if args.camera is not None else None
    if camera_type is None:
        camera_type = "debug" if args.fakehardware else "pi"

    if camera_type == "pi":
        rlogger.info("using pi camera")
        from PiFinder import camera_pi as camera
    elif camera_type == "debug":
        rlogger.info("using debug camera")
        from PiFinder import camera_debug as camera  # type: ignore[no-redef]
    elif camera_type == "asi":
        rlogger.info("using asi camera")
    else:
        rlogger.warn("not using camera")
        from PiFinder import camera_none as camera  # type: ignore[no-redef]

    if args.keyboard.lower() == "pi":
        from PiFinder import keyboard_pi as keyboard

        rlogger.info("using pi keyboard hat")
    elif args.keyboard.lower() == "local":
        if display_hardware.startswith("pg_"):
            from PiFinder import keyboard_none as keyboard  # type: ignore[no-redef]

            rlogger.info("using pygame keyboard (main loop captures keys)")
        else:
            from PiFinder import keyboard_local as keyboard  # type: ignore[no-redef]

            rlogger.info("using local keyboard")
    elif args.keyboard.lower() == "none":
        from PiFinder import keyboard_none as keyboard  # type: ignore[no-redef]

        rlogger.warning("using no keyboard")

    if args.lang:
        if args.lang.lower() not in ["en", "de", "fr", "es", "ko", "zh"]:
            raise Exception(f"Unknown language '{args.lang}' passed via command line.")
        else:
            config.Config().set_option("language", args.lang)

    try:
        main(log_helper, args.script, args.fps, args.verbose, args.profile_startup)
    except Exception:
        rlogger.exception("Exception in main(). Aborting program.")
        os._exit(1)
