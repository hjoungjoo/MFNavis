import json
from queue import Queue
from types import SimpleNamespace

import pytest
import PiFinder.i18n  # noqa: F401

from PiFinder import goto_arrival as arrival
from PiFinder.ui.align import align_on_radec

pytestmark = pytest.mark.unit


@pytest.fixture
def waiting(monkeypatch, tmp_path):
    monkeypatch.setattr(arrival.utils, "runtime_dir", tmp_path)
    monkeypatch.setattr(arrival.time, "time", lambda: 1000.0)
    status = tmp_path / "indi_goto_guide_status.json"
    status.write_text(
        json.dumps(
            {"updated": 1000, "goto_method": "mfnavis", "phase": "manual_retarget"}
        )
    )
    solution = SimpleNamespace(last_solve_success=990, last_solve_attempt=999)
    return status, solution, SimpleNamespace(solution=lambda: solution)


def test_lcd_align_confirms_unsolved_arrival_without_waiting_for_solver(waiting):
    _, _, shared = waiting
    queues = {"goto_guide": Queue(), "console": Queue(), "align_command": Queue()}
    assert align_on_radec(110, 30, queues, None, shared)
    assert queues["goto_guide"].get_nowait() == {
        "type": "confirm_goto_arrival",
        "ra": 110,
        "dec": 30,
        "requested_wall": 1000,
    }
    assert queues["align_command"].empty()


@pytest.mark.parametrize(
    "change", ["fresh_solve", "expired_status", "completed", "limit", "indi_mount"]
)
def test_confirmation_only_routes_active_unsolved_goto(waiting, change):
    path, solution, shared = waiting
    status = json.loads(path.read_text())
    if change == "fresh_solve":
        solution.last_solve_success = solution.last_solve_attempt
    elif change == "expired_status":
        status["updated"] = 990
    elif change == "completed":
        status["phase"] = "complete"
    elif change == "limit":
        status["phase"] = "limit_exceeded"
    else:
        status["goto_method"] = "indi_mount"
    path.write_text(json.dumps(status))
    commands = Queue()
    assert not arrival.queue_unsolved_arrival(commands, shared, 110, 30)
    assert commands.empty()


@pytest.mark.parametrize("has_pointing", [False, True])
@pytest.mark.parametrize("fresh_solve", [False, True])
def test_skysafari_unsolved_align_preserves_catalogue_alignment_intent(
    waiting, monkeypatch, has_pointing, fresh_solve
):
    from PiFinder import pos_server

    _, solution, shared = waiting
    if fresh_solve:
        solution.last_solve_success = solution.last_solve_attempt
    guide = Queue()
    monkeypatch.setattr(pos_server, "goto_guide_queue", guide)
    monkeypatch.setattr(
        pos_server, "_target_from_parsed_coordinates", lambda: (110, 30)
    )
    monkeypatch.setattr(
        pos_server, "_queue_multipoint_align_confirm_if_active", lambda *a: False
    )
    monkeypatch.setattr(
        pos_server, "_get_config_option", lambda key, default=None: default
    )
    monkeypatch.setattr(pos_server, "_catalog_target", lambda state, ra, dec: (ra, dec))
    monkeypatch.setattr(pos_server, "_has_solved_pointing", lambda state: has_pointing)
    monkeypatch.setattr(pos_server, "_align_pifinder_if_enabled", lambda *a: False)
    assert pos_server.handle_sync_command(shared, ":CM#") == "Alignment requested."
    assert guide.get_nowait() == dict(
        type="confirm_goto_arrival",
        ra=110,
        dec=30,
        requested_wall=1000,
        align_target=True,
    )


def test_skysafari_failed_attempt_does_not_bypass_valid_cached_alignment(
    waiting, monkeypatch
):
    from PiFinder import pos_server

    _, _, shared = waiting
    shared.target_pixel = lambda: (250, 270)
    guide = Queue()
    monkeypatch.setattr(pos_server, "goto_guide_queue", guide)
    monkeypatch.setattr(
        pos_server, "_target_from_parsed_coordinates", lambda: (110, 30)
    )
    monkeypatch.setattr(
        pos_server, "_queue_multipoint_align_confirm_if_active", lambda *a: False
    )
    monkeypatch.setattr(
        pos_server, "_get_config_option", lambda key, default=None: default
    )
    monkeypatch.setattr(pos_server, "_catalog_target", lambda state, ra, dec: (ra, dec))
    monkeypatch.setattr(pos_server, "_has_solved_pointing", lambda state: True)
    monkeypatch.setattr(pos_server, "_align_pifinder_if_enabled", lambda *a: True)
    monkeypatch.setattr(pos_server, "_queue_indi_sync_if_enabled", lambda *a: False)
    monkeypatch.setattr(pos_server, "_publish_push_target", lambda *a, **kw: None)
    assert pos_server.handle_sync_command(shared, ":CM#") == "Coordinates matched."
    assert guide.get_nowait() == dict(
        type="set_tracking_target", ra=110, dec=30, alignment_target_pixel=[250, 270]
    )
    assert guide.empty()
