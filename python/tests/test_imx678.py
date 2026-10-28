"""Upstream IMX678 RAW geometry, PiSP padding, and deferred camera selection."""

from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path
import shutil
import subprocess
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


@pytest.mark.parametrize(
    "model,overlay",
    [
        ("Raspberry Pi Compute Module 5 Rev 1.0\x00", "imx678-mfnavis-cm5-converter"),
        (
            "Raspberry Pi Compute Module 5 Lite Rev 1.0\x00",
            "imx678-mfnavis-cm5-converter",
        ),
        ("Raspberry Pi 5 Model B Rev 1.0\x00", "imx678-mfnavis"),
        ("Raspberry Pi 4 Model B Rev 1.4\x00", "imx678-mfnavis"),
    ],
)
def test_default_overlay_matches_board(tmp_path, model, overlay):
    model_path = tmp_path / "model"
    model_path.write_text(model)
    assert switch_camera._default_imx678_overlay(model_path) == overlay


def test_no_board_model_keeps_generic_default(tmp_path):
    assert (
        switch_camera._default_imx678_overlay(tmp_path / "absent") == "imx678-mfnavis"
    )


@pytest.mark.parametrize("other_camera", ["imx462", "imx296", "imx477"])
def test_fresh_cm5_menu_selection_needs_no_install_options(
    monkeypatch, tmp_path, other_camera
):
    # Ordinary setup has installed both overlays, with no saved IMX678 profile.
    boot = tmp_path / "config.txt"
    boot.write_text("camera_auto_detect=1\n")
    (tmp_path / "overlays").mkdir()
    for name in ("imx678-mfnavis", "imx678-mfnavis-cm5-converter"):
        (tmp_path / "overlays" / f"{name}.dtbo").touch()
    monkeypatch.setattr(switch_camera, "get_boot_config_path", lambda: boot)
    monkeypatch.setattr(callbacks, "get_boot_config_path", lambda: boot)
    monkeypatch.setattr(
        switch_camera,
        "_default_imx678_overlay",
        lambda: "imx678-mfnavis-cm5-converter",
    )
    switch_camera.ensure_default_boot()
    assert "imx678" not in boot.read_text()
    system = Mock()
    system.switch_cam_imx678.side_effect = lambda: switch_camera.switch_boot("imx678")
    monkeypatch.setattr(callbacks, "sys_utils", system)
    ui = SimpleNamespace(config_object=Mock(), message=Mock())
    callbacks.switch_cam_imx678(ui)
    expected = "[all]\ncamera_auto_detect=0\ndtoverlay=imx678-mfnavis-cm5-converter\n"
    assert boot.read_text().endswith(expected)
    system.restart_system.assert_called_once()
    # Selecting the already-active sensor is idempotent and does not reboot.
    selected = boot.read_text()
    callbacks.switch_cam_imx678(ui)
    assert boot.read_text() == selected
    system.restart_system.assert_called_once()
    switch_camera.switch_boot(other_camera)
    callbacks.switch_cam_imx678(ui)
    assert boot.read_text().endswith(expected)
    assert system.restart_system.call_count == 2
    assert (
        sum(line.startswith("dtoverlay=imx") for line in boot.read_text().splitlines())
        == 1
    )


def test_first_pi5_selection_remains_generic(monkeypatch, tmp_path):
    boot = tmp_path / "config.txt"
    boot.write_text("dtoverlay=imx462\n")
    (tmp_path / "overlays").mkdir()
    (tmp_path / "overlays/imx678-mfnavis.dtbo").touch()
    monkeypatch.setattr(switch_camera, "get_boot_config_path", lambda: boot)
    monkeypatch.setattr(
        switch_camera, "_default_imx678_overlay", lambda: "imx678-mfnavis"
    )
    switch_camera.switch_boot("imx678")
    assert boot.read_text().endswith("dtoverlay=imx678-mfnavis\n")


