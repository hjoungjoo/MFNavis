"""Chart-style reticle and camera-plane target direction."""

import math
from functools import lru_cache

from PIL import Image, ImageChops

from PiFinder import utils


@lru_cache(maxsize=1)
def _pointer_image():
    with Image.open(utils.pifinder_dir / "markers" / "pointer.png") as image:
        return image.convert("RGB").crop((64, 64, 192, 192))


def draw_pointer(image, center, side, angle, color):
    """Paint the chart/Push pointer on an image, leaving its background visible."""
    side = max(1, round(side))
    pointer = _pointer_image().resize((side, side)).rotate(-(angle + 180))
    pointer = ImageChops.multiply(pointer, Image.new("RGB", pointer.size, color))
    layer = Image.new("RGB", image.size)
    layer.paste(pointer, (round(center[0] - side / 2), round(center[1] - side / 2)))
    image.paste(ImageChops.add(image, layer))


def draw_reticle(draw, center, pixels_per_degree, color):
    """The chart's 4, 2 and 0.5 degree segmented circles."""
    cx, cy = center
    for diameter in (4, 2, 0.5):
        radius = diameter * pixels_per_degree / 2
        bounds = (cx - radius, cy - radius, cx + radius, cy + radius)
        for start in (20, 110, 200, 290):
            draw.arc(bounds, start, start + 50, fill=color)


def target_direction(camera, ra, dec, target_pixel, fov):
    """Screen-space bearing from the saved alignment point to a sky target.

    Uses the rotated camera basis, not mount Alt/Az arrows. Homogeneous
    coordinates keep far-offscreen targets finite; rear targets retain their
    tangent direction instead of reversing the pointer.
    """
    ra0, dec0, roll, ra, dec = map(
        math.radians, (camera.RA, camera.Dec, camera.Roll, ra, dec)
    )
    delta = ra - ra0
    forward = math.sin(dec0) * math.sin(dec) + math.cos(dec0) * math.cos(
        dec
    ) * math.cos(delta)
    east = math.cos(dec) * math.sin(delta)
    north = math.cos(dec0) * math.sin(dec) - math.sin(dec0) * math.cos(dec) * math.cos(
        delta
    )
    horizontal = math.cos(roll) * east + math.sin(roll) * north
    vertical = -math.sin(roll) * east + math.cos(roll) * north
    focal = 256 / math.tan(math.radians(fov) / 2)
    y, x = target_pixel
    dx = (256 - x) * max(0, forward) - focal * horizontal
    dy = (256 - y) * max(0, forward) - focal * vertical
    if not all(math.isfinite(v) for v in (dx, dy)) or math.hypot(dx, dy) < 0.5:
        return None
    return math.degrees(math.atan2(dy, dx))
