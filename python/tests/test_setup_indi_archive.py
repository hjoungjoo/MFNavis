"""Setup must install a matching archive into the app's Python environment."""

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/mfnavis_setup_runtime.sh"
pytestmark = pytest.mark.unit


@pytest.fixture
def installation(tmp_path):
    repo = tmp_path / "MFNavis"
    (repo / "dist").mkdir(parents=True)
    (repo / "scripts").mkdir()
    # Observe both verification and installation without changing the host.
    (repo / "scripts/install_indi_mount_archive.sh").write_text(
        '#!/bin/bash\nprintf "%s|%s|%s\\n" "$MFNAVIS_PYTHON" "$1" '
        '"${2:-install}" >> "$CALLS"\nexit "${INSTALLER_STATUS:-0}"\n'
    )
    return repo


def run_helper(repo, script, **overrides):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("MFNAVIS_")
    }
    env.update(
        MFNAVIS_REPO_DIR=str(repo),
        MFNAVIS_OS_CODENAME="trixie",
        MFNAVIS_PYTHON=str(repo / ".venv-trixie/bin/python"),
        CALLS=str(repo / "calls.log"),
    )
    env.update(overrides)
    return subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; source "$1"; ' + script,
            "test",
            str(HELPER),
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def archive(repo, codename="trixie", version="2.2.3.1", suffix=""):
    path = repo / "dist" / f"mfnavis-indi-{codename}-arm64-v{version}.tar.gz"
    Path(str(path) + suffix).touch()
    return path


@pytest.mark.parametrize("codename", ["bookworm", "trixie"])
def test_selects_only_current_os(installation, codename):
    chosen = archive(installation, codename)
    archive(installation, "bookworm" if codename == "trixie" else "trixie", "99")
    result = run_helper(
        installation, "find_mfnavis_indi_archive", MFNAVIS_OS_CODENAME=codename
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(chosen)


def test_newer_split_archive_beats_older_full_archive(installation):
    archive(installation, version="2.9")
    chosen = archive(installation, version="2.10", suffix=".part-00")
    result = run_helper(installation, "find_mfnavis_indi_archive")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(chosen)


@pytest.mark.parametrize("mode", [None, "true", "auto", "YES"])
def test_missing_required_archive_fails_without_installer(installation, mode):
    env = {} if mode is None else {"MFNAVIS_INSTALL_INDI_ARCHIVE": mode}
    result = run_helper(installation, "mfnavis_prepare_indi_archive", **env)
    assert result.returncode == 1
    assert "Required INDI archive not found for trixie" in result.stderr
    assert not (installation / "calls.log").exists()


@pytest.mark.parametrize("mode,expected", [("false", 0), ("off", 0), ("invalid", 1)])
def test_explicit_modes(installation, mode, expected):
    result = run_helper(
        installation,
        "mfnavis_prepare_indi_archive; mfnavis_install_setup_indi",
        MFNAVIS_INSTALL_INDI_ARCHIVE=mode,
    )
    assert result.returncode == expected
    assert not (installation / "calls.log").exists()


@pytest.mark.parametrize("split", [False, True])
def test_explicit_archive_and_same_app_python(installation, split):
    archive(installation, version="99")
    chosen = archive(installation, suffix=".part-00" if split else "")
    # A fake executable stands in for an already created app environment.
    interpreter = installation / ".venv-trixie/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("#!/bin/sh\nexit 0\n")
    interpreter.chmod(0o755)
    result = run_helper(
        installation,
        "mfnavis_prepare_indi_archive; mfnavis_install_setup_indi",
        MFNAVIS_INDI_ARCHIVE=str(chosen) + (".part-00" if split else ""),
    )
    assert result.returncode == 0, result.stderr
    assert (installation / "calls.log").read_text().splitlines() == [
        f"{interpreter}|{chosen}|--verify-only",
        f"{interpreter}|{chosen}|install",
    ]


def test_new_environment_preflight_uses_host_python(installation):
    chosen = archive(installation)
    result = run_helper(installation, "mfnavis_prepare_indi_archive")
    assert result.returncode == 0, result.stderr
    assert (installation / "calls.log").read_text().strip() == (
        f"/usr/bin/python3|{chosen}|--verify-only"
    )


def test_verification_failure_stops_before_python_or_install(installation):
    archive(installation)
    result = run_helper(
        installation,
        "mfnavis_prepare_indi_archive; echo unexpected; mfnavis_install_setup_indi",
        INSTALLER_STATUS="17",
    )
    assert result.returncode == 17
    assert "unexpected" not in result.stdout
    assert len((installation / "calls.log").read_text().splitlines()) == 1


def test_install_failure_propagates(installation):
    chosen = archive(installation)
    result = run_helper(
        installation,
        'MFNAVIS_SELECTED_INDI_ARCHIVE="$MFNAVIS_INDI_ARCHIVE"; '
        "mfnavis_install_setup_indi; echo unexpected",
        MFNAVIS_INDI_ARCHIVE=str(chosen),
        INSTALLER_STATUS="19",
    )
    assert result.returncode == 19
    assert "unexpected" not in result.stdout


@pytest.mark.parametrize("codename", ["bookworm", "trixie"])
def test_service_units_use_app_python(installation, codename):
    # Capture sudo tee inputs in the temporary repository, with no host writes.
    script = """
sudo() {
    if [[ "$1" == install ]]; then return 0; fi
    [[ "$1" == tee ]] || return 99
    case "$2" in
        */mfnavis.service.d/*) cat > "$MFNAVIS_REPO_DIR/main.conf" ;;
        */mfnavis_splash.service.d/*) cat > "$MFNAVIS_REPO_DIR/splash.conf" ;;
        *) return 99 ;;
    esac
}
mfnavis_configure_python_services
"""
    interpreter = (
        "/usr/bin/python3"
        if codename == "bookworm"
        else str(installation / ".venv-trixie/bin/python")
    )
    result = run_helper(
        installation,
        script,
        MFNAVIS_PYTHON=interpreter,
        MFNAVIS_OS_CODENAME=codename,
    )
    assert result.returncode == 0, result.stderr
    for filename, module in [("main.conf", "main"), ("splash.conf", "splash")]:
        assert (installation / filename).read_text() == (
            f'[Service]\nExecStart=\nExecStart="{interpreter}" -m MFNavis.{module}\n'
        )


@pytest.mark.parametrize("codename", ["bookworm", "trixie"])
def test_python_dependencies_follow_os_and_gpio_needs(installation, codename):
    interpreter = installation / "app-venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text('#!/bin/bash\nprintf "python %s\\n" "$*" >> "$CALLS"\n')
    interpreter.chmod(0o755)
    script = """
mfnavis_board_profile() { echo pi5_class; }
sudo() {
    if [[ "$1" == "$MFNAVIS_PYTHON" ]]; then "$@"; return; fi
    printf 'sudo %s\n' "$*" >> "$CALLS"
}
mfnavis_install_setup_python
"""
    result = run_helper(
        installation,
        script,
        MFNAVIS_OS_CODENAME=codename,
        MFNAVIS_PYTHON=str(interpreter),
    )
    assert result.returncode == 0, result.stderr
    calls = (installation / "calls.log").read_text()
    if codename == "trixie":
        assert "requirements-trixie.txt" in calls
        assert "-m pip uninstall -y RPi.GPIO" in calls
        assert "sudo apt-get install -y python3-rpi-lgpio" in calls
        assert "--break-system-packages" not in calls
    else:
        assert "--break-system-packages" in calls
        assert "requirements.txt" in calls
        assert "pip uninstall" not in calls
