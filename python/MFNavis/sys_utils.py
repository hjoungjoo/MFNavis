from __future__ import annotations
import glob
import configparser
import importlib.util
import ipaddress
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

import pam
import requests
import sh

try:
    from sh import wpa_cli, passwd
except ImportError:
    # Off-device (CI, dev machines) these binaries may not exist. The code
    # paths that call them only run on the Pi, so fail at call time instead
    # of import time.
    def _missing_command(name):
        def _fail(*args, **kwargs):
            raise RuntimeError(f"'{name}' command is not available on this system")

        return _fail

    wpa_cli = _missing_command("wpa_cli")
    passwd = _missing_command("passwd")

import socket
from PiFinder import board_config
from PiFinder import utils
import logging

BACKUP_PATH = str(utils.data_dir / "MFNavis_backup.zip")

logger = logging.getLogger("SysUtils")

WIFI_MODE_AP = "AP"
WIFI_MODE_CLIENT = "Client"
WIFI_MODE_APSTA = "AP+STA"
WPA_SUPPLICANT_PATH = "/etc/wpa_supplicant/wpa_supplicant.conf"
BOOT_WPA_SUPPLICANT_PATHS = [
    "/boot/firmware/wpa_supplicant.conf",
    "/boot/wpa_supplicant.conf",
]
NETWORKMANAGER_CONNECTION_GLOB = "/etc/NetworkManager/system-connections/*.nmconnection"
HOSTAPD_CONF_PATH = "/etc/hostapd/hostapd.conf"
HOSTAPD_TMP_PATH = "/tmp/hostapd.conf"
DHCPD_AP_CONF_PATH = "/etc/dhcpcd.conf.ap"
DHCPD_APSTA_CONF_PATH = "/etc/dhcpcd.conf.apsta"
DHCPD_ACTIVE_CONF_PATH = "/etc/dhcpcd.conf"
DNSMASQ_CONF_PATH = "/etc/dnsmasq.conf"
MFNAVIS_APSTA_NAT_CONF_PATH = "/etc/mfnavis_apsta_nat.conf"
MFNAVIS_STA_BAND_CONF_PATH = "/etc/mfnavis_sta_band.conf"
DNSMASQ_LEASES_PATH = "/var/lib/misc/dnsmasq.leases"
DEFAULT_AP_IP = "10.10.10.1"
AP_SECURITY_OPEN = "OPEN"
AP_SECURITY_WPA2 = "WPA2-PSK"
STA_BAND_AUTO = "auto"
STA_BAND_24 = "2.4"
STA_BAND_5 = "5"
STA_BAND_PREFERENCES = {STA_BAND_AUTO, STA_BAND_24, STA_BAND_5}
STA_24GHZ_SCAN_FREQ = "2412 2417 2422 2427 2432 2437 2442 2447 2452 2457 2462 2467 2472"
STA_5GHZ_SCAN_FREQ = (
    "5180 5200 5220 5240 5260 5280 5300 5320 "
    "5500 5520 5540 5560 5580 5600 5620 5640 5660 5680 5700 "
    "5745 5765 5785 5805 5825"
)
NMCLI_COMMAND = "nmcli"
INDI_SETPROP_COMMAND = "indi_setprop"
INDI_GETPROP_COMMAND = "indi_getprop"
INDI_WEB_MANAGER_SERVICE = "indiwebmanager.service"
DEFAULT_INDI_SERVER_HOST = "localhost"
DEFAULT_INDI_SERVER_PORT = 7624
DEFAULT_ONSTEP_NETWORK_PORT = 9999
ONSTEPX_DEVICE_NAME = "LX200 OnStepX"
LEGACY_ONSTEP_DEVICE_NAME = "LX200 OnStep"
DEFAULT_ONSTEP_DEVICE_NAME = ONSTEPX_DEVICE_NAME
DEFAULT_INDI_PROFILE_NAME = "MF_PiFinder"
INDI_PROFILE_DB_PATH = utils.home_dir / ".indi" / "profiles.db"
ONSTEP_CONNECTION_USB = "usb"
ONSTEP_CONNECTION_NETWORK = "network"
ONSTEP_SERIAL_AUTO_VALUE = "__auto__"
ONSTEP_SERIAL_BAUD_RATES = (9600, 19200, 38400, 57600, 115200, 230400, 460800)
DEFAULT_ONSTEP_SERIAL_BAUD = 9600
ONSTEP_SERIAL_PROBE_SETTLE_SECONDS = 0.15
ONSTEP_SERIAL_PROBE_REPLY_TIMEOUT_SECONDS = 0.8
ONSTEP_SERIAL_DISCOVERY_TIMEOUT_SECONDS = 30.0
ONSTEP_SERIAL_PROBE_MAX_REPLY_BYTES = 96
ONSTEP_PRODUCT_NAMES = frozenset({"on-step", "onstep", "on-stepx", "onstepx"})
ONSTEP_FIRMWARE_VERSION_RE = re.compile(r"^\d+(?:\.\d+)+(?:[A-Za-z0-9._+\-]*)$")
ONSTEP_LOCATION_CACHE_FILE = utils.data_dir / "onstep_location_cache.json"
# The LX200 OnStepX INDI driver may read site latitude/longitude back at minute
# precision even when the device itself keeps seconds.
ONSTEP_LOCATION_READBACK_TOLERANCE_DEGREES = (1.0 / 60.0) + 0.002
ONSTEP_BACKLASH_RA_PROPERTY = "Backlash.Backlash RA"
ONSTEP_BACKLASH_DE_PROPERTY = "Backlash.Backlash DEC"
ONSTEP_BACKLASH_RA_FALLBACK_PROPERTIES = (ONSTEP_BACKLASH_RA_PROPERTY, "Backlash.RA")
ONSTEP_BACKLASH_DE_FALLBACK_PROPERTIES = (ONSTEP_BACKLASH_DE_PROPERTY, "Backlash.DE")
ONSTEP_DISPLAY_PROPERTIES = [
    "CONNECTION.CONNECT",
    "CONNECTION_MODE.CONNECTION_SERIAL",
    "CONNECTION_MODE.CONNECTION_TCP",
    "DEVICE_PORT.PORT",
    "DEVICE_BAUD_RATE.*",
    "DEVICE_ADDRESS.ADDRESS",
    "DEVICE_ADDRESS.PORT",
    "TIME_UTC.UTC",
    "GEOGRAPHIC_COORD.LAT",
    "GEOGRAPHIC_COORD.LONG",
    "GEOGRAPHIC_COORD.ELEV",
    "TELESCOPE_PARK.PARK",
    "TELESCOPE_PARK.UNPARK",
    "OnStep Status.Park",
    "OnStep Status.Tracking",
    "OnStep Status.:GU# return",
    "EQUATORIAL_EOD_COORD.RA",
    "EQUATORIAL_EOD_COORD.DEC",
    "TELESCOPE_TRACK_STATE.TRACK_ON",
    "TELESCOPE_TRACK_STATE.TRACK_OFF",
    "TELESCOPE_HOME.SET",
    "TELESCOPE_HOME.GO",
    "TELESCOPE_PARK_OPTION.PARK_CURRENT",
    "TELESCOPE_PARK_OPTION.PARK_DEFAULT",
    "TELESCOPE_PARK_OPTION.PARK_WRITE_DATA",
    "TELESCOPE_PARK_OPTION.PARK_PURGE_DATA",
    *ONSTEP_BACKLASH_DE_FALLBACK_PROPERTIES,
    *ONSTEP_BACKLASH_RA_FALLBACK_PROPERTIES,
    *[f"TELESCOPE_SLEW_RATE.{rate}" for rate in range(10)],
]


def parse_onstep_home_park_state(
    status_text: str | None = "",
    park_switch: str | None = "",
    unpark_switch: str | None = "",
    raw_status: str | None = "",
) -> dict[str, str]:
    """Split OnStep's combined home/park text into explicit UI states."""
    text = (status_text or "").strip()
    lower_text = text.lower()

    if "waiting at home" in lower_text:
        home_state = "Waiting at Home"
    elif "home" in lower_text:
        home_state = "At Home"
    elif text:
        home_state = "Not at Home"
    else:
        home_state = "Unknown"

    if "failed" in lower_text:
        park_state = "Parking Failed"
    elif "progress" in lower_text or (
        "parking" in lower_text and "parked" not in lower_text
    ):
        park_state = "Parking"
    elif "unparked" in lower_text:
        park_state = "Unparked"
    elif "parked" in lower_text:
        park_state = "Parked"
    elif (park_switch or "").strip() == "On":
        park_state = "Parked"
    elif (unpark_switch or "").strip() == "On":
        park_state = "Unparked"
    else:
        park_state = "Unknown"

    return {
        "home_state": home_state,
        "park_state": park_state,
        "driver_status": text,
        "raw_status": (raw_status or "").strip(),
    }


BLUETOOTHCTL_COMMAND = "bluetoothctl"
BLUETOOTH_DEVICE_RE = re.compile(
    r"(?:\[[^\]]+\]\s*)?Device\s+([0-9A-Fa-f:]{17})\s+(.+)"
)
BLUETOOTH_DEVICE_FIELD_RE = re.compile(
    r"(?:\[[^\]]+\]\s*)?Device\s+([0-9A-Fa-f:]{17})\s+([^:]+):\s+(.+)"
)
BLUETOOTH_MAC_RE = re.compile(r"^[0-9A-Fa-f:]{17}$")
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# bluetoothctl wraps colored prompts in readline non-printing markers \x01/\x02;
# strip all C0 control chars except tab/newline so they don't corrupt parsing.
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# HID-over-uhid: BlueZ needs the `uhid` kernel module to register a paired
# Bluetooth keyboard as a Linux input device. Without it a keyboard shows as
# "Connected" but no keystrokes reach the system.
UHID_MODULE = "uhid"

# The Raspberry Pi onboard chip (BCM4345C0) shares a single 2.4GHz antenna
# between WiFi and Bluetooth. Active WiFi traffic reliably clobbers BLE
# connection-establishment events, so pairing a keyboard fails ~0.3s after
# connect with HCI 0x3e (Connection Failed to be Established). We therefore
# silence WiFi for the duration of a pairing attempt and always restore it.
# Bluetooth only occupies 2.4GHz, though: when every active WiFi link sits in
# the 5GHz band the radio does not contend with BLE and the pause is skipped
# (see bt_pairing_needs_wifi_pause).
BT_PAIRING_STA_INTERFACE = "wlan0"
BT_PAIRING_AP_INTERFACE = "uap0"
# Channel frequencies at or above this are 5GHz-band; below is 2.4GHz.
BT_PAIRING_5GHZ_MIN_FREQ_MHZ = 4900
# `iw dev <iface> info` reports the active channel as e.g.
# "channel 153 (5765 MHz), width: 80 MHz, ..." only while a link is up.
_IW_CHANNEL_FREQ_RE = re.compile(r"channel\s+\d+\s+\((\d+)\s*MHz\)")
BT_PAIRING_WIFI_SAFETY_TIMEOUT = 60
# In-process WiFi restore fired this many seconds after a pause, regardless of
# whether the caller's own resume path survives (see pause_wifi_for_bt_pairing).
# Matches the pairing screen's WIFI_MAX_PAUSE so behavior stays the same when
# everything is healthy.
BT_PAIRING_WIFI_APP_RESUME_SECONDS = 35
# Where we stash the active wlan0 connection UUID while WiFi is paused, so both
# the normal restore and the detached watchdog bring back exactly that profile
# instead of guessing (nmcli "device connect" can fail to pick an existing one).
BT_PAIRING_WIFI_STATE_FILE = "/tmp/pifinder_bt_pairing_wlan_conn"


def is_onstepx_device_name(device_name: str | None) -> bool:
    return (device_name or "").strip().lower() == ONSTEPX_DEVICE_NAME.lower()


def is_onstep_family_device_name(device_name: str | None) -> bool:
    normalized = (device_name or "").strip().lower()
    return normalized in {
        ONSTEPX_DEVICE_NAME.lower(),
        LEGACY_ONSTEP_DEVICE_NAME.lower(),
    }


def get_indi_profile_drivers(
    profile_name: str | None = None,
    profiles_db_path: Any = INDI_PROFILE_DB_PATH,
) -> dict[str, Any]:
    """Return the active INDI Web Manager profile and its driver labels."""
    path = profiles_db_path
    try:
        if not os.path.exists(path):
            return {"profile": "", "drivers": []}

        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            profile_row = None
            if profile_name:
                profile_row = cursor.execute(
                    "select id, name from profile where name = ? limit 1",
                    (profile_name,),
                ).fetchone()

            if profile_row is None:
                profile_row = cursor.execute(
                    "select id, name from profile where autostart = 1 order by id desc limit 1"
                ).fetchone()

            if profile_row is None:
                profile_row = cursor.execute(
                    "select id, name from profile where name = ? limit 1",
                    (DEFAULT_INDI_PROFILE_NAME,),
                ).fetchone()

            if profile_row is None:
                profile_row = cursor.execute(
                    "select id, name from profile order by id desc limit 1"
                ).fetchone()

            if profile_row is None:
                return {"profile": "", "drivers": []}

            drivers = [
                row["label"]
                for row in cursor.execute(
                    "select label from driver where profile = ? order by id",
                    (profile_row["id"],),
                )
                if row["label"]
            ]
            return {"profile": profile_row["name"], "drivers": drivers}
    except sqlite3.Error:
        logger.exception("Could not read INDI profile database")
        return {"profile": "", "drivers": []}


def get_indi_profile_device_name(
    profile_name: str | None = None,
    fallback: str = DEFAULT_ONSTEP_DEVICE_NAME,
) -> str:
    """Return the telescope-like driver label from the active INDI profile."""
    profile = get_indi_profile_drivers(profile_name=profile_name)
    drivers = profile.get("drivers", [])
    if not drivers:
        return fallback

    ignore_words = ("ccd", "camera", "focuser", "filter", "dome", "weather")
    telescope_words = (
        "telescope",
        "mount",
        "lx200",
        "onstep",
        "eqmod",
        "celestron",
        "skywatcher",
        "ioptron",
    )
    for driver in drivers:
        lowered = driver.lower()
        if any(word in lowered for word in telescope_words) and not any(
            word in lowered for word in ignore_words
        ):
            return driver

    return drivers[0] if drivers else fallback


def resolve_indi_device_name(device_name: str | None = None) -> str:
    return (device_name or "").strip() or get_indi_profile_device_name()


