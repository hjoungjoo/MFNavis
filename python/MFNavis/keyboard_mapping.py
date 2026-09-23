#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Configurable physical-keyboard shortcuts for mount control.

``keyboard_pi`` attaches the raw Linux key code and press/release state to its
normal PiFinder keycode.  The main process feeds those events here, allowing
the settings UI and dispatcher to share one in-process manager while leaving
the GPIO keypad and Web Remote unchanged.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional, TypeGuard

from PiFinder.keyboard_interface import KeyboardInterface


CONFIG_KEY = "keyboard_mapping"
EVENT_TYPE = "physical_keyboard"

MANUAL_MOTION_KEEPALIVE_INTERVAL = 0.4
MANUAL_MOTION_LEASE_SECONDS = 1.2
MANUAL_MOTION_RESTART_INTERVAL = 8.0

ACTIONS: tuple[tuple[str, str], ...] = (
    ("mount_up", "Mount Up"),
    ("mount_down", "Mount Down"),
    ("mount_left", "Mount Left"),
    ("mount_right", "Mount Right"),
    ("speed_up", "Speed +"),
    ("speed_down", "Speed -"),
    ("goto_start", "GoTo"),
    ("tracking_off", "Tracking Off"),
)

# Keep the keys needed to operate menus available at all times. In particular,
# Left must be able to leave Test Keys, and Enter/arrow keys must retain their
# normal UI navigation behavior instead of becoming global mount shortcuts.
RESERVED_KEY_IDS = frozenset(
    {
        "KEY_28",  # Enter
        "KEY_96",  # Keypad Enter
        "KEY_103",  # Up
        "KEY_105",  # Left
        "KEY_106",  # Right
        "KEY_108",  # Down
    }
)

_MOUNT_DIRECTIONS = {
    "mount_up": "north",
    "mount_down": "south",
    "mount_left": "west",
    "mount_right": "east",
}

# Linux input-event codes used by keyboard_pi. Unknown keys remain bindable and
# are displayed as KEY_<number>.
_KEY_LABELS = {
    1: "Esc",
    2: "1",
    3: "2",
    4: "3",
    5: "4",
    6: "5",
    7: "6",
    8: "7",
    9: "8",
    10: "9",
    11: "0",
    12: "-",
    13: "=",
    14: "Backspace",
    15: "Tab",
    16: "Q",
    17: "W",
    18: "E",
    19: "R",
    20: "T",
    21: "Y",
    22: "U",
    23: "I",
    24: "O",
    25: "P",
    28: "Enter",
    29: "Left Ctrl",
    30: "A",
    31: "S",
    32: "D",
    33: "F",
    34: "G",
    35: "H",
    36: "J",
    37: "K",
    38: "L",
    42: "Left Shift",
    44: "Z",
    45: "X",
    46: "C",
    47: "V",
    48: "B",
    49: "N",
    50: "M",
    51: ",",
    52: ".",
    54: "Right Shift",
    56: "Left Alt",
    57: "Space",
    71: "Keypad 7",
    72: "Keypad 8",
    73: "Keypad 9",
    74: "Keypad -",
    75: "Keypad 4",
    76: "Keypad 5",
    77: "Keypad 6",
    78: "Keypad +",
    79: "Keypad 1",
    80: "Keypad 2",
    81: "Keypad 3",
    82: "Keypad 0",
    96: "Keypad Enter",
    97: "Right Ctrl",
    100: "Right Alt",
    103: "Up",
    105: "Left",
    106: "Right",
    108: "Down",
}


def key_id(code: int) -> str:
    return f"KEY_{int(code)}"


def key_label(identifier: str) -> str:
    try:
        code = int(str(identifier).removeprefix("KEY_"))
    except (TypeError, ValueError):
        return str(identifier)
    return _KEY_LABELS.get(code, f"Key {code}")


def is_assignable_key(identifier: str) -> bool:
    return str(identifier) not in RESERVED_KEY_IDS


