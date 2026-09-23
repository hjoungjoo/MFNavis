#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Bluetooth/USB joystick and gamepad input.

libinput (keyboard_pi.py) deliberately ignores joystick-class devices, so a
paired controller connects fine but none of its buttons reach the UI. This
module reads those devices directly through evdev and dispatches the buttons
the user has mapped in Settings > Advanced > Joystick.

Two kinds of actions exist, on purpose:

* Keypad actions inject ordinary PiFinder keycodes into the keyboard queue,
  so they behave exactly like pressing the physical keypad on whatever screen
  is active (arrows navigate, GoTo is the keypad's 5 -- it starts a GoTo on
  the Object Details screen, where a target exists).
* Mount actions talk to the mount-control queue directly, so they work the
  same regardless of the active screen: hold-to-move manual slewing with the
  same lease/keepalive scheme the LCD guide screen uses, slew-rate steps,
  and tracking off.

Buttons are identified by a stable string id: ``BTN_<code>`` for key events
and ``HAT0X-``-style ids for the d-pad hat axes many gamepads use instead of
buttons. The mapping lives in config under ``joystick_mapping`` as
``{action: button_id}``.

evdev import is lazy and failure-tolerant: on systems without python3-evdev
the manager reports "no support" and everything else keeps working.
"""

from __future__ import annotations

import logging
import select
import threading
import time
from typing import Any, Callable, Optional

from PiFinder.keyboard_interface import KeyboardInterface

logger = logging.getLogger("Joystick")

CONFIG_KEY = "joystick_mapping"

# Same lease/keepalive scheme as the LCD guide screen (ui/indi.py): the mount
# process stops motion itself when the lease runs out, so a died reader can
# never leave the mount slewing.
MANUAL_MOTION_KEEPALIVE_INTERVAL = 0.4
MANUAL_MOTION_LEASE_SECONDS = 1.2
# The mount process refuses to extend one manual_movement past its 10 s
# continuous-hold cap on keepalives alone; the sender must re-send the full
# manual_movement to keep a held button moving (same contract as ui/base.py's
# guide keys and pos_server).
MANUAL_MOTION_RESTART_INTERVAL = 8.0

DEVICE_RESCAN_SECONDS = 3.0

# Actions the mapping UI offers, in display order. "keypad_*" inject keycodes;
# the rest address the mount directly.
ACTIONS: tuple[tuple[str, str], ...] = (
    ("keypad_up", "Keypad Up"),
    ("keypad_down", "Keypad Down"),
    ("keypad_left", "Keypad Left"),
    ("keypad_right", "Keypad Right"),
    ("mount_up", "Mount Up"),
    ("mount_down", "Mount Down"),
    ("mount_left", "Mount Left"),
    ("mount_right", "Mount Right"),
    ("speed_up", "Speed +"),
    ("speed_down", "Speed -"),
    ("goto_start", "GoTo (key 5)"),
    ("tracking_off", "Tracking Off"),
)

_KEYPAD_KEYCODES = {
    "keypad_up": KeyboardInterface.UP,
    "keypad_down": KeyboardInterface.DOWN,
    "keypad_left": KeyboardInterface.LEFT,
    "keypad_right": KeyboardInterface.RIGHT,
}

# Mount direction names follow the LCD guide screen: up=north, down=south,
# left=west, right=east.
_MOUNT_DIRECTIONS = {
    "mount_up": "north",
    "mount_down": "south",
    "mount_left": "west",
    "mount_right": "east",
}

# Hat axes (ABS_HAT0X/ABS_HAT0Y = 16/17): value -1/+1 maps to a pseudo-button
# per direction so d-pads that report axes instead of buttons stay mappable.
_HAT_AXES = {16: "HAT0X", 17: "HAT0Y"}


def hat_button_id(axis_name: str, value: int) -> str:
    return f"{axis_name}{'-' if value < 0 else '+'}"


class JoystickDispatcher:
    """Pure mapping/dispatch logic, separated from evdev I/O for testability.

    ``handle_button(button_id, pressed, now)`` is the single entry point; the
    reader thread feeds it decoded button events, tests feed it directly.
    """

    def __init__(
        self,
        keyboard_queue,
        mountcontrol_queue,
        mount_enabled: Callable[[], bool],
    ) -> None:
        self.keyboard_queue = keyboard_queue
        self.mountcontrol_queue = mountcontrol_queue
        self.mount_enabled = mount_enabled
        # button_id -> action
        self.button_actions: dict[str, str] = {}
        # Currently held mount direction (one at a time, matching the LCD
        # guide screen where a new direction supersedes the old one).
        self._held_direction: Optional[str] = None
        self._held_button: Optional[str] = None
        self._next_keepalive = 0.0
        self._next_restart = 0.0

    def set_mapping(self, mapping: dict[str, Any]) -> None:
        """Accept an {action: button_id} mapping (the config layout)."""
        actions = {action for action, _label in ACTIONS}
        inverted: dict[str, str] = {}
        for action, button in (mapping or {}).items():
            if action in actions and button:
                inverted[str(button)] = action
        self.button_actions = inverted

    def handle_button(self, button_id: str, pressed: bool, now: float) -> None:
        action = self.button_actions.get(button_id)
        if action is None:
            return
        if action in _KEYPAD_KEYCODES:
            if pressed:
                self.keyboard_queue.put(_KEYPAD_KEYCODES[action])
            return
        if action == "goto_start":
            # The keypad's 5: GoTo where a target is selected (Object
            # Details); elsewhere it keeps the keypad's normal meaning.
            if pressed:
                self.keyboard_queue.put(KeyboardInterface.number_press_key(5))
            else:
                self.keyboard_queue.put(KeyboardInterface.number_release_key(5))
            return

        # Mount actions from here on.
        if not self.mount_enabled():
            return
        if action in _MOUNT_DIRECTIONS:
            self._handle_mount_direction(
                _MOUNT_DIRECTIONS[action], button_id, pressed, now
            )
        elif action == "speed_up" and pressed:
            self.mountcontrol_queue.put(
                {"type": "increase_slew_rate", "notify_ui": True}
            )
        elif action == "speed_down" and pressed:
            self.mountcontrol_queue.put({"type": "reduce_slew_rate", "notify_ui": True})
        elif action == "tracking_off" and pressed:
            self.mountcontrol_queue.put({"type": "set_tracking", "enabled": False})

    def _handle_mount_direction(
        self, direction: str, button_id: str, pressed: bool, now: float
    ) -> None:
        if pressed:
            self._held_direction = direction
            self._held_button = button_id
            self._next_keepalive = now + MANUAL_MOTION_KEEPALIVE_INTERVAL
            self._next_restart = now + MANUAL_MOTION_RESTART_INTERVAL
            self.mountcontrol_queue.put(
                {
                    "type": "manual_movement",
                    "direction": direction,
                    "lease_seconds": MANUAL_MOTION_LEASE_SECONDS,
                }
            )
        elif button_id == self._held_button:
            self._held_direction = None
            self._held_button = None
            self.mountcontrol_queue.put({"type": "stop_movement"})

    def tick(self, now: float) -> None:
        """Renew the motion lease while a mount direction stays held."""
        if self._held_direction is None:
            return
        if now >= self._next_restart:
            self._next_restart = now + MANUAL_MOTION_RESTART_INTERVAL
            self._next_keepalive = now + MANUAL_MOTION_KEEPALIVE_INTERVAL
            self.mountcontrol_queue.put(
                {
                    "type": "manual_movement",
                    "direction": self._held_direction,
                    "lease_seconds": MANUAL_MOTION_LEASE_SECONDS,
                }
            )
            return
        if now < self._next_keepalive:
            return
        self._next_keepalive = now + MANUAL_MOTION_KEEPALIVE_INTERVAL
        self.mountcontrol_queue.put(
            {
                "type": "manual_movement_keepalive",
                "direction": self._held_direction,
                "lease_seconds": MANUAL_MOTION_LEASE_SECONDS,
            }
        )


class JoystickManager:
    """evdev reader thread plus the shared state the mapping UI polls.

    The UI runs in the same process, so it talks to this singleton directly:
    ``last_button`` for the button tester, ``start_capture()`` /
    ``take_captured()`` for assigning a button to an action.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dispatcher: Optional[JoystickDispatcher] = None
        self._config = None
        self._thread: Optional[threading.Thread] = None
        self._mapping_stamp: Any = None
        self.supported = True
        self.last_button: str = ""
        # Kernel event code of the last button. Shown next to the name in the
        # tester: distinct physical buttons can surface under the same name
        # (or the same code), and only the number makes that visible.
        self.last_button_code: int | None = None
        self.last_button_at: float = 0.0
        self.device_names: list[str] = []
        self._capturing = False
        self._captured: Optional[str] = None

    # -- UI side -----------------------------------------------------------

    def start_capture(self) -> None:
        with self._lock:
            self._capturing = True
            self._captured = None

    def cancel_capture(self) -> None:
        with self._lock:
            self._capturing = False
            self._captured = None

    def take_captured(self) -> Optional[str]:
        with self._lock:
            captured = self._captured
            if captured is not None:
                self._capturing = False
                self._captured = None
            return captured

    def reload_mapping(self) -> None:
        """Called by the mapping UI after it saves a change."""
        dispatcher = self._dispatcher
        config = self._config
        if dispatcher is None or config is None:
            return
        try:
            dispatcher.set_mapping(config.get_option(CONFIG_KEY) or {})
        except Exception:
            logger.exception("Joystick mapping reload failed")

    # -- reader side -------------------------------------------------------

    def start(self, keyboard_queue, mountcontrol_queue, config) -> None:
        """Start the reader thread (idempotent)."""
        if self._thread is not None:
            return
        self._config = config

        def _mount_enabled() -> bool:
            try:
                return bool(config.get_option("mount_control", False))
            except Exception:
                return False

        self._dispatcher = JoystickDispatcher(
            keyboard_queue, mountcontrol_queue, _mount_enabled
        )
        self.reload_mapping()
        self._thread = threading.Thread(
            target=self._run, name="JoystickInput", daemon=True
        )
        self._thread.start()

    def _record_button(self, button_id: str, code: int | None = None) -> None:
        with self._lock:
            self.last_button = button_id
            self.last_button_code = code
            self.last_button_at = time.time()
            if self._capturing:
                self._captured = button_id

    def _capture_active(self) -> bool:
        with self._lock:
            return self._capturing

    def _run(self) -> None:
        try:
            import evdev
            from evdev import ecodes
        except ImportError:
            self.supported = False
            logger.warning("python3-evdev not available; joystick input disabled")
            return

        devices: dict[str, Any] = {}
        hat_state: dict[tuple[str, str], int] = {}
        next_rescan = 0.0

        def _is_joystick(device) -> bool:
            capabilities = device.capabilities().get(ecodes.EV_KEY, [])
            return any(0x120 <= code <= 0x14F for code in capabilities)

        def _button_name(code: int) -> str:
            name = ecodes.BTN.get(code) or ecodes.KEY.get(code) or f"BTN_{code}"
            if isinstance(name, (list, tuple)):
                name = name[0]
            return str(name)

        while True:
            now = time.monotonic()
            if now >= next_rescan:
                next_rescan = now + DEVICE_RESCAN_SECONDS
                try:
                    for path in evdev.list_devices():
                        if path in devices:
                            continue
                        try:
                            device = evdev.InputDevice(path)
                            if _is_joystick(device):
                                devices[path] = device
                                logger.info("Joystick attached: %s", device.name)
                            else:
                                device.close()
                        except OSError:
                            continue
                    self.device_names = [d.name for d in devices.values()]
                except Exception:
                    logger.exception("Joystick device scan failed")

            dispatcher = self._dispatcher
            if dispatcher is not None:
                dispatcher.tick(now)

            if not devices:
                time.sleep(1.0)
                continue

            try:
                readable, _, _ = select.select(list(devices.values()), [], [], 0.2)
            except (OSError, ValueError):
                readable = []

            for device in readable:
                try:
                    for event in device.read():
                        self._handle_event(
                            event, device, ecodes, hat_state, _button_name
                        )
                except OSError:
                    # Device went away (Bluetooth disconnect).
                    logger.info("Joystick detached: %s", device.name)
                    for path, known in list(devices.items()):
                        if known is device:
                            del devices[path]
                    self.device_names = [d.name for d in devices.values()]

    def _handle_event(self, event, device, ecodes, hat_state, button_name) -> None:
        dispatcher = self._dispatcher
        now = time.monotonic()
        if event.type == ecodes.EV_KEY and event.value in (0, 1):
            button_id = button_name(event.code)
            pressed = event.value == 1
            if pressed:
                self._record_button(button_id, event.code)
            if dispatcher is not None and not self._capture_active():
                dispatcher.handle_button(button_id, pressed, now)
        elif event.type == ecodes.EV_ABS and event.code in _HAT_AXES:
            axis = _HAT_AXES[event.code]
            key = (device.path, axis)
            previous = hat_state.get(key, 0)
            value = int(event.value)
            if value == previous:
                return
            hat_state[key] = value
            if previous != 0:
                released = hat_button_id(axis, previous)
                if dispatcher is not None and not self._capture_active():
                    dispatcher.handle_button(released, False, now)
            if value != 0:
                button_id = hat_button_id(axis, value)
                self._record_button(button_id, event.code)
                if dispatcher is not None and not self._capture_active():
                    dispatcher.handle_button(button_id, True, now)


_manager: Optional[JoystickManager] = None
_manager_lock = threading.Lock()


def manager() -> JoystickManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = JoystickManager()
        return _manager
