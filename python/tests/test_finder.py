"""Finder navigation, camera geometry and displayed-centre GoTo commands."""

from queue import Queue
from dataclasses import replace
from datetime import datetime, timezone
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import quaternion
from PIL import Image, ImageDraw

import PiFinder.i18n  # noqa: F401
from PiFinder.displays import DisplayHeadless, DisplayHeadless176, DisplayHeadless320
from PiFinder.state import UIState
from PiFinder.ui import chart as chart_module, menu_structure
from PiFinder.ui.finder import UIFinder
from PiFinder.ui.menu_manager import MenuManager
from PiFinder.types.positioning import ImuSample, PointingEstimate, SolveSource
from test_chart_runtime import FakeStarfield, marker

pytestmark = pytest.mark.unit


def solution(ra=123.45, dec=-32.1, timestamp=10.0):
    return SimpleNamespace(
        estimate_time=timestamp,
        has_pointing=lambda: True,
        pointing=SimpleNamespace(
            aligned=SimpleNamespace(estimate=SimpleNamespace(RA=ra, Dec=dec)),
            camera=SimpleNamespace(estimate=SimpleNamespace(RA=120.0, Dec=-30.0)),
        ),
    )


@pytest.fixture(params=(DisplayHeadless, DisplayHeadless176, DisplayHeadless320))
def finder(request, monkeypatch):
    monkeypatch.setattr(chart_module.plot, "Starfield", FakeStarfield)
    settings = {
        "mount_control": True,
        "indi_goto_method": "mfnavis",
        "chart_coord_sys": "eq_north_up",
        "chart_reticle": 128,
        "chart_dso": 0,
        "chart_center_object": "Off",
    }
    config = SimpleNamespace(
        get_option=lambda key, default=None: settings.get(key, default)
    )
    ui = UIState()
    shared = SimpleNamespace(
        ui_state=lambda: ui,
        solution=lambda: solution(),
        solve_state=lambda: True,
        target_pixel=lambda: (230.25, 310.75),
        camera_type=lambda: "imx296",
        camera_lens=lambda: "",
        camera_manual_focal_mm=lambda: None,
        location=lambda: None,
        datetime=lambda: None,
        imu=lambda: None,
    )
    screen = UIFinder(
        request.param(),
        Image.new("L", (512, 512)),
        shared,
        {key: Queue() for key in ("mountcontrol", "goto_guide", "align_command")},
        config,
        None,
        add_to_stack=Mock(),
    )
    screen.screen_update = Mock(return_value=screen.screen)
    screen.message = Mock()
    screen.test_settings = settings
    screen.active()
    return screen


def test_finder_is_immediately_above_chart_in_main_menu():
    items = menu_structure.pifinder_menu["items"]
    index = next(i for i, item in enumerate(items) if item.get("class") is UIFinder)
    assert items[index]["name"] == "Finder"
    assert items[index]["label"] == "finder"
    assert items[index + 1]["class"] is chart_module.UIChart


def test_square_cycles_two_modes_and_restores_chart_without_new_solve(finder):
    assert finder.display_mode == "camera"
    finder.update()
    finder.key_square()
    assert finder.display_mode == "chart"
    assert finder.starfield.frames == 1
    finder.key_plus()
    assert finder.fov == 5
    finder.key_square()
    assert finder.display_mode == "camera"
    finder.key_plus()
    assert finder.camera_zoom_level == 1
    finder.key_square()
    assert finder.display_mode == "chart"
    assert finder.fov == 5
    assert finder.starfield.frames == 3
    finder.key_minus()
    assert finder.fov == 10.2
    finder.key_square()
    assert finder.display_mode == "camera"
    assert finder.camera_zoom_level == 1


def test_camera_is_full_height_with_no_title_or_information_bands(finder):
    finder.camera_image.paste(128, (0, 0, 512, 512))
    finder.draw = Mock(wraps=finder.draw)
    finder.update()
    finder.screen_update.assert_called_once_with(title_bar=False, button_hints=False)
    finder.draw.text.assert_not_called()
    width, height = finder.screen.size
    left = (width - min(width, height)) // 2
    assert finder.screen.getpixel((left, 0)) == finder.colors.get(128)
    assert finder.screen.getpixel((left, height - 1)) == finder.colors.get(128)


