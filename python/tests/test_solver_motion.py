import math

import numpy as np
import pytest
import quaternion

from PiFinder.solver_motion import SolverMotionGate
from PiFinder.solver_scheduling import SolverSchedulingPolicy
from PiFinder.preprocess_bias import PreprocessBiasTracker
from PiFinder.types.positioning import ImuSample

pytestmark = pytest.mark.unit


def frame(angle=0.0, *, moving=False, delta=0.0, timestamp=100.0):
    imu = ImuSample(
        quat=quaternion.from_rotation_vector([0, 0, math.radians(angle)]),
        timestamp=timestamp,
        status=3,
        moving=moving,
    )
    return {"imu": imu, "imu_delta": delta, "exposure_end": timestamp}


def test_stationary_vibration_keeps_fast_scheduling_and_calibrated_bias():
    gate = SolverMotionGate()
    policy = SolverSchedulingPolicy()
    bias = PreprocessBiasTracker(required_samples=2)
    raw, processed = {"RA": 10.0, "Dec": 20.0}, {"RA": 10.01, "Dec": 20.0}
    for _ in range(3):
        policy.choose(raw_solved=True)
        bias.update(raw, processed)
    assert bias.ready and policy.execution == "async"
    gate.evaluate(frame(), mount_moving=False)

    for i, angle in enumerate([0.005, -0.02, 0.015, 0.0] * 5):
        metadata = frame(angle, moving=True, delta=0.04, timestamp=101 + i)
        if gate.evaluate(metadata, mount_moving=False):
            policy.reset("moving")
            bias.reset()
        assert policy.choose(raw_solved=True) == "async"
        assert bias.ready
        assert gate.reason == "small_imu_jitter"


def test_slow_pan_is_measured_from_fixed_reference_not_previous_frame():
    gate = SolverMotionGate()
    decisions = [
        gate.evaluate(frame(angle, delta=0.04), mount_moving=False)
        for angle in (0, 0.04, 0.08, 0.12, 0.12)
    ]
    assert decisions == [False, False, False, True, False]


def test_interframe_repointing_without_moving_bit_invalidates_old_window():
    gate = SolverMotionGate()
    assert not gate.evaluate(frame(), mount_moving=False)
    assert gate.evaluate(frame(10), mount_moving=False)
    assert gate.reason == "field_displacement"
    assert not gate.evaluate(frame(10, moving=True), mount_moving=False)


def test_exposure_motion_resets_even_when_endpoint_returns_to_reference():
    gate = SolverMotionGate()
    gate.evaluate(frame(), mount_moving=False)
    assert gate.evaluate(frame(delta=0.2), mount_moving=False)
    assert gate.reason == "exposure_motion"


def test_motor_motion_remains_authoritative_without_imu_motion():
    gate = SolverMotionGate()
    assert gate.evaluate(frame(), mount_moving=True)
    assert gate.reason == "mount_motion"


@pytest.mark.parametrize("invalid", ["stale", "uncalibrated", "unhealthy", "zero"])
def test_unusable_orientation_cannot_override_moving_bit(invalid):
    gate = SolverMotionGate()
    metadata = frame(moving=True)
    imu = metadata["imu"]
    if invalid == "stale":
        imu.timestamp = 1.0
    elif invalid == "uncalibrated":
        imu.status = 0
    elif invalid == "unhealthy":
        imu.sensor_healthy = False
    else:
        imu.quat = quaternion.quaternion(0, 0, 0, 0)
    assert gate.evaluate(metadata, mount_moving=False)
    assert gate.reason == "unverified_imu_motion"


@pytest.mark.parametrize("delta", ["bad", float("nan"), float("inf")])
def test_invalid_exposure_delta_stays_conservative(delta):
    gate = SolverMotionGate()
    assert gate.evaluate(frame(delta=delta), mount_moving=False)


def test_quaternion_sign_flip_does_not_invalidate_same_field():
    gate = SolverMotionGate()
    metadata = frame(30)
    assert not gate.evaluate(metadata, mount_moving=False)
    metadata["imu"].quat = -metadata["imu"].quat
    metadata["imu"].moving = True
    assert not gate.evaluate(metadata, mount_moving=False)
    assert gate.displacement_deg == pytest.approx(0, abs=1e-10)


def test_no_imu_remains_supported():
    assert not SolverMotionGate().evaluate({"imu_delta": 0.0}, mount_moving=False)


def test_tiny_vibration_keeps_temporal_preprocessing_window():
    from PiFinder.mf_star_only_preprocess import (
        MFStarOnlyConfig,
        MFStarOnlyAccumulator,
    )

    gate = SolverMotionGate()
    preprocessor = MFStarOnlyAccumulator(
        MFStarOnlyConfig(accelerator="cpu", reduction_backend="numpy")
    )
    raw = np.full((128, 128), 100, dtype=np.uint16)
    raw[64, 64] = 1000
    try:
        for index, angle in enumerate([0, 0.005, -0.01, 0.015, 0]):
            if gate.evaluate(frame(angle, moving=True, delta=0.03), mount_moving=False):
                preprocessor.reset()
                continue
            preprocessor.add(raw, saturation_level=4095, fingerprint="same_optics")
            assert preprocessor.frame_count == index + 1
        assert preprocessor.frame_count == 5
        assert gate.evaluate(frame(1.0, moving=True), mount_moving=False)
        preprocessor.reset()
        assert not gate.evaluate(frame(1.0), mount_moving=False)
        preprocessor.add(raw, saturation_level=4095, fingerprint="same_optics")
        assert preprocessor.frame_count == 1
    finally:
        preprocessor.close()
