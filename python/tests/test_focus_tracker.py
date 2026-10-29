import numpy as np
import pytest

from PiFinder import focus
from PiFinder.focus_tracker import FocusTracker

pytestmark = pytest.mark.unit


def frame_at(stars, size=1024):
    frame = np.full((size, size), 12.0, dtype=np.float32)
    for y, x, sigma in stars:
        top, left = max(0, int(y) - 100), max(0, int(x) - 100)
        bottom, right = min(size, int(y) + 101), min(size, int(x) + 101)
        yy, xx = np.mgrid[top:bottom, left:right]
        frame[top:bottom, left:right] += 180 * np.exp(
            -((yy - y) ** 2 + (xx - x) ** 2) / (2 * sigma**2)
        )
    return frame.astype(np.uint8)


@pytest.mark.parametrize("sigma", [1.0, 2.5, 5.0])
def test_native_hfd_accuracy_and_tracking_reacquisition(sigma):
    frame = frame_at([(300, 400, sigma), (700, 700, sigma)])
    original = frame.copy()
    expected = focus.focus_hfd(frame)
    tracker = FocusTracker()
    result = tracker.measure(frame, now=0)
    assert result.measurement_mode == "scan"
    assert result.n_used == expected.n_used == 2
    assert result.median_hfd == pytest.approx(expected.median_hfd, abs=0.15)
    tracked = tracker.measure(frame_at([(303, 404, sigma), (703, 704, sigma)]), now=0.2)
    assert tracked.measurement_mode == "tracked"
    assert tracked.median_hfd == pytest.approx(expected.median_hfd, abs=0.15)
    moved = tracker.measure(frame_at([(150, 150, sigma)]), now=0.4)
    assert moved.measurement_mode == "scan"
    assert any(abs(b.y - 150) < 1 for b in moved.blobs)
    np.testing.assert_array_equal(frame, original)


def test_blank_hot_pixels_defocus_edges_and_periodic_full_scan():
    tracker = FocusTracker()
    frame = frame_at([(100, 100, 2), (800, 800, 25)])
    frame[500, 500] = 255
    result = tracker.measure(frame, now=0)
    assert any(b.extent > 50 for b in result.blobs)
    assert not any(abs(b.y - 500) < 5 for b in result.blobs)
    assert tracker.measure(frame, now=3).measurement_mode == "scan"
    assert tracker.measure(frame, reset=True, now=3.1).measurement_mode == "scan"
    blank = tracker.measure(np.full_like(frame, 12), now=3.2)
    assert blank.median_hfd is None
    assert not blank.blobs
    edge = tracker.measure(frame_at([(6, 6, 2)]), now=3.3)
    assert edge.n_used == 1


def test_roi_tracking_does_not_repeat_full_frame_detection(monkeypatch):
    tracker = FocusTracker()
    frame = frame_at([(300, 400, 2)], size=2180)
    result = tracker.measure(frame, now=0)
    assert result.n_used == 1
    monkeypatch.setattr(
        tracker, "_acquire", lambda *a: pytest.fail("Full scan repeated")
    )
    assert tracker.measure(frame, now=0.2).n_used == 1
