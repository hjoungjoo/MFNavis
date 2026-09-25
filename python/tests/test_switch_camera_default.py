"""Fresh installs select IMX462 without changing an existing camera choice."""

import pytest

from PiFinder import switch_camera


pytestmark = pytest.mark.unit


def test_default_boot_adds_imx462_once(monkeypatch, tmp_path):
    boot = tmp_path / "config.txt"
    boot.write_text("camera_auto_detect=1\n")
    monkeypatch.setattr(switch_camera, "get_boot_config_path", lambda: boot)

    assert switch_camera.ensure_default_boot() is True
    expected = "#camera_auto_detect=1\n" "dtoverlay=imx462,clock-frequency=74250000\n"
    assert boot.read_text() == expected
    assert switch_camera.ensure_default_boot() is False
    assert boot.read_text() == expected


def test_default_boot_preserves_selected_camera(monkeypatch, tmp_path):
    boot = tmp_path / "config.txt"
    existing = "#camera_auto_detect=1\ndtoverlay=imx477\n"
    boot.write_text(existing)
    monkeypatch.setattr(switch_camera, "get_boot_config_path", lambda: boot)

    assert switch_camera.ensure_default_boot() is False
    assert boot.read_text() == existing
