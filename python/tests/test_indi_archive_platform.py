"""Unsupported archive ABIs must be rejected before system installation."""

import os
from pathlib import Path
import subprocess

import pytest


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "codename,architecture,python_version,expected",
    [
        ("bookworm", "aarch64", "3.11", 0),
        ("trixie", "aarch64", "3.13", 0),
        ("trixie", "aarch64", "3.11", 1),
        ("bookworm", "aarch64", "3.13", 1),
        ("bookworm", "armv7l", "3.11", 1),
        ("bookworm", "x86_64", "3.11", 1),
        ("", "aarch64", "3.11", 1),
    ],
)
def test_archive_platform_compatibility(
    codename, architecture, python_version, expected
):
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; check_indi_archive_platform "$2" "$3" "$4"',
            "platform-test",
            str(SCRIPTS / "indi_archive_platform.sh"),
            codename,
            architecture,
            python_version,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected
    if expected:
        assert "Bookworm/Python 3.11 or Trixie/Python 3.13" in result.stderr


@pytest.mark.parametrize(
    "script,args",
    [
        ("package_indi_mount_archive.sh", []),
        ("install_indi_mount_archive.sh", ["absent.tar.gz"]),
    ],
)
def test_scripts_reject_platform_before_build_or_install(tmp_path, script, args):
    # Fake a non-ARM host. Reaching mktemp/sudo would imply that the platform
    # guard ran too late and risked changing a running installation.
    (tmp_path / "uname").write_text("#!/bin/sh\necho x86_64\n")
    (tmp_path / "uname").chmod(0o755)
    for name in ("sudo", "mktemp"):
        command = tmp_path / name
        command.write_text('#!/bin/sh\necho "unexpected mutation" >&2\nexit 99\n')
        command.chmod(0o755)
    result = subprocess.run(
        ["bash", str(SCRIPTS / script), *args],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Bookworm/Python 3.11 or Trixie/Python 3.13" in result.stderr
    assert "unexpected mutation" not in result.stderr
