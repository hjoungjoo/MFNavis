import datetime
import time
from types import SimpleNamespace

import pytest

from PiFinder.pointing_coordinate_service import (
    CoordinateHealth,
    CoordinateSample,
    PointingCoordinateService,
    SOURCE_FUSED,
    SOURCE_IMU,
    SOURCE_MOUNT,
    SOURCE_PIFINDER_IMU_ESTIMATE,
    SOURCE_SOLVE,
    SOURCE_UNAVAILABLE,
)


pytestmark = pytest.mark.unit


class DummySolution:
    def __init__(
        self,
        ra_deg,
        dec_deg,
        has_pointing=True,
        solve_source="CAM",
        has_plate_anchor=False,
        alt_deg=None,
        az_deg=None,
        estimate_time=1000.0,
    ):
        aligned_solve = (
            SimpleNamespace(RA=ra_deg, Dec=dec_deg) if has_plate_anchor else None
        )
        self.pointing = SimpleNamespace(
            aligned=SimpleNamespace(
                solve=aligned_solve,
                estimate=SimpleNamespace(RA=ra_deg, Dec=dec_deg),
            )
        )
        self.estimate_time = estimate_time
        self.Alt = alt_deg
        self.Az = az_deg
        self.solve_source = solve_source
        self.last_solve_success = 900.0 if has_plate_anchor else None
        self._has_pointing = has_pointing

    def has_pointing(self):
        return self._has_pointing


class DummyState:
    def __init__(self, solution=None):
        self._solution = solution

    def solution(self):
        return self._solution

    def imu(self):
        return None

    def location(self):
        return None


def disabled_config(option, default=None):
    if option == "skysafari_imu_fallback":
        return False
    return default


def mount_enabled_config(option, default=None):
    if option == "mount_control":
        return True
    return disabled_config(option, default)


def test_solved_pointing_overrides_synced_mount_readback():
    service = PointingCoordinateService()
    dt = datetime.datetime(2026, 7, 1, 12, tzinfo=datetime.timezone.utc)

    state = service.current_state(
        DummyState(DummySolution(120.0, 20.0)),
        dt,
        config_get=mount_enabled_config,
        mount_status_provider=lambda: {
            "ra": 50.0,
            "dec": 10.0,
            "coordinate_sync": {"active": True, "ra": 50.0, "dec": 10.0},
        },
    )

    assert state.current.source == SOURCE_SOLVE
    assert state.current.valid is True
    assert state.mount.valid is True
    assert state.mount.aligned is True


def test_update_state_publishes_latest_coordinate_state():
    service = PointingCoordinateService()
    dt = datetime.datetime(2026, 7, 1, 12, tzinfo=datetime.timezone.utc)

    assert service.get_state() is None

    state = service.update_state(
        DummyState(DummySolution(120.0, 20.0)),
        dt,
        config_get=disabled_config,
    )

    assert service.get_state() is state
    assert service.get_state().current.source == SOURCE_SOLVE

    service.clear_state()

    assert service.get_state() is None


def _camera_sample(
    ra_deg,
    dec_deg,
    timestamp,
    *,
    alt_deg=None,
    az_deg=None,
    solve_source="CAM",
):
    return CoordinateSample(
        ra_deg=ra_deg,
        dec_deg=dec_deg,
        alt_deg=alt_deg,
        az_deg=az_deg,
        source=SOURCE_SOLVE,
        quality="high",
        timestamp=timestamp,
        valid=True,
        metadata={"solve_source": solve_source},
    )


def test_solve_average_starts_after_five_independent_camera_solves():
    service = PointingCoordinateService()
    imu = CoordinateSample.invalid(SOURCE_IMU, "test")

    outputs = []
    for timestamp, ra_deg in enumerate((100.0, 100.1, 99.9, 100.05, 99.95), start=1):
        outputs.append(
            service._stabilize_solved_sample(
                _camera_sample(ra_deg, 20.0, float(timestamp)), imu
            )
        )
    averaged = outputs[-1]

    assert all(output.metadata.get("stabilized") is None for output in outputs[:4])
    assert averaged.metadata["stabilized"] is True
    assert averaged.metadata["stabilization_window"] == 5
    assert averaged.metadata["stabilization_frame"] == "equatorial"
    assert averaged.radec() == pytest.approx((100.0, 20.0000117), abs=1e-5)


def test_solve_average_handles_ra_wrap_as_a_spherical_mean():
    service = PointingCoordinateService()
    imu = CoordinateSample.invalid(SOURCE_IMU, "test")

    for timestamp, ra_deg in enumerate((359.9, 0.0, 0.1, 359.95, 0.05), start=1):
        averaged = service._stabilize_solved_sample(
            _camera_sample(ra_deg, 10.0, float(timestamp)), imu
        )

    assert averaged.ra_deg == pytest.approx(0.0, abs=1e-8)
    assert averaged.dec_deg == pytest.approx(10.00001, abs=1e-5)


def test_failed_solve_uses_existing_average_without_adding_duplicate():
    service = PointingCoordinateService()
    imu = CoordinateSample.invalid(SOURCE_IMU, "test")
    for timestamp, ra_deg in enumerate((10.0, 10.1, 9.9, 10.05, 9.95), start=1):
        service._stabilize_solved_sample(
            _camera_sample(ra_deg, 30.0, float(timestamp)), imu
        )

    retained = service._stabilize_solved_sample(
        _camera_sample(9.95, 30.0, 5.0, solve_source="CAM_FAILED"), imu
    )

    assert retained.metadata["stabilization_window"] == 5
    assert len(service._solve_average_samples) == 5
    assert retained.ra_deg == pytest.approx(10.0, abs=1e-5)


def test_imu_motion_bypasses_and_resets_solve_average():
    service = PointingCoordinateService()
    stationary_imu = CoordinateSample.invalid(SOURCE_IMU, "test")
    for timestamp, ra_deg in enumerate((10.0, 10.1, 9.9, 10.05, 9.95), start=1):
        service._stabilize_solved_sample(
            _camera_sample(ra_deg, 30.0, float(timestamp)), stationary_imu
        )
    moving_imu = CoordinateSample(
        source=SOURCE_IMU,
        valid=True,
        metadata={"moving": True},
    )
    raw = _camera_sample(25.0, 35.0, 4.0)

    output = service._stabilize_solved_sample(raw, moving_imu)

    assert output is raw
    assert service._solve_average_samples == []


