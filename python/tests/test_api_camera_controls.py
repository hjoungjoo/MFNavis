#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Tests for /api/camera/controls, the web LiveCam camera settings endpoint.

It drives the same camera the on-device Camera Exp / Camera Gain menus do, so
it has to behave the same way those menus do: record the exposure in config and
queue the camera command, and leave the gain to the camera process (the Camera
Gain menu does not persist a gain either).
"""

import json
import queue

import pytest
from flask import Flask

from PiFinder import config
from PiFinder.api_extensions import register_api_routes


class _SharedState:
    """Just enough shared state for the camera controls payload."""

    def camera_type(self):
        return "imx462"

    def last_image_metadata(self):
        return {
            "frame_id": 123,
            "sensor_timestamp_ns": 456,
            "exposure_time": 25000,
            "actual_exposure_us": 24991,
            "gain": 1.0,
            "gain_mode": "profile",
            "actual_gain": 1.02,
            "capture_pipeline": {
                "request_held_ms": 2.5,
                "estimated_dropped_since_last": 0,
            },
        }


class _Server:
    def __init__(self):
        self.camera_command_queue = queue.Queue()
        self.shared_state = _SharedState()

    def queued(self):
        commands = []
        while not self.camera_command_queue.empty():
            commands.append(self.camera_command_queue.get_nowait())
        return commands


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "PiFinder_data"
    data_dir.mkdir()
    (data_dir / "config.json").write_text(json.dumps({"camera_exp": 25000}))
    monkeypatch.setattr(config.utils, "data_dir", data_dir)

    app = Flask(__name__)
    server = _Server()
    register_api_routes(app, server, require_auth=False)
    app.config["TESTING"] = True
    return app.test_client(), server


def _post(client, body):
    return client.post("/api/camera/controls", json=body)


def _saved_config() -> dict:
    """The user config as written to disk (no default_config.json fallback)."""
    return json.loads(config.Config().config_file_path.read_text())


@pytest.mark.unit
@pytest.mark.parametrize("path", ["wide-tiles", "wide-solver"])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_retired_tile_endpoints_are_unavailable(client, path, method):
    test_client, server = client
    before = _saved_config()
    response = test_client.open(
        f"/api/camera/{path}", method=method, json={"enabled": True}
    )
    assert response.status_code == 404
    assert _saved_config() == before
    assert server.queued() == []


@pytest.mark.unit
def test_exposure_is_queued_and_recorded(client):
    test_client, server = client
    response = _post(test_client, {"exposure": 400000})

    assert response.status_code == 200
    assert server.queued() == ["set_exp:400000"]
    # Recorded straight away, like the menu does -- not only once the camera
    # process gets round to draining its queue.
    assert config.Config().get_option("camera_exp") == 400000
    assert response.get_json()["exposure"]["requested"] == 400000


@pytest.mark.unit
def test_auto_mode_is_queued_and_recorded(client):
    test_client, server = client
    response = _post(test_client, {"exposure": "auto_star"})

    assert server.queued() == ["set_exp:auto_star"]
    assert config.Config().get_option("camera_exp") == "auto_star"
    assert response.get_json()["exposure"]["mode"] == "auto_star"


@pytest.mark.unit
def test_gain_is_queued_but_not_recorded(client):
    test_client, server = client
    _post(test_client, {"gain": 8})

    assert server.queued() == ["set_gain:8"]
    # Gain is runtime-only, exactly as the Camera Gain menu leaves it: nothing
    # is written to the user config (get_option would report the packaged
    # default_config.json value, so check the saved file itself).
    assert "camera_gain" not in _saved_config()


@pytest.mark.unit
def test_exposure_and_gain_together(client):
    test_client, server = client
    _post(test_client, {"exposure": 100000, "gain": "profile"})

    assert server.queued() == ["set_exp:100000", "set_gain:profile"]
    assert config.Config().get_option("camera_exp") == 100000


@pytest.mark.unit
def test_clamped_exposure_records_the_clamped_value(client):
    test_client, server = client
    response = _post(test_client, {"exposure": 5_000_000})

    assert server.queued() == ["set_exp:1000000"]
    assert config.Config().get_option("camera_exp") == 1000000
    assert response.get_json()["notes"]


@pytest.mark.unit
def test_invalid_exposure_changes_nothing(client):
    test_client, server = client
    response = _post(test_client, {"exposure": "bogus"})

    assert response.status_code == 400
    assert server.queued() == []
    assert config.Config().get_option("camera_exp") == 25000


@pytest.mark.unit
def test_empty_body_is_rejected(client):
    test_client, server = client
    response = _post(test_client, {})

    assert response.status_code == 400
    assert server.queued() == []


@pytest.mark.unit
def test_get_reports_applied_values_and_capture_pipeline(client):
    test_client, _server = client

    payload = test_client.get("/api/camera/controls").get_json()

    assert payload["exposure"]["actual_us"] == 24991
    assert payload["gain"]["actual"] == 1.02
    assert payload["gain"]["requested"] == 1.0
    assert payload["gain"]["mode"] == "profile"
    assert payload["capture_pipeline"] == {
        "frame_id": 123,
        "sensor_timestamp_ns": 456,
        "request_held_ms": 2.5,
        "estimated_dropped_since_last": 0,
    }
