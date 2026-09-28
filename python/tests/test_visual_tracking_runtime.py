from datetime import datetime, timezone
import json
from types import SimpleNamespace

import numpy as np
import pytest

from PiFinder import utils
from PiFinder.visual_tracking import plate_basis
from PiFinder.visual_tracking_experiment import replay
from PiFinder.visual_tracking_runtime import LiveShadow, atomic_json, create_shadow
from PiFinder.visual_tracking_target import TrackingTarget

pytestmark = pytest.mark.unit


@pytest.fixture
def live(tmp_path, monkeypatch):
    import PiFinder.visual_tracking_runtime as runtime

    clock = [1000.0]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    monkeypatch.setattr(utils, "runtime_dir", tmp_path)
    state = SimpleNamespace(
        camera_type=lambda: "test-camera",
        camera_lens=lambda: "test-lens",
        target_pixel=lambda: (256, 256),
        datetime=lambda: datetime.fromtimestamp(clock[0], timezone.utc),
    )
    settings = {
        "schema": 1,
        "mode": "shadow",
        "environment_confirmed": True,
        "mount_type": "EQ",
        "camera_type": "test-camera",
        "lens": "test-lens",
        "calibration_id": "test",
        "output_dir": str(tmp_path / "results"),
        "expires_at": 2000,
        "max_frames": 20,
        "alignment_roll_deg": 0,
        "roll_confirmed": True,
        "raw_shape": [512, 512],
    }
    shadow = LiveShadow(settings, state)
    shadow.ephemeris = SimpleNamespace(
        resolve=lambda *a, **k: TrackingTarget(100, 20),
        basis=lambda *a, **k: plate_basis(100, 20, 0),
    )
    points = np.array([[60, 70], [90, 420], [240, 170], [420, 320]])
    info = {
        "rotation_deg": 0,
        "crop_width_px": 512,
        "base_fov_degrees": 10,
        "distortion_coefficients": None,
    }
    cfg = SimpleNamespace(get_option=lambda key: "EQ")

    def frame(index, points_override=None, **changes):
        clock[0] = 1000 + index
        atomic_json(
            tmp_path / "mount_control_status.json",
            {"updated": clock[0], "tracking_enabled": True},
        )
        args = dict(
            raw_entry={"frame_id": index, "frame": np.zeros((512, 512))},
            run=SimpleNamespace(
                frame_id=index,
                frame_hw=(512, 512),
                detection=SimpleNamespace(
                    centroids=points if points_override is None else points_override
                ),
            ),
            metadata={"frame_id": index, "exposure_end": clock[0]},
            geometry=info,
            solution={},
            moving=False,
            calibration_id="test",
            cfg=cfg,
        )
        args.update(changes)
        shadow.observe(**args)
        return json.loads((shadow.output / "status.json").read_text())

    def align(identifier="align1", timestamp=1000.5):
        atomic_json(
            shadow.output / "request.json",
            {
                "id": identifier,
                "command": "align",
                "requested_at": timestamp,
                "ra": 100,
                "dec": 20,
                "frame": "catalog",
            },
        )

    return SimpleNamespace(
        shadow=shadow,
        frame=frame,
        align=align,
        points=points,
        clock=clock,
        root=tmp_path,
        state=state,
    )


def test_shadow_alignment_measurement_and_exact_replay(live):
    live.align()
    assert live.frame(1)["reason"] == "user_alignment"
    assert live.frame(2)["state"] == "tracking_visual"
    assert live.frame(3, [])["state"] == "tracking_predicted"
    solution = {
        "RA": 100,
        "Dec": 20,
        "Roll": 0,
        "FOV": 10,
        "_alignment_frame": [512, 512, 512],
    }
    assert live.frame(4, solution=solution)["state"] == "tracking_solved"
    assert live.frame(5)["state"] == "tracking_visual"
    rows = [json.loads(row) for row in live.shadow.log_path.read_text().splitlines()]
    repeated = list(replay(rows))
    assert [r["state"] for r in repeated] == [r["state"] for r in rows]
    assert all(r["commands_sent"] == 0 for r in rows)
    for original, replayed in zip(rows, repeated):
        assert original["last_solve_time"] == replayed["last_solve_time"]
        if "residual_yx_px" in original:
            np.testing.assert_allclose(
                original["residual_yx_px"], replayed["residual_yx_px"]
            )


