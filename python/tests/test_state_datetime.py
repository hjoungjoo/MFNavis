"""Regression tests for the civil-datetime contract on SharedStateObj.

These lock in the behaviour decided in ADR-0018: the civil datetime is stored
timezone-aware in UTC, normalised at the set_datetime() boundary, and read back
through utc_datetime() (UTC) / local_datetime() (the location's zone). The
status-screen bug they guard against ("UTC TM" equal to "LCL TM" at a non-UTC
location) is exactly the kind that only shows up on a non-UTC box.
"""

import datetime

import pytest
import pytz

import PiFinder.state as state_mod
from PiFinder.state import Location, SharedStateObj

UTC = datetime.timezone.utc

# A real place whose zone is unambiguous and offset from UTC in June (CEST,
# +02:00). set_location() derives the zone from lat/lon, so we pick coordinates
# rather than naming the zone directly.
BRUSSELS_LAT, BRUSSELS_LON = 50.85, 4.35


@pytest.fixture
def frozen_clock(monkeypatch):
    """Freeze the monotonic clock state.datetime() uses for drift.

    datetime() returns __datetime + monotonic elapsed time; pinning monotonic
    makes that drift exactly zero so stored == read-back and the assertions
    below are deterministic instead of off by the test's runtime.
    """
    monkeypatch.setattr(state_mod.time, "monotonic", lambda: 1_000.0)


def _state_at(lat=0.0, lon=0.0):
    """A SharedStateObj whose location resolves to the zone at (lat, lon)."""
    shared_state = SharedStateObj()
    location = Location()
    location.lat = lat
    location.lon = lon
    shared_state.set_location(location)
    return shared_state, location


@pytest.mark.unit
def test_naive_input_is_interpreted_as_utc(frozen_clock):
    shared_state = SharedStateObj()
    # Note: linter will refuse naive datetimes, we have to trick it
    # to get past it, make an 'acceptable' datetime then nuke the tzinfo
    shared_state.set_datetime(
        datetime.datetime(2024, 6, 28, 11, 0, 0, tzinfo=UTC).replace(tzinfo=None),
        force=True,
    )

    stored = shared_state.utc_datetime()
    assert stored.utcoffset() == datetime.timedelta(0)
    assert stored == datetime.datetime(2024, 6, 28, 11, 0, 0, tzinfo=UTC)


@pytest.mark.unit
def test_aware_local_input_is_converted_to_utc(frozen_clock):
    shared_state = SharedStateObj()
    # 13:00 in Brussels in June (CEST, +02:00) is the same instant as 11:00 UTC
    # Note: linter will refuse naive datetimes, we have to trick it
    # to get past it, make an 'acceptable' datetime then nuke the tzinfo

    local = pytz.timezone("Europe/Brussels").localize(
        datetime.datetime(2024, 6, 28, 13, 0, 0, tzinfo=UTC).replace(tzinfo=None)
    )

    shared_state.set_datetime(local, force=True)

    assert shared_state.utc_datetime().utcoffset() == datetime.timedelta(0)
    assert shared_state.utc_datetime() == datetime.datetime(
        2024, 6, 28, 11, 0, 0, tzinfo=UTC
    )
    # The fix lives in storage: bare datetime() must already be UTC, so the
    # status screen's datetime().time() cannot print a local clock as "UTC".
    # (utc_datetime() would re-convert and mask a set_datetime() regression.)
    assert shared_state.datetime().utcoffset() == datetime.timedelta(0)
    assert shared_state.datetime().time() == datetime.time(11, 0, 0)


@pytest.mark.unit
def test_utc_and_local_are_one_instant_in_two_zones(frozen_clock):
    # The status-screen regression: at a non-UTC location, UTC TM and LCL TM
    # are the same instant but must NOT print the same wall-clock time-of-day.
    shared_state, _ = _state_at(BRUSSELS_LAT, BRUSSELS_LON)

    shared_state.set_datetime(
        datetime.datetime(2024, 6, 28, 11, 0, 0, tzinfo=UTC), force=True
    )

    utc_dt = shared_state.utc_datetime()
    local_dt = shared_state.local_datetime()

    assert utc_dt == local_dt  # one absolute instant
    assert utc_dt.time().isoformat()[:8] == "11:00:00"
    assert local_dt.time().isoformat()[:8] == "13:00:00"
    assert utc_dt.time() != local_dt.time()


