"""Offline benchmark validity, including held-out solve isolation and bad inputs."""

import json
from pathlib import Path

import numpy as np
import pytest

from PiFinder.visual_tracking import CameraGeometry
from scripts.benchmark_visual_fallback import (
    RelativeReplay,
    audit_runtime,
    fingerprint,
    main,
    prepare_capture,
    replay_capture,
    synthetic_benchmark,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def tracker():
    geometry = CameraGeometry(512, 512, 12, (250, 260), "test")
    tracker = RelativeReplay(geometry, max_gap_s=5)
    points = np.array([[70, 90], [100, 400], [260, 140], [380, 80], [400, 390]])
    assert tracker.align(points, 1, 100)
    return tracker, points


def test_known_rotation_noise_clouds_and_false_points():
    summary, records = synthetic_benchmark(frames=120)
    assert summary["tracked_visible"] == summary["visible_frames"]
    assert summary["false_accepts"] == 0
    assert summary["error_px"]["p95"] < 0.15
    assert records[-1]["valid"]  # reacquired after multiple cloud gaps
    assert summary["closed_loop"] is False


def test_fixed_reference_is_not_replaced_by_previous_frame(tracker):
    subject, points = tracker
    for i in range(1, 5):
        result = subject.measure(points + [0, i], i + 1, 100 + i)
    assert result["valid"]
    assert result["residual_yx_px"][1] == pytest.approx(4, abs=0.1)


def test_duplicate_and_reordered_frame_cannot_mutate_pose(tracker):
    subject, points = tracker
    subject.measure(points + [1, 1], 2, 101)
    before = subject.pose.copy()
    for frame_id, stamp in [(2, 102), (1, 103), (3, 100), (4, float("nan"))]:
        assert subject.measure(points + 5, frame_id, stamp)["reason"] == "stale_frame"
        np.testing.assert_array_equal(subject.pose, before)
    assert subject.last_valid == 101


@pytest.mark.parametrize("count", [0, 1, 2, 4])
def test_low_support_does_not_update_pose(tracker, count):
    subject, points = tracker
    before = subject.pose.copy()
    assert not subject.measure(points[:count], 2, 101)["valid"]
    assert subject.last_valid == 100
    np.testing.assert_array_equal(subject.pose, before)


def test_long_gap_requires_explicit_new_alignment(tracker):
    subject, points = tracker
    assert subject.measure(points, 2, 106)["reason"] == "gap_exceeded"
    assert subject.measure(points, 3, 107)["reason"] == "gap_exceeded"
    assert subject.align(points, 3, 107)
    assert subject.measure(points, 4, 108)["valid"]


def test_stop_does_not_resume_on_star_return(tracker):
    subject, points = tracker
    subject.stop()
    assert subject.measure(points, 2, 101)["reason"] == "not_aligned"
    assert subject.align(points, 2, 101)
    assert subject.measure(points, 3, 102)["valid"]


def test_duplicate_stars_cannot_establish_reference(tracker):
    subject, points = tracker
    subject.stop()
    assert not subject.align(np.repeat(points[:1], 8, axis=0), 2, 101)
    assert not subject.enabled


@pytest.fixture
def capture(tmp_path):
    directory = tmp_path / "capture"
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps({"requested_at": 1000}))
    yy, xx = np.indices((512, 512))
    points = [(80, 80), (100, 400), (200, 180), (300, 400), (400, 100), (400, 350)]
    records = []
    for index in range(3):
        raw = np.full((512, 512), 20.0)
        for y, x in points:
            raw += 1000 * np.exp(-((yy - y) ** 2 + (xx - x - index) ** 2) / 3)
        path = directory / f"frame_{index}.npz"
        np.savez_compressed(path, raw=raw.astype(np.uint16))
        records.append(
            dict(
                kind="solver",
                sequence=index + 1,
                metadata={
                    "frame_id": index + 1,
                    "exposure_end": 1000 + index,
                    "capture_epoch": "a",
                },
                raw_metadata={"frame_id": index + 1},
                artifact={"file": path.name, "sha256": fingerprint(path)},
                result={
                    "accepted": True,
                    "generation": 1,
                    "frame_moving": False,
                    "target_pixel": [256, 256],
                    "optics": {
                        "rotation_deg": 0,
                        "crop_width_px": 512,
                        "base_fov_degrees": 12,
                    },
                    "candidate": {
                        "RA": 120,
                        "Dec": 30,
                        "Roll": 0,
                        "_alignment_frame": [512, 512, 512],
                    },
                },
            )
        )
    log = directory / "solver.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in records))
    return directory, records