def parse_indi_utc_datetime(value: Any) -> datetime:
    """Return a timezone-aware UTC datetime for INDI TIME_UTC.UTC."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            parsed = datetime.now(timezone.utc)
        else:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def local_utc_offset_hours(at_utc: datetime | None = None) -> float:
    """Return the system local UTC offset in hours for the given UTC time."""
    utc_dt = parse_indi_utc_datetime(at_utc or datetime.now(timezone.utc))
    offset = utc_dt.astimezone().utcoffset()
    if offset is None:
        return 0.0
    return offset.total_seconds() / 3600.0


def onstep_longitude_degrees(longitude: float) -> float:
    """INDI LX200 longitude is 0..360 degrees eastward."""
    lon = float(longitude)
    if lon < 0:
        lon += 360.0
    return lon


def onstep_web_longitude_degrees(indi_longitude: float) -> float:
    """Convert INDI 0..360 eastward longitude to OnStep web west-positive style."""
    lon = float(indi_longitude) % 360.0
    if lon > 180.0:
        return 360.0 - lon
    return -lon


def signed_longitude_degrees(indi_longitude: float) -> float:
    """Convert INDI 0..360 eastward longitude to ordinary signed east-positive degrees."""
    lon = float(indi_longitude) % 360.0
    if lon > 180.0:
        lon -= 360.0
    return lon


def onstep_location_readback_matches(
    readback_latitude: Any,
    readback_indi_longitude: Any,
    target_latitude: Any,
    target_longitude: Any,
    tolerance_degrees: float = ONSTEP_LOCATION_READBACK_TOLERANCE_DEGREES,
) -> bool:
    """Compare a requested location with INDI readback at LX200 site precision."""
    try:
        current_lat = float(readback_latitude)
        current_lon = float(readback_indi_longitude) % 360.0
        target_lat = float(target_latitude)
        target_lon = onstep_longitude_degrees(float(target_longitude)) % 360.0
    except (TypeError, ValueError):
        return False

    lon_delta = abs(current_lon - target_lon)
    lon_delta = min(lon_delta, 360.0 - lon_delta)
    return (
        abs(current_lat - target_lat) <= tolerance_degrees
        and lon_delta <= tolerance_degrees
    )


def _format_signed_dms(value: float, degree_width: int) -> str:
    sign = "+" if value >= 0 else "-"
    total_seconds = int(round(abs(float(value)) * 3600.0))
    degrees, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"{sign}{degrees:0{degree_width}d}"
        f"\N{DEGREE SIGN}{minutes:02d}'{seconds:02d}\""
    )


def format_onstep_location_display(
    latitude: Any,
    indi_longitude: Any,
    elevation: Any = None,
) -> str:
    """Return location using the same longitude sign style as the OnStep web UI."""
    if latitude in (None, "") or indi_longitude in (None, ""):
        return "-"

    lat_dms = _format_signed_dms(float(latitude), 2)
    lon_dms = _format_signed_dms(
        onstep_web_longitude_degrees(float(indi_longitude)),
        3,
    )
    text = f"{lat_dms}, {lon_dms}"
    if elevation not in (None, ""):
        text += f" / {float(elevation):g}m"
    return text


def _onstep_property(properties: dict[str, Any], property_name: str) -> Any:
    suffix = f".{property_name}"
    for key, value in properties.items():
        if key.endswith(suffix):
            return value
    return None


def write_onstep_location_cache(
    latitude: float,
    longitude: float,
    elevation: float | None = None,
    utc_datetime: Any = None,
) -> None:
    """Persist the last high-precision location MFNavis successfully sent."""
    payload: dict[str, Any] = {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "elevation": None if elevation is None else float(elevation),
        "updated": time.time(),
    }
    if utc_datetime is not None:
        payload["utc_time"] = (
            parse_indi_utc_datetime(utc_datetime)
            .replace(microsecond=0)
            .strftime("%Y-%m-%dT%H:%M:%S")
        )

    try:
        utils.create_path(utils.data_dir)
        with open(ONSTEP_LOCATION_CACHE_FILE, "w", encoding="utf-8") as cache_out:
            json.dump(payload, cache_out, indent=2, sort_keys=True)
    except OSError:
        logger.exception("Could not write OnStep location cache")


def read_onstep_location_cache() -> dict[str, Any]:
    """Return the last high-precision location sent by MFNavis, if available."""
    try:
        with open(ONSTEP_LOCATION_CACHE_FILE, encoding="utf-8") as cache_in:
            payload = json.load(cache_in)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

    if "latitude" not in payload or "longitude" not in payload:
        return {}
    return payload


def format_onstep_location_display_with_cache(
    onstep_props: dict[str, Any],
    location_cache: dict[str, Any] | None = None,
) -> str:
    """Format OnStep location, using cached MFNavis values when readback is coarse."""
    raw_lat = _onstep_property(onstep_props, "GEOGRAPHIC_COORD.LAT")
    raw_lon = _onstep_property(onstep_props, "GEOGRAPHIC_COORD.LONG")
    raw_elev = _onstep_property(onstep_props, "GEOGRAPHIC_COORD.ELEV")
    location_cache = location_cache or read_onstep_location_cache()

    if location_cache and onstep_location_readback_matches(
        raw_lat,
        raw_lon,
        location_cache.get("latitude"),
        location_cache.get("longitude"),
    ):
        return format_onstep_location_display(
            location_cache["latitude"],
            onstep_longitude_degrees(location_cache["longitude"]),
            location_cache.get("elevation"),
        )

    return format_onstep_location_display(raw_lat, raw_lon, raw_elev)


def effective_onstep_location(
    onstep_props: dict[str, Any],
    location_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Return the best available OnStep site coordinates in PiFinder convention.

    The INDI LX200 OnStep driver's GEOGRAPHIC_COORD readback can be coarse. If
    it matches the last high-precision PiFinder sync, prefer the cached synced
    coordinates for application logic and keep driver readback for diagnostics.
    """
    raw_lat = _onstep_property(onstep_props, "GEOGRAPHIC_COORD.LAT")
    raw_lon = _onstep_property(onstep_props, "GEOGRAPHIC_COORD.LONG")
    raw_elev = _onstep_property(onstep_props, "GEOGRAPHIC_COORD.ELEV")
    location_cache = location_cache or read_onstep_location_cache()

    if location_cache and onstep_location_readback_matches(
        raw_lat,
        raw_lon,
        location_cache.get("latitude"),
        location_cache.get("longitude"),
    ):
        return {
            "latitude": float(location_cache["latitude"]),
            "longitude": float(location_cache["longitude"]),
            "elevation": location_cache.get("elevation"),
            "source": "MFNavis synced location",
            "driver_readback_matched": True,
        }

    try:
        return {
            "latitude": float(raw_lat),
            "longitude": signed_longitude_degrees(float(raw_lon)),
            "elevation": None if raw_elev in (None, "") else float(raw_elev),
            "source": "INDI driver readback",
            "driver_readback_matched": False,
        }
    except (TypeError, ValueError):
        return {
            "latitude": None,
            "longitude": None,
            "elevation": None,
            "source": "Unavailable",
            "driver_readback_matched": False,
        }


def format_effective_onstep_location(
    onstep_props: dict[str, Any],
    location_cache: dict[str, Any] | None = None,
) -> str:
    """Format effective OnStep site coordinates as decimal MFNavis coordinates."""
    effective = effective_onstep_location(onstep_props, location_cache)
    if effective["latitude"] is None or effective["longitude"] is None:
        return "-"
    elevation = effective.get("elevation")
    elevation_text = "-" if elevation is None else f"{float(elevation):g}"
    return (
        f"{float(effective['latitude']):.5f}, "
        f"{float(effective['longitude']):.5f} / {elevation_text}m"
    )


def _dms_parts(value: float) -> tuple[int, int, int]:
    total_seconds = int(round(abs(float(value)) * 3600.0))
    degrees, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return degrees, minutes, seconds


def build_onstep_lx200_location_time_commands(
    latitude: float,
    longitude: float,
    utc_datetime: Any,
    elevation: float | None = None,
    utc_offset_hours: float | None = None,
) -> list[str]:
    """Build OnStep/LX200 commands for exclusive direct site/time sync."""
    lat = float(latitude)
    onstep_lon = onstep_web_longitude_degrees(onstep_longitude_degrees(longitude))
    utc_dt = parse_indi_utc_datetime(utc_datetime)
    offset = (
        local_utc_offset_hours(utc_dt)
        if utc_offset_hours is None
        else float(utc_offset_hours)
    )
    local_dt = utc_dt.astimezone(timezone(timedelta(hours=offset)))
    # OnStep :SG is the value added to local time to get UTC, so its sign is
    # opposite of the usual local UTC offset used by INDI TIME_UTC.OFFSET.
    onstep_offset = -offset

    lat_d, lat_m, lat_s = _dms_parts(lat)
    lon_d, lon_m, lon_s = _dms_parts(onstep_lon)
    offset_sign = "+" if onstep_offset >= 0 else "-"
    offset_minutes_total = int(round(abs(onstep_offset) * 60.0))
    offset_h, offset_m = divmod(offset_minutes_total, 60)

    commands = [
        f":St{'+' if lat >= 0 else '-'}{lat_d:02d}*{lat_m:02d}:{lat_s:02d}#",
        f":Sg{'+' if onstep_lon >= 0 else '-'}{lon_d:03d}*{lon_m:02d}:{lon_s:02d}#",
        f":SG{offset_sign}{offset_h:02d}:{offset_m:02d}#",
        f":SL{local_dt.hour:02d}:{local_dt.minute:02d}:{local_dt.second:02d}#",
        f":SC{local_dt.month:02d}/{local_dt.day:02d}/{local_dt.year % 100:02d}#",
    ]
    if elevation is not None:
        commands.insert(2, f":Sv{float(elevation):g}#")
    return commands


def build_indi_location_time_properties(
    latitude: float | None = None,
    longitude: float | None = None,
    elevation: float | None = None,
    utc_datetime: Any = None,
    utc_offset_hours: float | None = None,
    device_name: str | None = None,
) -> list[str]:
    """Build INDI properties for site location and UTC time."""
    device_name = resolve_indi_device_name(device_name)
    properties: list[str] = []

    if latitude is not None and longitude is not None:
        properties.extend(
            [
                f"{device_name}.GEOGRAPHIC_COORD.LAT={float(latitude)}",
                f"{device_name}.GEOGRAPHIC_COORD.LONG="
                f"{onstep_longitude_degrees(float(longitude))}",
            ]
        )
        if elevation is not None:
            properties.append(f"{device_name}.GEOGRAPHIC_COORD.ELEV={float(elevation)}")

    if utc_datetime is not None:
        utc_dt = parse_indi_utc_datetime(utc_datetime)
        offset_hours = (
            local_utc_offset_hours(utc_dt)
            if utc_offset_hours is None
            else float(utc_offset_hours)
        )
        properties.extend(
            [
                f"{device_name}.TIME_UTC.UTC="
                + utc_dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S"),
                f"{device_name}.TIME_UTC.OFFSET={offset_hours:.2f}",
            ]
        )

    return properties