def test_large_confirmed_coordinate_change_resets_solve_average():
    service = PointingCoordinateService()
    imu = CoordinateSample.invalid(SOURCE_IMU, "test")
    for timestamp, ra_deg in enumerate((10.0, 10.01, 9.99, 10.005, 9.995), start=1):
        service._stabilize_solved_sample(
            _camera_sample(ra_deg, 30.0, float(timestamp)), imu
        )

    moved = _camera_sample(11.0, 30.0, 4.0)
    output = service._stabilize_solved_sample(moved, imu)

    assert output is moved
    assert service._solve_average_samples == [moved]


def test_solve_average_selects_horizontal_frame_for_fixed_camera(monkeypatch):
    service = PointingCoordinateService()
    service._fusion_context = {
        "dt": object(),
        "location": SimpleNamespace(lat=1.0, lon=2.0, altitude=3.0),
    }
    monkeypatch.setattr(
        "PiFinder.pointing_coordinate_service.sf_utils.set_location",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "PiFinder.pointing_coordinate_service.sf_utils.observed_altaz_to_radec",
        lambda alt, az, _dt: (200.0 + az, 30.0 + alt),
    )
    imu = CoordinateSample.invalid(SOURCE_IMU, "test")

    for timestamp, values in enumerate(
        (
            (100.0, 45.0, 180.000),
            (100.1, 45.001, 180.001),
            (100.2, 44.999, 179.999),
            (100.3, 45.0005, 180.0005),
            (100.4, 44.9995, 179.9995),
        ),
        start=1,
    ):
        ra_deg, alt_deg, az_deg = values
        averaged = service._stabilize_solved_sample(
            _camera_sample(
                ra_deg,
                20.0,
                float(timestamp),
                alt_deg=alt_deg,
                az_deg=az_deg,
            ),
            imu,
        )

    assert averaged.metadata["stabilization_frame"] == "horizontal"
    assert averaged.alt_deg == pytest.approx(45.0, abs=1e-6)
    assert averaged.az_deg == pytest.approx(180.0, abs=1e-6)
    assert averaged.radec() == pytest.approx((20.0, 75.0), abs=1e-6)


def test_solve_average_keeps_selected_frame_until_reset():
    service = PointingCoordinateService()
    service._solve_average_frame = "horizontal"

    selected = service._choose_solve_average_frame(
        equatorial_scatter=0.0001,
        horizontal_scatter=1.0,
    )

    assert selected == "horizontal"


def test_horizontal_solve_average_returns_to_original_icrs_frame():
    from PiFinder.calc_utils import sf_utils

    service = PointingCoordinateService()
    dt = datetime.datetime(2026, 9, 8, 13, 33, tzinfo=datetime.timezone.utc)
    location = SimpleNamespace(lat=37.52704, lon=127.10936, altitude=30.0)
    service._fusion_context = {"dt": dt, "location": location}
    service._solve_average_frame = "horizontal"
    sf_utils.set_location(location.lat, location.lon, location.altitude)
    imu = CoordinateSample.invalid(SOURCE_IMU, "test")
    for index, delta in enumerate((-0.0002, -0.0001, 0.0, 0.0001, 0.0002)):
        ra, dec = 13.2 + delta, 2.7533333333333334
        alt, az = sf_utils.radec_to_altaz(ra, dec, dt)
        averaged = service._stabilize_solved_sample(
            _camera_sample(ra, dec, float(index), alt_deg=alt, az_deg=az), imu
        )
    # The former apparent-of-date inverse produced RA 13.5303, Dec 2.9211:
    # about 22 arcmin despite a stationary, precise ICRS input.
    assert averaged.metadata["stabilization_frame"] == "horizontal"
    assert averaged.ra_deg == pytest.approx(13.2, abs=0.1 / 3600)
    assert averaged.dec_deg == pytest.approx(2.7533333333333334, abs=0.1 / 3600)


def test_unanchored_imu_solution_is_not_treated_as_trusted_pointing():
    service = PointingCoordinateService()
    dt = datetime.datetime(2026, 7, 1, 12, tzinfo=datetime.timezone.utc)

    state = service.current_state(
        DummyState(DummySolution(120.0, 20.0, solve_source="IMU")),
        dt,
        config_get=disabled_config,
    )

    assert state.solved.valid is False
    assert "no plate-solve anchor" in state.solved.reason
    assert state.current.source == SOURCE_UNAVAILABLE


def test_anchored_imu_solution_can_supply_pifinder_estimate():
    service = PointingCoordinateService()
    dt = datetime.datetime(2026, 7, 1, 12, tzinfo=datetime.timezone.utc)

    state = service.current_state(
        DummyState(
            DummySolution(
                120.0,
                20.0,
                solve_source="IMU",
                has_plate_anchor=True,
            )
        ),
        dt,
        config_get=disabled_config,
    )

    assert state.solved.valid is True
    assert state.current.source == SOURCE_PIFINDER_IMU_ESTIMATE


def test_anchored_failed_solve_keeps_last_pifinder_estimate():
    service = PointingCoordinateService()
    dt = datetime.datetime(2026, 7, 1, 12, tzinfo=datetime.timezone.utc)

    state = service.current_state(
        DummyState(
            DummySolution(
                120.0,
                20.0,
                solve_source="CAM_FAILED",
                has_plate_anchor=True,
            )
        ),
        dt,
        config_get=disabled_config,
    )

    assert state.solved.valid is True
    assert state.solved.metadata["has_plate_anchor"] is True
    assert state.current.source == SOURCE_PIFINDER_IMU_ESTIMATE
    assert state.current.radec() == pytest.approx((120.0, 20.0))


def test_unanchored_failed_solve_is_not_trusted():
    service = PointingCoordinateService()
    dt = datetime.datetime(2026, 7, 1, 12, tzinfo=datetime.timezone.utc)

    state = service.current_state(
        DummyState(DummySolution(120.0, 20.0, solve_source="CAM_FAILED")),
        dt,
        config_get=disabled_config,
    )

    assert state.solved.valid is False
    assert "no plate-solve anchor" in state.solved.reason
    assert state.current.source == SOURCE_UNAVAILABLE


