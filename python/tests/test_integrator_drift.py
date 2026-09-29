"""
Integration tests for IMU dead-reckoning drift through the real integrator
apply/advance functions. Replays synthetic telemetry through ImuDeadReckoning
and measures pointing error vs ground truth.

Catches regressions in:
- Quaternion math (drift explodes)
- Solve incorporation (positions don't update)
- Dead-reckoning (IMU movements not reflected)
- RaDecRoll / quaternion transform correctness
"""

from dataclasses import dataclass
from queue import Queue
from types import SimpleNamespace
from typing import List, Union
from unittest.mock import Mock

import numpy as np
import pytest
import quaternion

from PiFinder.integrator import _advance_with_imu, _apply_successful_solve
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
from PiFinder.pointing_model.quaternion_transforms import axis_angle2quat, radec2q_eq
from PiFinder.types.positioning import (
    FailedSolve,
    ImuSample,
    Pointing,
    PointingEstimate,
    SuccessfulSolve,
)


def test_stationary_imu_observations_are_published_and_enable_fallback(monkeypatch):
    from PiFinder import integrator as mod
    from PiFinder.indi_goto_guide_service import IndiGotoGuideService
    from PiFinder.pointing_coordinate_service import PointingCoordinateService

    anchor = quaternion.quaternion(1, 0, 0, 0)
    messages = iter(
        [
            SuccessfulSolve(
                camera=Pointing(100.0, 20.0, 0.0),
                aligned=Pointing(100.0, 20.0, 0.0),
                imu_anchor=anchor,
                last_solve_attempt=100.0,
                last_solve_success=100.0,
            ),
            FailedSolve(last_solve_attempt=101.0, last_solve_success=100.0),
            ImuSample(quat=anchor, timestamp=102.0, status=3, moving=False),
            ImuSample(quat=anchor, timestamp=102.1, status=3, moving=False),
            ImuSample(quat=anchor, timestamp=103.0, status=3, moving=False),
            ImuSample(quat=anchor, timestamp=104.0, status=3, sensor_healthy=False),
        ]
    )

    def next_message():
        try:
            return next(messages)
        except StopIteration:
            raise EOFError

    telemetry = Mock(replaying=True)
    telemetry.next_replay_message.side_effect = next_message
    monkeypatch.setattr(mod, "TelemetryManager", Mock(return_value=telemetry))
    monkeypatch.setattr(mod, "CaptureRecorder", Mock())
    monkeypatch.setattr(mod.MultiprocLogging, "configurer", Mock())
    monkeypatch.setattr(
        mod.config, "Config", lambda: SimpleNamespace(get_option=lambda _: "flat")
    )
    monkeypatch.setattr(mod.state_utils, "sleep_for_framerate", Mock())
    monkeypatch.setattr(mod, "_get_constellation", lambda *args: "")
    monkeypatch.setattr(mod, "_get_alt_az", lambda *args: (45.0, 90.0))
    state = Mock()
    state.target_pixel.return_value = (256, 256)
    mod.integrator(state, Queue(), Queue(), Queue())

    published = [call.args[0] for call in state.set_solution.call_args_list]
    assert [p.imu_observed_time for p in published] == [None, None, 102.0, 103.0]
    assert all(p.estimate_time == 100.0 for p in published)
    assert all(p.last_solve_success == 100.0 for p in published)
    state.solution.return_value = published[-1]
    coordinate = PointingCoordinateService().solved_sample(state, None)
    sample = {
        "valid": coordinate.valid,
        "ra": coordinate.ra_deg,
        "dec": coordinate.dec_deg,
        "source": coordinate.source,
        "timestamp": coordinate.timestamp,
        "metadata": coordinate.metadata,
    }
    service = IndiGotoGuideService(Queue(), Queue(), None)
    monkeypatch.setattr(mod.time, "time", lambda: 104.0)
    anchor_sample = service._imu_goto_anchor({"fresh": True, "solved": sample})
    assert anchor_sample["ra"] == 100.0
    assert anchor_sample["source"] == "pifinder_imu_estimate"
    monkeypatch.setattr(mod.time, "time", lambda: 110.0)
    assert service._imu_goto_anchor({"fresh": True, "solved": sample}) is None


