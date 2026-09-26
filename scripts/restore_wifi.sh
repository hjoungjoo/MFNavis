#!/usr/bin/env bash
# Root-owned entry point shared by Bluetooth pairing and its detached watchdog.
set -u
if [[ $# -gt 1 || ! "${1:-0}" =~ ^[0-9]+$ ]]; then
    exit 2
fi
sleep "${1:-0}"
uuid="$(cat /tmp/pifinder_bt_pairing_wlan_conn 2>/dev/null || true)"
nmcli radio wifi on || exit 1
if [[ "${uuid}" =~ ^[0-9a-fA-F-]{36}$ ]]; then
    nmcli connection up uuid "${uuid}" 2>/dev/null || nmcli device connect wlan0
else
    nmcli device connect wlan0 2>/dev/null || true
fi
ip link set uap0 up 2>/dev/null || true
if systemctl is-active --quiet hostapd; then
    systemctl restart hostapd
fi