def test_unaligned_imuplus_is_not_used_as_absolute_fallback():
    service = PointingCoordinateService()
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    mount = CoordinateSample.invalid(SOURCE_MOUNT, "test")
    imu = CoordinateSample(
        ra_deg=250.0,
        dec_deg=35.0,
        source=SOURCE_IMU,
        valid=True,
        metadata={"uses_magnetometer": False, "alignment_applied": False},
    )
    health = CoordinateHealth()

    current = service._select_current(solved, imu, mount, health)

    assert current.source == SOURCE_UNAVAILABLE
    assert any("absolute IMU fallback unavailable" in item for item in health.warnings)


@pytest.mark.parametrize(
    "metadata",
    [
        {"uses_magnetometer": True, "alignment_applied": False},
        {"uses_magnetometer": False, "alignment_applied": True},
    ],
)
def test_absolute_or_aligned_imu_can_supply_fallback(metadata):
    service = PointingCoordinateService()
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    mount = CoordinateSample.invalid(SOURCE_MOUNT, "test")
    imu = CoordinateSample(
        ra_deg=250.0,
        dec_deg=35.0,
        source=SOURCE_IMU,
        valid=True,
        metadata=metadata,
    )

    current = service._select_current(solved, imu, mount, CoordinateHealth())

    assert current.source == SOURCE_IMU
    assert current.radec() == pytest.approx((250.0, 35.0))


def test_unsynced_mount_readback_is_not_used_as_primary_coordinate():
    service = PointingCoordinateService()
    dt = datetime.datetime(2026, 7, 1, 12, tzinfo=datetime.timezone.utc)

    state = service.current_state(
        DummyState(),
        dt,
        config_get=mount_enabled_config,
        mount_status_provider=lambda: {"ra": 50.0, "dec": 10.0, "updated": 1000.0},
    )

    assert state.mount.valid is True
    assert state.mount.aligned is False
    assert state.health.mount_pre_alignment_only is True
    assert state.current.source == SOURCE_UNAVAILABLE
    assert state.current.valid is False


def test_parked_mount_readback_is_excluded_from_coordinate_candidates():
    service = PointingCoordinateService()
    dt = datetime.datetime(2026, 7, 1, 12, tzinfo=datetime.timezone.utc)

    state = service.current_state(
        DummyState(),
        dt,
        config_get=mount_enabled_config,
        mount_status_provider=lambda: {
            "ra": 50.0,
            "dec": 10.0,
            "updated": 1000.0,
            "park_state": "Parked",
            "state": "connected",
        },
    )

    assert state.mount.valid is False
    assert "parked" in state.mount.reason
    assert state.current.source == SOURCE_UNAVAILABLE


def test_synced_mount_readback_can_supply_no_solve_coordinate():
    service = PointingCoordinateService()
    dt = datetime.datetime(2026, 7, 1, 12, tzinfo=datetime.timezone.utc)

    state = service.current_state(
        DummyState(),
        dt,
        config_get=mount_enabled_config,
        mount_status_provider=lambda: {
            "ra": 50.0,
            "dec": 10.0,
            "updated": 1000.0,
            "coordinate_sync": {
                "active": True,
                "synced": True,
                "ra": 50.0,
                "dec": 10.0,
            },
        },
    )

    assert state.current.source == SOURCE_MOUNT
    assert state.current.radec() == pytest.approx((50.0, 10.0))
    assert state.mount.aligned is True


def test_synced_mount_uses_imu_delta_after_anchor_not_absolute_imu_position():
    service = PointingCoordinateService()
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    mount = CoordinateSample(
        ra_deg=10.0,
        dec_deg=10.0,
        source=SOURCE_MOUNT,
        valid=True,
        aligned=True,
        timestamp=100.0,
        metadata={"coordinate_sync": {"synced_at": 1.0}},
    )
    imu_anchor = CoordinateSample(
        ra_deg=100.0,
        dec_deg=20.0,
        source=SOURCE_IMU,
        valid=True,
        timestamp=100.0,
    )
    health = CoordinateHealth()

    first = service._select_current(solved, imu_anchor, mount, health)

    assert first.source == SOURCE_FUSED
    assert first.radec() == pytest.approx((10.0, 10.0))

    imu_moved = CoordinateSample(
        ra_deg=110.0,
        dec_deg=25.0,
        source=SOURCE_IMU,
        valid=True,
        timestamp=101.0,
    )
    health = CoordinateHealth()
    moved = service._select_current(solved, imu_moved, mount, health)

    assert moved.source == SOURCE_FUSED
    moved_ra, moved_dec = moved.radec()
    assert moved_dec > 14.0
    assert 18.0 < moved_ra < 22.0


def test_mount_heartbeat_without_position_change_does_not_clear_imu_delta():
    service = PointingCoordinateService()
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    mount = CoordinateSample(
        ra_deg=10.0,
        dec_deg=10.0,
        source=SOURCE_MOUNT,
        valid=True,
        aligned=True,
        timestamp=100.0,
        metadata={"coordinate_sync": {"synced_at": 1.0}},
    )
    imu_anchor = CoordinateSample(
        ra_deg=100.0,
        dec_deg=20.0,
        source=SOURCE_IMU,
        valid=True,
        timestamp=100.0,
    )
    service._select_current(solved, imu_anchor, mount, CoordinateHealth())

    heartbeat_mount = CoordinateSample(
        ra_deg=10.0,
        dec_deg=10.0,
        source=SOURCE_MOUNT,
        valid=True,
        aligned=True,
        timestamp=105.0,
        metadata={"coordinate_sync": {"synced_at": 1.0}},
    )
    imu_moved = CoordinateSample(
        ra_deg=110.0,
        dec_deg=25.0,
        source=SOURCE_IMU,
        valid=True,
        timestamp=105.0,
    )

    moved = service._select_current(
        solved, imu_moved, heartbeat_mount, CoordinateHealth()
    )

    assert moved.radec()[1] > 14.0