@pytest.mark.parametrize("zoom", (0, 1, 2))
def test_camera_zoom_keeps_star_at_reticle_centre(finder, zoom):
    finder.camera_zoom_level = zoom
    y, x = finder.shared_state.target_pixel()
    ImageDraw.Draw(finder.camera_image).ellipse((x - 4, y - 4, x + 4, y + 4), fill=255)
    finder.update()
    width, height = finder.screen.size
    side = min(width, height)
    cx = (width - side) / 2 + (x + 0.5) * side / 512 - 0.5
    cy = (height - side) / 2 + (y + 0.5) * side / 512 - 0.5
    if zoom:
        cx, cy = (width - 1) / 2, (height - 1) / 2
    assert finder.screen.getpixel((round(cx), round(cy)))[0] > 100
    finder.camera_image.paste(0, (0, 0, 512, 512))
    finder.update()
    assert finder.screen.getpixel((round(cx), round(cy))) == (0, 0, 0)


def test_camera_zoom_limits_and_right_does_not_open_old_chart_object(finder):
    for _ in range(4):
        finder.key_plus()
    assert finder.camera_zoom_level == 2
    for _ in range(4):
        finder.key_minus()
    assert finder.camera_zoom_level == 0
    finder.key_right()
    finder.add_to_stack.assert_not_called()


@pytest.mark.parametrize("mode", ("camera", "chart"))
def test_right_shortcuts_stay_in_finder_with_center_and_recent_objects(finder, mode):
    obj = marker(1)
    finder.ui_state.set_target(obj)
    finder.test_settings["chart_center_object"] = "On"
    finder.draw = Mock(wraps=finder.draw)
    finder.key_square()
    assert finder._center_tracker.center_object is obj
    assert finder._center_scroller is not None
    assert not any(
        call.args[1] == finder._RIGHT_ARROW for call in finder.draw.text.call_args_list
    )
    if mode == "camera":
        finder.key_square()

    manager = MenuManager.__new__(MenuManager)
    manager.stack = [finder]
    manager.help_images = None
    manager.marking_menu_stack = []
    manager.ui_state = SimpleNamespace(recent_list=lambda: [obj])
    manager.add_to_stack = finder.add_to_stack
    center = finder.serialize_ui_state()["goto_center"]
    manager.key_right()
    manager.key_long_right()
    finder.add_to_stack.assert_not_called()
    assert manager.stack == [finder]
    assert finder.display_mode == mode
    assert finder.serialize_ui_state()["goto_center"] == center

    finder.key_number_press(8)
    finder.key_number_release(8)
    queue = finder.command_queues["mountcontrol"]
    assert queue.get_nowait()["direction"] == "north"
    assert queue.get_nowait() == {"type": "stop_movement"}
    finder.key_number(5)
    assert finder.command_queues["goto_guide"].get_nowait() == {
        "type": "goto_target",
        "ra": center[0],
        "dec": center[1],
    }


@pytest.mark.parametrize("mode", ("camera", "chart"))
@pytest.mark.parametrize("command", ("key", "press", "align"))
def test_goto_uses_displayed_aligned_centre_for_every_input(finder, mode, command):
    if mode == "chart":
        finder.key_square()
    finder.update()
    assert finder.serialize_ui_state()["goto_center"] == (123.45, -32.1)
    # A later estimator update must not replace the coordinates the user saw.
    finder.shared_state.solution = lambda: solution(222.0, 44.0, 11.0)
    if command == "key":
        finder.key_number(5)
    elif command == "press":
        finder.key_number_press(5)
        finder.key_number_release(5)
    else:
        submenu = finder.marking_menu.down.callback
        assert submenu.right.callback(submenu, submenu.right) is True
    queue = finder.command_queues["goto_guide"]
    assert queue.get_nowait() == {"type": "goto_target", "ra": 123.45, "dec": -32.1}
    assert queue.empty()
    assert finder.command_queues["align_command"].empty()


