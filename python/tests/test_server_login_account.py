"""Web credentials follow the OS account selected for the MFNavis service."""

from types import SimpleNamespace

import pytest

from PiFinder import server as server_module


@pytest.fixture
def login_client(monkeypatch):
    monkeypatch.setattr(
        server_module,
        "pwd",
        SimpleNamespace(getpwuid=lambda uid: SimpleNamespace(pw_name="observer")),
    )
    server = server_module.Server()
    server.app.testing = True
    return server.app.test_client()


@pytest.mark.unit
def test_login_authenticates_service_account(login_client, monkeypatch):
    calls = []

    def verify(username, password):
        calls.append((username, password))
        return password == "correct"

    monkeypatch.setattr(server_module.sys_utils, "verify_password", verify)

    rejected = login_client.post("/login", data={"password": "wrong"})
    accepted = login_client.post("/login", data={"password": "correct"})

    assert rejected.status_code == 200
    assert accepted.status_code == 302
    assert calls == [("observer", "wrong"), ("observer", "correct")]


@pytest.mark.unit
def test_password_change_targets_service_account(login_client, monkeypatch):
    calls = []

    def change(username, current_password, new_password):
        calls.append((username, current_password, new_password))
        return True

    monkeypatch.setattr(server_module.sys_utils, "change_password", change)
    with login_client.session_transaction() as session:
        session["authenticated"] = True

    response = login_client.post(
        "/tools/pwchange",
        data={
            "current_password": "old",
            "new_passworda": "new",
            "new_passwordb": "new",
        },
    )

    assert response.status_code == 200
    assert calls == [("observer", "old", "new")]
