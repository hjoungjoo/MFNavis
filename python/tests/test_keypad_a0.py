"""A0 switch wiring, event lifecycle, and isolation from legacy/USB input."""

import importlib.util
from pathlib import Path
import queue
import sys
from types import SimpleNamespace

import pytest

from PiFinder import keyboard_mapping
from PiFinder.board_config import A0_MODE, LEGACY_MODE
from PiFinder.keyboard_interface import KeyboardInterface as K
from PiFinder.keypad_a0 import A0Keypad, KEYS, matrix_keys


pytestmark = pytest.mark.unit


def settle(pad, pressed, now):
    events = pad.update(set(pressed), now)
    return events + pad.update(set(pressed), now + 0.04)


def tap(index):
    pad = A0Keypad(matrix_keys())
    return settle(pad, {index}, 0) + settle(pad, set(), 0.1)


@pytest.mark.parametrize(
    "index,name,code,number,release",
    [
        (0, "SW1_DOWN", 3, 2, 0),
        (1, "SW2_DOWN", 108, None, K.DOWN),
        (2, "SW3", 11, 0, 0),
        (3, "SW8", 74, None, K.MINUS),
        (4, "SW1_RIGHT", 7, 6, 0),
        (5, "SW2_RIGHT", 106, None, K.RIGHT),
        (6, "SW4", 61, None, 0),
        (7, "SW9", 78, None, K.PLUS),
        (8, "SW1_LEFT", 5, 4, 0),
        (9, "SW2_LEFT", 105, None, K.LEFT),
        (10, "SW5", 60, None, 0),
        (11, "SW10", 30, None, 0),
        (12, "SW1_CENTER", 6, 5, 0),
        (13, "SW2_CENTER", 256, None, 0),
        (14, "SW6", 59, None, 0),
        (16, "SW1_UP", 9, 8, 0),
        (17, "SW2_UP", 103, None, K.UP),
        (18, "SW7", 28, None, K.SQUARE),
    ],
)
def test_each_physical_contact_emits_correct_press_and_release(
    index, name, code, number, release
):
    press, released = tap(index)
    assert [press["pressed"], released["pressed"]] == [True, False]
    for event in (press, released):
        assert event["key_id"] == f"A0_{name}"
        assert event["code"] == code
        assert event["matrix_index"] == index
        assert event["source"] == A0_MODE
        assert keyboard_mapping.is_keyboard_event(event)
    assert press["keycode"] == (K.number_press_key(number) if number is not None else 0)
    assert released["keycode"] == (
        K.number_release_key(number) if number is not None else release
    )


def test_unused_contacts_and_bounce_do_not_emit_keys():
    pad = A0Keypad(matrix_keys())
    assert settle(pad, {15, 19}, 0) == []
    assert pad.update({0}, 1) == []
    assert pad.update(set(), 1.01) == []
    assert pad.update({0}, 1.02) == []
    press = pad.update({0}, 1.06)
    assert len(press) == 1
    assert pad.update(set(), 1.07) == []
    assert pad.update({0}, 1.08) == []
    assert pad.update({0}, 1.12) == []
    assert len(settle(pad, set(), 1.2)) == 1


@pytest.mark.parametrize("index", [6, 10, 14, 11, 13])
def test_reserved_key_is_visible_capturable_but_has_no_default_action(index):
    pad = A0Keypad(matrix_keys())
    (press,) = settle(pad, {index}, 0)
    assert pad.update({index}, 5) == []
    (released,) = settle(pad, set(), 6)
    manager = keyboard_mapping.KeyboardMappingManager()
    # Even an existing USB A/F-key binding must not activate this A0 key.
    commands = queue.Queue()
    cfg = SimpleNamespace(
        get_option=lambda key, default=None: {"mount_left": f"KEY_{press['code']}"}
        if key == "keyboard_mapping"
        else True
    )
    manager.start(queue.Queue(), commands, cfg)
    assert manager.handle_event(press) is None
    assert manager.handle_event(released) is None
    assert commands.empty()
    assert manager.last_key == press["key_id"]
    assert "reserved" in keyboard_mapping.key_label(manager.last_key)
    assert keyboard_mapping.is_assignable_key(manager.last_key)
    manager.start_capture()
    assert manager.handle_event(press) is None
    assert manager.take_captured() == press["key_id"]
    assert manager.handle_event(released) is None
    manager._dispatcher.set_mapping({"mount_left": press["key_id"]})
    manager.handle_event(press)
    manager.tick()
    manager.handle_event(released)
    assert commands.get_nowait()["type"] == "manual_movement"
    assert commands.get_nowait() == {"type": "stop_movement"}


@pytest.mark.parametrize(
    "index,keycode", [(9, K.LNG_LEFT), (5, K.LNG_RIGHT), (18, K.LNG_SQUARE)]
)
def test_long_press_is_sent_once_and_does_not_create_a_new_press(index, keycode):
    pad = A0Keypad(matrix_keys())
    settle(pad, {index}, 0)
    (event,) = pad.update({index}, 1.1)
    assert event["keycode"] == keycode
    assert event["repeat"]
    assert pad.update({index}, 3) == []
    (released,) = settle(pad, set(), 4)
    assert not released["pressed"]
    assert released["keycode"] == 0
    assert len(settle(pad, {index}, 5)) == 1


