#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Bluetooth device pairing and connection UI (keyboards and joysticks/gamepads).
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import re
import select
import subprocess
import time
from typing import Any, TYPE_CHECKING

from PiFinder import utils
from PiFinder.ui.text_menu import UITextMenu

logger = logging.getLogger("UIBluetoothKeyboard")

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


sys_utils = utils.get_sys_utils()

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# bluetoothctl wraps its colored agent prompts in readline's non-printing
# markers \x01 (SOH) and \x02 (STX). Left in place they sit between "Passkey:"
# and the digits, breaking passkey detection, so strip all C0 control chars
# except tab/newline (\r is normalized to \n separately).
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
PASSKEY_RE = re.compile(r"Passkey:\s*([0-9]{4,8})", re.IGNORECASE)
MAC_ADDRESS_RE = re.compile(r"^[0-9A-Fa-f:]{17}$")
DEVICE_NAME_MAX = 20
SCAN_SECONDS = 12
PAIR_TIMEOUT = 90
# Hard cap on how long WiFi may stay paused during a pairing attempt. A
# successful pair (incl. passkey entry) completes well inside this; capping it
# means a slow/hung pair can never leave the user without WiFi for the full
# PAIR_TIMEOUT. The attempt keeps running; only the WiFi silence ends.
WIFI_MAX_PAUSE = 35


