from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).resolve().parent / "data" / "location_catalog.json"


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    try:
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {"countries": []}


def _find_country(country_code: str) -> dict[str, Any] | None:
    country_code = (country_code or "").upper()
    for country in load_catalog().get("countries", []):
        if country.get("code") == country_code:
            return country
    return None


def _find_region(country: dict[str, Any], region_code: str) -> dict[str, Any] | None:
    for region in country.get("regions", []):
        if region.get("code") == region_code:
            return region
    return None


def countries() -> list[dict[str, str]]:
    return [
        {"code": country["code"], "name": country["name"]}
        for country in load_catalog().get("countries", [])
    ]


def regions(country_code: str) -> list[dict[str, str]]:
    country = _find_country(country_code)
    if not country:
        return []
    return [
        {"code": region["code"], "name": region["name"]}
        for region in country.get("regions", [])
    ]


def districts(country_code: str, region_code: str) -> list[dict[str, str]]:
    country = _find_country(country_code)
    if not country:
        return []
    region = _find_region(country, region_code)
    if not region:
        return []
    return [
        {"code": district["code"], "name": district["name"]}
        for district in region.get("districts", [])
    ]


def places(
    country_code: str, region_code: str, district_code: str = "", limit: int = 500
) -> list[dict[str, Any]]:
    country = _find_country(country_code)
    if not country:
        return []
    region = _find_region(country, region_code)
    if not region:
        return []

    found_places: list[dict[str, Any]] = []
    for district in region.get("districts", []):
        if district_code and district.get("code") != district_code:
            continue
        for place in district.get("places", []):
            found_places.append(
                {
                    "id": place["id"],
                    "name": place["name"],
                    "ascii_name": place.get("ascii_name", ""),
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "height": place.get("height", 0),
                    "population": place.get("population", 0),
                    "timezone": place.get("timezone", ""),
                    "district_code": district.get("code", ""),
                    "district_name": district.get("name", ""),
                    "region_code": region.get("code", ""),
                    "region_name": region.get("name", ""),
                    "country_code": country.get("code", ""),
                    "country_name": country.get("name", ""),
                }
            )
    found_places.sort(key=lambda item: (-item["population"], item["name"]))
    return found_places[:limit]