def test_synced_mount_motion_uses_mount_readback_until_stationary():
    service = PointingCoordinateService()
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    slewing_mount = CoordinateSample(
        ra_deg=10.0,
        dec_deg=10.0,
        source=SOURCE_MOUNT,
        valid=True,
        aligned=True,
        timestamp=100.0,
        metadata={
            "state": "slewing",
            "goto_motion_active": True,
            "coordinate_sync": {"synced_at": 1.0},
        },
    )
    imu_moved = CoordinateSample(
        ra_deg=120.0,
        dec_deg=40.0,
        source=SOURCE_IMU,
        valid=True,
        timestamp=100.0,
    )
    health = CoordinateHealth()

    current = service._select_current(solved, imu_moved, slewing_mount, health)

    assert current.source == SOURCE_MOUNT
    assert current.radec() == pytest.approx((10.0, 10.0))
    assert current.metadata["motion_active"] is True
    assert "mount motion/settle active" in health.warnings[0]


def test_synced_manual_motion_uses_mount_readback_until_stationary():
    service = PointingCoordinateService()
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    manual_mount = CoordinateSample(
        ra_deg=20.0,
        dec_deg=30.0,
        source=SOURCE_MOUNT,
        valid=True,
        aligned=True,
        timestamp=100.0,
        metadata={
            "state": "manual_motion",
            "manual_motion_direction": "east",
            "coordinate_sync": {"synced_at": 1.0},
        },
    )
    imu_moved = CoordinateSample(
        ra_deg=120.0,
        dec_deg=40.0,
        source=SOURCE_IMU,
        valid=True,
        timestamp=100.0,
    )
    health = CoordinateHealth()

    current = service._select_current(solved, imu_moved, manual_mount, health)

    assert current.source == SOURCE_MOUNT
    assert current.radec() == pytest.approx((20.0, 30.0))
    assert current.metadata["motion_active"] is True
    assert "mount motion/settle active" in health.warnings[0]


def test_common_readback_priority_overrides_legacy_motion_state():
    service = PointingCoordinateService()
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    mount = CoordinateSample(
        ra_deg=20.0,
        dec_deg=30.0,
        source=SOURCE_MOUNT,
        valid=True,
        aligned=True,
        timestamp=100.0,
        metadata={
            "state": "connected",
            "mount_motion_active": False,
            "mount_motion_type": "goto_refine_settle",
            "mount_readback_priority": True,
            "coordinate_sync": {"synced_at": 1.0},
        },
    )
    imu_moved = CoordinateSample(
        ra_deg=120.0,
        dec_deg=40.0,
        source=SOURCE_IMU,
        valid=True,
        timestamp=100.0,
    )
    health = CoordinateHealth()

    current = service._select_current(solved, imu_moved, mount, health)

    assert current.source == SOURCE_MOUNT
    assert current.radec() == pytest.approx((20.0, 30.0))
    assert current.metadata["motion_active"] is False
    assert current.metadata["readback_priority"] is True
    assert "mount motion/settle active" in health.warnings[0]


def test_synced_mount_reanchors_imu_delta_after_motion_stops():
    service = PointingCoordinateService()
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    slewing_mount = CoordinateSample(
        ra_deg=10.0,
        dec_deg=10.0,
        source=SOURCE_MOUNT,
        valid=True,
        aligned=True,
        timestamp=100.0,
        metadata={
            "state": "slewing",
            "goto_motion_active": True,
            "coordinate_sync": {"synced_at": 1.0},
        },
    )
    imu_during_motion = CoordinateSample(
        ra_deg=120.0,
        dec_deg=40.0,
        source=SOURCE_IMU,
        valid=True,
        timestamp=100.0,
    )
    service._select_current(
        solved, imu_during_motion, slewing_mount, CoordinateHealth()
    )

    stopped_mount = CoordinateSample(
        ra_deg=11.0,
        dec_deg=11.0,
        source=SOURCE_MOUNT,
        valid=True,
        aligned=True,
        timestamp=105.0,
        metadata={"state": "connected", "coordinate_sync": {"synced_at": 1.0}},
    )
    imu_at_stop = CoordinateSample(
        ra_deg=130.0,
        dec_deg=45.0,
        source=SOURCE_IMU,
        valid=True,
        timestamp=105.0,
    )
    current = service._select_current(
        solved, imu_at_stop, stopped_mount, CoordinateHealth()
    )

    assert current.source == SOURCE_MOUNT

    service._mount_motion_hold_until = time.monotonic() - 0.1
    current = service._select_current(
        solved, imu_at_stop, stopped_mount, CoordinateHealth()
    )

    assert current.source == SOURCE_FUSED
    assert current.radec() == pytest.approx((11.0, 11.0))


def test_mount_readback_change_extends_imu_delta_hold_after_status_is_connected():
    service = PointingCoordinateService()
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    service._last_mount_motion_radec = (10.0, 10.0)
    service._mount_motion_hold_until = time.monotonic() - 0.1
    mount_moved = CoordinateSample(
        ra_deg=10.1,
        dec_deg=10.0,
        source=SOURCE_MOUNT,
        valid=True,
        aligned=True,
        timestamp=105.0,
        metadata={"state": "connected", "coordinate_sync": {"synced_at": 1.0}},
    )
    imu = CoordinateSample(
        ra_deg=120.0,
        dec_deg=40.0,
        source=SOURCE_IMU,
        valid=True,
        timestamp=105.0,
    )
    health = CoordinateHealth()

    current = service._select_current(solved, imu, mount_moved, health)

    assert current.source == SOURCE_MOUNT
    assert current.radec() == pytest.approx((10.1, 10.0))
    assert service._mount_motion_hold_until > time.monotonic()


def test_imu_altaz_smoothing_damps_small_jitter_and_resets_on_large_motion():
    service = PointingCoordinateService()

    alt, az, state, delta = service._smooth_imu_altaz(10.0, 20.0)
    assert (alt, az, delta) == pytest.approx((10.0, 20.0, 0.0))
    assert state == "initial"

    alt, az, state, delta = service._smooth_imu_altaz(10.1, 20.1)
    assert state == "smoothed_small_jitter"
    assert 10.0 < alt < 10.1
    assert 20.0 < az < 20.1
    assert delta > 0.0

    alt, az, state, delta = service._smooth_imu_altaz(18.0, 40.0)
    assert state == "reset_large_motion"
    assert (alt, az) == pytest.approx((18.0, 40.0))
    assert delta >= 5.0


