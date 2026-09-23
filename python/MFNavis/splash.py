#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the main entry point for PiFinder it:
* Initializes the display
* Spawns keyboard process
* Sets up time/location via GPS
* Spawns camers/solver process
* then runs the UI loop

"""

import os
from PIL import ImageDraw
from PiFinder import displays
from PiFinder import hardware_detect
from PiFinder import utils
from PiFinder.branding import welcome_image as product_welcome_image
from PiFinder.image_util import convert_image_to_mode


def do_nothing():
    pass


def show_splash():
    display = displays.get_display(hardware_detect.default_display_hardware())
    display.device.cleanup = do_nothing
    display.set_brightness(125)

    # load welcome image to screen
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    banner_height = round(display.resY * 16 / 128)
    welcome_image = product_welcome_image(
        (display.resX, display.resY), top_margin=banner_height + 1
    )
    welcome_image = convert_image_to_mode(welcome_image, display.colors.mode)
    screen_draw = ImageDraw.Draw(welcome_image)

    # Display version and Wifi mode
    with open(os.path.join(root_dir, "version.txt"), "r") as ver_f:
        version = "v" + ver_f.read()

    wifi_mode = utils.read_wifi_mode()
    screen_draw.rectangle([0, 0, display.resX, banner_height], fill=(0, 0, 0))
    screen_draw.text(
        (0, 1),
        f"Wifi:{wifi_mode: <6}  {version: >8}",
        font=display.fonts.base.font,
        fill=display.colors.get(255),
    )

    display.device.display(welcome_image.convert(display.device.mode))


if __name__ == "__main__":
    show_splash()
