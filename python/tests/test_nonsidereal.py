"""Tests for PiFinder.nonsidereal (tracking-frequency conversions) and the
mount-control track-frequency command plumbing."""

import pytest

from PiFinder import nonsidereal


@pytest.mark.unit
def test_sidereal_round_trip():
    hz = nonsidereal.hz_from_rate(nonsidereal.SIDEREAL_RATE_ARCSEC_S)
    assert hz == pytest.approx(nonsidereal.SIDEREAL_FREQ_HZ, abs=1e-9)
    assert nonsidereal.rate_from_hz(hz) == pytest.approx(
        nonsidereal.SIDEREAL_RATE_ARCSEC_S, abs=1e-9
    )


@pytest.mark.unit
def test_hz_is_about_four_times_arcsec_rate():
    # LX200 model: frequency ~= 4x tracking rate in arcsec/s
    assert nonsidereal.hz_from_rate(15.0411) == pytest.approx(60.164, abs=0.01)


@pytest.mark.unit
def test_offset_examples():
    # Zero offset = sidereal
    assert nonsidereal.hz_from_offset(0.0) == pytest.approx(
        nonsidereal.SIDEREAL_FREQ_HZ, abs=1e-9
    )
    # The Moon moves eastward (+0.55 arcsec/s) -> the mount must track
    # SLOWER than sidereal: the classic 57.9 Hz lunar rate.
    assert nonsidereal.hz_from_offset(0.55) == pytest.approx(57.96, abs=0.05)
    # A target receding westward at sidereal speed -> 2x clock (bench value)
    assert nonsidereal.hz_from_offset(-nonsidereal.SIDEREAL_RATE_ARCSEC_S) == (
        pytest.approx(120.329, abs=0.01)
    )


@pytest.mark.unit
def test_clamp_window():
    inside, clamped = nonsidereal.clamp_hz(66.0)
    assert inside == 66.0 and clamped is False
    low, clamped = nonsidereal.clamp_hz(10.0)
    assert low == nonsidereal.MIN_FREQ_HZ and clamped is True
    high, clamped = nonsidereal.clamp_hz(120.33)
    assert high == nonsidereal.MAX_FREQ_HZ and clamped is True


@pytest.mark.unit
def test_ra_rate_from_positions():
    # 0.05 arcsec/s eastward over 10 minutes
    dra_deg = 0.05 * 600 / 3600.0
    rate = nonsidereal.ra_rate_from_positions(100.0, 100.0 + dra_deg, 600)
    assert rate == pytest.approx(0.05, abs=1e-9)
    # 0/360 wrap, westward motion
    rate = nonsidereal.ra_rate_from_positions(0.01, 359.99, 600)
    assert rate == pytest.approx(-0.12, abs=1e-9)
    assert nonsidereal.ra_rate_from_positions(10.0, 11.0, 0) is None


@pytest.mark.unit
def test_track_freq_for_target():
    result = nonsidereal.track_freq_for_target(100.0, 100.0 + 0.05 * 600 / 3600.0, 600)
    assert result is not None
    freq, dra_dt, was_clamped = result
    assert dra_dt == pytest.approx(0.05, abs=1e-9)
    assert freq == pytest.approx(nonsidereal.hz_from_offset(0.05), abs=1e-9)
    assert was_clamped is False


@pytest.mark.unit
def test_mountcontrol_dispatch_routes_track_freq_commands(monkeypatch):
    """handle_command must route the new command types to the new handlers
    without touching the mount (handlers are stubbed out)."""
    from PiFinder import mountcontrol_indi

    controller = mountcontrol_indi.MountControlIndi.__new__(
        mountcontrol_indi.MountControlIndi
    )
    controller._smooth_runtime = None
    controller.connected = False

    calls = []
    controller.set_track_frequency = lambda hz, label="": calls.append(
        ("set", hz, label)
    )
    controller.reset_track_frequency = lambda: calls.append(("reset",))

    assert controller.handle_command(
        {"type": "set_track_freq", "hz": 66.0, "label": "moon"}
    )
    assert controller.handle_command({"type": "reset_track_freq"})
    assert calls == [("set", 66.0, "moon"), ("reset",)]