# ── Synthetic telemetry generation ──────────────────────────────────


@dataclass
class SolveEvent:
    """A plate-solve event with true RA/Dec and IMU quaternion."""

    timestamp: float
    ra_deg: float
    dec_deg: float
    roll_deg: float
    imu_quat: quaternion.quaternion


@dataclass
class ImuEvent:
    """An IMU-only reading between solves, with ground truth for error measurement."""

    timestamp: float
    imu_quat: quaternion.quaternion
    moving: bool
    true_ra_deg: float
    true_dec_deg: float


@dataclass
class Measurement:
    """Dead-reckoned vs ground-truth angular error."""

    error_arcsec: float
    timestamp: float


def angular_separation_deg(ra1, dec1, ra2, dec2):
    """Great-circle angular separation in degrees between two (RA, Dec) pairs in degrees."""
    ra1_r, dec1_r = np.deg2rad(ra1), np.deg2rad(dec1)
    ra2_r, dec2_r = np.deg2rad(ra2), np.deg2rad(dec2)
    cos_sep = np.sin(dec1_r) * np.sin(dec2_r) + np.cos(dec1_r) * np.cos(
        dec2_r
    ) * np.cos(ra1_r - ra2_r)
    cos_sep = np.clip(cos_sep, -1.0, 1.0)
    return np.rad2deg(np.arccos(cos_sep))


def _make_imu_quat_for_radec(
    imu_dr: ImuDeadReckoning, ra_rad: float, dec_rad: float, roll_rad: float
) -> quaternion.quaternion:
    """
    Compute the IMU quaternion q_x2imu consistent with a given (RA, Dec, Roll),
    assuming q_eq2x is identity.

    From: q_eq2cam = q_eq2x * q_x2imu * q_imu2cam
    With q_eq2x = I: q_x2imu = q_eq2cam * q_imu2cam.conj()
    """
    q_eq2cam = radec2q_eq(ra_rad, dec_rad, roll_rad)
    q_x2imu = q_eq2cam * imu_dr.q_imu2cam.conj()
    return q_x2imu.normalized()


def generate_stationary_session(
    seed: int = 42,
    duration_s: float = 10.0,
    solve_interval_s: float = 2.0,
    imu_rate_hz: float = 10.0,
    noise_arcsec: float = 1.0,
) -> list:
    """
    Generate a stationary session: scope doesn't move, IMU has small noise.
    Returns list of SolveEvent and ImuEvent in chronological order.
    """
    rng = np.random.default_rng(seed)
    ra_deg, dec_deg, roll_deg = 180.0, 45.0, 0.0
    ra_rad, dec_rad = np.deg2rad(ra_deg), np.deg2rad(dec_deg)
    roll_rad = np.deg2rad(0.0)

    tmp_dr = ImuDeadReckoning("flat")
    base_quat = _make_imu_quat_for_radec(tmp_dr, ra_rad, dec_rad, roll_rad)

    events: List[Union[SolveEvent, ImuEvent]] = []
    t = 0.0
    imu_dt = 1.0 / imu_rate_hz
    next_solve = 0.0

    while t <= duration_s:
        noise_rad = np.deg2rad(noise_arcsec / 3600.0)
        axis = rng.normal(size=3)
        axis /= np.linalg.norm(axis)
        angle = rng.normal(scale=noise_rad)
        q_noise = axis_angle2quat(axis, angle)
        noisy_quat = (base_quat * q_noise).normalized()

        if t >= next_solve:
            events.append(
                SolveEvent(
                    timestamp=t,
                    ra_deg=ra_deg,
                    dec_deg=dec_deg,
                    roll_deg=roll_deg,
                    imu_quat=noisy_quat,
                )
            )
            next_solve = t + solve_interval_s
        else:
            events.append(
                ImuEvent(
                    timestamp=t,
                    imu_quat=noisy_quat,
                    moving=False,
                    true_ra_deg=ra_deg,
                    true_dec_deg=dec_deg,
                )
            )

        t += imu_dt

    return events


