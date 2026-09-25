#!/usr/bin/env python3
"""Import OS-provisioned Wi-Fi profiles into PiFinder's wpa_supplicant list."""

from __future__ import annotations

import configparser
import os
import re
from pathlib import Path


WPA_PATH = Path(
    os.environ.get(
        "MFNAVIS_WPA_SUPPLICANT_CONF", "/etc/wpa_supplicant/wpa_supplicant.conf"
    )
)
NM_DIR = Path(
    os.environ.get(
        "MFNAVIS_NM_CONNECTION_DIR", "/etc/NetworkManager/system-connections"
    )
)
BOOT_WPA_PATHS = [
    Path("/boot/firmware/wpa_supplicant.conf"),
    Path("/boot/wpa_supplicant.conf"),
]


def quote_wpa_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def decode_nm_ssid(ssid: str) -> str:
    ssid = ssid.strip()
    if len(ssid) >= 2 and len(ssid) % 2 == 0 and re.fullmatch(r"[0-9A-Fa-f]+", ssid):
        try:
            decoded = bytes.fromhex(ssid).decode("utf-8")
            if decoded.isprintable():
                return decoded
        except (ValueError, UnicodeDecodeError):
            pass
    return ssid.strip('"')


def parse_wpa_networks(contents: str) -> list[dict[str, str]]:
    networks = []
    current: dict[str, str] | None = None
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if line.startswith("network={"):
            current = {}
            continue
        if line == "}" and current is not None:
            if current.get("ssid"):
                networks.append(current)
            current = None
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in ("ssid", "psk", "key_mgmt"):
            current[key] = value.strip().strip('"')
    return networks


def parse_nm_connection(path: Path) -> dict[str, str] | None:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(path)
    except configparser.Error:
        return None

    wifi_section = None
    for section in ("wifi", "802-11-wireless"):
        if parser.has_section(section):
            wifi_section = section
            break
    if wifi_section is None:
        return None

    ssid = decode_nm_ssid(parser.get(wifi_section, "ssid", fallback=""))
    if not ssid:
        return None

    security_section = None
    for section in ("wifi-security", "802-11-wireless-security"):
        if parser.has_section(section):
            security_section = section
            break

    if security_section is None:
        return {"ssid": ssid, "key_mgmt": "NONE"}

    key_mgmt = parser.get(security_section, "key-mgmt", fallback="").lower()
    psk = parser.get(security_section, "psk", fallback="")
    if key_mgmt in ("wpa-psk", "sae") and psk:
        return {"ssid": ssid, "psk": psk, "key_mgmt": "WPA-PSK"}
    if not key_mgmt:
        return {"ssid": ssid, "key_mgmt": "NONE"}
    return None


def append_networks(path: Path, networks: list[dict[str, str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_contents = path.read_text() if path.exists() else ""
    existing_ssids = {
        network["ssid"] for network in parse_wpa_networks(existing_contents)
    }

    new_networks = []
    for network in networks:
        ssid = network.get("ssid", "").strip()
        if not ssid or ssid in existing_ssids:
            continue
        new_networks.append(network)
        existing_ssids.add(ssid)

    if not new_networks:
        return 0

    with path.open("a") as wpa_conf:
        if "ctrl_interface=" not in existing_contents:
            wpa_conf.write(
                "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n"
            )
            wpa_conf.write("update_config=1\n")
            wpa_conf.write("country=US\n")
        for network in new_networks:
            ssid = quote_wpa_value(network["ssid"])
            psk = quote_wpa_value(network.get("psk", ""))
            key_mgmt = network.get("key_mgmt", "NONE")
            wpa_conf.write("\nnetwork={\n")
            wpa_conf.write(f'\tssid="{ssid}"\n')
            if key_mgmt == "WPA-PSK" and psk:
                wpa_conf.write(f'\tpsk="{psk}"\n')
            wpa_conf.write(f"\tkey_mgmt={key_mgmt}\n")
            wpa_conf.write("}\n")
    return len(new_networks)


def main() -> int:
    networks: list[dict[str, str]] = []
    for boot_path in BOOT_WPA_PATHS:
        if boot_path.exists():
            networks.extend(parse_wpa_networks(boot_path.read_text()))

    if NM_DIR.exists():
        for path in sorted(NM_DIR.glob("*.nmconnection")):
            network = parse_nm_connection(path)
            if network:
                networks.append(network)

    imported = append_networks(WPA_PATH, networks)
    print(f"Imported {imported} Wi-Fi network(s) into {WPA_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
