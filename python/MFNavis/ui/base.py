#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the base UIModule class

"""

import json
import logging
import time
import uuid
from itertools import cycle
from typing import TYPE_CHECKING, Any, Callable, Type, Union

from PIL import Image, ImageDraw
from PiFinder import utils
from PiFinder.ui.help_text import render_help_text
from PiFinder.image_util import make_red
from PiFinder.displays import DisplayBase
from PiFinder.config import Config
from PiFinder.ui.marking_menus import MarkingMenu
from PiFinder.catalogs import Catalogs

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


# Rate (brightness units per second of elapsed time) for the pulsing GPS
# "searching" animation in the title bar. This is an animation speed, not a
# geometry value — it must NOT scale with display resolution (it previously
# read as a bare ``128`` which looked resolution-derived).
GPS_ANIM_RATE = 128
# A4 clock-trust warning: how often to re-read the tmpfs trust marker for the
# title-bar indicator (cheap, but no need to stat it every frame).
CLOCK_TRUST_CHECK_SECONDS = 5.0
INDI_STATUS_FILE = utils.runtime_dir / "mount_control_status.json"
INDI_OK_STATES = {"connected", "moving", "slewing", "stopped"}
INDI_PROBLEM_STATES = {
    "backlash_failed",
    "device_connect_failed",
    "disconnected",
    "error",
    "goto_failed",
    "manual_failed",
    "missing_pyindi",
    "no_telescope",
    "park_failed",
    "server_unavailable",
    "slew_rate_failed",
    "stop_failed",
    "sync_failed",
}


class GuideKeyMixin:
    """Keyboard guide controls for passive LCD screens.

    Screens using this mixin keep their normal arrow/square controls while
    Bluetooth/USB keyboard letters and numeric keypad keys provide quick
    INDI guide movement when mount control is enabled.
    """

    if TYPE_CHECKING:
        # Provided by the host class (UIModule); declared for the type
        # checker only.
        _mount_key: Callable[..., Any]
        _mount_key_press: Callable[..., Any]
        _mount_key_release: Callable[..., Any]
        _guide_key_text: Callable[..., Any]
        _guide_key_text_press: Callable[..., Any]
        _guide_key_text_release: Callable[..., Any]

    def key_number(self, number=None):
        # Cardinal keys nudge/jog the mount; 0/5/7 are discrete commands
        # and 9/3 adjust the slew rate.
        # A subclass that owns key_number (e.g. object-list catalog jump) must
        # also override key_number_press/release to keep its behavior.
        self._mount_key(number)

    def key_number_press(self, number=None):
        self._mount_key_press(number)

    def key_number_release(self, number=None):
        self._mount_key_release(number)

    def key_text(self, char: str = ""):
        self._guide_key_text(char)

    def key_text_press(self, char: str = ""):
        self._guide_key_text_press(char)

    def key_text_release(self, char: str = ""):
        self._guide_key_text_release(char)


class RotatingInfoDisplay:
    """Alternates between constellation and SQM with cross-fade animation."""

    def __init__(self, shared_state, interval=3.0, fade_speed=0.15):
        self.shared_state = shared_state
        self.interval = interval
        self.fade_speed = fade_speed
        self.show_sqm = False
        self.last_switch = time.time()
        self.progress = 1.0  # 1.0 = stable, <1.0 = transitioning

    def _get_text(self, use_sqm):
        if use_sqm:
            sqm = self.shared_state.sqm()
            if sqm and sqm.last_update is not None:
                return f"{sqm.value:.1f}"
            return "---"
        else:
            sol = self.shared_state.solution()
            return sol.constellation if sol and sol.constellation else "---"

    def update(self):
        """Update state, returns (current_text, previous_text, progress)."""
        now = time.time()
        if now - self.last_switch >= self.interval:
            self.show_sqm = not self.show_sqm
            self.last_switch = now
            self.progress = 0.0
        if self.progress < 1.0:
            self.progress = min(1.0, self.progress + self.fade_speed)
        return (
            self._get_text(self.show_sqm),
            self._get_text(not self.show_sqm),
            self.progress,
        )

    def draw(self, draw, x, y, font, colors, max_brightness=255, inverted=False):
        """Draw with cross-fade animation. inverted=True for dark text on light bg."""
        current, previous, progress = self.update()
        if progress < 1.0:
            fade_out = progress < 0.5
            t = progress * 2 if fade_out else (progress - 0.5) * 2
            if inverted:
                brightness = (
                    int(max_brightness * t)
                    if fade_out
                    else int(max_brightness * (1 - t))
                )
            else:
                brightness = (
                    int(max_brightness * (1 - t))
                    if fade_out
                    else int(max_brightness * t)
                )
            text = previous if fade_out else current
            draw.text((x, y), text, font=font, fill=colors.get(brightness))
        else:
            draw.text(
                (x, y),
                current,
                font=font,
                fill=colors.get(0 if inverted else max_brightness),
            )


class UIModule:
    __title__ = "BASE"
    __help_name__ = ""
    __uuid__ = str(uuid.uuid1()).split("-")[0]
    _config_options: dict
    _CAM_ICON = ""
    _IMU_ICON = ""
    _GPS_ICON = "󰤉"
    _LEFT_ARROW = ""
    _RIGHT_ARROW = ""
    _UP_ARROW = ""
    _DOWN_ARROW = ""
    _CHECKMARK = ""
    _SQUARE_ = "󰝤"
    _ARROWS_ = ""
    _PLUS_ = "󰐕"
    _MINUS_ = "󰍴"
    _PLUSMINUS_ = "󰐕/󰍴"
    _gps_brightness = 0
    _clock_trust_checked_at = 0.0
    _clock_trust_cached = False
    _unmoved = False  # has the telescope moved since the last cam solve?
    _display_mode_list: Union[list[None], list[str]] = [None]  # List of display modes
    marking_menu: Union[None, MarkingMenu] = None

    def __init__(
        self,
        display_class: Type[DisplayBase],
        camera_image,
        shared_state,
        command_queues,
        config_object,
        catalogs: Catalogs,
        item_definition={},
        add_to_stack=None,
        remove_from_stack=None,
        jump_to_label=None,
    ):
        assert shared_state is not None
        self.title = self.__title__
        self.display_class = display_class
        self.display = display_class.device
        self.colors = display_class.colors
        self.shared_state = shared_state
        self.catalogs = catalogs
        self.ui_state = shared_state.ui_state()
        self.camera_image = camera_image
        self.command_queues = command_queues
        self.add_to_stack = add_to_stack
        self.remove_from_stack = remove_from_stack
        self.jump_to_label = jump_to_label

        # mode stuff
        self._display_mode_cycle = cycle(self._display_mode_list)
        self.display_mode = next(self._display_mode_cycle)

        self.screen = Image.new("RGB", display_class.resolution)
        self.draw = ImageDraw.Draw(self.screen, mode="RGBA")
        self.fonts = self.display_class.fonts

        # UI Module definition
        self.item_definition = item_definition
        self.title = item_definition.get("name", self.title)

        self.config_object: Config = config_object

        # FPS
        self.fps = 0
        self.frame_count = 0
        self.last_fps_sample_time = time.time()

        # anim timer stuff
        self.last_update_time = time.time()

        # Rotating info: alternates between constellation and SQM value
        self._rotating_display = RotatingInfoDisplay(self.shared_state)

    def active(self):
        """
        Called when a module becomes active
        i.e. foreground controlling display
        """
        pass

    def inactive(self):
        """
        Called when a module becomes inactive
        i.e. leaving a UI screen
        """
        self._guide_stop_motion_if_active()

    def covered(self):
        """Optional cleanup when another screen covers or discards this one.

        Unlike inactive(), this also runs for non-stateful menu pushes. Keep
        the default inert: existing screens retain their lifecycle behavior.
        """

    def help(self) -> Union[None, list[Image.Image]]:
        """
        Called when help is selected from the
        marking menu.  Should render the
        help screens as a list of images to be displayed
        up/down arrow will scroll through images
        """
        if self.__help_name__ == "":
            return None

        help_image_list = []
        help_image_path = utils.pifinder_dir / "help" / self.__help_name__
        for i in range(1, 10):
            try:
                text_path = help_image_path / f"{i}.txt"
                if text_path.is_file():
                    help_image = render_help_text(
                        text_path.read_text(), self.fonts.base.font
                    )
                else:
                    help_image = Image.open(help_image_path / f"{i}.png")
            except FileNotFoundError:
                break

            # help_image_list.append(
            #    convert_image_to_mode(help_image, self.colors.mode)
            # )

            red_help_image = make_red(help_image, self.colors)

            # Help PNGs are authored at 128x128, but luma requires every
            # displayed image to match the device resolution. Normalise each
            # frame onto a black resX x resY canvas (centred) so it renders on
            # any panel; scale down first if a frame is larger than the display
            # so it always fits. Derived from the display, not special-cased to
            # 176.
            res = (self.display_class.resX, self.display_class.resY)
            if red_help_image.size != res:
                if red_help_image.width > res[0] or red_help_image.height > res[1]:
                    red_help_image = red_help_image.copy()
                    red_help_image.thumbnail(res)
                frame = Image.new("RGB", res, self.colors.get(0))
                frame.paste(
                    red_help_image,
                    (
                        (res[0] - red_help_image.width) // 2,
                        (res[1] - red_help_image.height) // 2,
                    ),
                )
                red_help_image = frame

            help_image_list.append(red_help_image)

        if help_image_list == []:
            return None
        return help_image_list

    def update(self, force=False) -> None:
        """
        Called to trigger UI Updates
        to be overloaded by subclases and shoud
        end up calling self.screen_update to
        to the actual screen draw
        retun the results of the screen_update to
        pass any signals back to main
        """
        self.screen_update()

    def clear_screen(self):
        """
        Clears the screen (draws rectangle in black)
        """
        self.draw.rectangle(
            [
                0,
                0,
                self.display_class.resX,
                self.display_class.resY,
            ],
            fill=self.colors.get(0),
        )

    def draw_gate_message(self, message: str) -> None:
        """Render a full-screen "precondition not met" notice into ``self.screen``.

        A module that gates itself on a runtime precondition (e.g. a location
        fix) draws this from ``update`` in place of its normal UI and returns
        early; the user reads it and backs out with LEFT/Cancel rather than
        being blocked from opening the screen at all (see ADR 0019). Newlines
        in ``message`` split it into centred lines; a Cancel hint is pinned to
        the bottom-left, mirroring the entry screens' legends.
        """
        self.clear_screen()
        font = self.fonts.bold
        lines = message.split("\n")
        line_h = font.height + 2
        top = self.display_class.titlebar_height
        block_h = line_h * len(lines)
        y = top + max(4, (self.display_class.resY - top - block_h) // 2)
        for line in lines:
            text_w = font.font.getbbox(line)[2]
            x = max(0, (self.display_class.resX - text_w) // 2)
            self.draw.text((x, y), line, font=font.font, fill=self.colors.get(255))
            y += line_h
        self.draw.text(
            (10, self.display_class.resY - self.fonts.base.height - 2),
            _(" Cancel"),
            font=self.fonts.base.font,
            fill=self.colors.get(255),
        )

    def message(self, message, timeout: float = 2, size=None):
        """
        Creates a box with text in the center of the screen.
        Waits timeout in seconds
        """
        if size is None:
            # Centre the popup box on the screen, deriving from the display
            # resolution (was hardcoded to 128: (5, 44, 123, 84)).
            box_w = self.display_class.resX - 10
            box_h = round(self.display_class.resY * 40 / 128)
            x0 = 5
            y0 = (self.display_class.resY - box_h) // 2
            size = (x0, y0, x0 + box_w, y0 + box_h)

        # shadow
        self.draw.rectangle(
            (size[0] + 5, size[1] + 5, size[2] + 5, size[3] + 5),
            fill=self.colors.get(0),
            outline=self.colors.get(0),
        )
        self.draw.rectangle(size, fill=self.colors.get(0), outline=self.colors.get(128))

        line_length = int((size[2] - size[0]) / self.fonts.bold.width)
        message = " " * int((line_length - len(message)) / 2) + message

        self.draw.text(
            (size[0] + 4, size[1] + 5),
            message,
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        screen_to_display = self.screen.convert(self.display.mode)
        self.display.display(screen_to_display)

        # Update shared state so web interface shows the popup message
        if self.shared_state:
            self.shared_state.set_screen(screen_to_display)

        self.ui_state.set_message_timeout(timeout + time.time())

    def _draw_titlebar_rotating_info(self, x, y, fg):
        """Draw rotating constellation/SQM in title bar (dark text on gray bg)."""
        self._rotating_display.draw(
            self.draw,
            x,
            y,
            self.fonts.bold.font,
            self.colors,
            max_brightness=64,
            inverted=True,
        )

    def _indi_indicator_state(self):
        if not self.config_object.get_option("mount_control", False):
            return None
        try:
            with open(INDI_STATUS_FILE, encoding="utf-8") as status_in:
                status = json.load(status_in)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return "problem"

        state = str(status.get("state", "unknown"))
        updated = float(status.get("updated", 0) or 0)
        if time.time() - updated > 120:
            return "problem"
        if state in INDI_OK_STATES:
            return "ok"
        if state in INDI_PROBLEM_STATES or state.endswith("_failed"):
            return "problem"
        return "idle"

    def _indi_indicator_spec(self):
        """Return the GoTo Type glyph and current INDI connection state.

        ``off`` deliberately has no indicator. ``I`` denotes direct INDI Mount
        GoTo; ``P`` denotes the PiFinder GoTo procedure. The caller renders a
        connected state in bold and every
        other state in the matching regular/thin face.
        """
        goto_method = self._effective_goto_method()
        if goto_method == "off":
            return None, None
        glyph = "I" if goto_method == "indi_mount" else "P"
        return glyph, self._indi_indicator_state()

    def _effective_goto_method(self) -> str:
        """Return the valid session override, otherwise the saved setting."""
        session_method = self.config_object.get_option("session.indi_goto_method")
        if session_method in self._GOTO_METHOD_CYCLE:
            return str(session_method)
        saved_method = self.config_object.get_option("indi_goto_method", "pifinder")
        return (
            str(saved_method) if saved_method in self._GOTO_METHOD_CYCLE else "pifinder"
        )

    def _draw_indi_indicator(self, y):
        glyph, state = self._indi_indicator_spec()
        if glyph is None or state is None:
            return

        fill = self.colors.get(0 if state == "ok" else 32)
        x = int(self.display_class.resX * 0.865)
        font = self.fonts.bold.font if state == "ok" else self.fonts.regular.font
        self.draw.text((x, y), glyph, font=font, fill=fill)

    def _clock_untrusted(self) -> bool:
        """True while the system clock has not been GPS/NTP-synchronized this
        boot (stale fake-hwclock time) and no manual time is set -- mount time
        sync is deferred then."""
        now = time.monotonic()
        if now - self._clock_trust_checked_at > CLOCK_TRUST_CHECK_SECONDS:
            from PiFinder.gps_time_sync import read_clock_trust_marker

            manual = False
            try:
                manual = bool(self.shared_state.datetime_is_manual())
            except Exception:
                pass
            self._clock_trust_cached = manual or read_clock_trust_marker() is not None
            self._clock_trust_checked_at = now
        return not self._clock_trust_cached

    def _draw_clock_indicator(self, y):
        if not self._clock_untrusted():
            return
        # Blink like the INDI problem indicator so it reads as a warning.
        if int(time.time() * 2) % 2 == 0:
            return
        x = int(self.display_class.resX * 0.93)
        self.draw.text((x, y), "T", font=self.fonts.bold.font, fill=self.colors.get(32))

    def draw_rotating_info(self, x=10, y=92, font=None):
        """Draw rotating constellation/SQM display with cross-fade."""
        self._rotating_display.draw(
            self.draw,
            x,
            y,
            font or self.fonts.bold.font,
            self.colors,
            max_brightness=255,
        )

    def screen_update(self, title_bar=True, button_hints=True) -> None:
        """
        called to trigger UI updates
        takes self.screen adds title bar and
        writes to display
        """
        self._guide_send_motion_keepalive()

        # Don't redraw screen if message popup is active
        if time.time() < self.ui_state.message_timeout():
            return None

        if title_bar:
            fg = self.colors.get(0)
            bg = self.colors.get(64)
            tb_height = self.display_class.titlebar_height
            self.draw.rectangle(
                [0, 0, self.display_class.resX, tb_height],
                fill=bg,
            )
            # Vertically centre the title-bar text / icons in the bar so they
            # track titlebar_height across displays (was hardcoded for 128).
            title_y = max(0, (tb_height - self.fonts.bold.height) // 2)
            icon_y = (tb_height - self.fonts.icon_bold_large.height) // 2
            title_text = str(self.fps) if self.ui_state.show_fps() else _(self.title)
            # Truncate so the title never runs under the right-side status icons.
            # They start at the GPS icon (~0.8*resX); leave a small gap. Derived
            # from the screen size + bold font, so it adapts to 128/176/320.
            title_max_px = int(self.display_class.resX * 0.8) - 6 - 4
            title_max_chars = max(1, title_max_px // self.fonts.bold.width)
            if len(title_text) > title_max_chars:
                title_text = title_text[: title_max_chars - 1] + "…"
            self.draw.text((6, title_y), title_text, font=self.fonts.bold.font, fill=fg)
            imu = self.shared_state.imu()
            moving = bool(imu and imu.is_usable() and imu.moving)

            # GPS status
            if self.shared_state.altaz_ready():
                self._gps_brightness = 0
            else:
                gps_anim = (
                    int(GPS_ANIM_RATE * (time.time() - self.last_update_time)) + 1
                )
                self._gps_brightness += gps_anim
                if self._gps_brightness > 64:
                    self._gps_brightness = -128

            _gps_color = self.colors.get(
                self._gps_brightness if self._gps_brightness > 0 else 0
            )
            self.draw.text(
                (self.display_class.resX * 0.8, icon_y),
                self._GPS_ICON,
                font=self.fonts.icon_bold_large.font,
                fill=_gps_color,
            )
            self._draw_indi_indicator(title_y)
            self._draw_clock_indicator(title_y)

            if moving:
                self._unmoved = False

            if self.shared_state:
                if self.shared_state.solve_state():
                    solution = self.shared_state.solution()
                    cam_active = solution.is_camera_solve()
                    # a fresh cam solve sets unmoved to True
                    self._unmoved = True if cam_active else self._unmoved
                    if self._unmoved:
                        time_since_cam_solve = time.time() - (
                            solution.last_solve_success or 0.0
                        )
                        var_fg = min(64, int(time_since_cam_solve / 3 * 64))
                    # self.draw.rectangle([115, 2, 125, 14], fill=bg)

                    if self._unmoved:
                        self.draw.text(
                            (self.display_class.resX * 0.91, icon_y),
                            self._CAM_ICON,
                            font=self.fonts.icon_bold_large.font,
                            fill=var_fg,
                        )

                    if len(self.title) < 9:
                        # Draw rotating constellation/SQM wheel (replaces static constellation)
                        self._draw_titlebar_rotating_info(
                            x=int(self.display_class.resX * 0.54),
                            y=title_y,
                            fg=fg if self._unmoved else self.colors.get(32),
                        )
                else:
                    # no solve yet....
                    self.draw.text(
                        (self.display_class.resX * 0.91, title_y),
                        "X",
                        font=self.fonts.bold.font,
                        fill=fg,
                    )

        # FPS
        self.frame_count += 1
        if int(time.time()) - self.last_fps_sample_time > 0:
            # flipped second
            self.fps = self.frame_count
            self.frame_count = 0
            self.last_fps_sample_time = int(time.time())

        self.last_update_time = time.time()

    # Marking menu items
    def cycle_display_mode(self):
        """
        Cycle through available display modes
        for a module.  Invoked when the square
        key is pressed
        """
        self.display_mode = next(self._display_mode_cycle)

    _GUIDE_NUMBER_DIRECTIONS = {
        1: "southwest",
        2: "south",
        3: "southeast",
        4: "west",
        6: "east",
        7: "northwest",
        8: "north",
        9: "northeast",
    }
    _GUIDE_TEXT_DIRECTIONS = {
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
    # Slew-rate keys sit next to the letter jog pad, mirroring the 9/3 number
    # keys. Kept identical everywhere the letters drive the mount.
    _GUIDE_TEXT_SPEED = {
        ",": "reduce_slew_rate",
        ".": "increase_slew_rate",
    }
    _GUIDE_MOTION_LEASE_SECONDS = 2.5
    _GUIDE_MOTION_KEEPALIVE_INTERVAL = 0.25
    _GUIDE_MOTION_RESTART_INTERVAL = 8.0

    def _guide_mount_queue(self):
        try:
            mount_control_enabled = self.config_object.get_option(
                "mount_control", False
            )
        except Exception:
            mount_control_enabled = False

        if not mount_control_enabled:
            return None
        return self.command_queues.get("mountcontrol")

    def _guide_send_mount(self, command: dict) -> bool:
        mount_queue = self._guide_mount_queue()
        if mount_queue is None:
            return False
        mount_queue.put(command)
        return True

    def _guide_send_motion_keepalive(self) -> None:
        direction = getattr(self, "_guide_active_motion_direction", None)
        if direction is None:
            return

        now = time.monotonic()
        next_restart_at = getattr(self, "_guide_next_motion_restart_at", 0.0)
        if next_restart_at and now >= next_restart_at:
            self._guide_send_mount(
                {
                    "type": "manual_movement",
                    "direction": direction,
                    "lease_seconds": self._GUIDE_MOTION_LEASE_SECONDS,
                }
            )
            self._guide_next_motion_restart_at = (
                now + self._GUIDE_MOTION_RESTART_INTERVAL
            )
            self._guide_next_motion_keepalive_at = (
                now + self._GUIDE_MOTION_KEEPALIVE_INTERVAL
            )
            return

        next_keepalive_at = getattr(self, "_guide_next_motion_keepalive_at", 0.0)
        if now < next_keepalive_at:
            return

        self._guide_send_mount(
            {
                "type": "manual_movement_keepalive",
                "direction": direction,
                "lease_seconds": self._GUIDE_MOTION_LEASE_SECONDS,
            }
        )
        self._guide_next_motion_keepalive_at = (
            now + self._GUIDE_MOTION_KEEPALIVE_INTERVAL
        )

    def _guide_stop_motion_if_active(self) -> None:
        if getattr(self, "_guide_active_motion_direction", None) is None:
            return
        self._guide_move("stop")

    def _guide_move(self, direction: str, keepalive: bool = False) -> bool:
        if direction == "stop":
            self._guide_active_motion_direction = None
            self._guide_next_motion_keepalive_at = 0.0
            self._guide_next_motion_restart_at = 0.0
            return self._guide_send_mount({"type": "stop_movement"})
        if keepalive:
            now = time.monotonic()
            self._guide_active_motion_direction = direction
            self._guide_next_motion_keepalive_at = (
                now + self._GUIDE_MOTION_KEEPALIVE_INTERVAL
            )
            self._guide_next_motion_restart_at = (
                now + self._GUIDE_MOTION_RESTART_INTERVAL
            )
        return self._guide_send_mount(
            {
                "type": "manual_movement",
                "direction": direction,
                "lease_seconds": self._GUIDE_MOTION_LEASE_SECONDS,
            }
        )

    def _guide_key_number(self, number) -> bool:
        if number is None:
            return False
        if number in (0, 5):
            return self._guide_move("stop")
        direction = self._GUIDE_NUMBER_DIRECTIONS.get(number)
        if direction:
            return self._guide_move(direction)
        return False

    def _guide_key_number_press(self, number) -> bool:
        if number is None:
            return False
        if number in (0, 5):
            return self._guide_move("stop")
        direction = self._GUIDE_NUMBER_DIRECTIONS.get(number)
        if direction:
            return self._guide_move(direction, keepalive=True)
        return False

    def _guide_key_number_release(self, number) -> bool:
        if number is None:
            return False
        if number in self._GUIDE_NUMBER_DIRECTIONS:
            return self._guide_move("stop")
        return False

    def _guide_key_speed(self, char: str) -> bool:
        """Handle the slew-rate letters (, and .). One step per key event.

        key_text and key_text_press are mutually exclusive per input source (the
        main loop dispatches one or the other), so handling it in both fires
        exactly once either way; release is ignored.
        """
        command = self._GUIDE_TEXT_SPEED.get(char)
        if command is None:
            return False
        if not self._guide_send_mount({"type": command, "notify_ui": True}):
            return False
        return True

    def _guide_key_text(self, char: str) -> bool:
        if not char:
            return False
        direction = self._GUIDE_TEXT_DIRECTIONS.get(char.lower())
        if direction:
            return self._guide_move(direction)
        return self._guide_key_speed(char)

    def _guide_key_text_press(self, char: str) -> bool:
        if not char:
            return False
        direction = self._GUIDE_TEXT_DIRECTIONS.get(char.lower())
        if direction:
            return self._guide_move(direction, keepalive=True)
        return self._guide_key_speed(char)

    def _guide_key_text_release(self, char: str) -> bool:
        if not char:
            return False
        if char.lower() in self._GUIDE_TEXT_DIRECTIONS:
            return self._guide_move("stop")
        return False

    # --- Mount number keys -----------------------------------------------------
    # Wherever a number key drives the INDI mount (Object Details, mount-on menus,
    # status screens, INDI guide screens), the cardinal keys (2/4/6/8) move the
    # mount for as long as they are held (press starts motion, release stops it),
    # a few discrete commands sit on 0/1/5/7 and the slew rate is on 9 (faster)
    # / 3 (slower). Continuous jog is also on the keyboard letters. See
    # docs/mf_dev/mf_input_keymap_*.md.
    _MOUNT_JOG_DIRECTIONS = {2: "south", 4: "west", 6: "east", 8: "north"}
    _GOTO_METHOD_CYCLE = ("off", "indi_mount", "pifinder")
    _GOTO_METHOD_LABELS = {
        "off": "Off",
        "indi_mount": "INDI Mount",
        "pifinder": "MFNavis",
    }

    def _mount_control_queue(self):
        return self._guide_mount_queue()

    def _goto_guide_queue(self):
        """Queue for the INDI GoTo/Guide service (tracking-guide auto-correction).

        Used alongside the mount-control queue so a Stop also halts the
        auto-correction and a GoTo re-arms its tracking target.
        """
        try:
            return self.command_queues.get("goto_guide")
        except Exception:
            return None

    def _mount_pointing_radec(self):
        solution = self.shared_state.solution()
        if not solution or not solution.has_pointing():
            return None
        aligned = solution.pointing.aligned.estimate
        if aligned is None:
            return None
        return aligned.RA, aligned.Dec

    def _toggle_goto_method(self) -> bool:
        """Persist and announce the next GoTo Type selection.

        This is a session-only setting: keypad, keyboard, and Web Remote
        changes must not add frequent writes to the SD card. The persistent
        Settings menu remains the place to save ``indi_goto_method``.
        """
        current = self._effective_goto_method()
        try:
            current_index = self._GOTO_METHOD_CYCLE.index(current)
        except ValueError:
            current_index = self._GOTO_METHOD_CYCLE.index("pifinder")
        next_method = self._GOTO_METHOD_CYCLE[
            (current_index + 1) % len(self._GOTO_METHOD_CYCLE)
        ]
        try:
            self.config_object.set_option("session.indi_goto_method", next_method)
        except (OSError, ValueError, TypeError) as exc:
            logging.getLogger("UI.base").warning("Failed to save GoTo Type: %s", exc)
            self.message(_("GoTo Type failed"), 1)
            return False

        goto_guide_queue = self._goto_guide_queue()
        if goto_guide_queue is not None:
            goto_guide_queue.put(
                {"type": "set_goto_method", "goto_method": next_method}
            )
        self.message(
            _("GoTo Type\n{method}").format(
                method=_(self._GOTO_METHOD_LABELS[next_method])
            ),
            1,
        )
        return True

    def _mount_command(self, number, target=None, target_object=None) -> bool:
        """Run a discrete mount command for a number key: 0=Stop, 1=GoTo Type,
        5=GoTo, 7=Sync, 9=Speed+, 3=Speed-.

        Directional keys (2/4/6/8) are handled as hold-to-move by _mount_key_*,
        not here. GoTo (5) needs an explicit ``target`` (ra, dec) — the screen
        that owns a selected object (Object Details) passes it. On plain menus /
        status screens there is no selected object, so 5 does nothing. Returns
        True if the mount was addressed.
        """
        if number is None:
            return False
        queue = self._mount_control_queue()
        if queue is None:
            return False

        guide_queue = self._goto_guide_queue()
        if number == 0:
            queue.put({"type": "stop_movement"})
            # Also stop the GoTo/Guide auto-correction (and clear its tracking
            # target) so it does not immediately re-correct.
            if guide_queue is not None:
                guide_queue.put({"type": "stop_movement"})
            self.message(_("Mount Stop"), 1)
        elif number == 1:
            self._toggle_goto_method()
        elif number == 5:
            # GoTo is only available where an object is selected. Without a
            # target (plain menus / status) the key is unused.
            if target is None:
                return False
            if self.config_object.get_option("indi_goto_method", "pifinder") == "off":
                self.message(_("GoTo Off"), 1)
                return True
            command = {
                "type": "goto_target",
                "ra": target[0],
                "dec": target[1],
            }
            if guide_queue is not None:
                # GoTo policy (INDI Mount forward vs PiFinder sync + GoTo loop)
                # lives in the GoTo/Guide service; it also re-arms the
                # tracking-guide target itself.
                guide_queue.put(command)
            else:
                queue.put(command)
            # Same tracking-frequency policy as the web catalog push:
            # planets get an ephemeris feed-forward rate, static targets
            # reset an active non-sidereal frequency back to sidereal.
            try:
                from PiFinder.track_freq_policy import track_freq_command_for_target

                freq_command = track_freq_command_for_target(
                    target_object, self.shared_state
                )
                if freq_command is not None:
                    queue.put(freq_command)
            except Exception:
                logging.getLogger("UI.base").exception("Track frequency policy failed")
            self.message(_("Mount GoTo"), 1)
        elif number == 7:
            pointing = self._mount_pointing_radec()
            if pointing is None:
                self.message(_("No solve"), 1)
                return True
            queue.put(
                {
                    "type": "sync",
                    "ra": pointing[0],
                    "dec": pointing[1],
                    "origin": "lcd_guide",
                    "pointing_source": "pifinder_pointing",
                }
            )
            self.message(_("Mount Sync"), 1)
        elif number == 9:
            queue.put({"type": "increase_slew_rate", "notify_ui": True})
        elif number == 3:
            queue.put({"type": "reduce_slew_rate", "notify_ui": True})
        else:
            return False
        return True

    def _mount_key(self, number, target=None, target_object=None) -> None:
        """Single-tap number key: cardinal = one nudge, else discrete command."""
        if number is None:
            return
        direction = self._MOUNT_JOG_DIRECTIONS.get(number)
        if direction is not None:
            self._guide_move(direction)
            return
        self._mount_command(number, target=target, target_object=target_object)

    def _mount_key_press(self, number, target=None, target_object=None) -> None:
        """Press a number key: cardinal starts hold-to-move, else discrete."""
        if number is None:
            return
        direction = self._MOUNT_JOG_DIRECTIONS.get(number)
        if direction is not None:
            self._guide_move(direction, keepalive=True)
            return
        self._mount_command(number, target=target, target_object=target_object)

    def _mount_key_release(self, number) -> None:
        """Release a cardinal number key: stop the hold-to-move motion."""
        if number in self._MOUNT_JOG_DIRECTIONS:
            self._guide_move("stop")

    def key_number(self, number):
        pass

    def key_number_press(self, number=None):
        if number is None:
            return
        self.key_number(number)

    def key_number_release(self, number=None):
        pass

    def key_text(self, char: str = ""):
        pass

    def key_text_press(self, char: str = ""):
        pass

    def key_text_release(self, char: str = ""):
        if not char:
            return
        self.key_text(char)

    def key_plus(self):
        pass

    def key_minus(self):
        pass

    def key_square(self):
        self.cycle_display_mode()
        self.update()

    def key_long_up(self):
        pass

    def key_long_down(self):
        pass

    def key_long_right(self):
        pass

    def key_up(self):
        pass

    def key_down(self):
        pass

    def key_right(self):
        pass

    def key_left(self) -> bool:
        """
        This is passed through from menu_manager
        and normally results in the module being
        removed from the stack.  Return False to
        override the remove from stack behavior
        """
        return True
