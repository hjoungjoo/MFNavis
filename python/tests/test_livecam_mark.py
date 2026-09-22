"""Mark overlays share the LCD target, but follow LiveCam pixel geometry."""

from types import SimpleNamespace
from unittest.mock import Mock
import io

import numpy as np
import pytest
from PIL import Image

from PiFinder import livecam_mark
from PiFinder.raw_live_stack import RawLiveStackProcessor

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("display_rotation", [0, 90, 180, 270])
@pytest.mark.parametrize(
    "source",
    ["original_raw", "star_only", "cropped_raw", "resized_512", "solver_input"],
)
def test_alignment_follows_the_same_star_through_image_rotations(
    rotation, display_rotation, source
):
    # A square 512 crop from a larger rectangular frame. Put a star off centre
    # and follow actual np.rot90 images, independently of the coordinate helper.
    raw = np.zeros((600, 800), dtype=np.uint8)
    raw[190, 450] = 255
    crop = raw[44:556, 144:656]
    production = np.rot90(crop, rotation // 90)
    target = np.argwhere(production == 255)[0]
    if source in ("original_raw", "star_only"):
        frame = raw
    elif source == "solver_input":
        frame = production
    else:
        frame = crop
    frame = np.rot90(frame, display_rotation // 90)
    expected_y, expected_x = np.argwhere(frame == 255)[0]
    size = (frame.shape[1] // 2, frame.shape[0] // 2)
    center, side, _ = livecam_mark.mark_geometry(
        {
            "shape": frame.shape,
            "source": source,
            "display_rotation_degrees": display_rotation,
        },
        size,
        target,
        rotation,
        512,
    )
    assert center == pytest.approx(
        ((expected_x + 0.5) / 2 - 0.5, (expected_y + 0.5) / 2 - 0.5)
    )
    assert side == 256


def shared_state(target=None, solved=True):
    camera = SimpleNamespace(RA=0.0, Dec=0.0, Roll=0.0)
    return SimpleNamespace(
        target_pixel=lambda: (256, 256),
        solve_image_rotation=lambda: 90,
        camera_type=lambda: "imx462",
        camera_lens=lambda: "16mm",
        camera_manual_focal_mm=lambda: None,
        ui_state=lambda: SimpleNamespace(target=lambda: target),
        solution=lambda: SimpleNamespace(
            has_pointing=lambda: solved,
            pointing=SimpleNamespace(camera=SimpleNamespace(estimate=camera)),
        ),
    )


def test_full_sensor_alignment_scales_from_native_980_crop():
    # Native star (200,800), minus centred crop offset (50,470), then resize
    # to 512 and rotate 90 degrees just as the LCD camera image does.
    crop_y, crop_x = (150.5 * 512 / 980 - 0.5, 330.5 * 512 / 980 - 0.5)
    target = (511 - crop_x, crop_y)
    center, side, _ = livecam_mark.mark_geometry(
        {"shape": (1080, 1920), "source": "original_raw"},
        (960, 540),
        target,
        90,
        980,
    )
    assert center == pytest.approx((399.75, 99.75))
    assert side == 490


def test_rendering_removes_arrow_when_target_is_cleared():
    state = shared_state(SimpleNamespace(ra=5, dec=0))
    state.raw_live_frame = lambda: {
        "frame": np.zeros((512, 512), dtype=np.uint16),
        "info": {"source": "solver_input", "shape": (512, 512), "mono": True},
    }
    processor = RawLiveStackProcessor()
    settings = {"processing_enabled": True, "web_image_format": "png"}

    def render(enabled):
        payload, _ = processor.render_image(state, settings, overlay_mark=enabled)
        return np.asarray(Image.open(io.BytesIO(payload)))

    off = render(False)
    targeted = render(True)
    state.ui_state = lambda: SimpleNamespace(target=lambda: None)
    reticle_only = render(True)
    assert np.any(reticle_only != off)
    assert np.any(targeted != reticle_only)
    np.testing.assert_array_equal(render(False), off)


def test_without_target_draws_reticle_but_never_an_arrow(monkeypatch):
    pointer = Mock()
    monkeypatch.setattr(livecam_mark, "draw_pointer", pointer)
    image = livecam_mark.draw_mark_overlay(
        Image.new("RGB", (512, 512)),
        {"source": "solver_input", "shape": (512, 512)},
        shared_state(),
    )
    assert image.getbbox() is not None
    assert image.getpixel((256, 256)) == (0, 0, 0)
    pointer.assert_not_called()


@pytest.mark.parametrize("source,offset", [("original_raw", 90), ("solver_input", 0)])
@pytest.mark.parametrize("display_rotation", [0, 90, 180, 270])
def test_arrow_tracks_selected_target_in_display_orientation(
    monkeypatch, source, offset, display_rotation
):
    pointer = Mock()
    monkeypatch.setattr(livecam_mark, "draw_pointer", pointer)
    livecam_mark.draw_mark_overlay(
        Image.new("RGB", (512, 512)),
        {
            "source": source,
            "shape": (512, 512),
            "display_rotation_degrees": display_rotation,
        },
        shared_state(SimpleNamespace(ra=5, dec=0)),
    )
    # At zero roll an eastward target points left on the production image.
    assert pointer.call_args.args[3] == pytest.approx(180 + offset - display_rotation)


def test_target_without_pointing_keeps_reticle_only(monkeypatch):
    pointer = Mock()
    monkeypatch.setattr(livecam_mark, "draw_pointer", pointer)
    image = livecam_mark.draw_mark_overlay(
        Image.new("RGB", (512, 512)),
        {"source": "solver_input", "shape": (512, 512)},
        shared_state(SimpleNamespace(ra=5, dec=0), solved=False),
    )
    assert image.getbbox() is not None
    pointer.assert_not_called()


@pytest.mark.parametrize(
    "sep,mark", [(False, False), (True, False), (False, True), (True, True)]
)
def test_image_endpoint_supports_independent_overlay_switches(monkeypatch, sep, mark):
    from flask import Flask
    from PiFinder import api_extensions

    monkeypatch.setattr(api_extensions.config, "Config", lambda: object())
    monkeypatch.setattr(
        api_extensions, "settings_from_config", lambda cfg: {"processing_enabled": True}
    )
    render = Mock(return_value=(b"image", "image/jpeg"))
    monkeypatch.setattr(RawLiveStackProcessor, "render_image", render)
    app = Flask(__name__)
    api_extensions.register_api_routes(
        app, SimpleNamespace(shared_state=shared_state())
    )
    query = [
        ("overlay", value)
        for value, enabled in [("sep", sep), ("mark", mark)]
        if enabled
    ]
    response = app.test_client().get("/api/camera/raw-stack/image", query_string=query)
    assert response.status_code == 200
    assert render.call_args.kwargs["overlay_sep"] is sep
    assert render.call_args.kwargs["overlay_mark"] is mark
