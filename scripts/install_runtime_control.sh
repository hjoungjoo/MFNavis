#!/usr/bin/env bash
# Install the application's noninteractive device-management permissions.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
MFNAVIS_USER="${1:-${MFNAVIS_USER:-${SUDO_USER:-$(id -un)}}}"
ACTION="${2:-install}"

if [[ ! "${MFNAVIS_USER}" =~ ^[a-z_][a-z0-9_-]*\$?$ || "${MFNAVIS_USER}" == root ]]; then
    echo "Specify a non-root MFNavis service user." >&2
    exit 1
fi
if [[ ! "${REPO_DIR}" =~ ^/[a-zA-Z0-9_./-]+$ ]]; then
    echo "Repository path contains unsupported sudoers characters." >&2
    exit 1
fi
if [[ "${ACTION}" != install && "${ACTION}" != --print-policy ]]; then
    echo "Usage: $0 [service-user] [--print-policy]" >&2
    exit 1
fi

print_policy() {
    local destination source mode command camera
    for destination in /etc/hostapd/hostapd.conf /etc/dhcpcd.conf.ap \
        /etc/dhcpcd.conf.apsta /etc/dhcpcd.conf /etc/dnsmasq.conf \
        /etc/mfnavis_apsta_nat.conf /etc/mfnavis_sta_band.conf /etc/hosts /etc/default/gpsd; do
        case "${destination}" in
            /etc/hostapd/hostapd.conf) source=/tmp/hostapd.conf ;;
            /etc/hosts) source=/tmp/hosts ;;
            /etc/default/gpsd) source=/tmp/gpsd.conf ;;
            *) source="${destination#/}"; source="/tmp/${source//\//_}" ;;
        esac
        printf '%s ALL=(root) NOPASSWD: /usr/bin/cp %s %s\n' \
            "${MFNAVIS_USER}" "${source}" "${destination}"
    done
    for mode in ap cli apsta; do
        printf '%s ALL=(root) NOPASSWD: %s/switch-%s.sh ""\n' \
            "${MFNAVIS_USER}" "${REPO_DIR}" "${mode}"
    done
    # Argument regexes require sudo >= 1.9.10 (Bookworm and Trixie).
    printf '%s ALL=(root) NOPASSWD: /usr/bin/hostnamectl ^set-hostname [a-zA-Z0-9][a-zA-Z0-9.-]*$\n' "${MFNAVIS_USER}"
    printf '%s ALL=(root) NOPASSWD: /usr/sbin/shutdown -r now\n' "${MFNAVIS_USER}"
    printf '%s ALL=(root) NOPASSWD: /usr/sbin/shutdown now\n' "${MFNAVIS_USER}"
    for command in \
        '/usr/bin/systemctl --no-block restart mfnavis.service' \
        '/usr/bin/systemctl restart gpsd' \
        '/usr/bin/systemctl start indiwebmanager.service' \
        '/usr/bin/systemctl stop indiwebmanager.service' \
        '/usr/bin/systemctl restart indiwebmanager.service' \
        '/usr/sbin/modprobe uhid' \
        '/usr/sbin/iw dev wlan0 scan' \
        '/usr/sbin/iwlist wlan0 scan' \
        '/usr/sbin/wpa_cli -i wlan0 reconfigure' \
        '/usr/sbin/ip link set uap0 down' \
        '/usr/bin/nmcli -t -f NAME\,TYPE con show' \
        '/usr/bin/nmcli -g 802-11-wireless.ssid con show *' \
        '/usr/bin/nmcli con delete *' \
        '/usr/bin/nmcli con add type wifi ifname wlan0 con-name *' \
        '/usr/bin/nmcli con modify *' \
        '/usr/bin/nmcli -w 25 con up *' \
        '/usr/bin/nmcli -t -g GENERAL.CON-UUID device show wlan0' \
        '/usr/bin/nmcli radio wifi off' \
        '/usr/bin/bash /usr/local/lib/mfnavis/restore_wifi.sh' \
        '/usr/bin/setsid ^/usr/bin/bash /usr/local/lib/mfnavis/restore_wifi.sh [0-9]+$'; do
        printf '%s ALL=(root) NOPASSWD: %s\n' "${MFNAVIS_USER}" "${command}"
    done
    printf '%s ALL=(root) NOPASSWD: /usr/bin/bash %s/scripts/mf_wifi_recover.sh\n' "${MFNAVIS_USER}" "${REPO_DIR}"
    for camera in imx477 imx296 imx462; do
        printf '%s ALL=(root) NOPASSWD: /usr/bin/python3 /usr/local/lib/mfnavis/switch_camera.py %s\n' "${MFNAVIS_USER}" "${camera}"
    done
}

if [[ "${ACTION}" == --print-policy ]]; then
    print_policy
    exit 0
fi
id "${MFNAVIS_USER}" >/dev/null
if [[ "${EUID}" -ne 0 ]]; then
    exec sudo bash "${SCRIPT_DIR}/install_runtime_control.sh" "${MFNAVIS_USER}"
fi

policy_tmp="$(mktemp)"
trap 'rm -f "${policy_tmp}"' EXIT
print_policy > "${policy_tmp}"
/usr/sbin/visudo -cf "${policy_tmp}"
install -d -o root -g root -m 0755 /usr/local/lib/mfnavis
install -o root -g root -m 0644 "${REPO_DIR}/python/MFNavis/switch_camera.py" \
    "${REPO_DIR}/python/MFNavis/boot_config.py" /usr/local/lib/mfnavis/
install -o root -g root -m 0644 "${SCRIPT_DIR}/restore_wifi.sh" /usr/local/lib/mfnavis/restore_wifi.sh
install -o root -g root -m 0644 "${SCRIPT_DIR}/import_initial_wifi_networks.py" /usr/local/lib/mfnavis/import_initial_wifi_networks.py
install -d -o root -g root -m 0755 /etc/systemd/system/mfnavis.service.d
cat > /etc/systemd/system/mfnavis.service.d/70-wifi-profile-import.conf <<EOF
[Unit]
After=NetworkManager.service

[Service]
ExecStartPre=+/usr/bin/python3 /usr/local/lib/mfnavis/import_initial_wifi_networks.py --initial-only --owner ${MFNAVIS_USER}
EOF
chmod 0644 /etc/systemd/system/mfnavis.service.d/70-wifi-profile-import.conf
install -o root -g root -m 0440 "${policy_tmp}" /etc/sudoers.d/90-mfnavis-runtime-control
systemctl daemon-reload
echo "Installed MFNavis device-management permissions for ${MFNAVIS_USER}."
