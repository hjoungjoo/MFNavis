from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw

import PiFinder.i18n  # noqa: F401
from PiFinder.displays import DisplayHeadless, DisplayHeadless176, DisplayHeadless320
from PiFinder.ui import base, fonts


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "display_type", [DisplayHeadless, DisplayHeadless176, DisplayHeadless320]
)
@pytest.mark.parametrize("language", ["en", "ko"])
@pytest.mark.parametrize("clock_warning", [False, True])
@pytest.mark.parametrize("solved", [False, True])
def test_titlebar_status_glyphs_have_clear_gaps(
    monkeypatch, display_type, language, clock_warning, solved
):
    monkeypatch.setattr(
        fonts.config,
        "Config",
        lambda: SimpleNamespace(
            get_option=lambda key, default=None: language
            if key == "language"
            else default
        ),
    )
    monkeypatch.setattr(base.time, "time", lambda: 1000.75)
    display = display_type()
    screen = base.UIModule.__new__(base.UIModule)
    screen.display_class = display
    screen.fonts = display.fonts
    screen.colors = display.colors
    screen.screen = Image.new("RGB", display.resolution)
    screen.draw = Mock(wraps=ImageDraw.Draw(screen.screen))
    screen.title = "A very long title for the status bar"
    screen.ui_state = SimpleNamespace(message_timeout=lambda: 0, show_fps=lambda: False)
    screen.shared_state = SimpleNamespace(
        imu=lambda: None,
        altaz_ready=lambda: True,
        solve_state=lambda: solved,
        solution=lambda: SimpleNamespace(
            is_camera_solve=lambda: True, last_solve_success=1000.5
        ),
    )
    screen._guide_send_motion_keepalive = Mock()
    screen._clock_untrusted = lambda: clock_warning
    screen._indi_indicator_spec = lambda: ("M", "ok")
    screen.frame_count = 0
    screen.fps = 0
    screen.last_fps_sample_time = 1000
    screen.last_update_time = 1000
    screen.screen_update()

    bounds = []
    for call in screen.draw.text.call_args_list:
        position, text = call.args
        left, _, right, _ = call.kwargs["font"].getbbox(text)
        bounds.append((position[0] + left, position[0] + right, text))
    bounds.sort()
    assert len(bounds) == (5 if clock_warning else 4)
    assert bounds[-1][1] <= display.resX - 4
    for previous, current in zip(bounds, bounds[1:]):
        assert current[0] - previous[1] >= 3, (previous, current)
    assert bounds[-1][2] == (screen._CAM_ICON if solved else "X")