def make_event(
    code: int, pressed: bool, keycode: int = 0, *, repeat: bool = False
) -> dict[str, Any]:
    return {
        "type": EVENT_TYPE,
        "code": int(code),
        "key_id": key_id(code),
        "pressed": bool(pressed),
        "repeat": bool(repeat),
        "keycode": int(keycode or 0),
    }


def is_keyboard_event(value: Any) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict) and value.get("type") == EVENT_TYPE


class KeyboardDispatcher:
    """Turn mapped physical key events into direct mount/UI commands."""

    def __init__(
        self,
        keyboard_queue,
        mountcontrol_queue,
        mount_enabled: Callable[[], bool],
    ) -> None:
        self.keyboard_queue = keyboard_queue
        self.mountcontrol_queue = mountcontrol_queue
        self.mount_enabled = mount_enabled
        self.key_actions: dict[str, str] = {}
        self._held_direction: Optional[str] = None
        self._held_key: Optional[str] = None
        self._next_keepalive = 0.0
        self._next_restart = 0.0

    def set_mapping(self, mapping: dict[str, Any]) -> None:
        actions = {action for action, _label in ACTIONS}
        inverted: dict[str, str] = {}
        for action, identifier in (mapping or {}).items():
            if action in actions and identifier and is_assignable_key(str(identifier)):
                inverted[str(identifier)] = action
        # A binding may be cleared/reassigned while its direction key is held.
        # Stop first so the old held key cannot keep renewing motion after its
        # release is no longer mapped to this dispatcher.
        if self._held_direction is not None:
            self.mountcontrol_queue.put({"type": "stop_movement"})
            self._held_direction = None
            self._held_key = None
        self.key_actions = inverted

    def handle_key(
        self, identifier: str, pressed: bool, now: float, *, repeat: bool = False
    ) -> bool:
        action = self.key_actions.get(identifier)
        if action is None:
            return False
        if repeat:
            return True

        if action == "goto_start":
            keycode = (
                KeyboardInterface.number_press_key(5)
                if pressed
                else KeyboardInterface.number_release_key(5)
            )
            self.keyboard_queue.put(keycode)
            return True

        if not self.mount_enabled():
            return True
        if action in _MOUNT_DIRECTIONS:
            self._handle_mount_direction(
                _MOUNT_DIRECTIONS[action], identifier, pressed, now
            )
        elif action == "speed_up" and pressed:
            self.mountcontrol_queue.put(
                {"type": "increase_slew_rate", "notify_ui": True}
            )
        elif action == "speed_down" and pressed:
            self.mountcontrol_queue.put({"type": "reduce_slew_rate", "notify_ui": True})
        elif action == "tracking_off" and pressed:
            self.mountcontrol_queue.put({"type": "set_tracking", "enabled": False})
        return True

    def _handle_mount_direction(
        self, direction: str, identifier: str, pressed: bool, now: float
    ) -> None:
        if pressed:
            self._held_direction = direction
            self._held_key = identifier
            self._next_keepalive = now + MANUAL_MOTION_KEEPALIVE_INTERVAL
            self._next_restart = now + MANUAL_MOTION_RESTART_INTERVAL
            self.mountcontrol_queue.put(
                {
                    "type": "manual_movement",
                    "direction": direction,
                    "lease_seconds": MANUAL_MOTION_LEASE_SECONDS,
                }
            )
        elif identifier == self._held_key:
            self._held_direction = None
            self._held_key = None
            self.mountcontrol_queue.put({"type": "stop_movement"})

    def tick(self, now: float) -> None:
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


