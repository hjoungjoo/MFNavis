#!/usr/bin/env python3
"""
Build the offline location catalog used by the PiFinder Locations web page.

Source data:
  https://download.geonames.org/export/dump/

Required files in --source-dir:
  - cities5000.zip
  - countryInfo.txt
  - admin1CodesASCII.txt
  - admin2Codes.txt

Optional enhancement files:
  - KR.zip
"""

import argparse
import json
import zipfile
from pathlib import Path


EXCLUDED_COUNTRIES = {"KP"}
KOREA_DETAIL_FEATURE_CODES = {
    "ADM2",
    "ADM3",
    "ADM4",
    "PPL",
    "PPLA",
    "PPLA2",
    "PPLA3",
    "PPLA4",
    "PPLC",
    "PPLL",
    "PPLX",
}


def read_country_names(path: Path) -> dict[str, str]:
    countries = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) > 4:
                code = fields[0]
                name = fields[4]
                if code not in EXCLUDED_COUNTRIES:
                    countries[code] = name
    return countries


def read_admin_codes(path: Path) -> dict[str, str]:
    codes = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) >= 2:
                codes[fields[0]] = fields[1]
    return codes


def as_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_district(
    country_map: dict[str, dict],
    countries: dict[str, str],
    admin1: dict[str, str],
    admin2: dict[str, str],
    country_code: str,
    admin1_code: str,
    admin2_code: str,
) -> dict:
    country = country_map.setdefault(
        country_code,
        {
            "code": country_code,
            "name": countries[country_code],
            "regions": {},
        },
    )

    region_code = admin1_code or "_"
    region_name = admin1.get(f"{country_code}.{admin1_code}", admin1_code)
    if not region_name:
        region_name = "Unspecified"
    region = country["regions"].setdefault(
        region_code,
        {
            "code": region_code,
            "name": region_name,
            "districts": {},
        },
    )

    district_code = admin2_code or "_"
    district_name = admin2.get(f"{country_code}.{admin1_code}.{admin2_code}", admin2_code)
    if not district_name:
        district_name = "All / Unspecified"
    return region["districts"].setdefault(
        district_code,
        {
            "code": district_code,
            "name": district_name,
            "places": [],
            "_place_ids": set(),
        },
    )


def add_place(
    district: dict,
    geoname_id: str,
    name: str,
    ascii_name: str,
    latitude: str,
    longitude: str,
    elevation: str,
    dem: str,
    population: str,
    feature_code: str,
    timezone: str,
) -> None:
    place_id = as_int(geoname_id)
    if place_id in district["_place_ids"]:
        return
    district["_place_ids"].add(place_id)
    height = as_int(elevation, as_int(dem, 0))
    district["places"].append(
        {
            "id": place_id,
            "name": name,
            "ascii_name": ascii_name,
            "latitude": round(as_float(latitude), 6),
            "longitude": round(as_float(longitude), 6),
            "height": height,
            "population": as_int(population),
            "feature_code": feature_code,
            "timezone": timezone,
        }
    )


def merge_geonames_file(
    raw_handle,
    country_map: dict[str, dict],
    countries: dict[str, str],
    admin1: dict[str, str],
    admin2: dict[str, str],
    allowed_country_codes: set[str] | None = None,
    allowed_feature_codes: set[str] | None = None,
) -> None:
    for raw_line in raw_handle:
        line = raw_line.decode("utf-8").rstrip("\n")
        fields = line.split("\t")
        if len(fields) < 19:
            continue

        (
            geoname_id,
            name,
            ascii_name,
            alternate_names,
            latitude,
            longitude,
            feature_class,
            feature_code,
            country_code,
            cc2,
            admin1_code,
            admin2_code,
            admin3_code,
            admin4_code,
            population,
            elevation,
            dem,
            timezone,
            modification_date,
        ) = fields[:19]

        if country_code in EXCLUDED_COUNTRIES or country_code not in countries:
            continue
        if allowed_country_codes and country_code not in allowed_country_codes:
            continue
        if allowed_feature_codes and feature_code not in allowed_feature_codes:
            continue
        if allowed_country_codes and not admin1_code:
            continue
        if (
            allowed_country_codes
            and country_code == "KR"
            and admin1_code
            and admin2_code
            and not admin2_code.startswith(admin1_code)
        ):
            continue

        # ADM1 rows represent the region itself. Regions are already selectable,
        # so do not duplicate them in the place list.
        if feature_code == "ADM1":
            continue

        if country_code == "KR" and feature_code == "ADM2":
            district_admin2_code = admin2_code or geoname_id
        else:
            district_admin2_code = admin2_code

        district = get_district(
            country_map,
            countries,
            admin1,
            admin2,
            country_code,
            admin1_code,
            district_admin2_code,
        )
        add_place(
            district,
            geoname_id,
            name,
            ascii_name,
            latitude,
            longitude,
            elevation,
            dem,
            population,
            feature_code,
            timezone,
        )


def build_catalog(source_dir: Path, output_path: Path) -> None:
    countries = read_country_names(source_dir / "countryInfo.txt")
    admin1 = read_admin_codes(source_dir / "admin1CodesASCII.txt")
    admin2 = read_admin_codes(source_dir / "admin2Codes.txt")
    country_map: dict[str, dict] = {}

    with zipfile.ZipFile(source_dir / "cities5000.zip") as archive:
        with archive.open("cities5000.txt") as raw_handle:
            merge_geonames_file(raw_handle, country_map, countries, admin1, admin2)

    korea_path = source_dir / "KR.zip"
    if korea_path.exists():
        with zipfile.ZipFile(korea_path) as archive:
            with archive.open("KR.txt") as raw_handle:
                merge_geonames_file(
                    raw_handle,
                    country_map,
                    countries,
                    admin1,
                    admin2,
                    allowed_country_codes={"KR"},
                    allowed_feature_codes=KOREA_DETAIL_FEATURE_CODES,
                )

    catalog = {
        "version": 1,
        "source": (
            "GeoNames cities5000, countryInfo, admin1CodesASCII, admin2Codes"
            ", KR country extract"
        ),
        "license": "CC BY 4.0",
        "excluded_countries": sorted(EXCLUDED_COUNTRIES),
        "countries": [],
    }

    for country in sorted(country_map.values(), key=lambda item: item["name"]):
        regions = []
        for region in sorted(country["regions"].values(), key=lambda item: item["name"]):
            districts = []
            for district in sorted(
                region["districts"].values(), key=lambda item: item["name"]
            ):
                district["places"].sort(
                    key=lambda item: (-item["population"], item["name"])
                )
                unique_places = []
                seen_place_names = set()
                for place in district["places"]:
                    name_key = place["name"].casefold()
                    if name_key in seen_place_names:
                        continue
                    seen_place_names.add(name_key)
                    unique_places.append(place)
                district["places"] = unique_places
                district.pop("_place_ids", None)
                districts.append(district)
            region["districts"] = districts
            regions.append(region)
        country["regions"] = regions
        catalog["countries"].append(country)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(catalog, handle, ensure_ascii=False, separators=(",", ":"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("python/MFNavis/data/location_catalog.json"),
    )
    args = parser.parse_args()
    build_catalog(args.source_dir, args.output)


if __name__ == "__main__":
    main()
