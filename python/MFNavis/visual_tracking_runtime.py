"""Opt-in, bounded live shadow experiment. Never writes operational pointing.

MFNAVIS_VISUAL_TRACKING_EXPERIMENT names a reviewed JSON environment manifest.
Only 'shadow' is implemented: no queue, driver or actuator is held by this
object. Missing/invalid manifests leave the legacy solver untouched.
"""

from dataclasses import asdict
import json
import logging
import math
import os
from pathlib import Path
import time
import uuid

import numpy as np

from PiFinder.visual_tracking import CameraGeometry, TrackingSession, plate_basis
from PiFinder.visual_tracking_images import measure_moon
from PiFinder.visual_tracking_target import TargetEphemeris

logger = logging.getLogger(__name__)
ENVIRONMENT = "MFNAVIS_VISUAL_TRACKING_EXPERIMENT"


def read_manifest(path, *, now=None):
    value = json.loads(Path(path).read_text())
    now = time.time() if now is None else now
    if not isinstance(value, dict):
        raise ValueError("manifest must be an object")
    if (
        value.get("schema") != 1
        or value.get("mode") != "shadow"
        or value.get("environment_confirmed") is not True
    ):
        raise ValueError("confirmed schema-1 shadow environment required")
    if value.get("mount_type") not in {"Alt/Az", "EQ"}:
        raise ValueError("explicit Alt/Az or EQ environment required")
    for key in ("camera_type", "lens", "calibration_id", "output_dir"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"missing environment field: {key}")
    if (
        type(value.get("expires_at")) not in (int, float)
        or not math.isfinite(value["expires_at"])
        or value["expires_at"] <= now
    ):
        raise ValueError("experiment environment expired")
    if (
        type(value.get("max_frames")) is not int
        or not 1 <= value["max_frames"] <= 10000
    ):
        raise ValueError("max_frames must be between 1 and 10000")
    if type(value.get("alignment_roll_deg")) not in (int, float) or not math.isfinite(
        value["alignment_roll_deg"]
    ):
        raise ValueError("calibrated alignment roll required")
    if value.get("roll_confirmed") is not True:
        raise ValueError("roll calibration must be confirmed")
    shape = value.get("raw_shape", [])
    if len(shape) != 2 or any(type(v) is not int or v < 2 for v in shape):
        raise ValueError("raw_shape must contain height and width")
    if not Path(value["output_dir"]).is_absolute():
        raise ValueError("output_dir must be absolute")
    radius = value.get("moon_radius_px")
    if radius is not None and (
        type(radius) not in (int, float) or not math.isfinite(radius) or radius < 5
    ):
        raise ValueError("moon_radius_px must be a finite radius of at least 5 pixels")
    return value


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False))
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def write_request(manifest_path, command, **payload):
    manifest = read_manifest(manifest_path)
    if command not in {"align", "stop", "manual_move"}:
        raise ValueError("unsupported experiment command")
    request = {
        **payload,
        "command": command,
        "id": uuid.uuid4().hex,
        "requested_at": time.time(),
    }
    atomic_json(Path(manifest["output_dir"]) / "request.json", request)
    return request


def mirror_alignment(ra, dec, *, frame="catalog"):
    """Copy a user intent without changing the old command/result semantics."""
    path = os.environ.get(ENVIRONMENT)
    if not path:
        return
    try:
        write_request(path, "align", ra=float(ra), dec=float(dec), frame=frame)
    except Exception:
        logger.exception("Visual tracking shadow alignment was not recorded")


def mirror_control(command_type):
    """Invalidate the experimental session on user lifecycle commands only."""
    path = os.environ.get(ENVIRONMENT)
    if not path:
        return
    if command_type not in {
        "goto_target",
        "stop_movement",
        "shutdown",
        "clear_tracking_target",
        "set_goto_method",
    }:
        return
    try:
        write_request(path, "stop")
    except Exception:
        logger.exception("Visual shadow cancellation was not recorded")


def create_shadow(shared_state):
    path = os.environ.get(ENVIRONMENT)
    if not path:
        return None
    try:
        return LiveShadow(read_manifest(path), shared_state)
    except Exception:
        logger.exception("Visual tracking experiment disabled: environment not ready")
        return None


