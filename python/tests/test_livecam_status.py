"""LiveCam reports solver health independently of its selected image."""

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

from flask import Flask
from jinja2 import Template
import pytest

from PiFinder import api_extensions
from PiFinder.livecam_config import normalize_settings
from PiFinder.types.positioning import PointingEstimate, SolveDiagnostics
from test_raw_live_stack import DummySharedState

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("source", ["original_raw", "cropped_raw", "star_only"])
@pytest.mark.parametrize("preview_enabled", [False, True])
def test_status_reports_preprocessing_and_solve_for_every_input(
    monkeypatch, source, preview_enabled
):
    settings = normalize_settings(
        {"input_frame_source": source, "processing_enabled": preview_enabled}
    )
    shared = DummySharedState()
    shared.set_solver_preprocess_status(
        {"enabled": True, "state": "ready", "frame_count": 3, "frame_limit": 5}
    )
    sol = PointingEstimate(
        last_solve_attempt=100.0,
        last_solve_success=100.0,
        diagnostics=SolveDiagnostics(Centroids=24, Matches=12),
    )
    shared.solution = lambda: sol
    monkeypatch.setattr(api_extensions, "settings_from_config", lambda cfg: settings)
    monkeypatch.setattr(api_extensions.config, "Config", lambda: object())
    monkeypatch.setattr(api_extensions.time, "time", lambda: 110.0)
    server = SimpleNamespace(shared_state=shared)
    app = Flask(__name__)
    api_extensions.register_api_routes(app, server, require_auth=False)
    response = app.test_client().get("/api/camera/raw-stack/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["preprocess"]["state"] == "ready"
    assert data["preprocess"]["frame_count"] == 3
    assert data["solver"] == {
        "state": "success",
        "last_attempt": 100.0,
        "last_success": 100.0,
        "attempt_age_s": 10.0,
        "success_age_s": 10.0,
        "detected_stars": 24,
        "matched_stars": 12,
    }
    if not preview_enabled:
        assert not hasattr(server, "raw_live_stack_processor")


@pytest.mark.parametrize(
    "attempt,success,state",
    [
        (0, None, "waiting"),
        (100, None, "failed"),
        (110, 100, "failed"),
        (110, 110, "success"),
    ],
)
def test_latest_attempt_does_not_use_retained_pointing(
    monkeypatch, attempt, success, state
):
    sol = PointingEstimate(last_solve_attempt=attempt, last_solve_success=success)
    shared = SimpleNamespace(solution=lambda: sol, solve_state=lambda: True)
    monkeypatch.setattr(api_extensions.time, "time", lambda: 120)
    result = api_extensions._livecam_solver_status(shared)
    assert result["state"] == state
    assert result["success_age_s"] == (120 - success if success else None)
    if not attempt:
        assert result["detected_stars"] is None


def test_solver_status_unavailable_without_solution():
    assert api_extensions._livecam_solver_status(SimpleNamespace()) == {
        "state": "unavailable"
    }


def test_status_labels_in_browser_javascript():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to execute browser status formatting")
    template = (Path(__file__).parents[1] / "views" / "livecam.html").read_text()
    functions = template[
        template.index("function formatStatusAge(") : template.index(
            "function renderStatus("
        )
    ]
    javascript = Template(functions).render(_=lambda text: text)
    harness = """
const assert = require('node:assert/strict');
const values = {};
function setText(key, value) { values[key] = value; }
renderSolverStatus({input_frame_source:'original_raw', solver_preprocess_enabled:true},
  {state:'ready', frame_count:3, frame_limit:5},
  {state:'failed', attempt_age_s:3, success_age_s:75, detected_stars:20, matched_stars:0});
assert.equal(values.statusPreprocess, 'Ready (3 / 5)');
assert.equal(values.statusSolveResult, 'Failed (3s ago)');
assert.equal(values.statusSolveSuccess, '1m 15s ago');
assert.equal(values.statusSolveStars, '20 / 0');
renderSolverStatus({solver_preprocess_enabled:true},
  {state:'background_processing', frame_count:99, frame_limit:5}, {state:'waiting'});
assert.equal(values.statusPreprocess, 'Processing in background');
assert.equal(values.statusSolveResult, 'Waiting for first solve');
assert.equal(values.statusSolveSuccess, 'No successful solve yet');
renderSolverStatus({solver_preprocess_enabled:false}, {state:'ready'}, {});
assert.equal(values.statusPreprocess, 'Off');
assert.equal(values.statusSolveSuccess, 'Unavailable');
renderSolverStatus({solver_preprocess_enabled:true}, {}, {state:'success', attempt_age_s:0});
assert.equal(values.statusPreprocess, 'Waiting');
assert.equal(values.statusSolveResult, 'Success (0s ago)');
console.log(JSON.stringify(values));
"""
    result = subprocess.run(
        [node, "-e", javascript + harness], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["statusSolveResult"] == "Success (0s ago)"


def test_guide_history_optical_errors_and_accepted_pulses():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to execute guide history calculations")
    script = """
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source = readFileSync('guide_history.js').toString('base64');
const {measuredError, acceptedPulses, rms, guideTarget} =
  await import('data:text/javascript;base64,' + source);
const target = [0.01, 60.01];
const solved = {valid:true, source:'solve', quality:'high', timestamp:100,
  ra:200, dec:10, metadata:{source_ra:359.99, source_dec:60, last_solve_success:100}};
const error = measuredError(solved, target, 101, 90);
assert.ok(Math.abs(error.ra - 36) < 1e-6);
assert.ok(Math.abs(error.dec - 36) < 1e-6);
assert.equal(measuredError({...solved, source:'pifinder_imu_estimate'}, target, 101, 90), null);
assert.equal(measuredError(solved, target, 120, 90), null);
assert.equal(measuredError(solved, target, 101, 101), null);
assert.equal(measuredError({...solved, metadata:{...solved.metadata, last_solve_attempt:101}},
  target, 101, 90), null);
assert.deepEqual(rms([{ra:3, dec:4},{ra:-3, dec:-4}]), {ra:3, dec:4, total:5});
assert.equal(rms([]), null);
const active = {active_target_ra:0, active_target_dec:0};
assert.deepEqual(guideTarget({...active, service_state:'running', phase:'pifinder_goto'}), [0,0]);
assert.equal(guideTarget({...active, service_state:'idle', phase:'complete'}), null);
const line = changes => 'INFO Guide pulse event ' + JSON.stringify(
  {accepted:true, sent_wall:100, target, direction:'west', duration_ms:260, ...changes});
const pulses = acceptedPulses(['unrelated', 'Guide pulse event {', line({}), line({direction:'north'}),
  line({accepted:false}), line({sent_wall:10}), line({target:[0,0]})], target, 90, 101);
assert.deepEqual(pulses.map(p => [p.axis, p.value]), [['ra', -260], ['dec', 260]]);
"""
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        cwd=Path(__file__).parents[1] / "views/js",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
