"""Authenticated configuration never directly dispatches hardware."""

from queue import Queue
from types import SimpleNamespace
from pathlib import Path
import json
import shutil
import subprocess
import pytest
from PiFinder.tracking_mailbox import TrackingMailbox

pytestmark = pytest.mark.unit


def test_diagnostics_script_starts_with_translated_bound_label():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for browser script execution")
    script = Path(__file__).parents[1] / "views/js/smooth_tracking.js"
    harness = r"""
      const fs = require('fs'), vm = require('vm');
      const elements = {};
      const panel = {dataset: {bound: '오차 상한', stars: '별', motionNoise: '이동 오차',
        controlledAxes: '보정축'}, querySelectorAll: () => []};
      const document = {contains: () => true, getElementById: id =>
        id === 'smooth_tracking_panel' ? panel : (elements[id] ||= {})};
      let polls = 0;
      const context = {document, URL, Blob, console, setTimeout: () => {},
        fetch: async () => {polls++; return {ok: true, json: async () => ({
          mode: 'shadow', state: 'FINE_TRACKING', configured_mode: 'shadow',
          response_axes: [1], measurement: {reason: 'catalog_stars', stars: 12,
            bound_arcsec: 100, relative_bound_arcsec: 8, timing: {verified: true}},
          error_budget_arcsec: 200,
        })};}};
      const code = fs.readFileSync(process.argv[1], 'utf8');
      vm.runInNewContext(code, context);
      setImmediate(() => {
        vm.runInNewContext(code, context);
        console.log(JSON.stringify({polls, status: elements.smooth_measurement_status?.textContent,
          label: panel.dataset.bound}));
      });
    """
    result = subprocess.run(
        [node, "-e", harness, str(script)],
        check=True,
        text=True,
        capture_output=True,
        timeout=5,
    )
    data = json.loads(result.stdout)
    assert data["polls"] == 1
    assert data["label"] == "오차 상한"
    assert "오차 상한: 100.0″ / 200.0″" in data["status"]
    assert "이동 오차: 8.0″" in data["status"]
    assert "보정축: Dec" in data["status"]


@pytest.fixture(name="motion_client")
def make_motion_client(monkeypatch, tmp_path):
    from PiFinder import server as module

    monkeypatch.setattr(module.config.utils, "data_dir", tmp_path)
    monkeypatch.setattr(module.config.utils, "runtime_dir", tmp_path)
    monkeypatch.setattr(module.sys_utils, "get_indi_profile_drivers", lambda: {})
    monkeypatch.setattr(module.sys_utils, "get_indi_profile_device_name", lambda: "sim")

    def unexpected_write(*args, **kwargs):
        pytest.fail("Web route bypassed the motion controller")

    monkeypatch.setattr(
        module.sys_utils, "apply_indi_onstep_properties", unexpected_write
    )
    queue = Queue()
    server = module.Server(mountcontrol_queue=queue)
    server.app.testing = True
    client = server.app.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
    return client, queue, server


def setup_client(fixture):
    client, mount_queue, server = fixture
    box = TrackingMailbox()

    def smooth(action="snapshot", value=None):
        if action == "snapshot":
            return box.snapshot()
        if action == "stop":
            return box.stop(value)
        raise AssertionError(action)

    server.shared_state = SimpleNamespace(smooth_tracking=smooth)
    server.goto_guide_queue = Queue()
    return client, mount_queue, server


def test_mode_save_never_arms_and_start_is_explicit(motion_client):
    client, mount, server = setup_client(motion_client)
    initial = client.get("/indi/smooth_tracking").json
    assert initial["configured_mode"] == "active"
    assert initial["mode"] == "off" and initial["state"] == "DISABLED"
    assert mount.empty() and server.goto_guide_queue.empty()
    response = client.post(
        "/indi/smooth_tracking",
        json={"action": "configure", "mode": "shadow", "profile": {}},
    )
    assert response.status_code == 200
    assert response.json["armed"] is False
    assert mount.empty() and server.goto_guide_queue.empty()
    status = client.get("/indi/smooth_tracking").json
    assert status["configured_mode"] == "shadow" and status["mode"] == "off"
    response = client.post(
        "/indi/smooth_tracking",
        json={"action": "start", "ra": 40, "dec": 20, "frame": "catalog"},
    )
    assert response.status_code == 202
    assert server.goto_guide_queue.get_nowait()["type"] == "smooth_tracking_start"
    assert mount.empty()
    response = client.post("/indi/smooth_tracking", json={"action": "stop"})
    assert response.status_code == 202
    assert server.goto_guide_queue.get_nowait()["type"] == "smooth_tracking_stop"


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "configure", "mode": "active", "profile": {}},
        {
            "action": "configure",
            "mode": "shadow",
            "profile": {"max_pulse_ms": float("nan")},
        },
        {"action": "start", "ra": 40, "dec": 91, "frame": "catalog"},
        {"action": "start", "ra": 40, "dec": 20},
    ],
)
def test_invalid_activation_never_queues(motion_client, payload):
    client, mount, server = setup_client(motion_client)
    assert client.post("/indi/smooth_tracking", json=payload).status_code == 400
    assert mount.empty() and server.goto_guide_queue.empty()


def test_web_panel_and_script_are_available(motion_client):
    client, _, server = setup_client(motion_client)
    assert server.app.jinja_env.get_template("smooth_tracking.html")
    response = client.get("/js/smooth_tracking.js")
    assert response.status_code == 200
    assert b"smooth_tracking_panel" in response.data
    with client.session_transaction() as session:
        session.clear()
    assert client.post(
        "/indi/smooth_tracking", json={"action": "stop"}
    ).status_code in {302, 401}


def test_web_diagnostics_show_used_reference_budget_and_rejected_stars(
    motion_client, monkeypatch
):
    from dataclasses import replace
    from PiFinder import smooth_tracking_runtime
    from test_smooth_tracking import measurement

    client, mount, server = setup_client(motion_client)
    box = TrackingMailbox()
    box.arm(
        {
            "session": "session",
            "mode": "shadow",
            "profile": {"max_error_bound_arcsec": 180},
        }
    )
    m = measurement(3, 100, roi_counts={"accepted": 14, "saturated": 20})
    box.publish(replace(m, timing=replace(m.timing, verified=False)))
    box.publish_reference({"id": "latest", "capture_epoch": "capture", "sequence": 2})
    box.activate_reference({"id": "used", "absolute_bound": 67})
    server.shared_state.smooth_tracking = lambda: box.snapshot()
    monkeypatch.setattr(smooth_tracking_runtime.time, "monotonic", lambda: 100)
    data = client.get("/indi/smooth_tracking").json
    assert data["reference"]["id"] == "latest"
    assert data["active_reference"] == {
        "id": "used",
        "absolute_bound": 67,
        "timing": None,
    }
    assert data["error_budget_arcsec"] == 180
    assert data["measurement"]["age_s"] == pytest.approx(0.05)
    assert data["measurement"]["timing"]["verified"] is False
    assert data["measurement"]["roi_counts"] == {"accepted": 14, "saturated": 20}
    assert mount.empty() and server.goto_guide_queue.empty()


def test_new_optical_prediction_setting_remains_supported(motion_client):
    client, mount, server = setup_client(motion_client)
    response = client.post(
        "/indi/smooth_tracking",
        json={"action": "configure", "mode": "shadow", "prediction": True},
    )
    assert response.status_code == 200
    assert response.json["armed"] is False
    assert mount.empty() and server.goto_guide_queue.empty()
