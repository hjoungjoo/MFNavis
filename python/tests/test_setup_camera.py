"""Run camera setup decisions without installing packages or changing hardware."""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/mfnavis_setup_camera.sh"
pytestmark = pytest.mark.unit


@pytest.fixture
def setup_camera(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts/install_imx678.sh").write_text(
        'printf "check %s\\n" "$*" >> "$EVENTS"\nexit "${CHECK_RESULT:-0}"\n'
    )
    boot = tmp_path / "config.txt"
    boot.write_text("dtoverlay=imx462,cam0\n")
    events = tmp_path / "events"

    def invoke(camera=None, mode=None, model="Raspberry Pi Compute Module 5", **extra):
        events.write_text("")
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("MFNAVIS_CAMERA", "MFNAVIS_INSTALL_IMX678")
        }
        env.update(
            MFNAVIS_REPO_DIR=str(repo),
            MFNAVIS_USER="testuser",
            MFNAVIS_OS_CODENAME="trixie",
            BOOT_CONFIG=str(boot),
            EVENTS=str(events),
            BOARD_MODEL=model,
            HELPER=str(HELPER),
        )
        if camera is not None:
            env["MFNAVIS_CAMERA"] = camera
        if mode is not None:
            env["MFNAVIS_INSTALL_IMX678"] = mode
        env.update(extra)
        result = subprocess.run(
            [
                "bash",
                "-c",
                """
set -eu
source "$HELPER"
mfnavis_board_model() { printf '%s' "$BOARD_MODEL"; }
mfnavis_board_profile() {
    case "$BOARD_MODEL" in *'Pi 5'*|*'Module 5'*) echo pi5_class;; *) echo pi4;; esac
}
sudo() {
    printf '%s\n' "$*" >> "$EVENTS"
    return "${INSTALL_RESULT:-0}"
}
mfnavis_install_setup_camera
""",
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        return result, events.read_text().splitlines()

    return invoke, boot


def test_default_cm5_prepares_support_then_preserves_sensor(setup_camera):
    invoke, boot = setup_camera
    before = boot.read_text()
    result, events = invoke()
    assert result.returncode == 0, result.stderr
    assert len(events) == 3
    assert events[0].endswith("install_imx678.sh --install")
    assert events[1] == "check --check"
    assert events[2].endswith("-m MFNavis.switch_camera --default imx462")
    assert boot.read_text() == before


def test_fresh_setup_installs_support_but_selects_imx462(setup_camera):
    invoke, boot = setup_camera
    boot.write_text("camera_auto_detect=1\n")
    result, events = invoke()
    assert result.returncode == 0, result.stderr
    assert events[0].endswith("install_imx678.sh --install")
    assert events[1] == "check --check"
    assert events[2].endswith("-m MFNavis.switch_camera --default imx462")
    assert not any("--activate-converter" in event for event in events)


def test_converter_install_selects_board_without_imx462_fallback(setup_camera):
    invoke, _ = setup_camera
    result, events = invoke(camera="imx678-cm5-converter")
    assert result.returncode == 0, result.stderr
    assert len(events) == 2
    assert events[0].endswith("install_imx678.sh --activate-converter")
    assert events[1] == "check --check"


def test_generic_imx678_prepares_before_switching(setup_camera):
    invoke, _ = setup_camera
    result, events = invoke(camera="imx678", model="Raspberry Pi 5")
    assert result.returncode == 0, result.stderr
    assert events[0].endswith("install_imx678.sh --install")
    assert events[-1].endswith("-m MFNavis.switch_camera imx678")


@pytest.mark.parametrize("failure", ["INSTALL_RESULT", "CHECK_RESULT"])
def test_driver_failure_stops_before_camera_selection(setup_camera, failure):
    invoke, _ = setup_camera
    result, events = invoke(camera="imx678", **{failure: "1"})
    assert result.returncode != 0
    assert not any("switch_camera" in event for event in events)


@pytest.mark.parametrize(
    "options",
    [
        {"camera": "invalid"},
        {"mode": "tru"},
        {"camera": "imx678", "mode": "false"},
        {"camera": "imx678-cm5-converter", "model": "Raspberry Pi 5"},
    ],
)
def test_invalid_configuration_fails_before_mutation(setup_camera, options):
    invoke, _ = setup_camera
    result, events = invoke(**options)
    assert result.returncode != 0
    assert not events


def test_opt_out_preserves_default_camera_behavior(setup_camera):
    invoke, _ = setup_camera
    result, events = invoke(mode="false")
    assert result.returncode == 0, result.stderr
    assert len(events) == 1
    assert events[0].endswith("--default imx462")


def test_other_boards_do_not_install_imx678_automatically(setup_camera):
    invoke, _ = setup_camera
    result, events = invoke(model="Raspberry Pi 4")
    assert result.returncode == 0, result.stderr
    assert len(events) == 1
    assert events[0].endswith("--default imx462")


def test_bookworm_opt_in_and_existing_imx678(setup_camera):
    invoke, boot = setup_camera
    result, events = invoke(MFNAVIS_OS_CODENAME="bookworm")
    assert result.returncode == 0
    assert len(events) == 1
    boot.write_text("dtoverlay=imx678-mfnavis-cm5-converter\n")
    result, events = invoke(MFNAVIS_OS_CODENAME="bookworm")
    assert result.returncode == 0
    assert events[0].endswith("install_imx678.sh --install")
    result, events = invoke(mode="false")
    assert result.returncode != 0
    assert not events


def test_commented_imx678_does_not_force_installation(setup_camera):
    invoke, boot = setup_camera
    boot.write_text("#dtoverlay=imx678-mfnavis-cm5-converter\ndtoverlay=imx477\n")
    result, events = invoke(mode="false")
    assert result.returncode == 0
    assert len(events) == 1


def test_kernel_targets_include_pending_kernel_and_require_headers(tmp_path):
    source = (ROOT / "scripts/install_imx678.sh").read_text()
    function = source.split("imx678_kernel_targets() {\n", 1)[1].split("\n}\n", 1)[0]
    script = (
        "imx678_kernel_targets() {\n" + function + '\n}\nimx678_kernel_targets "$1"'
    )
    for name in ("6.18.50+rpt-rpi-2712", "6.18.51+rpt-rpi-2712", "6.18.51+rpt-rpi-v8"):
        (tmp_path / name / "build").mkdir(parents=True)

    def targets():
        return subprocess.run(
            ["bash", "-c", script, "test", str(tmp_path)],
            env={**os.environ, "KERNEL": "6.18.50+rpt-rpi-2712"},
            capture_output=True,
            text=True,
        )

    result = targets()
    assert result.returncode == 0, result.stderr
    assert set(result.stdout.splitlines()) == {
        "6.18.50+rpt-rpi-2712",
        "6.18.51+rpt-rpi-2712",
    }
    (tmp_path / "6.18.51+rpt-rpi-2712/build").rmdir()
    result = targets()
    assert result.returncode != 0
    assert "Missing headers for 6.18.51+rpt-rpi-2712" in result.stderr
