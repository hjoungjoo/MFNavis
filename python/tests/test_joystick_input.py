#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Tests for the joystick button dispatcher (PiFinder.joystick_input).

The dispatcher is the pure half of the joystick reader: it turns decoded
button events into keypad keycodes or mount-control commands according to the
user's mapping. The evdev I/O half is exercised on hardware.
"""

import queue

import pytest

from PiFinder import joystick_input
from PiFinder.joystick_input import (
    MANUAL_MOTION_KEEPALIVE_INTERVAL,
    MANUAL_MOTION_LEASE_SECONDS,
    MANUAL_MOTION_RESTART_INTERVAL,
    JoystickDispatcher,
    hat_button_id,
)
from PiFinder.keyboard_interface import KeyboardInterface


def _dispatcher(mount_enabled=True):
    keyboard: queue.Queue = queue.Queue()
    mount: queue.Queue = queue.Queue()
    dispatcher = JoystickDispatcher(keyboard, mount, lambda: mount_enabled)
    return dispatcher, keyboard, mount


def _drain(q: queue.Queue) -> list:
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


@pytest.mark.unit
class TestMappingNormalization:
    def test_config_layout_is_inverted_to_button_lookup(self):
        dispatcher, _, _ = _dispatcher()
        dispatcher.set_mapping({"keypad_up": "BTN_SOUTH", "speed_up": "BTN_TR"})
        assert dispatcher.button_actions == {
            "BTN_SOUTH": "keypad_up",
            "BTN_TR": "speed_up",
        }

    def test_unknown_actions_and_empty_buttons_are_dropped(self):
        dispatcher, _, _ = _dispatcher()
        dispatcher.set_mapping({"bogus": "BTN_A", "keypad_up": "", "mount_up": None})
        assert dispatcher.button_actions == {}


@pytest.mark.unit
class TestKeypadActions:
    def test_press_injects_keycode_release_is_silent(self):
        dispatcher, keyboard, mount = _dispatcher()
        dispatcher.set_mapping({"keypad_up": "BTN_DPAD_UP"})
        dispatcher.handle_button("BTN_DPAD_UP", True, 0.0)
        dispatcher.handle_button("BTN_DPAD_UP", False, 0.1)
        assert _drain(keyboard) == [KeyboardInterface.UP]
        assert _drain(mount) == []

    def test_goto_sends_number_5_press_and_release(self):
        """GoTo rides the keypad's 5, so Object Details starts the GoTo."""
        dispatcher, keyboard, _ = _dispatcher()
        dispatcher.set_mapping({"goto_start": "BTN_START"})
        dispatcher.handle_button("BTN_START", True, 0.0)
        dispatcher.handle_button("BTN_START", False, 0.1)
        assert _drain(keyboard) == [
            KeyboardInterface.number_press_key(5),
            KeyboardInterface.number_release_key(5),
        ]

    def test_unmapped_button_does_nothing(self):
        dispatcher, keyboard, mount = _dispatcher()
        dispatcher.set_mapping({"keypad_up": "BTN_DPAD_UP"})
        dispatcher.handle_button("BTN_SOUTH", True, 0.0)
        assert _drain(keyboard) == []
        assert _drain(mount) == []


