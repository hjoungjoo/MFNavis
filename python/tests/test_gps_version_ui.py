from queue import Queue
from unittest.mock import Mock

import pytest
import PiFinder.i18n  # noqa: F401
from PiFinder.ui.base import UIModule
from PiFinder.ui.gpsstatus import UIGPSStatus


@pytest.mark.parametrize("gps_type", ["ublox", "gpsd", "fake", None])
def test_version_menu_visibility_and_command(monkeypatch, gps_type):
    config = Mock()
    config.get_option.return_value = gps_type
    commands = Queue()
    navigation = Queue()

    def init(screen):
        screen.config_object = config
        screen.command_queues = {"gps_command": commands, "gps": navigation}

    monkeypatch.setattr(UIModule, "__init__", init)
    screen = UIGPSStatus()
    screen.message = Mock()
    option = screen.marking_menu.down
    assert option.label == ("Get VER" if gps_type == "ublox" else "")
    assert option.enabled == (gps_type == "ublox")
    if gps_type == "ublox":
        assert option.callback(None, option)
        assert commands.get_nowait() == "get_version"
        screen.message.assert_called_once()
    else:
        assert option.callback is None
        screen.mm_get_version(None, option)
        assert commands.empty()
    assert navigation.empty()


def test_menu_refreshes_when_config_changes(monkeypatch):
    config = Mock()
    config.get_option.return_value = "ublox"

    def init(screen):
        screen.config_object = config
        screen.command_queues = {"camera": Queue()}

    monkeypatch.setattr(UIModule, "__init__", init)
    screen = UIGPSStatus()
    config.get_option.return_value = "gpsd"
    screen.active()
    assert not screen.marking_menu.down.enabled
    assert screen.marking_menu.down.label == ""


def test_unavailable_backend_reports_failure(monkeypatch):
    def init(screen):
        screen.config_object = Mock()
        screen.config_object.get_option.return_value = "ublox"
        screen.command_queues = {}

    monkeypatch.setattr(UIModule, "__init__", init)
    screen = UIGPSStatus()
    screen.message = Mock()
    screen.mm_get_version(None, None)
    screen.message.assert_called_once_with("GPS unavailable", timeout=2)
