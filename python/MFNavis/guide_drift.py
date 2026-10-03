"""Bounded feed-forward drift learned from solved pointing and sent pulses."""

from collections import deque
import math


class GuideDrift:
    # Require two agreeing velocity measurements (three distinct solves).
    MAX_AGE = 12.0
    MIN_RATE = 0.2
    MAX_RATE = 5.0

    def __init__(self):
        self.reset()

    def reset(self):
        self.sample = None
        self.previous_rate = (0.0, 0.0)
        self.rate = (0.0, 0.0)
        self.pulse_remainder = [0.0, 0.0]
        self.interval = 0.0
        self.pulses = deque(maxlen=128)

    def record_pulse(self, axis, start, duration, correction):
        """Record accepted logical correction, before direction inversion."""
        self.pulses.append((axis, start, duration, correction))

    def observe(self, stamp, errors):
        if not all(math.isfinite(v) for v in (stamp, *errors)):
            self.reset()
            return
        if self.sample is not None:
            previous_stamp, previous_errors = self.sample
            if stamp <= previous_stamp:
                return
            elapsed = stamp - previous_stamp
            horizon = (
                min(self.MAX_AGE, 2 * self.interval) if self.interval else self.MAX_AGE
            )
            if elapsed > horizon:
                self.reset()
            elif elapsed >= 0.5:
                corrections = [0.0, 0.0]
                for axis, start, duration, correction in self.pulses:
                    overlap = max(
                        0.0, min(stamp, start + duration) - max(previous_stamp, start)
                    )
                    corrections[axis] += correction * overlap / duration
                measured = tuple(
                    (errors[i] - previous_errors[i] + corrections[i]) / elapsed
                    for i in range(2)
                )
                self.rate = tuple(
                    0.5 * (old + new)
                    if self.MIN_RATE <= abs(new) <= self.MAX_RATE
                    and old * new > 0
                    and abs(new - old) <= max(self.MIN_RATE, abs(old) * 0.5)
                    else 0.0
                    for old, new in zip(self.previous_rate, measured)
                )
                self.previous_rate = measured
                for axis, rate in enumerate(self.rate):
                    if rate == 0:
                        self.pulse_remainder[axis] = 0.0
                self.interval = elapsed
            else:
                return
        self.sample = (stamp, errors)
        while self.pulses and self.pulses[0][1] + self.pulses[0][2] <= stamp:
            self.pulses.popleft()

    def rates(self, now):
        if self.sample is None:
            return (0.0, 0.0)
        age = now - self.sample[0]
        horizon = (
            min(self.MAX_AGE, 2 * self.interval) if self.interval else self.MAX_AGE
        )
        if not 0 <= age <= horizon:
            self.reset()
            return (0.0, 0.0)
        return self.rate
