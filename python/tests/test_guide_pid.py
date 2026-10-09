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


def test_distance_shaping_preserves_fast_travel_and_softens_near_target():
    outputs = [
        GuidePID().correction(error, 100, 40, approach_band=20)
        for error in (1, 5, 10, 20, 100)
    ]
    assert outputs == sorted(outputs)
    assert outputs[-2:] == [20, 40]
    assert 0.5 < outputs[0] < 0.6
    assert outputs[1] < 5
    assert outputs[2] == pytest.approx(7.5)
    # Shape even saturated corrections: a wide accuracy band must not hide
    # approach damping behind the 2.5 s actuator cap.
    assert GuidePID().correction(180, 100, 40, approach_band=360) == 30


def test_derivative_filter_reduces_response_to_fast_solve_jitter():
    filtered, unfiltered = GuidePID(ki=0), GuidePID(ki=0, derivative_filter_seconds=0)
    filtered.correction(10, 100, 40)
    unfiltered.correction(10, 100, 40)
    assert filtered.correction(9, 100.1, 40) > unfiltered.correction(9, 100.1, 40)
    filtered.correction(-1, 100.2, 40)
    assert filtered.filtered_derivative == 0


@pytest.mark.parametrize("cadence", [0.1, 0.4, 1.0, 3.0])
@pytest.mark.parametrize("response", [0.8, 1.0, 1.2])
def test_closed_loop_pulse_replacement_converges(cadence, response):
    # A simple timed actuator: each observation replaces its remaining timer.
    # Exercise solves both inside a 2.5 s pulse and after it, with rate mismatch.
    pid = GuidePID()
    error = 150.0
    speed = 15.041
    for tick in range(int(40 / cadence)):
        if abs(error) <= 1:
            break
        correction = pid.correction(
            error, 100 + tick * cadence, speed * 2.5, approach_band=12
        )
        travel = min(abs(correction), speed * cadence) * response
        error -= travel if correction > 0 else -travel
        assert error >= -6  # Overshoot stays within the 0.1 arcmin guide floor.
    assert abs(error) <= 1
