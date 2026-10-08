"""Bounded per-axis optical PID, driven only by distinct camera observations."""

import math
from dataclasses import dataclass


@dataclass
class GuidePID:
    # P=1 requests the full measured error. D damps approach; I removes bias.
    kp: float = 1.0
    ki: float = 0.05
    kd: float = 0.25
    integral: float = 0.0
    previous_error: float = 0.0
    previous_stamp: float = 0.0

    def reset(self) -> None:
        self.integral = 0.0
        self.previous_error = 0.0
        self.previous_stamp = 0.0

    def correction(self, error: float, stamp: float, limit: float) -> float:
        """Return signed arcseconds, with anti-windup and no derivative reversal."""
        if not all(math.isfinite(v) for v in (error, stamp, limit)) or limit <= 0:
            self.reset()
            return 0.0
        dt = stamp - self.previous_stamp
        if self.previous_stamp and dt <= 0:
            return 0.0
        derivative = 0.0
        if not self.previous_stamp or dt > 12 or error * self.previous_error <= 0:
            self.integral = 0.0
        else:
            derivative = (error - self.previous_error) / max(dt, 0.1)
        # Never accumulate bias while the actuator is saturated.
        candidate = self.integral
        if self.previous_stamp and 0 < dt <= 12 and abs(error) < limit:
            candidate += error * dt
        bound = min(limit * 0.25, abs(error) * 0.25)
        candidate = max(-bound / self.ki, min(bound / self.ki, candidate))
        proportional = self.kp * error
        damping = max(
            -abs(proportional) * 0.8, min(abs(proportional) * 0.8, self.kd * derivative)
        )
        output = proportional + self.ki * candidate + damping
        if abs(output) <= limit or output * error < 0:
            self.integral = candidate
        output = proportional + self.ki * self.integral + damping
        self.previous_error, self.previous_stamp = error, stamp
        # A crossing is handled by the new measured sign, never by stored I/D.
        return math.copysign(
            min(limit, max(0.0, output * math.copysign(1, error))), error
        )
