"""Persistent LCD errors, acknowledgement, and isolation from mount shortcuts."""

import queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

import PiFinder.i18n  # noqa: F401

from PiFinder.displays import DisplayHeadless, DisplayHeadless176
from PiFinder.keyboard_interface import KeyboardInterface as Keys
from PiFinder.keyboard_mapping import (
    KeyboardMappingManager,
    KeyboardDispatcher,
    make_event,
)
from PiFinder.operation_errors import ErrorNotifier, mount_failure
from PiFinder.state import UIState
from PiFinder.ui.menu_manager import MenuManager

pytestmark = pytest.mark.unit


def test_failure_notifier_latches_until_new_operation():
    messages = queue.Queue()
    notifier = ErrorNotifier(messages, "INDI Mount")
    notifier.emit("sync_failed", "Driver rejected SYNC")
    notifier.emit("sync_failed", "Driver rejected SYNC")
    assert messages.qsize() == 1
    assert messages.get()["type"] == "operation_error"
    notifier.reset()
    notifier.emit("sync_failed", "Driver rejected SYNC")
    assert messages.qsize() == 1
    assert mount_failure("tracking_failed")
    assert mount_failure("usb_absent")
    assert not mount_failure("connected")
    assert not mount_failure("moving")


def _manager(display):
    manager = MenuManager.__new__(MenuManager)
    manager.display_class = display
    manager.ui_state = UIState()
    manager.shared_state = SimpleNamespace(
        ui_state=lambda: manager.ui_state,
        set_current_ui_state=Mock(),
        set_screen=Mock(),
    )
    manager.camera_image = None
    manager.command_queues = {}
    manager.config_object = SimpleNamespace(
        get_option=lambda key, default=None: default
    )
    manager.catalogs = None
    manager.error_dialog = None
    manager.help_images = None
    manager.marking_menu_stack = []
    manager._stack_anim_counter = 0
    manager.stack = [
        SimpleNamespace(
            update=Mock(),
            _guide_send_motion_keepalive=Mock(),
            _guide_stop_motion_if_active=Mock(),
            screen=Image.new("RGB", display.resolution),
            title="Previous screen",
        )
    ]
    return manager


@pytest.mark.parametrize("display_type", [DisplayHeadless, DisplayHeadless176])
def test_lcd_error_persists_scrolls_and_returns_to_exact_previous_screen(
    display_type, monkeypatch
):
    import builtins

    monkeypatch.setattr(builtins, "_", lambda text: text, raising=False)
    manager = _manager(display_type())
    previous = manager.stack[-1]
    error = {
        "source": "GoTo / Guide",
        "code": "sync_failed",
        "message": "Driver rejected SYNC. " * 30,
    }
    manager.show_error(error)
    manager.show_error(error)
    manager.update()
    dialog = manager.error_dialog
    assert len(dialog.errors) == 1
    assert manager.serialize_current_ui_state()["ui_type"] == "UIOperationError"
    assert len(dialog.lines) > dialog.visible_lines
    assert manager.consume_error_key(Keys.DOWN)
    assert dialog.offset == 1
    assert manager.consume_error_key(Keys.number_press_key(5))
    assert manager.error_dialog is dialog
    previous.update.assert_not_called()
    previous._guide_send_motion_keepalive.assert_not_called()
    assert manager.consume_error_key(Keys.RIGHT)
    assert manager.error_dialog is None
    assert manager.stack == [previous]
    previous.update.assert_called_once()


def test_error_keys_bypass_custom_mount_mapping_and_swallow_release():
    manager = KeyboardMappingManager()
    mount = queue.Queue()
    dispatcher = KeyboardDispatcher(queue.Queue(), mount, lambda: True)
    dispatcher.key_actions = {"KEY_106": "mount_right"}
    manager._dispatcher = dispatcher
    event = make_event(106, True, Keys.RIGHT)
    assert manager.error_dialog_key(event) == Keys.RIGHT
    assert mount.empty()
    assert manager.handle_event(make_event(106, True, Keys.RIGHT, repeat=True)) is None
    assert manager.handle_event(make_event(106, False, Keys.RIGHT)) is None
    assert mount.empty()
    manager.handle_event(event)
    assert mount.get_nowait()["type"] == "manual_movement"
    manager.suspend_for_error()
    manager.suspend_for_error()
    assert mount.get_nowait()["type"] == "stop_movement"
    dispatcher.tick(1e10)
    assert mount.empty()


def test_boot_errors_are_quiet_until_first_real_connection(monkeypatch):
    from PiFinder.operation_errors import MountErrorGate

    gate = MountErrorGate()
    errors = queue.Queue()
    notifier = ErrorNotifier(errors, "INDI Mount")
    clock = [100.0]
    monkeypatch.setattr("PiFinder.operation_errors.time.monotonic", lambda: clock[0])
    notifier.emit("no_telescope", "No mount attached for debugging")
    startup_error = errors.get_nowait()
    assert not gate.observe(startup_error)
    assert not gate.observe({"type": "mount_ready", "monotonic": 110.0})
    # Delayed pre-connection events must not suddenly open an error screen.
    assert not gate.observe(startup_error)
    clock[0] = 120.0
    notifier.emit("disconnected", "USB unplugged")
    assert gate.observe(errors.get_nowait())
    gate.observe({"type": "mount_ready", "monotonic": 130.0})
    assert gate.ready_at == 110.0  # Reconnection does not disarm error reporting.
