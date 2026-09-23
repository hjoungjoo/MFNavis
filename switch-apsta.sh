#! /usr/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -n "AP+STA" > "${SCRIPT_DIR}/wifi_status.txt"
cp /etc/dhcpcd.conf.apsta /etc/dhcpcd.conf
# AP+STA needs the STA up; return wlan0 to NetworkManager in case AP-only left
# it unmanaged/down, then let prepare wait for the association to pick the
# channel.
nmcli device set wlan0 managed yes 2>/dev/null || true
nmcli device connect wlan0 2>/dev/null || true
"${SCRIPT_DIR}/scripts/pifinder_apsta.sh" prepare
systemctl enable mfnavis_apsta_prepare
systemctl enable mfnavis_apsta_monitor
systemctl enable dnsmasq
systemctl enable hostapd
