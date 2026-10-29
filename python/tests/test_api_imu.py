"""Health-contract tests for the ``/api/imu`` endpoint."""

import time

import pytest
import quaternion
from flask import Flask

from PiFinder.api_extensions import register_api_routes
from PiFinder.types.positioning import ImuSample


class _SharedState:
    def __init__(self, sample):
        self._sample = sample

    def imu(self):
        return self._sample


class _Server:
    def __init__(self, sample):
        self.shared_state = _SharedState(sample)


def _get_imu(sample):
    app = Flask(__name__)
    register_api_routes(app, _Server(sample), require_auth=False)
    app.config["TESTING"] = True
    return app.test_client().get("/api/imu")


def _sample(**overrides):
    values = {
        "quat": quaternion.quaternion(1, 0, 0, 0),
        "timestamp": time.time(),
        "status": 3,
        "sensor_healthy": True,
        "last_success_time": time.time(),
    }
    values.update(overrides)
    return ImuSample(**values)


@pytest.mark.unit
def test_imu_endpoint_returns_healthy_fresh_sample():
    response = _get_imu(
        _sample(
            sensor_model="BNO086",
            fusion_mode="game_rotation_vector",
            heading_reference="startup_magnetic",
            startup_heading_status="acquired",
        )
    )

    assert response.status_code == 200
    assert response.get_json()["sensor_healthy"] is True
    assert response.get_json()["fresh"] is True
    assert response.get_json()["usable"] is True
    assert response.get_json()["sensor_model"] == "BNO086"
    assert response.get_json()["fusion_mode"] == "game_rotation_vector"
    assert response.get_json()["heading_reference"] == "startup_magnetic"
    assert response.get_json()["startup_heading_status"] == "acquired"
    assert response.get_json()["uses_magnetometer"] is False


@pytest.mark.unit
def test_imu_endpoint_marks_stale_sample_unavailable():
    response = _get_imu(_sample(timestamp=time.time() - 2.0))

    assert response.status_code == 503
    assert response.get_json()["sensor_healthy"] is True
    assert response.get_json()["fresh"] is False
    assert response.get_json()["usable"] is False


@pytest.mark.unit
def test_imu_endpoint_exposes_runtime_failure():
    response = _get_imu(
        _sample(
            sensor_healthy=False,
            consecutive_errors=4,
            last_error="OSError: I2C read failed",
        )
    )

    assert response.status_code == 503
    assert response.get_json()["consecutive_errors"] == 4
    assert response.get_json()["last_error"] == "OSError: I2C read failed"
    assert response.get_json()["usable"] is False
