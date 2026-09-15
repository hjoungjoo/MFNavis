"""Capture tests use disposable paths, fake frames and no camera or mount."""

import json
import threading
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest
from flask import Flask

from PiFinder import solver_capture as capture
from PiFinder.api_extensions import register_api_routes
from PiFinder.solver import _solve_center_first_remainder

pytestmark = pytest.mark.unit


@pytest.fixture
def paths(tmp_path, monkeypatch):
    runtime, root = tmp_path / "runtime", tmp_path / "sessions"
    monkeypatch.setattr(capture.utils, "runtime_dir", runtime)
    return runtime, root


def recorder(paths, role="solver"):
    runtime, root = paths
    return capture.CaptureRecorder(role, SimpleNamespace(), runtime=runtime, root=root)


def arm(paths, **options):
    return capture.request_capture("start", options, runtime=paths[0])["request"]


def attempt(rec, index=1, *, accepted=True, raw_id=None):
    token = rec.begin({"frame_id": index, "exposure_end": float(index)})
    rec.finish(
        token,
        {"accepted": accepted, "input_ready_monotonic_ns": 100},
        raw_entry={
            "frame_id": index if raw_id is None else raw_id,
            "frame": np.arange(24, dtype=np.uint16).reshape(4, 6),
        },
        image=np.ones((2, 2), dtype=np.uint8),
    )
    return token


def rows(rec):
    return [
        json.loads(line)
        for line in (rec.writer.path / f"{rec.role}.jsonl").read_text().splitlines()
        if json.loads(line)["kind"] == rec.role
    ]


def test_disabled_is_noop_without_creating_capture_directory(paths):
    rec = recorder(paths)
    assert rec.begin({"frame_id": 1}) is None
    rec.finish(None, {})
    assert not paths[1].exists()
    assert not paths[0].exists()


@pytest.mark.parametrize(
    "options",
    [
        {"duration": 0},
        {"duration": float("nan")},
        {"duration": 3601},
        {"raw_every": -1},
        {"raw_every": float("inf")},
        {"max_frames": 0},
        {"max_mib": 1},
        {"scene": "../oops"},
        {"stage": "unknown"},
        {"note": "x" * 501},
        {"mode": "unknown"},
    ],
)
def test_control_rejects_invalid_requests_without_arming(paths, options):
    with pytest.raises(ValueError):
        arm(paths, **options)
    assert not capture.capture_status(paths[0])["requested_active"]


def test_raw_is_lossless_paired_and_failed_attempts_are_kept(paths):
    request = arm(paths)
    rec = recorder(paths)
    attempt(rec, accepted=False)
    rec.close()
    result = rows(rec)[0]
    assert not result["result"]["accepted"]
    with np.load(
        rec.writer.path / result["artifact"]["file"], allow_pickle=False
    ) as arrays:
        np.testing.assert_array_equal(
            arrays["raw"], np.arange(24, dtype=np.uint16).reshape(4, 6)
        )
        assert arrays["raw"].dtype == np.uint16
        assert arrays["solver_512"].dtype == np.uint8
    report = capture.report_session(paths[1] / request["session_id"])
    assert report["raw_saved"] == 1
    assert report["integrity_errors"] == []
    assert not report["complete"]  # Integrator did not participate in this test.


def test_mismatched_raw_never_saved_under_another_frame(paths):
    arm(paths)
    rec = recorder(paths)
    attempt(rec, raw_id=999)
    rec.close()
    assert rows(rec)[0]["raw_status"] == "missing_matching_raw"
    assert not list(rec.writer.path.glob("*.npz"))


def test_source_snapshot_is_preserved_and_verified(paths):
    arm(paths)
    rec = recorder(paths)
    attempt(rec)
    rec.close()
    source = rec.writer.path / "source" / "solver_capture.py"
    assert source.read_bytes() == Path(capture.__file__).read_bytes()
    source.write_text("changed")
    assert any(
        "source/solver_capture.py" in error
        for error in capture.report_session(rec.writer.path)["integrity_errors"]
    )


