"""Bounded disturbance history; no device access or target mutation."""

from collections import deque
import numpy as np


class MotionHistory:
    def __init__(self):
        self.samples = deque(maxlen=12)
        self.pending_step = None
        self.step_confirmations = 0

    def reset(self):
        self.samples.clear()
        self.pending_step = None
        self.step_confirmations = 0

    def observe(self, stamp, error, applied, bound, max_drift):
        error = np.asarray(error, dtype=float)
        corrected = error + np.asarray(applied, dtype=float)
        if self.samples and stamp <= self.samples[-1][0]:
            return "unknown", None
        if self.samples:
            dt = stamp - self.samples[-1][0]
            change = np.linalg.norm(corrected - self.samples[-1][1])
            if change > max(4 * bound, max_drift * dt * 3):
                if (
                    self.pending_step is None
                    or np.linalg.norm(error - self.pending_step) > 2 * bound
                ):
                    self.pending_step = error.copy()
                    self.step_confirmations = 0
                    return "step_pending", None
        if self.pending_step is not None:
            if np.linalg.norm(error - self.pending_step) <= 2 * bound:
                self.step_confirmations += 1
                if self.step_confirmations < 2:
                    return "step_pending", None
                self.reset()
            else:
                self.reset()
                return "step_pending", None
        self.samples.append((stamp, corrected.copy(), bound))
        if len(self.samples) < 4:
            return "observed", None
        times = np.array([s[0] for s in self.samples])
        values = np.array([s[1] for s in self.samples])
        durations = np.diff(times)
        if times[-1] - times[0] < 1:
            return "observed", None
        deltas = np.diff(values, axis=0)
        meaningful = np.linalg.norm(deltas, axis=1) > 2 * bound
        turns = [
            np.dot(deltas[i], deltas[i - 1]) < 0
            for i in range(1, len(deltas))
            if meaningful[i] and meaningful[i - 1]
        ]
        if sum(turns[-4:]) >= 2:
            return "oscillatory", None
        velocities = deltas / durations[:, None]
        drift = np.median(velocities, axis=0)
        scatter = np.median(np.linalg.norm(velocities - drift, axis=1))
        uncertainty = 2 * bound / (times[-1] - times[0]) + scatter
        if np.linalg.norm(drift) <= uncertainty or scatter > max(
            0.5, np.linalg.norm(drift) * 0.4
        ):
            return "observed", None
        if np.linalg.norm(drift) > max_drift:
            return "unknown", None
        return "persistent_drift", drift
