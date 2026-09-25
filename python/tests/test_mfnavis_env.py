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
