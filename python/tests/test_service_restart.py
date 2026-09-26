"""Restart failures must leave the UI usable instead of killing the service."""

from types import SimpleNamespace

import pytest

import PiFinder.i18n  # noqa: F401
from PiFinder import server, sys_utils
from PiFinder.ui import callbacks

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("exit_code,expected", [(0, True), (1, False)])
def test_restart_request_is_noninteractive(monkeypatch, exit_code, expected):
    requests = []

    def run(command, **options):
        requests.append((command, options))
        return SimpleNamespace(
            returncode=exit_code,
            stderr="sudo: a password is required" if exit_code else "",
        )

    monkeypatch.setattr(sys_utils.subprocess, "run", run)

    assert sys_utils.restart_pifinder() is expected
    command, options = requests[0]
    assert command == [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/systemctl",
        "--no-block",
        "restart",
        "mfnavis.service",
    ]
    assert options["timeout"] == 5


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("sudo"), sys_utils.subprocess.TimeoutExpired("sudo", 5)],
)
def test_restart_command_errors_are_reported(monkeypatch, error):
    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(sys_utils.subprocess, "run", run)
    assert sys_utils.restart_pifinder() is False


@pytest.mark.parametrize("accepted", [False, True])
def test_restart_callback_reports_failure(monkeypatch, accepted):
    messages = []
    monkeypatch.setattr(
        callbacks, "sys_utils", SimpleNamespace(restart_pifinder=lambda: accepted)
    )
    monkeypatch.setattr(callbacks, "_", lambda text: text, raising=False)
    callbacks.restart_pifinder(
        SimpleNamespace(message=lambda text, seconds: messages.append(text))
    )
    assert messages == (
        ["Restarting..."] if accepted else ["Restarting...", "Restart failed"]
    )


@pytest.mark.parametrize("accepted,status", [(False, 503), (True, 200)])
def test_web_restart_reports_request_result(monkeypatch, tmp_path, accepted, status):
    monkeypatch.setattr(server.config.utils, "data_dir", tmp_path)
    monkeypatch.setattr(server.config.utils, "runtime_dir", tmp_path)
    monkeypatch.setattr(server.sys_utils, "restart_pifinder", lambda: accepted)
    app = server.Server().app
    app.testing = True
    client = app.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True

    assert client.get("/system/restart_pifinder").status_code == status
