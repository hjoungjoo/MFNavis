#!/usr/bin/bash
# Recover a wedged Wi-Fi chip (brcmfmac) without a reboot.
#
# The CYW43455 shares one 2.4 GHz radio between Wi-Fi and Bluetooth. High
# duty-cycle BT phases (pairing, boot-time reconnect storms) can wedge the
# firmware's STA state machine: the link drops and no supplicant retry can
# bring it back (docs/mf_dev/mf_change_history_ko.md, 2026-08-05 incident).
# Service restarts don't help — the fault is below them. This script does the
# only software-level fix: tear the stack down to the kernel module, reload
# the driver (which resets the chip firmware), and bring the stack back in
# boot order. Run from the LCD (Settings > Advanced > WiFi Recover) or a
# console; running it over Wi-Fi SSH will drop the session by design.
#
# Must run as root.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../pifinder_paths.sh"
LOG_FILE="${MF_WIFI_RECOVER_LOG:-${PIFINDER_DATA_DIR}/wifi_recover.log}"
STA_IFACE="wlan0"
AP_IFACE="uap0"
# Units above the driver, in stop order. prepare is a oneshot that recreates
# the uap0 virtual interface; the monitor keeps AP/STA on one channel.
AP_UNITS=(mfnavis_apsta_monitor hostapd dnsmasq)

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "${LOG_FILE}"
}

sta_state() {
    wpa_cli -i "${STA_IFACE}" status 2>/dev/null | sed -n 's/^wpa_state=//p'
}

log "=== wifi recover start ==="
log "pre: sta=$(sta_state | head -1) ifaces=$(iw dev 2>/dev/null | sed -n 's/^\tInterface //p' | tr '\n' ' ')"

# Remember which AP-side units were running so we only bring those back.
ACTIVE_UNITS=()
for unit in "${AP_UNITS[@]}"; do
    if systemctl is-active --quiet "${unit}" 2>/dev/null; then
        ACTIVE_UNITS+=("${unit}")
    fi
done
log "active ap units: ${ACTIVE_UNITS[*]:-none}"

# 1) Quiesce everything holding the radio. NetworkManager owns the STA;
#    hostapd/dnsmasq own the virtual AP interface.
for unit in "${ACTIVE_UNITS[@]}"; do
    systemctl stop "${unit}" 2>/dev/null || true
done
systemctl stop NetworkManager 2>/dev/null || true
iw dev "${AP_IFACE}" del 2>/dev/null || true
ip link set "${STA_IFACE}" down 2>/dev/null || true

# 2) Reload the driver stack. Order matters: the wcc shim holds brcmfmac,
#    brcmfmac holds brcmutil. This power-cycles the chip firmware.
modprobe -r brcmfmac_wcc 2>/dev/null || true
modprobe -r brcmfmac 2>/dev/null || true
modprobe -r brcmutil 2>/dev/null || true
sleep 2
modprobe brcmfmac
log "driver reloaded"

# 3) Wait for the base interface to come back.
waited=0
while [[ ${waited} -lt 15 ]] && ! ip link show "${STA_IFACE}" >/dev/null 2>&1; do
    sleep 1
    waited=$((waited + 1))
done
if ! ip link show "${STA_IFACE}" >/dev/null 2>&1; then
    log "FAIL: ${STA_IFACE} did not reappear after driver reload -- reboot needed"
    exit 1
fi
log "${STA_IFACE} back after ${waited}s"

# 4) Bring the stack back in boot order: NM re-manages the STA, prepare
#    recreates uap0, then the AP-side units that were running before.
systemctl start NetworkManager 2>/dev/null || true
if systemctl cat mfnavis_apsta_prepare >/dev/null 2>&1; then
    systemctl restart mfnavis_apsta_prepare 2>/dev/null || true
fi
for unit in "${ACTIVE_UNITS[@]}"; do
    systemctl start "${unit}" 2>/dev/null || true
done

# 5) Give the STA a moment to associate, then report.
waited=0
while [[ ${waited} -lt 20 ]]; do
    state="$(sta_state | head -1)"
    [[ "${state}" == "COMPLETED" ]] && break
    sleep 1
    waited=$((waited + 1))
done
state="$(sta_state | head -1)"
ap_up="down"
ip link show "${AP_IFACE}" 2>/dev/null | grep -q "state UP" && ap_up="up"
log "post: sta=${state:-none} (${waited}s) ap=${ap_up}"
log "=== wifi recover done ==="

# STA COMPLETED or a running AP both count as success (client-only setups
# have no AP units; field AP-only setups may have no STA network in range).
if [[ "${state}" == "COMPLETED" || "${ap_up}" == "up" ]]; then
    exit 0
fi
exit 1
