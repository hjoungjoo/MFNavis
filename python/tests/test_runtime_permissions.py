"""Installation permissions and failures must work without a field terminal."""

from pathlib import Path
import os
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sh

from PiFinder import server, sys_utils
from PiFinder.ui import callbacks

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.unit


def command_error():
    return sh.ErrorReturnCode_1("sudo cp", b"", b"password required: secret-value")


@pytest.mark.parametrize("user", ["mfnavis", "pifinder", "observer"])
def test_installed_policy_covers_device_commands(tmp_path, user):
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts/install_runtime_control.sh"),
            user,
            "--print-policy",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    policy = result.stdout
    assert all(
        line.startswith(f"{user} ALL=(root) NOPASSWD: ") for line in policy.splitlines()
    )
    for command in (
        "/usr/bin/cp /tmp/hostapd.conf /etc/hostapd/hostapd.conf",
        "/usr/bin/cp /tmp/etc_mfnavis_apsta_nat.conf /etc/mfnavis_apsta_nat.conf",
        f'{ROOT}/switch-apsta.sh ""',
        "/usr/sbin/shutdown -r now",
        "/usr/sbin/shutdown now",
        "/usr/bin/systemctl restart gpsd",
        "/usr/bin/systemctl restart indiwebmanager.service",
        "/usr/bin/nmcli -w 25 con up *",
        "/usr/sbin/modprobe uhid",
        "/usr/bin/python3 /usr/local/lib/mfnavis/switch_camera.py imx462",
    ):
        assert command in policy
    assert "NOPASSWD: ALL" not in policy
    assert "/usr/bin/bash -c" not in policy
    validator = shutil.which("visudo") or "/usr/sbin/visudo"
    if Path(validator).exists():
        path = tmp_path / "sudoers"
        path.write_text(policy)
        subprocess.run([validator, "-cf", str(path)], check=True, capture_output=True)


@pytest.mark.parametrize("user", ["root", "bad user", "observer\nALL"])
def test_policy_rejects_invalid_service_account(user):
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts/install_runtime_control.sh"),
            user,
            "--print-policy",
        ],
        capture_output=True,
    )
    assert result.returncode != 0
    assert not result.stdout


def test_initial_setup_installs_permissions_before_enabling_service():
    setup = (ROOT / "mfnavis_setup.sh").read_text()
    assert setup.index(
        'scripts/install_runtime_control.sh" "${MFNAVIS_USER}"'
    ) < setup.index("sudo systemctl enable mfnavis\n")
    update = (ROOT / "mfnavis_post_update.sh").read_text()
    assert update.index("MFNAVIS_CODE_UPDATE:-0") < update.index(
        "install_runtime_control.sh"
    )


@pytest.fixture
def web(monkeypatch, tmp_path):
    monkeypatch.setattr(server.config.utils, "data_dir", tmp_path)
    monkeypatch.setattr(server.config.utils, "runtime_dir", tmp_path)
    instance = server.Server()
    instance.app.testing = True
    client = instance.app.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
    return instance, client


@pytest.mark.parametrize("failure", [command_error(), PermissionError("secret-value")])
def test_network_permission_failure_does_not_restart_or_leak_output(web, failure):
    instance, client = web
    instance.network = Mock()
    instance.network.set_ap_security.side_effect = failure
    instance.app.jinja_env.get_template = Mock(
        return_value=SimpleNamespace(render=lambda **kw: kw.get("error_message", ""))
    )
    result = client.post("/network/update", data={"wifi_mode": "AP+STA", "apply": "1"})
    assert result.status_code == 503
    assert b"Could not save or apply" in result.data
    assert b"secret-value" not in result.data
    instance.network.set_wifi_mode.assert_not_called()


def test_web_reboot_permission_failure_is_reported(web, monkeypatch):
    _, client = web
    monkeypatch.setattr(
        server.sys_utils, "restart_system", Mock(side_effect=command_error())
    )
    result = client.get("/system/restart")
    assert result.status_code == 503
    assert b"secret-value" not in result.data


