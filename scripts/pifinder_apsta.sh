#!/usr/bin/env bash
# Manage PiFinder's AP+STA Wi-Fi mode.
#
# wlan0 remains the STA interface for internet access. uap0 is a virtual AP
# interface used by hostapd/dnsmasq for MFNavisAP. Broadcom single-radio
# devices require the AP to follow the associated STA channel, so monitor mode
# rewrites hostapd.conf and restarts hostapd when the STA channel changes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MFNAVIS_REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

STA_IFACE="${MFNAVIS_STA_IFACE:-wlan0}"
AP_IFACE="${MFNAVIS_AP_IFACE:-uap0}"
AP_IP_CIDR="${MFNAVIS_AP_IP_CIDR:-}"
DEFAULT_CHANNEL="${MFNAVIS_AP_DEFAULT_CHANNEL:-7}"
CHANNEL_WAIT_SECONDS="${MFNAVIS_APSTA_CHANNEL_WAIT_SECONDS:-15}"
STATUS_FILE="${MFNAVIS_REPO_DIR}/wifi_status.txt"
HOSTAPD_CONF="${MFNAVIS_HOSTAPD_CONF:-/etc/hostapd/hostapd.conf}"
DNSMASQ_CONF="${MFNAVIS_DNSMASQ_CONF:-/etc/dnsmasq.conf}"
APSTA_DHCPCD_CONF="${MFNAVIS_APSTA_DHCPCD_CONF:-/etc/dhcpcd.conf.apsta}"
APSTA_NAT_CONF="${MFNAVIS_APSTA_NAT_CONF:-/etc/mfnavis_apsta_nat.conf}"
NFT_TABLE="${MFNAVIS_APSTA_NFT_TABLE:-pifinder_apsta}"

IW_BIN="${IW_BIN:-$(command -v iw || true)}"
IP_BIN="${IP_BIN:-$(command -v ip || true)}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-$(command -v systemctl || true)}"
SYSCTL_BIN="${SYSCTL_BIN:-$(command -v sysctl || true)}"
NFT_BIN="${NFT_BIN:-$(command -v nft || true)}"
NMCLI_BIN="${NMCLI_BIN:-$(command -v nmcli || true)}"

log() {
    printf "pifinder_apsta: %s\n" "$*" >&2
}

wifi_mode() {
    if [[ -r "${STATUS_FILE}" ]]; then
        tr -d '\n' <"${STATUS_FILE}"
    else
        printf "Client"
    fi
}

is_apsta_mode() {
    [[ "$(wifi_mode)" == "AP+STA" ]]
}

ap_ip_cidr() {
    if [[ -n "${AP_IP_CIDR}" ]]; then
        printf "%s\n" "${AP_IP_CIDR}"
        return
    fi
    sed -n 's/^[[:space:]]*static ip_address=//p' "${APSTA_DHCPCD_CONF}" 2>/dev/null | head -n 1
}

require_commands() {
    if [[ -z "${IW_BIN}" || -z "${IP_BIN}" ]]; then
        log "iw and ip are required for AP+STA mode"
        exit 1
    fi
}

freq_to_channel() {
    local freq="$1"
    if [[ -z "${freq}" ]]; then
        return 1
    fi
    if [[ "${freq}" -eq 2484 ]]; then
        printf "14\n"
    elif [[ "${freq}" -ge 2412 && "${freq}" -le 2472 ]]; then
        printf "%s\n" $(((freq - 2407) / 5))
    elif [[ "${freq}" -ge 5000 && "${freq}" -le 5900 ]]; then
        printf "%s\n" $(((freq - 5000) / 5))
    else
        return 1
    fi
}

sta_channel() {
    local channel
    channel="$(sta_channel_or_empty)"
    if [[ -n "${channel}" ]]; then
        printf "%s\n" "${channel}"
        return
    fi
    printf "%s\n" "${DEFAULT_CHANNEL}"
}

sta_channel_or_empty() {
    local link_output freq channel
    link_output="$("${IW_BIN}" dev "${STA_IFACE}" link 2>/dev/null || true)"
    freq="$(awk '/freq:/ {print $2; exit}' <<<"${link_output}")"
    channel="$(freq_to_channel "${freq}" 2>/dev/null || true)"
    if [[ -n "${channel}" ]]; then
        printf "%s\n" "${channel}"
        return 0
    fi
    return 0
}

wait_sta_channel() {
    local channel elapsed=0
    while [[ "${elapsed}" -lt "${CHANNEL_WAIT_SECONDS}" ]]; do
        channel="$(sta_channel_or_empty)"
        if [[ -n "${channel}" ]]; then
            printf "%s\n" "${channel}"
            return
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    printf "%s\n" "${DEFAULT_CHANNEL}"
}

channel_hw_mode() {
    local channel="$1"
    if [[ "${channel}" -gt 14 ]]; then
        printf "a\n"
    else
        printf "g\n"
    fi
}

