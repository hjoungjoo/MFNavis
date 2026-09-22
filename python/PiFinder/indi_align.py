"""Shared INDI alignment helpers."""

from __future__ import annotations

import csv
import math
from datetime import datetime, timezone
from typing import Any

from PiFinder import calc_utils, utils


ALIGN_POINT_MIN = 1
ALIGN_POINT_MAX = 9
DEFAULT_ALIGN_POINTS = 3
ALIGN_STAR_MIN_ALTITUDE_DEG = 20.0
ALIGN_STAR_MAX_ALTITUDE_DEG = 78.0


def alignment_altitude_limits(
    minimum: Any = None, maximum: Any = None
) -> tuple[float, float]:
    """Validate INDI limits, using the legacy range when unavailable/invalid."""
    try:
        low, high = float(minimum), float(maximum)
        if math.isfinite(low) and math.isfinite(high) and -90 <= low <= high <= 90:
            return low, high
    except (TypeError, ValueError, OverflowError):
        pass
    return ALIGN_STAR_MIN_ALTITUDE_DEG, ALIGN_STAR_MAX_ALTITUDE_DEG


_FALLBACK_BRIGHT_ALIGN_STARS: list[dict[str, Any]] = [
    {"name": "Sirius", "ra": 101.287155, "dec": -16.716116, "mag": -1.46},
    {"name": "Canopus", "ra": 95.987958, "dec": -52.695661, "mag": -0.74},
    {"name": "Arcturus", "ra": 213.915300, "dec": 19.182410, "mag": -0.05},
    {"name": "Vega", "ra": 279.234735, "dec": 38.783689, "mag": 0.03},
    {"name": "Capella", "ra": 79.172327, "dec": 45.997991, "mag": 0.08},
    {"name": "Rigel", "ra": 78.634467, "dec": -8.201638, "mag": 0.13},
    {"name": "Procyon", "ra": 114.825493, "dec": 5.224993, "mag": 0.34},
    {"name": "Achernar", "ra": 24.4, "dec": -57.233333, "mag": 0.4},
    {"name": "Betelgeuse", "ra": 88.792939, "dec": 7.407064, "mag": 0.42},
    {"name": "Hadar", "ra": 210.95, "dec": -60.366667, "mag": 0.6},
    {"name": "Altair", "ra": 297.695827, "dec": 8.868322, "mag": 0.77},
    {"name": "Aldebaran", "ra": 68.980163, "dec": 16.509302, "mag": 0.87},
    {"name": "Spica", "ra": 201.298247, "dec": -11.161319, "mag": 0.98},
    {"name": "Antares", "ra": 247.351915, "dec": -26.432002, "mag": 1.06},
    {"name": "Pollux", "ra": 116.328958, "dec": 28.026199, "mag": 1.14},
    {"name": "Fomalhaut", "ra": 344.412693, "dec": -29.622236, "mag": 1.16},
    {"name": "Deneb", "ra": 310.357979, "dec": 45.280338, "mag": 1.25},
    {"name": "Acrux", "ra": 186.625, "dec": -63.083333, "mag": 1.3},
    {"name": "Mimosa", "ra": 191.925, "dec": -59.683333, "mag": 1.3},
    {"name": "Regulus", "ra": 152.092962, "dec": 11.967209, "mag": 1.35},
    {"name": "Adhara", "ra": 104.65, "dec": -28.966667, "mag": 1.5},
    {"name": "Castor", "ra": 113.65, "dec": 31.883333, "mag": 1.5},
    {"name": "Bellatrix", "ra": 81.275, "dec": 6.333333, "mag": 1.6},
    {"name": "Shaula", "ra": 263.4, "dec": -37.1, "mag": 1.6},
    {"name": "Alioth", "ra": 193.5, "dec": 55.95, "mag": 1.7},
    {"name": "Alnair", "ra": 332.05, "dec": -46.95, "mag": 1.7},
    {"name": "Alnilam", "ra": 84.05, "dec": -1.2, "mag": 1.7},
    {"name": "Alkaid", "ra": 206.875, "dec": 49.3, "mag": 1.8},
    {"name": "Dubhe", "ra": 165.925, "dec": 61.75, "mag": 1.8},
    {"name": "Kaus Australis", "ra": 276.025, "dec": -34.383333, "mag": 1.8},
    {"name": "Alhena", "ra": 99.4, "dec": 16.383333, "mag": 1.9},
    {"name": "Alphard", "ra": 141.875, "dec": -8.65, "mag": 1.9},
    {"name": "Alpheratz", "ra": 2.075, "dec": 29.083333, "mag": 2.0},
    {"name": "Hamal", "ra": 31.775, "dec": 23.45, "mag": 2.0},
    {"name": "Polaris", "ra": 37.95, "dec": 89.25, "mag": 2.0},
    {"name": "Rasalhague", "ra": 263.725, "dec": 12.55, "mag": 2.0},
    {"name": "Saiph", "ra": 86.925, "dec": -9.666667, "mag": 2.0},
    {"name": "Denebola", "ra": 177.25, "dec": 14.566667, "mag": 2.1},
]


