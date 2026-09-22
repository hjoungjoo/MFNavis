"""Camera push geometry and mode navigation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw, ImageFont

import PiFinder.i18n  # noqa: F401
from PiFinder.ui.object_details import (
    DM_CAMERA,
    DM_CONTRAST,
    DM_DESC,
    DM_LOCATE,
    DM_POSS,
    UIObjectDetails,
)

pytestmark = pytest.mark.unit


def camera_ui(resolution, target):
    ui = UIObjectDetails.__new__(UIObjectDetails)
    width, height = resolution
    ui.display_class = SimpleNamespace(
        resolution=resolution,
        resX=width,
        resY=height,
        titlebar_height=16,
    )
    font = SimpleNamespace(font=ImageFont.load_default(), height=10)
    ui.fonts = SimpleNamespace(base=font, small=font, large=font)
    ui.colors = SimpleNamespace(get=lambda value: (value, 0, 0))
    ui.screen = Image.new("RGB", resolution)
    ui.draw = ImageDraw.Draw(ui.screen, "RGBA")
    ui.camera_image = Image.new("L", (512, 512))
    ui.object = SimpleNamespace(display_name="Test star", obj_type="*", const="ORI")
    ui.shared_state = SimpleNamespace(
        target_pixel=lambda: target,
        camera_type=lambda: "imx296",
        camera_lens=lambda: "",
        camera_manual_focal_mm=lambda: None,
    )
    ui._camera_optics = SimpleNamespace(
        resolve=lambda *args: SimpleNamespace(fov_degrees=10.2)
    )
    ui._draw_camera_pointer = Mock()
    ui._render_pointing_instructions = Mock()
    ui._render_push_status = Mock()
    return ui


@pytest.mark.parametrize("resolution", [(128, 128), (320, 240)])
def test_alignment_ring_matches_live_star_and_leaves_center_open(resolution):
    ui = camera_ui(resolution, (230, 310))
    ImageDraw.Draw(ui.camera_image).ellipse((306, 226, 314, 234), fill=255)
    ui._render_camera_push()
    width, height = resolution
    side = min(width, height - 16)
    x = (width - side) // 2 + (310.5 * side / 512) - 0.5
    y = 16 + (height - 16 - side) // 2 + (230.5 * side / 512) - 0.5
    radius = side / 10.2  # middle (2 degree) segmented circle
    assert ui.screen.getpixel((round(x), round(y)))[0] > 100
    assert any(
        ui.screen.getpixel((px, py))[0] == 192
        for px in range(round(x + radius * 0.7) - 2, round(x + radius * 0.7) + 3)
        for py in range(round(y + radius * 0.7) - 2, round(y + radius * 0.7) + 3)
    )
    ui.camera_image.paste(0, (0, 0, 512, 512))
    ui._render_camera_push()
    assert ui.screen.getpixel((round(x), round(y))) == (0, 0, 0)
    ui._render_pointing_instructions.assert_called_with(compact=True)


@pytest.mark.parametrize("target", [None, (-1, -1), (float("nan"), 256), (512, 256)])
def test_unavailable_alignment_does_not_invent_center_marker(target):
    ui = camera_ui((128, 128), target)
    ui._render_camera_push()
    assert ui.screen.crop((30, 45, 100, 85)).getbbox() is None


def test_square_cycles_camera_and_existing_modes():
    ui = UIObjectDetails.__new__(UIObjectDetails)
    ui.object_display_mode = DM_LOCATE
    ui.update_object_info = Mock()
    ui.update = Mock()
    for expected in (DM_CAMERA, DM_POSS, DM_DESC, DM_CONTRAST, DM_LOCATE):
        ui.key_square()
        assert ui.object_display_mode == expected


def test_camera_without_solve_keeps_compact_wait_message():
    ui = camera_ui((128, 128), (256, 256))
    del ui._render_pointing_instructions
    ui._refresh_push_status = Mock()
    ui.shared_state.solution = lambda: SimpleNamespace(has_pointing=lambda: False)
    ui._elipsis_count = 0
    ui._render_camera_push()
    assert ui._elipsis_count == 1


@pytest.mark.parametrize(
    "mount_type,reverse,expected",
    [
        ("Alt/Az", "Default", ("L0.005°", "U  1.2°")),
        ("Alt/Az", "Reverse", ("R0.005°", "U  1.2°")),
        ("EQ", "Default", ("-0.005°", "+  1.2°")),
    ],
)
def test_compact_guidance_preserves_signs_and_fine_precision(
    monkeypatch, mount_type, reverse, expected
):
    ui = camera_ui((128, 128), (256, 256))
    del ui._render_pointing_instructions
    ui._refresh_push_status = Mock()
    ui.shared_state.solution = lambda: SimpleNamespace(has_pointing=lambda: True)
    ui.shared_state.altaz_ready = lambda: True
    ui._check_catalog_initialized = lambda: True
    ui._push_display_solution = lambda: None
    ui.mount_type = mount_type
    ui.screen_direction = "right"
    ui._unmoved = True
    ui.config_object = SimpleNamespace(get_option=lambda *args: reverse)
    ui._LEFT_ARROW, ui._RIGHT_ARROW = "L", "R"
    ui._UP_ARROW, ui._DOWN_ARROW = "U", "D"
    ui.draw = Mock()
    monkeypatch.setattr(
        "PiFinder.ui.object_details.calc_utils.aim_degrees",
        lambda *a, **k: (-0.005, 1.2),
    )
    ui._render_pointing_instructions(compact=True)
    assert tuple(call.args[1] for call in ui.draw.text.call_args_list) == expected


@pytest.mark.parametrize(
    "ra,dec,roll,expected",
    [(1, 0, 0, 180), (-1, 0, 0, 0), (0, 1, 0, -90), (1, 0, 90, 90)],
)
def test_pointer_follows_camera_rotation(ra, dec, roll, expected):
    from PiFinder.ui.camera_guidance import target_direction

    camera = SimpleNamespace(RA=0, Dec=0, Roll=roll)
    angle = target_direction(camera, ra, dec, (256, 256), 10.2)
    assert (angle - expected + 180) % 360 - 180 == pytest.approx(0)


def test_pointer_suppressed_at_alignment_point():
    from PiFinder.ui.camera_guidance import target_direction

    camera = SimpleNamespace(RA=0, Dec=0, Roll=0)
    assert target_direction(camera, 0, 0, (256, 256), 10.2) is None
    assert target_direction(camera, 0, 0, (256, 300), 10.2) == pytest.approx(180)
