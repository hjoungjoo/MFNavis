#! /usr/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Record the mode first so the prepare service (which dispatches on
# wifi_status.txt) takes the AP-only path on the next boot.
echo -n "AP" > "${SCRIPT_DIR}/wifi_status.txt"

systemctl disable mfnavis_apsta_monitor 2>/dev/null || true
systemctl stop mfnavis_apsta_monitor 2>/dev/null || true

# AP-only shares the AP+STA plumbing: hostapd/dnsmasq run on the uap0 virtual
# interface (NetworkManager keeps wlan0), and the AP IP is assigned directly
# with `ip addr` instead of dhcpcd (which is disabled on Bookworm). The prepare
# service recreates uap0 before hostapd/dnsmasq start on boot; the channel
# monitor is not needed because AP-only uses a fixed default channel.
cp /etc/dhcpcd.conf.apsta /etc/dhcpcd.conf
"${SCRIPT_DIR}/scripts/mfnavis_apsta.sh" cleanup 2>/dev/null || true
"${SCRIPT_DIR}/scripts/mfnavis_apsta.sh" configure-ap

systemctl enable mfnavis_apsta_prepare
systemctl enable dnsmasq
systemctl enable hostapd
#systemctl start dnsmasq
#systemctl start hostapd
#systemctl restart dhcpcd