@pytest.mark.parametrize("mode", ("camera", "chart"))
@pytest.mark.parametrize("invalid", ("unsolved", "missing", "nan", "range"))
def test_invalid_pointing_never_sends_goto(finder, mode, invalid):
    finder.update()
    if mode == "chart":
        finder.key_square()
    if invalid == "unsolved":
        finder.shared_state.solve_state = lambda: False
        finder.shared_state.solution = lambda: PointingEstimate()
        finder.update()
    elif invalid == "missing":
        finder.shared_state.solution = lambda: None
        # No chart is rendered without either pointing source.
        finder.shared_state.solve_state = lambda: False
        finder.update()
    else:
        bad = solution(float("nan"), 0.0) if invalid == "nan" else solution(12.0, 91.0)
        finder.shared_state.solution = lambda: bad
        finder.update(force=True)
    finder.key_number(5)
    finder.mm_align(None, None)
    assert finder.command_queues["goto_guide"].empty()
    assert finder.command_queues["mountcontrol"].empty()
    finder.message.assert_called_with("No solve", 1)


@pytest.mark.parametrize("mode", ("camera", "chart"))
def test_lost_pointing_between_draw_and_input_blocks_goto(finder, mode):
    if mode == "chart":
        finder.key_square()
    finder.update()
    finder.shared_state.solve_state = lambda: False
    finder.shared_state.solution = lambda: PointingEstimate()
    finder.key_number_press(5)
    assert finder.command_queues["goto_guide"].empty()


@pytest.mark.parametrize("pixel", (None, (-1, -1), (float("nan"), 256)))
def test_no_camera_reticle_means_no_goto(finder, pixel):
    finder.shared_state.target_pixel = lambda: pixel
    finder.update()
    finder.key_number(5)
    assert finder.command_queues["goto_guide"].empty()


def test_mount_disabled_and_goto_off_do_not_send_goto(finder):
    finder.update()
    finder.test_settings["mount_control"] = False
    finder.key_number(5)
    assert finder.command_queues["goto_guide"].empty()
    finder.test_settings["mount_control"] = True
    finder.test_settings["indi_goto_method"] = "off"
    finder.key_number(5)
    assert finder.command_queues["goto_guide"].empty()


def test_goto_falls_back_to_mount_queue_and_stop_is_preserved(finder):
    finder.command_queues.pop("goto_guide")
    finder.update()
    finder.mm_align(None, None)
    assert finder.command_queues["mountcontrol"].get_nowait() == {
        "type": "goto_target",
        "ra": 123.45,
        "dec": -32.1,
    }
    finder.key_number(0)
    commands = []
    queue = finder.command_queues["mountcontrol"]
    while not queue.empty():
        commands.append(queue.get_nowait())
    assert commands[-1] == {"type": "stop_movement", "stop_tracking": True}


@pytest.fixture
def imu_only(finder):
    finder.shared_state.solution = lambda: PointingEstimate()
    finder.shared_state.solve_state = lambda: False
    finder.shared_state.location = lambda: SimpleNamespace(
        lat=37.5, lon=127.0, altitude=30.0, lock=True
    )
    finder.shared_state.datetime = lambda: datetime(2026, 10, 14, tzinfo=timezone.utc)
    finder.test_imu = ImuSample(
        quaternion.quaternion(1, 0, 0, 0), time.time(), status=3
    )
    finder.shared_state.imu = lambda: finder.test_imu
    # Finder pointing is independent of the SkySafari setting in both modes.
    finder.test_settings["skysafari_imu_fallback"] = False
    return finder


@pytest.mark.parametrize("mode", ("camera", "chart"))
def test_unsolved_finder_uses_real_imu_projection_and_goto(imu_only, mode):
    finder = imu_only
    if mode == "chart":
        finder.key_square()
    else:
        finder.update()
    initial = finder.serialize_ui_state()
    assert finder._chart_pointing_source == "imu"
    ra, dec = initial["goto_center"]
    assert 0 <= ra < 360 and -90 <= dec <= 90
    if mode == "chart":
        assert finder._chart_backdrop is not None
    finder.key_number(5)
    assert finder.command_queues["goto_guide"].get_nowait() == {
        "type": "goto_target",
        "ra": ra,
        "dec": dec,
    }
    finder.test_imu = replace(
        finder.test_imu,
        quat=quaternion.from_rotation_vector([0.1, 0.2, 0.3]),
        timestamp=time.time(),
    )
    finder.update()
    moved = finder.serialize_ui_state()["goto_center"]
    assert moved != (ra, dec)
    finder.mm_align(None, None)
    assert finder.command_queues["goto_guide"].get_nowait() == {
        "type": "goto_target",
        "ra": moved[0],
        "dec": moved[1],
    }
    # A UI fallback must never turn itself into a successful optical solve.
    assert not finder.shared_state.solution().has_pointing()
    assert not finder.shared_state.solve_state()


