"""Project an alignment target using a recent, accepted plate solution."""

import math

import numpy as np
import quaternion

from PiFinder import solver_frame_map as sfm
from PiFinder.mf_manual_lens import manual_focal_from_state
from PiFinder.mf_wide_calibration import CalibrationProfileStore
from PiFinder.sqm import get_camera_profile

MAX_AGE_SECONDS = 5.0
MAX_MOTION_DEGREES = 0.05


def projection_context(shared_state, cfg) -> tuple:
    camera = shared_state.camera_type()
    lens = getattr(shared_state, "camera_lens", lambda: "")() or ""
    profile = CalibrationProfileStore(cfg).load_active(
        camera, lens, get_camera_profile(camera)
    )
    return (
        camera,
        lens,
        manual_focal_from_state(shared_state),
        sfm.stage5_rotation_deg(
            cfg.get_option("screen_direction"), cfg.get_option("camera_rotation")
        ),
        str(profile.get("id") or "") if profile else "",
    )


def make_projection(solution, captured_at, context):
    """Only the accepted solution's own solver canvas is a valid plate scale."""
    frame = solution.get("_alignment_frame")
    if frame is None or context is None:
        return None
    return {
        "captured_at": captured_at,
        "context": context,
        "frame": frame,
        "RA": solution["RA"],
        "Dec": solution["Dec"],
        "Roll": solution["Roll"],
        "FOV": solution.get("FOV"),
    }


def _plate_rotation(plate):
    ra, dec, roll = np.radians([plate["RA"], plate["Dec"], plate["Roll"]])
    east = np.array([-np.sin(ra), np.cos(ra), 0.0])
    north = np.array(
        [-np.sin(dec) * np.cos(ra), -np.sin(dec) * np.sin(ra), np.cos(dec)]
    )
    forward = np.array(
        [np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)]
    )
    return np.array(
        [
            forward,
            np.cos(roll) * east + np.sin(roll) * north,
            -np.sin(roll) * east + np.cos(roll) * north,
        ]
    )


def target_pixel_pointing(plate, target_pixel):
    """Re-evaluate the eyepiece axis on the accepted camera plate."""
    h, w, crop = plate["frame"]
    y, x = sfm.map_target_pixel_to_frame(target_pixel, (h, w), crop)
    focal = w / (2 * math.tan(math.radians(plate["FOV"]) / 2))
    vector = np.array([1.0, (w / 2 - x) / focal, (h / 2 - y) / focal])
    sky = vector @ _plate_rotation(plate)
    sky /= np.linalg.norm(sky)
    return math.degrees(math.atan2(sky[1], sky[0])) % 360, math.degrees(
        math.asin(sky[2])
    )


def project_target(plate, ra_deg, dec_deg):
    """Same pinhole projection and 512 mapping as tetra3 target_sky_coord.

    The detector already applied global lens correction before solving.
    tetra3 returns target_sky_coord in that undistorted solver canvas.
    """
    values = [plate[k] for k in ("RA", "Dec", "Roll", "FOV")]
    values.extend([ra_deg, dec_deg, *plate["frame"]])
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError("non-finite alignment geometry")
    if not -90 <= dec_deg <= 90 or not 0 < plate["FOV"] < 180:
        raise ValueError("invalid sky coordinate or FOV")
    h, w, crop = plate["frame"]
    if min(h, w, crop) <= 0:
        raise ValueError("invalid solver canvas")
    rotation = _plate_rotation(plate)
    target_ra, target_dec = np.radians([ra_deg, dec_deg])
    target = np.array(
        [
            np.cos(target_ra) * np.cos(target_dec),
            np.sin(target_ra) * np.cos(target_dec),
            np.sin(target_dec),
        ]
    )
    vec = rotation @ target
    if vec[0] <= 0:
        raise ValueError("alignment target behind camera")
    focal = w / (2 * math.tan(math.radians(plate["FOV"]) / 2))
    y, x = h / 2 - focal * vec[2] / vec[0], w / 2 - focal * vec[1] / vec[0]
    if not (0 < y < h and 0 < x < w):
        raise ValueError("alignment target outside solved frame")
    return sfm.map_frame_pixel_to_target((y, x), (h, w), crop)


def cached_target_pixel(estimate, imu, ra_deg, dec_deg, *, now, context):
    plate = getattr(estimate, "alignment_projection", None)
    if not plate:
        raise ValueError("no accepted alignment projection")
    age = now - float(plate["captured_at"])
    if not 0 <= age <= MAX_AGE_SECONDS:
        raise ValueError("last solve is too old")
    if plate["captured_at"] != estimate.last_solve_success:
        raise ValueError("projection does not match last solve")
    if tuple(plate["context"]) != tuple(context):
        raise ValueError("optics changed since last solve")
    if imu is None or not imu.is_usable(now=now) or imu.moving:
        raise ValueError("camera moving or IMU unavailable")
    anchor = estimate.imu_anchor
    if anchor is None:
        raise ValueError("solve has no IMU anchor")
    q0 = quaternion.as_float_array(anchor)
    q1 = quaternion.as_float_array(imu.quat)
    if (
        not np.all(np.isfinite([q0, q1]))
        or min(np.linalg.norm(q0), np.linalg.norm(q1)) < 0.5
    ):
        raise ValueError("invalid IMU orientation")
    dot = abs(float(np.dot(q0, q1) / (np.linalg.norm(q0) * np.linalg.norm(q1))))
    motion = math.degrees(2 * math.acos(min(1.0, dot)))
    if motion > MAX_MOTION_DEGREES:
        raise ValueError("camera moved since last solve")
    return project_target(plate, ra_deg, dec_deg)