@pytest.mark.parametrize(
    "action",
    ["go_wifi_ap", "go_wifi_cli", "go_wifi_apsta", "shutdown", "restart_system"],
)
def test_menu_permission_failure_keeps_menu_alive(monkeypatch, action):
    messages = []
    monkeypatch.setattr(callbacks, "_", lambda text: text, raising=False)
    monkeypatch.setattr(callbacks.sys_utils, action, Mock(side_effect=command_error()))
    ui = SimpleNamespace(message=lambda text, seconds: messages.append(text))
    getattr(callbacks, action)(ui)
    assert messages[-1] == "Operation failed"


@pytest.mark.parametrize(
    "action",
    [
        "go_wifi_ap",
        "go_wifi_cli",
        "go_wifi_apsta",
        "shutdown",
        "restart_system",
        "switch_cam_imx477",
        "switch_cam_imx296",
        "switch_cam_imx462",
    ],
)
def test_privileged_requests_never_prompt(monkeypatch, action):
    sudo = Mock()
    monkeypatch.setattr(sys_utils.sh, "sudo", sudo)
    getattr(sys_utils, action)()
    assert sudo.call_args.args[0] == "-n"


def test_backup_cleanup_needs_no_root(monkeypatch, tmp_path):
    backup = tmp_path / "backup.zip"
    backup.write_bytes(b"old")
    monkeypatch.setattr(sys_utils, "BACKUP_PATH", str(backup))
    monkeypatch.setattr(sys_utils.sh, "sudo", Mock(side_effect=AssertionError("sudo")))
    sys_utils.remove_backup()
    sys_utils.remove_backup()
    assert not backup.exists()


def test_bt_pairing_keeps_wifi_up_without_restore_permission(monkeypatch):
    monkeypatch.setattr(sys_utils, "ensure_uhid_loaded", lambda: True)
    monkeypatch.setattr(sys_utils, "bt_pairing_needs_wifi_pause", lambda: True)
    run = Mock(return_value=SimpleNamespace(returncode=1))
    monkeypatch.setattr(sys_utils.subprocess, "run", run)
    assert sys_utils.pause_wifi_for_bt_pairing() is False
    assert run.call_count == 1
    assert run.call_args.args[0][:3] == ["sudo", "-n", "-l"]


def test_camera_helper_runs_outside_app_directory(tmp_path):
    helper = tmp_path / "switch_camera.py"
    shutil.copy(ROOT / "python/MFNavis/switch_camera.py", helper)
    boot = tmp_path / "config.txt"
    boot.write_text("camera_auto_detect=1\n")
    (tmp_path / "boot_config.py").write_text(
        f"from pathlib import Path\ndef get_boot_config_path(): return Path({str(boot)!r})\n"
    )
    subprocess.run(["/usr/bin/python3", str(helper), "imx462"], cwd="/", check=True)
    assert "dtoverlay=imx462,clock-frequency=74250000" in boot.read_text()


@pytest.mark.parametrize("ap_active", [False, True])
def test_restore_helper_restores_connection_and_only_existing_ap(tmp_path, ap_active):
    calls = tmp_path / "calls"
    for name in ("nmcli", "ip", "systemctl", "sleep", "cat"):
        command = tmp_path / name
        command.write_text(
            "#!/bin/bash\n"
            f'printf "%s|%s\\n" "{name}" "$*" >> "$CALLS"\n'
            + ("echo 12345678-1234-1234-1234-123456789abc\n" if name == "cat" else "")
            + (
                'if [[ "$1" == is-active ]]; then exit "$AP_STATUS"; fi\n'
                if name == "systemctl"
                else ""
            )
            + "exit 0\n"
        )
        command.chmod(0o755)
    env = dict(
        os.environ,
        PATH=str(tmp_path),
        CALLS=str(calls),
        AP_STATUS="0" if ap_active else "3",
    )
    subprocess.run(
        ["/bin/bash", str(ROOT / "scripts/restore_wifi.sh"), "42"],
        env=env,
        check=True,
    )
    requests = calls.read_text()
    assert "sleep|42" in requests
    assert "nmcli|radio wifi on" in requests
    assert "nmcli|connection up uuid 12345678-1234-1234-1234-123456789abc" in requests
    assert "ip|link set uap0 up" in requests
    assert ("systemctl|restart hostapd" in requests) is ap_active
