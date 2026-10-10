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
