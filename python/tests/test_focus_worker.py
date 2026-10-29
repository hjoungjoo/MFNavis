"""Real spawned-worker lifecycle and nonblocking UI integration."""

from collections import deque
from multiprocessing.shared_memory import SharedMemory
import time
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from PiFinder.focus import FocusResult, focus_hfd
from PiFinder.focus_worker import FocusWorker
from PiFinder.ui import preview as ui

pytestmark = pytest.mark.unit


def await_result(worker):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = worker.poll()
        if result is not None:
            return result
        time.sleep(0.01)
    pytest.fail("Focus worker did not return")


def test_spawned_worker_matches_sync_and_never_queues_extra_frames():
    y, x = np.indices((128, 128))
    frame = (20 + 180 * np.exp(-((y - 60) ** 2 + (x - 65) ** 2) / 32)).astype(np.uint8)
    expected = focus_hfd(frame)
    worker = FocusWorker(timeout=15)
    try:
        assert worker.submit(frame)
        name = worker._memory.name
        assert not worker.submit(frame)
        result, error, duration = await_result(worker)
        assert error is None
        assert result == expected
        assert duration > 0
        assert worker.available
        assert worker.submit(np.zeros((256, 256), dtype=np.uint8))
        assert await_result(worker)[0].median_hfd is None
    finally:
        worker.close()
    with pytest.raises(FileNotFoundError):
        SharedMemory(name=name)
    assert worker._process is None


def test_worker_error_and_process_death_do_not_freeze_or_leave_stale_results():
    worker = FocusWorker(timeout=15)
    try:
        assert worker.submit(np.zeros((8, 8, 3), dtype=np.uint8))
        result, error, _ = await_result(worker)
        assert result is None
        assert "ValueError" in error
        assert worker.submit(np.zeros((128, 128), dtype=np.uint8))
        assert await_result(worker)[1] is None
        worker._process.terminate()
        worker._process.join(timeout=2)
        result, error, _ = worker.poll()
        assert result is None and error
        assert not worker.available
        worker._retry_after = 0
        assert worker.submit(np.zeros((128, 128), dtype=np.uint8))
        assert await_result(worker)[1] is None
    finally:
        worker.close()


def test_worker_timeout_and_close_while_busy_release_shared_memory():
    worker = FocusWorker(timeout=15)
    try:
        worker.submit(np.zeros((2180, 2180), dtype=np.uint8))
        name = worker._memory.name
        worker._started -= 30
        result, error, _ = worker.poll()
        assert result is None and error
        assert worker._process is None
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=name)
    finally:
        worker.close()


class FakeWorker:
    def __init__(self):
        self.available = True
        self.jobs = []
        self.completed = None
        self.closed = False

    def submit(self, frame, **kwargs):
        assert self.available
        self.jobs.append(frame.copy())
        self.available = False
        return True

    def poll(self):
        completed, self.completed = self.completed, None
        if completed is not None:
            self.available = True
        return completed

    def close(self):
        self.closed = True


@pytest.fixture
def preview(monkeypatch):
    p = object.__new__(ui.UIPreview)
    p._reset_focus_cache()
    p._wide_focus_mode = False
    p._focus_frame_hw = (32, 32)
    p._last_focus_frame_time = 0
    p._last_focus_catalog_time = 0
    p.last_focus_result = None
    p._tracked_focus_blobs = ()
    p._focus_slot_catalog_ids = ()
    p.focus_history = deque()
    p.last_update = 0
    p.display_mode = ui.DISPLAY_STARS
    p.camera_image = Image.new("L", (32, 32), 10)
    p.screen = Image.new("RGB", (32, 32))
    p.metadata = {"exposure_end": 1.0}
    p.shared_state = SimpleNamespace(last_image_metadata=lambda: p.metadata)
    p._focus_input_image = lambda image: image
    p._adopt_solved_catalog_ids = lambda t: None
    p._render_focus_tiles = lambda image: image
    p._render_image_frame = lambda image: image
    p._draw_focus_overlay = lambda: None
    p._draw_status_bar = lambda: None
    p.screen_update = lambda: None
    worker = FakeWorker()
    monkeypatch.setattr(ui, "FocusWorker", lambda: worker)
    monkeypatch.setattr(ui, "FOCUS_MEASURE_INTERVAL", 0)

    def no_sync(*args, **kwargs):
        pytest.fail("UI called synchronous focus calculation")

    monkeypatch.setattr(ui.focus, "focus_hfd", no_sync)
    return p, worker


def test_forced_redraws_do_not_remeasure_same_frame(preview):
    p, worker = preview
    p.update(force=True)
    for _ in range(5):
        p.update(force=True)
    assert len(worker.jobs) == 1
    worker.completed = (FocusResult(4, 1, 10, 100, False), None, 0.2)
    p.update()
    p.update(force=True)
    assert len(worker.jobs) == 1
    assert len(p.focus_history) == 1


def test_slow_result_uses_its_exact_frame_then_submits_latest_only(preview):
    p, worker = preview
    p.update(force=True)
    for frame_time in (2, 3, 4):
        p.metadata = {"exposure_end": frame_time}
        p.camera_image = Image.new("L", (32, 32), frame_time * 10)
        p.update()
    assert len(worker.jobs) == 1
    worker.completed = (FocusResult(4, 1, 10, 100, False), None, 1.5)
    p.update()
    assert p._last_focus_frame_time == 1
    assert p.screen.getpixel((0, 0)) == (10, 10, 10)
    assert len(worker.jobs) == 2
    assert worker.jobs[-1][0, 0] == 40
    assert p._focus_pending[1]["exposure_end"] == 4


def test_image_preview_keeps_refreshing_while_focus_is_busy(preview):
    p, worker = preview
    p.display_mode = ui.DISPLAY_IMAGE
    p.update()
    p.metadata = {"exposure_end": 2}
    p.camera_image = Image.new("L", (32, 32), 42)
    p.update()
    assert not worker.available
    assert p.screen.getpixel((0, 0)) == (42, 42, 42)


def test_failed_result_clears_hfd_and_exit_discards_inflight_image(preview):
    p, worker = preview
    p.update()
    p.last_focus_result = FocusResult(4, 1, 10, 100, False)
    worker.completed = (None, "worker timed out", 0)
    p.update()
    assert p.last_focus_result is None
    assert p._tracked_focus_blobs == ()
    p._close_focus_worker()
    p._reset_focus_cache()
    assert worker.closed
    assert p._focus_pending is None
    assert p._focus_image is None
