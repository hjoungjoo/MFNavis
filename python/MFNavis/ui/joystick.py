#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Joystick button mapping UI (Settings > Advanced > Joystick).

Lists the mappable actions with their assigned buttons; selecting one enters
capture mode, where the next joystick button pressed becomes the binding. A
"Test Buttons" entry shows live button ids so the user can see what a
connected controller actually sends. Bindings persist in config under
``joystick_mapping`` ({action: button_id}); the reader thread
(PiFinder.joystick_input) reloads them on save.
"""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

from PiFinder import joystick_input
from PiFinder.ui.text_menu import UITextMenu

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


CAPTURE_TIMEOUT = 15.0


class UIJoystick(UITextMenu):
    """
    Map joystick/gamepad buttons to PiFinder actions.
    """

    __title__ = "Joystick"

    def __init__(self, *args, **kwargs):
        self.manager = joystick_input.manager()
        # "menu" | "capture" | "test"
        self.mode = "menu"
        self.capture_action: str | None = None
        self.capture_until = 0.0
        # The menu items show the current bindings, so the definition needs
        # config before UIModule.__init__ has stored it on self.
        self._config = kwargs.get("config_object")
        kwargs["item_definition"] = self._create_menu_definition()
        super().__init__(*args, **kwargs)

    def _mapping(self) -> dict[str, str]:
        config = self._config or getattr(self, "config_object", None)
        if config is None:
            return {}
        mapping = config.get_option(joystick_input.CONFIG_KEY) or {}
        return {str(k): str(v) for k, v in mapping.items()}

    def _create_menu_definition(self):
        mapping = self._mapping()
        items = [{"name": _("Test Buttons"), "value": "__test__"}]
        for action, label in joystick_input.ACTIONS:
            button = mapping.get(action, "")
            display = self._short_button(button) if button else "-"
            items.append({"name": f"{label}: {display}", "value": action})
        items.append({"name": _("Clear All"), "value": "__clear__"})
        return {"name": _("Joystick"), "select": "single", "items": items}

    def _short_button(self, button: str) -> str:
        # "BTN_SOUTH" -> "SOUTH", "HAT0X-" stays as is.
        return button[4:] if button.startswith("BTN_") else button

    def _rebuild_menu(self):
        self.item_definition = self._create_menu_definition()
        self._menu_items = [x["name"] for x in self.item_definition["items"]]
        if self._current_item_index >= len(self._menu_items):
            self._current_item_index = max(0, len(self._menu_items) - 1)

    def _action_label(self, action: str) -> str:
        for candidate, label in joystick_input.ACTIONS:
            if candidate == action:
                return label
        return action

    def _save_binding(self, action: str, button: str):
        mapping = self._mapping()
        # One binding per button: assigning a button steals it from any other
        # action, otherwise one press would fire twice.
        for existing_action in list(mapping):
            if mapping[existing_action] == button:
                del mapping[existing_action]
        mapping[action] = button
        self.config_object.set_option(joystick_input.CONFIG_KEY, mapping)
        self.manager.reload_mapping()

    def _draw_lines(self, lines: list[str]):
        self.clear_screen()
        draw_y = self.display_class.titlebar_height + 2
        max_chars = max(4, (self.display_class.resX - 4) // self.fonts.base.width)
        for line in lines:
            if draw_y > self.display_class.resY - self.fonts.base.height:
                break
            if len(line) > max_chars:
                line = line[: max_chars - 3] + "..."
            self.draw.text(
                (2, draw_y), line, font=self.fonts.base.font, fill=self.colors.get(192)
            )
            draw_y += self.fonts.base.height + 2

    def _draw_capture(self):
        captured = self.manager.take_captured()
        if captured is not None and self.capture_action is not None:
            self._save_binding(self.capture_action, captured)
            self.mode = "menu"
            self.capture_action = None
            self._rebuild_menu()
            self.message(self._short_button(captured), 1)
            return self.update(force=True)
        if time.monotonic() > self.capture_until:
            self.manager.cancel_capture()
            self.mode = "menu"
            self.capture_action = None
            return self.update(force=True)

        lines = [
            self._action_label(self.capture_action or ""),
            _("Press a button"),
            "",
            _("Left cancels"),
        ]
        if not self.manager.device_names:
            lines.append(_("No joystick found"))
        if not self.manager.supported:
            lines.append("evdev missing")
        self._draw_lines(lines)
        return self.screen_update()

    def _draw_test(self):
        lines = [_("Press buttons")]
        if self.manager.last_button and time.time() - self.manager.last_button_at < 10:
            lines.extend(["", self.manager.last_button])
            # The kernel event code: distinct buttons can share a name (or a
            # name can hide the fact that two buttons send the same code), and
            # only the number tells them apart.
            if self.manager.last_button_code is not None:
                lines.append(f"code {self.manager.last_button_code}")
        if self.manager.device_names:
            lines.append("")
            lines.extend(self.manager.device_names[:2])
        else:
            lines.extend(["", _("No joystick found")])
        if not self.manager.supported:
            lines.append("evdev missing")
        lines.append(_("Left exits"))
        self._draw_lines(lines)
        return self.screen_update()

    def update(self, force=False):
        if self.mode == "capture":
            return self._draw_capture()
        if self.mode == "test":
            return self._draw_test()
        return super().update(force)

    def key_right(self):
        if self.mode != "menu":
            return
        selected = self.item_definition["items"][self._current_item_index]
        value = selected.get("value")
        if value == "__test__":
            self.mode = "test"
            # Capture mode also suppresses dispatch, so testing buttons does
            # not trigger their currently mapped actions.
            self.manager.start_capture()
            return
        if value == "__clear__":
            self.config_object.set_option(joystick_input.CONFIG_KEY, {})
            self.manager.reload_mapping()
            self._rebuild_menu()
            self.message(_("Cleared"), 1)
            return
        if value:
            self.capture_action = str(value)
            self.capture_until = time.monotonic() + CAPTURE_TIMEOUT
            self.mode = "capture"
            self.manager.start_capture()

    def key_left(self) -> bool:
        if self.mode == "capture":
            self.manager.cancel_capture()
            self.mode = "menu"
            self.capture_action = None
            return False
        if self.mode == "test":
            self.manager.cancel_capture()
            self.mode = "menu"
            return False
        return True

    def key_up(self):
        if self.mode != "menu":
            return
        super().key_up()

    def key_down(self):
        if self.mode != "menu":
            return
        super().key_down()

    def inactive(self):
        self.manager.cancel_capture()
        super().inactive()