def generate_slew_session(
    seed: int = 123,
    duration_s: float = 30.0,
    solve_interval_s: float = 3.0,
    imu_rate_hz: float = 10.0,
    slew_speed_deg_s: float = 2.0,
    drift_arcsec_s: float = 5.0,
) -> list:
    """
    Generate a slewing session: scope moves in RA at constant rate,
    IMU has a slow systematic drift added on top.
    """
    rng = np.random.default_rng(seed)
    start_ra_deg, dec_deg, roll_deg = 90.0, 30.0, 0.0

    tmp_dr = ImuDeadReckoning("flat")
    events: List[Union[SolveEvent, ImuEvent]] = []
    t = 0.0
    imu_dt = 1.0 / imu_rate_hz
    next_solve = 0.0
    last_solve_time = 0.0

    drift_axis = rng.normal(size=3)
    drift_axis /= np.linalg.norm(drift_axis)
    drift_rate_rad_s = np.deg2rad(drift_arcsec_s / 3600.0)

    while t <= duration_s:
        true_ra_deg = start_ra_deg + slew_speed_deg_s * t
        true_ra_rad = np.deg2rad(true_ra_deg)
        dec_rad = np.deg2rad(dec_deg)
        roll_rad = np.deg2rad(roll_deg)

        base_quat = _make_imu_quat_for_radec(tmp_dr, true_ra_rad, dec_rad, roll_rad)

        time_since_solve = t - last_solve_time
        drift_angle = drift_rate_rad_s * time_since_solve
        q_drift = axis_angle2quat(drift_axis, drift_angle)

        noise_rad = np.deg2rad(1.0 / 3600.0)
        noise_axis = rng.normal(size=3)
        noise_axis /= np.linalg.norm(noise_axis)
        q_noise = axis_angle2quat(noise_axis, rng.normal(scale=noise_rad))

        drifted_quat = (base_quat * q_drift * q_noise).normalized()

        if t >= next_solve:
            events.append(
                SolveEvent(
                    timestamp=t,
                    ra_deg=true_ra_deg,
                    dec_deg=dec_deg,
                    roll_deg=roll_deg,
                    imu_quat=drifted_quat,
                )
            )
            last_solve_time = t
            next_solve = t + solve_interval_s
        else:
            events.append(
                ImuEvent(
                    timestamp=t,
                    imu_quat=drifted_quat,
                    moving=True,
                    true_ra_deg=true_ra_deg,
                    true_dec_deg=dec_deg,
                )
            )

        t += imu_dt

    return events


# ── Replay engine ───────────────────────────────────────────────────


def _solve_event_to_message(event: SolveEvent) -> SuccessfulSolve:
    """Build the solver→integrator message for a synthetic solve event,
    mirroring the real solver (camera == aligned: no alignment offset)."""
    pointing = Pointing(RA=event.ra_deg, Dec=event.dec_deg, Roll=event.roll_deg)
    return SuccessfulSolve(
        camera=pointing,
        aligned=pointing,
        imu_anchor=event.imu_quat,
        last_solve_attempt=event.timestamp,
        last_solve_success=event.timestamp,
    )


def _imu_event_to_sample(event: ImuEvent) -> ImuSample:
    """Build the shared-state IMU sample for a synthetic IMU event."""
    return ImuSample(
        quat=event.imu_quat,
        timestamp=event.timestamp,
        status=3,
        moving=event.moving,
    )


def _aligned_estimate_error_arcsec(
    estimate: PointingEstimate, event: ImuEvent
) -> float:
    """Angular error of the published aligned estimate vs ground truth."""
    aligned = estimate.pointing.aligned.estimate
    assert aligned is not None, "callers only measure populated estimates"
    error_deg = angular_separation_deg(
        aligned.RA,
        aligned.Dec,
        event.true_ra_deg,
        event.true_dec_deg,
    )
    return error_deg * 3600.0


