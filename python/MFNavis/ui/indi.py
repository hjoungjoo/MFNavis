#!/usr/bin/python
# -*- coding:utf-8 -*-

import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from PIL import ImageChops

from PiFinder import utils
from PiFinder.branding import product_label
from PiFinder.indi_align import (
    BRIGHT_ALIGN_STARS,
    align_star_altaz,
    alignment_altitude_limits,
    clamp_align_points,
    visible_align_stars,
)
from PiFinder.ui.base import GuideKeyMixin, UIModule
from PiFinder.ui.camera_render import resize_for_display


if TYPE_CHECKING:

    def _(a) -> Any:
        return a


STATUS_FILE = utils.runtime_dir / "mount_control_status.json"

SLEW_STEPS = [
    "Off",
    "1/2x",
    "1x",
    "2x",
    "4x",
    "8x",
    "20x",
    "48x",
    "1/2 Max",
    "Max",
]
MANUAL_MOTION_KEEPALIVE_INTERVAL = 0.4
MANUAL_MOTION_LEASE_SECONDS = 1.2
# The mount process refuses to extend one manual_movement past its 10 s
# continuous-hold cap on keepalives alone; re-send the full manual_movement to
# keep a held key moving (same contract as ui/base.py's guide keys).
MANUAL_MOTION_RESTART_INTERVAL = 8.0


class UIIndiBase(UIModule):
    def _mount_queue(self):
        if not self.config_object.get_option("mount_control", False):
            return None
        return self.command_queues.get("mountcontrol")

    def _send_mount(self, command):
        mount_queue = self._mount_queue()
        if mount_queue is None:
            self.message(_("Mount Control Off"), 1)
            return False
        mount_queue.put(command)
        return True

    def _status(self):
        try:
            with open(STATUS_FILE, encoding="utf-8") as status_in:
                return json.load(status_in)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"state": "unknown", "message": _("No status")}

    def _current_pointing_radec(self):
        solution = self.shared_state.solution()
        if not solution or not solution.has_pointing():
            return None
        aligned = solution.pointing.aligned.estimate
        if aligned is None:
            return None
        return aligned.RA, aligned.Dec

    def _draw_text(self, xy, text, font=None, fill=None):
        self.draw.text(
            xy,
            text,
            font=font or self.fonts.bold.font,
            fill=fill or self.colors.get(255),
        )


class UIIndiInit(UIIndiBase):
    __title__ = "INDI INIT"

    def update(self, force=False):
        self.clear_screen()
        status = self._status()
        y = self.display_class.titlebar_height + 6
        line_h = max(12, self.fonts.bold.height + 2)

        state = status.get("state", "unknown")
        message = status.get("message", "")
        slew_rate = status.get("slew_rate")
        ra = status.get("ra")
        dec = status.get("dec")

        self._draw_text((6, y), _("State: {state}").format(state=state))
        y += line_h
        if message:
            self._draw_text((6, y), str(message)[:24], fill=self.colors.get(160))
            y += line_h
        if slew_rate is not None:
            rate = int(slew_rate)
            label = SLEW_STEPS[rate] if 0 <= rate < len(SLEW_STEPS) else ""
            self._draw_text(
                (6, y), _("Speed: {rate} {label}").format(rate=rate, label=label)
            )
            y += line_h
        if ra is not None and dec is not None:
            self._draw_text(
                (6, y),
                _("RA {ra:.1f} Dec {dec:.1f}").format(ra=float(ra), dec=float(dec)),
                fill=self.colors.get(160),
            )
            y += line_h

        location = self.shared_state.location()
        if location and getattr(location, "lock", False):
            loc_text = _("Loc: {lat:.4f},{lon:.4f}").format(
                lat=float(location.lat), lon=float(location.lon)
            )
        else:
            loc_text = _("Loc: default/GPS none")
        self._draw_text((6, y), loc_text[:28])
        y += line_h

        hint_font = self.fonts.small.font
        hint_line_h = max(10, self.fonts.small.height + 2)
        hints = [
            _("1 Init   2 Time"),
            _("3 Park   6 Unpark"),
            _("4 Home   5 Return"),
            _("7 SetPark"),
            _("8 Restart 9 Reboot"),
        ]
        hint_y = max(y + 4, self.display_class.resY - (len(hints) * hint_line_h) - 2)
        for hint in hints:
            self._draw_text(
                (6, hint_y), hint, font=hint_font, fill=self.colors.get(128)
            )
            hint_y += hint_line_h

        return self.screen_update()

    def key_number(self, number):
        if number == 1:
            if self._send_mount({"type": "init"}):
                self.message(_("INDI Init"), 1)
        elif number == 2:
            if self._send_mount({"type": "sync_location_time"}):
                self.message(_("Time/Location"), 1)
        elif number == 3:
            if self._send_mount({"type": "park_action", "action": "park"}):
                self.message(_("Park"), 1)
        elif number == 4:
            if self._send_mount({"type": "park_action", "action": "set_home"}):
                self.message(_("Set Home"), 1)
        elif number == 5:
            if self._send_mount({"type": "park_action", "action": "return_home"}):
                self.message(_("Return Home"), 1)
        elif number == 6:
            if self._send_mount({"type": "park_action", "action": "unpark"}):
                self.message(_("Unpark"), 1)
        elif number == 7:
            if self._send_mount({"type": "park_action", "action": "set_park"}):
                self.message(_("Set-Park"), 1)
        elif number == 8:
            if self._send_mount({"type": "restart_driver"}):
                self.message(_("INDI Restart"), 1)
        elif number == 9:
            if self._send_mount({"type": "reboot_mount"}):
                self.message(_("Mount Reboot"), 1)

    def key_square(self):
        self.key_number(1)


