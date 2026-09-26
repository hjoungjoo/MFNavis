"""Serial Auto must only announce discovery when it can be processed."""

import json
from queue import Queue

import pytest

from PiFinder import server as module, sys_utils_fake

pytestmark = pytest.mark.unit
AUTO_FORM = {
    "connection_type": "usb",
    "serial_port": "__auto__",
    "server_host": "localhost",
    "server_port": "7624",
}


@pytest.fixture
def serial_client(monkeypatch, tmp_path):
    monkeypatch.setattr(module.config.utils, "data_dir", tmp_path)
    monkeypatch.setattr(module.config.utils, "runtime_dir", tmp_path)
    monkeypatch.setattr(module.sys_utils, "Network", sys_utils_fake.Network)
    monkeypatch.setattr(module.sys_utils, "get_indi_profile_drivers", lambda: {})
    monkeypatch.setattr(
        module.sys_utils, "get_indi_profile_device_name", lambda: "LX200 OnStepX"
    )
    monkeypatch.setattr(
        module.sys_utils,
        "get_indi_onstep_properties",
        lambda **kwargs: {"LX200 OnStepX.CONNECTION.CONNECT": "Off"},
    )
    monkeypatch.setattr(
        module.sys_utils, "read_saved_indi_onstep_connection_config", lambda **kw: None
    )
    monkeypatch.setattr(module.sys_utils, "list_onstep_serial_ports", lambda: [])
    module.config.Config().set_options({"mount_control": True})
    queue = Queue()
    instance = module.Server(mountcontrol_queue=queue, ui_queue=Queue())
    instance.app.testing = True
    client = instance.app.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
    return client, queue, instance, tmp_path


def test_serial_auto_queues_discovery_without_persisting_auto_values(serial_client):
    client, queue, _, _ = serial_client
    # The browser disables the baud select for Auto, so it is omitted here.
    response = client.post("/indi/driver", data=AUTO_FORM)
    assert response.status_code == 200
    assert queue.get_nowait() == {"type": "discover_serial_connection"}
    assert queue.empty()
    cfg = module.config.Config()
    assert cfg.get_stored_option("onstep_serial_port") != "__auto__"


@pytest.mark.parametrize("language", ["en", "ko"])
def test_serial_auto_does_not_queue_without_enabled_consumer(serial_client, language):
    client, queue, _, _ = serial_client
    module.config.Config().set_options({"mount_control": False})
    client.set_cookie("mfnavis_web_language", language)
    response = client.post("/indi/driver", data=AUTO_FORM)
    assert response.status_code == 400
    assert queue.empty()
    assert (
        "Mount Control is off" if language == "en" else "마운트 제어가 꺼져"
    ) in response.text
    assert "discovery started" not in response.text


def test_serial_auto_requires_running_driver(serial_client, monkeypatch):
    client, queue, _, _ = serial_client
    monkeypatch.setattr(module.sys_utils, "get_indi_onstep_properties", lambda **kw: {})
    response = client.post("/indi/driver", data=AUTO_FORM)
    assert response.status_code == 400
    assert "Start the OnStepX profile" in response.text
    assert queue.empty()


def test_serial_auto_accepts_driver_after_start_even_with_empty_page_cache(
    serial_client,
):
    client, queue, instance, _ = serial_client
    assert instance._indi_properties_cache == {}
    response = client.post("/indi/driver", data=AUTO_FORM)
    assert response.status_code == 200
    assert queue.get_nowait() == {"type": "discover_serial_connection"}


def test_serial_auto_requires_controller_queue(serial_client):
    client, queue, instance, _ = serial_client
    instance.mountcontrol_queue = None
    response = client.post("/indi/driver", data=AUTO_FORM)
    assert response.status_code == 400
    assert "Mount-control process is not available" in response.text
    assert queue.empty()


@pytest.mark.parametrize("host", ["192.0.2.5", "127.0.0.1"])
def test_serial_auto_rejects_remote_or_changed_endpoint(serial_client, host):
    client, queue, _, _ = serial_client
    response = client.post("/indi/driver", data={**AUTO_FORM, "server_host": host})
    assert response.status_code == 400
    assert queue.empty()


def test_serial_auto_does_not_start_a_second_scan(serial_client):
    client, queue, _, runtime_dir = serial_client
    (runtime_dir / "mount_control_status.json").write_text(
        json.dumps({"serial_discovery_state": "scanning"})
    )
    response = client.post("/indi/driver", data=AUTO_FORM)
    assert response.status_code == 400
    assert "Serial discovery is already running" in response.text
    assert queue.empty()


@pytest.mark.parametrize("enabled", [True, False])
def test_provisional_imu_goto_setting_is_visible_and_saved(serial_client, enabled):
    client, _, _, _ = serial_client
    form = {"indi_goto_method": "pifinder"}
    if enabled:
        form["indi_goto_allow_unaligned_imu"] = "on"
    response = client.post("/indi/goto_guide", data=form)
    assert response.status_code == 200
    cfg = module.config.Config()
    assert cfg.get_option("indi_goto_allow_unaligned_imu") is enabled
    assert 'name="indi_goto_allow_unaligned_imu"' in response.text
