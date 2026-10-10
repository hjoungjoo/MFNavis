"""Tests for the mono/colour camera-variant selection.

The CFA is an optical layer the sensor cannot report over I2C, so the
variant is a per-device config declaration ("camera_variant") folded into
the profile name (docs/mf_dev/camera_ko.md). These tests
pin the mapping helper, the derived colour profiles, and the settings-UI
composition and restart behaviour.
"""

from __future__ import annotations

import dataclasses
from unittest import mock

import pytest

import PiFinder.i18n  # noqa: F401
from PiFinder.sqm.camera_profiles import apply_variant, get_camera_profile
from PiFinder.ui import callbacks, menu_structure

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- profiles


def test_apply_variant_maps_v3_sensors_to_their_colour_profiles():
    assert apply_variant("imx462", "color") == "imx462_color"
    assert apply_variant("imx296", "color") == "imx296_color"


def test_apply_variant_defaults_and_unknown_values_keep_the_base_profile():
    assert apply_variant("imx462", "mono") == "imx462"
    assert apply_variant("imx462", None) == "imx462"
    assert apply_variant("imx462", "colour") == "imx462"  # unknown spelling
    assert apply_variant("imx462", "") == "imx462"


def test_apply_variant_passes_through_cameras_without_a_colour_twin():
    # hq is always colour; there is no derived profile to switch to.
    assert apply_variant("hq", "color") == "hq"
    assert apply_variant("hq", "mono") == "hq"


def test_colour_profiles_inherit_the_mono_calibration():
    """The colour twins are ``dataclasses.replace`` derivations, not forks.

    Calibration constants are inherited from the mono units (unverified on
    colour hardware -- plan doc §4); only the declared deltas may differ.
    """
    for base_name, deltas in (
        ("imx462", {"mono"}),
        ("imx296", {"mono", "format"}),
    ):
        base = get_camera_profile(base_name)
        color = get_camera_profile(f"{base_name}_color")
        assert color.mono is False, base_name
        for field in dataclasses.fields(type(base)):
            if field.name in deltas:
                continue
            assert getattr(color, field.name) == getattr(base, field.name), (
                base_name,
                field.name,
            )


def test_imx296_colour_format_is_the_bayer_label():
    # Kernel driver: Y10 for mono, the SBGGR10 family for colour (plan doc
    # §6 V1). Order unverified on real hardware; non-SRGGB is the safe side.
    assert get_camera_profile("imx296_color").format == "SBGGR10"


# ------------------------------------------------------------- settings UI


class _FakeConfig:
    def __init__(self, variant="mono"):
        self.options = {"camera_variant": variant}

    def get_option(self, option, default=None):
        return self.options.get(option, default)

    def set_option(self, option, value):
        self.options[option] = value


class _FakeUIModule:
    def __init__(self, variant="mono"):
        self.config_object = _FakeConfig(variant)
        self.messages = []

    def message(self, text, timeout=2):
        self.messages.append(text)


def _boot_config(monkeypatch, tmp_path, line):
    boot = tmp_path / "config.txt"
    boot.write_text(line + "\n")
    monkeypatch.setattr(callbacks, "get_boot_config_path", lambda: boot)
    return boot


def test_get_camera_type_composes_sensor_and_variant(monkeypatch, tmp_path):
    _boot_config(monkeypatch, tmp_path, "dtoverlay=imx462,clock-frequency=74250000")
    ui_module = _FakeUIModule(variant="color")
    assert callbacks.get_camera_type(ui_module) == ["imx462_color"]

    ui_module.config_object.options["camera_variant"] = "mono"
    assert callbacks.get_camera_type(ui_module) == ["imx462_mono"]

    # An unknown stored value must still land on a real menu item.
    ui_module.config_object.options["camera_variant"] = "bogus"
    assert callbacks.get_camera_type(ui_module) == ["imx462_mono"]


def test_get_camera_type_aliases_imx290_and_skips_variant_for_imx477(
    monkeypatch, tmp_path
):
    _boot_config(monkeypatch, tmp_path, "dtoverlay=imx290,clock-frequency=74250000")
    assert callbacks.get_camera_type(_FakeUIModule()) == ["imx462_mono"]

    _boot_config(monkeypatch, tmp_path, "dtoverlay=imx477")
    assert callbacks.get_camera_type(_FakeUIModule(variant="color")) == ["imx477"]


def test_variant_only_change_restarts_the_service_not_the_system(monkeypatch, tmp_path):
    _boot_config(monkeypatch, tmp_path, "dtoverlay=imx462,clock-frequency=74250000")
    inert = mock.MagicMock(name="sys_utils")
    monkeypatch.setattr(callbacks, "sys_utils", inert)

    ui_module = _FakeUIModule(variant="mono")
    callbacks.switch_cam_imx462_color(ui_module)

    assert ui_module.config_object.options["camera_variant"] == "color"
    inert.restart_pifinder.assert_called_once()
    inert.restart_system.assert_not_called()
    inert.switch_cam_imx462.assert_not_called()


def test_sensor_change_switches_the_overlay_and_reboots(monkeypatch, tmp_path):
    _boot_config(monkeypatch, tmp_path, "dtoverlay=imx462,clock-frequency=74250000")
    inert = mock.MagicMock(name="sys_utils")
    monkeypatch.setattr(callbacks, "sys_utils", inert)

    ui_module = _FakeUIModule(variant="mono")
    callbacks.switch_cam_imx296_mono(ui_module)

    inert.switch_cam_imx296.assert_called_once()
    inert.restart_system.assert_called_once()
    inert.restart_pifinder.assert_not_called()


def test_reselecting_the_current_camera_is_a_noop(monkeypatch, tmp_path):
    _boot_config(monkeypatch, tmp_path, "dtoverlay=imx462,clock-frequency=74250000")
    inert = mock.MagicMock(name="sys_utils")
    monkeypatch.setattr(callbacks, "sys_utils", inert)

    ui_module = _FakeUIModule(variant="mono")
    callbacks.switch_cam_imx462_mono(ui_module)

    inert.switch_cam_imx462.assert_not_called()
    inert.restart_system.assert_not_called()
    inert.restart_pifinder.assert_not_called()


def _camera_type_menu():
    def walk(node):
        if isinstance(node, dict):
            if node.get("name") == "Camera Type":
                return node
            for child in node.get("items", []):
                found = walk(child)
                if found:
                    return found
        return None

    menu = walk(menu_structure.pifinder_menu)
    assert menu is not None, "Camera Type menu not found"
    return menu


def test_camera_type_menu_values_match_the_composed_camera_type():
    """Menu item values must equal what get_camera_type composes.

    The checkmark works by equality between the two, so a drifting value
    silently loses the checkmark rather than failing loudly.
    """
    values = {item["value"] for item in _camera_type_menu()["items"]}
    assert values == {
        "imx678",
        "imx477",
        "imx296_mono",
        "imx296_color",
        "imx462_mono",
        "imx462_color",
    }
