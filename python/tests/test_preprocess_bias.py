import pytest

from PiFinder.preprocess_bias import PreprocessBiasTracker

pytestmark = pytest.mark.unit


def _solution(ra, dec, target_ra=None, target_dec=None):
    result = {"RA": ra, "Dec": dec, "Matches": 12}
    if target_ra is not None:
        result["RA_target"] = target_ra
        result["Dec_target"] = target_dec
    return result


def test_bias_requires_two_agreeing_samples_before_application():
    tracker = PreprocessBiasTracker(required_samples=2)
    raw = _solution(10.0, 20.0)
    trusted = _solution(10.05, 19.98)

    assert tracker.update(raw, trusted)
    assert not tracker.ready
    assert tracker.apply(raw)["RA"] == 10.0
    assert tracker.update(raw, trusted)
    corrected = tracker.apply(raw)

    assert tracker.ready
    assert corrected["RA"] == pytest.approx(10.05)
    assert corrected["Dec"] == pytest.approx(19.98)


def test_large_disagreement_is_rejected_without_changing_bias():
    tracker = PreprocessBiasTracker(max_agreement_deg=0.12, required_samples=1)

    assert not tracker.update(_solution(10.0, 20.0), _solution(11.0, 20.0))

    status = tracker.status()
    assert not status.ready
    assert status.accepted_samples == 0
    assert status.rejected_samples == 1


def test_ra_wrap_uses_short_offset():
    tracker = PreprocessBiasTracker(required_samples=1)
    assert tracker.update(_solution(359.98, 0.0), _solution(0.02, 0.0))

    corrected = tracker.apply(_solution(359.99, 0.0))

    assert corrected["RA"] == pytest.approx(0.03)


def test_target_coordinate_has_its_own_bias():
    tracker = PreprocessBiasTracker(required_samples=1)
    raw = _solution(10.0, 20.0, 11.0, 21.0)
    trusted = _solution(10.04, 19.98, 11.06, 20.97)

    assert tracker.update(raw, trusted)
    corrected = tracker.apply(raw)

    assert corrected["RA"] == pytest.approx(10.04)
    assert corrected["Dec"] == pytest.approx(19.98)
    assert corrected["RA_target"] == pytest.approx(11.06)
    assert corrected["Dec_target"] == pytest.approx(20.97)


def test_reset_discards_learned_bias():
    tracker = PreprocessBiasTracker(required_samples=1)
    tracker.update(_solution(10.0, 20.0), _solution(10.05, 19.98))
    assert tracker.ready

    tracker.reset()

    assert not tracker.ready
    assert tracker.apply(_solution(10.0, 20.0))["RA"] == 10.0


@pytest.mark.parametrize(
    "key,value",
    [
        ("RA", float("nan")),
        ("RA", float("inf")),
        ("Dec", 91),
        ("Dec_target", float("nan")),
        ("RA_target", float("inf")),
    ],
)
def test_invalid_sample_never_poison_bias(key, value):
    tracker = PreprocessBiasTracker(required_samples=1)
    raw = _solution(10, 20, 11, 21)
    trusted = _solution(10.01, 20.01, 11.01, 21.01)
    assert tracker.update(raw, trusted)
    before = tracker.apply(raw)
    trusted[key] = value
    assert not tracker.update(raw, trusted)
    assert tracker.apply(raw) == before


def test_bias_expires_and_requires_new_stable_samples():
    now = [100.0]
    tracker = PreprocessBiasTracker(clock=lambda: now[0], max_age_s=30)
    raw, trusted = _solution(10, 20), _solution(10.01, 20.01)
    assert tracker.update(raw, trusted)
    assert tracker.update(raw, trusted)
    assert tracker.ready
    now[0] += 31
    assert tracker.apply(raw) == raw
    assert tracker.status().accepted_samples == 0
    assert tracker.update(raw, trusted)
    assert not tracker.ready
    assert tracker.update(raw, trusted)
    assert tracker.ready


def test_correction_cannot_cross_declination_pole():
    tracker = PreprocessBiasTracker(required_samples=1)
    assert tracker.update(_solution(10, 89.9), _solution(10, 89.99))
    raw = _solution(10, 89.99)
    assert tracker.apply(raw) == raw


def test_camera_only_sample_does_not_refresh_old_target_bias():
    tracker = PreprocessBiasTracker(required_samples=1)
    assert tracker.update(
        _solution(10, 20, 11, 21), _solution(10.01, 20.01, 11.01, 21.01)
    )
    assert tracker.update(_solution(10, 20), _solution(10.01, 20.01))
    assert tracker.status().target_ra_deg is None
    assert tracker.apply(_solution(10, 20, 11, 21))["RA_target"] == 11
