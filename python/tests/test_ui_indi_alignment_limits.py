from datetime import datetime, timezone

import PiFinder.i18n  # noqa: F401
import pytest

from PiFinder.ui import indi


pytestmark = pytest.mark.unit


def make_screen():
    screen = object.__new__(indi.UIIndiMultiPointAlign)
    screen._status = lambda: {
        "alignment_min_altitude": 5.0,
        "alignment_max_altitude": 88.0,
    }
    return screen


def test_manual_star_pool_uses_both_published_limits(monkeypatch):
    screen = make_screen()
    screen._location_time_context = lambda: (
        37.0,
        127.0,
        0.0,
        datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    screen._completed_stars = lambda: []
    stars = [
        {"name": "low", "ra": 10},
        {"name": "high", "ra": 85},
        {"name": "outside", "ra": 89},
    ]
    monkeypatch.setattr("PiFinder.indi_align.BRIGHT_ALIGN_STARS", stars)
    monkeypatch.setattr(
        "PiFinder.indi_align.align_star_altaz", lambda star, *args: (star["ra"], 0)
    )
    assert [s["name"] for s in screen._manual_star_pool()] == ["low", "high"]


@pytest.mark.parametrize(
    "altitude,allowed",
    [(4, False), (5, True), (10, True), (85, True), (88, True), (89, False)],
)
def test_ui_goto_uses_published_limits(altitude, allowed):
    screen = make_screen()
    screen._selected_star = lambda: {"name": "Vega"}
    screen._star_altitude = lambda star: altitude
    sent = []
    screen._send_mount = lambda command: sent.append(command) or True
    screen.message = lambda *args: None
    screen.update = lambda: None
    screen._select_star_and_goto()
    assert bool(sent) is allowed


def test_ui_limits_fall_back_without_status():
    screen = make_screen()
    screen._status = lambda: {}
    assert screen._alignment_altitude_limits() == (20, 78)
