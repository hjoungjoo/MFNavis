#! /usr/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#systemctl stop dnsmasq
#systemctl stop hostapd
systemctl disable mfnavis_apsta_monitor 2>/dev/null || true
systemctl disable mfnavis_apsta_prepare 2>/dev/null || true
systemctl stop mfnavis_apsta_monitor 2>/dev/null || true
"${SCRIPT_DIR}/scripts/pifinder_apsta.sh" cleanup 2>/dev/null || true
# Return wlan0 to NetworkManager in case AP-only left it unmanaged/down. A
# reboot also restores management, but do it explicitly so NM reconnects.
nmcli device set wlan0 managed yes 2>/dev/null || true
nmcli device connect wlan0 2>/dev/null || true
cp /etc/dhcpcd.conf.sta /etc/dhcpcd.conf
systemctl disable dnsmasq
systemctl disable hostapd
#systemctl restart dhcpcd
echo -n "Client" > "${SCRIPT_DIR}/wifi_status.txt"