def test_stop_drains_queued_records(paths):
    arm(paths)
    rec = recorder(paths)
    attempt(rec)
    capture.request_capture("stop", runtime=paths[0])
    rec.next_poll = 0
    assert rec.begin() is None
    rec.close()
    assert rec.writer.state == "complete"
    assert rec.writer.reason == "stopped"
    assert len(rows(rec)) == 1


def test_byte_limit_prevents_oversized_raw_write(paths):
    arm(paths, max_mib=16)
    rec = recorder(paths)
    token = rec.begin({"frame_id": 1})
    rec.finish(
        token,
        {"accepted": False},
        raw_entry={"frame_id": 1, "frame": np.zeros((3000, 3000), dtype=np.uint16)},
        image=np.zeros((2, 2), dtype=np.uint8),
    )
    rec.close()
    assert rec.writer.reason == "size_limit"
    assert rec.writer.dropped == 1
    assert not list(rec.writer.path.glob("*.npz"))


def test_telemetry_mode_does_not_write_images(paths):
    arm(paths, mode="telemetry")
    rec = recorder(paths)
    attempt(rec)
    rec.close()
    assert rows(rec)[0]["raw_status"] == "telemetry_only"
    assert not list(rec.writer.path.glob("*.npz"))


def test_sampling_only_affects_saved_images_not_attempt_records(paths):
    arm(paths, raw_every=60)
    rec = recorder(paths)
    attempt(rec, 1)
    attempt(rec, 2)
    rec.close()
    assert [row["raw_status"] for row in rows(rec)] == ["saved", "sample_interval"]


def test_mark_freezes_phase_at_attempt_start_and_preserves_settings(paths):
    original = arm(paths, duration=120, stage="baseline")
    rec = recorder(paths)
    token = rec.begin({"frame_id": 1})
    marked = capture.request_capture(
        "mark", {"stage": "validation", "note": "이동 후"}, runtime=paths[0]
    )["request"]
    rec.next_poll = 0
    rec.poll()
    rec.finish(token, {"accepted": False})
    rec.close()
    assert rows(rec)[0]["phase"]["stage"] == "baseline"
    assert marked["duration"] == original["duration"]
    assert marked["mode"] == original["mode"]
    assert marked["session_id"] == original["session_id"]


def test_active_start_rejected_and_expired_capture_drains(paths):
    arm(paths)
    with pytest.raises(ValueError, match="already"):
        arm(paths)
    rec = recorder(paths)
    attempt(rec)
    request_path = paths[0] / capture.CONTROL_NAME
    request = json.loads(request_path.read_text())
    request["deadline_monotonic"] = 0
    request_path.write_text(json.dumps(request))
    rec.next_poll = 0
    assert rec.begin() is None
    rec.close()
    assert rec.writer.reason == "duration_limit"
    assert len(rows(rec)) == 1


def test_frame_limit_stops_writer(paths):
    arm(paths, max_frames=1)
    rec = recorder(paths)
    attempt(rec)
    rec.writer.thread.join(3)
    assert rec.writer.reason == "frame_limit"
    assert rec.begin() is None