class KeyboardMappingManager:
    """Shared main-process state for dispatch, key test, and key capture."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dispatcher: Optional[KeyboardDispatcher] = None
        self._config = None
        self.last_key = ""
        self.last_key_code: Optional[int] = None
        self.last_key_at = 0.0
        self._capturing = False
        self._capture_allows_left = False
        self._captured: Optional[str] = None
        self._suppressed_until_release: set[str] = set()

    def start(self, keyboard_queue, mountcontrol_queue, config) -> None:
        self._config = config

        def _mount_enabled() -> bool:
            try:
                return bool(config.get_option("mount_control", False))
            except Exception:
                return False

        self._dispatcher = KeyboardDispatcher(
            keyboard_queue, mountcontrol_queue, _mount_enabled
        )
        self.reload_mapping()

    def start_capture(self, *, allow_left: bool = False) -> None:
        with self._lock:
            self._capturing = True
            self._capture_allows_left = allow_left
            self._captured = None

    def cancel_capture(self) -> None:
        with self._lock:
            self._capturing = False
            self._capture_allows_left = False
            self._captured = None

    def take_captured(self) -> Optional[str]:
        with self._lock:
            captured = self._captured
            if captured is not None:
                self._capturing = False
                self._capture_allows_left = False
                self._captured = None
            return captured

    def reload_mapping(self) -> None:
        if self._dispatcher is None or self._config is None:
            return
        self._dispatcher.set_mapping(self._config.get_option(CONFIG_KEY) or {})

    def handle_event(
        self, event: dict[str, Any], now: Optional[float] = None
    ) -> int | None:
        identifier = str(event.get("key_id") or key_id(int(event.get("code", 0))))
        code = int(event.get("code", 0))
        pressed = bool(event.get("pressed"))
        repeat = bool(event.get("repeat"))
        event_now = time.monotonic() if now is None else now

        with self._lock:
            pass_through_left = (
                self._capturing
                and self._capture_allows_left
                and identifier == "KEY_105"
            )
            if pressed and not repeat:
                self.last_key = identifier
                self.last_key_code = code
                self.last_key_at = time.time()
                if self._capturing and not pass_through_left:
                    self._captured = identifier
                    self._suppressed_until_release.add(identifier)
            capturing = self._capturing and not pass_through_left
            suppressed = identifier in self._suppressed_until_release
            if suppressed and not pressed:
                self._suppressed_until_release.discard(identifier)

        if capturing or suppressed:
            return None
        dispatcher = self._dispatcher
        if dispatcher is not None and dispatcher.handle_key(
            identifier, pressed, event_now, repeat=repeat
        ):
            return None
        keycode = int(event.get("keycode", 0) or 0)
        return keycode or None

    def tick(self, now: Optional[float] = None) -> None:
        if self._dispatcher is not None:
            self._dispatcher.tick(time.monotonic() if now is None else now)

    def suspend_for_error(self) -> None:
        """Stop held shortcuts while the LCD owns input for acknowledgement."""
        dispatcher = self._dispatcher
        if dispatcher is not None and dispatcher._held_direction is not None:
            if dispatcher._held_key is not None:
                self._suppressed_until_release.add(dispatcher._held_key)
            dispatcher.mountcontrol_queue.put({"type": "stop_movement"})
            dispatcher._held_direction = None
            dispatcher._held_key = None

    def error_dialog_key(self, event: dict[str, Any]) -> int | None:
        """Bypass mount bindings and swallow the eventual acknowledgement release."""
        identifier = str(event.get("key_id") or key_id(int(event.get("code", 0))))
        with self._lock:
            if not event.get("pressed"):
                self._suppressed_until_release.discard(identifier)
                return None
            already_held = identifier in self._suppressed_until_release
            self._suppressed_until_release.add(identifier)
        if already_held or event.get("repeat"):
            return None
        return {
            106: KeyboardInterface.RIGHT,
            105: KeyboardInterface.LEFT,
            103: KeyboardInterface.UP,
            108: KeyboardInterface.DOWN,
            28: KeyboardInterface.SQUARE,
            96: KeyboardInterface.SQUARE,
        }.get(int(event.get("code", 0)), int(event.get("keycode", 0)) or None)


_manager: Optional[KeyboardMappingManager] = None


def manager() -> KeyboardMappingManager:
    global _manager
    if _manager is None:
        _manager = KeyboardMappingManager()
    return _manager
