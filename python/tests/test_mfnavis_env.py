"""Keep installer settings and runtime configuration names in sync."""

import os
from pathlib import Path
import pwd
import subprocess

import pytest


REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.unit


def _source_paths(script: str, *args: str, home: Path) -> str:
    env = {
        **os.environ,
        "MFNAVIS_USER": pwd.getpwuid(os.getuid()).pw_name,
        "MFNAVIS_HOME": str(home),
        "MFNAVIS_REPO_DIR": str(REPO),
    }
    env.pop("MFNAVIS_DATA_DIR", None)
    return subprocess.check_output(
        [
            "bash",
            "-c",
            'source "$1"\n' + script,
            "bash",
            str(REPO / "mfnavis_paths.sh"),
            *args,
        ],
        env=env,
        text=True,
    )


def test_paths_export_mfnavis_defaults_and_render_template(tmp_path):
    source = tmp_path / "template"
    output = tmp_path / "rendered"
    source.write_text("__MFNAVIS_USER__:__MFNAVIS_REPO_DIR__:__MFNAVIS_DATA_DIR__")
    result = _source_paths(
        'sudo() { "$@"; }\n'
        'mfnavis_render_config "$2" "$3"\n'
        'printf "%s:%s:%s" "$MFNAVIS_USER" "$MFNAVIS_GROUP" "$MFNAVIS_DATA_DIR"',
        str(source),
        str(output),
        home=tmp_path,
    )
    user = pwd.getpwuid(os.getuid()).pw_name
    group = subprocess.check_output(["id", "-gn", user], text=True).strip()
    assert result == f"{user}:{group}:{tmp_path}/MFNavis_data"
    assert output.read_text() == f"{user}:{REPO}:{tmp_path}/MFNavis_data"


@pytest.mark.parametrize(
    ("helper", "old_key", "new_key", "value"),
    [
        (
            "mfnavis_prepare_apsta_nat_config",
            "PIFINDER_APSTA_SHARE_INTERNET",
            "MFNAVIS_APSTA_SHARE_INTERNET",
            "1",
        ),
        (
            "mfnavis_prepare_sta_band_config",
            "PIFINDER_STA_BAND",
            "MFNAVIS_STA_BAND",
            "5",
        ),
    ],
)
def test_existing_mfnavis_setting_keeps_value_on_key_rename(
    tmp_path, helper, old_key, new_key, value
):
    config = tmp_path / "setting.conf"
    config.write_text(f"# existing MFNavis setting\n{old_key}={value}\n")
    _source_paths(
        'sudo() { "$@"; }\n' + f'{helper} "$2"',
        str(config),
        home=tmp_path,
    )
    assert config.read_text() == f"# existing MFNavis setting\n{new_key}={value}\n"


def test_existing_new_setting_takes_priority_over_old_key(tmp_path):
    config = tmp_path / "mfnavis_apsta_nat.conf"
    config.write_text(
        "PIFINDER_APSTA_SHARE_INTERNET=1\nMFNAVIS_APSTA_SHARE_INTERNET=0\n"
    )
    _source_paths(
        'sudo() { "$@"; }\nmfnavis_prepare_apsta_nat_config "$2"',
        str(config),
        home=tmp_path,
    )
    assert config.read_text() == "MFNAVIS_APSTA_SHARE_INTERNET=0\n"


@pytest.mark.parametrize(
    "model",
    ["Raspberry Pi Compute Module 5", "Raspberry Pi 5 Model B", "Raspberry Pi 4"],
)
def test_keypad_boot_leaves_reset_free_and_legacy_pwm_available(tmp_path, model):
    boot = tmp_path / "config.txt"
    boot.write_text(
        "[all]\ndtparam=i2c_arm=on\ndtoverlay=imx678-mfnavis-cm5-converter\n"
        "dtoverlay=pwm,pin=13,func=4\n"
        "  dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4\n"
        "[pi4]\ndtparam=spi=on\n"
    )
    script = """
sudo() { "$@"; }
TEST_BOARD_MODEL="$3"
mfnavis_board_model() { printf '%s' "$TEST_BOARD_MODEL"; }
mfnavis_configure_keypad_boot "$2"
"""
    _source_paths(script, str(boot), model, home=tmp_path)
    first = boot.read_text()
    assert first.endswith(
        "[all]\ngpio=12=op,dl,pd\ndtoverlay=pwm,pin=13,func=4\n# END MFNavis keypad\n"
    )
    assert "dtparam=i2c_arm=on" in first
    assert "dtoverlay=imx678-mfnavis-cm5-converter" in first
    assert "[pi4]\ndtparam=spi=on" in first
    assert first.count("dtoverlay=pwm") == 1
    assert "pwm-2chan" not in first
    _source_paths(script, str(boot), model, home=tmp_path)
    assert boot.read_text() == first


@pytest.mark.parametrize(
    "model,hardware",
    [
        ("Raspberry Pi Compute Module 5", True),
        ("Raspberry Pi 5 Model B", True),
        ("Raspberry Pi 4", False),
        ("Raspberry Pi 3", False),
    ],
)
def test_i2c_boot_normalizes_conflicts_and_preserves_other_hardware(
    tmp_path, model, hardware
):
    boot = tmp_path / "config.txt"
    preserved = (
        "dtoverlay=imx678-mfnavis-cm5-converter\n"
        "dtparam=fan_temp0_speed=200\n"
        "dtparam=i2c_vc=on\n"
        "dtparam=i2c_arm=off,spi=on\n"
    )
    boot.write_text(
        "[all]\ndtparam=i2c_arm=on\n"
        "  dtparam=i2c_arm_baudrate=100000 # old speed\n"
        "dtoverlay=i2c-gpio,i2c_gpio_sda=2,i2c_gpio_scl=3,bus=3\n"
        + preserved
        + "[pi4]\ndtparam=i2c_arm=off\n"
    )
    script = """
sudo() { "$@"; }
TEST_BOARD_MODEL="$3"
mfnavis_board_model() { printf '%s' "$TEST_BOARD_MODEL"; }
mfnavis_configure_i2c_boot "$2"
"""
    _source_paths(script, str(boot), model, home=tmp_path)
    first = boot.read_text()
    assert preserved in first
    assert "100000" not in first
    block = first.split("# BEGIN MFNavis I2C\n")[1]
    assert block.startswith("[all]\n")
    if hardware:
        assert "dtparam=i2c_arm=on\ndtparam=i2c_arm_baudrate=400000\n" in block
        assert "dtoverlay=i2c-gpio" not in first
    else:
        assert "dtparam=i2c_arm=off\n" in block
        assert "dtoverlay=i2c-gpio,i2c_gpio_sda=2,i2c_gpio_scl=3,bus=3\n" in block
        assert "baudrate=" not in first
    _source_paths(script, str(boot), model, home=tmp_path)
    assert boot.read_text() == first