@pytest.mark.unit
class TestMountActions:
    def test_hold_to_move_press_keepalive_release(self):
        dispatcher, _, mount = _dispatcher()
        dispatcher.set_mapping({"mount_up": "BTN_DPAD_UP"})

        dispatcher.handle_button("BTN_DPAD_UP", True, 10.0)
        # Before the keepalive interval: nothing extra.
        dispatcher.tick(10.0 + MANUAL_MOTION_KEEPALIVE_INTERVAL / 2)
        # After it: one keepalive.
        dispatcher.tick(10.0 + MANUAL_MOTION_KEEPALIVE_INTERVAL + 0.01)
        dispatcher.handle_button("BTN_DPAD_UP", False, 11.0)

        commands = _drain(mount)
        assert commands == [
            {
                "type": "manual_movement",
                "direction": "north",
                "lease_seconds": MANUAL_MOTION_LEASE_SECONDS,
            },
            {
                "type": "manual_movement_keepalive",
                "direction": "north",
                "lease_seconds": MANUAL_MOTION_LEASE_SECONDS,
            },
            {"type": "stop_movement"},
        ]

    def test_long_hold_resends_manual_movement_past_the_10s_cap(self):
        """Retain start resends for mount processes with the old 10 s cap."""
        dispatcher, _, mount = _dispatcher()
        dispatcher.set_mapping({"mount_up": "BTN_DPAD_UP"})

        dispatcher.handle_button("BTN_DPAD_UP", True, 0.0)
        dispatcher.tick(MANUAL_MOTION_RESTART_INTERVAL - 0.01)
        dispatcher.tick(MANUAL_MOTION_RESTART_INTERVAL + 0.01)

        moves = [c for c in _drain(mount) if c["type"] == "manual_movement"]
        assert len(moves) == 2

        # And the restart re-arms itself for the next interval.
        dispatcher.tick(2 * MANUAL_MOTION_RESTART_INTERVAL + 0.02)
        moves = [c for c in _drain(mount) if c["type"] == "manual_movement"]
        assert len(moves) == 1

    def test_direction_names_follow_the_guide_screen(self):
        dispatcher, _, mount = _dispatcher()
        dispatcher.set_mapping(
            {
                "mount_up": "U",
                "mount_down": "D",
                "mount_left": "L",
                "mount_right": "R",
            }
        )
        for button in ("U", "D", "L", "R"):
            dispatcher.handle_button(button, True, 0.0)
        directions = [c["direction"] for c in _drain(mount) if "direction" in c]
        assert directions == ["north", "south", "west", "east"]

    def test_release_of_superseded_direction_does_not_stop(self):
        """New direction supersedes the old; the old release must not stop it."""
        dispatcher, _, mount = _dispatcher()
        dispatcher.set_mapping({"mount_up": "U", "mount_left": "L"})
        dispatcher.handle_button("U", True, 0.0)
        dispatcher.handle_button("L", True, 0.1)  # supersedes U
        dispatcher.handle_button("U", False, 0.2)  # stale release
        commands = _drain(mount)
        assert {"type": "stop_movement"} not in commands
        dispatcher.handle_button("L", False, 0.3)
        assert {"type": "stop_movement"} in _drain(mount)

    def test_speed_and_tracking_fire_on_press_only(self):
        dispatcher, _, mount = _dispatcher()
        dispatcher.set_mapping(
            {"speed_up": "P", "speed_down": "M", "tracking_off": "T"}
        )
        for button in ("P", "M", "T"):
            dispatcher.handle_button(button, True, 0.0)
            dispatcher.handle_button(button, False, 0.1)
        assert _drain(mount) == [
            {"type": "increase_slew_rate", "notify_ui": True},
            {"type": "reduce_slew_rate", "notify_ui": True},
            {"type": "set_tracking", "enabled": False},
        ]

    def test_mount_actions_ignored_when_mount_control_off(self):
        dispatcher, keyboard, mount = _dispatcher(mount_enabled=False)
        dispatcher.set_mapping({"mount_up": "U", "speed_up": "P", "keypad_up": "K"})
        dispatcher.handle_button("U", True, 0.0)
        dispatcher.handle_button("P", True, 0.0)
        dispatcher.handle_button("K", True, 0.0)
        assert _drain(mount) == []
        # Keypad actions are independent of mount control.
        assert _drain(keyboard) == [KeyboardInterface.UP]


@pytest.mark.unit
class TestHatButtons:
    def test_hat_ids(self):
        assert hat_button_id("HAT0X", -1) == "HAT0X-"
        assert hat_button_id("HAT0Y", 1) == "HAT0Y+"


@pytest.mark.unit
def test_actions_cover_the_requested_functions():
    """The mapping menu offers every function the feature was asked for."""
    actions = {action for action, _label in joystick_input.ACTIONS}
    assert {
        "keypad_up",
        "keypad_down",
        "keypad_left",
        "keypad_right",
        "mount_up",
        "mount_down",
        "mount_left",
        "mount_right",
        "speed_up",
        "speed_down",
        "goto_start",
        "tracking_off",
    } <= actions