update_key_value_file() {
    local path="$1"
    local key="$2"
    local value="$3"
    local tmp
    tmp="$(mktemp)"
    if [[ -f "${path}" ]]; then
        awk -v key="${key}" -v value="${value}" '
            BEGIN { found = 0 }
            $0 ~ "^" key "=" {
                print key "=" value
                found = 1
                next
            }
            { print }
            END {
                if (!found) {
                    print key "=" value
                }
            }
        ' "${path}" >"${tmp}"
    else
        printf "%s=%s\n" "${key}" "${value}" >"${tmp}"
    fi
    cp "${tmp}" "${path}"
    rm -f "${tmp}"
}

configure_hostapd() {
    local interface="$1"
    local channel="$2"
    local hw_mode
    hw_mode="$(channel_hw_mode "${channel}")"
    update_key_value_file "${HOSTAPD_CONF}" "interface" "${interface}"
    update_key_value_file "${HOSTAPD_CONF}" "channel" "${channel}"
    update_key_value_file "${HOSTAPD_CONF}" "hw_mode" "${hw_mode}"
}

current_hostapd_channel() {
    awk -F= '/^channel=/ {print $2; exit}' "${HOSTAPD_CONF}" 2>/dev/null || true
}

configure_dnsmasq() {
    local interface="$1"
    update_key_value_file "${DNSMASQ_CONF}" "interface" "${interface} # Listening interface"
}

ap_iface_exists() {
    "${IW_BIN}" dev "${AP_IFACE}" info >/dev/null 2>&1
}

ensure_ap_iface() {
    require_commands
    if ap_iface_exists; then
        return
    fi
    log "creating ${AP_IFACE} on ${STA_IFACE}"
    "${IW_BIN}" dev "${STA_IFACE}" interface add "${AP_IFACE}" type __ap
}

configure_ap_ip() {
    require_commands
    local cidr
    cidr="$(ap_ip_cidr)"
    if [[ -z "${cidr}" ]]; then
        cidr="10.10.10.1/24"
    fi
    "${IP_BIN}" link set "${AP_IFACE}" up
    "${IP_BIN}" addr replace "${cidr}" dev "${AP_IFACE}"
}

internet_sharing_enabled() {
    grep -qx 'MFNAVIS_APSTA_SHARE_INTERNET=1' "${APSTA_NAT_CONF}" 2>/dev/null
}

sta_has_default_route() {
    "${IP_BIN}" route show default dev "${STA_IFACE}" 2>/dev/null | grep -q '^default '
}

nft_table_exists() {
    [[ -n "${NFT_BIN}" ]] && "${NFT_BIN}" list table ip "${NFT_TABLE}" >/dev/null 2>&1
}

enable_internet_sharing() {
    if [[ -z "${NFT_BIN}" || -z "${SYSCTL_BIN}" ]]; then
        log "nft and sysctl are required for AP+STA internet sharing"
        return 0
    fi
    if ! sta_has_default_route; then
        disable_internet_sharing
        return 0
    fi
    "${SYSCTL_BIN}" -w net.ipv4.ip_forward=1 >/dev/null
    if nft_table_exists; then
        return 0
    fi
    "${NFT_BIN}" add table ip "${NFT_TABLE}"
    "${NFT_BIN}" add chain ip "${NFT_TABLE}" postrouting "{ type nat hook postrouting priority srcnat; policy accept; }"
    "${NFT_BIN}" add chain ip "${NFT_TABLE}" forward "{ type filter hook forward priority filter; policy accept; }"
    "${NFT_BIN}" add rule ip "${NFT_TABLE}" postrouting oifname "${STA_IFACE}" masquerade
    "${NFT_BIN}" add rule ip "${NFT_TABLE}" forward iifname "${AP_IFACE}" oifname "${STA_IFACE}" accept
    "${NFT_BIN}" add rule ip "${NFT_TABLE}" forward iifname "${STA_IFACE}" oifname "${AP_IFACE}" ct state related,established accept
    log "AP+STA internet sharing enabled"
}

disable_internet_sharing() {
    if [[ -n "${NFT_BIN}" ]]; then
        "${NFT_BIN}" delete table ip "${NFT_TABLE}" >/dev/null 2>&1 || true
    fi
}

configure_internet_sharing() {
    if is_apsta_mode && internet_sharing_enabled; then
        enable_internet_sharing
    else
        disable_internet_sharing
    fi
}

prepare_apsta() {
    if ! is_apsta_mode; then
        log "not in AP+STA mode; skipping prepare"
        return 0
    fi
    local channel
    channel="$(wait_sta_channel)"
    ensure_ap_iface
    configure_dnsmasq "${AP_IFACE}"
    configure_hostapd "${AP_IFACE}" "${channel}"
    configure_ap_ip
    configure_internet_sharing
    log "prepared ${AP_IFACE} on channel ${channel}"
}

