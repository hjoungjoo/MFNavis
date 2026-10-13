"""Exercise the real Chart UI with a deterministic, disk-free starfield."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image, ImageDraw

import PiFinder.i18n  # noqa: F401
from PiFinder.displays import DisplayHeadless, DisplayHeadless176, DisplayHeadless320
from PiFinder.ui import chart as chart_module, menu_structure
from PiFinder.ui.menu_manager import MenuManager

pytestmark = pytest.mark.unit


def marker(identity, ra=0.0):
    return SimpleNamespace(
        object_id=identity,
        ra=ra,
        dec=0.0,
        obj_type="Gx",
        display_name=f"NGC {identity}",
        names=[],
        size=SimpleNamespace(is_vertices=False),
    )


class FakeStarfield:
    def __init__(self, colors, resolution):
        self.resolution = resolution
        self.calls = []
        self.frames = 0

    def set_fov(self, fov):
        self.fov = fov

    def plot_starfield(self, *args):
        self.frames += 1
        return Image.new("RGB", self.resolution), []

    def plot_markers(self, markers):
        self.calls.append(markers)
        image = Image.new("RGB", self.resolution)
        ImageDraw.Draw(image).point(
            (self.resolution[0] // 2, self.resolution[1] // 2), fill=(255, 0, 0)
        )
        return image

    def radec_to_xy_many(self, ras, decs):
        return (
            [self.resolution[0] / 2 + ra for ra in ras],
            [self.resolution[1] / 2 + dec for dec in decs],
        )

    def radec_to_xy(self, ra, dec):
        xs, ys = self.radec_to_xy_many([ra], [dec])
        return xs[0], ys[0]


@pytest.fixture(params=(DisplayHeadless, DisplayHeadless176, DisplayHeadless320))
def chart(request, monkeypatch):
    monkeypatch.setattr(chart_module.plot, "Starfield", FakeStarfield)
    settings = {
        "chart_center_object": "On",
        "chart_dso": 128,
        "chart_radec": "Off",
        "chart_coord_sys": "eq_north_up",
        "chart_reticle": 0,
        "text_scroll_speed": "Off",
    }
    config = SimpleNamespace(
        get_option=lambda key, default=None: settings.get(key, default)
    )
    ui = SimpleNamespace(target_obj=None, objects=[marker(1), marker(2, 8.0)])
    ui.target = lambda: ui.target_obj
    ui.observing_list = lambda: ui.objects
    estimate = SimpleNamespace(RA=0.0, Dec=0.0)
    solution = SimpleNamespace(
        estimate_time=10.0,
        has_pointing=lambda: True,
        pointing=SimpleNamespace(aligned=SimpleNamespace(estimate=estimate)),
    )
    shared = SimpleNamespace(
        ui_state=lambda: ui,
        solution=lambda: solution,
        solve_state=lambda: True,
        location=lambda: None,
        datetime=lambda: None,
    )
    screen = chart_module.UIChart(
        request.param(), None, shared, {}, config, None, add_to_stack=MagicMock()
    )
    screen.screen_update = lambda: screen.screen
    screen.test_settings = settings
    screen.active()
    return screen


def test_chart_constructs_draws_center_and_opens_ranked_details(chart):
    chart.update()
    state = chart.serialize_ui_state()
    assert state["center_object"]["object_id"] == 1
    assert chart._chart_backdrop is not None
    chart.key_right()
    pushed = chart.add_to_stack.call_args.args[0]
    assert pushed["object"].object_id == 1
    assert [obj.object_id for obj in pushed["object_list"]] == [1, 2]


def test_standalone_chart_long_right_still_opens_recent_object(chart):
    obj = marker(9)
    manager = MenuManager.__new__(MenuManager)
    manager.stack = [chart]
    manager.ui_state = SimpleNamespace(recent_list=lambda: [obj])
    manager.add_to_stack = MagicMock()
    manager.key_long_right()
    assert manager.add_to_stack.call_args.args[0]["object"] is obj


def test_target_remains_visible_when_dso_markers_are_off(chart):
    chart.test_settings["chart_dso"] = 0
    chart.ui_state.target_obj = marker(9)
    chart.update()
    assert chart.starfield.calls == [[(0.0, 0.0, "target")]]
    assert chart.serialize_ui_state()["center_object"]["object_id"] == 9
    center = (chart.display_class.centerX, chart.display_class.centerY)
    assert chart.screen.getpixel(center)[0] == 255


def test_disabled_center_readout_clears_pick_and_right_is_inert(chart):
    chart.update()
    chart.test_settings["chart_center_object"] = "Off"
    chart.active()  # Settings return, same pointing timestamp.
    chart.update()
    assert chart.serialize_ui_state()["center_object"] is None
    chart.key_right()
    chart.add_to_stack.assert_not_called()


def test_return_from_details_redraws_new_target_without_new_solve(chart):
    chart.ui_state.objects = []
    chart.update()
    chart.ui_state.target_obj = marker(9)
    chart.active()
    chart.update()
    assert chart.starfield.frames == 2
    assert chart.starfield.calls[-1] == [(0.0, 0.0, "target")]
    assert chart.serialize_ui_state()["center_object"]["object_id"] == 9


def test_no_solve_clears_readout_and_right_is_inert(chart):
    chart.update()
    chart.shared_state.solve_state = lambda: False
    chart.shared_state.solution = lambda: None
    chart.update()
    assert chart.serialize_ui_state()["center_object"] is None
    assert chart._chart_backdrop is None
    chart.key_right()
    chart.add_to_stack.assert_not_called()


@pytest.mark.parametrize("radec", ("Off", "HH:MM", "Degr"))
def test_readout_draws_on_each_panel_without_covering_coordinate_row(chart, radec):
    chart.test_settings["chart_radec"] = radec
    chart.update()
    assert chart._center_scroller is not None
    strip_y = chart._center_readout_y()
    if radec != "Off":
        assert strip_y + chart.fonts.base.height < (
            chart.display_class.resY - chart.fonts.base.height - 3
        )
    frame_count = chart.starfield.frames
    chart.update()  # Readout continues without rebuilding the sky.
    assert chart.starfield.frames == frame_count


def test_center_object_setting_is_only_in_chart_settings():
    paths = []

    def walk(node, path):
        path = path + [node.get("label")]
        if node.get("config_option") == "chart_center_object":
            paths.append(path)
        for child in node.get("items", []):
            walk(child, path)

    walk(menu_structure.pifinder_menu, [])
    assert len(paths) == 1
    assert "chart_settings" in paths[0]