def test_raw_replay_hides_solves_and_does_not_modify_source(capture):
    directory, records = capture
    before = {p.name: fingerprint(p) for p in directory.iterdir()}
    summary, first = replay_capture(directory)
    assert summary["tracked_frames"] == 2
    assert first[0]["reason"] == "simulated_align"
    assert first[2]["residual_yx_px"][1] == pytest.approx(2, abs=0.1)
    assert before == {p.name: fingerprint(p) for p in directory.iterdir()}
    records[-1]["result"]["candidate"]["RA"] += 0.1
    (directory / "solver.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records)
    )
    _, second = replay_capture(directory)
    assert first[-1]["residual_yx_px"] == second[-1]["residual_yx_px"]
    assert first[-1]["solve_comparison_px"] != second[-1]["solve_comparison_px"]


def test_failed_solve_frames_use_raw_not_candidate_centroids(capture):
    directory, records = capture
    records[-1]["result"]["accepted"] = False
    records[-1]["result"]["candidate"] = {}
    (directory / "solver.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records)
    )
    summary, frames = replay_capture(directory)
    assert summary["real_solve_failure_frames"] == 1
    assert summary["tracked_real_solve_failure_frames"] == 1
    assert frames[-1]["solve_comparison_px"] is None


@pytest.mark.parametrize("damage", ["hash", "pairing", "path"])
def test_corrupt_or_unpaired_capture_rejected(capture, damage):
    directory, records = capture
    record = records[0]
    if damage == "hash":
        record["artifact"]["sha256"] = "wrong"
    elif damage == "pairing":
        record["raw_metadata"]["frame_id"] = 999
    else:
        record["artifact"]["file"] = "../outside.npz"
    with pytest.raises(ValueError):
        prepare_capture(record, directory)


def test_runtime_audit_counts_observation_epochs_not_poll_samples(tmp_path):
    path = tmp_path / "runtime.jsonl"
    records = []
    for wall, source, epoch in [
        (100, "solve", 90),
        (101, "solve", 101),
        (102, "solve", 101),
        (103, "pifinder_imu_estimate", 101),
    ]:
        records.append(
            {
                "wall": wall,
                "pointing_coordinate": {
                    "current": {
                        "source": source,
                        "metadata": {"last_solve_success": epoch},
                    }
                },
                "indi_goto_guide": {"phase": "native_tracking"},
            }
        )
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    result = audit_runtime(path)
    assert result["status_samples"] == 4
    assert result["unique_success_epochs_seen"] == 1
    assert result["visual_replay_available"] is False
    assert result["start_kst"].endswith("+09:00")


def test_cli_output_does_not_overwrite_previous_run(capture, tmp_path):
    directory, _ = capture
    output = tmp_path / "output"
    assert main(["--capture", str(directory), "--output", str(output)]) == 0
    report = json.loads((output / "summary.json").read_text())
    assert report["captures"][0]["solves_hidden_from_tracker"]
    with pytest.raises(FileExistsError):
        main(["--capture", str(directory), "--output", str(output)])
    assert Path(output / "capture_0.jsonl").exists()


def test_reordered_capture_cannot_realign_after_context_change(capture):
    directory, records = capture
    old = json.loads(json.dumps(records[0]))
    old["result"]["generation"] = 99
    records.append(old)
    (directory / "solver.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records)
    )
    summary, frames = replay_capture(directory)
    assert frames[-1]["reason"] == "stale_capture"
    assert summary["reasons"]["simulated_align"] == 1
