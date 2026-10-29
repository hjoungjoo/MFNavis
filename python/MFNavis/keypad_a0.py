"""MFNavis_A0 matrix events, independent of GPIO and the legacy keypad.

Each switch has its own identity so USB keyboard bindings cannot accidentally
assign a function to a reserved A0 key. Defaults remain separate from bindings.
"""

from __future__ import annotations

from dataclasses import dataclass

from PiFinder.keyboard_interface import KeyboardInterface as K


@dataclass(frozen=True)
class Key:
    identifier: str
    label: str
    code: int
    number: int | None = None
    release: int = 0
    alt: int = 0
    long: int = 0
    repeat: bool = False


KEYS = {
    "SW1_UP": Key("A0_SW1_UP", "SW1 Up: 8", 9, number=8),
    "SW1_DOWN": Key("A0_SW1_DOWN", "SW1 Down: 2", 3, number=2),
    "SW1_LEFT": Key("A0_SW1_LEFT", "SW1 Left: 4", 5, number=4),
    "SW1_RIGHT": Key("A0_SW1_RIGHT", "SW1 Right: 6", 7, number=6),
    "SW1_CENTER": Key("A0_SW1_CENTER", "SW1 Center: 5", 6, number=5),
    "SW2_UP": Key("A0_SW2_UP", "SW2 Up", 103, release=K.UP, alt=K.ALT_UP, repeat=True),
    "SW2_DOWN": Key(
        "A0_SW2_DOWN", "SW2 Down", 108, release=K.DOWN, alt=K.ALT_DOWN, repeat=True
    ),
    "SW2_LEFT": Key(
        "A0_SW2_LEFT", "SW2 Left", 105, release=K.LEFT, alt=K.ALT_LEFT, long=K.LNG_LEFT
    ),
    "SW2_RIGHT": Key(
        "A0_SW2_RIGHT",
        "SW2 Right",
        106,
        release=K.RIGHT,
        alt=K.ALT_RIGHT,
        long=K.LNG_RIGHT,
    ),
    # BTN_0 is a raw identity only; the center has no Enter/UI default.
    "SW2_CENTER": Key("A0_SW2_CENTER", "SW2 Center (reserved)", 256),
    "SW3": Key("A0_SW3", "SW3: 0", 11, number=0, alt=K.ALT_0),
    "SW4": Key("A0_SW4", "SW4: F3 (reserved)", 61),
    "SW5": Key("A0_SW5", "SW5: F2 (reserved)", 60),
    "SW6": Key("A0_SW6", "SW6: F1 (reserved)", 59),
    "SW7": Key("A0_SW7", "SW7: Square", 28, release=K.SQUARE, long=K.LNG_SQUARE),
    "SW8": Key("A0_SW8", "SW8: -", 74, release=K.MINUS, alt=K.ALT_MINUS),
    "SW9": Key("A0_SW9", "SW9: +", 78, release=K.PLUS, alt=K.ALT_PLUS),
    "SW10": Key("A0_SW10", "SW10: A (reserved)", 30),
}
NAVIGATION_IDS = frozenset(
    KEYS[name].identifier
    for name in ("SW2_UP", "SW2_DOWN", "SW2_LEFT", "SW2_RIGHT", "SW7")
)
LEFT_ID = KEYS["SW2_LEFT"].identifier
KEY_LABELS = {key.identifier: key.label for key in KEYS.values()}
SQUARE = 18  # ROW4 / COL2 (SW7), not the legacy keypad's index 15.
# Measured on the assembled A0 board: D=up, C=left, E=right, A=center, B=down.
JOYSTICK_ROWS = {"UP": 4, "LEFT": 2, "RIGHT": 1, "CENTER": 3, "DOWN": 0}


def matrix_keys(joystick_rows: dict[str, int] = JOYSTICK_ROWS) -> dict[int, Key]:
    """Build the schematic's row-major 5 x 4 matrix from joystick directions."""
    if set(joystick_rows) != {"UP", "DOWN", "LEFT", "RIGHT", "CENTER"} or set(
        joystick_rows.values()
    ) != set(range(5)):
        raise ValueError("Joystick directions must identify each of the five rows")
    result = {row * 4 + 2: KEYS[f"SW{row + 3}"] for row in range(5)}
    result.update({row * 4 + 3: KEYS[f"SW{row + 8}"] for row in range(3)})
    for direction, row in joystick_rows.items():
        for col in (0, 1):
            result[row * 4 + col] = KEYS[f"SW{col + 1}_{direction}"]
    return result


class A0Keypad:
    DEBOUNCE_SECONDS = 0.025
    HOLD_SECONDS = 1.0
    REPEAT_SECONDS = 0.08

    def __init__(self, keys: dict[int, Key]):
        self.keys = keys
        self._candidates: set[int] = set()
        self._changed: dict[int, float] = {}
        self._pressed: dict[int, float] = {}
        self._alt: set[int] = set()
        self._held: set[int] = set()
        self._repeated: dict[int, float] = {}
        self._square_used = False

    def _event(self, index: int, pressed: bool, keycode=0, *, repeat=False) -> dict:
        # Keep the existing event protocol and remapping UI, with A0 identities.
        from PiFinder.keyboard_mapping import make_event

        key = self.keys[index]
        event = make_event(key.code, pressed, keycode, repeat=repeat)
        event.update(key_id=key.identifier, source="MFNavis_A0", matrix_index=index)
        return event

    def update(self, raw: set[int], now: float) -> list[dict]:
        """Consume one complete scan; debounce edges and retain true releases."""
        raw = raw.intersection(self.keys)
        for index in raw ^ self._candidates:
            self._changed[index] = now
        self._candidates = set(raw)
        stable = {
            index
            for index in self.keys
            if now - self._changed.get(index, now) >= self.DEBOUNCE_SECONDS
        }
        released = (self._pressed.keys() - raw) & stable
        added = (raw - self._pressed.keys()) & stable
        events = []
        # Other keys release before Square so simultaneous release preserves
        # a chord. Square presses first, independent of matrix scan order.
        for index in sorted(released, key=lambda i: i == SQUARE):
            key = self.keys[index]
            if index in self._alt:
                keycode = key.alt
            elif index in self._held or (index == SQUARE and self._square_used):
                keycode = 0
            elif key.number is not None:
                keycode = K.number_release_key(key.number)
            else:
                keycode = key.release
            events.append(self._event(index, False, keycode))
            del self._pressed[index]
            self._alt.discard(index)
            self._held.discard(index)
            self._repeated.pop(index, None)
        for index in sorted(added, key=lambda i: i != SQUARE):
            key = self.keys[index]
            self._pressed[index] = now
            if index == SQUARE:
                self._square_used = False
            if SQUARE in self._pressed and key.alt:
                self._alt.add(index)
                self._square_used = True
            keycode = (
                K.number_press_key(key.number)
                if key.number is not None and index not in self._alt
                else 0
            )
            events.append(self._event(index, True, keycode))
        for index, started in self._pressed.items():
            key = self.keys[index]
            if (
                index not in raw
                or index in self._alt
                or now - started < self.HOLD_SECONDS
                or (index == SQUARE and self._square_used)
            ):
                continue
            if (
                key.repeat
                and now - self._repeated.get(index, started) >= self.REPEAT_SECONDS
            ):
                events.append(self._event(index, True, key.release, repeat=True))
                self._repeated[index] = now
                self._held.add(index)
            elif key.long and index not in self._held:
                events.append(self._event(index, True, key.long, repeat=True))
                self._held.add(index)
        return events
