"""Persistent error overlay; acknowledgement does not retry a mount operation."""

import textwrap

from PiFinder.ui.base import UIModule


class UIOperationError(UIModule):
    __title__ = "ERROR"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.errors = []
        self.offset = 0
        self.lines = []

    def add_error(self, error):
        entry = {
            key: str(error.get(key) or "") for key in ("source", "code", "message")
        }
        if entry in self.errors:
            return
        self.errors = (self.errors + [entry])[-10:]
        self.offset = 0
        text = "\n\n".join(
            f"{item['source']}\n{item['code'].replace('_', ' ')}\n{item['message']}"
            for item in reversed(self.errors)
        )
        self.lines = [
            line
            for paragraph in text.splitlines()
            for line in (
                textwrap.wrap(paragraph, width=self.fonts.base.line_length - 1) or [""]
            )
        ]

    @property
    def visible_lines(self):
        return max(
            1,
            (
                self.display_class.resY
                - self.display_class.titlebar_height
                - 2 * self.fonts.base.height
            )
            // self.fonts.base.height,
        )

    def key_up(self):
        self.offset = max(0, self.offset - 1)

    def key_down(self):
        self.offset = min(max(0, len(self.lines) - self.visible_lines), self.offset + 1)

    def update(self):
        self.clear_screen()
        fg = self.colors.get(255)
        self.draw.text((2, 0), _("ERROR"), font=self.fonts.bold.font, fill=fg)
        y = self.display_class.titlebar_height
        for line in self.lines[self.offset : self.offset + self.visible_lines]:
            self.draw.text((2, y), line, font=self.fonts.base.font, fill=fg)
            y += self.fonts.base.height
        y = self.display_class.resY - 2 * self.fonts.base.height
        self.draw.text((2, y), _("Up/Down: scroll"), font=self.fonts.base.font, fill=fg)
        self.draw.text(
            (2, y + self.fonts.base.height),
            _("Right: back"),
            font=self.fonts.base.font,
            fill=fg,
        )

    def serialize_ui_state(self):
        return {
            "ui_type": "UIOperationError",
            "title": "ERROR",
            "errors": self.errors,
            "scroll_offset": self.offset,
        }
