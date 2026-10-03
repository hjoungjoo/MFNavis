import pytest

from PiFinder.guide_drift import GuideDrift

pytestmark = pytest.mark.unit


def test_drift_requires_three_distinct_consistent_solves():
    drift = GuideDrift()
    drift.observe(100, (0, 0))
    assert drift.rates(101) == (0, 0)
    drift.observe(103, (6, -3))
    for _ in range(5):
        drift.observe(103, (6, -3))
    assert drift.rates(104) == (0, 0)
    drift.observe(106, (12, -6))
    assert drift.rates(107) == pytest.approx((2, -1))


def test_sent_corrections_are_not_mistaken_for_a_drift_reversal():
    drift = GuideDrift()
    drift.observe(100, (0, 0))
    drift.observe(103, (6, 0))
    # Correct 9 arcsec over two seconds: half is before the next exposure.
    drift.record_pulse(0, 105, 2, 9)
    drift.observe(106, (7.5, 0))
    assert drift.rates(106) == pytest.approx((2, 0))
    drift.observe(109, (9, 0))
    assert drift.rates(109) == pytest.approx((2, 0))


@pytest.mark.parametrize("errors", [(-6, 0), (60, 0), (6, 0), (float("nan"), 0)])
def test_reversal_jump_stall_and_invalid_measurement_disable_prediction(errors):
    drift = GuideDrift()
    drift.observe(100, (0, 0))
    drift.observe(103, (3, 0))
    drift.observe(106, (6, 0))
    assert drift.rates(106) == (1, 0)
    drift.pulse_remainder[0] = 0.1
    drift.observe(109, errors)
    assert drift.rates(109) == (0, 0)
    assert drift.pulse_remainder == [0.0, 0.0]


@pytest.mark.parametrize("now", [99, 113, 130])
def test_stale_solve_or_clock_jump_requires_new_learning(now):
    drift = GuideDrift()
    for stamp in (100, 103, 106):
        drift.observe(stamp, (stamp - 100, 0))
    assert drift.rates(now) == (0, 0)
    drift.observe(now + 1, (0, 0))
    assert drift.rates(now + 1) == (0, 0)


def test_gap_resets_even_if_no_prediction_tick_ran():
    drift = GuideDrift()
    for stamp in (100, 103, 106, 115):
        drift.observe(stamp, (stamp - 100, 0))
    assert drift.rates(115) == (0, 0)
