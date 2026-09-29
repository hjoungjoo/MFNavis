"""Chart-style reticle and camera-plane target direction."""

import math
from functools import lru_cache

from PIL import Image, ImageChops, ImageFilter

from PiFinder import utils
from PiFinder.solver_frame_map import map_target_pixel_to_frame


@lru_cache(maxsize=1)
def _pointer_image():
    with Image.open(utils.pifinder_dir / "markers" / "pointer.png") as image:
        return image.convert("RGB").crop((64, 64, 192, 192))


def draw_pointer(image, center, side, angle, color, *, outline=None):
    """Paint the chart/Push pointer on an image, leaving its background visible."""
    side = max(1, round(side))
    pointer = _pointer_image().resize((side, side)).rotate(-(angle + 180))
    origin = (round(center[0] - side / 2), round(center[1] - side / 2))
    if outline is not None:
        # Paint over the camera image rather than adding light to it: an
        # additive pointer disappears on saturated backgrounds.
        mask = Image.new("L", image.size)
        mask.paste(pointer.convert("L"), origin)
        image.paste(outline, (0, 0), mask.filter(ImageFilter.MaxFilter(3)))
        image.paste(color, (0, 0), mask)
        return
    pointer = ImageChops.multiply(pointer, Image.new("RGB", pointer.size, color))
    layer = Image.new("RGB", image.size)
    layer.paste(pointer, origin)
    image.paste(ImageChops.add(image, layer))


def draw_reticle(draw, center, pixels_per_degree, color, *, outline=None):
    """The chart's 4, 2 and 0.5 degree segmented circles."""
    cx, cy = center
    for diameter in (4, 2, 0.5):
        radius = diameter * pixels_per_degree / 2
        bounds = (cx - radius, cy - radius, cx + radius, cy + radius)
        for start in (20, 110, 200, 290):
            if outline is not None:
                draw.arc(
                    (bounds[0] - 1, bounds[1] - 1, bounds[2] + 1, bounds[3] + 1),
                    start,
                    start + 50,
                    fill=outline,
                    width=3,
                )
            draw.arc(bounds, start, start + 50, fill=color)


def _projection_geometry(projection):
    if not projection:
        return None
    try:
        h, w, crop = map(float, projection["frame"])
        fov = float(projection["FOV"])
        if (
            all(math.isfinite(v) for v in (h, w, crop, fov))
            and min(h, w, crop) > 0
            and 0 < fov < 180
        ):
            return h, w, crop, fov
    except (KeyError, TypeError, ValueError):
        pass
    return None


def camera_fov(solution, fallback_fov):
    """Use the accepted plate's measured scale for the cropped camera image."""
    geometry = _projection_geometry(getattr(solution, "alignment_projection", None))
    if geometry is None:
        return fallback_fov
    _, w, crop, fov = geometry
    return math.degrees(2 * math.atan(crop / w * math.tan(math.radians(fov) / 2)))


def target_direction(camera, ra, dec, target_pixel, fov, *, projection=None):
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
    geometry = _projection_geometry(projection)
    if geometry is None:
        h = w = crop = 512.0
        y, x = target_pixel
    else:
        h, w, crop, fov = geometry
        y, x = map_target_pixel_to_frame(target_pixel, (h, w), crop)
    focal = w / (2 * math.tan(math.radians(fov) / 2))
    # Match alignment projection exactly, including full-frame crop mapping
    # and its pixel-centre convention. Compare the deadband in 512-space.
    dx = ((w / 2 - x) * max(0, forward) - focal * horizontal) * 512 / crop
    dy = ((h / 2 - y) * max(0, forward) - focal * vertical) * 512 / crop
    if not all(math.isfinite(v) for v in (dx, dy)) or math.hypot(dx, dy) < 0.5:
        return None
    return math.degrees(math.atan2(dy, dx))