@pytest.mark.parametrize("mode", ("camera", "chart"))
@pytest.mark.parametrize("command", ("key", "press", "align"))
def test_unsolved_goto_freezes_displayed_imu_coordinates(imu_only, mode, command):
    finder = imu_only
    if mode == "chart":
        finder.key_square()
    else:
        finder.update()
    ra, dec = finder.serialize_ui_state()["goto_center"]
    finder.test_imu = replace(
        finder.test_imu,
        quat=quaternion.from_rotation_vector([0.1, 0.2, 0.3]),
        timestamp=time.time(),
    )
    if command == "key":
        finder.key_number(5)
    elif command == "press":
        finder.key_number_press(5)
        finder.key_number_release(5)
    else:
        finder.mm_align(None, None)
    queue = finder.command_queues["goto_guide"]
    assert queue.get_nowait() == {"type": "goto_target", "ra": ra, "dec": dec}
    assert queue.empty()
    assert finder.command_queues["align_command"].empty()


@pytest.mark.parametrize("mode", ("camera", "chart"))
def test_imu_finder_recovers_to_optical_solve_and_keeps_failed_plate_estimate(
    imu_only, mode
):
    finder = imu_only
    if mode == "chart":
        finder.key_square()
    else:
        finder.update()
    assert finder._chart_pointing_source == "imu"
    # A new plate can have an older epoch than the last displayed IMU sample.
    plate = solution()
    plate.solve_source = SolveSource.CAMERA
    finder.shared_state.solution = lambda: plate
    finder.update()
    assert finder._chart_pointing_source == "solve"
    assert finder.serialize_ui_state()["goto_center"] == (123.45, -32.1)
    for source in (SolveSource.IMU, SolveSource.CAMERA_FAILED):
        plate.solve_source = source
        plate.pointing.aligned.estimate.RA = 124.0
        finder.update()
        assert finder._chart_pointing_source == "imu"
        assert finder.serialize_ui_state()["goto_center"] == (124.0, -32.1)
        finder.key_number(5)
        assert finder.command_queues["goto_guide"].get_nowait() == {
            "type": "goto_target",
            "ra": 124.0,
            "dec": -32.1,
        }


@pytest.mark.parametrize("failure", ("stale", "unhealthy", "uncalibrated", "location"))
@pytest.mark.parametrize("mode", ("camera", "chart"))
@pytest.mark.parametrize("redraw", (False, True))
def test_imu_fallback_loss_blocks_goto(imu_only, failure, mode, redraw):
    finder = imu_only
    if mode == "chart":
        finder.key_square()
    else:
        finder.update()
    assert finder.serialize_ui_state()["goto_center"] is not None
    if failure == "stale":
        finder.test_imu = replace(finder.test_imu, timestamp=time.time() - 60)
    elif failure == "unhealthy":
        finder.test_imu = replace(finder.test_imu, sensor_healthy=False)
    elif failure == "uncalibrated":
        finder.test_imu = replace(finder.test_imu, status=0)
    else:
        finder.shared_state.location = lambda: None
    if redraw:
        finder.update()
        assert finder._chart_backdrop is None
        assert finder.serialize_ui_state()["goto_center"] is None
    finder.key_number(5)
    assert finder.command_queues["goto_guide"].empty()


@pytest.mark.parametrize("mode", ("camera", "chart"))
def test_imu_finder_can_use_saved_observing_site_without_gps_lock(imu_only, mode):
    finder = imu_only
    finder.shared_state.location = lambda: None
    finder.test_settings["locations.default"] = SimpleNamespace(
        latitude=37.5, longitude=127.0, height=30.0
    )
    if mode == "chart":
        finder.key_square()
    else:
        finder.update()
    assert finder._chart_pointing_source == "imu"
    assert finder.serialize_ui_state()["goto_center"] is not None
    assert finder.shared_state.location() is None
