#! /usr/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
systemctl disable mfnavis_apsta_monitor 2>/dev/null || true
systemctl disable mfnavis_apsta_prepare 2>/dev/null || true
# The requested reboot restores NetworkManager ownership of wlan0 and removes
# the virtual AP. Keep the current link alive until the response is delivered.
cp /etc/dhcpcd.conf.sta /etc/dhcpcd.conf
systemctl disable dnsmasq
systemctl disable hostapd
echo -n "Client" > "${SCRIPT_DIR}/wifi_status.txt"