def test_full_writer_queue_drops_without_blocking_solver(paths, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def environment(_cfg, _source_directory=None):
        entered.set()
        assert release.wait(3)
        return {}

    monkeypatch.setattr(capture, "_environment", environment)
    arm(paths)
    rec = recorder(paths)
    try:
        rec.poll()
        assert entered.wait(1)
        for index in range(4):
            attempt(rec, index)
        assert rec.writer.items.qsize() == 2
        assert rec.writer.dropped == 2
    finally:
        release.set()
        rec.close()
    assert len(rows(rec)) == 2


def test_low_disk_stops_capture_not_the_caller(paths, monkeypatch):
    arm(paths)
    monkeypatch.setattr(capture.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    rec = recorder(paths)
    attempt(rec)
    rec.writer.thread.join(3)
    assert rec.writer.reason == "low_disk_space"
    assert not list(rec.writer.path.glob("*.npz"))


def test_write_error_stays_inside_recorder(paths, monkeypatch):
    arm(paths)

    def fail(*_args, **_kwargs):
        raise OSError("injected disk error")

    monkeypatch.setattr(capture.np, "savez", fail)
    rec = recorder(paths)
    attempt(rec)
    rec.close()
    assert rec.writer.state == "error"


def test_report_pairs_publication_by_frame_and_epoch_and_checks_hash(paths):
    request = arm(paths)
    rec, integ = recorder(paths), recorder(paths, "integrator")
    attempt(rec, 42)
    for epoch in (41.0, 42.0):
        token = integ.begin({"frame_id": 42, "exposure_end": epoch})
        integ.finish(token, {"published": True, "published_monotonic_ns": 1000100})
    rec.close()
    integ.close()
    directory = paths[1] / request["session_id"]
    report = capture.report_session(directory)
    assert report["complete"]
    assert report["matched_publications"] == 1
    assert report["input_ready_to_publication_ms"]["median"] == 1.0
    assert report["phases"][0]["matched_publications"] == 1
    raw = next(directory.glob("*.npz"))
    raw.write_bytes(b"damaged")
    assert "checksum" in capture.report_session(directory)["integrity_errors"][0]


def test_corrupt_control_and_reboot_request_are_inactive(paths):
    request = arm(paths)
    request["boot_id"] = "another boot"
    path = paths[0] / capture.CONTROL_NAME
    path.write_text(json.dumps(request))
    assert recorder(paths).begin() is None
    path.write_text("[]")
    assert recorder(paths).begin() is None


def test_trace_keeps_cascade_order_and_early_return():
    trace, visited = [], []

    def solve(name, value):
        visited.append(name)
        return value

    result, path = _solve_center_first_remainder(
        [
            ("first", lambda: solve("first", {})),
            ("second", lambda: solve("second", {"RA": 2})),
            ("third", lambda: solve("third", {"RA": 3})),
        ],
        trace=trace,
    )
    assert visited == ["first", "second"]
    assert result == {"RA": 2} and path == "second"
    assert [item["quality_solved"] for item in trace] == [False, True]
    assert all(item["elapsed_ms"] >= 0 for item in trace)


def test_web_capture_controls_and_auth(paths):
    app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / "views"))
    register_api_routes(app, SimpleNamespace())
    client = app.test_client()
    assert "기록 시작" in client.get("/solver-capture").get_data(as_text=True)
    assert client.post("/api/solver-capture", json=[]).status_code == 400
    assert (
        client.post(
            "/api/solver-capture", json={"action": "start", "scene": "indoor"}
        ).status_code
        == 200
    )
    assert client.get("/api/solver-capture").json["requested_active"]
    request = client.get("/api/solver-capture").json["request"]
    assert request["mode"] == "raw"
    assert request["stage"] == "baseline"
    assert (request["duration"], request["max_frames"], request["max_mib"]) == (
        60,
        120,
        512,
    )
    assert (
        client.post("/api/solver-capture", json={"action": "stop"}).status_code == 200
    )
    protected = Flask("protected")
    register_api_routes(protected, SimpleNamespace(), require_auth=True)
    assert (
        protected.test_client()
        .post("/api/solver-capture", json={"action": "start"})
        .status_code
        == 401
    )


def test_capture_freezes_selected_target_and_keeps_input_frame_identity(paths):
    target = SimpleNamespace(
        object_id=1, display_name="frame target", ra=12.0, dec=-4.0
    )
    shared = SimpleNamespace(ui_state=lambda: SimpleNamespace(target=lambda: target))
    arm(paths)
    rec = recorder(paths)
    rec.shared_state = shared
    token = rec.begin({"frame_id": 17, "exposure_end": 123})
    target.ra = 13.0
    rec.finish(token, {"accepted": False})
    rec.close()
    row = rows(rec)[0]
    assert row["metadata"]["frame_id"] == 17
    assert row["observation"]["target"]["ra_deg"] == 12.0
    assert row["observation"]["pointing"] is None
