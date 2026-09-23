#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Physical keyboard mapping UI (Settings > Advanced > Keyboard)."""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

from PiFinder import keyboard_mapping
from PiFinder.ui.text_menu import UITextMenu

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


CAPTURE_TIMEOUT = 15.0


class UIKeyboardMapping(UITextMenu):
    __title__ = "Keyboard"

    def __init__(self, *args, **kwargs):
        self.manager = keyboard_mapping.manager()
        self.mode = "menu"
        self.capture_action: str | None = None
        self.capture_until = 0.0
        self._config = kwargs.get("config_object")
        kwargs["item_definition"] = self._create_menu_definition()
        super().__init__(*args, **kwargs)

    def _mapping(self) -> dict[str, str]:
        config = self._config or getattr(self, "config_object", None)
        if config is None:
            return {}
        mapping = config.get_option(keyboard_mapping.CONFIG_KEY) or {}
        return {
            str(k): str(v)
            for k, v in mapping.items()
            if keyboard_mapping.is_assignable_key(str(v))
        }

    def _create_menu_definition(self):
        mapping = self._mapping()
        items = [{"name": _("Test Keys"), "value": "__test__"}]
        for action, label in keyboard_mapping.ACTIONS:
            identifier = mapping.get(action, "")
            display = keyboard_mapping.key_label(identifier) if identifier else "-"
            items.append({"name": f"{label}: {display}", "value": action})
        items.append({"name": _("Clear All"), "value": "__clear__"})
        return {"name": _("Keyboard"), "select": "single", "items": items}

    def _rebuild_menu(self):
        self.item_definition = self._create_menu_definition()
        self._menu_items = [x["name"] for x in self.item_definition["items"]]
        if self._current_item_index >= len(self._menu_items):
            self._current_item_index = max(0, len(self._menu_items) - 1)

    def _action_label(self, action: str) -> str:
        for candidate, label in keyboard_mapping.ACTIONS:
            if candidate == action:
                return label
        return action

    def _save_binding(self, action: str, identifier: str):
        if not keyboard_mapping.is_assignable_key(identifier):
            return False
        mapping = self._mapping()
        for existing_action in list(mapping):
            if mapping[existing_action] == identifier:
                del mapping[existing_action]
        mapping[action] = identifier
        self.config_object.set_option(keyboard_mapping.CONFIG_KEY, mapping)
        self.manager.reload_mapping()
        return True

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
            if not self._save_binding(self.capture_action, captured):
                self.mode = "menu"
                self.capture_action = None
                self._rebuild_menu()
                self.message(_("Arrow/Enter unavailable"), 1)
                return self.update(force=True)
            self.mode = "menu"
            self.capture_action = None
            self._rebuild_menu()
            self.message(keyboard_mapping.key_label(captured), 1)
            return self.update(force=True)
        if time.monotonic() > self.capture_until:
            self.manager.cancel_capture()
            self.mode = "menu"
            self.capture_action = None
            return self.update(force=True)

        self._draw_lines(
            [
                self._action_label(self.capture_action or ""),
                _("Press a key"),
                "",
                _("Keypad Left cancels"),
            ]
        )
        return self.screen_update()

    def _draw_test(self):
        lines = [_("Press keyboard keys")]
        if self.manager.last_key and time.time() - self.manager.last_key_at < 10:
            lines.extend(["", keyboard_mapping.key_label(self.manager.last_key)])
            if self.manager.last_key_code is not None:
                lines.append(f"code {self.manager.last_key_code}")
        lines.append(_("Keypad Left exits"))
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
            # Keyboard Left remains a real UI Left key in test mode so it can
            # return to this menu, while all other keys are only displayed.
            self.manager.start_capture(allow_left=True)
            return
        if value == "__clear__":
            self.config_object.set_option(keyboard_mapping.CONFIG_KEY, {})
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
        if self.mode in {"capture", "test"}:
            self.manager.cancel_capture()
            self.mode = "menu"
            self.capture_action = None
            return False
        return True

    def key_up(self):
        if self.mode == "menu":
            super().key_up()

    def key_down(self):
        if self.mode == "menu":
            super().key_down()

    def inactive(self):
        self.manager.cancel_capture()
        super().inactive()