def test_multipoint_mount_sync_status_marks_mount_as_aligned():
    service = PointingCoordinateService()

    sample = service.mount_sample_from_status(
        {
            "ra": 42.0,
            "dec": -5.0,
            "multipoint_align": {
                "pifinder_mount_synced": True,
                "completed_points": 0,
            },
        }
    )

    assert sample.valid is True
    assert sample.aligned is True


def test_multipoint_completed_points_without_sync_do_not_align_mount():
    service = PointingCoordinateService()

    sample = service.mount_sample_from_status(
        {
            "ra": 42.0,
            "dec": -5.0,
            "multipoint_align": {
                "active": False,
                "completed_points": 3,
                "pifinder_mount_synced": False,
            },
        }
    )

    assert sample.valid is True
    assert sample.aligned is False


def _fused_mount(ra_deg, dec_deg, synced_at=1.0, **extra_metadata):
    metadata = {"state": "connected", "coordinate_sync": {"synced_at": synced_at}}
    metadata.update(extra_metadata)
    return CoordinateSample(
        ra_deg=ra_deg,
        dec_deg=dec_deg,
        source=SOURCE_MOUNT,
        valid=True,
        aligned=True,
        timestamp=100.0,
        metadata=metadata,
    )


def _fused_imu(ra_deg, dec_deg):
    return CoordinateSample(
        ra_deg=ra_deg,
        dec_deg=dec_deg,
        source=SOURCE_IMU,
        valid=True,
        timestamp=100.0,
    )


def _build_disturbance_offset(service, monkeypatch, clock):
    """Push the IMU fast (5 deg/s) so a +5 deg dec offset is applied."""
    import PiFinder.pointing_coordinate_service as pcs

    monkeypatch.setattr(pcs.time, "monotonic", lambda: clock[0])
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")

    first = service._select_current(
        solved, _fused_imu(100.0, 20.0), _fused_mount(10.0, 10.0), CoordinateHealth()
    )
    assert first.source == SOURCE_FUSED
    assert first.radec() == pytest.approx((10.0, 10.0))

    clock[0] += 1.0
    pushed = service._select_current(
        solved, _fused_imu(100.0, 25.0), _fused_mount(10.0, 10.0), CoordinateHealth()
    )
    assert pushed.source == SOURCE_FUSED
    assert pushed.radec()[1] == pytest.approx(15.0)
    return solved


def test_disturbance_offset_holds_after_scope_stops(monkeypatch):
    service = PointingCoordinateService()
    clock = [1000.0]
    solved = _build_disturbance_offset(service, monkeypatch, clock)

    # Scope stationary for 5 minutes: the offset must not decay back.
    for _ in range(5):
        clock[0] += 60.0
        held = service._select_current(
            solved,
            _fused_imu(100.0, 25.0),
            _fused_mount(10.0, 10.0),
            CoordinateHealth(),
        )

    assert held.source == SOURCE_FUSED
    assert held.radec()[1] == pytest.approx(15.0)
    assert held.metadata["imu_delta_gate"] == "hold"


def test_disturbance_offset_survives_mount_motion(monkeypatch):
    service = PointingCoordinateService()
    clock = [1000.0]
    solved = _build_disturbance_offset(service, monkeypatch, clock)

    # Mount slews itself; the IMU sees that motion too. Readback has priority
    # during the slew, but the offset must survive it.
    clock[0] += 1.0
    slewing = service._select_current(
        solved,
        _fused_imu(101.0, 26.0),
        _fused_mount(11.0, 10.0, goto_motion_active=True, state="slewing"),
        CoordinateHealth(),
    )
    assert slewing.source == SOURCE_MOUNT
    assert slewing.radec() == pytest.approx((11.0, 10.0))

    # Motion over, hold window expired: fused = live readback + held offset,
    # and the mount-driven IMU movement was not double-counted.
    clock[0] += 10.0
    service._mount_motion_hold_until = clock[0] - 0.1
    resumed = service._select_current(
        solved,
        _fused_imu(101.0, 26.0),
        _fused_mount(11.0, 10.0),
        CoordinateHealth(),
    )
    assert resumed.source == SOURCE_FUSED
    assert resumed.radec()[1] == pytest.approx(15.0)
    assert resumed.radec()[0] == pytest.approx(11.0)


def test_fused_base_follows_live_readback_without_losing_offset(monkeypatch):
    service = PointingCoordinateService()
    clock = [1000.0]
    solved = _build_disturbance_offset(service, monkeypatch, clock)

    # A tiny readback move (guide pulse, below the motion-detect threshold)
    # shifts the fused base directly; the offset stays applied.
    clock[0] += 1.0
    nudged = service._select_current(
        solved,
        _fused_imu(100.0, 25.0),
        _fused_mount(10.004, 10.0),
        CoordinateHealth(),
    )
    assert nudged.source == SOURCE_FUSED
    assert nudged.radec()[0] == pytest.approx(10.004)
    assert nudged.radec()[1] == pytest.approx(15.0)


def test_sync_clears_disturbance_offset(monkeypatch):
    service = PointingCoordinateService()
    clock = [1000.0]
    solved = _build_disturbance_offset(service, monkeypatch, clock)

    # A mount sync re-establishes the frame. The sync jumped the readback, so
    # the motion hold shows the readback first; once it expires the fused
    # coordinate must be the plain readback — the offset is cleared, not held.
    clock[0] += 1.0
    synced = service._select_current(
        solved,
        _fused_imu(100.0, 25.0),
        _fused_mount(12.0, 14.9, synced_at=2.0),
        CoordinateHealth(),
    )
    assert synced.radec() == pytest.approx((12.0, 14.9))

    clock[0] += 10.0
    service._mount_motion_hold_until = clock[0] - 0.1
    settled = service._select_current(
        solved,
        _fused_imu(100.0, 25.0),
        _fused_mount(12.0, 14.9, synced_at=2.0),
        CoordinateHealth(),
    )
    assert settled.source == SOURCE_FUSED
    assert settled.radec() == pytest.approx((12.0, 14.9))