def list_onstep_serial_ports(
    excluded_paths: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    """
    Return likely USB serial ports for an OnStep controller.

    Collapse aliases that resolve to the same character device. Prefer stable
    /dev/serial/by-id names when available, then by-path and common ttyUSB/
    ttyACM fallbacks. The label includes the resolved target for clarity.
    """
    ports_by_target: dict[str, dict[str, str]] = {}
    excluded_targets = {
        os.path.realpath(str(path))
        for path in (excluded_paths or ())
        if str(path).strip()
    }

    def path_priority(path: str) -> tuple[int, str]:
        if path.startswith("/dev/serial/by-id/"):
            return (0, path)
        if path.startswith("/dev/serial/by-path/"):
            return (1, path)
        return (2, path)

    for pattern in [
        "/dev/serial/by-id/*",
        "/dev/serial/by-path/*",
        "/dev/ttyUSB*",
        "/dev/ttyACM*",
    ]:
        for path in sorted(glob.glob(pattern)):
            try:
                resolved = os.path.realpath(path)
            except OSError:
                resolved = path
            if resolved in excluded_targets:
                continue
            label = path
            if resolved != path:
                label = f"{path} ({resolved})"
            candidate = {"path": path, "label": label, "resolved": resolved}
            existing = ports_by_target.get(resolved)
            if existing is None or path_priority(path) < path_priority(
                existing["path"]
            ):
                ports_by_target[resolved] = candidate
    return sorted(ports_by_target.values(), key=lambda item: item["path"])


def onstep_serial_baud_probe_order(
    preferred_bauds: Iterable[Any] | None = None,
) -> list[int]:
    """Return a unique, deterministic baud order for OnStep discovery."""
    ordered: list[int] = []
    for value in [*(preferred_bauds or ()), DEFAULT_ONSTEP_SERIAL_BAUD]:
        try:
            baud = int(value)
        except (TypeError, ValueError):
            continue
        if baud in ONSTEP_SERIAL_BAUD_RATES and baud not in ordered:
            ordered.append(baud)
    for baud in ONSTEP_SERIAL_BAUD_RATES:
        if baud not in ordered:
            ordered.append(baud)
    return ordered


def _sanitize_onstep_probe_reply(reply: bytes | str) -> str:
    if isinstance(reply, bytes):
        text = reply.decode("ascii", errors="replace")
    else:
        text = str(reply)
    text = "".join(char for char in text if char == "#" or char.isprintable())
    return text[:ONSTEP_SERIAL_PROBE_MAX_REPLY_BYTES]


def _onstep_probe_payload(reply: bytes | str) -> str | None:
    text = _sanitize_onstep_probe_reply(reply).strip()
    if not text.endswith("#") or text.count("#") != 1:
        return None
    payload = text[:-1].strip()
    if not payload or len(payload) > ONSTEP_SERIAL_PROBE_MAX_REPLY_BYTES - 1:
        return None
    return payload


def _serial_class_without_modem_control(serial_class: Any) -> Any:
    """Return a pySerial class that never drives the DTR or RTS output lines.

    Disabling ``rtscts``/``dsrdtr`` only disables flow control. pySerial still
    applies its default active DTR and RTS states whenever it opens a port. On
    ESP32 OnStepX controllers those lines can be wired to EN and GPIO0, so even
    a read-only probe could otherwise reset the MCU or select its bootloader.
    """

    class SerialWithoutModemControl(serial_class):
        def _update_rts_state(self) -> None:
            return None

        def _update_dtr_state(self) -> None:
            return None

        def _reconfigure_port(self, *args: Any, **kwargs: Any) -> None:
            super()._reconfigure_port(*args, **kwargs)
            try:
                import termios

                settings = termios.tcgetattr(self.fd)
                settings[0] &= ~(
                    getattr(termios, "IXON", 0)
                    | getattr(termios, "IXOFF", 0)
                    | getattr(termios, "IXANY", 0)
                )
                settings[2] &= ~(
                    getattr(termios, "CRTSCTS", 0) | getattr(termios, "HUPCL", 0)
                )
                settings[2] |= getattr(termios, "CLOCAL", 0)
                termios.tcsetattr(self.fd, termios.TCSANOW, settings)
            except (ImportError, AttributeError, OSError):
                # Virtual and test serial backends may not expose POSIX termios.
                # The DTR/RTS method suppression above remains effective.
                pass

    SerialWithoutModemControl.__name__ = "SerialWithoutModemControl"
    return SerialWithoutModemControl


def probe_onstep_serial_port(
    serial_port: str,
    baudrate: int,
    *,
    settle_seconds: float = ONSTEP_SERIAL_PROBE_SETTLE_SECONDS,
    reply_timeout: float = ONSTEP_SERIAL_PROBE_REPLY_TIMEOUT_SECONDS,
    serial_factory: Any = None,
) -> dict[str, Any]:
    """Identify OnStep with read-only ``:GVP#`` and ``:GVN#`` queries."""
    serial_port = str(serial_port or "").strip()
    baudrate = int(baudrate)
    result: dict[str, Any] = {
        "status": "rejected",
        "path": serial_port,
        "baud": baudrate,
        "product": "",
        "version": "",
        "error": "",
    }
    if not serial_port.startswith("/dev/"):
        result["error"] = "invalid_port"
        return result
    if baudrate not in ONSTEP_SERIAL_BAUD_RATES:
        result["error"] = "unsupported_baud"
        return result

    if serial_factory is None:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is not installed") from exc
        serial_factory = _serial_class_without_modem_control(serial.Serial)

    try:
        with serial_factory(
            serial_port,
            baudrate=baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=float(reply_timeout),
            write_timeout=float(reply_timeout),
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
            exclusive=True,
        ) as serial_device:
            reset_input = getattr(serial_device, "reset_input_buffer", None)
            if callable(reset_input):
                reset_input()
            reset_output = getattr(serial_device, "reset_output_buffer", None)
            if callable(reset_output):
                reset_output()
            if settle_seconds > 0:
                time.sleep(float(settle_seconds))

            serial_device.write(b":GVP#")
            serial_device.flush()
            product_reply = serial_device.read_until(
                b"#", ONSTEP_SERIAL_PROBE_MAX_REPLY_BYTES
            )
            product = _onstep_probe_payload(product_reply)
            result["product_reply"] = _sanitize_onstep_probe_reply(product_reply)
            if product is None or product.lower() not in ONSTEP_PRODUCT_NAMES:
                result["error"] = "product_mismatch"
                return result
            result["product"] = product

            serial_device.write(b":GVN#")
            serial_device.flush()
            version_reply = serial_device.read_until(
                b"#", ONSTEP_SERIAL_PROBE_MAX_REPLY_BYTES
            )
            version = _onstep_probe_payload(version_reply)
            result["version_reply"] = _sanitize_onstep_probe_reply(version_reply)
            if version is None or ONSTEP_FIRMWARE_VERSION_RE.fullmatch(version) is None:
                result["status"] = "probable"
                result["error"] = "invalid_version"
                return result
            result["version"] = version
            result["status"] = "verified"
            return result
    except (OSError, ValueError) as exc:
        result["error"] = f"open_or_io_failed: {exc}"
        return result


def discover_onstep_serial(
    *,
    preferred_bauds: Iterable[Any] | None = None,
    excluded_paths: Iterable[str] | None = None,
    ports: list[dict[str, str]] | None = None,
    timeout: float = ONSTEP_SERIAL_DISCOVERY_TIMEOUT_SECONDS,
    status_callback: Any = None,
    probe: Any = None,
) -> dict[str, Any]:
    """Probe attached USB serial devices and select only one verified OnStep."""
    candidates = list(
        ports if ports is not None else list_onstep_serial_ports(excluded_paths)
    )
    baud_order = onstep_serial_baud_probe_order(preferred_bauds)
    probe = probe or probe_onstep_serial_port
    started = time.monotonic()
    deadline = started + max(0.1, float(timeout))
    verified_by_target: dict[str, dict[str, Any]] = {}
    probable: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    timed_out = False

    for baud in baud_order:
        for candidate in candidates:
            target = str(candidate.get("resolved") or candidate.get("path") or "")
            if not target or target in verified_by_target:
                continue
            if time.monotonic() >= deadline:
                timed_out = True
                break
            path = str(candidate.get("path") or "")
            if callable(status_callback):
                status_callback(
                    {
                        "state": "scanning",
                        "candidate_count": len(candidates),
                        "verified_count": len(verified_by_target),
                        "current_port": path,
                        "current_baud": baud,
                    }
                )
            try:
                attempt = dict(probe(path, baud))
            except Exception as exc:
                attempt = {
                    "status": "rejected",
                    "path": path,
                    "baud": baud,
                    "error": f"probe_failed: {exc}",
                }
            attempt.setdefault("path", path)
            attempt.setdefault("baud", baud)
            attempt["resolved"] = target
            attempts.append(attempt)
            if attempt.get("status") == "verified":
                attempt["stable_path"] = path
                verified_by_target[target] = attempt
            elif attempt.get("status") == "probable":
                probable.append(attempt)
        if timed_out:
            break

    verified = list(verified_by_target.values())
    if timed_out:
        state = "timeout"
    elif len(verified) == 1:
        state = "found"
    elif len(verified) > 1:
        state = "ambiguous"
    else:
        state = "not_found"
    selected = verified[0] if state == "found" else None
    return {
        "ok": selected is not None,
        "state": state,
        "candidate_count": len(candidates),
        "verified_count": len(verified),
        "baud_order": baud_order,
        "selected": selected,
        "verified": verified,
        "probable": probable,
        "attempts": attempts,
        "elapsed_seconds": max(0.0, time.monotonic() - started),
    }


def is_local_indi_server_host(host: str) -> bool:
    """Return whether serial discovery can safely inspect this host's /dev."""
    normalized = str(host or "").strip().lower().strip("[]")
    if normalized in {"", "localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def normalize_onstep_connection_config(
    values: dict[str, Any] | None,
    source: str = "",
) -> dict[str, Any] | None:
    """Validate and normalize an OnStep USB/TCP transport description."""
    if not isinstance(values, dict):
        return None
    connection_type = str(values.get("connection_type", "")).strip().lower()
    if connection_type not in {ONSTEP_CONNECTION_USB, ONSTEP_CONNECTION_NETWORK}:
        return None

    serial_port = str(values.get("serial_port", "") or "").strip()
    network_host = str(values.get("network_host", "") or "").strip()
    if connection_type == ONSTEP_CONNECTION_USB:
        if not serial_port.startswith("/dev/"):
            return None
        try:
            serial_baud = int(values.get("serial_baud", DEFAULT_ONSTEP_SERIAL_BAUD))
        except (TypeError, ValueError):
            return None
        if serial_baud not in ONSTEP_SERIAL_BAUD_RATES:
            return None
        try:
            network_port = int(values.get("network_port", DEFAULT_ONSTEP_NETWORK_PORT))
        except (TypeError, ValueError):
            network_port = DEFAULT_ONSTEP_NETWORK_PORT
    else:
        try:
            network_port = int(values.get("network_port", DEFAULT_ONSTEP_NETWORK_PORT))
        except (TypeError, ValueError):
            return None
        if not network_host or not 1 <= network_port <= 65535:
            return None
        try:
            serial_baud = int(values.get("serial_baud", DEFAULT_ONSTEP_SERIAL_BAUD))
        except (TypeError, ValueError):
            serial_baud = DEFAULT_ONSTEP_SERIAL_BAUD
        if serial_baud not in ONSTEP_SERIAL_BAUD_RATES:
            serial_baud = DEFAULT_ONSTEP_SERIAL_BAUD

    return {
        "connection_type": connection_type,
        "serial_port": serial_port,
        "serial_baud": serial_baud,
        "network_host": network_host,
        "network_port": network_port,
        "source": source or str(values.get("source", "") or ""),
        "verified": bool(values.get("verified", False)),
    }


def _onstep_property_value(
    properties: dict[str, str], device_name: str, property_name: str
) -> str:
    return str(properties.get(f"{device_name}.{property_name}", "") or "").strip()


def parse_indi_onstep_connection_properties(
    properties: dict[str, str],
    device_name: str | None = None,
) -> dict[str, Any] | None:
    """Read the effective OnStep transport from live INDI properties."""
    device_name = resolve_indi_device_name(device_name)
    serial_on = (
        _onstep_property_value(
            properties, device_name, "CONNECTION_MODE.CONNECTION_SERIAL"
        ).lower()
        == "on"
    )
    tcp_on = (
        _onstep_property_value(
            properties, device_name, "CONNECTION_MODE.CONNECTION_TCP"
        ).lower()
        == "on"
    )
    if serial_on == tcp_on:
        return None

    selected_baud: int | None = None
    for candidate in ONSTEP_SERIAL_BAUD_RATES:
        if (
            _onstep_property_value(
                properties, device_name, f"DEVICE_BAUD_RATE.{candidate}"
            ).lower()
            == "on"
        ):
            selected_baud = candidate
            break
    if serial_on and selected_baud is None:
        return None

    values = {
        "connection_type": (
            ONSTEP_CONNECTION_USB if serial_on else ONSTEP_CONNECTION_NETWORK
        ),
        "serial_port": _onstep_property_value(
            properties, device_name, "DEVICE_PORT.PORT"
        ),
        "serial_baud": selected_baud or DEFAULT_ONSTEP_SERIAL_BAUD,
        "network_host": _onstep_property_value(
            properties, device_name, "DEVICE_ADDRESS.ADDRESS"
        ),
        "network_port": _onstep_property_value(
            properties, device_name, "DEVICE_ADDRESS.PORT"
        )
        or DEFAULT_ONSTEP_NETWORK_PORT,
        "verified": True,
    }
    return normalize_onstep_connection_config(values, source="indi_live")


def _indi_xml_element_value(
    root: ET.Element,
    vector_name: str,
    element_name: str,
    device_name: str,
) -> str:
    for vector in root.iter():
        if vector.attrib.get("name") != vector_name:
            continue
        vector_device = vector.attrib.get("device", "").strip()
        if vector_device and vector_device != device_name:
            continue
        for element in vector:
            if element.attrib.get("name") == element_name:
                return (element.text or "").strip()
    return ""


def read_saved_indi_onstep_connection_config(
    device_name: str | None = None,
    config_path: Any = None,
) -> dict[str, Any] | None:
    """Read the OnStep transport persisted by INDI CONFIG_SAVE."""
    device_name = resolve_indi_device_name(device_name)
    if not device_name or "/" in device_name or "\\" in device_name:
        return None
    path = (
        config_path
        if config_path is not None
        else utils.home_dir / ".indi" / f"{device_name}_config.xml"
    )
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    xml_devices = {
        element.attrib.get("device", "").strip()
        for element in root.iter()
        if element.attrib.get("device", "").strip()
    }
    if xml_devices and device_name not in xml_devices:
        return None

    serial_on = (
        _indi_xml_element_value(
            root, "CONNECTION_MODE", "CONNECTION_SERIAL", device_name
        ).lower()
        == "on"
    )
    tcp_on = (
        _indi_xml_element_value(
            root, "CONNECTION_MODE", "CONNECTION_TCP", device_name
        ).lower()
        == "on"
    )
    if serial_on == tcp_on:
        return None

    selected_baud: int | None = None
    for candidate in ONSTEP_SERIAL_BAUD_RATES:
        if (
            _indi_xml_element_value(
                root, "DEVICE_BAUD_RATE", str(candidate), device_name
            ).lower()
            == "on"
        ):
            selected_baud = candidate
            break
    if serial_on and selected_baud is None:
        return None

    values = {
        "connection_type": (
            ONSTEP_CONNECTION_USB if serial_on else ONSTEP_CONNECTION_NETWORK
        ),
        "serial_port": _indi_xml_element_value(
            root, "DEVICE_PORT", "PORT", device_name
        ),
        "serial_baud": selected_baud or DEFAULT_ONSTEP_SERIAL_BAUD,
        "network_host": _indi_xml_element_value(
            root, "DEVICE_ADDRESS", "ADDRESS", device_name
        ),
        "network_port": _indi_xml_element_value(
            root, "DEVICE_ADDRESS", "PORT", device_name
        )
        or DEFAULT_ONSTEP_NETWORK_PORT,
        "verified": True,
    }
    return normalize_onstep_connection_config(values, source="indi_xml")


def onstep_connection_configs_match(
    left: dict[str, Any] | None, right: dict[str, Any] | None
) -> bool:
    """Compare only the fields active for the selected transport."""
    left_normalized = normalize_onstep_connection_config(left)
    right_normalized = normalize_onstep_connection_config(right)
    if left_normalized is None or right_normalized is None:
        return False
    if left_normalized["connection_type"] != right_normalized["connection_type"]:
        return False
    if left_normalized["connection_type"] == ONSTEP_CONNECTION_USB:
        keys = ("serial_port", "serial_baud")
    else:
        keys = ("network_host", "network_port")
    return all(left_normalized[key] == right_normalized[key] for key in keys)


def onstep_connection_mirror_options(
    connection: dict[str, Any],
) -> dict[str, Any]:
    """Build the persistent MFNavis mirror keys for an effective transport."""
    normalized = normalize_onstep_connection_config(connection)
    if normalized is None:
        raise ValueError("Invalid OnStep connection configuration")
    options: dict[str, Any] = {"onstep_connection_type": normalized["connection_type"]}
    if normalized["connection_type"] == ONSTEP_CONNECTION_USB:
        options.update(
            {
                "onstep_serial_port": normalized["serial_port"],
                "onstep_serial_baud": normalized["serial_baud"],
            }
        )
    else:
        options.update(
            {
                "onstep_network_host": normalized["network_host"],
                "onstep_network_port": normalized["network_port"],
            }
        )
    return options


def _run_indi_command(
    args: list[str], timeout: float = 5.0
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def get_indi_onstep_properties(
    server_host: str = DEFAULT_INDI_SERVER_HOST,
    server_port: int = DEFAULT_INDI_SERVER_PORT,
    device_name: str | None = None,
) -> dict[str, str]:
    device_name = resolve_indi_device_name(device_name)
    property_names = [
        f"{device_name}.{property_name}" for property_name in ONSTEP_DISPLAY_PROPERTIES
    ]
    try:
        result = _run_indi_command(
            [
                INDI_GETPROP_COMMAND,
                "-h",
                server_host,
                "-p",
                str(server_port),
                "-t",
                "1",
                *property_names,
            ],
            timeout=5.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    prefix = f"{device_name}."
    properties: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line.startswith(prefix) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key] = value
    return properties


def apply_indi_onstep_connection(
    connection_type: str,
    serial_port: str = "",
    serial_baud: int = DEFAULT_ONSTEP_SERIAL_BAUD,
    network_host: str = "",
    network_port: int = DEFAULT_ONSTEP_NETWORK_PORT,
    server_host: str = DEFAULT_INDI_SERVER_HOST,
    server_port: int = DEFAULT_INDI_SERVER_PORT,
    device_name: str | None = None,
    save_config: bool = True,
) -> dict[str, Any]:
    device_name = resolve_indi_device_name(device_name)
    connection_type = connection_type.strip().lower()
    if connection_type not in {ONSTEP_CONNECTION_USB, ONSTEP_CONNECTION_NETWORK}:
        raise ValueError("Invalid OnStep connection type")

    if connection_type == ONSTEP_CONNECTION_USB:
        if not serial_port.strip().startswith("/dev/"):
            raise ValueError("USB serial port must be a /dev path")
        serial_baud = int(serial_baud)
        if serial_baud not in ONSTEP_SERIAL_BAUD_RATES:
            raise ValueError("Unsupported USB serial baud rate")
        config_properties = [
            f"{device_name}.CONNECTION_MODE.CONNECTION_SERIAL=On",
            f"{device_name}.DEVICE_PORT.PORT={serial_port.strip()}",
            f"{device_name}.DEVICE_BAUD_RATE.{serial_baud}=On",
        ]
    else:
        if not network_host.strip():
            raise ValueError("Network host/IP is required")
        if not (1 <= int(network_port) <= 65535):
            raise ValueError("Network port must be between 1 and 65535")
        config_properties = [
            f"{device_name}.CONNECTION_MODE.CONNECTION_TCP=On",
            f"{device_name}.CONNECTION_TYPE.TCP=On",
            f"{device_name}.DEVICE_ADDRESS.ADDRESS={network_host.strip()}",
            f"{device_name}.DEVICE_ADDRESS.PORT={int(network_port)}",
        ]

    def _setprop(properties: list) -> subprocess.CompletedProcess:
        try:
            return _run_indi_command(
                [
                    INDI_SETPROP_COMMAND,
                    "-h",
                    server_host,
                    "-p",
                    str(server_port),
                    *properties,
                ],
                timeout=10.0,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("indi_setprop is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Timed out while applying INDI OnStep settings") from exc

    def _connect_state() -> str:
        try:
            result = _run_indi_command(
                [
                    INDI_GETPROP_COMMAND,
                    "-h",
                    server_host,
                    "-p",
                    str(server_port),
                    "-t",
                    "1",
                    f"{device_name}.CONNECTION.CONNECT",
                ],
                timeout=5.0,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
        for line in result.stdout.splitlines():
            if "=" in line:
                return line.split("=", 1)[1].strip()
        return ""

    def _wait_for_connect(deadline_seconds: float) -> bool:
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            if _connect_state() == "On":
                return True
            time.sleep(1.0)
        return _connect_state() == "On"

    # The OnStepX driver fails to (re)connect when disconnect, address changes
    # and CONNECT=On arrive in a single indi_setprop batch, leaving CONNECT
    # stuck Off while the settings apply. Stage the commands instead: settle
    # the disconnect, apply the connection settings, then connect and verify
    # (with one retry) before persisting via CONFIG_SAVE.
    applied_properties = [f"{device_name}.CONNECTION.DISCONNECT=On"]
    result = _setprop(applied_properties[-1:])
    if result.returncode != 0:
        return {
            "ok": False,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "properties": applied_properties,
        }
    time.sleep(1.0)

    result = _setprop(config_properties)
    applied_properties.extend(config_properties)
    if result.returncode != 0:
        return {
            "ok": False,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "properties": applied_properties,
        }
    time.sleep(0.5)

    connected = False
    for _attempt in range(2):
        result = _setprop([f"{device_name}.CONNECTION.CONNECT=On"])
        applied_properties.append(f"{device_name}.CONNECTION.CONNECT=On")
        if result.returncode == 0 and _wait_for_connect(8.0):
            connected = True
            break
        time.sleep(1.0)

    if not connected:
        return {
            "ok": False,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
            or f"{device_name} did not connect with the applied settings",
            "properties": applied_properties,
        }

    requested = normalize_onstep_connection_config(
        {
            "connection_type": connection_type,
            "serial_port": serial_port,
            "serial_baud": serial_baud,
            "network_host": network_host,
            "network_port": network_port,
        }
    )
    live = parse_indi_onstep_connection_properties(
        get_indi_onstep_properties(
            server_host=server_host,
            server_port=server_port,
            device_name=device_name,
        ),
        device_name=device_name,
    )
    if not onstep_connection_configs_match(live, requested):
        return {
            "ok": False,
            "returncode": 1,
            "stdout": result.stdout,
            "stderr": "INDI connection readback does not match applied settings",
            "properties": applied_properties,
        }

    if save_config:
        save_result = _setprop([f"{device_name}.CONFIG_PROCESS.CONFIG_SAVE=On"])
        applied_properties.append(f"{device_name}.CONFIG_PROCESS.CONFIG_SAVE=On")
        if save_result.returncode != 0:
            return {
                "ok": False,
                "returncode": save_result.returncode,
                "stdout": save_result.stdout,
                "stderr": save_result.stderr or "INDI CONFIG_SAVE failed after connect",
                "properties": applied_properties,
            }

    return {
        "ok": True,
        "returncode": 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "properties": applied_properties,
    }


def apply_indi_onstep_properties(
    properties: list[str],
    server_host: str = DEFAULT_INDI_SERVER_HOST,
    server_port: int = DEFAULT_INDI_SERVER_PORT,
) -> dict[str, Any]:
    if not properties:
        raise ValueError("No INDI properties were provided")

    try:
        result = _run_indi_command(
            [
                INDI_SETPROP_COMMAND,
                "-h",
                server_host,
                "-p",
                str(server_port),
                *properties,
            ],
            timeout=10.0,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("indi_setprop is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Timed out while applying INDI properties") from exc

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "properties": properties,
    }


def apply_indi_onstep_backlash(
    backlash_ra: int,
    backlash_de: int,
    server_host: str = DEFAULT_INDI_SERVER_HOST,
    server_port: int = DEFAULT_INDI_SERVER_PORT,
    device_name: str | None = None,
) -> dict[str, Any]:
    """
    Apply OnStep backlash as a full INDI number vector.

    LX200 OnStep expects both Backlash vector elements in the same update before
    it sends :$BD/:$BR to the controller. Some indi_setprop versions send the
    elements one at a time, so use PyIndi here just like location/time sync.
    """
    device_name = resolve_indi_device_name(device_name)
    backlash_ra = int(backlash_ra)
    backlash_de = int(backlash_de)
    properties = [
        f"{device_name}.{ONSTEP_BACKLASH_RA_PROPERTY}={backlash_ra}",
        f"{device_name}.{ONSTEP_BACKLASH_DE_PROPERTY}={backlash_de}",
    ]

    if importlib.util.find_spec("PyIndi") is None:
        raise RuntimeError("PyIndi is not installed")
    from PiFinder.mountcontrol_indi import PiFinderIndiClient

    client = PiFinderIndiClient()
    client.setServer(server_host, server_port)
    if not client.connectServer():
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": f"Could not connect to INDI server {server_host}:{server_port}",
            "properties": properties,
        }

    try:
        start = time.time()
        device = None
        while time.time() - start < 10.0:
            if hasattr(client, "getDevice"):
                try:
                    device = client.getDevice(device_name)
                except Exception:
                    device = None
                try:
                    if device is not None and device.getDeviceName() != device_name:
                        device = None
                except Exception:
                    device = None
            if device is None:
                device = client.get_telescope_device()
                try:
                    if device is not None and device.getDeviceName() != device_name:
                        device = None
                except Exception:
                    device = None
            if device is not None:
                break
            time.sleep(0.2)

        if device is None:
            return {
                "ok": False,
                "returncode": 1,
                "stdout": "",
                "stderr": f"Could not find INDI device {device_name}",
                "properties": properties,
            }

        if not client.set_number(
            device,
            "Backlash",
            {"Backlash RA": float(backlash_ra), "Backlash DEC": float(backlash_de)},
        ):
            return {
                "ok": False,
                "returncode": 1,
                "stdout": "",
                "stderr": "Could not set INDI Backlash vector",
                "properties": properties,
            }

        return {
            "ok": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "properties": properties,
        }
    finally:
        client.disconnectServer()


def apply_indi_onstep_location_time(
    latitude: float | None = None,
    longitude: float | None = None,
    elevation: float | None = None,
    utc_datetime: Any = None,
    utc_offset_hours: float | None = None,
    server_host: str = DEFAULT_INDI_SERVER_HOST,
    server_port: int = DEFAULT_INDI_SERVER_PORT,
    device_name: str | None = None,
) -> dict[str, Any]:
    """
    Apply OnStep location/time using PyIndi vector updates.

    indi_setprop sends number/text elements as individual updates on some
    versions, which can zero unspecified GEOGRAPHIC_COORD elements. PyIndi keeps
    the full vector intact, matching the live PiFinder INDI client path.
    """
    device_name = resolve_indi_device_name(device_name)
    properties = build_indi_location_time_properties(
        latitude=latitude,
        longitude=longitude,
        elevation=elevation,
        utc_datetime=utc_datetime,
        utc_offset_hours=utc_offset_hours,
        device_name=device_name,
    )
    if not properties:
        raise ValueError("No INDI location/time values were provided")

    if importlib.util.find_spec("PyIndi") is None:
        raise RuntimeError("PyIndi is not installed")
    from PiFinder.mountcontrol_indi import PiFinderIndiClient

    coord_values: dict[str, float] = {}
    if latitude is not None and longitude is not None:
        coord_values = {
            "LAT": float(latitude),
            "LONG": onstep_longitude_degrees(float(longitude)),
        }
        if elevation is not None:
            coord_values["ELEV"] = float(elevation)

    time_values: dict[str, str] = {}
    if utc_datetime is not None:
        utc_dt = parse_indi_utc_datetime(utc_datetime)
        offset_hours = (
            local_utc_offset_hours(utc_dt)
            if utc_offset_hours is None
            else float(utc_offset_hours)
        )
        time_values = {
            "UTC": utc_dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S"),
            "OFFSET": f"{offset_hours:.2f}",
        }

    client = PiFinderIndiClient()
    client.setServer(server_host, server_port)
    if not client.connectServer():
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": f"Could not connect to INDI server {server_host}:{server_port}",
            "properties": properties,
        }

    try:
        start = time.time()
        device = None
        while time.time() - start < 10.0:
            if hasattr(client, "getDevice"):
                try:
                    device = client.getDevice(device_name)
                except Exception:
                    device = None
                try:
                    if device is not None and device.getDeviceName() != device_name:
                        device = None
                except Exception:
                    device = None
            if device is None:
                device = client.get_telescope_device()
                try:
                    if device is not None and device.getDeviceName() != device_name:
                        device = None
                except Exception:
                    device = None
            if device is not None:
                break
            time.sleep(0.2)

        if device is None:
            return {
                "ok": False,
                "returncode": 1,
                "stdout": "",
                "stderr": f"Could not find INDI device {device_name}",
                "properties": properties,
            }

        if client._wait_for_property(device, "CONNECTION", timeout=2.0):
            try:
                connected = bool(device.isConnected())
            except Exception:
                connected = False
            if not connected:
                if not client.set_switch(device, "CONNECTION", "CONNECT"):
                    return {
                        "ok": False,
                        "returncode": 1,
                        "stdout": "",
                        "stderr": f"Could not connect INDI device {device_name}",
                        "properties": properties,
                    }
                start = time.time()
                while time.time() - start < 8.0:
                    try:
                        if device.isConnected():
                            break
                    except Exception:
                        pass
                    time.sleep(0.2)

        if coord_values and not client.set_number(
            device, "GEOGRAPHIC_COORD", coord_values
        ):
            return {
                "ok": False,
                "returncode": 1,
                "stdout": "",
                "stderr": "Could not set INDI GEOGRAPHIC_COORD",
                "properties": properties,
            }
        if time_values and not client.set_text(device, "TIME_UTC", time_values):
            return {
                "ok": False,
                "returncode": 1,
                "stdout": "",
                "stderr": "Could not set INDI TIME_UTC",
                "properties": properties,
            }
        return {
            "ok": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "properties": properties,
        }
    finally:
        client.disconnectServer()


def restart_indi_web_manager(timeout: float = 30.0) -> dict[str, Any]:
    """Restart INDI Web Manager, which also restarts indiserver and drivers."""
    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", INDI_WEB_MANAGER_SERVICE],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("systemctl or sudo is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Timed out while restarting INDI Web Manager") from exc

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "service": INDI_WEB_MANAGER_SERVICE,
    }


def set_indi_web_manager_running(
    action: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Start or stop INDI Web Manager."""
    if action not in {"start", "stop"}:
        raise ValueError("action must be start or stop")

    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", action, INDI_WEB_MANAGER_SERVICE],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("systemctl or sudo is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Timed out while running {action} on INDI Web Manager"
        ) from exc

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "service": INDI_WEB_MANAGER_SERVICE,
        "action": action,
    }


def _send_onstep_lx200_network_commands(
    host: str,
    port: int,
    commands: list[str],
    timeout: float = 4.0,
) -> list[dict[str, str]]:
    responses = []
    with socket.create_connection((host, int(port)), timeout=timeout) as sock:
        sock.settimeout(1.0)
        for command in commands:
            sock.sendall(command.encode("ascii"))
            try:
                response = sock.recv(64).decode("ascii", errors="replace")
            except (TimeoutError, socket.timeout):
                response = ""
            responses.append({"command": command, "response": response})
            time.sleep(0.1)
    return responses


def _send_onstep_lx200_serial_commands(
    serial_port: str,
    commands: list[str],
    baudrate: int = 9600,
) -> list[dict[str, str]]:
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("pyserial is not installed") from exc

    responses = []
    serial_class = _serial_class_without_modem_control(serial.Serial)
    with serial_class(
        serial_port, baudrate=baudrate, timeout=1, write_timeout=2
    ) as ser:
        for command in commands:
            ser.write(command.encode("ascii"))
            ser.flush()
            response = ser.read(64).decode("ascii", errors="replace")
            responses.append({"command": command, "response": response})
            time.sleep(0.1)
    return responses


def sync_onstep_location_time_exclusive(
    connection_type: str,
    latitude: float,
    longitude: float,
    utc_datetime: Any,
    network_host: str = "",
    network_port: int = DEFAULT_ONSTEP_NETWORK_PORT,
    serial_port: str = "",
    serial_baud: int = DEFAULT_ONSTEP_SERIAL_BAUD,
    server_host: str = DEFAULT_INDI_SERVER_HOST,
    server_port: int = DEFAULT_INDI_SERVER_PORT,
    elevation: float | None = None,
) -> dict[str, Any]:
    """
    Stop INDI, send LX200 site/time commands directly, then restart INDI.

    This is intentionally exclusive because OnStep TCP/serial ports should not be
    shared with the running LX200 OnStepX INDI driver.
    """
    commands = build_onstep_lx200_location_time_commands(
        latitude=latitude,
        longitude=longitude,
        utc_datetime=utc_datetime,
        elevation=elevation,
    )
    result: dict[str, Any] = {
        "ok": False,
        "commands": commands,
        "responses": [],
        "stop_result": None,
        "start_result": None,
        "connect_result": None,
        "elevation": elevation,
    }

    stop_result = set_indi_web_manager_running("stop")
    result["stop_result"] = stop_result
    if not stop_result["ok"]:
        result["stderr"] = (
            stop_result.get("stderr") or "Could not stop INDI Web Manager"
        )
        return result

    try:
        time.sleep(1.0)
        connection_type = connection_type.strip().lower()
        if connection_type == ONSTEP_CONNECTION_USB:
            if not serial_port:
                raise RuntimeError("No OnStep serial port configured")
            responses = _send_onstep_lx200_serial_commands(
                serial_port, commands, baudrate=int(serial_baud)
            )
        else:
            if not network_host:
                raise RuntimeError("No OnStep network host configured")
            responses = _send_onstep_lx200_network_commands(
                network_host,
                int(network_port),
                commands,
            )
        result["responses"] = responses
        failed_responses = [
            item
            for item in responses
            if str(item.get("response", "")).strip("#") != "1"
        ]
        if failed_responses:
            raise RuntimeError(
                "OnStep rejected LX200 site/time command(s): "
                + ", ".join(
                    f"{item['command']} -> {item.get('response', '') or '<no reply>'}"
                    for item in failed_responses
                )
            )
        result["ok"] = True
    except Exception as exc:
        result["stderr"] = str(exc)
    finally:
        start_result = set_indi_web_manager_running("start")
        result["start_result"] = start_result
        if start_result["ok"]:
            time.sleep(3.0)
            result["connect_result"] = connect_indi_onstep_driver(
                server_host=server_host,
                server_port=server_port,
            )

    if not result["ok"]:
        return result
    if result["start_result"] and not result["start_result"].get("ok"):
        result["ok"] = False
        result["stderr"] = (
            result["start_result"].get("stderr") or "Could not restart INDI"
        )
    elif result["connect_result"] and not result["connect_result"].get("ok"):
        result["ok"] = False
        result["stderr"] = (
            result["connect_result"].get("stderr")
            or result["connect_result"].get("stdout")
            or "Could not reconnect INDI OnStep driver"
        )
    return result


def reset_onstep_alignment_exclusive(
    connection_type: str,
    network_host: str = "",
    network_port: int = DEFAULT_ONSTEP_NETWORK_PORT,
    serial_port: str = "",
    serial_baud: int = DEFAULT_ONSTEP_SERIAL_BAUD,
    server_host: str = DEFAULT_INDI_SERVER_HOST,
    server_port: int = DEFAULT_INDI_SERVER_PORT,
) -> dict[str, Any]:
    """
    Stop INDI, reset OnStep alignment state with LX200, then restart INDI.

    This is used before PiFinder-managed multi-point alignment so a stale
    OnStep native ``:A<n>#`` session cannot reinterpret normal sync commands as
    native align-point accepts.
    """
    commands = [":A?#", ":SX09,0#", ":A?#"]
    result: dict[str, Any] = {
        "ok": False,
        "commands": commands,
        "responses": [],
        "stop_result": None,
        "start_result": None,
        "connect_result": None,
    }

    stop_result = set_indi_web_manager_running("stop")
    result["stop_result"] = stop_result
    if not stop_result["ok"]:
        result["stderr"] = (
            stop_result.get("stderr") or "Could not stop INDI Web Manager"
        )
        return result

    try:
        time.sleep(1.0)
        connection_type = connection_type.strip().lower()
        if connection_type == ONSTEP_CONNECTION_USB:
            if not serial_port:
                raise RuntimeError("No OnStep serial port configured")
            responses = _send_onstep_lx200_serial_commands(
                serial_port, commands, baudrate=int(serial_baud)
            )
        else:
            if not network_host:
                raise RuntimeError("No OnStep network host configured")
            responses = _send_onstep_lx200_network_commands(
                network_host,
                int(network_port),
                commands,
            )
        result["responses"] = responses
        reset_response = responses[1].get("response", "") if len(responses) > 1 else ""
        if str(reset_response).strip("#") != "1":
            raise RuntimeError(
                "OnStep rejected alignment reset command: "
                f":SX09,0# -> {reset_response or '<no reply>'}"
            )
        result["ok"] = True
    except Exception as exc:
        result["stderr"] = str(exc)
    finally:
        start_result = set_indi_web_manager_running("start")
        result["start_result"] = start_result
        if start_result["ok"]:
            time.sleep(3.0)
            result["connect_result"] = connect_indi_onstep_driver(
                server_host=server_host,
                server_port=server_port,
            )

    if not result["ok"]:
        return result
    if result["start_result"] and not result["start_result"].get("ok"):
        result["ok"] = False
        result["stderr"] = (
            result["start_result"].get("stderr") or "Could not restart INDI"
        )
    elif result["connect_result"] and not result["connect_result"].get("ok"):
        result["ok"] = False
        result["stderr"] = (
            result["connect_result"].get("stderr")
            or result["connect_result"].get("stdout")
            or "Could not reconnect INDI OnStep driver"
        )
    return result


# OnStepX reboot (:ERESET#) timing, measured 2026-07-18: the controller drops
# off the network for ~35s. Wait for it to actually go down before probing so
# a not-yet-rebooted controller cannot answer the readiness probe.
ONSTEP_REBOOT_SETTLE_SECONDS = 10.0
ONSTEP_REBOOT_WAIT_SECONDS = 90.0


def _wait_for_onstep_network_ready(
    host: str,
    port: int,
    timeout: float = ONSTEP_REBOOT_WAIT_SECONDS,
) -> bool:
    """Wait for the OnStep TCP command port to accept connections again."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, int(port)), timeout=2.0):
                return True
        except OSError:
            time.sleep(2.0)
    return False


def reboot_onstep_controller_exclusive(
    connection_type: str,
    network_host: str = "",
    network_port: int = DEFAULT_ONSTEP_NETWORK_PORT,
    serial_port: str = "",
    serial_baud: int = DEFAULT_ONSTEP_SERIAL_BAUD,
    server_host: str = DEFAULT_INDI_SERVER_HOST,
    server_port: int = DEFAULT_INDI_SERVER_PORT,
) -> dict[str, Any]:
    """
    Stop INDI, send the OnStepX ``:ERESET#`` reboot command directly, wait for
    the controller to come back, then restart INDI and reconnect the driver.

    This is the verified recovery for the wedged OnStepX state where
    sync/GoTo/tracking commands are refused while manual moves still work (see
    docs/mf_report/mf_goto_tracking_recovery_analysis_ko.md). The controller loses
    date/time on reboot (no RTC), so the caller must re-run the mount init
    (location/time sync, unpark, tracking) after this returns.
    """
    commands = [":ERESET#"]
    result: dict[str, Any] = {
        "ok": False,
        "commands": commands,
        "responses": [],
        "stop_result": None,
        "start_result": None,
        "connect_result": None,
    }

    stop_result = set_indi_web_manager_running("stop")
    result["stop_result"] = stop_result
    if not stop_result["ok"]:
        result["stderr"] = (
            stop_result.get("stderr") or "Could not stop INDI Web Manager"
        )
        return result

    try:
        time.sleep(1.0)
        connection_type = connection_type.strip().lower()
        if connection_type == ONSTEP_CONNECTION_USB:
            if not serial_port:
                raise RuntimeError("No OnStep serial port configured")
            # :ERESET# has no reply; the controller reboots immediately.
            result["responses"] = _send_onstep_lx200_serial_commands(
                serial_port, commands, baudrate=int(serial_baud)
            )
            time.sleep(ONSTEP_REBOOT_SETTLE_SECONDS + ONSTEP_REBOOT_WAIT_SECONDS / 2)
        else:
            if not network_host:
                raise RuntimeError("No OnStep network host configured")
            result["responses"] = _send_onstep_lx200_network_commands(
                network_host,
                int(network_port),
                commands,
            )
            time.sleep(ONSTEP_REBOOT_SETTLE_SECONDS)
            if not _wait_for_onstep_network_ready(network_host, int(network_port)):
                raise RuntimeError(
                    "OnStep controller did not come back after reboot "
                    f"({network_host}:{network_port})"
                )
        result["ok"] = True
    except Exception as exc:
        result["stderr"] = str(exc)
    finally:
        start_result = set_indi_web_manager_running("start")
        result["start_result"] = start_result
        if start_result["ok"]:
            time.sleep(3.0)
            result["connect_result"] = connect_indi_onstep_driver(
                server_host=server_host,
                server_port=server_port,
            )

    if not result["ok"]:
        return result
    if result["start_result"] and not result["start_result"].get("ok"):
        result["ok"] = False
        result["stderr"] = (
            result["start_result"].get("stderr") or "Could not restart INDI"
        )
    elif result["connect_result"] and not result["connect_result"].get("ok"):
        result["ok"] = False
        result["stderr"] = (
            result["connect_result"].get("stderr")
            or result["connect_result"].get("stdout")
            or "Could not reconnect INDI OnStep driver"
        )
    return result


def connect_indi_onstep_driver(
    server_host: str = DEFAULT_INDI_SERVER_HOST,
    server_port: int = DEFAULT_INDI_SERVER_PORT,
    device_name: str | None = None,
    wait_timeout: float = 15.0,
) -> dict[str, Any]:
    """Wait for the active INDI telescope driver and request CONNECTION.CONNECT."""
    device_name = resolve_indi_device_name(device_name)
    property_deadline = time.monotonic() + wait_timeout
    properties: dict[str, str] = {}
    while time.monotonic() < property_deadline:
        properties = get_indi_onstep_properties(
            server_host=server_host,
            server_port=server_port,
            device_name=device_name,
        )
        if f"{device_name}.CONNECTION.CONNECT" in properties:
            break
        time.sleep(0.5)

    if f"{device_name}.CONNECTION.CONNECT" not in properties:
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": f"{device_name} CONNECTION property was not available",
            "properties": [],
        }

    if properties.get(f"{device_name}.CONNECTION.CONNECT") == "On":
        return {
            "ok": True,
            "returncode": 0,
            "stdout": f"{device_name} already connected",
            "stderr": "",
            "properties": [f"{device_name}.CONNECTION.CONNECT=On"],
        }

    result = apply_indi_onstep_properties(
        [f"{device_name}.CONNECTION.CONNECT=On"],
        server_host=server_host,
        server_port=server_port,
    )
    if not result.get("ok"):
        return result

    connect_deadline = time.monotonic() + wait_timeout
    while time.monotonic() < connect_deadline:
        properties = get_indi_onstep_properties(
            server_host=server_host,
            server_port=server_port,
            device_name=device_name,
        )
        if properties.get(f"{device_name}.CONNECTION.CONNECT") == "On":
            result["verified"] = True
            return result
        time.sleep(0.5)

    result["ok"] = False
    result["stderr"] = (
        result.get("stderr")
        or f"{device_name} did not enter connected state after CONNECT"
    )
    return result


class Network:
    """
    Provides wifi network info
    """

    def __init__(self):
        self._wifi_mode = utils.read_wifi_mode()

        # Saved-but-not-applied STA edits (add/delete/reorder/band). Edits only
        # rewrite config files; the disruptive part (NetworkManager profile
        # sync + wpa reconfigure) waits for apply_sta_changes() so editing the
        # list cannot drop the connection the editor is using.
        self.sta_dirty = False

        # Outcome of the most recent background STA switch (see
        # connect_wifi_network); shown as a banner on the next page render.
        self._last_connect_result: dict[str, Any] | None = None

        self.populate_wifi_networks()

    def get_last_connect_result(self) -> dict[str, Any] | None:
        return self._last_connect_result

    def populate_wifi_networks(self) -> None:
        self._wifi_networks = []

        parsed_networks = []
        for path in [WPA_SUPPLICANT_PATH, *BOOT_WPA_SUPPLICANT_PATHS]:
            try:
                with open(path, "r") as wpa_conf:
                    parsed_networks.extend(Network._parse_wpa_supplicant(wpa_conf))
            except FileNotFoundError:
                if path == WPA_SUPPLICANT_PATH:
                    logger.info("wpa_supplicant.conf not found")
                continue
            except IOError as e:
                logger.error(f"Error reading {path}: {e}")

        for path in glob.glob(NETWORKMANAGER_CONNECTION_GLOB):
            try:
                with open(path, "r") as nm_conf:
                    parsed = Network._parse_networkmanager_connection(nm_conf.read())
                    if parsed:
                        parsed_networks.append(parsed)
            except PermissionError:
                logger.info(
                    "Skipping unreadable NetworkManager connection %s; "
                    "setup migration imports these profiles when run with sudo",
                    path,
                )
            except IOError as e:
                logger.error(f"Error reading NetworkManager connection {path}: {e}")

        deduped = Network._dedupe_wifi_networks(parsed_networks)
        # Highest priority first; file order breaks ties. ids track list
        # position so the web routes' delete/move/connect stay aligned.
        deduped.sort(
            key=lambda network: -int(network.get("priority") or 0),
        )
        for index, network in enumerate(deduped):
            network["id"] = index
        self._wifi_networks = deduped

    @staticmethod
    def _dedupe_wifi_networks(networks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        wifi_networks: list[dict[str, Any]] = []
        seen_ssids = set()
        for network in networks:
            ssid = (network.get("ssid") or "").strip()
            if not ssid or ssid in seen_ssids:
                continue
            key_mgmt = network.get("key_mgmt") or "NONE"
            wifi_networks.append(
                {
                    "id": len(wifi_networks),
                    "ssid": ssid,
                    "psk": network.get("psk"),
                    "key_mgmt": key_mgmt,
                }
            )
            seen_ssids.add(ssid)
        return wifi_networks

    @staticmethod
    def _decode_networkmanager_ssid(ssid: str) -> str:
        ssid = ssid.strip()
        if (
            len(ssid) >= 2
            and len(ssid) % 2 == 0
            and re.fullmatch(r"[0-9A-Fa-f]+", ssid)
        ):
            try:
                decoded = bytes.fromhex(ssid).decode("utf-8")
                if decoded.isprintable():
                    return decoded
            except ValueError:
                pass
            except UnicodeDecodeError:
                pass
        return ssid.strip('"')

    @staticmethod
    def _parse_networkmanager_connection(contents: str) -> dict[str, Any] | None:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read_string(contents)
        except configparser.Error as e:
            logger.error(f"Error parsing NetworkManager connection: {e}")
            return None

        wifi_section = None
        for section in ("wifi", "802-11-wireless"):
            if parser.has_section(section):
                wifi_section = section
                break
        if not wifi_section:
            return None

        ssid = Network._decode_networkmanager_ssid(
            parser.get(wifi_section, "ssid", fallback="")
        )
        if not ssid:
            return None

        security_section = None
        for section in ("wifi-security", "802-11-wireless-security"):
            if parser.has_section(section):
                security_section = section
                break

        key_mgmt = "NONE"
        psk = None
        if security_section:
            nm_key_mgmt = parser.get(security_section, "key-mgmt", fallback="")
            psk = parser.get(security_section, "psk", fallback=None)
            if nm_key_mgmt.lower() in ("wpa-psk", "sae") and psk:
                key_mgmt = "WPA-PSK"
            elif nm_key_mgmt:
                key_mgmt = nm_key_mgmt.upper()

        return {"id": 0, "ssid": ssid, "psk": psk, "key_mgmt": key_mgmt}

    @staticmethod
    def _parse_wpa_supplicant(contents: Iterable[str]) -> list:
        """
        Parses wpa_supplicant.conf to get current config
        """
        wifi_networks = []
        network_dict: Dict[str, Any] = {}
        network_id = 0
        in_network_block = False
        for line in contents:
            line = line.strip()
            if line.startswith("network={"):
                in_network_block = True
                network_dict = {
                    "id": network_id,
                    "ssid": None,
                    "psk": None,
                    "key_mgmt": None,
                    "scan_freq": None,
                    "priority": None,
                }

            elif line == "}" and in_network_block:
                in_network_block = False
                wifi_networks.append(network_dict)
                network_id += 1

            elif in_network_block:
                match = re.match(r"(\w+)=(.+)", line)
                if match:
                    key, value = match.groups()
                    if key in network_dict:
                        network_dict[key] = value.strip('"')

        return wifi_networks

    def get_wifi_networks(self):
        return self._wifi_networks

    @staticmethod
    def _nmcli(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["sudo", "-n", NMCLI_COMMAND, *args],
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _networkmanager_active() -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "NetworkManager"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        return result.stdout.strip() == "active"

    @staticmethod
    def _nm_band_for_preference(preference: str) -> str:
        if preference == STA_BAND_24:
            return "bg"
        if preference == STA_BAND_5:
            return "a"
        return ""

    @staticmethod
    def _networkmanager_wifi_profiles() -> list[dict[str, str]]:
        if not Network._networkmanager_active():
            return []
        result = Network._nmcli(["-t", "-f", "NAME,TYPE", "con", "show"])
        if result.returncode != 0:
            logger.info("Unable to list NetworkManager profiles: %s", result.stderr)
            return []

        profiles = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            name, _, connection_type = line.partition(":")
            if connection_type not in ("802-11-wireless", "wifi"):
                continue
            ssid_result = Network._nmcli(
                ["-g", "802-11-wireless.ssid", "con", "show", name]
            )
            if ssid_result.returncode != 0:
                continue
            profiles.append({"name": name, "ssid": ssid_result.stdout.strip()})
        return profiles

    def _sync_networkmanager_profiles(self) -> None:
        """
        Mirror PiFinder's saved STA list into NetworkManager when Bookworm keeps
        wlan0 under NetworkManager control.
        """
        profiles = Network._networkmanager_wifi_profiles()
        if not profiles:
            return

        saved_by_ssid = {
            network["ssid"]: network
            for network in self._wifi_networks
            if network.get("ssid")
        }
        profile_by_ssid = {
            profile["ssid"]: profile for profile in profiles if profile.get("ssid")
        }

        for profile in profiles:
            if profile.get("ssid") not in saved_by_ssid:
                result = Network._nmcli(["con", "delete", profile["name"]])
                if result.returncode != 0:
                    logger.info(
                        "Unable to delete stale NetworkManager profile %s: %s",
                        profile["name"],
                        result.stderr,
                    )

        nm_band = Network._nm_band_for_preference(self.get_sta_band_preference())
        for ssid, network in saved_by_ssid.items():
            existing = profile_by_ssid.get(ssid)
            profile_name = existing["name"] if existing else f"MFNavis {ssid}"
            if not existing:
                result = Network._nmcli(
                    [
                        "con",
                        "add",
                        "type",
                        "wifi",
                        "ifname",
                        "wlan0",
                        "con-name",
                        profile_name,
                        "ssid",
                        ssid,
                    ]
                )
                if result.returncode != 0:
                    logger.info(
                        "Unable to create NetworkManager profile for %s: %s",
                        ssid,
                        result.stderr,
                    )
                    continue

            modify_args = [
                "con",
                "modify",
                profile_name,
                "connection.autoconnect",
                "yes",
                "connection.autoconnect-priority",
                str(int(network.get("priority") or 0)),
                "802-11-wireless.band",
                nm_band,
            ]
            if network.get("key_mgmt") == "WPA-PSK" and network.get("psk"):
                modify_args.extend(
                    [
                        "wifi-sec.key-mgmt",
                        "wpa-psk",
                        "wifi-sec.psk",
                        network["psk"],
                    ]
                )
            result = Network._nmcli(modify_args)
            if result.returncode != 0:
                logger.info(
                    "Unable to update NetworkManager profile %s: %s",
                    profile_name,
                    result.stderr,
                )

    @staticmethod
    def _sta_scan_freq_for_preference(preference: str) -> str | None:
        if preference == STA_BAND_24:
            return STA_24GHZ_SCAN_FREQ
        if preference == STA_BAND_5:
            return STA_5GHZ_SCAN_FREQ
        return None

    @staticmethod
    def _normalize_sta_band_preference(preference: str | None) -> str:
        preference = (preference or STA_BAND_AUTO).strip().lower()
        if preference in ("24", "2g", "2.4g", "2.4ghz", "2.4"):
            return STA_BAND_24
        if preference in ("5g", "5ghz", "5"):
            return STA_BAND_5
        if preference in ("auto", ""):
            return STA_BAND_AUTO
        raise ValueError("Unsupported STA band preference")

    @staticmethod
    def _rewrite_wpa_supplicant_band_preference(contents: str, preference: str) -> str:
        scan_freq = Network._sta_scan_freq_for_preference(preference)
        lines = contents.splitlines(keepends=True)
        output = []
        in_network = False
        added_scan_freq = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("network={"):
                in_network = True
                added_scan_freq = False
                output.append(line)
                continue

            if in_network and stripped.startswith("scan_freq="):
                continue

            if in_network and stripped == "}":
                if scan_freq and not added_scan_freq:
                    output.append(f"\tscan_freq={scan_freq}\n")
                    added_scan_freq = True
                output.append(line)
                in_network = False
                continue

            output.append(line)

        return "".join(output)

    def get_sta_band_preference(self):
        try:
            with open(MFNAVIS_STA_BAND_CONF_PATH, "r") as conf:
                for line in conf:
                    if line.startswith("MFNAVIS_STA_BAND="):
                        return Network._normalize_sta_band_preference(
                            line.split("=", 1)[1]
                        )
        except FileNotFoundError:
            return STA_BAND_AUTO
        except IOError as e:
            logger.error(f"Error reading STA band preference config: {e}")
        return STA_BAND_AUTO

    def _apply_sta_band_preference(self, preference: str) -> None:
        try:
            with open(WPA_SUPPLICANT_PATH, "r") as wpa_conf:
                contents = wpa_conf.read()
        except FileNotFoundError:
            contents = ""
        rewritten = Network._rewrite_wpa_supplicant_band_preference(
            contents, preference
        )
        with open(WPA_SUPPLICANT_PATH, "w") as wpa_conf:
            wpa_conf.write(rewritten)

    def set_sta_band_preference(self, preference):
        preference = Network._normalize_sta_band_preference(preference)
        contents = "# MFNavis STA band preference\n" f"MFNAVIS_STA_BAND={preference}\n"
        Network._write_root_file(MFNAVIS_STA_BAND_CONF_PATH, contents)
        self._apply_sta_band_preference(preference)
        self.populate_wifi_networks()
        # Saved-only; the NM sync + reconfigure happen in apply_sta_changes().
        self.sta_dirty = True

    @staticmethod
    def _quote_wpa_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _write_wpa_networks(self) -> None:
        """Rewrite every network block from self._wifi_networks (order kept)."""
        with open(WPA_SUPPLICANT_PATH, "r") as wpa_conf:
            wpa_contents = list(wpa_conf)

        with open(WPA_SUPPLICANT_PATH, "w") as wpa_conf:
            in_networks = False
            for line in wpa_contents:
                if not in_networks:
                    if line.startswith("network={"):
                        in_networks = True
                    else:
                        wpa_conf.write(line)

            for network in self._wifi_networks:
                ssid = Network._quote_wpa_value(network["ssid"])
                key_mgmt = network["key_mgmt"]
                psk = Network._quote_wpa_value(network["psk"] or "")
                scan_freq = Network._sta_scan_freq_for_preference(
                    self.get_sta_band_preference()
                )

                wpa_conf.write("\nnetwork={\n")
                wpa_conf.write(f'\tssid="{ssid}"\n')
                if key_mgmt == "WPA-PSK" and psk:
                    wpa_conf.write(f'\tpsk="{psk}"\n')
                wpa_conf.write(f"\tkey_mgmt={key_mgmt}\n")
                if scan_freq:
                    wpa_conf.write(f"\tscan_freq={scan_freq}\n")
                if network.get("priority"):
                    wpa_conf.write(f"\tpriority={int(network['priority'])}\n")

                wpa_conf.write("}\n")

    def delete_wifi_network(self, network_id):
        """
        Delete a saved wifi network. Saved to config only -- takes effect on
        apply_sta_changes() so editing cannot drop the current connection.
        """
        self._wifi_networks.pop(network_id)
        self._write_wpa_networks()
        self.populate_wifi_networks()
        self.sta_dirty = True

    def move_wifi_network(self, network_id: int, direction: str) -> None:
        """
        Move a saved network up/down in connection priority. Priorities are
        rewritten so the top of the list is preferred. Saved-only (see
        delete_wifi_network).
        """
        offset = -1 if direction == "up" else 1
        target = network_id + offset
        if not (
            0 <= network_id < len(self._wifi_networks)
            and 0 <= target < len(self._wifi_networks)
        ):
            return
        networks = self._wifi_networks
        networks[network_id], networks[target] = (
            networks[target],
            networks[network_id],
        )
        total = len(networks)
        for index, network in enumerate(networks):
            network["priority"] = total - index
        self._write_wpa_networks()
        self.populate_wifi_networks()
        self.sta_dirty = True

    def apply_sta_changes(self) -> None:
        """
        Apply saved STA edits: mirror them into NetworkManager and reconfigure
        the supplicant. This is the disruptive step (it may drop/reconnect the
        STA link), so the web UI runs it only from an explicit apply button.
        """
        self._sync_networkmanager_profiles()
        if self._wifi_mode in (WIFI_MODE_CLIENT, WIFI_MODE_APSTA):
            wpa_cli("reconfigure")
        self.sta_dirty = False

    def connect_wifi_network(
        self, network_id: int, async_switch: bool = True
    ) -> tuple[bool, str]:
        """
        Manually switch the STA link to a saved network right now (explicit
        user action, so this one is immediate by design).

        Validation (profile exists, SSID in range) runs synchronously while
        the current link is untouched; the actual switch runs in a background
        thread AFTER the HTTP response has left. Doing the `con up` inline
        tears down the link that is carrying the response, so the user saw
        no feedback at all whether the switch worked or silently reverted
        (field-observed 2026-08-08). The outcome lands in
        get_last_connect_result() for the next page render.
        """
        try:
            network = self._wifi_networks[network_id]
        except IndexError:
            return False, "Unknown network"
        ssid = network.get("ssid") or ""
        if not Network._networkmanager_active():
            return False, "NetworkManager is not active"
        profile = next(
            (
                p
                for p in Network._networkmanager_wifi_profiles()
                if p.get("ssid") == ssid
            ),
            None,
        )
        if profile is None:
            return False, f"No NetworkManager profile for {ssid} (apply first)"
        # A `con up` on an out-of-range SSID is destructive: NetworkManager
        # drops the CURRENT link first, fails after its timeout, and
        # autoconnect then quietly reverts to another saved network. Refuse up
        # front while the link is untouched. An empty scan result proceeds
        # best-effort so a scan hiccup cannot block a legitimate switch; the
        # trade-off is that hidden SSIDs cannot be switched to while other
        # networks are visible.
        visible = self.scan_wifi_networks()
        if visible and ssid not in visible:
            return False, (
                f"{ssid} is not in range (router off or out of reach); "
                "keeping the current connection"
            )

        profile_name = profile["name"]

        def _switch() -> None:
            if async_switch:
                # Let the HTTP response flush before the link may drop.
                time.sleep(1.0)
            result = Network._nmcli(["-w", "25", "con", "up", profile_name])
            ok = result.returncode == 0
            message = (
                f"Connected to {ssid}"
                if ok
                else (result.stderr or result.stdout or "nmcli failed").strip()
            )
            self._last_connect_result = {
                "ssid": ssid,
                "ok": ok,
                "message": message,
                "at": time.time(),
            }
            if not ok:
                logger.warning("Manual STA switch to %s failed: %s", ssid, message)

        if async_switch:
            threading.Thread(
                target=_switch, name=f"sta-switch-{ssid}", daemon=True
            ).start()
        else:
            _switch()
            last = self._last_connect_result or {}
            return bool(last.get("ok")), str(last.get("message") or "")
        return True, (
            f"Switching to {ssid} now. If this page is on the old network it "
            "will briefly lose connection -- reload after the switch."
        )

    def add_wifi_network(self, ssid, key_mgmt, psk=None):
        """
        Add a wifi network
        """
        ssid = (ssid or "").strip()
        psk = (psk or "").strip()
        if not ssid:
            raise ValueError("SSID is required")
        if key_mgmt == "WPA-PSK" and len(psk) < 8:
            raise ValueError("Wi-Fi password must be at least 8 characters")

        with open(WPA_SUPPLICANT_PATH, "a") as wpa_conf:
            scan_freq = Network._sta_scan_freq_for_preference(
                self.get_sta_band_preference()
            )
            wpa_conf.write("\nnetwork={\n")
            wpa_conf.write(f'\tssid="{Network._quote_wpa_value(ssid)}"\n')
            if key_mgmt == "WPA-PSK":
                wpa_conf.write(f'\tpsk="{Network._quote_wpa_value(psk)}"\n')
            wpa_conf.write(f"\tkey_mgmt={key_mgmt}\n")
            if scan_freq:
                wpa_conf.write(f"\tscan_freq={scan_freq}\n")

            wpa_conf.write("}\n")

        self.populate_wifi_networks()
        # Saved-only: NetworkManager sync + supplicant reconfigure wait for
        # apply_sta_changes() so adding a network cannot drop the current link.
        self.sta_dirty = True

    @staticmethod
    def _parse_iw_scan(output: str) -> list[str]:
        networks = []
        seen = set()
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped.startswith("SSID:"):
                continue
            ssid = stripped[5:].strip()
            if not ssid or ssid in seen:
                continue
            networks.append(ssid)
            seen.add(ssid)
        return networks

    def scan_wifi_networks(self) -> list[str]:
        """
        Scan nearby Wi-Fi networks and return a deduplicated SSID list.
        """
        scan_commands = [
            ["iw", "dev", "wlan0", "scan"],
            ["sudo", "-n", "iw", "dev", "wlan0", "scan"],
            ["iwlist", "wlan0", "scan"],
            ["sudo", "-n", "iwlist", "wlan0", "scan"],
        ]
        for command in scan_commands:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
            output = result.stdout + result.stderr
            if "iwlist" in command:
                networks = Network._parse_iwlist_scan(output)
            else:
                networks = Network._parse_iw_scan(output)
            if networks:
                return networks
        return []

    @staticmethod
    def _parse_iwlist_scan(output: str) -> list[str]:
        networks = []
        seen = set()
        for match in re.finditer(r'ESSID:"([^"]*)"', output):
            ssid = match.group(1).strip()
            if not ssid or ssid in seen:
                continue
            networks.append(ssid)
            seen.add(ssid)
        return networks

    @staticmethod
    def _parse_dnsmasq_leases(contents: str) -> dict[str, dict[str, Any]]:
        leases = {}
        for line in contents.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            expires, mac, ip, hostname = parts[:4]
            leases[mac.lower()] = {
                "mac": mac.lower(),
                "ip": ip,
                "hostname": "" if hostname == "*" else hostname,
                "lease_expires": expires,
            }
        return leases

    @staticmethod
    def _parse_iw_station_dump(output: str) -> dict[str, dict[str, Any]]:
        stations: dict[str, dict[str, Any]] = {}
        current_mac = None
        for line in output.splitlines():
            station_match = re.match(r"Station\s+([0-9A-Fa-f:]{17})", line.strip())
            if station_match:
                current_mac = station_match.group(1).lower()
                stations[current_mac] = {"mac": current_mac, "connected": True}
                continue
            if not current_mac or ":" not in line:
                continue
            key, value = line.strip().split(":", 1)
            key = key.strip().replace(" ", "_")
            stations[current_mac][key] = value.strip()
        return stations

    @staticmethod
    def _parse_ip_neigh(output: str) -> dict[str, dict[str, str]]:
        neighbors = {}
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            ip = parts[0]
            state = parts[-1]
            mac = ""
            if "lladdr" in parts:
                mac_index = parts.index("lladdr") + 1
                if mac_index < len(parts):
                    mac = parts[mac_index].lower()
            if mac:
                neighbors[mac] = {"ip": ip, "neighbor_state": state}
            else:
                neighbors[ip] = {"ip": ip, "neighbor_state": state}
        return neighbors

    def _ap_interfaces(self) -> list[str]:
        if self._wifi_mode == WIFI_MODE_APSTA:
            return ["uap0"]
        if self._wifi_mode == WIFI_MODE_AP:
            return ["wlan0"]
        return ["uap0", "wlan0"]

    def get_ap_clients(self) -> list[dict[str, Any]]:
        """
        Return AP clients by combining live hostapd station state, DHCP leases,
        and neighbor information. A DHCP lease alone is marked disconnected.
        """
        try:
            with open(DNSMASQ_LEASES_PATH, "r") as leases_file:
                clients: dict[str, dict[str, Any]] = Network._parse_dnsmasq_leases(
                    leases_file.read()
                )
        except FileNotFoundError:
            clients = {}
        except IOError as e:
            logger.error(f"Error reading dnsmasq leases: {e}")
            clients = {}

        for interface in self._ap_interfaces():
            try:
                station_result = subprocess.run(
                    ["iw", "dev", interface, "station", "dump"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                station_result = subprocess.CompletedProcess([], 1, "", "")
            stations = Network._parse_iw_station_dump(station_result.stdout)

            try:
                neigh_result = subprocess.run(
                    ["ip", "neigh", "show", "dev", interface],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                neigh_result = subprocess.CompletedProcess([], 1, "", "")
            neighbors = Network._parse_ip_neigh(neigh_result.stdout)

            for mac, station in stations.items():
                client = clients.setdefault(
                    mac, {"mac": mac, "ip": "", "hostname": "", "lease_expires": ""}
                )
                client.update(station)
                client["interface"] = interface
                client["connected"] = True
                if mac in neighbors:
                    client.update(neighbors[mac])

        for client in clients.values():
            client.setdefault("connected", False)
            client.setdefault("interface", "")
            client.setdefault("neighbor_state", "")
            client.setdefault("inactive_time", "")
            client.setdefault("rx_bitrate", "")
            client.setdefault("tx_bitrate", "")

        return sorted(
            clients.values(),
            key=lambda item: (not item.get("connected", False), item.get("ip", "")),
        )

    def get_ap_name(self):
        with open(HOSTAPD_CONF_PATH, "r") as conf:
            for line in conf:
                if line.startswith("ssid="):
                    return line[5:-1]
        return "UNKN"

    @staticmethod
    def _rewrite_key_value_lines(
        lines: list[str], updates: dict[str, str], remove_keys: set[str] | None = None
    ) -> list[str]:
        remove_keys = remove_keys or set()
        remaining_updates = dict(updates)
        rewritten = []
        for line in lines:
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key in remove_keys:
                continue
            if key in remaining_updates:
                rewritten.append(f"{key}={remaining_updates.pop(key)}\n")
                continue
            rewritten.append(line)
        for key, value in remaining_updates.items():
            rewritten.append(f"{key}={value}\n")
        return rewritten

    def _write_hostapd_config(
        self, updates: dict[str, str], remove_keys: set[str] | None = None
    ) -> None:
        with open(HOSTAPD_CONF_PATH, "r") as conf:
            lines = list(conf)
        lines = Network._rewrite_key_value_lines(lines, updates, remove_keys)
        with open(HOSTAPD_TMP_PATH, "w") as new_conf:
            new_conf.writelines(lines)
        sh.sudo("cp", HOSTAPD_TMP_PATH, HOSTAPD_CONF_PATH)

    def set_ap_name(self, ap_name):
        if ap_name == self.get_ap_name():
            return
        ap_name = (ap_name or "").strip()
        if not ap_name or "\n" in ap_name:
            raise ValueError("AP network name is invalid")
        self._write_hostapd_config({"ssid": ap_name})

    def _get_hostapd_value(self, key: str) -> str:
        with open(HOSTAPD_CONF_PATH, "r") as conf:
            for line in conf:
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip()
        return ""

    def get_ap_security(self):
        if self._get_hostapd_value("wpa") or self._get_hostapd_value("wpa_passphrase"):
            return AP_SECURITY_WPA2
        return AP_SECURITY_OPEN

    def get_ap_password(self):
        return self._get_hostapd_value("wpa_passphrase")

    def set_ap_security(self, security, password):
        security = (security or AP_SECURITY_OPEN).strip().upper()
        password = (password or "").strip()
        if security in ("OPEN", "NONE"):
            self._write_hostapd_config(
                {},
                {
                    "wpa",
                    "wpa_passphrase",
                    "wpa_key_mgmt",
                    "wpa_pairwise",
                    "rsn_pairwise",
                },
            )
            return

        if security not in (AP_SECURITY_WPA2, "WPA2"):
            raise ValueError("Unsupported AP security mode")

        if not password:
            password = self.get_ap_password()
        if len(password) < 8 or len(password) > 63:
            raise ValueError("AP password must be 8 to 63 characters")
        if "\n" in password:
            raise ValueError("AP password is invalid")

        self._write_hostapd_config(
            {
                "wpa": "2",
                "wpa_passphrase": password,
                "wpa_key_mgmt": "WPA-PSK",
                "rsn_pairwise": "CCMP",
            },
            {"wpa_pairwise"},
        )

    @staticmethod
    def _validate_ap_ip(ap_ip: str) -> ipaddress.IPv4Address:
        try:
            ip = ipaddress.IPv4Address((ap_ip or "").strip())
        except ipaddress.AddressValueError as e:
            raise ValueError("AP IP address is invalid") from e

        if (
            not ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError("AP IP address must be a private IPv4 address")
        return ip

    @staticmethod
    def _ap_ip_cidr(ap_ip: str) -> str:
        ip = Network._validate_ap_ip(ap_ip)
        return f"{ip}/24"

    @staticmethod
    def _ap_dhcp_range(ap_ip: str) -> tuple[str, str]:
        interface = ipaddress.IPv4Interface(Network._ap_ip_cidr(ap_ip))
        ap_address = interface.ip
        candidates = [host for host in interface.network.hosts() if host != ap_address]
        if len(candidates) < 2:
            raise ValueError("AP network is too small")
        end_index = min(19, len(candidates))
        return str(candidates[0]), str(candidates[end_index - 1])

    @staticmethod
    def _rewrite_dhcpcd_static_ip(contents: str, interface: str, ap_ip: str) -> str:
        lines = contents.splitlines(keepends=True)
        target_line = f"    static ip_address={Network._ap_ip_cidr(ap_ip)}\n"
        in_interface = False
        saw_interface = False
        replaced = False
        output = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("interface "):
                if in_interface and not replaced:
                    output.append(target_line)
                    replaced = True
                in_interface = stripped == f"interface {interface}"
                saw_interface = saw_interface or in_interface
                output.append(line)
                continue

            if in_interface and stripped.startswith("static ip_address="):
                if not replaced:
                    output.append(target_line)
                    replaced = True
                continue

            output.append(line)

        if in_interface and not replaced:
            output.append(target_line)
        if not saw_interface:
            if output and not output[-1].endswith("\n"):
                output[-1] += "\n"
            output.extend([f"\ninterface {interface}\n", target_line])
        return "".join(output)

    @staticmethod
    def _write_root_file(path: str, contents: str) -> None:
        tmp_path = f"/tmp/{path.strip('/').replace('/', '_')}"
        with open(tmp_path, "w") as tmp_file:
            tmp_file.write(contents)
        sh.sudo("cp", tmp_path, path)

    def _update_dhcpcd_ap_file(self, path: str, interface: str, ap_ip: str) -> None:
        try:
            with open(path, "r") as conf:
                contents = conf.read()
        except FileNotFoundError:
            contents = ""
        Network._write_root_file(
            path, Network._rewrite_dhcpcd_static_ip(contents, interface, ap_ip)
        )

    @staticmethod
    def _rewrite_dnsmasq_ap_network(contents: str, ap_ip: str) -> str:
        start, end = Network._ap_dhcp_range(ap_ip)
        return "".join(
            Network._rewrite_key_value_lines(
                contents.splitlines(keepends=True),
                {
                    "dhcp-range": f"{start},{end},255.255.255.0,24h",
                    "address": f"/gw.wlan/{ap_ip}",
                },
            )
        )

    def _update_dnsmasq_ap_network(self, ap_ip: str) -> None:
        try:
            with open(DNSMASQ_CONF_PATH, "r") as conf:
                contents = conf.read()
        except FileNotFoundError:
            contents = ""
        Network._write_root_file(
            DNSMASQ_CONF_PATH, Network._rewrite_dnsmasq_ap_network(contents, ap_ip)
        )

    @staticmethod
    def _parse_dhcpcd_static_ip(contents: str, interface: str) -> str:
        in_interface = False
        for line in contents.splitlines():
            stripped = line.strip()
            if stripped.startswith("interface "):
                in_interface = stripped == f"interface {interface}"
                continue
            if in_interface and stripped.startswith("static ip_address="):
                cidr = stripped.split("=", 1)[1]
                return str(ipaddress.IPv4Interface(cidr).ip)
        return DEFAULT_AP_IP

    def get_ap_ip(self):
        try:
            with open(DHCPD_AP_CONF_PATH, "r") as conf:
                return Network._parse_dhcpcd_static_ip(conf.read(), "wlan0")
        except Exception:
            return DEFAULT_AP_IP

    def set_ap_ip(self, ap_ip):
        ap_ip = str(Network._validate_ap_ip(ap_ip))
        if ap_ip == self.get_ap_ip():
            return

        self._update_dhcpcd_ap_file(DHCPD_AP_CONF_PATH, "wlan0", ap_ip)
        self._update_dhcpcd_ap_file(DHCPD_APSTA_CONF_PATH, "uap0", ap_ip)
        if self._wifi_mode == WIFI_MODE_AP:
            self._update_dhcpcd_ap_file(DHCPD_ACTIVE_CONF_PATH, "wlan0", ap_ip)
        elif self._wifi_mode == WIFI_MODE_APSTA:
            self._update_dhcpcd_ap_file(DHCPD_ACTIVE_CONF_PATH, "uap0", ap_ip)
        self._update_dnsmasq_ap_network(ap_ip)

    @staticmethod
    def _parse_apsta_nat_config(contents: str) -> bool:
        for line in contents.splitlines():
            if line.strip() == "MFNAVIS_APSTA_SHARE_INTERNET=1":
                return True
        return False

    def get_apsta_internet_sharing(self):
        try:
            with open(MFNAVIS_APSTA_NAT_CONF_PATH, "r") as conf:
                return Network._parse_apsta_nat_config(conf.read())
        except FileNotFoundError:
            return False
        except IOError as e:
            logger.error(f"Error reading AP+STA internet sharing config: {e}")
            return False

    def set_apsta_internet_sharing(self, enabled):
        enabled_value = "1" if enabled else "0"
        contents = (
            "# MFNavis AP+STA internet sharing setting\n"
            f"MFNAVIS_APSTA_SHARE_INTERNET={enabled_value}\n"
        )
        Network._write_root_file(MFNAVIS_APSTA_NAT_CONF_PATH, contents)

    def get_host_name(self):
        return socket.gethostname()

    def get_connected_ssid(self) -> str:
        """
        Returns the SSID of the connected wifi network or
        None if not connected or in AP mode
        """
        if self.wifi_mode() == WIFI_MODE_AP:
            return ""
        # get output from iwgetid
        try:
            iwgetid = sh.Command("iwgetid")
            _t = iwgetid("wlan0", _ok_code=(0, 255)).strip()
            if not _t:
                _t = iwgetid(_ok_code=(0, 255)).strip()
            return _t.split(":")[-1].strip('"')
        except sh.CommandNotFound:
            return "ssid_not_found"

    def set_host_name(self, hostname) -> None:
        if hostname == self.get_host_name():
            return
        _result = sh.sudo("hostnamectl", "set-hostname", hostname)
        self._update_etc_hosts(hostname)

    @staticmethod
    def _rewrite_hosts(contents: str, new_hostname: str) -> str:
        """
        Rewrite the Debian-convention ``127.0.1.1`` line in /etc/hosts to point
        at ``new_hostname``. Preserves indentation, the IP, and any trailing
        aliases/comments. If no ``127.0.1.1`` line exists, appends one so that
        ``sudo`` can still resolve the host.
        """
        lines = contents.splitlines(keepends=True)
        pattern = re.compile(r"^(\s*127\.0\.1\.1\s+)\S+(.*)$")
        replaced = False
        for i, line in enumerate(lines):
            match = pattern.match(line)
            if match:
                eol = "\n" if line.endswith("\n") else ""
                lines[i] = f"{match.group(1)}{new_hostname}{match.group(2)}{eol}"
                replaced = True
                break
        if not replaced:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append(f"127.0.1.1\t{new_hostname}\n")
        return "".join(lines)

    def _update_etc_hosts(self, new_hostname: str) -> None:
        try:
            with open("/etc/hosts", "r") as hosts_f:
                contents = hosts_f.read()
        except IOError as e:
            logger.error(f"Error reading /etc/hosts: {e}")
            return
        new_contents = Network._rewrite_hosts(contents, new_hostname)
        with open("/tmp/hosts", "w") as new_hosts:
            new_hosts.write(new_contents)
        sh.sudo("cp", "/tmp/hosts", "/etc/hosts")

    def wifi_mode(self):
        return self._wifi_mode

    def set_wifi_mode(self, mode):
        if mode == self._wifi_mode:
            return
        if mode == WIFI_MODE_AP:
            go_wifi_ap()

        if mode == WIFI_MODE_CLIENT:
            go_wifi_cli()

        if mode == WIFI_MODE_APSTA:
            go_wifi_apsta()

    def _route_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.255.255.255", 1))
            return s.getsockname()[0]
        except Exception:
            return "NONE"
        finally:
            s.close()

    def local_ip(self):
        if self._wifi_mode == WIFI_MODE_AP:
            return "10.10.10.1"
        if self._wifi_mode == WIFI_MODE_APSTA:
            sta_ip = self._route_ip()
            if sta_ip == "NONE":
                return "10.10.10.1"
            return f"{sta_ip} / 10.10.10.1"

        return self._route_ip()


def go_wifi_ap():
    logger.info("SYS: Switching to AP")
    sh.sudo(str(utils.pifinder_dir / "switch-ap.sh"))
    return True


def go_wifi_cli():
    logger.info("SYS: Switching to Client")
    sh.sudo(str(utils.pifinder_dir / "switch-cli.sh"))
    return True


def go_wifi_apsta():
    logger.info("SYS: Switching to AP+STA")
    sh.sudo(str(utils.pifinder_dir / "switch-apsta.sh"))
    return True


def ensure_uhid_loaded() -> bool:
    """
    Make sure the `uhid` kernel module is loaded so BlueZ can register a paired
    Bluetooth keyboard as an input device. Idempotent and best-effort: returns
    True if /dev/uhid is present afterwards.
    """
    if os.path.exists("/dev/uhid"):
        return True
    try:
        subprocess.run(
            ["sudo", "-n", "modprobe", UHID_MODULE],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as e:
        logger.warning("SYS: could not modprobe uhid: %s", e)
    return os.path.exists("/dev/uhid")


def _restore_wifi_command() -> str:
    """
    Shell command that brings WiFi (client + AP) back online.

    ``radio wifi on`` only re-enables the radio; reassociating the client is
    otherwise left to NetworkManager autoconnect and can lag 10-30s, which reads
    as "WiFi never came back". We therefore explicitly bring the exact profile
    that was active back up (its UUID was stashed at pause time), falling back to
    ``device connect``. hostapd is only restarted if it was already running, so
    client-only-mode devices don't get an access point started behind their back.
    """
    return (
        f"uuid=$(cat {BT_PAIRING_WIFI_STATE_FILE} 2>/dev/null); "
        f"{NMCLI_COMMAND} radio wifi on; "
        f'if [ -n "$uuid" ]; then {NMCLI_COMMAND} connection up "$uuid" 2>/dev/null; '
        f"else {NMCLI_COMMAND} device connect {BT_PAIRING_STA_INTERFACE} 2>/dev/null; fi; "
        f"ip link set {BT_PAIRING_AP_INTERFACE} up 2>/dev/null; "
        "systemctl is-active --quiet hostapd && systemctl restart hostapd || true"
    )


def _capture_wlan_connection() -> None:
    """Stash the active wlan0 connection UUID for a precise restore later."""
    uuid = ""
    try:
        result = subprocess.run(
            [
                "sudo",
                "-n",
                NMCLI_COMMAND,
                "-t",
                "-g",
                "GENERAL.CON-UUID",
                "device",
                "show",
                BT_PAIRING_STA_INTERFACE,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        uuid = (result.stdout or "").strip()
    except Exception as e:
        logger.warning("SYS: could not read wlan0 connection: %s", e)
    try:
        with open(BT_PAIRING_WIFI_STATE_FILE, "w") as state_file:
            state_file.write(uuid)
    except Exception as e:
        logger.warning("SYS: could not stash wlan0 connection: %s", e)


def _active_wifi_link_freqs_mhz() -> Optional[list[int]]:
    """
    Channel frequencies (MHz) of the WiFi interfaces that currently have an
    active link. Interfaces that are absent or down contribute nothing.
    Returns None when the state cannot be determined, so callers can fall back
    to the conservative behavior.
    """
    freqs: list[int] = []
    for interface in (BT_PAIRING_STA_INTERFACE, BT_PAIRING_AP_INTERFACE):
        try:
            result = subprocess.run(
                ["iw", "dev", interface, "info"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if result.returncode != 0:
                continue
            match = _IW_CHANNEL_FREQ_RE.search(result.stdout or "")
        except Exception as e:
            logger.warning("SYS: could not read %s channel: %s", interface, e)
            return None
        if match:
            freqs.append(int(match.group(1)))
    return freqs


def bt_pairing_needs_wifi_pause() -> bool:
    """
    Whether Bluetooth pairing needs WiFi silenced first.

    Bluetooth occupies only the 2.4GHz band, so the coexistence interference
    that breaks BLE pairing (HCI 0x3e) needs an active 2.4GHz WiFi link on the
    shared radio. With every active link on 5GHz -- or no active link at all --
    WiFi can stay up. An undeterminable state pauses (conservative).
    """
    freqs = _active_wifi_link_freqs_mhz()
    if freqs is None:
        return True
    return any(freq < BT_PAIRING_5GHZ_MIN_FREQ_MHZ for freq in freqs)


def pause_wifi_for_bt_pairing(
    safety_timeout: int = BT_PAIRING_WIFI_SAFETY_TIMEOUT,
) -> bool:
    """
    Silence the 2.4GHz radio so a Bluetooth keyboard can pair without WiFi
    coexistence interference (see BT_PAIRING_* notes above).

    Returns True when WiFi was actually paused -- callers resume only then.
    When every active WiFi link is on 5GHz the pause is skipped (returns
    False) and WiFi stays up throughout the pairing attempt.

    A detached watchdog restores WiFi after ``safety_timeout`` seconds no matter
    what, so a crash mid-pairing can never leave the device without networking.
    ``resume_wifi_after_bt_pairing`` restores it sooner on the normal path.
    """
    ensure_uhid_loaded()
    if not bt_pairing_needs_wifi_pause():
        logger.info(
            "SYS: WiFi idle or 5GHz-only; skipping WiFi pause for Bluetooth pairing"
        )
        return False
    # Remember exactly which client profile is up so we can bring it back cleanly.
    _capture_wlan_connection()
    # In-process fallback: restore WiFi even if the caller's resume path never
    # runs (the pairing screen's per-frame timeout check stops with the screen,
    # and its wall-clock timers used to freeze on a GPS/NTP clock jump). The
    # threading.Timer runs on a monotonic schedule and resume is idempotent, so
    # firing after a normal resume is harmless.
    try:
        timer = threading.Timer(
            BT_PAIRING_WIFI_APP_RESUME_SECONDS, resume_wifi_after_bt_pairing
        )
        timer.daemon = True
        timer.start()
    except Exception as e:
        logger.warning("SYS: could not arm in-process WiFi resume: %s", e)
    # Safety net: an independent, session-detached process that re-enables WiFi
    # even if this process dies while WiFi is down.
    try:
        subprocess.Popen(
            [
                "sudo",
                "-n",
                "setsid",
                "bash",
                "-c",
                f"sleep {int(safety_timeout)}; {_restore_wifi_command()}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning("SYS: could not arm WiFi restore watchdog: %s", e)
    logger.info("SYS: pausing WiFi for Bluetooth pairing")
    subprocess.run(
        ["sudo", "-n", "ip", "link", "set", BT_PAIRING_AP_INTERFACE, "down"],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["sudo", "-n", NMCLI_COMMAND, "radio", "wifi", "off"],
        capture_output=True,
        text=True,
        check=False,
    )
    return True


def resume_wifi_after_bt_pairing() -> None:
    """Bring WiFi (client + AP) back after a pairing attempt. Idempotent."""
    logger.info("SYS: resuming WiFi after Bluetooth pairing")
    subprocess.run(
        ["sudo", "-n", "bash", "-c", _restore_wifi_command()],
        capture_output=True,
        text=True,
        check=False,
    )


def _clean_bluetoothctl_output(output: str) -> str:
    output = ANSI_ESCAPE_RE.sub("", output)
    output = CONTROL_CHARS_RE.sub("", output)
    return output.replace("\r", "\n")


def _bluetoothctl(commands: list[str], timeout: int = 20) -> str:
    script = "\n".join(commands + ["quit"]) + "\n"
    result = subprocess.run(
        [BLUETOOTHCTL_COMMAND],
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return _clean_bluetoothctl_output(result.stdout + result.stderr)


def _parse_bluetooth_bool(value: str) -> bool:
    return value.strip().lower() == "yes"


def _new_bluetooth_device(address: str, name: str = "") -> dict[str, Any]:
    return {
        "address": address,
        "name": name,
        "paired": False,
        "trusted": False,
        "connected": False,
        "blocked": False,
        "icon": "",
    }


def _has_bluetooth_name(device: dict[str, Any]) -> bool:
    name = str(device.get("name", "")).strip()
    return bool(name) and not BLUETOOTH_MAC_RE.match(name)


def _merge_bluetooth_device_name(device: dict[str, Any], name: str) -> None:
    name = name.strip()
    if not name or BLUETOOTH_MAC_RE.match(name):
        return
    if not _has_bluetooth_name(device):
        device["name"] = name


def _parse_bluetooth_devices(output: str) -> dict[str, dict[str, Any]]:
    devices: dict[str, dict[str, Any]] = {}
    for line in _clean_bluetoothctl_output(output).splitlines():
        field_match = BLUETOOTH_DEVICE_FIELD_RE.search(line)
        if field_match:
            address = field_match.group(1).upper()
            field = field_match.group(2).strip().lower()
            value = field_match.group(3).strip()
            device = devices.setdefault(address, _new_bluetooth_device(address))
            if field in ["name", "alias"]:
                _merge_bluetooth_device_name(device, value)
                continue
            elif field in ["paired", "trusted", "connected", "blocked"]:
                device[field] = _parse_bluetooth_bool(value)
                continue
            elif field == "icon":
                device["icon"] = value
                continue
            elif field in ["rssi", "txpower", "uuids", "servicesresolved"]:
                continue

        match = BLUETOOTH_DEVICE_RE.search(line)
        if not match:
            continue
        address = match.group(1).upper()
        name = match.group(2).strip()
        device = devices.setdefault(address, _new_bluetooth_device(address))
        _merge_bluetooth_device_name(device, name)
    return devices


def _parse_bluetooth_info(output: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for raw_line in _clean_bluetoothctl_output(output).splitlines():
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if key in ["Name", "Alias", "Icon"]:
            info[key.lower()] = value
        elif key in ["Paired", "Trusted", "Connected", "Blocked"]:
            info[key.lower()] = _parse_bluetooth_bool(value)
    return info


# Name fragments that mark a device as a HID input device we want to
# auto-reconnect: keyboards plus joysticks/gamepads (the Bluetooth settings
# screen manages both). Common controller brandings are included because many
# report a plain model name ("8BitDo Zero 2") with no generic keyword.
_BT_INPUT_NAME_FRAGMENTS = (
    "keyboard",
    "keys",
    "joystick",
    "joypad",
    "gamepad",
    "game pad",
    "controller",
    "8bitdo",
    "dualshock",
    "dualsense",
    "joy-con",
)
# bluetoothctl Icon values for HID input devices.
_BT_INPUT_ICONS = ("input-keyboard", "input-gaming", "input-mouse")


def is_bluetooth_input_device(device: dict[str, Any]) -> bool:
    """
    Best-effort HID input device detection (keyboard/joystick/gamepad) for
    reconnect filtering.
    """
    name = str(device.get("name", "")).lower()
    icon = str(device.get("icon", "")).lower()
    return icon in _BT_INPUT_ICONS or any(
        fragment in name for fragment in _BT_INPUT_NAME_FRAGMENTS
    )


def is_bluetooth_keyboard(device: dict[str, Any]) -> bool:
    """
    Kept for compatibility; reconnect filtering now uses
    is_bluetooth_input_device().
    """
    name = str(device.get("name", "")).lower()
    icon = str(device.get("icon", "")).lower()
    return "keyboard" in name or "keys" in name or icon == "input-keyboard"


def list_bluetooth_devices(scan_output: str = "") -> list[dict[str, Any]]:
    """
    Return cached Bluetooth devices with paired/trusted/connected status.
    """
    logger.info("SYS: Listing Bluetooth devices")
    devices = _parse_bluetooth_devices(scan_output)
    output = _bluetoothctl(["power on", "devices", "devices Paired"], timeout=12)
    for address, scanned_device in _parse_bluetooth_devices(output).items():
        device = devices.setdefault(address, _new_bluetooth_device(address))
        _merge_bluetooth_device_name(device, str(scanned_device.get("name", "")))

    for address, device in devices.items():
        info = _parse_bluetooth_info(_bluetoothctl([f"info {address}"], timeout=8))
        for key, value in info.items():
            if key in ["name", "alias"]:
                _merge_bluetooth_device_name(device, str(value))
            else:
                device[key] = value
        device["address"] = address
        device["name"] = device.get("name") or device.get("alias") or address

    return sorted(
        devices.values(),
        key=lambda item: (
            not bool(item.get("connected")),
            not bool(item.get("paired")),
            str(item.get("name", "")).lower(),
        ),
    )


def scan_bluetooth_devices(scan_seconds: int = 12) -> list[dict[str, Any]]:
    """
    Scan for nearby Bluetooth devices and return the refreshed cached device list.
    """
    logger.info("SYS: Scanning for Bluetooth devices for %s seconds", scan_seconds)
    ensure_uhid_loaded()
    process = subprocess.Popen(
        [BLUETOOTHCTL_COMMAND],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert process.stdin is not None
    scan_output = ""
    try:
        for command in [
            "power on",
            "agent KeyboardDisplay",
            "default-agent",
            "pairable on",
            "scan on",
        ]:
            process.stdin.write(command + "\n")
            process.stdin.flush()

        time.sleep(scan_seconds)

        for command in ["scan off", "devices", "devices Paired", "quit"]:
            process.stdin.write(command + "\n")
            process.stdin.flush()
        scan_output, _ = process.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        scan_output, _ = process.communicate()
    finally:
        if process.poll() is None:
            process.terminate()

    return list_bluetooth_devices(scan_output)


def connect_bluetooth_device(address: str, timeout: int = 25) -> str:
    logger.info("SYS: Connecting Bluetooth device %s", address)
    ensure_uhid_loaded()
    return _bluetoothctl(
        [
            "power on",
            "agent KeyboardDisplay",
            "default-agent",
            f"trust {address}",
            f"connect {address}",
        ],
        timeout=timeout,
    )


def disconnect_bluetooth_device(address: str) -> str:
    logger.info("SYS: Disconnecting Bluetooth device %s", address)
    return _bluetoothctl([f"disconnect {address}"], timeout=15)


def remove_bluetooth_device(address: str) -> str:
    logger.info("SYS: Removing Bluetooth device %s", address)
    return _bluetoothctl([f"remove {address}"], timeout=15)


def reconnect_bluetooth_keyboards(connect_timeout: int = 25) -> int:
    """
    Connect paired HID input devices (keyboards and joysticks/gamepads). If
    none are identifiable as input devices, try all paired devices so generic
    HID names still work.
    """
    devices = [
        d for d in list_bluetooth_devices() if d.get("paired") or d.get("trusted")
    ]
    targets = [d for d in devices if is_bluetooth_input_device(d)] or devices
    count = 0
    for device in targets:
        if device.get("connected"):
            continue
        connect_bluetooth_device(str(device["address"]), timeout=connect_timeout)
        count += 1
    return count


def auto_reconnect_bluetooth_keyboards(
    attempts: int = 12,
    delay_seconds: int = 5,
    connect_timeout: int = 10,
) -> int:
    """
    Retry Bluetooth input device reconnection in the background during startup.

    Bluetooth controllers and HID devices can appear a few seconds after the
    PiFinder service starts, especially after a reboot. This helper is designed
    for a daemon thread: it logs failures and keeps retrying without raising.
    """
    total_attempted = 0
    for attempt in range(1, attempts + 1):
        try:
            logger.info(
                "SYS: Bluetooth keyboard reconnect attempt %s/%s",
                attempt,
                attempts,
            )
            total_attempted += reconnect_bluetooth_keyboards(connect_timeout)
            devices = [
                d
                for d in list_bluetooth_devices()
                if d.get("paired") or d.get("trusted")
            ]
            targets = [d for d in devices if is_bluetooth_input_device(d)] or devices
            if targets and any(d.get("connected") for d in targets):
                logger.info("SYS: Bluetooth keyboard reconnect complete")
                return total_attempted
        except Exception as e:
            logger.warning("SYS: Bluetooth keyboard reconnect failed: %s", e)

        if attempt < attempts:
            time.sleep(delay_seconds)

    logger.info(
        "SYS: Bluetooth keyboard reconnect finished after %s attempts",
        attempts,
    )
    return total_attempted


def remove_backup():
    """
    Removes backup file
    """
    sh.sudo("rm", BACKUP_PATH, _ok_code=(0, 1))


def backup_userdata():
    """
    Back up userdata to a single zip file for later
    restore.  Returns the path to the zip file.

    Backs up:
        config.json
        observations.db
        obslist/*
    """

    from PiFinder.userdata_backup import create_backup

    remove_backup()
    return create_backup(utils.data_dir, BACKUP_PATH)


def restore_userdata(zip_path):
    """Restore current or legacy backup entries into the selected data directory."""
    from PiFinder.userdata_backup import restore_backup

    restore_backup(zip_path, utils.data_dir)


def restart_pifinder() -> None:
    """
    Uses systemctl to restart the PiFinder
    service
    """
    logger.info("SYS: Restarting MFNavis")
    sh.sudo("systemctl", "restart", "mfnavis")


def restart_system() -> None:
    """
    Restarts the system
    """
    logger.info("SYS: Initiating System Restart")
    sh.sudo("shutdown", "-r", "now")


def shutdown() -> None:
    """
    shuts down the system
    """
    logger.info("SYS: Initiating Shutdown")
    sh.sudo("shutdown", "now")


def update_software():
    """
    Uses systemctl to git pull and then restart
    service
    """
    logger.info("SYS: Running update")
    try:
        sh.bash(str(utils.pifinder_dir / "mfnavis_update.sh"))
    except Exception:
        # MF: a failed update script (no release branch cut yet, network
        # drop mid-pull) must report failure, not unwind the UI main loop
        # and take the whole app down with it.
        logger.exception("SYS: software update failed")
        return False
    return True


def recover_wifi():
    """
    Reload the brcmfmac driver stack to un-wedge the Wi-Fi chip
    (BT-coexistence firmware wedge; see scripts/mf_wifi_recover.sh).
    Returns True when the script reports a working STA or AP afterwards.
    """
    logger.info("SYS: Running Wi-Fi recovery")
    try:
        sh.sudo("bash", str(utils.pifinder_dir / "scripts" / "mf_wifi_recover.sh"))
    except Exception:
        logger.exception("SYS: Wi-Fi recovery failed")
        return False
    return True


def verify_password(username, password):
    """
    Checks the provided password against the provided user
    password
    """
    p = pam.pam()

    return p.authenticate(username, password)


def change_password(username, current_password, new_password):
    """
    Changes the PiFinder User password
    """
    result = passwd(
        username,
        _in=f"{current_password}\n{new_password}\n{new_password}\n",
        _ok_code=(0, 10),
    )

    if result.exit_code == 0:
        return True
    else:
        return False


def switch_cam_imx477() -> None:
    logger.info("SYS: Switching cam to imx477")
    sh.sudo("python", "-m", "PiFinder.switch_camera", "imx477")


def switch_cam_imx296() -> None:
    logger.info("SYS: Switching cam to imx296")
    sh.sudo("python", "-m", "PiFinder.switch_camera", "imx296")


def switch_cam_imx462() -> None:
    logger.info("SYS: Switching cam to imx462")
    sh.sudo("python", "-m", "PiFinder.switch_camera", "imx462")


def get_default_gpsd_device() -> str:
    return board_config.get_default_gpsd_device()


DEFAULT_GPSD_DEVICE = get_default_gpsd_device()


def resolve_gpsd_device(device: str | None) -> str:
    if not device or device == "auto":
        return get_default_gpsd_device()
    return device


def _gpsd_options_line(baud_rate: int) -> str:
    if baud_rate == 115200:
        # NOTE: the space before -s in the next line is really needed
        return 'GPSD_OPTIONS=" -s 115200"'
    return 'GPSD_OPTIONS=""'


def _gpsd_devices_line(device: str) -> str:
    return f'DEVICES="{device}"'


def check_and_sync_gpsd_config(
    baud_rate: int, device: str = DEFAULT_GPSD_DEVICE
) -> bool:
    """
    Checks if GPSD configuration matches the desired serial device and baud rate,
    and updates it only if necessary.

    Args:
        baud_rate: The desired baud rate (9600 or 115200)
        device: The serial device path to configure for gpsd

    Returns:
        True if configuration was updated, False if already correct
    """
    device = resolve_gpsd_device(device)
    logger.info(f"SYS: Checking GPSD config for device {device}, baud rate {baud_rate}")

    try:
        # Read current config
        with open("/etc/default/gpsd", "r") as f:
            content = f.read()

        expected_devices = _gpsd_devices_line(device)
        expected_options = _gpsd_options_line(baud_rate)

        # Check if update is needed
        current_match = re.search(r"^GPSD_OPTIONS=.*$", content, re.MULTILINE)
        current_options = current_match.group(0) if current_match else ""
        current_match = re.search(r"^DEVICES=.*$", content, re.MULTILINE)
        current_devices = current_match.group(0) if current_match else ""
        if current_options == expected_options and current_devices == expected_devices:
            logger.info("SYS: GPSD config already correct, no update needed")
            return False

        # Update is needed
        logger.info(
            "SYS: GPSD config mismatch, updating to %s, %s",
            expected_devices,
            expected_options,
        )
        update_gpsd_config(baud_rate, device)
        return True

    except Exception as e:
        logger.error(f"SYS: Error checking/syncing GPSD config: {e}")
        return False


def update_gpsd_config(baud_rate: int, device: str = DEFAULT_GPSD_DEVICE) -> None:
    """
    Updates the GPSD configuration file with the specified device and baud rate
    and restarts the GPSD service.

    Args:
        baud_rate: The baud rate to configure (9600 or 115200)
        device: The serial device path to configure for gpsd
    """
    device = resolve_gpsd_device(device)
    logger.info(
        f"SYS: Updating GPSD config with device {device}, baud rate {baud_rate}"
    )

    try:
        # Read the current config
        with open("/etc/default/gpsd", "r") as f:
            lines = f.readlines()

        expected_devices = _gpsd_devices_line(device)
        expected_options = _gpsd_options_line(baud_rate)

        # Update DEVICES and GPSD_OPTIONS lines
        updated_lines = []
        saw_devices = False
        saw_options = False
        for line in lines:
            if line.startswith("DEVICES="):
                updated_lines.append(f"{expected_devices}\n")
                saw_devices = True
            elif line.startswith("GPSD_OPTIONS="):
                updated_lines.append(f"{expected_options}\n")
                saw_options = True
            else:
                updated_lines.append(line)
        if not saw_devices:
            updated_lines.append(f"{expected_devices}\n")
        if not saw_options:
            updated_lines.append(f"{expected_options}\n")

        # Write the updated config to a temporary file
        with open("/tmp/gpsd.conf", "w") as f:
            f.writelines(updated_lines)

        # Copy the temp file to the actual location with sudo
        sh.sudo("cp", "/tmp/gpsd.conf", "/etc/default/gpsd")

        # Restart GPSD service
        sh.sudo("systemctl", "restart", "gpsd")

        logger.info("SYS: GPSD configuration updated and service restarted")

    except Exception as e:
        logger.error(f"SYS: Error updating GPSD config: {e}")
        raise


# ---------------------------------------------------------------------------
# NixOS migration
# ---------------------------------------------------------------------------

MIGRATION_PROGRESS_FILE = "/tmp/nixos_migration_progress"
MIGRATION_SCRIPT = str(utils.pifinder_dir / "python/scripts/nixos_migration.sh")


def _fetch_migration_sha256(version_info: dict) -> str:
    """Fetch SHA256 from sidecar URL, falling back to hardcoded value."""
    sha256_url = version_info.get("migration_sha256_url", "")
    if sha256_url:
        try:
            resp = requests.get(sha256_url, timeout=15)
            if resp.status_code == 200:
                sha256 = resp.text.strip().split()[0]
                logger.info(f"SYS: Fetched migration SHA256: {sha256[:16]}...")
                return sha256
            logger.warning(f"SYS: SHA256 fetch returned {resp.status_code}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"SYS: Failed to fetch SHA256: {e}")

    sha256 = version_info.get("migration_sha256", "")
    if sha256:
        logger.info("SYS: Using hardcoded migration SHA256")
    return sha256


def start_nixos_migration(version_info: dict) -> None:
    """
    Start the NixOS migration process in the background.

    Raises ValueError if migration_url or a migration SHA256 cannot be
    obtained — an in-place OS replacement must not run without checksum
    verification.
    """
    url = version_info.get("migration_url", "")
    if not url:
        raise ValueError("Missing migration_url")
    sha256 = _fetch_migration_sha256(version_info)
    if not sha256:
        raise ValueError(
            "No migration SHA256 available (neither migration_sha256_url nor "
            "migration_sha256 produced a value); refusing to migrate without "
            "checksum verification"
        )
    display_class = str(version_info.get("display_class", ""))
    display_resolution_value = version_info.get("display_resolution", "")
    if isinstance(display_resolution_value, (list, tuple)):
        display_resolution = "x".join(str(part) for part in display_resolution_value)
    else:
        display_resolution = str(display_resolution_value)

    logger.info(f"SYS: Starting NixOS migration to {version_info.get('version', '?')}")

    with open(MIGRATION_PROGRESS_FILE, "w") as f:
        json.dump({"percent": 0, "status": "Starting..."}, f)

    def _log_output(line):
        logger.info(f"SYS: migration: {line.strip()}")

    def _log_error(line):
        logger.error(f"SYS: migration: {line.strip()}")

    def _on_done(cmd, success, exit_code):
        if not success:
            logger.error(f"SYS: Migration script failed with exit code {exit_code}")

    try:
        sh.bash(
            MIGRATION_SCRIPT,
            url,
            sha256,
            MIGRATION_PROGRESS_FILE,
            display_class,
            display_resolution,
            _bg=True,
            _bg_exc=False,
            _out=_log_output,
            _err=_log_error,
            _done=_on_done,
        )
    except Exception as e:
        logger.error(f"SYS: Migration failed to start: {e}")
        raise


def get_migration_progress() -> Dict[str, Any]:
    """
    Read current migration progress from the progress file.
    """
    try:
        with open(MIGRATION_PROGRESS_FILE, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