def _csv_dec_to_deg(dec_degrees: str, dec_minutes: str) -> float:
    degrees = float(dec_degrees)
    minutes = abs(float(dec_minutes))
    sign = -1.0 if degrees < 0 else 1.0
    return sign * (abs(degrees) + minutes / 60.0)


def _load_bright_align_stars() -> list[dict[str, Any]]:
    stars_by_name: dict[str, dict[str, Any]] = {
        str(star["name"]).casefold(): dict(star)
        for star in _FALLBACK_BRIGHT_ALIGN_STARS
    }
    csv_path = utils.astro_data_dir / "bright_stars.csv"
    try:
        with open(csv_path, newline="", encoding="utf-8") as csv_in:
            for row in csv.DictReader(csv_in):
                name = (row.get("NamedStar") or "").strip()
                if not name:
                    continue
                key = name.casefold()
                if key in stars_by_name:
                    continue
                ra = (float(row["RA Hr"]) + float(row["RA Min"]) / 60.0) * 15.0
                stars_by_name[key] = {
                    "name": name,
                    "ra": ra % 360.0,
                    "dec": _csv_dec_to_deg(row["Dec Deg"], row["Dec Min"]),
                    "mag": float(row["Magnitude"]),
                }
    except (FileNotFoundError, OSError, KeyError, ValueError):
        return list(_FALLBACK_BRIGHT_ALIGN_STARS)

    return sorted(
        stars_by_name.values(),
        key=lambda star: (float(star.get("mag", 99.0)), str(star.get("name", ""))),
    )


BRIGHT_ALIGN_STARS: list[dict[str, Any]] = _load_bright_align_stars()


def clamp_align_points(value: Any) -> int:
    try:
        points = int(float(value))
    except (TypeError, ValueError):
        points = DEFAULT_ALIGN_POINTS
    return max(ALIGN_POINT_MIN, min(ALIGN_POINT_MAX, points))


def get_align_star(name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    normalized = name.strip().casefold()
    for star in BRIGHT_ALIGN_STARS:
        if star["name"].casefold() == normalized:
            return dict(star)
    return None


def next_align_star(completed: list[dict[str, Any]]) -> dict[str, Any]:
    used_names = {str(star.get("name", "")).casefold() for star in completed}
    for star in BRIGHT_ALIGN_STARS:
        if star["name"].casefold() not in used_names:
            return dict(star)
    return dict(BRIGHT_ALIGN_STARS[len(completed) % len(BRIGHT_ALIGN_STARS)])


def angular_separation_degrees(
    ra_a: float, dec_a: float, ra_b: float, dec_b: float
) -> float:
    ra_a_rad = math.radians(float(ra_a))
    dec_a_rad = math.radians(float(dec_a))
    ra_b_rad = math.radians(float(ra_b))
    dec_b_rad = math.radians(float(dec_b))
    cos_sep = math.sin(dec_a_rad) * math.sin(dec_b_rad) + math.cos(
        dec_a_rad
    ) * math.cos(dec_b_rad) * math.cos(ra_a_rad - ra_b_rad)
    cos_sep = max(-1.0, min(1.0, cos_sep))
    return math.degrees(math.acos(cos_sep))


def nearest_align_star(
    ra_deg: float,
    dec_deg: float,
    completed: list[dict[str, Any]] | None = None,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    used_names = {str(star.get("name", "")).casefold() for star in (completed or [])}
    pool = candidates or BRIGHT_ALIGN_STARS
    usable = [
        star for star in pool if str(star.get("name", "")).casefold() not in used_names
    ]
    if not usable:
        usable = pool or BRIGHT_ALIGN_STARS
    if not usable:
        return next_align_star(completed or [])
    return dict(
        min(
            usable,
            key=lambda star: angular_separation_degrees(
                ra_deg,
                dec_deg,
                float(star["ra"]),
                float(star["dec"]),
            ),
        )
    )


def _normalize_datetime(dt: Any) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def align_star_altaz(
    star: dict[str, Any],
    latitude: float,
    longitude: float,
    elevation: float | None,
    dt: Any,
) -> tuple[float, float]:
    dt = _normalize_datetime(dt)
    calc_utils.sf_utils.set_location(latitude, longitude, elevation or 0.0)
    alt_deg, az_deg = calc_utils.sf_utils.radec_to_altaz(
        float(star["ra"]), float(star["dec"]), dt
    )
    return float(alt_deg), float(az_deg) % 360.0


def visible_align_stars(
    latitude: float,
    longitude: float,
    elevation: float | None,
    dt: Any,
    completed: list[dict[str, Any]] | None = None,
    min_altitude: float = ALIGN_STAR_MIN_ALTITUDE_DEG,
    max_altitude: float = ALIGN_STAR_MAX_ALTITUDE_DEG,
) -> list[dict[str, Any]]:
    used_names = {str(star.get("name", "")).casefold() for star in (completed or [])}
    visible: list[dict[str, Any]] = []
    for star in BRIGHT_ALIGN_STARS:
        if str(star.get("name", "")).casefold() in used_names:
            continue
        alt_deg, az_deg = align_star_altaz(star, latitude, longitude, elevation, dt)
        if min_altitude <= alt_deg <= max_altitude:
            candidate = dict(star)
            candidate["alt"] = alt_deg
            candidate["az"] = az_deg
            visible.append(candidate)
    return visible
