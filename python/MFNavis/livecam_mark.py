"""LCD Push marks mapped onto the selected LiveCam image geometry."""

import logging
import math

import numpy as np
from PIL import ImageDraw

from PiFinder import solver_frame_map as sfm
from PiFinder.livecam_config import (
    SOURCE_ORIGINAL,
    SOURCE_STAR_ONLY,
    SOURCE_SOLVER_INPUT,
)
from PiFinder.mf_manual_lens import manual_focal_from_state
from PiFinder.optics import OpticalTrainResolver
from PiFinder.ui.camera_guidance import draw_pointer, draw_reticle, target_direction

logger = logging.getLogger("LiveCam.Mark")
_OPTICS = OpticalTrainResolver()


def mark_geometry(info, image_size, target_pixel, solve_rotation, crop_width):
    """Return display centre (x,y), crop side and clockwise bearing offset.

    Alignment is stored in rotated 512-space. Original/star-only frames use
    the full sensor canvas; intermediate stages use the unrotated crop;
    solver_input has already received the solve rotation. None of these
    images is lens-rectified, so the saved pixel needs no distortion transform.
    """
    shape = tuple(info["shape"])
    display_rotation = float(info.get("display_rotation_degrees") or 0)
    _, base_shape = sfm.rotate_centroids(np.empty((0, 2)), shape, -display_rotation)
    source = info["source"]
    if source in (SOURCE_ORIGINAL, SOURCE_STAR_ONLY):
        _, canvas = sfm.rotate_centroids(np.empty((0, 2)), base_shape, solve_rotation)
        point = sfm.map_target_pixel_to_frame(target_pixel, canvas, crop_width)
        points, _ = sfm.rotate_centroids(np.array([point]), canvas, -solve_rotation)
        side = crop_width
    else:
        points = np.asarray([target_pixel], dtype=float)
        if source != SOURCE_SOLVER_INPUT:
            points, _ = sfm.rotate_centroids(points, (512, 512), -solve_rotation)
        points = (points + 0.5) * np.asarray(base_shape) / 512 - 0.5
        side = min(base_shape)
    points, _ = sfm.rotate_centroids(points, base_shape, display_rotation)
    scale_yx = np.asarray((image_size[1], image_size[0])) / np.asarray(shape)
    y, x = (points[0] + 0.5) * scale_yx - 0.5
    offset = -display_rotation
    if source != SOURCE_SOLVER_INPUT:
        offset += solve_rotation
    return (float(x), float(y)), float(side * min(scale_yx)), offset


def draw_mark_overlay(image, info, shared_state, web_theme="grey"):
    """Draw the alignment reticle; a selected target adds the Push arrow."""
    try:
        target_pixel = shared_state.target_pixel()
        rotation = shared_state.solve_image_rotation()
        if (
            target_pixel is None
            or len(target_pixel) != 2
            or not all(math.isfinite(v) and 0 <= v < 512 for v in target_pixel)
            or rotation is None
        ):
            return image
        optics = _OPTICS.resolve(
            info.get("camera_type") or shared_state.camera_type(),
            shared_state.camera_lens(),
            manual_focal_from_state(shared_state),
        )
        center, side, offset = mark_geometry(
            info, image.size, target_pixel, rotation, optics.profile.crop_size[0]
        )
        image = image.convert("RGB")
        color = (232, 75, 63) if web_theme == "red" else (80, 200, 255)
        draw_reticle(ImageDraw.Draw(image), center, side / optics.fov_degrees, color)

        ui_state = shared_state.ui_state()
        target = ui_state.target() if ui_state is not None else None
        if target is None or target.ra is None or target.dec is None:
            return image
        solution = shared_state.solution()
        if solution is None or not solution.has_pointing():
            return image
        camera = solution.pointing.camera.estimate
        if camera is None:
            return image
        angle = target_direction(
            camera, target.ra, target.dec, target_pixel, optics.fov_degrees
        )
        if angle is not None:
            draw_pointer(image, center, side * 0.5, angle + offset, color)
        return image
    except (AttributeError, TypeError, ValueError, KeyError):
        logger.debug("Mark unavailable for current camera state", exc_info=True)
        return image