def replay_imu_drift(events: list) -> List[Measurement]:
    """
    Replay telemetry and measure dead-reckoning error at each IMU update
    by comparing the integrator's published estimate to ground truth.
    """
    idr = ImuDeadReckoning("flat")
    estimate = PointingEstimate()
    measurements: List[Measurement] = []

    for event in events:
        if isinstance(event, SolveEvent):
            estimate = _apply_successful_solve(
                estimate, _solve_event_to_message(event), idr
            )

        elif isinstance(event, ImuEvent):
            if not idr.is_initialized() or estimate.imu_anchor is None:
                continue

            # May not advance (below deadband); the estimate then stays at
            # the last applied value, which is still the published answer.
            _advance_with_imu(estimate, idr, _imu_event_to_sample(event))

            if estimate.pointing.aligned.estimate is not None:
                measurements.append(
                    Measurement(
                        error_arcsec=_aligned_estimate_error_arcsec(estimate, event),
                        timestamp=event.timestamp,
                    )
                )

    return measurements


def replay_post_solve_errors(events: list, max_readings: int = 3) -> List[Measurement]:
    """
    Measure dead-reckoning error of the first few IMU readings after each solve
    vs ground truth. Verifies that solve incorporation resets drift.
    """
    idr = ImuDeadReckoning("flat")
    estimate = PointingEstimate()
    measurements: List[Measurement] = []
    readings_since_solve = max_readings

    for event in events:
        if isinstance(event, SolveEvent):
            estimate = _apply_successful_solve(
                estimate, _solve_event_to_message(event), idr
            )
            readings_since_solve = 0

        elif isinstance(event, ImuEvent):
            if not idr.is_initialized() or estimate.imu_anchor is None:
                continue

            _advance_with_imu(estimate, idr, _imu_event_to_sample(event))

            if (
                readings_since_solve < max_readings
                and estimate.pointing.aligned.estimate is not None
            ):
                measurements.append(
                    Measurement(
                        error_arcsec=_aligned_estimate_error_arcsec(estimate, event),
                        timestamp=event.timestamp,
                    )
                )
            readings_since_solve += 1

    return measurements


# ── Tests ───────────────────────────────────────────────────────────


