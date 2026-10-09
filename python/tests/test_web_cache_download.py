"""Exercise cache job lifecycle with real children and no network downloads."""

import json
import time

from flask import Flask
import pytest

from PiFinder.web_cache_download import CacheDownloadJob, register_cache_download_routes


def wait_for(job, predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = job.snapshot()
        if predicate(state):
            return state
        time.sleep(0.02)
    pytest.fail(f"Job did not reach expected state: {job.snapshot()}")


@pytest.fixture
def cache_job(tmp_path):
    script = tmp_path / "scripts" / "warm.py"
    script.parent.mkdir()
    script.write_text("""
import json
from pathlib import Path
import time

cache = Path(__file__).parent / "completed-image"
resuming = cache.exists()
cache.write_text("complete JPEG")
print("Existing file reused" if resuming else "First image saved", flush=True)
print("MFNAVIS_CACHE_PROGRESS " + json.dumps({
    "stage": "images", "total": 2, "completed": 1, "processed": 1,
    "elapsed": 2, "current": "M31", "cached": int(resuming), "fetched": 1,
    "failed": 0, "unavailable": 0,
}), flush=True)
if not resuming:
    while True:
        time.sleep(0.1)
print("MFNAVIS_CACHE_PROGRESS " + json.dumps({
    "stage": "images", "total": 2, "completed": 2, "processed": 1,
    "elapsed": 1, "current": "M32", "cached": 1, "fetched": 1,
    "failed": 0, "unavailable": 0,
}), flush=True)
""")
    job = CacheDownloadJob(tmp_path / "status.json", script)
    yield job
    job.stop()
    wait_for(job, lambda s: s["status"] not in {"running", "stopping"})


@pytest.mark.unit
def test_stop_and_resume_preserve_files_options_and_progress(cache_job):
    job = cache_job
    assert job.snapshot()["status"] == "idle"
    options = {"images": "poss", "workers": 2, "skip_runtime": True}
    job.start(options)
    try:
        state = wait_for(job, lambda s: s.get("progress", {}).get("completed") == 1)
        assert state["stage"] == "images"
        assert state["eta"] == 2
        assert state["logs"] == ["First image saved"]
        with pytest.raises(RuntimeError, match="already running"):
            job.start(options)
    finally:
        job.stop()
    state = wait_for(job, lambda s: s["status"] == "stopped")
    assert state["options"] == options
    assert state["eta"] is None
    assert "First image saved" in state["logs"]
    saved = json.loads(job.state_path.read_text())
    assert saved["status"] == "stopped"
    assert saved["progress"]["completed"] == 1

    # Simulate opening Tools after a service restart, then resume the same job.
    restored = CacheDownloadJob(job.state_path, job.script)
    restored.start(resume=True)
    state = wait_for(restored, lambda s: s["status"] == "completed")
    assert state["options"] == options
    assert state["progress"]["cached"] == 1
    assert state["progress"]["completed"] == 2
    assert state["logs"] == ["Existing file reused"]


@pytest.mark.unit
def test_service_restart_marks_active_job_interrupted(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(
        json.dumps(
            {
                "status": "running",
                "options": {"images": "both", "workers": 4},
                "progress": {"completed": 32, "total": 100},
                "logs": ["Downloading"],
            }
        )
    )
    job = CacheDownloadJob(path)
    state = job.snapshot()
    assert state["status"] == "interrupted"
    assert state["progress"]["completed"] == 32
    assert job._process is None


@pytest.mark.unit
def test_job_failure_keeps_log_and_can_retry(tmp_path):
    script = tmp_path / "fail.py"
    script.write_text('print("Network unavailable", flush=True)\nraise SystemExit(1)\n')
    job = CacheDownloadJob(tmp_path / "status.json", script)
    job.start()
    state = wait_for(job, lambda s: s["status"] == "failed")
    assert state["returncode"] == 1
    assert state["logs"] == ["Network unavailable"]
    script.write_text('print("Recovered", flush=True)\n')
    job.start(resume=True)
    assert wait_for(job, lambda s: s["status"] == "completed")["logs"] == ["Recovered"]


@pytest.mark.unit
def test_cache_download_api_auth_validation_and_no_cached_status(cache_job):
    app = Flask(__name__)
    app.secret_key = "test"
    register_cache_download_routes(app, cache_job)
    client = app.test_client()
    url = "/tools/api/cache-download"
    assert client.get(url).status_code == 401
    for action in ("start", "stop", "resume"):
        assert client.post(url, json={"action": action}).status_code == 401
    assert cache_job.snapshot()["status"] == "idle"
    with client.session_transaction() as sess:
        sess["authenticated"] = True
    response = client.get(url)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["status"] == "idle"
    for data in (
        [],
        {"action": "unknown"},
        {"action": "resume"},
        {"action": "start", "images": "../../etc"},
        {"action": "start", "workers": 0},
        {"action": "start", "workers": 11},
        {"action": "start", "workers": True},
        {"action": "start", "skip_runtime": "yes"},
    ):
        assert client.post(url, json=data).status_code == 400
    assert cache_job.snapshot()["status"] == "idle"
    assert client.post(url, json={"action": "start"}).status_code == 200
    wait_for(cache_job, lambda s: s.get("progress", {}).get("completed") == 1)
    assert client.post(url, json={"action": "start"}).status_code == 409
    assert client.post(url, json={"action": "stop"}).status_code == 200
    wait_for(cache_job, lambda s: s["status"] == "stopped")
    assert client.post(url, json={"action": "resume"}).status_code == 200
    wait_for(cache_job, lambda s: s["status"] == "completed")


@pytest.mark.unit
def test_stop_terminates_descendant_even_after_parent_exits(tmp_path):
    script = tmp_path / "nested.py"
    script.write_text('''
import subprocess
import sys
import time

subprocess.Popen([sys.executable, "-u", "-c", """
import signal
import time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
print('Child ready', flush=True)
while True:
    time.sleep(0.1)
"""])
while True:
    time.sleep(0.1)
''')
    job = CacheDownloadJob(tmp_path / "status.json", script)
    job.start()
    try:
        wait_for(job, lambda s: "Child ready" in s["logs"])
    finally:
        job.stop()
    # Child inherits stdout, so the monitor cannot finish until it is killed.
    assert wait_for(job, lambda s: s["status"] == "stopped")["returncode"] < 0


@pytest.mark.unit
def test_disk_error_before_launch_leaves_job_retryable(tmp_path, monkeypatch):
    job = CacheDownloadJob(tmp_path / "status.json")

    def no_space():
        raise OSError("No space left on device")

    monkeypatch.setattr(job, "_save", no_space)
    with pytest.raises(OSError):
        job.start()
    assert job.snapshot()["status"] == "failed"
    assert job._process is None


@pytest.mark.unit
def test_tools_template_has_download_controls():
    from pathlib import Path
    from PiFinder import utils

    app = Flask(
        __name__, template_folder=str(Path(utils.__file__).parent.parent / "views")
    )
    app.jinja_env.add_extension("jinja2.ext.i18n")
    app.jinja_env.install_null_translations()
    with app.test_request_context():
        html = app.jinja_env.get_template("tools.html").render(title="Tools")
    for name in (
        "cache-start",
        "cache-stop",
        "cache-resume",
        "cache-progress",
        "cache-log",
    ):
        assert f'id="{name}"' in html
    assert "/js/cache_download.js" in html