def test_gate_hysteresis_captures_weak_slip_head_and_tail(monkeypatch):
    """Reproduces the hardware-captured weak stall-slip pattern (2026-07-16):
    rates ramp 0.033 -> 0.06 -> 0.02 -> 0.01 deg/s. With enter=0.03/exit=0.015
    the episode accumulates from the first 0.033 tick through the 0.02 tail,
    and releases at 0.01."""
    import PiFinder.pointing_coordinate_service as pcs

    service = PointingCoordinateService()
    clock = [1000.0]
    monkeypatch.setattr(pcs.time, "monotonic", lambda: clock[0])
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")

    dec = 20.0
    mount = _fused_mount(10.0, 10.0)

    def tick(dec_step):
        nonlocal dec
        clock[0] += 1.0
        dec += dec_step
        return service._select_current(
            solved, _fused_imu(100.0, dec), mount, CoordinateHealth()
        )

    service._select_current(solved, _fused_imu(100.0, dec), mount, CoordinateHealth())

    assert tick(0.004).metadata["imu_delta_gate"] == "hold"  # artifact floor
    assert tick(0.033).metadata["imu_delta_gate"] == "fast_follow"  # enters
    assert tick(0.060).metadata["imu_delta_gate"] == "fast_follow"  # peak
    assert tick(0.020).metadata["imu_delta_gate"] == "fast_follow"  # tail kept
    released = tick(0.010)  # exits
    assert released.metadata["imu_delta_gate"] == "hold"
    assert tick(0.020).metadata["imu_delta_gate"] == "hold"  # below re-entry

    # Applied dec offset = 0.033 + 0.060 + 0.020 only.
    assert released.metadata["imu_delta_applied_dec"] == pytest.approx(0.113)
    assert released.radec()[1] == pytest.approx(10.0 + 0.113)


def _fused_imu_altaz(alt_deg, az_deg, dt):
    """IMU sample carrying raw alt/az metadata, radec derived for consistency."""
    from PiFinder.calc_utils import sf_utils

    ra_deg, dec_deg = sf_utils.altaz_to_radec(alt_deg, az_deg, dt)
    return CoordinateSample(
        ra_deg=ra_deg % 360.0,
        dec_deg=dec_deg,
        alt_deg=alt_deg,
        az_deg=az_deg,
        source=SOURCE_IMU,
        valid=True,
        timestamp=100.0,
        metadata={"raw_alt": alt_deg, "raw_az": az_deg},
    )


def test_altaz_mount_hand_swing_applies_delta_in_altaz_space():
    """Regression for the 2026-07-19 hardware repro: on an alt/az mount an
    az-only hand swing must produce an az-only fused change, never the
    below-horizon dive of the old RA/Dec component transplant."""
    from PiFinder.calc_utils import sf_utils

    dt = datetime.datetime(2026, 7, 18, 15, 0, tzinfo=datetime.timezone.utc)
    location = SimpleNamespace(lat=37.527, lon=127.109, altitude=50.0)
    sf_utils.set_location(location.lat, location.lon, location.altitude)

    service = PointingCoordinateService()
    service._fusion_context = {
        "dt": dt,
        "location": location,
        "mount_type": "Alt/Az",
    }
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    # Mount synced somewhere in the west at alt ~20.
    mount_ra, mount_dec = sf_utils.altaz_to_radec(20.0, 275.0, dt)
    mount = _fused_mount(mount_ra % 360.0, mount_dec)

    anchor = service._select_current(
        solved, _fused_imu_altaz(15.0, 340.0, dt), mount, CoordinateHealth()
    )
    assert anchor.source == SOURCE_FUSED
    assert anchor.metadata["fusion_frame"] == "altaz"
    assert anchor.radec() == pytest.approx((mount_ra % 360.0, mount_dec))

    # Hand-swing az by +60 deg at constant alt (fast: consecutive ticks).
    moved = service._select_current(
        solved, _fused_imu_altaz(15.0, 40.0, dt), mount, CoordinateHealth()
    )
    assert moved.source == SOURCE_FUSED
    moved_ra, moved_dec = moved.radec()
    moved_alt, moved_az = sf_utils.radec_to_altaz(moved_ra, moved_dec, dt, atmos=False)
    # Az follows the swing; alt stays at the mount's altitude.
    assert moved_az == pytest.approx((275.0 + 60.0) % 360.0, abs=1.5)
    assert moved_alt == pytest.approx(20.0, abs=1.5)
    # The old transplant dove far below the horizon on exactly this move.
    assert moved_alt > 0.0


def test_eq_mount_delta_stays_component_additive_without_cos_rescale():
    """EQ mount FALLBACK path (no dt/location context, so the rotation
    tracker cannot run): the delta must be added component-wise with no
    cos(dec) transplant."""
    service = PointingCoordinateService()
    service._fusion_context = {
        "dt": None,
        "location": None,
        "mount_type": "Equatorial",
    }
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    mount = _fused_mount(10.0, 10.0)

    first = service._select_current(
        solved, _fused_imu(100.0, 60.0), mount, CoordinateHealth()
    )
    assert first.metadata["fusion_frame"] == "equatorial"
    assert first.radec() == pytest.approx((10.0, 10.0))

    moved = service._select_current(
        solved, _fused_imu(110.0, 60.0), mount, CoordinateHealth()
    )
    # +10 deg RA at the IMU must be +10 deg RA on the mount, dec unchanged.
    assert moved.radec() == pytest.approx((20.0, 10.0), abs=1e-6)


