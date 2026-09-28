"""Upstream IMX678 RAW geometry, PiSP padding, and deferred camera selection."""

from types import SimpleNamespace
from unittest.mock import Mock
import sys

import numpy as np
import pytest

import PiFinder.i18n  # noqa: F401
from PiFinder import switch_camera
from PiFinder.camera_pi import CameraPI, imx678_variant
from PiFinder.optics import build_optical_train
from PiFinder.sqm.camera_profiles import detect_camera_type, get_camera_profile
from PiFinder.ui import callbacks

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("mono", [True, False])
def test_camera_initialization_uses_sensor_variant_and_pins_raw12(monkeypatch, mono):
    driver = Mock()
    driver.camera.id = "/base/axi/i2c/imx678@1a"
    delivered = "R16" if mono else "SRGGB16"
    driver.sensor_modes = [
        {"size": (3856, 2180), "unpacked": delivered, "bit_depth": 16}
    ]
    driver.camera_configuration.return_value = {
        "raw": {"format": delivered, "size": (3856, 2180)}
    }
    monkeypatch.setitem(
        sys.modules, "picamera2", SimpleNamespace(Picamera2=lambda: driver)
    )
    config = SimpleNamespace(
        get_option=lambda key, default=None: ("color" if mono else "mono")
        if key == "camera_variant"
        else False
    )
    camera = CameraPI(100_000, config)
    assert camera.profile.mono is mono
    assert camera.camera_type == ("imx678" if mono else "imx678_color")
    assert camera._raw_shift == 4
    assert driver.create_still_configuration.call_args.kwargs["sensor"] == {
        "bit_depth": 12,
        "output_size": (3856, 2180),
    }
    driver.start.assert_called_once()


@pytest.mark.parametrize(
    "raw_format,depth,variant",
    [
        ("R12", 12, "mono"),
        ("SRGGB12", 12, "color"),
        ("R16", 16, "mono"),
        ("SRGGB16", 16, "color"),
    ],
)
def test_upstream_variant_uses_raw_mode(raw_format, depth, variant):
    modes = [{"size": (3856, 2180), "unpacked": raw_format, "bit_depth": depth}]
    assert imx678_variant(modes) == variant
    assert detect_camera_type("/base/axi/i2c/imx678@1a") == "imx678"


@pytest.mark.parametrize(
    "modes", [[], [{"size": (1920, 1080), "bit_depth": 12, "unpacked": "SRGGB12"}]]
)
def test_incompatible_driver_does_not_silently_change_geometry(modes):
    with pytest.raises(RuntimeError, match="upstream"):
        imx678_variant(modes)


@pytest.mark.parametrize("name,mono", [("imx678", True), ("imx678_color", False)])
def test_upstream_crop_preserves_geometry_and_bayer_phase(name, mono):
    profile = get_camera_profile(name)
    frame = np.zeros((2180, 3856), dtype=np.uint16)
    frame[0::2, 0::2] = 100
    frame[1::2, 1::2] = 200
    crop = profile.crop_and_rotate(frame)
    assert crop.shape == (2180, 2180)
    assert crop[0, 0] == 100
    assert crop[1, 1] == 200
    assert profile.mono is mono
    assert profile.radiometric_zero_point == 0
    assert build_optical_train(name, "16mm").fov_degrees > 0


def test_pisp_stride_is_removed_before_raw_publication():
    camera = CameraPI.__new__(CameraPI)
    camera._raw_size = (3856, 2180)
    camera._raw_shift = 4
    dma = np.full((2180, 3872), 65535, dtype=np.uint16)
    dma[:, :3856] = 123 << 4
    request = SimpleNamespace(make_array=lambda _: dma.view(np.uint8))
    result = camera._raw_array(request)
    assert result.shape == (2180, 3856)
    assert np.all(result == 123)
    assert dma[0, 0] == 123 << 4


def test_select_requires_preparation_and_preserves_current_camera(
    monkeypatch, tmp_path
):
    boot = tmp_path / "config.txt"
    original = "camera_auto_detect=1\ndtoverlay=imx462,clock-frequency=74250000\n"
    boot.write_text(original)
    monkeypatch.setattr(switch_camera, "get_boot_config_path", lambda: boot)
    with pytest.raises(RuntimeError, match="Prepare IMX678"):
        switch_camera.switch_boot("imx678")
    assert boot.read_text() == original


def test_switch_back_preserves_imx678_port_and_lanes(monkeypatch, tmp_path):
    boot = tmp_path / "config.txt"
    boot.write_text(
        "camera_auto_detect=1\ndtoverlay=imx462\n"
        "#dtoverlay=imx678-mfnavis,cam0,4lane\n"
    )
    (tmp_path / "overlays").mkdir()
    (tmp_path / "overlays/imx678-mfnavis.dtbo").touch()
    monkeypatch.setattr(switch_camera, "get_boot_config_path", lambda: boot)
    monkeypatch.setattr(callbacks, "get_boot_config_path", lambda: boot)
    switch_camera.switch_boot("imx678")
    assert "\ndtoverlay=imx678-mfnavis,cam0,4lane\n" in boot.read_text()
    assert "\ncamera_auto_detect=0\n" in boot.read_text()
    assert callbacks.get_camera_type(SimpleNamespace()) == ["imx678"]
    selected = boot.read_text()
    switch_camera.switch_boot("imx678")
    assert boot.read_text() == selected
    switch_camera.switch_boot("imx462")
    switch_camera.switch_boot("imx678")
    assert "\ndtoverlay=imx678-mfnavis,cam0,4lane\n" in boot.read_text()


def test_menu_selects_imx678_without_inheriting_variant(monkeypatch, tmp_path):
    boot = tmp_path / "config.txt"
    boot.write_text("dtoverlay=imx462\n")
    monkeypatch.setattr(callbacks, "get_boot_config_path", lambda: boot)
    system = Mock()
    monkeypatch.setattr(callbacks, "sys_utils", system)
    cfg = Mock()
    ui = SimpleNamespace(config_object=cfg, message=Mock())
    callbacks.switch_cam_imx678(ui)
    cfg.set_option.assert_not_called()
    system.switch_cam_imx678.assert_called_once()
    system.restart_system.assert_called_once()