class UIIndiStatus(GuideKeyMixin, UIIndiBase):
    __title__ = "INDI STATUS"

    def _format_age(self, updated):
        if not updated:
            return "--"
        age = max(0.0, time.time() - float(updated))
        if age < 60:
            return f"{age:.0f}s ago"
        return f"{age / 60:.1f}m ago"

    def _format_float(self, value, places=2):
        if value is None:
            return "--"
        return f"{float(value):.{places}f}"

    def update(self, force=False):
        self.clear_screen()
        status = self._status()
        y = self.display_class.titlebar_height + 4
        line_h = max(10, self.fonts.small.height + 2)
        font = self.fonts.small.font

        rows = [
            ("State", status.get("state", "unknown")),
            ("Msg", status.get("message", "--")),
            ("Age", self._format_age(status.get("updated"))),
            ("Device", status.get("device", "--")),
            ("Home", status.get("home_state", "--")),
            ("Park", status.get("park_state", "--")),
            ("Raw", status.get("raw_mount_status", "--")),
            ("RA", self._format_float(status.get("ra"), 2)),
            ("Dec", self._format_float(status.get("dec"), 2)),
            ("Speed", status.get("slew_rate", "--")),
        ]
        if status.get("target_ra") is not None or status.get("target_dec") is not None:
            rows.extend(
                [
                    ("Tgt RA", self._format_float(status.get("target_ra"), 2)),
                    ("Tgt Dec", self._format_float(status.get("target_dec"), 2)),
                ]
            )

        key_w = 7
        max_chars = max(8, self.display_class.resX // self.fonts.small.width)
        for key, value in rows:
            if y + line_h > self.display_class.resY:
                break
            text = f"{key:<{key_w}} {value}"
            self.draw.text(
                (4, y),
                str(text)[:max_chars],
                font=font,
                fill=self.colors.get(192),
            )
            y += line_h

        return self.screen_update()


class UIIndiBacklash(UIIndiBase):
    __title__ = "INDI BACKLASH"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.selected_axis = "ra"
        self.inputs = {"ra": "", "de": ""}

    def active(self):
        self._send_mount({"type": "refresh_backlash"})

    def _status_value(self, axis):
        status = self._status()
        value = status.get(f"backlash_{axis}")
        if value is None:
            return "--"
        return str(value)

    def _input_value(self, axis):
        if self.inputs[axis] != "":
            return self.inputs[axis]
        current = self._status_value(axis)
        return "" if current == "--" else current

    def _draw_row(self, y, axis, label):
        selected = axis == self.selected_axis
        marker = ">" if selected else " "
        value = self._input_value(axis) or "--"
        current = self._status_value(axis)
        fill = self.colors.get(255 if selected else 160)
        self._draw_text(
            (4, y),
            f"{marker}{label} in:{value:<3} cur:{current:<3}"[:28],
            font=self.fonts.small.font,
            fill=fill,
        )

    def update(self, force=False):
        self.clear_screen()
        status = self._status()
        y = self.display_class.titlebar_height + 4
        line_h = max(10, self.fonts.small.height + 2)

        self._draw_row(y, "ra", "RA")
        y += line_h
        self._draw_row(y, "de", "DE")
        y += line_h

        auto = status.get("backlash_auto", {})
        auto_message = auto.get("message") or status.get("message") or _("Idle")
        self._draw_text(
            (4, y),
            str(auto_message)[:28],
            font=self.fonts.small.font,
            fill=self.colors.get(128),
        )
        y += line_h
        if auto.get("axis"):
            self._draw_text(
                (4, y),
                _("Axis: {axis}").format(axis=auto.get("axis")),
                font=self.fonts.small.font,
                fill=self.colors.get(128),
            )

        hints = [
            _("+ RA  - DE"),
            _("Digits input  0 clear"),
            _("Right Auto  Square Save"),
        ]
        hint_y = self.display_class.resY - (len(hints) * line_h) - 2
        for hint in hints:
            self._draw_text(
                (4, hint_y),
                hint[:28],
                font=self.fonts.small.font,
                fill=self.colors.get(128),
            )
            hint_y += line_h

        return self.screen_update()

    def _select_axis(self, axis):
        if self.selected_axis != axis:
            self.selected_axis = axis
            self.update()

    def key_plus(self):
        # Distinct from key_minus: + selects the RA axis, - selects DE.
        self._select_axis("ra")

    def key_minus(self):
        self._select_axis("de")

    def key_number(self, number):
        axis = self.selected_axis
        if number == 0:
            self.inputs[axis] = ""
        elif len(self.inputs[axis]) < 3:
            candidate = f"{self.inputs[axis]}{number}"
            if 0 <= int(candidate) <= 999:
                self.inputs[axis] = candidate
        self.update()

    def key_right(self):
        if self._send_mount({"type": "auto_backlash", "axis": self.selected_axis}):
            self.message(_("Auto Backlash"), 1)
        return False

    def key_square(self):
        ra_value = self._input_value("ra") or "0"
        de_value = self._input_value("de") or "0"
        if self._send_mount(
            {
                "type": "set_backlash",
                "ra": ra_value,
                "de": de_value,
            }
        ):
            self.message(_("Backlash Saved"), 1)


class UIIndiGuide(UIIndiBase):
    __title__ = "INDI GUIDE"

    # Cardinal-only, matching the unified mount map used by Object Details /
    # status screens. Diagonal jog stays on the keyboard letters (q/e/z/c);
    # 9/3 adjust the slew rate like everywhere else.
    _number_direction = {
        2: "south",
        4: "west",
        6: "east",
        8: "north",
    }
    _text_direction = {
        "z": "southwest",
        "x": "south",
        "c": "southeast",
        "a": "west",
        "s": "stop",
        "d": "east",
        "q": "northwest",
        "w": "north",
        "e": "northeast",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._active_motion_direction = None
        self._next_motion_keepalive_at = 0.0
        self._next_motion_restart_at = 0.0

    def active(self):
        self._active_motion_direction = None
        self._next_motion_keepalive_at = 0.0
        self._next_motion_restart_at = 0.0
        self._send_mount({"type": "refresh_slew_rate"})

    def inactive(self):
        if self._active_motion_direction is not None:
            self._send_mount({"type": "stop_movement"})
        self._active_motion_direction = None
        self._next_motion_keepalive_at = 0.0
        self._next_motion_restart_at = 0.0

    def _send_motion_keepalive(self):
        if self._active_motion_direction is None:
            return

        now = time.monotonic()
        if now >= self._next_motion_restart_at:
            self._next_motion_restart_at = now + MANUAL_MOTION_RESTART_INTERVAL
            self._next_motion_keepalive_at = now + MANUAL_MOTION_KEEPALIVE_INTERVAL
            self._send_mount(
                {
                    "type": "manual_movement",
                    "direction": self._active_motion_direction,
                    "lease_seconds": MANUAL_MOTION_LEASE_SECONDS,
                }
            )
            return
        if now < self._next_motion_keepalive_at:
            return

        self._send_mount(
            {
                "type": "manual_movement_keepalive",
                "direction": self._active_motion_direction,
                "lease_seconds": MANUAL_MOTION_LEASE_SECONDS,
            }
        )
        self._next_motion_keepalive_at = now + MANUAL_MOTION_KEEPALIVE_INTERVAL

    def _draw_camera_background(self):
        try:
            image_obj = self.camera_image.copy()
            image_obj = resize_for_display(
                image_obj,
                (self.display_class.resX, self.display_class.resY),
                0,
            )
            image_obj = image_obj.convert("L").convert("RGB")
            image_obj = ImageChops.multiply(image_obj, self.colors.red_image)
            self.screen.paste(image_obj)
        except Exception:
            self.clear_screen()

    def _draw_keypad_overlay(self):
        status = self._status()
        slew_rate = int(status.get("slew_rate", 5))
        label = SLEW_STEPS[slew_rate] if 0 <= slew_rate < len(SLEW_STEPS) else ""
        font = self.fonts.base.font
        line_h = self.fonts.base.height + 2
        bright = self.colors.get(192)
        shadow = self.colors.get(0)

        def overlay_text(x, y, text, fill=bright):
            self.draw.text((x + 1, y + 1), text, font=font, fill=shadow)
            self.draw.text((x, y), text, font=font, fill=fill)

        bottom_hint_y = max(
            self.display_class.titlebar_height + 1,
            self.display_class.resY - (line_h * 3) - 2,
        )

        overlay_text(4, bottom_hint_y, _("2/4/6/8 : Move"))
        compact_label = label.replace(" ", "")
        overlay_text(
            4,
            bottom_hint_y + line_h,
            _("9/3 : Speed {label}").format(label=compact_label),
        )
        guide_corr = status.get("guide_correction_enabled", False)
        overlay_text(
            4,
            bottom_hint_y + (line_h * 2),
            _("0 : Guide {state}").format(state="On" if guide_corr else "off"),
        )

    def update(self, force=False):
        self._send_motion_keepalive()
        self._draw_camera_background()
        self._draw_keypad_overlay()
        return self.screen_update(title_bar=True, button_hints=False)

    def _move(self, direction):
        if direction == "stop":
            self._active_motion_direction = None
            self._next_motion_keepalive_at = 0.0
            self._next_motion_restart_at = 0.0
            self._send_mount({"type": "stop_movement"})
        else:
            self._active_motion_direction = direction
            now = time.monotonic()
            self._next_motion_keepalive_at = now + MANUAL_MOTION_KEEPALIVE_INTERVAL
            self._next_motion_restart_at = now + MANUAL_MOTION_RESTART_INTERVAL
            self._send_mount(
                {
                    "type": "manual_movement",
                    "direction": direction,
                    "lease_seconds": MANUAL_MOTION_LEASE_SECONDS,
                }
            )
        self.update(force=True)

    def key_number(self, number):
        if number == 0:
            self._send_mount(
                {
                    "type": "toggle_guide_correction",
                    "accuracy_arcmin": self.config_object.get_option(
                        "indi_goto_refine_accuracy_arcmin", 3.0
                    ),
                }
            )
            self.message(_("Guide Correction"), 1)
        elif number == 9:
            self._send_mount({"type": "increase_slew_rate", "notify_ui": True})
        elif number == 3:
            self._send_mount({"type": "reduce_slew_rate", "notify_ui": True})

    def key_number_press(self, number=None):
        if number is None:
            return
        if number in (0, 3, 9):
            self.key_number(number)
            return
        direction = self._number_direction.get(number)
        if direction:
            self._move(direction)

    def key_number_release(self, number=None):
        if number is None:
            return
        if number in (0, 3, 9):
            return
        if number in self._number_direction:
            self._move("stop")

    def _text_speed(self, char: str) -> bool:
        """Slew-rate letters (, and .), matching the 9/3 number keys.

        key_text and key_text_press are mutually exclusive per input source, so
        handling it in both fires exactly once either way.
        """
        command = self._GUIDE_TEXT_SPEED.get(char)
        if command is None:
            return False
        self._send_mount({"type": command, "notify_ui": True})
        return True

    def key_text(self, char: str = ""):
        if not char:
            return
        direction = self._text_direction.get(char.lower())
        if direction == "stop":
            self._move(direction)
        elif direction:
            self._send_mount(
                {
                    "type": "manual_movement",
                    "direction": direction,
                    "lease_seconds": MANUAL_MOTION_LEASE_SECONDS,
                }
            )
            self.update(force=True)
        else:
            self._text_speed(char)

    def key_text_press(self, char: str = ""):
        if not char:
            return
        direction = self._text_direction.get(char.lower())
        if direction:
            self._move(direction)
        else:
            self._text_speed(char)

    def key_text_release(self, char: str = ""):
        if not char:
            return
        if char.lower() in self._text_direction:
            self._move("stop")

    def key_square(self):
        pointing = self._current_pointing_radec()
        if pointing is None:
            self.message(_("No solve"), 1)
            return
        if self._send_mount({"type": "sync", "ra": pointing[0], "dec": pointing[1]}):
            self.message(_("Aligned"), 1)


class UIIndiMultiPointAlign(UIIndiGuide):
    __title__ = "MULTI ALIGN"
    _STAGE_POINTS = "points"
    _STAGE_MODE = "mode"
    _STAGE_PREPARING = "preparing"
    _STAGE_STAR = "star"
    _STAGE_ADJUST = "adjust"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.align_points = 3
        self.align_mode = "manual"
        self.star_index = 0
        self._stage = self._STAGE_POINTS
        self._align_start_requested_at = 0.0

    def active(self):
        self._send_mount(
            {
                "type": "sync_location_time",
                "include_default_location": True,
            }
        )

    def _align_status(self):
        status = self._status()
        align_status = status.get("multipoint_align", {})
        if not isinstance(align_status, dict):
            return {}
        if align_status.get("active"):
            return align_status
        if align_status.get("state") != "complete":
            return align_status
        updated = float(align_status.get("updated") or 0.0)
        if (
            self._stage in {self._STAGE_ADJUST, self._STAGE_STAR, self._STAGE_PREPARING}
            and self._align_start_requested_at > 0.0
            and updated >= self._align_start_requested_at
        ):
            return align_status
        return {}

    def _location_time_context(self):
        try:
            location = self.shared_state.location()
        except Exception:
            return None
        if not location or not getattr(location, "lock", False):
            try:
                default_location = self.config_object.locations.default_location
            except Exception:
                default_location = None
            if not default_location:
                return None
            return (
                float(default_location.latitude),
                float(default_location.longitude),
                float(default_location.height),
                datetime.now(timezone.utc),
            )
        try:
            dt = self.shared_state.datetime()
        except Exception:
            dt = None
        if dt is None:
            dt = datetime.now(timezone.utc)
        return (
            float(location.lat),
            float(location.lon),
            None if location.altitude is None else float(location.altitude),
            dt,
        )

    def _completed_stars(self):
        completed = self._align_status().get("completed", [])
        return completed if isinstance(completed, list) else []

    def _alignment_altitude_limits(self):
        status = self._status()
        return alignment_altitude_limits(
            status.get("alignment_min_altitude"), status.get("alignment_max_altitude")
        )

    def _manual_star_pool(self):
        context = self._location_time_context()
        if context is None:
            return BRIGHT_ALIGN_STARS
        try:
            min_altitude, max_altitude = self._alignment_altitude_limits()
            visible = visible_align_stars(
                context[0],
                context[1],
                context[2],
                context[3],
                completed=self._completed_stars(),
                min_altitude=min_altitude,
                max_altitude=max_altitude,
            )
        except Exception:
            return BRIGHT_ALIGN_STARS
        return visible or BRIGHT_ALIGN_STARS

    def _selected_star(self):
        stars = self._manual_star_pool()
        self.star_index %= len(stars)
        return stars[self.star_index]

    def _star_altitude(self, star):
        if "alt" in star:
            return float(star["alt"])
        context = self._location_time_context()
        if context is None:
            return None
        try:
            alt, _az = align_star_altaz(
                star,
                context[0],
                context[1],
                context[2],
                context[3],
            )
            return alt
        except Exception:
            return None

    def _current_star(self):
        return self._align_status().get("current_star") or {}

    def _is_adjusting(self):
        align_status = self._align_status()
        return bool(align_status.get("active") and align_status.get("current_star"))

    def _has_solved_pointing(self):
        solution = self.shared_state.solution()
        return bool(solution and solution.has_pointing())

    def _current_solved_pointing(self):
        pointing = self._current_pointing_radec()
        if pointing is None:
            return None
        return {"ra": float(pointing[0]) % 360.0, "dec": float(pointing[1])}

    def _complete_or_cancel_to_settings(self, message=None):
        if message:
            self.message(message, 1)
        self._align_start_requested_at = 0.0
        if self.remove_from_stack:
            self.remove_from_stack()

    def _sync_stage_from_status(self):
        align_status = self._align_status()
        state = align_status.get("state")
        if (
            align_status.get("active")
            and align_status.get("current_star")
            and state in {"adjust", "moving"}
        ):
            self._stage = self._STAGE_ADJUST
            return
        if align_status.get("active"):
            if not align_status.get("pifinder_mount_synced") or state == "preparing":
                self._stage = self._STAGE_PREPARING
                return
            if state == "failed":
                self._stage = (
                    self._STAGE_STAR
                    if self.align_mode == "manual"
                    else self._STAGE_MODE
                )
                return
            self._stage = (
                self._STAGE_STAR if self.align_mode == "manual" else self._STAGE_ADJUST
            )
            return
        if align_status.get("state") == "complete" and self._stage in {
            self._STAGE_ADJUST,
            self._STAGE_STAR,
            self._STAGE_PREPARING,
        }:
            self._complete_or_cancel_to_settings(_("Align Complete"))
        if align_status.get("state") in {"failed", "cancelled"} and self._stage in {
            self._STAGE_ADJUST,
            self._STAGE_STAR,
            self._STAGE_PREPARING,
        }:
            self._stage = self._STAGE_MODE

    def _draw_rows(self, rows, hints):
        self.clear_screen()
        y = self.display_class.titlebar_height + 4
        line_h = max(10, self.fonts.small.height + 2)
        font = self.fonts.small.font
        for row in rows:
            if y + line_h > self.display_class.resY:
                break
            self._draw_text(
                (4, y), product_label(row)[:28], font=font, fill=self.colors.get(192)
            )
            y += line_h

        hint_y = self.display_class.resY - (len(hints) * line_h) - 2
        for hint in hints:
            self._draw_text(
                (4, hint_y), hint[:28], font=font, fill=self.colors.get(128)
            )
            hint_y += line_h

    def _draw_setup(self):
        align_status = self._align_status()
        completed = align_status.get("completed_points", 0)
        total = align_status.get("total_points", self.align_points)
        message = align_status.get("message") or _("Idle")
        if self._stage == self._STAGE_POINTS:
            self._draw_rows(
                [
                    _("Align Points"),
                    _("Points: {points}").format(points=self.align_points),
                    _("Progress: {done}/{total}").format(done=completed, total=total),
                    str(message),
                ],
                [
                    _("+/- or 1-9 select"),
                    _("Right/Square next"),
                    _("Left back"),
                ],
            )
            return

        if self._stage == self._STAGE_PREPARING:
            self._draw_rows(
                [
                    _("Preparing Align"),
                    _("Points: {points}").format(points=self.align_points),
                    str(message),
                ],
                [
                    _("Syncing MFNavis"),
                    _("Wait for mount"),
                    _("Left mode/cancel"),
                ],
            )
            return

        if self._stage == self._STAGE_MODE:
            self._draw_rows(
                [
                    _("Align Mode"),
                    _("Mode: {mode}").format(mode=self.align_mode.title()),
                    _("Points: {points}").format(points=self.align_points),
                    str(message),
                ],
                [
                    _("1 Manual  2 Auto"),
                    _("Up/Down change"),
                    _("Right/Square start"),
                    _("Left points"),
                ],
            )
            return

        selected_star = self._selected_star()
        altitude = self._star_altitude(selected_star)
        altitude_text = (
            _("Alt: {alt:.0f} deg").format(alt=altitude)
            if altitude is not None
            else _("Alt: unknown")
        )
        self._draw_rows(
            [
                _("Manual Star"),
                _("Star: {star}").format(star=selected_star["name"]),
                altitude_text,
                _("Point {done}/{total}").format(done=completed + 1, total=total),
                str(message),
            ],
            [
                _("Up/Down star"),
                _("Right/Square GoTo"),
                _("SkySafari GoTo/Align OK"),
                _("Left mode/cancel"),
            ],
        )

    def _draw_align_overlay(self):
        align_status = self._align_status()
        current_star = self._current_star()
        completed = align_status.get("completed_points", 0)
        total = align_status.get("total_points", self.align_points)
        star_name = current_star.get("name") or _("Align Star")
        font = self.fonts.base.font
        small_font = self.fonts.small.font
        line_h = self.fonts.base.height + 2
        small_h = self.fonts.small.height + 2
        bright = self.colors.get(192)
        shadow = self.colors.get(0)

        def overlay_text(x, y, text, use_font=font, fill=bright):
            self.draw.text((x + 1, y + 1), text, font=use_font, fill=shadow)
            self.draw.text((x, y), text, font=use_font, fill=fill)

        top_y = self.display_class.titlebar_height + 2
        overlay_text(4, top_y, str(star_name)[:18])
        overlay_text(
            4,
            top_y + line_h,
            _("Point {done}/{total}").format(done=completed + 1, total=total)[:22],
            use_font=small_font,
        )

        bottom_y = self.display_class.resY - (small_h * 3) - 2
        overlay_text(4, bottom_y, _("8/2/4/6 move  9/3 speed"), use_font=small_font)
        overlay_text(
            4,
            bottom_y + small_h,
            _("Release stop  Left back"),
            use_font=small_font,
        )
        overlay_text(
            4, bottom_y + small_h * 2, _("Square : Confirm"), use_font=small_font
        )

    def update(self, force=False):
        self._sync_stage_from_status()
        if self._stage == self._STAGE_ADJUST and self._is_adjusting():
            self._send_motion_keepalive()
            self._draw_camera_background()
            self._draw_align_overlay()
            return self.screen_update(title_bar=True, button_hints=False)

        self._draw_setup()
        return self.screen_update()

    def key_number(self, number):
        if self._stage == self._STAGE_ADJUST:
            if number == 0:
                self._cancel_and_exit()
            elif number == 9:
                self._send_mount({"type": "increase_slew_rate", "notify_ui": True})
            elif number == 3:
                self._send_mount({"type": "reduce_slew_rate", "notify_ui": True})
            return

        if self._stage == self._STAGE_POINTS and 1 <= number <= 9:
            self.align_points = clamp_align_points(number)
            self.update()
            return

        if self._stage == self._STAGE_MODE:
            if number == 1:
                self.align_mode = "manual"
                self._start_manual()
            elif number == 2:
                self.align_mode = "auto"
                self._start_auto()
            elif number == 0:
                self._cancel_and_exit()
            return

        if self._stage == self._STAGE_STAR and number == 0:
            self._cancel_and_exit()

    def key_number_press(self, number=None):
        if number is None:
            return
        if self._stage == self._STAGE_ADJUST and self._is_adjusting():
            direction = self._number_direction.get(number)
            if direction:
                self._move(direction)
                return
        self.key_number(number)

    def key_number_release(self, number=None):
        if number is None:
            return
        if self._stage == self._STAGE_ADJUST and number in self._number_direction:
            self._move("stop")

    def key_text(self, char: str = ""):
        if self._stage == self._STAGE_ADJUST and self._is_adjusting():
            super().key_text(char)

    def key_text_press(self, char: str = ""):
        if self._stage == self._STAGE_ADJUST and self._is_adjusting():
            super().key_text_press(char)

    def key_text_release(self, char: str = ""):
        if self._stage == self._STAGE_ADJUST and self._is_adjusting():
            super().key_text_release(char)

    def key_plus(self):
        if self._stage != self._STAGE_POINTS:
            return
        self.align_points = clamp_align_points(self.align_points + 1)
        self.update()

    def key_minus(self):
        if self._stage != self._STAGE_POINTS:
            return
        self.align_points = clamp_align_points(self.align_points - 1)
        self.update()

    def key_up(self):
        if self._stage == self._STAGE_MODE:
            self.align_mode = "manual"
            self.update()
        elif self._stage == self._STAGE_STAR:
            self.star_index = (self.star_index - 1) % len(self._manual_star_pool())
            self.update()

    def key_down(self):
        if self._stage == self._STAGE_MODE:
            self.align_mode = "auto"
            self.update()
        elif self._stage == self._STAGE_STAR:
            self.star_index = (self.star_index + 1) % len(self._manual_star_pool())
            self.update()

    def key_left(self):
        if self._stage == self._STAGE_ADJUST:
            self._move("stop")
            if self.align_mode == "manual":
                self._send_mount({"type": "multipoint_align_clear_target"})
                self._stage = self._STAGE_STAR
            else:
                if self._send_mount({"type": "multipoint_align_cancel"}):
                    self.message(_("Align Cancelled"), 1)
                self._stage = self._STAGE_MODE
            self.update()
            return False
        if self._stage == self._STAGE_STAR:
            if self._send_mount({"type": "multipoint_align_cancel"}):
                self.message(_("Align Cancelled"), 1)
            self._stage = self._STAGE_MODE
            self.update()
            return False
        if self._stage == self._STAGE_PREPARING:
            if self._send_mount({"type": "multipoint_align_cancel"}):
                self.message(_("Align Cancelled"), 1)
            self._stage = self._STAGE_MODE
            self.update()
            return False
        if self._stage == self._STAGE_MODE:
            self._stage = self._STAGE_POINTS
            self.update()
            return False
        return True

    def key_right(self):
        if self._stage == self._STAGE_POINTS:
            self._stage = self._STAGE_MODE
            self.update()
            return False
        if self._stage == self._STAGE_MODE:
            if self.align_mode == "manual":
                self._start_manual()
            else:
                self._start_auto()
            return False
        if self._stage == self._STAGE_STAR:
            self._select_star_and_goto()
            return False
        return False

    def _start_manual(self):
        if self._send_mount(
            {
                "type": "multipoint_align_start",
                "mode": "manual",
                "points": self.align_points,
            }
        ):
            self._align_start_requested_at = time.time()
            self._stage = self._STAGE_PREPARING
            self.message(_("Manual Align"), 1)

    def _start_auto(self):
        if not self._has_solved_pointing():
            self.message(_("No solve"), 2)
            self._stage = self._STAGE_MODE
            return
        pointing = self._current_solved_pointing()
        if pointing is None:
            self.message(_("No solve"), 2)
            self._stage = self._STAGE_MODE
            return
        if self._send_mount(
            {
                "type": "multipoint_align_start",
                "mode": "auto",
                "points": self.align_points,
                "target_ra": pointing["ra"],
                "target_dec": pointing["dec"],
            }
        ):
            self._align_start_requested_at = time.time()
            self._stage = self._STAGE_PREPARING
            self.message(_("Auto Align"), 1)

    def _select_star_and_goto(self):
        star = self._selected_star()
        altitude = self._star_altitude(star)
        min_altitude, max_altitude = self._alignment_altitude_limits()
        if altitude is not None and altitude < min_altitude:
            self.message(_("Below horizon"), 2)
            self.update()
            return
        if altitude is not None and altitude > max_altitude:
            self.message(_("Near zenith"), 2)
            self.update()
            return
        if self._send_mount(
            {
                "type": "multipoint_align_select_star",
                "star_name": star["name"],
                "goto": True,
            }
        ):
            self.message(_("GoTo Sent"), 1)

    def _cancel_and_exit(self):
        self._move("stop")
        self._send_mount({"type": "multipoint_align_cancel"})
        self._complete_or_cancel_to_settings(_("Align Cancelled"))

    def key_square(self):
        align_status = self._align_status()
        if self._stage == self._STAGE_POINTS:
            self._stage = self._STAGE_MODE
            self.update()
            return
        if self._stage == self._STAGE_MODE:
            if self.align_mode == "manual":
                self._start_manual()
            else:
                self._start_auto()
            return
        if self._stage == self._STAGE_STAR:
            self._select_star_and_goto()
            return
        if (
            self._stage == self._STAGE_ADJUST
            and align_status.get("active")
            and align_status.get("current_star")
        ):
            if self._send_mount({"type": "multipoint_align_confirm"}):
                self.message(_("Point Confirmed"), 1)
            return
