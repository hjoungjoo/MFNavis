"""Plate-anchored IMU prediction for displays, independent of mount control."""

import math
import time
from dataclasses import replace

import quaternion

from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
from PiFinder.types.positioning import (
    ImuSample,
    Pointing,
    PointingEstimate,
    SolveSource,
)


class DisplayPointing:
    """Follow commanded motion even below the IMU wake/movement threshold.

    Never publish into shared_state.solution(): guiding, solve acceptance and
    motor control retain their existing inputs. Hold the last display prediction
    after motion ends until a newer integrator estimate or plate solve arrives.
    """

    def __init__(self):
        self._key = None
        self._prediction = None
        self._timestamp = 0.0

    def reset(self):
        self._key = None
        self._prediction = None
        self._timestamp = 0.0

    def solution(self, solution, imu, screen_direction, mount_status):
        if not isinstance(solution, PointingEstimate):
            self.reset()
            return solution
        camera = solution.pointing.camera.solve
        aligned = solution.pointing.aligned.solve
        anchor = solution.imu_anchor
        if (
            camera is None
            or aligned is None
            or anchor is None
            or solution.last_solve_success is None
            or not ImuSample(anchor, time.time(), status=3).orientation_valid()
        ):
            self.reset()
            return solution

        key = (
            solution.last_solve_success,
            camera.RA,
            camera.Dec,
            camera.Roll,
            aligned.RA,
            aligned.Dec,
            aligned.Roll,
            tuple(quaternion.as_float_array(anchor)),
            screen_direction,
        )
        if key != self._key:
            self.reset()
            self._key = key
        estimate_time = solution.estimate_time or 0.0
        if estimate_time >= self._timestamp:
            self._prediction = None

        status = mount_status if isinstance(mount_status, dict) else {}
        try:
            updated = float(status.get("updated", 0))
            active = math.isfinite(updated) and 0 <= time.time() - updated < 5
        except (TypeError, ValueError):
            active = False
        active = active and bool(
            status.get("mount_motion_active")
            or status.get("goto_motion_active")
            or status.get("manual_motion_direction")
        )
        if (
            active
            and imu is not None
            and imu.is_usable()
            and imu.timestamp > max(estimate_time, self._timestamp)
        ):
            idr = ImuDeadReckoning(screen_direction)
            idr.solve(camera.as_radecroll(), aligned.as_radecroll(), anchor)
            prediction = idr.predict(imu.quat)
            if prediction is not None:
                self._prediction = tuple(Pointing.from_radecroll(p) for p in prediction)
                self._timestamp = imu.timestamp

        if self._prediction is None:
            return solution
        camera_now, aligned_now = self._prediction
        return replace(
            solution,
            pointing=replace(
                solution.pointing,
                camera=replace(solution.pointing.camera, estimate=camera_now),
                aligned=replace(solution.pointing.aligned, estimate=aligned_now),
            ),
            estimate_time=self._timestamp,
            solve_source=SolveSource.IMU,
            Alt=None,
            Az=None,
        )
