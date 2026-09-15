"""Single-worker, latest-frame-wins background execution.

The camera may publish frames faster than an expensive consumer can process
them.  Queueing every frame increases latency indefinitely, so this helper
keeps at most one in-flight item and one pending item.  A newer pending item
replaces the older one and increments ``skipped``.

The worker is deliberately generic.  The solver can benchmark and validate
the scheduling policy independently before plate-solve arbitration is moved
off the synchronous path.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import threading
import time
from typing import Callable, Generic, Optional, TypeVar


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class WorkerResult(Generic[InputT, OutputT]):
    item: InputT
    value: Optional[OutputT]
    elapsed_ms: float
    error: Optional[BaseException] = None
    offered_at: float = 0.0

    def is_fresh(self, max_age_s: float = 5.0) -> bool:
        """Bound queue + processing + consumption delay using one monotonic clock."""
        return 0 <= time.monotonic() - self.offered_at <= max_age_s


@dataclass(frozen=True)
class WorkerStats:
    submitted: int
    completed: int
    skipped: int
    busy: bool
    pending: bool


class LatestFrameWorker(Generic[InputT, OutputT]):
    """Run one expensive item at a time and retain only the newest pending one.

    ``offer`` and ``poll`` are called by the owning solver thread.  Only
    ``process`` runs in the background thread.  This keeps stateful processors
    such as a temporal accumulator confined to one worker thread.
    """

    def __init__(
        self,
        process: Callable[[InputT], OutputT],
        *,
        thread_name: str = "latest-frame-worker",
    ) -> None:
        self._process = process
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=thread_name,
        )
        self._future: Optional[Future[WorkerResult[InputT, OutputT]]] = None
        self._pending: Optional[InputT] = None
        self._pending_at = 0.0
        self._closed = False
        self._lock = threading.Lock()
        self._submitted = 0
        self._completed = 0
        self._skipped = 0

    def _run(self, item: InputT, offered_at: float) -> WorkerResult[InputT, OutputT]:
        started = time.perf_counter()
        try:
            value = self._process(item)
            return WorkerResult(
                item=item,
                value=value,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                offered_at=offered_at,
            )
        except BaseException as exc:
            return WorkerResult(
                item=item,
                value=None,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                error=exc,
                offered_at=offered_at,
            )

    def _submit(self, item: InputT, offered_at: float) -> None:
        self._future = self._executor.submit(self._run, item, offered_at)
        self._submitted += 1

    def offer(self, item: InputT) -> bool:
        """Offer an item; return ``True`` when it starts immediately.

        While a task is running, the item becomes the sole pending task.  If a
        pending task already exists it is replaced, never queued behind it.
        """

        with self._lock:
            if self._closed:
                raise RuntimeError("latest-frame worker is closed")
            if self._future is None:
                self._submit(item, time.monotonic())
                return True
            if self._pending is not None:
                self._skipped += 1
            self._pending = item
            self._pending_at = time.monotonic()
            return False

    def exchange(self, item: InputT) -> Optional[WorkerResult[InputT, OutputT]]:
        """Collect completion and offer the newest frame atomically.

        If A completed with B pending and C arrives, run C next, never B.
        Use poll only when no new frame is available.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("latest-frame worker is closed")
            result = None
            if self._future is not None and self._future.done():
                result = self._future.result()
                self._completed += 1
                self._future = None
            if self._pending is not None:
                self._skipped += 1
                self._pending = None
            now = time.monotonic()
            if self._future is None:
                self._submit(item, now)
            else:
                self._pending = item
                self._pending_at = now
            return result

    def poll(self) -> Optional[WorkerResult[InputT, OutputT]]:
        """Return one completed result without blocking and start the pending item."""

        with self._lock:
            future = self._future
            if future is None or not future.done():
                return None
            result = future.result()
            self._completed += 1
            self._future = None
            if self._pending is not None:
                pending = self._pending
                self._pending = None
                self._submit(pending, self._pending_at)
            return result

    def stats(self) -> WorkerStats:
        with self._lock:
            return WorkerStats(
                submitted=self._submitted,
                completed=self._completed,
                skipped=self._skipped,
                busy=self._future is not None,
                pending=self._pending is not None,
            )

    def clear_pending(self) -> bool:
        """Drop the queued replacement while allowing the in-flight task to finish."""

        with self._lock:
            if self._pending is None:
                return False
            self._pending = None
            self._skipped += 1
            return True

    def close(self, *, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._pending = None
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def __enter__(self) -> "LatestFrameWorker[InputT, OutputT]":
        return self

    def __exit__(self, *_args) -> None:
        self.close()