def test_altaz_rotation_tracker_survives_zenith_crossing():
    """The az-component tracker is singular at the zenith — a small physical
    motion over the top legitimately flips az by ~180, which component
    accumulation books as garbage. The rotation tracker must follow the swing
    over the zenith and land the fused pointing on the far side."""
    import math as m

    from PiFinder.calc_utils import sf_utils

    dt = datetime.datetime(2026, 7, 18, 15, 0, tzinfo=datetime.timezone.utc)
    location = SimpleNamespace(lat=37.527, lon=127.109, altitude=50.0)
    sf_utils.set_location(location.lat, location.lon, location.altitude)

    service = PointingCoordinateService()
    service._fusion_context = {
        "dt": dt,
        "location": location,
        "mount_type": "Alt/Az",
    }
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    mount_ra, mount_dec = sf_utils.altaz_to_radec(75.0, 0.0, dt)
    mount = _fused_mount(mount_ra % 360.0, mount_dec)

    # Hand swing along the meridian over the zenith: 20 deg of physical arc.
    path = [
        (80.0, 0.0),
        (85.0, 0.0),
        (89.0, 0.0),
        (89.0, 180.0),
        (85.0, 180.0),
        (80.0, 180.0),
    ]
    current = None
    for alt, az in path:
        current = service._select_current(
            solved, _fused_imu_altaz(alt, az, dt), mount, CoordinateHealth()
        )

    assert current is not None
    assert current.metadata["fusion_method"] == "rotation"
    ra, dec = current.radec()
    alt_f, az_f = sf_utils.radec_to_altaz(ra, dec, dt, atmos=False)
    # Mount at (75, az 0) carried 20 deg over the top must land at (85, az 180).
    sep = m.degrees(
        m.acos(
            max(
                -1.0,
                min(
                    1.0,
                    m.sin(m.radians(alt_f)) * m.sin(m.radians(85.0))
                    + m.cos(m.radians(alt_f))
                    * m.cos(m.radians(85.0))
                    * m.cos(m.radians(az_f - 180.0)),
                ),
            )
        )
    )
    assert sep < 2.0


def test_eq_mount_uses_rotation_tracker_and_survives_imu_yaw_offset():
    """EQ mount with full context must use the rotation tracker: the scalar
    RA/Dec path measures deltas in the IMU's own az frame, whose arbitrary
    imuplus yaw offset bends a pure polar-axis rotation into a large fake Dec
    component (measured on hardware: +15 RA read as +11.4 RA / +9.9 Dec at a
    -53 deg offset). The rotation tracker's psi0 mapping must recover the true
    motion."""
    from PiFinder.calc_utils import sf_utils

    dt = datetime.datetime(2026, 7, 18, 15, 0, tzinfo=datetime.timezone.utc)
    location = SimpleNamespace(lat=37.527, lon=127.109, altitude=50.0)
    sf_utils.set_location(location.lat, location.lon, location.altitude)

    service = PointingCoordinateService()
    service._fusion_context = {
        "dt": dt,
        "location": location,
        "mount_type": "Equatorial",
    }
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    yaw_off = -53.0  # arbitrary imuplus yaw frame offset

    # Mount synced: readback equals the scope's true pointing.
    alt0, az0 = 40.0, 200.0
    mount_ra, mount_dec = sf_utils.altaz_to_radec(alt0, az0, dt)
    mount = _fused_mount(mount_ra % 360.0, mount_dec)

    def imu_at(true_alt, true_az):
        # The IMU reports its own yaw-shifted azimuth for the true pointing.
        return _fused_imu_altaz(true_alt, (true_az + yaw_off) % 360.0, dt)

    first = service._select_current(
        solved, imu_at(alt0, az0), mount, CoordinateHealth()
    )
    assert first.metadata["fusion_method"] == "rotation"
    assert first.metadata["fusion_frame"] == "equatorial"
    assert first.radec() == pytest.approx((mount_ra % 360.0, mount_dec))

    # Physical hand rotation of +15 deg about the POLAR axis, in 5-deg steps:
    # true pointing RA increases, Dec constant.
    current = first
    for dra in (5.0, 10.0, 15.0):
        true_ra = (mount_ra + dra) % 360.0
        true_alt, true_az = sf_utils.radec_to_altaz(true_ra, mount_dec, dt, atmos=False)
        current = service._select_current(
            solved, imu_at(true_alt, true_az), mount, CoordinateHealth()
        )

    fused_ra, fused_dec = current.radec()
    assert _wrap(fused_ra - (mount_ra + 15.0)) == pytest.approx(0.0, abs=1.0)
    assert fused_dec == pytest.approx(mount_dec, abs=1.0)


def _tracking_freeze_setup(freeze_seconds):
    """Reproduce the 2026-07-22 hardware capture geometry: mount target-locked
    (constant readback RA/Dec) while tracking physically rotates the axes; the
    BNO055 output stays frozen for freeze_seconds while the fusion context's
    time advances 1 s per tick. Returns everything the snap/push phase needs."""
    from PiFinder.calc_utils import sf_utils

    t0 = datetime.datetime(2026, 7, 22, 14, 0, tzinfo=datetime.timezone.utc)
    location = SimpleNamespace(lat=37.527, lon=127.109, altitude=50.0)
    sf_utils.set_location(location.lat, location.lon, location.altitude)

    service = PointingCoordinateService()
    solved = CoordinateSample.invalid(SOURCE_SOLVE, "test")
    mount_ra, mount_dec = sf_utils.altaz_to_radec(30.0, 250.0, t0)
    mount = _fused_mount(mount_ra % 360.0, mount_dec)

    def tick(dt, imu_alt, imu_az):
        service._fusion_context = {
            "dt": dt,
            "location": location,
            "mount_type": "Alt/Az",
        }
        return service._select_current(
            solved, _fused_imu_altaz(imu_alt, imu_az, dt), mount, CoordinateHealth()
        )

    # IMU boresight with an arbitrary imuplus yaw offset (psi0 = +50 here).
    imu_alt0, imu_az0 = 30.0, 200.0
    anchor = tick(t0, imu_alt0, imu_az0)
    assert anchor.source == SOURCE_FUSED

    dt = t0
    for _ in range(freeze_seconds):
        dt = dt + datetime.timedelta(seconds=1)
        frozen = tick(dt, imu_alt0, imu_az0)
        assert frozen.metadata["imu_delta_gate"] in ("hold", "init")

    # Physical trajectory the scope actually followed while frozen.
    alt0, az0 = sf_utils.radec_to_altaz(mount_ra, mount_dec, t0, atmos=False)
    alt_now, az_now = sf_utils.radec_to_altaz(mount_ra, mount_dec, dt, atmos=False)
    moved_alt = alt_now - alt0
    moved_az = ((az_now - az0 + 180.0) % 360.0) - 180.0
    # The geometry must actually move enough to look like a hardware snap.
    assert abs(moved_alt) > 0.1

    return service, tick, dt, mount, (imu_alt0, imu_az0), (moved_alt, moved_az)