def test_arrow_repeat_does_not_duplicate_action_on_release():
    pad = A0Keypad(matrix_keys())
    settle(pad, {1}, 0)
    (first,) = pad.update({1}, 1.1)
    assert first["keycode"] == K.DOWN
    assert pad.update({1}, 1.12) == []
    (second,) = pad.update({1}, 1.2)
    assert second["repeat"]
    assert settle(pad, set(), 2)[0]["keycode"] == 0


def test_number_hold_keeps_single_press_and_a_real_release():
    pad = A0Keypad(matrix_keys())
    (press,) = settle(pad, {0}, 0)
    assert press["keycode"] == K.number_press_key(2)
    assert pad.update({0}, 4) == []
    assert settle(pad, set(), 5)[0]["keycode"] == K.number_release_key(2)


@pytest.mark.parametrize(
    "index,alt",
    [
        (17, K.ALT_UP),
        (1, K.ALT_DOWN),
        (9, K.ALT_LEFT),
        (5, K.ALT_RIGHT),
        (2, K.ALT_0),
        (3, K.ALT_MINUS),
        (7, K.ALT_PLUS),
    ],
)
def test_square_chord_uses_a0_square_and_suppresses_plain_actions(index, alt):
    pad = A0Keypad(matrix_keys())
    presses = settle(pad, {18, index}, 0)
    assert all(event["keycode"] == 0 for event in presses)
    assert pad.update({18, index}, 3) == []
    releases = settle(pad, set(), 4)
    assert [event["keycode"] for event in releases] == [alt, 0]
    assert len(releases) == 2


def test_square_after_number_press_does_not_lose_number_release():
    pad = A0Keypad(matrix_keys())
    settle(pad, {2}, 0)
    settle(pad, {2, 18}, 0.1)
    assert settle(pad, {18}, 0.2)[0]["keycode"] == K.number_release_key(0)


@pytest.mark.parametrize("allow_left", [False, True])
def test_a0_left_exits_capture_and_test_and_navigation_cannot_be_rebound(allow_left):
    manager = keyboard_mapping.KeyboardMappingManager()
    manager.start_capture(allow_left=allow_left)
    press, released = tap(9)
    assert manager.handle_event(press) is None
    assert manager.handle_event(released) == K.LEFT
    assert manager.take_captured() is None
    for name in ("SW2_LEFT", "SW2_RIGHT", "SW2_UP", "SW2_DOWN", "SW7"):
        assert not keyboard_mapping.is_assignable_key(KEYS[name].identifier)


def test_zero_survives_manager_and_reserved_center_cannot_acknowledge_as_enter():
    manager = keyboard_mapping.KeyboardMappingManager()
    assert [manager.handle_event(e) for e in tap(2)] == [
        K.number_press_key(0),
        K.number_release_key(0),
    ]
    assert manager.error_dialog_key(tap(13)[0]) is None
    assert manager.error_dialog_key(tap(18)[0]) == K.SQUARE


@pytest.fixture
def keyboard_module(monkeypatch):
    gpio = SimpleNamespace(BCM=11, IN=1, OUT=0, LOW=0, PUD_UP=22)
    monkeypatch.setitem(sys.modules, "RPi", SimpleNamespace(GPIO=gpio))
    monkeypatch.setitem(sys.modules, "RPi.GPIO", gpio)
    monkeypatch.setitem(
        sys.modules,
        "libinput",
        SimpleNamespace(
            LibInput=lambda **kw: SimpleNamespace(assign_seat=lambda seat: None),
            ContextType=SimpleNamespace(UDEV=0),
        ),
    )
    path = Path(__file__).parents[1] / "MFNavis" / "keyboard_pi.py"
    spec = importlib.util.spec_from_file_location("keyboard_pi_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_mapping_preserved_and_a0_selected_only_by_detected_mode(
    keyboard_module,
):
    legacy = keyboard_module.KeyboardPi(queue.Queue())
    assert legacy.board_mode == LEGACY_MODE
    assert legacy.a0_keypad is None
    assert legacy.keymap == [
        7,
        8,
        9,
        K.NA,
        4,
        5,
        6,
        K.PLUS,
        1,
        2,
        3,
        K.MINUS,
        K.NA,
        0,
        K.NA,
        K.SQUARE,
        K.LEFT,
        K.UP,
        K.DOWN,
        K.RIGHT,
    ]
    a0 = keyboard_module.KeyboardPi(queue.Queue(), A0_MODE)
    assert a0.a0_keypad.keys == matrix_keys()
    assert a0.rows == [19, 17, 18, 22, 20]
    assert a0.cols == [16, 23, 26, 27]
    assert a0.physical_key_mapping == legacy.physical_key_mapping


def test_gpio_scan_returns_full_matrix_and_releases_rows(keyboard_module):
    keyboard = keyboard_module.KeyboardPi(queue.Queue(), A0_MODE)
    active = set()

    def setup(pin, direction, **kwargs):
        if direction == keyboard_module.GPIO.OUT:
            assert not active
            active.add(pin)
        else:
            active.discard(pin)

    keyboard_module.GPIO.setup = setup
    keyboard_module.GPIO.input = (
        lambda pin: 0 if (next(iter(active)), pin) in {(22, 16), (20, 26)} else 1
    )
    assert keyboard._scan_matrix() == {12, 18}
    assert not active