@pytest.mark.unit
def test_local_datetime_falls_back_to_utc_for_unresolvable_timezone(frozen_clock):
    # set_location() always resolves a valid zone from lat/lon, so to exercise
    # the defensive fallback we force an invalid zone on the stored location.
    shared_state, location = _state_at(BRUSSELS_LAT, BRUSSELS_LON)
    location.timezone = "Not/AZone"

    shared_state.set_datetime(
        datetime.datetime(2024, 6, 28, 11, 0, 0, tzinfo=UTC), force=True
    )

    assert shared_state.local_datetime().utcoffset() == datetime.timedelta(0)
    assert shared_state.local_datetime() == shared_state.utc_datetime()


@pytest.mark.unit
def test_set_location_settles_an_unresolvable_zone_to_utc(monkeypatch):
    """timezone_at() returning None must not reach the stored Location.

    Location.timezone is Optional and pytz.timezone(None) raises, so a raw
    None would turn every reader into a guard -- and crash the manual
    time-entry callbacks, which slice and localise it. UTC is already the
    documented fallback for an unknown zone, so set_location settles it there
    and the field stays a usable zone name.
    """
    monkeypatch.setattr(
        state_mod.TimezoneFinder, "timezone_at", lambda self, **kwargs: None
    )

    shared_state, location = _state_at(BRUSSELS_LAT, BRUSSELS_LON)

    assert location.timezone == "UTC"
    assert shared_state.location().timezone == "UTC"


@pytest.mark.unit
def test_accessors_return_none_when_datetime_unset():
    shared_state = SharedStateObj()

    assert shared_state.utc_datetime() is None
    assert shared_state.local_datetime() is None


@pytest.mark.unit
def test_datetime_is_manual_tracks_forced_sets():
    shared_state = SharedStateObj()

    assert shared_state.datetime_is_manual() is False

    # A regular (GPS) set is not manual.
    shared_state.set_datetime(datetime.datetime(2026, 7, 25, 1, 0, 0, tzinfo=UTC))
    assert shared_state.datetime_is_manual() is False

    # A forced set (user time entry) is manual and blocks GPS overrides.
    shared_state.set_datetime(
        datetime.datetime(2026, 7, 25, 2, 0, 0, tzinfo=UTC), force=True
    )
    assert shared_state.datetime_is_manual() is True

    # Reset clears the manual override (service restart / reboot semantics).
    shared_state.reset_datetime()
    assert shared_state.datetime_is_manual() is False


@pytest.mark.unit
def test_datetime_ignores_wall_clock_steps(monkeypatch):
    """Chrony correcting the boot clock must not advance sky time twice."""
    wall_time = [1_700_000_000.0]
    monotonic_time = [1_000.0]
    monkeypatch.setattr(state_mod.time, "time", lambda: wall_time[0])
    monkeypatch.setattr(state_mod.time, "monotonic", lambda: monotonic_time[0])

    shared_state = SharedStateObj()
    initial = datetime.datetime(2026, 9, 4, 11, 43, 0, tzinfo=UTC)
    shared_state.set_datetime(initial)

    # Simulate chrony stepping an RTC that was 17 hours behind.  Only the five
    # seconds of monotonic elapsed time belong in the astronomical epoch.
    wall_time[0] += 17 * 60 * 60
    monotonic_time[0] += 5

    assert shared_state.utc_datetime() == initial + datetime.timedelta(seconds=5)


@pytest.mark.unit
@pytest.mark.parametrize("days", [-30, 30])
def test_gps_corrects_large_civil_time_error_in_both_directions(frozen_clock, days):
    shared_state = SharedStateObj()
    gps = datetime.datetime(2026, 11, 21, tzinfo=UTC)
    shared_state.set_datetime(gps + datetime.timedelta(days=days))
    shared_state.set_datetime(gps)
    assert shared_state.utc_datetime() == gps
    assert not shared_state.datetime_is_manual()


@pytest.mark.unit
def test_gps_still_ignores_small_backward_jitter(frozen_clock):
    shared_state = SharedStateObj()
    gps = datetime.datetime(2026, 11, 21, tzinfo=UTC)
    shared_state.set_datetime(gps)
    shared_state.set_datetime(gps - datetime.timedelta(seconds=1))
    assert shared_state.utc_datetime() == gps


@pytest.mark.unit
def test_gps_large_correction_preserves_manual_time_override(frozen_clock):
    shared_state = SharedStateObj()
    manual = datetime.datetime(2026, 11, 21, tzinfo=UTC)
    shared_state.set_datetime(manual, force=True)
    shared_state.set_datetime(manual - datetime.timedelta(days=30))
    assert shared_state.utc_datetime() == manual
