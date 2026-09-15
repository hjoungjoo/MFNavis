import threading
import time

import pytest

from PiFinder.latest_frame_worker import LatestFrameWorker

pytestmark = pytest.mark.unit


def _wait_result(worker, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = worker.poll()
        if result is not None:
            return result
        time.sleep(0.005)
    raise AssertionError("worker did not complete")


def test_worker_processes_on_background_thread():
    caller = threading.get_ident()
    with LatestFrameWorker(lambda item: (item, threading.get_ident())) as worker:
        assert worker.offer(4)
        result = _wait_result(worker)

    assert result.value[0] == 4
    assert result.value[1] != caller
    assert result.error is None


def test_latest_pending_item_replaces_intermediate_items():
    release = threading.Event()

    def process(item):
        if item == 1:
            assert release.wait(1.0)
        return item

    with LatestFrameWorker(process) as worker:
        assert worker.offer(1)
        assert not worker.offer(2)
        assert not worker.offer(3)
        assert not worker.offer(4)
        release.set()

        first = _wait_result(worker)
        second = _wait_result(worker)
        stats = worker.stats()

    assert first.value == 1
    assert second.value == 4
    assert stats.submitted == 2
    assert stats.completed == 2
    assert stats.skipped == 2


def test_worker_reports_exception_and_continues_with_latest_item():
    release = threading.Event()

    def process(item):
        if item == "bad":
            assert release.wait(1.0)
            raise ValueError("bad frame")
        return item.upper()

    with LatestFrameWorker(process) as worker:
        worker.offer("bad")
        worker.offer("next")
        release.set()

        failed = _wait_result(worker)
        recovered = _wait_result(worker)

    assert isinstance(failed.error, ValueError)
    assert failed.value is None
    assert recovered.error is None
    assert recovered.value == "NEXT"


def test_closed_worker_rejects_new_items():
    worker = LatestFrameWorker(lambda item: item)
    worker.close()

    with pytest.raises(RuntimeError):
        worker.offer(1)


def test_clear_pending_drops_replacement_but_not_running_item():
    release = threading.Event()

    def process(item):
        if item == 1:
            assert release.wait(1.0)
        return item

    with LatestFrameWorker(process) as worker:
        worker.offer(1)
        worker.offer(2)
        assert worker.clear_pending()
        assert not worker.clear_pending()
        release.set()
        result = _wait_result(worker)
        stats = worker.stats()

    assert result.value == 1
    assert stats.submitted == 1
    assert stats.completed == 1
    assert stats.skipped == 1


def test_exchange_starts_new_frame_instead_of_stale_pending():
    started = []
    release = threading.Event()

    def process(item):
        started.append(item)
        if item == "A":
            assert release.wait(1)
        return item

    with LatestFrameWorker(process) as worker:
        worker.exchange("A")
        worker.exchange("B")
        release.set()
        worker._future.result(timeout=1)
        result = worker.exchange("C")
        assert result.value == "A"
        assert _wait_result(worker).value == "C"
        assert worker.stats().skipped == 1
    assert started == ["A", "C"]


def test_result_age_includes_queue_and_consumption_delay(monkeypatch):
    from PiFinder import latest_frame_worker as module

    now = [10.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    with LatestFrameWorker(lambda item: item) as worker:
        worker.offer(1)
        worker._future.result(timeout=1)
        now[0] = 14.0
        result = worker.poll()
        assert result.is_fresh()
        now[0] = 16.0
        assert not result.is_fresh()
        now[0] = 9.0
        assert not result.is_fresh()