nm_is_running() {
    [[ -n "${NMCLI_BIN}" ]] && "${NMCLI_BIN}" general status >/dev/null 2>&1
}

release_sta() {
    # Free the shared single radio for AP-only use. A plain `device disconnect`
    # is not enough: the wlan0 profile has connection.autoconnect=yes, so
    # NetworkManager immediately reconnects wlan0 to its saved network and pins
    # the radio to that STA channel. On a single-radio device the AP (uap0) must
    # share that channel, so hostapd cannot bring uap0 up on the default channel
    # and the AP never starts. Take wlan0 out of NetworkManager entirely and
    # bring it down instead. `managed no` is a runtime setting, so a normal
    # reboot (used when switching back to Client/AP+STA) restores management.
    if [[ -n "${NMCLI_BIN}" ]]; then
        # prepare can race NetworkManager's boot-time auto-connect; wait briefly
        # so the unmanage actually sticks.
        local waited=0
        while [[ "${waited}" -lt 10 ]] && ! nm_is_running; do
            sleep 1
            waited=$((waited + 1))
        done
        "${NMCLI_BIN}" device set "${STA_IFACE}" managed no >/dev/null 2>&1 || true
    fi
    if [[ -n "${IP_BIN}" ]]; then
        "${IP_BIN}" link set "${STA_IFACE}" down 2>/dev/null || true
    fi
}

prepare_ap_only() {
    # AP-only reuses the AP+STA plumbing: hostapd/dnsmasq bind the uap0 virtual
    # interface and the AP IP is assigned directly with `ip addr`. This is the
    # NetworkManager-friendly path; binding hostapd to wlan0 with a dhcpcd
    # static IP does not work on Bookworm because dhcpcd is disabled and NM
    # keeps wlan0 in managed (STA) mode.
    disable_internet_sharing
    release_sta
    ensure_ap_iface
    configure_dnsmasq "${AP_IFACE}"
    configure_hostapd "${AP_IFACE}" "${DEFAULT_CHANNEL}"
    configure_ap_ip
    log "prepared ${AP_IFACE} (AP-only) on channel ${DEFAULT_CHANNEL}"
}

cleanup_apsta() {
    require_commands
    disable_internet_sharing
    if ap_iface_exists; then
        "${IP_BIN}" link set "${AP_IFACE}" down 2>/dev/null || true
        "${IW_BIN}" dev "${AP_IFACE}" del 2>/dev/null || true
        log "removed ${AP_IFACE}"
    fi
}

restart_hostapd() {
    if [[ -n "${SYSTEMCTL_BIN}" ]]; then
        "${SYSTEMCTL_BIN}" restart hostapd || true
    fi
}

monitor_apsta() {
    local last_channel candidate stable_channel stable_count
    last_channel="$(current_hostapd_channel)"
    stable_channel=""
    stable_count=0
    while true; do
        if ! is_apsta_mode; then
            sleep 30
            continue
        fi

        ensure_ap_iface
        configure_ap_ip
        configure_internet_sharing

        # Only follow the STA channel when the STA is actually associated.
        # sta_channel_or_empty returns empty while wlan0 is disconnected or
        # roaming; in that case keep the AP on its current channel instead of
        # flapping to DEFAULT_CHANNEL and restarting hostapd (which drops every
        # AP client) on every cycle. A single-radio device also cannot host the
        # AP on a different channel than the STA association, so a bad guess
        # actively breaks the AP.
        candidate="$(sta_channel_or_empty)"
        if [[ -n "${candidate}" ]]; then
            # Require the same channel twice in a row before acting so a brief
            # roam does not trigger an unnecessary hostapd restart.
            if [[ "${candidate}" == "${stable_channel}" ]]; then
                stable_count=$((stable_count + 1))
            else
                stable_channel="${candidate}"
                stable_count=1
            fi
            if [[ "${stable_count}" -ge 2 && "${candidate}" != "${last_channel}" ]]; then
                configure_hostapd "${AP_IFACE}" "${candidate}"
                restart_hostapd
                last_channel="${candidate}"
                log "hostapd set to STA channel ${candidate}"
            fi
        fi
        sleep 20
    done
}

case "${1:-prepare}" in
    prepare)
        case "$(wifi_mode)" in
            "AP+STA")
                prepare_apsta
                ;;
            "AP")
                prepare_ap_only
                ;;
            *)
                log "not in an AP mode; skipping prepare"
                ;;
        esac
        ;;
    monitor)
        monitor_apsta
        ;;
    cleanup)
        cleanup_apsta
        ;;
    configure-ap)
        prepare_ap_only
        ;;
    sharing)
        configure_internet_sharing
        ;;
    channel)
        sta_channel
        ;;
    *)
        echo "Usage: $0 {prepare|monitor|cleanup|configure-ap|sharing|channel}" >&2
        exit 2
        ;;
esac
