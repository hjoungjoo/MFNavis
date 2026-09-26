"""Limit writes require complete vectors and fresh server confirmation."""

import xml.etree.ElementTree as ET

import pytest

from PiFinder import indi_limits as mod
from PiFinder import server
from test_server_serial_auto import serial_client as base_serial_client

pytestmark = pytest.mark.unit
VALUES = {"horizon": -10, "overhead": 85, "meridian_east": 20, "meridian_west": -20}
DEVICE = "LX200 OnStepX"


@pytest.fixture
def serial_client(monkeypatch, tmp_path):
    return base_serial_client.__wrapped__(monkeypatch, tmp_path)


@pytest.mark.parametrize("key", VALUES)
@pytest.mark.parametrize("value", ["", "nan", "inf", "1.5", "wrong", "999"])
def test_invalid_values_never_open_connection(monkeypatch, key, value):
    monkeypatch.setattr(
        mod, "_LimitConnection", lambda *a: pytest.fail("opened connection")
    )
    with pytest.raises(ValueError):
        mod.apply_limits(
            {**VALUES, key: value},
            server_host="host",
            server_port=7624,
            device_name=DEVICE,
        )


def vector(name, values, tag="setNumberVector", state="Ok", **attrs):
    e = ET.Element(tag, device=DEVICE, name=name, state=state, **attrs)
    for key, value in values.items():
        ET.SubElement(e, "oneNumber", name=key).text = str(value)
    return e


@pytest.fixture
def peer(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])

    class Peer:
        commands = []
        closed = False
        outcome = "success"
        current = None
        count = 0

        def send(self, command):
            self.commands.append(command)
            self.current = command
            self.count = 0

        def events(self):
            clock[0] += 0.75
            self.count += 1
            if self.current.tag == "getProperties":
                return [
                    vector("CONNECTION", {"CONNECT": "On"}, tag="defSwitchVector"),
                    vector(
                        "Slew elevation Limit",
                        {"minAlt": -10, "maxAlt": 80},
                        tag="defNumberVector",
                        perm="rw",
                    ),
                    vector(
                        "Minutes Past Meridian",
                        {"East": 20, "West": -20},
                        tag="defNumberVector",
                        perm="rw",
                    ),
                ]
            name = self.current.get("name")
            values = {c.get("name"): c.text for c in self.current}
            if self.outcome == "error":
                return [
                    ET.Element(
                        "message",
                        device=DEVICE,
                        message="[ERROR] Controller rejected limits",
                    ),
                    vector(name, values),
                ]
            if self.outcome == "alert":
                return [
                    vector(name, values, state="Alert"),
                    vector(name, values, state="Idle"),
                ]
            if self.outcome == "disconnect":
                return [vector("CONNECTION", {"CONNECT": "Off"}, tag="setSwitchVector")]
            if self.outcome == "echo_only" and self.count > 1:
                values["maxAlt"] = "80"
            return [vector(name, values)]

        def close(self):
            self.closed = True

    peer = Peer()
    monkeypatch.setattr(mod, "_LimitConnection", lambda *args: peer)
    return peer


def apply():
    return mod.apply_limits(
        VALUES, server_host="localhost", server_port=7624, device_name=DEVICE, timeout=4
    )


def test_full_vectors_and_delayed_elevation_readback(peer):
    assert apply() == VALUES
    writes = [c for c in peer.commands if c.tag == "newNumberVector"]
    assert [{c.get("name"): c.text for c in v} for v in writes] == [
        {"minAlt": "-10", "maxAlt": "85"},
        {"East": "20", "West": "-20"},
    ]
    assert peer.closed


@pytest.mark.parametrize("outcome", ["error", "alert", "disconnect", "echo_only"])
def test_rejection_and_unverified_echo_never_succeed(peer, outcome):
    peer.outcome = outcome
    with pytest.raises(RuntimeError):
        apply()
    assert peer.closed
    assert len(peer.commands) == 2  # Do not send the second vector after failure.


def properties():
    return {
        f"{DEVICE}.CONNECTION.CONNECT": "On",
        **{
            f"{DEVICE}.{vector}.{element}": str(VALUES[key])
            for key, (vector, element, _, _) in mod.LIMIT_FIELDS.items()
        },
    }


def test_missing_and_disconnected_values_are_not_defaults():
    assert mod.limit_values(properties(), DEVICE) == VALUES
    assert set(mod.limit_values({}, DEVICE).values()) == {""}
    assert set(
        mod.limit_values(
            {**properties(), f"{DEVICE}.CONNECTION.CONNECT": "Off"}, DEVICE
        ).values()
    ) == {""}


def test_protocol_handles_split_utf8_and_ignores_other_devices(monkeypatch):
    payload = '<setNumberVector device="Other" name="x"/><message device="LX200 OnStepX" message="고도"/>'.encode()
    split = payload.index("고".encode()) + 1

    class Socket:
        def __init__(self):
            self.chunks = iter([payload[:split], payload[split:]])
            self.closed = False

        def settimeout(self, value):
            pass

        def recv(self, size):
            return next(self.chunks)

        def close(self):
            self.closed = True

    sock = Socket()
    monkeypatch.setattr(mod.socket, "create_connection", lambda *a, **kw: sock)
    connection = mod._LimitConnection("localhost", 7624, DEVICE)
    assert connection.events() == []
    assert [e.get("message") for e in connection.events()] == ["고도"]
    connection.close()
    assert sock.closed


def test_web_displays_limits_and_updates_poll_payload(serial_client, monkeypatch):
    client, _, instance, _ = serial_client
    monkeypatch.setattr(
        server.sys_utils, "get_indi_onstep_properties", lambda **kw: properties()
    )
    instance._indi_properties_cache = {}
    response = client.get("/indi")
    assert response.status_code == 200
    assert 'id="indi_limits_form"' in response.text
    assert 'name="overhead"' in response.text
    assert client.get("/indi/current_values").json["limit_values"] == VALUES


def test_web_apply_uses_active_endpoint_and_fresh_values(serial_client, monkeypatch):
    client, queue, _, _ = serial_client
    calls = []
    monkeypatch.setattr(
        server.indi_limits,
        "apply_limits",
        lambda values, **kw: calls.append((dict(values), kw)),
    )
    monkeypatch.setattr(
        server.sys_utils, "get_indi_onstep_properties", lambda **kw: properties()
    )
    response = client.post("/indi/limits", data=VALUES)
    assert response.status_code == 200
    assert calls[0][1] == {
        "server_host": "localhost",
        "server_port": 7624,
        "device_name": DEVICE,
    }
    assert queue.empty()  # No movement, sync, or tracking commands.
    assert "Mount limits applied and verified" in response.text


def test_web_error_never_claims_success(serial_client, monkeypatch):
    client, _, _, _ = serial_client

    def fail(*args, **kwargs):
        raise RuntimeError("Controller rejected limits")

    monkeypatch.setattr(server.indi_limits, "apply_limits", fail)
    response = client.post("/indi/limits", data=VALUES)
    assert response.status_code == 400
    assert "Controller rejected limits" in response.text
    assert "Mount limits applied and verified" not in response.text


def test_write_requires_login(serial_client, monkeypatch):
    client, _, _, _ = serial_client
    with client.session_transaction() as session:
        session.clear()
    monkeypatch.setattr(
        server.indi_limits,
        "apply_limits",
        lambda *a, **kw: pytest.fail("unauthenticated write"),
    )
    assert client.post("/indi/limits", data=VALUES).status_code == 302