class UIBluetoothKeyboard(UITextMenu):
    """
    Small Bluetooth HID manager for pairing keyboards and joysticks/gamepads
    from the PiFinder UI. USB devices need no pairing; they are handled by the
    normal libinput path.
    """

    __title__ = "Bluetooth"

    def __init__(self, *args, **kwargs):
        self.devices: list[dict[str, Any]] = []
        self.status = ""
        self.action_menu_active = False
        self.action_index = 0
        self.selected_device: dict[str, Any] | None = None

        self.pair_process: subprocess.Popen | None = None
        self.pair_address = ""
        self.pair_name = ""
        self.pair_started = 0.0
        self.pair_status = ""
        self.pair_output = ""
        self.pair_done_at: float | None = None
        self.pair_success = False
        self.pair_connect_sent = False
        self.pair_yes_sent = False
        self.pair_passkey = ""
        self.wifi_paused = False

        self._refresh_devices()
        kwargs["item_definition"] = self._create_menu_definition()
        super().__init__(*args, **kwargs)

    def _refresh_devices(self):
        try:
            self.devices = sys_utils.list_bluetooth_devices()
            self.status = ""
        except Exception as e:
            self.devices = []
            self.status = f"BT error: {e}"

    def _create_menu_definition(self):
        items = [
            {"name": _("Scan"), "value": "__scan__"},
            {"name": _("Reconnect"), "value": "__reconnect__"},
            {"name": _("Refresh"), "value": "__refresh__"},
        ]
        for device in self.devices:
            items.append(
                {
                    "name": self._device_label(device),
                    "value": device["address"],
                    "device": device,
                }
            )
        if not self.devices:
            items.append({"name": _("No BT devices"), "value": None})
        return {"name": _("Bluetooth"), "select": "single", "items": items}

    def _rebuild_menu(self):
        self.item_definition = self._create_menu_definition()
        self._menu_items = [x["name"] for x in self.item_definition["items"]]
        if self._current_item_index >= len(self._menu_items):
            self._current_item_index = max(0, len(self._menu_items) - 1)

    def _device_label(self, device: dict[str, Any]) -> str:
        if device.get("connected"):
            marker = "*"
        elif device.get("paired"):
            marker = "+"
        else:
            marker = "-"
        name = self._device_name(device)
        available = max(5, DEVICE_NAME_MAX - 2)
        if len(name) > available:
            name = name[: available - 3] + "..."
        return f"{marker} {name}"

    def _device_name(self, device: dict[str, Any]) -> str:
        name = str(device.get("name") or device.get("alias") or "").strip()
        address = str(device.get("address") or "").strip()
        if not name or MAC_ADDRESS_RE.match(name):
            return f"Unknown {address[-5:]}" if address else "Unknown"
        return name

    def _short_address(self, device: dict[str, Any]) -> str:
        address = str(device.get("address") or "").strip()
        if not address:
            return ""
        return f"MAC ...{address[-8:]}"

    def _selected_item(self) -> dict[str, Any]:
        return self.item_definition["items"][self._current_item_index]

    def _run_scan(self):
        self.message(_("BT scanning"), SCAN_SECONDS)
        try:
            self.devices = sys_utils.scan_bluetooth_devices(SCAN_SECONDS)
            self.status = f"Found {len(self.devices)}"
        except Exception as e:
            self.status = f"Scan error: {e}"
        self._rebuild_menu()

    @contextlib.contextmanager
    def _wifi_paused_for_link(self):
        """
        Silence WiFi while establishing a Bluetooth link, then always restore
        it. Onboard WiFi/BT share one 2.4GHz antenna and coexistence breaks BLE
        connection setup; a detached watchdog restores WiFi even if we die here.
        The pause is skipped (returns False) while every active WiFi link is on
        5GHz -- no contention with 2.4GHz-only Bluetooth, so WiFi stays up.
        """
        paused = False
        try:
            paused = bool(sys_utils.pause_wifi_for_bt_pairing())
        except Exception as e:
            logger.warning("BT link: could not pause WiFi: %s", e)
        try:
            yield
        finally:
            if paused:
                try:
                    sys_utils.resume_wifi_after_bt_pairing()
                except Exception as e:
                    logger.warning("BT link: could not resume WiFi: %s", e)

    def _run_reconnect(self):
        self.message(_("Connecting"), 2)
        try:
            with self._wifi_paused_for_link():
                count = sys_utils.reconnect_bluetooth_keyboards()
            self.status = f"Reconnect {count}"
        except Exception as e:
            self.status = f"Conn error: {e}"
        self._refresh_devices()
        self._rebuild_menu()

    def _open_action_menu(self, device: dict[str, Any]):
        self.selected_device = device
        self.action_menu_active = True
        self.action_index = 0

    def _action_items(self) -> list[tuple[str, str]]:
        device = self.selected_device or {}
        actions: list[tuple[str, str]] = []
        if not device.get("paired"):
            actions.append((_("Pair+Connect"), "pair"))
        else:
            actions.append((_("Pair Again"), "pair"))
        actions.append((_("Connect"), "connect"))
        if device.get("connected"):
            actions.append((_("Disconnect"), "disconnect"))
        actions.append((_("Remove"), "remove"))
        actions.append((_("Cancel"), "cancel"))
        return actions

    def _perform_action(self):
        if self.selected_device is None:
            self.action_menu_active = False
            return

        label, action = self._action_items()[self.action_index]
        address = str(self.selected_device["address"])
        if action == "cancel":
            self.action_menu_active = False
            return
        if action == "pair":
            self._start_pairing(address, str(self.selected_device.get("name", "")))
            return

        self.message(label, 1)
        try:
            if action == "connect":
                with self._wifi_paused_for_link():
                    output = sys_utils.connect_bluetooth_device(address)
            elif action == "disconnect":
                output = sys_utils.disconnect_bluetooth_device(address)
            elif action == "remove":
                output = sys_utils.remove_bluetooth_device(address)
            else:
                output = ""
            self.status = self._short_result(output)
        except Exception as e:
            self.status = f"BT error: {e}"
        self.action_menu_active = False
        self._refresh_devices()
        self._rebuild_menu()

    def _short_result(self, output: str) -> str:
        clean = self._clean_text(output)
        for line in reversed([x.strip() for x in clean.splitlines() if x.strip()]):
            if "successful" in line.lower() or "failed" in line.lower():
                return line[:24]
        return "Done"

    def _start_pairing(self, address: str, name: str):
        self._close_pair_process()
        self.pair_address = address
        self.pair_name = name or address
        # Monotonic: a GPS/NTP clock jump (no RTC on this device) must not
        # freeze the WiFi-resume and pairing timeouts below.
        self.pair_started = time.monotonic()
        self.pair_status = "Starting"
        self.pair_output = ""
        self.pair_done_at = None
        self.pair_success = False
        self.pair_connect_sent = False
        self.pair_yes_sent = False
        self.pair_passkey = ""

        # Onboard WiFi shares the 2.4GHz antenna with Bluetooth and reliably
        # breaks BLE pairing (HCI 0x3e). Silence WiFi for the attempt; it is
        # always restored in _close_pair_process (plus a detached watchdog).
        # Skipped (returns False) while every active WiFi link is on 5GHz --
        # no contention with 2.4GHz-only Bluetooth, so WiFi stays up.
        self.pair_status = "Pausing WiFi"
        try:
            self.wifi_paused = bool(sys_utils.pause_wifi_for_bt_pairing())
        except Exception as e:
            logger.warning("BT pairing: could not pause WiFi: %s", e)

        try:
            self.pair_process = subprocess.Popen(
                [sys_utils.BLUETOOTHCTL_COMMAND],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
            )
            assert self.pair_process.stdout is not None
            flags = fcntl.fcntl(self.pair_process.stdout.fileno(), fcntl.F_GETFL)
            fcntl.fcntl(
                self.pair_process.stdout.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK
            )
            for command in [
                "power on",
                "agent KeyboardDisplay",
                "default-agent",
                "pairable on",
                f"pair {address}",
            ]:
                self._send_pair_command(command)
            self.pair_status = "Pairing"
        except Exception as e:
            self.pair_status = f"Start failed: {e}"
            self._finish_pairing(False)
            # The update loop won't tear down a process it never saw, so restore
            # WiFi here rather than waiting for the safety watchdog.
            self._close_pair_process()

    def _send_pair_command(self, command: str):
        if self.pair_process is None or self.pair_process.stdin is None:
            return
        try:
            self.pair_process.stdin.write((command + "\n").encode())
            self.pair_process.stdin.flush()
        except BrokenPipeError:
            pass

    def _clean_text(self, text: str) -> str:
        text = ANSI_ESCAPE_RE.sub("", text)
        text = CONTROL_CHARS_RE.sub("", text)
        return text.replace("\r", "\n")

    def _read_pair_output(self):
        if self.pair_process is None or self.pair_process.stdout is None:
            return
        fd = self.pair_process.stdout.fileno()
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                break
            if not chunk:
                break
            text = chunk.decode(errors="replace")
            self.pair_output = (self.pair_output + text)[-4000:]
            self._handle_pair_text(self._clean_text(self.pair_output))

    def _handle_pair_text(self, text: str):
        passkey = PASSKEY_RE.search(text)
        if passkey:
            self.pair_passkey = passkey.group(1)
            self.pair_status = "Type this code:"

        if not self.pair_yes_sent and (
            "Confirm passkey" in text
            or "Authorize service" in text
            or "Accept pairing" in text
        ):
            self._send_pair_command("yes")
            self.pair_yes_sent = True

        pair_ok = "Pairing successful" in text or "AlreadyExists" in text
        if pair_ok and not self.pair_connect_sent:
            self.pair_status = "Connecting"
            self._send_pair_command(f"trust {self.pair_address}")
            self._send_pair_command(f"connect {self.pair_address}")
            self.pair_connect_sent = True

        if "Connection successful" in text:
            self.pair_status = "Connected"
            self._finish_pairing(True)
            return

        failure_tokens = [
            "AuthenticationCanceled",
            "AuthenticationFailed",
            "Failed to pair",
            "Failed to connect",
            "not available",
            "No default controller",
        ]
        if any(token in text for token in failure_tokens):
            if pair_ok:
                self.pair_status = "Paired"
            else:
                self.pair_status = "Pair failed"
            self._finish_pairing(pair_ok)

    def _finish_pairing(self, success: bool):
        if self.pair_done_at is not None:
            return
        self.pair_success = success
        self.pair_done_at = time.monotonic()
        self._send_pair_command("quit")

    def _close_pair_process(self):
        if self.pair_process is None:
            self._resume_wifi()
            return
        try:
            if self.pair_process.poll() is None:
                self.pair_process.terminate()
                self.pair_process.wait(timeout=1)
        except Exception:
            try:
                self.pair_process.kill()
            except Exception:
                pass
        self.pair_process = None
        self._resume_wifi()

    def _resume_wifi(self):
        if not self.wifi_paused:
            return
        self.wifi_paused = False
        try:
            sys_utils.resume_wifi_after_bt_pairing()
        except Exception as e:
            logger.warning("BT pairing: could not resume WiFi: %s", e)

    def _update_pairing(self):
        if self.pair_process is None:
            return
        self._read_pair_output()
        # Bound the WiFi-off window independently of how long pairing runs, so a
        # slow attempt can't lock the user out of the network.
        if self.wifi_paused and time.monotonic() - self.pair_started > WIFI_MAX_PAUSE:
            self._resume_wifi()
        if time.monotonic() - self.pair_started > PAIR_TIMEOUT:
            self.pair_status = "Pair timeout"
            self._finish_pairing(False)
        if self.pair_process.poll() is not None and self.pair_done_at is None:
            self._finish_pairing(self.pair_success)
        if self.pair_done_at and time.monotonic() - self.pair_done_at > 2.5:
            self._close_pair_process()
            self.action_menu_active = False
            self._refresh_devices()
            self._rebuild_menu()

    def _draw_lines(self, lines: list[str], selected: int | None = None):
        self.clear_screen()
        draw_y = self.display_class.titlebar_height + 2
        max_chars = max(4, (self.display_class.resX - 4) // self.fonts.base.width)
        for idx, line in enumerate(lines):
            if draw_y > self.display_class.resY - self.fonts.base.height:
                break
            if len(line) > max_chars:
                line = line[: max_chars - 3] + "..."
            fill = self.colors.get(255 if selected == idx else 128)
            font = self.fonts.bold.font if selected == idx else self.fonts.base.font
            self.draw.text((2, draw_y), line, font=font, fill=fill)
            draw_y += self.fonts.base.height + 2

    def _draw_action_menu(self):
        device = self.selected_device or {}
        name = self._device_name(device)
        state = []
        if device.get("connected"):
            state.append("Conn")
        if device.get("paired"):
            state.append("Pair")
        if device.get("trusted"):
            state.append("Trust")
        lines = [name, self._short_address(device), " ".join(state) or "New device"]
        lines.extend(label for label, _ in self._action_items())
        self._draw_lines(lines, self.action_index + 3)
        return self.screen_update()

    def _draw_pairing(self):
        self._update_pairing()
        # While a passkey must be typed on the keyboard, show the digits in a
        # large font so they're easy to read off the small display.
        if self.pair_passkey and not self.pair_done_at:
            self.clear_screen()
            draw_y = self.display_class.titlebar_height + 2
            max_chars = max(4, (self.display_class.resX - 4) // self.fonts.base.width)
            name = self.pair_name
            if len(name) > max_chars:
                name = name[: max_chars - 3] + "..."
            for text in (name, "Type this code:"):
                self.draw.text(
                    (2, draw_y),
                    text,
                    font=self.fonts.base.font,
                    fill=self.colors.get(128),
                )
                draw_y += self.fonts.base.height + 2
            self.draw.text(
                (2, draw_y + 2),
                self.pair_passkey,
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            draw_y += self.fonts.large.height + 4
            if self.wifi_paused:
                self.draw.text(
                    (2, draw_y),
                    "WiFi paused",
                    font=self.fonts.base.font,
                    fill=self.colors.get(96),
                )
            return self.screen_update()

        lines = [
            "Pair Keyboard",
            self.pair_name,
            self.pair_status,
        ]
        if self.pair_done_at:
            lines.append("OK" if self.pair_success else "Failed")
        else:
            lines.append("Left cancels")
        if self.wifi_paused:
            lines.append("WiFi paused")
        self._draw_lines(lines)
        return self.screen_update()

    def update(self, force=False):
        if self.pair_process is not None:
            return self._draw_pairing()
        if self.action_menu_active:
            return self._draw_action_menu()
        result = super().update(force)
        if self.status:
            y = self.display_class.resY - self.fonts.base.height - 1
            max_chars = max(4, (self.display_class.resX - 4) // self.fonts.base.width)
            status = self.status[:max_chars]
            self.draw.rectangle(
                [0, y - 1, self.display_class.resX, self.display_class.resY],
                fill=self.colors.get(0),
            )
            self.draw.text(
                (2, y), status, font=self.fonts.base.font, fill=self.colors.get(192)
            )
            return self.screen_update()
        return result

    def key_up(self):
        if self.action_menu_active:
            self.action_index = (self.action_index - 1) % len(self._action_items())
            return
        super().key_up()

    def key_down(self):
        if self.action_menu_active:
            self.action_index = (self.action_index + 1) % len(self._action_items())
            return
        super().key_down()

    def key_right(self):
        if self.pair_process is not None:
            return
        if self.action_menu_active:
            return self._perform_action()

        selected_item = self._selected_item()
        value = selected_item.get("value")
        if value == "__scan__":
            return self._run_scan()
        if value == "__reconnect__":
            return self._run_reconnect()
        if value == "__refresh__":
            self._refresh_devices()
            self._rebuild_menu()
            return
        if selected_item.get("device"):
            return self._open_action_menu(selected_item["device"])

    def key_left(self) -> bool:
        if self.pair_process is not None:
            self._close_pair_process()
            self.pair_status = "Canceled"
            self.action_menu_active = False
            self._refresh_devices()
            self._rebuild_menu()
            return False
        if self.action_menu_active:
            self.action_menu_active = False
            return False
        return True