def test_default_and_invalid_opt_in_never_require_shared_state(monkeypatch, tmp_path):
    monkeypatch.delenv("MFNAVIS_VISUAL_TRACKING_EXPERIMENT", raising=False)
    assert create_shadow(object()) is None
    monkeypatch.setenv(
        "MFNAVIS_VISUAL_TRACKING_EXPERIMENT", str(tmp_path / "absent.json")
    )
    assert create_shadow(object()) is None


def test_old_request_does_not_restart_previous_session(live):
    live.align(timestamp=999)
    result = live.frame(1)
    assert result["state"] == "unavailable"
    assert live.shadow.session is None


def test_geometry_mismatch_invalidates_reference(live):
    live.align()
    live.frame(1)
    result = live.frame(2, calibration_id="changed")
    assert result["state"] == "unavailable"
    assert live.shadow.session.state == "geometry_changed"
    assert live.frame(3)["reason"] == "alignment_required"


def test_mismatched_raw_is_not_observation(live):
    live.align()
    result = live.frame(1, raw_entry={"frame_id": 99, "frame": np.zeros((512, 512))})
    assert result["state"] == "unavailable"
    assert live.shadow.session is None


def test_movement_and_realign_increase_generation(live):
    live.align()
    live.frame(1)
    assert live.frame(2, moving=True)["state"] == "manual_move"
    assert live.frame(3)["reason"] == "alignment_required"
    live.align("align2", 1003.5)
    result = live.frame(4)
    assert result["generation"] == 3
    assert live.frame(5)["state"] == "tracking_visual"


def test_solve_of_different_canvas_is_not_promoted(live):
    live.align()
    live.frame(1)
    solution = {
        "RA": 100,
        "Dec": 20,
        "Roll": 0,
        "FOV": 10,
        "_alignment_frame": [400, 400, 400],
    }
    result = live.frame(2, solution=solution)
    assert result["last_solve_time"] is None
    assert result["source"] == "stars"


def test_experiment_is_bounded(live):
    live.shadow.manifest["max_frames"] = 2
    live.align()
    live.frame(1)
    live.frame(2)
    assert live.frame(3)["reason"] == "experiment_limit"
    previous = live.shadow.log_path.read_text()
    live.frame(4)
    assert live.shadow.log_path.read_text() == previous


def test_input_arrays_and_accepted_solution_are_unchanged(live):
    live.align()
    solution = {
        "RA": 100,
        "Dec": 20,
        "Roll": 0,
        "FOV": 10,
        "_alignment_frame": [512, 512, 512],
    }
    before = json.dumps(solution, sort_keys=True)
    points = live.points.copy()
    live.frame(1)
    live.frame(2, solution=solution)
    np.testing.assert_array_equal(live.points, points)
    assert json.dumps(solution, sort_keys=True) == before


def test_legacy_lifecycle_is_mirrored_only_when_opted_in(monkeypatch):
    from PiFinder import visual_tracking_runtime as runtime

    calls = []
    monkeypatch.setattr(
        runtime, "write_request", lambda *args, **kw: calls.append(args)
    )
    monkeypatch.delenv("MFNAVIS_VISUAL_TRACKING_EXPERIMENT", raising=False)
    runtime.mirror_control("stop_movement")
    assert calls == []
    monkeypatch.setenv("MFNAVIS_VISUAL_TRACKING_EXPERIMENT", "/test/environment.json")
    runtime.mirror_control("stop_movement")
    runtime.mirror_control("goto_target")
    runtime.mirror_control("set_tracking_target")
    assert calls == [("/test/environment.json", "stop")] * 2


def test_shadow_stop_is_replayable(live):
    live.align()
    live.frame(1)
    atomic_json(
        live.shadow.output / "request.json",
        {
            "id": "stop",
            "command": "stop",
            "requested_at": 1001.5,
        },
    )
    result = live.frame(2)
    assert result["state"] == "idle"
    rows = [json.loads(row) for row in live.shadow.log_path.read_text().splitlines()]
    assert list(replay(rows))[-1]["state"] == "idle"