@pytest.mark.integration
class TestIntegratorDrift:
    """
    Integration tests that replay synthetic telemetry through the real
    ImuDeadReckoning and integrator apply/advance functions, measuring
    drift vs ground truth.
    """

    def test_stationary_drift(self):
        """
        Scope is stationary, IMU has only tiny noise.
        Dead-reckoned position should stay very close to truth.
        """
        events = generate_stationary_session(seed=42, duration_s=10.0)
        measurements = replay_imu_drift(events)

        assert len(measurements) > 0, "Should have at least one measurement"
        errors = [m.error_arcsec for m in measurements]
        mean_error = np.mean(errors)
        max_error = np.max(errors)

        # Stationary scope with 1 arcsec noise: drift should be tiny
        # Baseline: ~0 arcsec (noise below measurement precision)
        assert (
            mean_error < 5
        ), f"Stationary mean drift {mean_error:.1f} arcsec exceeds 5 arcsec threshold"
        assert (
            max_error < 10
        ), f"Stationary max drift {max_error:.1f} arcsec exceeds 10 arcsec threshold"

    def test_stationary_anchor_drift_does_not_move_plate_anchored_coordinate(self):
        """Large accumulated IMUPLUS drift is not physical telescope motion."""
        idr = ImuDeadReckoning("flat")
        anchor_quat = _make_imu_quat_for_radec(
            idr, np.deg2rad(180.0), np.deg2rad(45.0), 0.0
        )
        solve = SuccessfulSolve(
            camera=Pointing(RA=180.0, Dec=45.0, Roll=0.0),
            aligned=Pointing(RA=180.0, Dec=45.0, Roll=0.0),
            imu_anchor=anchor_quat,
            last_solve_attempt=100.0,
            last_solve_success=100.0,
        )
        estimate = _apply_successful_solve(PointingEstimate(), solve, idr)
        drifted_quat = (
            anchor_quat * axis_angle2quat([0, 0, 1], np.deg2rad(0.5))
        ).normalized()

        advanced = _advance_with_imu(
            estimate,
            idr,
            ImuSample(
                quat=drifted_quat,
                timestamp=101.0,
                status=3,
                moving=False,
            ),
        )

        assert advanced is False
        assert estimate.pointing.aligned.estimate == solve.aligned
        assert estimate.estimate_time == 100.0
        assert estimate.imu_observed_time == 101.0
        assert estimate.last_solve_success == 100.0

        # Failed sensor reads must not keep an old estimate usable for GoTo.
        _advance_with_imu(
            estimate,
            idr,
            ImuSample(
                quat=drifted_quat,
                timestamp=102.0,
                status=3,
                moving=False,
                sensor_healthy=False,
            ),
        )
        assert estimate.imu_observed_time == 101.0
        _apply_successful_solve(estimate, solve, idr)
        assert estimate.imu_observed_time is None

    def test_failed_solve_then_real_motion_uses_last_successful_anchor(self):
        """No-solve motion remains relative to the last confirmed plate solve."""
        from PiFinder.integrator import _apply_failed_solve

        idr = ImuDeadReckoning("flat")
        anchor_quat = _make_imu_quat_for_radec(
            idr, np.deg2rad(100.0), np.deg2rad(20.0), 0.0
        )
        solve = SuccessfulSolve(
            camera=Pointing(RA=100.0, Dec=20.0, Roll=0.0),
            aligned=Pointing(RA=100.0, Dec=20.0, Roll=0.0),
            imu_anchor=anchor_quat,
            last_solve_attempt=100.0,
            last_solve_success=100.0,
        )
        estimate = _apply_successful_solve(PointingEstimate(), solve, idr)
        _apply_failed_solve(
            estimate,
            FailedSolve(last_solve_attempt=101.0, last_solve_success=100.0),
        )

        moved_quat = _make_imu_quat_for_radec(
            idr, np.deg2rad(102.0), np.deg2rad(20.0), 0.0
        )
        advanced = _advance_with_imu(
            estimate,
            idr,
            ImuSample(
                quat=moved_quat,
                timestamp=102.0,
                status=3,
                moving=True,
            ),
        )

        assert advanced is True
        assert estimate.pointing.camera.solve == solve.camera
        assert estimate.imu_anchor == anchor_quat
        assert estimate.pointing.aligned.estimate.RA == pytest.approx(102.0)
        assert estimate.pointing.aligned.estimate.Dec == pytest.approx(20.0)

    def test_slew_tracking_accuracy(self):
        """
        Scope slewing at 2 deg/s with 5 arcsec/s simulated IMU drift.
        Dead-reckoning should track the true position with bounded error.
        Error should not grow without bound over the session.
        """
        events = generate_slew_session(seed=123, duration_s=30.0)
        measurements = replay_imu_drift(events)

        assert len(measurements) > 0, "Should have at least one measurement"
        errors = [m.error_arcsec for m in measurements]
        mean_error = np.mean(errors)

        # With 5 arcsec/s drift and 3s solve intervals, accumulated drift
        # between solves is bounded. Baseline: mean ~6, max ~13 arcsec.
        assert (
            mean_error < 15
        ), f"Slew mean drift {mean_error:.1f} arcsec exceeds 15 arcsec threshold"

        # Verify errors don't grow without bound across the session
        if len(errors) >= 20:
            first_quarter = np.mean(errors[: len(errors) // 4])
            last_quarter = np.mean(errors[-len(errors) // 4 :])
            assert last_quarter < first_quarter * 3, (
                f"Drift growing over time: first quarter {first_quarter:.1f}, "
                f"last quarter {last_quarter:.1f} arcsec"
            )

    def test_solve_correction_resets_drift(self):
        """
        After each solve, the first few IMU dead-reckoned positions should
        have near-zero error vs ground truth (solve corrects drift).
        """
        events = generate_slew_session(
            seed=456,
            duration_s=20.0,
            solve_interval_s=4.0,
            slew_speed_deg_s=1.0,
            drift_arcsec_s=2.0,
        )
        measurements = replay_post_solve_errors(events, max_readings=3)

        assert len(measurements) > 0, "Should have post-solve measurements"
        errors = [m.error_arcsec for m in measurements]
        mean_error = np.mean(errors)

        # Right after a solve, error should be just noise + tiny drift.
        # Baseline: mean ~7, max ~11 arcsec.
        assert mean_error < 20, (
            f"Post-solve mean error {mean_error:.1f} arcsec exceeds 20 arcsec threshold. "
            "Solve correction may not be resetting drift properly."
        )
