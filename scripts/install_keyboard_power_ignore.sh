#!/usr/bin/env bash
# Persist the verified 1915:1025 keyboard power-key mapping on new installs
# and updates. No keyboard needs to be connected during installation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MFNAVIS_REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
    exec sudo bash "${SCRIPT_DIR}/install_keyboard_power_ignore.sh" "$@"
fi

HWDB_NAME="90-pifinder-keyboard-power-ignore.hwdb"
install -D -m 644 "${MFNAVIS_REPO_DIR}/pi_config_files/${HWDB_NAME}" \
    "/etc/udev/hwdb.d/${HWDB_NAME}"
systemd-hwdb update

# Reapply only to this receiver, without restarting logind or PiFinder.
# All interfaces share the same USB IDs; hwdb selects the three key maps.
# On later hotplug/boot udev applies the installed database automatically.
keyboard_events=0
for event_path in /sys/class/input/event*; do
    [[ -r "${event_path}/device/id/vendor" && \
       -r "${event_path}/device/id/product" ]] || continue
    [[ "$(<"${event_path}/device/id/vendor")" == "1915" && \
       "$(<"${event_path}/device/id/product")" == "1025" ]] || continue
    udevadm trigger --action=change "${event_path}"
    keyboard_events=$((keyboard_events + 1))
done
if [[ "${keyboard_events}" -gt 0 ]]; then
    udevadm settle --timeout=15
fi

echo "Installed keyboard power-key protection for XING WEI USB 1915:1025 (${keyboard_events} connected interfaces)."
