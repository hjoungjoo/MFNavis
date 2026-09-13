"""Sky-source selection and approximate visual catalog ranking."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from PiFinder import web_catalog_visibility as vis
from PiFinder.sky_quality import sqm_to_bortle


@pytest.fixture()
def context(monkeypatch):
    now = 1789260000
    settings = {}
    equipment = SimpleNamespace(
        active_telescope=SimpleNamespace(aperture_mm=200),
        active_eyepiece=object(),
        calc_magnification=lambda: 40,
    )
    monkeypatch.setattr(
        vis,
        "Config",
        lambda: SimpleNamespace(
            get_option=lambda key: settings.get(key),
            equipment=equipment,
        ),
    )
    monkeypatch.setattr(vis.time, "time", lambda: now)
    sample = SimpleNamespace(
        value=20.0,
        source="Radiometer",
        last_update=datetime.fromtimestamp(now - 1, timezone.utc).isoformat(),
    )
    shared = SimpleNamespace(sqm=lambda: sample)
    return settings, sample, shared, equipment, now


@pytest.mark.unit
@pytest.mark.parametrize(
    "sqm,bortle",
    [
        (22, 1),
        (21.76, 1),
        (21.75, 2),
        (21.60, 2),
        (21.5, 3),
        (21.30, 3),
        (21, 4),
        (20.80, 4),
        (20.5, 4.5),
        (20, 5),
        (19, 6),
        (18.3, 7),
        (17.5, 8),
        (16, 9),
        (23, None),
        (float("nan"), None),
        (None, None),
    ],
)
def test_bortle_matches_device_bands(sqm, bortle):
    assert sqm_to_bortle(sqm) == bortle


@pytest.mark.unit
def test_current_sqm_and_equipment(context):
    _settings, _sample, shared, _equipment, _now = context
    sky = vis.sky_conditions(shared)
    assert sky["enabled"] is True
    assert sky["configured_bortle"] is None
    assert sky["measured_bortle"] == 5
    assert sky["sqm"] == 20
    assert sky["aperture_mm"] == 200
    assert sky["magnification"] == 40
    assert sky["source"] == "measured"


@pytest.mark.unit
@pytest.mark.parametrize("measured", [17.5, 22])
def test_configured_and_measured_use_brighter_sky(context, measured):
    settings, sample, shared, _equipment, _now = context
    settings["filter.bortle"] = 4
    sample.value = measured
    sky = vis.sky_conditions(shared)
    assert sky["source"] == "both"
    assert sky["sqm"] == min(21.05, measured)
    assert sky["configured_bortle"] == 4


@pytest.mark.unit
@pytest.mark.parametrize(
    "change",
    [
        {"last_update": None},
        {"source": "None"},
        {"value": float("nan")},
        {"value": 0},
        {"value": 23},
        {"last_update": "invalid"},
    ],
)
def test_unmeasured_or_invalid_sqm_is_not_a_reading(context, change):
    settings, sample, shared, _equipment, _now = context
    for key, value in change.items():
        setattr(sample, key, value)
    sky = vis.sky_conditions(shared)
    assert sky["enabled"] is False
    assert sky["measured_bortle"] is None
    settings["filter.bortle"] = 6
    sky = vis.sky_conditions(shared)
    assert sky["enabled"] is True
    assert sky["source"] == "configured"
    assert sky["bortle"] == 6


@pytest.mark.unit
@pytest.mark.parametrize("age", [61, -10])
def test_stale_or_future_sqm_is_not_current(context, age):
    _settings, sample, shared, _equipment, now = context
    sample.last_update = datetime.fromtimestamp(now - age, timezone.utc).isoformat()
    sky = vis.sky_conditions(shared)
    assert sky["enabled"] is False
    assert sky["measurement_state"] == "stale"


@pytest.mark.unit
def test_device_local_sqm_timestamp(context):
    _settings, sample, shared, _equipment, now = context
    sample.last_update = (
        datetime.fromtimestamp(now - 1, timezone.utc)
        .astimezone()
        .replace(tzinfo=None)
        .isoformat()
    )
    assert vis.sky_conditions(shared)["enabled"] is True
    assert vis.sky_conditions(shared)["measurement_state"] == "available"


@pytest.mark.unit
def test_missing_equipment_and_invalid_config(context):
    settings, sample, shared, equipment, _now = context
    equipment.active_telescope = None
    assert vis.sky_conditions(shared)["enabled"] is False
    settings["filter.bortle"] = 99
    sample.last_update = None
    assert vis.sky_conditions(shared)["configured_bortle"] is None


@pytest.mark.unit
def test_light_pollution_changes_star_and_galaxy_rank(context):
    _settings, sample, shared, _equipment, _now = context
    sample.value = 22
    dark = vis.sky_conditions(shared)
    sample.value = 17
    bright = vis.sky_conditions(shared)
    for obj_type, mag, size in [("*", 12, None), ("Gx", 12, '{"e": [60, 60]}')]:
        assert vis.visibility(obj_type, mag, size, dark)["rank"] == 0
        assert vis.visibility(obj_type, mag, size, bright)["rank"] == 2


@pytest.mark.unit
def test_point_limit_respects_aperture_exit_pupil_and_magnitude_setting(context):
    settings, _sample, shared, equipment, _now = context
    baseline = vis.sky_conditions(shared)["limiting_mag"]
    equipment.active_telescope.aperture_mm = 100
    assert vis.sky_conditions(shared)["limiting_mag"] < baseline
    equipment.active_telescope.aperture_mm = 200
    equipment.calc_magnification = lambda: 10
    assert vis.sky_conditions(shared)["limiting_mag"] < baseline
    settings["filter.magnitude"] = 8
    assert vis.sky_conditions(shared)["limiting_mag"] == 8


@pytest.mark.unit
@pytest.mark.parametrize(
    "obj_type,mag,size",
    [
        ("*", None, None),
        ("*", 99, None),
        ("Gx", 10, None),
        ("Gx", 10, '{"e": [0]}'),
        ("Gx", 10, '{"e": [[1, 2], [3, 4]]}'),
        ("DN", 10, '{"e": [100]}'),
    ],
)
def test_missing_photometry_is_unknown(context, obj_type, mag, size):
    _settings, _sample, shared, _equipment, _now = context
    assert (
        vis.visibility(obj_type, mag, size, vis.sky_conditions(shared))["label"]
        == "Unknown"
    )