def test_cm5_never_falls_back_when_converter_overlay_is_missing(monkeypatch, tmp_path):
    boot = tmp_path / "config.txt"
    original = "dtoverlay=imx462\n"
    boot.write_text(original)
    (tmp_path / "overlays").mkdir()
    (tmp_path / "overlays/imx678-mfnavis.dtbo").touch()
    monkeypatch.setattr(switch_camera, "get_boot_config_path", lambda: boot)
    monkeypatch.setattr(
        switch_camera,
        "_default_imx678_overlay",
        lambda: "imx678-mfnavis-cm5-converter",
    )
    with pytest.raises(RuntimeError, match="Prepare IMX678"):
        switch_camera.switch_boot("imx678")
    assert boot.read_text() == original


def test_installed_menu_helper_runs_without_app_python_environment(tmp_path):
    boot = tmp_path / "config.txt"
    boot.write_text("camera_auto_detect=1\n")
    (tmp_path / "overlays").mkdir()
    for name in ("imx678-mfnavis", "imx678-mfnavis-cm5-converter"):
        (tmp_path / "overlays" / f"{name}.dtbo").touch()
    # Same standalone layout as /usr/local/lib/mfnavis; only boot destination
    # is redirected. Board detection reads the real host, without touching it.
    helper = tmp_path / "switch_camera.py"
    shutil.copy(Path(switch_camera.__file__), helper)
    (tmp_path / "boot_config.py").write_text(
        f"from pathlib import Path\ndef get_boot_config_path(): return Path({str(boot)!r})\n"
    )

    def select(*args):
        subprocess.run([sys.executable, str(helper), *args], check=True)

    select("--default", "imx462")
    assert "dtoverlay=imx462,clock-frequency=74250000" in boot.read_text()
    assert "imx678" not in boot.read_text()
    expected = f"dtoverlay={switch_camera._default_imx678_overlay()}\n"
    select("imx678")
    assert boot.read_text().endswith(expected)
    select("imx462")
    select("imx678")
    assert boot.read_text().endswith(expected)


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


def test_converter_activation_is_unique_global_and_survives_menu_switch(
    monkeypatch, tmp_path
):
    boot = tmp_path / "config.txt"
    boot.write_text(
        "dtoverlay=imx462\n[pi4]\ncamera_auto_detect=0\n"
        "#dtoverlay=imx678-mfnavis,cam0,4lane\n"
        "#dtoverlay=imx678-mfnavis-cm5-converter\n"
    )
    (tmp_path / "overlays").mkdir()
    (tmp_path / "overlays/imx678-mfnavis-cm5-converter.dtbo").touch()
    monkeypatch.setattr(switch_camera, "get_boot_config_path", lambda: boot)
    switch_camera.switch_boot("imx678", converter=True)
    expected = boot.read_text()
    assert expected.endswith(
        "[all]\ncamera_auto_detect=0\ndtoverlay=imx678-mfnavis-cm5-converter\n"
    )
    assert sum(line.startswith("dtoverlay=imx") for line in expected.splitlines()) == 1
    switch_camera.switch_boot("imx678")
    assert boot.read_text() == expected
    switch_camera.switch_boot("imx462")
    switch_camera.switch_boot("imx678")
    assert boot.read_text().endswith(
        "[all]\ncamera_auto_detect=0\ndtoverlay=imx678-mfnavis-cm5-converter\n"
    )


def test_converter_requires_its_own_overlay_before_editing(monkeypatch, tmp_path):
    boot = tmp_path / "config.txt"
    original = "dtoverlay=imx462\n"
    boot.write_text(original)
    (tmp_path / "overlays").mkdir()
    (tmp_path / "overlays/imx678-mfnavis.dtbo").touch()
    monkeypatch.setattr(switch_camera, "get_boot_config_path", lambda: boot)
    with pytest.raises(RuntimeError, match="Prepare IMX678"):
        switch_camera.switch_boot("imx678", converter=True)
    assert boot.read_text() == original