class LiveShadow:
    def __init__(self, manifest, shared_state):
        self.manifest = manifest
        self.shared_state = shared_state
        self.ephemeris = TargetEphemeris(shared_state)
        self.output = Path(manifest["output_dir"])
        self.output.mkdir(parents=True, exist_ok=True)
        self.run_id = uuid.uuid4().hex
        self.log_path = self.output / f"shadow-{self.run_id}.jsonl"
        self.session = None
        self.target = None
        self.request_id = None
        self.started_at = time.time()
        self.frames = 0
        self.stopped = False
        self.aligned_at = None
        self.mount_key = None
        self.context = None

    def _publish(self, result):
        # Bounded by max_frames, with a new file per process/session run.
        result = {
            **result,
            "run_id": self.run_id,
            "mode": "shadow",
            "commands_sent": 0,
            "updated_at": time.time(),
        }
        with self.log_path.open("a") as stream:
            stream.write(json.dumps(result, allow_nan=False) + "\n")
        atomic_json(self.output / "status.json", result)

    def _moon(self, raw, info, geometry):
        from PiFinder import solver_frame_map as sfm
        from PiFinder.mf_wide_distortion import (
            distort_global_centroids,
            undistort_global_centroids,
        )

        radius = self.manifest.get("moon_radius_px")
        if self.target is None or self.target.body != "MOON" or radius is None:
            return None, None
        shape = tuple(np.shape(raw["frame"]))
        corrected, _ = sfm.rotate_centroids(
            [geometry.target_yx],
            (geometry.height, geometry.width),
            -info["rotation_deg"],
        )
        coefficients = info.get("distortion_coefficients")
        native = (
            distort_global_centroids(corrected, shape, coefficients)
            if coefficients
            else corrected
        )
        lunar = measure_moon(raw["frame"], native[0], float(radius))
        exclusion = native[0], float(radius) * 1.5
        if lunar is None:
            return None, exclusion
        measured = np.array([lunar["center_yx"]])
        if coefficients:
            measured = undistort_global_centroids(measured, shape, coefficients)
        measured, _ = sfm.rotate_centroids(measured, shape, info["rotation_deg"])
        return measured[0].tolist(), exclusion

    def observe(
        self,
        *,
        raw_entry,
        run,
        metadata,
        geometry,
        solution,
        moving,
        calibration_id,
        cfg,
    ):
        if self.stopped:
            return
        self.frames += 1
        if (
            self.frames > self.manifest["max_frames"]
            or time.time() >= self.manifest["expires_at"]
        ):
            self.stopped = True
            self._publish({"state": "stopped", "reason": "experiment_limit"})
            return
        try:
            self._observe(
                raw_entry,
                run,
                metadata,
                geometry,
                solution,
                moving,
                calibration_id,
                cfg,
            )
        except Exception as exc:
            # An experiment failure must not abort a production solve or reuse
            # its last good residual as a new observation.
            if self.session is not None:
                self.session.suspend("geometry_changed")
            self._publish({"state": "unavailable", "reason": str(exc)})

    def _observe(self, raw, run, metadata, info, solution, moving, calibration_id, cfg):
        from PiFinder import solver_frame_map as sfm, utils
        from PiFinder.mf_wide_distortion import undistort_global_centroids

        expected = self.manifest
        if (
            self.shared_state.camera_type() != expected["camera_type"]
            or self.shared_state.camera_lens() != expected["lens"]
            or cfg.get_option("mount_type") != expected["mount_type"]
            or str(calibration_id or "none") != expected["calibration_id"]
        ):
            raise ValueError(
                "camera/lens/mount/calibration differs from confirmed environment"
            )
        if raw is None or run is None or info is None:
            raise ValueError("paired RAW and MFDS detection unavailable")
        frame_id, stamp = metadata.get("frame_id"), float(metadata["exposure_end"])
        if (
            frame_id is None
            or raw.get("frame_id") != frame_id
            or run.frame_id != frame_id
            or not 0 <= time.time() - stamp <= 10
            or tuple(run.frame_hw) != tuple(expected["raw_shape"])
            or np.shape(raw.get("frame")) != tuple(run.frame_hw)
        ):
            raise ValueError("stale/mismatched frame or geometry")
        mount_path = utils.runtime_dir / "mount_control_status.json"
        mount = json.loads(mount_path.read_text())
        # Require a live timestamp; a remembered mount state cannot validate a test.
        mount_stamp = mount.get("updated", 0)
        if not 0 <= time.time() - float(mount_stamp) <= 5:
            raise ValueError("fresh mount telemetry required")
        if (
            mount.get("tracking_enabled") is False
            or mount.get("park_state") == "parked"
        ):
            if self.session:
                self.session.cancel()
            self._publish({"state": "idle", "reason": "mount_tracking_off_or_parked"})
            return
        mount_key = mount.get("pier_side"), mount.get("rotator_angle")
        if self.mount_key is not None and mount_key != self.mount_key and self.session:
            self.session.suspend("mount_changed")
        self.mount_key = mount_key
        points = np.asarray(run.detection.centroids, dtype=float).copy()
        coefficients = info.get("distortion_coefficients")
        if coefficients:
            points = undistort_global_centroids(points, run.frame_hw, coefficients)
        points, canvas = sfm.rotate_centroids(
            points, run.frame_hw, info["rotation_deg"]
        )
        target_pixel = sfm.map_target_pixel_to_frame(
            self.shared_state.target_pixel(), canvas, info["crop_width_px"]
        )
        geometry = CameraGeometry(
            *canvas,
            sfm.fov_estimate_deg(
                canvas[1], info["crop_width_px"], info["base_fov_degrees"]
            ),
            target_pixel,
            expected["calibration_id"],
        )
        context = (
            geometry,
            info["rotation_deg"],
            json.dumps(coefficients, sort_keys=True),
        )
        if self.context is not None and context != self.context:
            if self.session:
                self.session.suspend("geometry_changed")
            self.target = None
        self.context = context
        dt = self.shared_state.datetime()
        if dt is None or dt.tzinfo is None:
            raise ValueError("astronomical UTC clock unavailable")
        astronomical_stamp = dt.timestamp() - (time.time() - stamp)
        request_path = self.output / "request.json"
        request = json.loads(request_path.read_text()) if request_path.exists() else {}
        is_new = request.get("id") and request["id"] != self.request_id
        if is_new:
            requested = float(request["requested_at"])
            if requested < self.started_at or time.time() - requested > 30:
                self.request_id = request["id"]
                raise ValueError("old experiment request rejected")
            if request["command"] in {"stop", "manual_move"}:
                self.request_id = request["id"]
                if self.session:
                    self.session.cancel() if request[
                        "command"
                    ] == "stop" else self.session.suspend()
                    self._publish(
                        {
                            **self.session.status(request["command"]),
                            "input": {"event": request["command"]},
                        }
                    )
                return
            elif request["command"] == "align":
                if moving or stamp < requested:
                    self._publish(
                        {
                            "state": "alignment_pending",
                            "reason": "waiting_stationary_frame",
                        }
                    )
                    return
                self.request_id = request["id"]
                self.target = self.ephemeris.resolve(
                    request["ra"],
                    request["dec"],
                    frame=request.get("frame", "catalog"),
                    body=request.get("body"),
                    identify_planets=bool(expected.get("identify_planets", False)),
                )
                self.aligned_at = astronomical_stamp
                pose = self.ephemeris.basis(
                    self.target,
                    astronomical_stamp,
                    geometry,
                    mount_type=expected["mount_type"],
                    alignment_timestamp=self.aligned_at,
                    alignment_roll_deg=expected["alignment_roll_deg"],
                )
                previous_generation = self.session.generation if self.session else 0
                self.session = TrackingSession(geometry, generation=previous_generation)
                _, exclusion = self._moon(raw, info, geometry)
                if exclusion is not None:
                    raw_points = np.asarray(run.detection.centroids).reshape(-1, 2)
                    points = points[
                        np.linalg.norm(raw_points - exclusion[0], axis=1) > exclusion[1]
                    ]
                self.session.align(self.target.identity, stamp, pose, points)
                self._publish(
                    {
                        **self.session.status("user_alignment"),
                        "geometry": asdict(geometry),
                        "target": asdict(self.target),
                        "input": {
                            "event": "align",
                            "geometry": asdict(geometry),
                            "target_id": self.target.identity,
                            "timestamp": stamp,
                            "expected_basis": pose.tolist(),
                            "centroids": points.tolist(),
                        },
                    }
                )
                return
        if self.session is None or self.target is None:
            self._publish({"state": "idle", "reason": "waiting_experiment_alignment"})
            return
        if moving:
            self.session.suspend()
            self._publish(
                {
                    **self.session.status("motion_invalidates_reference"),
                    "input": {"event": "manual_move"},
                }
            )
            return
        pose = self.ephemeris.basis(
            self.target,
            astronomical_stamp,
            geometry,
            mount_type=expected["mount_type"],
            alignment_timestamp=self.aligned_at,
            alignment_roll_deg=expected["alignment_roll_deg"],
        )
        solved = None
        frame = (solution or {}).get("_alignment_frame")
        if (
            solution
            and solution.get("RA") is not None
            and frame
            and tuple(frame[:2]) == canvas
            and abs(float(solution["FOV"]) / geometry.fov_deg - 1) < 0.03
        ):
            solved = plate_basis(solution["RA"], solution["Dec"], solution["Roll"])
        moon_yx, exclusion = self._moon(raw, info, geometry)
        if exclusion is not None:
            raw_points = np.asarray(run.detection.centroids).reshape(-1, 2)
            points = points[
                np.linalg.norm(raw_points - exclusion[0], axis=1) > exclusion[1]
            ]
        observation = dict(
            generation=self.session.generation,
            frame_id=frame_id,
            timestamp=stamp,
            expected_basis=pose.tolist(),
            centroids=points.tolist(),
            solved_basis=solved.tolist() if solved is not None else None,
            moon_yx=moon_yx,
        )
        result = self.session.observe(**observation)
        self._publish(
            {
                **result,
                "accepted_solve_used": solved is not None,
                "input": {"event": "frame", **observation},
            }
        )
