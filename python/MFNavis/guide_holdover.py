"""Account for measured residuals and learned drift across camera outages.

Times are monotonic. A pulse is charged only for elapsed travel; replacing an
axis timer truncates its previous command. Only independent optical observations
train drift. Predictions never become observations and never wind up the PID.
"""

import math


class GuideHoldover:
    def __init__(self):
        self.reset()

    def reset(self):
        self.sample = None
        self.rate_sample = None
        self.rate = (0.0, 0.0)  # NS, WE signed error growth, arcsec/s
        self.previous_rate = None
        self.pulses = []
        self.prefix = [0.0, 0.0]
        self.history_after = -math.inf

    def _travel(self, stamp):
        result = list(self.prefix)
        for axis, start, end, rate in self.pulses:
            result[axis] += max(0.0, min(stamp, end) - start) * rate
        return result

    def record_pulse(self, axis, start, duration, rate):
        if not all(math.isfinite(v) for v in (start, duration, rate)) or duration <= 0:
            return
        for pulse in self.pulses:
            if pulse[0] == axis and pulse[2] > start:
                pulse[2] = max(pulse[1], start)
        self.pulses.append([axis, start, start + duration, rate])
        self._prune(start - 30.0)

    def _prune(self, before):
        retained = []
        for axis, start, end, rate in self.pulses:
            if end < before:
                self.prefix[axis] += (end - start) * rate
                self.history_after = max(self.history_after, end)
            else:
                retained.append([axis, start, end, rate])
        self.pulses = retained

    def observe(self, stamp, errors):
        if not all(math.isfinite(v) for v in (stamp, *errors)):
            return False
        if stamp < self.history_after or (self.sample and stamp <= self.sample[0]):
            return False
        travel = self._travel(stamp)
        sample = (stamp, tuple(errors), travel)
        if self.rate_sample:
            previous, old_errors, old_travel = self.rate_sample
            elapsed = stamp - previous
            if 0.5 <= elapsed <= 12.0:
                measured = tuple(
                    (errors[i] - old_errors[i] + travel[i] - old_travel[i]) / elapsed
                    for i in range(2)
                )
                if self.previous_rate is not None:
                    self.rate = tuple(
                        (old + new) / 2.0
                        if 0.2 <= abs(new) <= 5.0
                        and old * new > 0
                        and abs(new - old) <= max(0.2, abs(old) * 0.5)
                        else 0.0
                        for old, new in zip(self.previous_rate, measured)
                    )
                self.previous_rate = measured
            elif elapsed > 12.0:
                # The recovered position replaces the residual immediately.
                # Retain the previously learned rate until new observations
                # can measure it again; a long outage does not erase it.
                self.previous_rate = None
            if elapsed >= 0.5:
                self.rate_sample = sample
        else:
            self.rate_sample = sample
        self.sample = sample
        self._prune(stamp - 30.0)
        return True

    def residual(self, now):
        if self.sample is None or now < self.sample[0]:
            return None
        stamp, errors, previous_travel = self.sample
        travel = self._travel(now)
        return tuple(
            errors[i] + self.rate[i] * (now - stamp) - travel[i] + previous_travel[i]
            for i in range(2)
        )
