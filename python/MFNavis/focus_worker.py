"""One isolated, bounded focus computation; the UI never waits for a result."""

from __future__ import annotations

import multiprocessing as mp
from multiprocessing.shared_memory import SharedMemory
import time

import numpy as np


def _run(requests, results):
    from PiFinder.focus_tracker import FocusTracker

    tracker = FocusTracker()

    while True:
        try:
            name, shape, dtype, sigma_k, reset = requests.recv()
        except EOFError:
            return
        started = time.monotonic()
        memory = None
        try:
            memory = SharedMemory(name=name)
            frame = np.ndarray(shape, dtype=dtype, buffer=memory.buf)
            result = tracker.measure(frame, sigma_k=sigma_k, reset=reset)
            response = (result, None, time.monotonic() - started)
        except Exception as exc:
            response = (
                None,
                f"{type(exc).__name__}: {exc}",
                time.monotonic() - started,
            )
        finally:
            if memory is not None:
                memory.close()
        results.send(response)


class FocusWorker:
    """At most one frame in flight, with no camera-frame backlog.

    Share one reusable pixel buffer; only small requests/results cross pipes.
    The caller retains its image until poll() returns to associate the result
    with that exact frame. Spawn rather than fork the threaded UI process.
    """

    def __init__(self, *, timeout=8.0):
        self.timeout = timeout
        self._process = None
        self._requests = None
        self._results = None
        self._memory = None
        self._busy = False
        self._started = 0.0
        self._retry_after = 0.0

    @property
    def available(self):
        return not self._busy and time.monotonic() >= self._retry_after

    def _start(self):
        context = mp.get_context("spawn")
        child_requests, self._requests = context.Pipe(duplex=False)
        self._results, child_results = context.Pipe(duplex=False)
        self._process = context.Process(
            target=_run,
            args=(child_requests, child_results),
            name="FocusMeasure",
            daemon=True,
        )
        try:
            self._process.start()
        finally:
            child_requests.close()
            child_results.close()

    def submit(self, frame, *, sigma_k=5.0, reset=False):
        if not self.available:
            return False
        try:
            if self._process is None:
                self._start()
            frame = np.asarray(frame)
            if self._memory is None or self._memory.size < frame.nbytes:
                self._close_memory()
                self._memory = SharedMemory(create=True, size=max(1, frame.nbytes))
            shared = np.ndarray(frame.shape, dtype=frame.dtype, buffer=self._memory.buf)
            np.copyto(shared, frame)
            self._requests.send(
                (self._memory.name, frame.shape, frame.dtype, sigma_k, reset)
            )
            self._started = time.monotonic()
            self._busy = True
            return True
        except (OSError, RuntimeError):
            self.close()
            self._retry_after = time.monotonic() + 1.0
            return False

    def poll(self):
        if self._process is None:
            return None
        failed = False
        if self._busy:
            try:
                if self._results.poll():
                    result = self._results.recv()
                    self._busy = False
                    return result
            except (OSError, EOFError):
                failed = True
        if (
            failed
            or not self._process.is_alive()
            or (self._busy and time.monotonic() - self._started > self.timeout)
        ):
            self.close()
            self._retry_after = time.monotonic() + 1.0
            return None, "Focus worker exited or timed out", 0.0
        return None

    def _close_memory(self):
        if self._memory is not None:
            self._memory.close()
            self._memory.unlink()
            self._memory = None

    def close(self):
        process, self._process = self._process, None
        if process is not None and process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=0.05)
            if process.is_alive():
                process.kill()
                process.join(timeout=0.05)
            if not process.is_alive():
                process.close()
        for channel in (self._requests, self._results):
            if channel is not None:
                channel.close()
        self._requests = self._results = None
        self._close_memory()
        self._busy = False