def test_tracking_catchup_snap_is_cancelled_not_booked_as_disturbance():
    """Regression for the 2026-07-22 hardware sawtooth: the BNO055 cannot
    resolve sidereal-rate tracking motion — it freezes, then snaps ~0.3 deg to
    catch up at 0.25-0.4 deg/s. The rate gate booked each snap as a physical
    push, stepping the fused coordinate off target until the guide re-aligned.
    The tracking budget must cancel the snap so fused stays on the readback."""
    _service, tick, dt, mount, (imu_alt0, imu_az0), (moved_alt, moved_az) = (
        _tracking_freeze_setup(180)
    )

    # Full catch-up snap in one tick (rate >> enter gate).
    snapped = tick(dt, imu_alt0 + moved_alt, imu_az0 + moved_az)
    assert snapped.metadata["imu_delta_gate"] == "fast_follow"
    # The snap must be recognized as tracking catch-up, not a disturbance:
    assert snapped.metadata["imu_track_cancelled_alt"] != 0.0
    ra, dec = snapped.radec()
    mount_ra, mount_dec = mount.radec()
    assert abs(((ra - mount_ra + 180.0) % 360.0) - 180.0) < 0.03
    assert abs(dec - mount_dec) < 0.03
    assert abs(snapped.metadata["imu_delta_applied_alt"]) < 0.03
    assert abs(snapped.metadata["imu_delta_applied_az"]) < 0.03


def test_real_push_during_tracking_still_registers():
    """The budget must only absorb tracking-consistent motion: a hand push
    against the tracking direction books its full magnitude even with a large
    pending catch-up budget."""
    _service, tick, dt, _mount, (imu_alt0, imu_az0), (moved_alt, _moved_az) = (
        _tracking_freeze_setup(120)
    )
    assert moved_alt < 0.0  # setting target: pending budget is negative in alt

    # Push the scope UP 2 deg — opposite the pending alt budget.
    pushed = tick(dt, imu_alt0 + 2.0, imu_az0)
    assert pushed.metadata["imu_delta_gate"] == "fast_follow"
    assert pushed.metadata["imu_delta_applied_alt"] == pytest.approx(2.0, abs=0.1)


def test_imu_wobble_episode_nets_to_zero_after_rebalance():
    """Regression for the 2026-07-23 hardware capture: a symmetric BNO055
    oscillation (0.07 deg/s wobble) had its tracking-direction half-cycles
    cancelled against the budget and its return half-cycles booked as a
    disturbance — rectifying ~zero net motion into a ~430 arcsec offset. The
    end-of-episode rebalance must settle bookings against the NET displacement
    so a wobble leaves the fused coordinate on the readback."""
    _service, tick, dt, mount, (imu_alt0, imu_az0), (moved_alt, _moved_az) = (
        _tracking_freeze_setup(120)
    )
    assert moved_alt < 0.0  # pending alt budget is negative (setting target)

    # Fast symmetric wobble: down (tracking direction), back up, down, back up.
    for wobble_alt in (-0.05, 0.0, -0.05, 0.0):
        wobbled = tick(dt, imu_alt0 + wobble_alt, imu_az0)
        assert wobbled.metadata["imu_delta_gate"] == "fast_follow"

    # One quiet tick ends the episode and triggers the rebalance.
    settled = tick(dt, imu_alt0, imu_az0)
    assert settled.metadata["imu_delta_gate"] == "hold"
    ra, dec = settled.radec()
    mount_ra, mount_dec = mount.radec()
    assert abs(((ra - mount_ra + 180.0) % 360.0) - 180.0) < 0.02
    assert abs(dec - mount_dec) < 0.02
    assert abs(settled.metadata["imu_delta_applied_alt"]) < 0.02
    assert abs(settled.metadata["imu_delta_applied_az"]) < 0.02
    # And the wrongly-consumed budget was given back (still roughly the
    # pre-wobble pending amount, i.e. clearly nonzero in the tracking sign).
    assert settled.metadata["imu_track_budget_alt"] < -0.1


def test_fusion_anchor_resets_when_observer_location_moves():
    service = PointingCoordinateService()
    here = SimpleNamespace(lat=37.5, lon=127.0, altitude=30.0)

    # First observation just records the site -- nothing to reset yet.
    service._mount_imu_anchor = {"sentinel": "anchor"}
    service._imu_delta_tracker = {"sentinel": "tracker"}
    service._reset_fusion_on_location_change(here)
    assert service._mount_imu_anchor == {"sentinel": "anchor"}
    assert service._fusion_location == (37.5, 127.0, 30.0)

    # GPS jitter (a few metres) must NOT reset the anchor.
    service._reset_fusion_on_location_change(
        SimpleNamespace(lat=37.50001, lon=127.00001, altitude=30.0)
    )
    assert service._mount_imu_anchor == {"sentinel": "anchor"}

    # A real relocation (~1.5 km) discards the anchor and tracker so they
    # rebuild for the new site.
    service._reset_fusion_on_location_change(
        SimpleNamespace(lat=37.51, lon=127.01, altitude=30.0)
    )
    assert service._mount_imu_anchor is None
    assert service._imu_delta_tracker is None
    assert service._fusion_location == (37.51, 127.01, 30.0)


def _wrap(delta):
    return ((delta + 180.0) % 360.0) - 180.0


def test_failed_solve_metadata_retains_camera_epochs_separate_from_imu_epoch():
    solution = DummySolution(
        120.0, 20.0, solve_source="CAM_FAILED", has_plate_anchor=True
    )
    solution.last_solve_attempt = 999.0
    solution.last_solve_success = 990.0
    sample = PointingCoordinateService().solved_sample(DummyState(solution), None)
    assert sample.timestamp == 1000.0
    assert sample.metadata["last_solve_attempt"] == 999.0
    assert sample.metadata["last_solve_success"] == 990.0
    assert sample.source == SOURCE_PIFINDER_IMU_ESTIMATE
