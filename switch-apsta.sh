#! /usr/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -n "AP+STA" > "${SCRIPT_DIR}/wifi_status.txt"
cp /etc/dhcpcd.conf.apsta /etc/dhcpcd.conf
# The caller reboots after the HTTP response is displayed. Let the boot-time
# prepare service associate the STA and choose the AP channel; doing it here
# blocks the response and can disconnect the browser before it receives it.
systemctl enable mfnavis_apsta_prepare
systemctl enable mfnavis_apsta_monitor
systemctl enable dnsmasq
systemctl enable hostapd
