"""Optical PID limits and approach behavior."""

import pytest
from PiFinder.guide_pid import GuidePID

pytestmark = pytest.mark.unit


def test_full_first_response_and_damped_approach():
    pid = GuidePID()
    assert pid.correction(30, 100, 40) == 30
    approach = pid.correction(6, 100.25, 40)
    assert 0 < approach < 6


def test_large_error_has_no_integral_windup():
    pid = GuidePID()
    for stamp in range(100, 120):
        assert pid.correction(100, stamp, 20) == 20
        assert pid.integral == 0
    assert 0 < pid.correction(2, 120, 20) < 2


def test_axes_are_independent_and_crossing_resets_history():
    ns, we = GuidePID(), GuidePID()
    ns.correction(10, 100, 40)
    ns.correction(10, 101, 40)
    assert ns.integral > 0
    assert we.correction(10, 101, 40) == 10
    assert ns.correction(-2, 102, 40) < 0
    assert ns.integral <= 0


def test_repeated_observation_cannot_integrate_and_outage_resets():
    pid = GuidePID()
    pid.correction(10, 100, 40)
    pid.correction(10, 101, 40)
    integral = pid.integral
    assert pid.correction(5, 101, 40) == 0
    assert pid.integral == integral
    assert pid.correction(5, 120, 40) == 5
    pid.reset()
    assert pid.correction(5, 121, 40) == 5
