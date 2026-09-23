"""Boot artwork keeps its RGB colours through the display submission path."""

from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image, ImageChops, ImageFont
import pytest

from PiFinder import splash
from PiFinder.branding import welcome_image
from PiFinder.displays import Colors, RED_RGB, RED_BGR
from PiFinder.image_util import convert_image_to_mode

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "mode,expected", [("RGB", (240, 80, 10)), ("BGR", (10, 80, 240))]
)
def test_image_colour_order(mode, expected):
    source = Image.new("RGB", (2, 2), (240, 80, 10))
    assert convert_image_to_mode(source, mode).getpixel((0, 0)) == expected
    assert source.getpixel((0, 0)) == (240, 80, 10)


@pytest.mark.parametrize("resolution", [(128, 128), (176, 176), (320, 240)])
@pytest.mark.parametrize("mask", [RED_RGB, RED_BGR])
def test_boot_logo_and_banner_follow_display_colour_order(
    monkeypatch, resolution, mask
):
    width, height = resolution
    display = SimpleNamespace(
        resX=width,
        resY=height,
        colors=Colors(mask, resolution),
        device=SimpleNamespace(mode="RGB", display=Mock()),
        fonts=SimpleNamespace(base=SimpleNamespace(font=ImageFont.load_default())),
        set_brightness=Mock(),
    )
    monkeypatch.setattr(
        splash.hardware_detect, "default_display_hardware", lambda: "test"
    )
    monkeypatch.setattr(splash.displays, "get_display", lambda hardware: display)
    monkeypatch.setattr(splash.utils, "read_wifi_mode", lambda: "ap")
    splash.show_splash()
    actual = display.device.display.call_args.args[0]
    banner_height = round(height * 16 / 128)
    expected = welcome_image(resolution, top_margin=banner_height + 1)
    if mask.mode == "BGR":
        red, green, blue = expected.split()
        expected = Image.merge("RGB", (blue, green, red))
    logo_box = (0, banner_height + 1, width, height)
    assert (
        ImageChops.difference(actual.crop(logo_box), expected.crop(logo_box)).getbbox()
        is None
    )
    banner = actual.crop((0, 0, width, banner_height + 1))
    red, _, blue = banner.split()
    bright, dark = (red, blue) if mask.mode == "RGB" else (blue, red)
    assert bright.getbbox() is not None
    assert dark.getbbox() is None
