import pytest

from PiFinder.guide_holdover import GuideHoldover

pytestmark = pytest.mark.unit


def test_residual_is_spent_once_even_after_day_without_solve():
    guide = GuideHoldover()
    guide.observe(100, (30, -15))
    guide.record_pulse(0, 100, 2, 15)
    guide.record_pulse(1, 100, 1, -15)
    assert guide.residual(101) == pytest.approx((15, 0))
    assert guide.residual(102) == pytest.approx((0, 0))
    assert guide.residual(86500) == pytest.approx((0, 0))


def test_learned_drift_survives_long_outage_without_reintegrating_old_error():
    guide = GuideHoldover()
    guide.observe(0, (10, 0))
    guide.record_pulse(0, 0, 1, 10)
    guide.observe(1, (1, 0))
    guide.record_pulse(0, 1, 0.1, 10)
    guide.observe(2, (1, 0))
    assert guide.rate == pytest.approx((1, 0))
    for now in range(2, 7202):
        residual = guide.residual(now)[0]
        if residual >= 1:
            guide.record_pulse(0, now, residual / 10, 10)
    # Rounding at the 1 arcsec deadband can defer one pulse by one tick.
    assert 0.99 <= guide.residual(7202)[0] <= 2.001
    assert len(guide.pulses) < 40
    guide.observe(7202, (-3, 4))
    assert guide.residual(7202) == pytest.approx((-3, 4))
    assert not guide.observe(7202, (100, 100))
    assert guide.residual(7202) == pytest.approx((-3, 4))


def test_replacing_axis_timer_charges_only_executed_travel():
    guide = GuideHoldover()
    guide.observe(0, (100, 50))
    guide.record_pulse(0, 0, 5, 10)
    guide.record_pulse(1, 0, 4, 10)
    guide.record_pulse(0, 1, 0.001, 10)
    assert guide.residual(10) == pytest.approx((89.99, 10))
    guide.reset()
    assert guide.residual(11) is None
    assert guide.rate == (0, 0)


def test_fast_camera_frames_still_learn_drift_over_independent_intervals():
    guide = GuideHoldover()
    for frame in range(21):
        stamp = frame / 10
        guide.observe(stamp, (2 * stamp, -stamp))
    assert guide.rate == pytest.approx((2, -1))
    assert guide.residual(100) == pytest.approx((200, -100))
