#!/usr/bin/env bash
# Install or manage chronyd as the preferred PiFinder system-clock manager.
#
# Besides installing/enabling chronyd, `install` (and `configure`) idempotently
# applies the field-timing configuration verified on 2026-07-25
# (docs/mf_report/mf_field_test_20260724_analysis_ko.md, item A2b):
#   - gpsd must run with -n so it feeds NTP SHM without waiting for a client
#     (a raw-watch-only client such as PiFinder's gps_ubx does not trigger it)
#   - chrony reads GPS time via the gpsd SHM refclock (refid gps1)
#   - makestep 1 -1 so a large offset is stepped even long after boot
#     (no RTC: fake-hwclock restores a stale time and GPS fix may arrive late)

set -euo pipefail

SERVICE_NAME="chrony.service"
if systemctl list-unit-files chronyd.service >/dev/null 2>&1; then
    SERVICE_NAME="chronyd.service"
fi

CHRONY_CONF="/etc/chrony/chrony.conf"
GPSD_DEFAULTS="/etc/default/gpsd"
REFCLOCK_LINE="refclock SHM 0 poll 3 refid gps1"

install_chrony() {
    if ! command -v chronyc >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y chrony
    fi
    sudo systemctl enable --now "${SERVICE_NAME}"
    configure_time_chain
    echo "chronyd is enabled as the system-clock manager."
}

configure_time_chain() {
    local changed_chrony=0 changed_gpsd=0

    # chrony: GPS SHM refclock (fed by gpsd)
    if ! sudo grep -Eq '^refclock SHM 0\b' "${CHRONY_CONF}"; then
        echo "${REFCLOCK_LINE}" | sudo tee -a "${CHRONY_CONF}" >/dev/null
        changed_chrony=1
    fi

    # chrony: always step large offsets, not only during the first updates
    if sudo grep -Eq '^makestep\b' "${CHRONY_CONF}"; then
        if ! sudo grep -Eq '^makestep 1 -1$' "${CHRONY_CONF}"; then
            sudo sed -i 's/^makestep\b.*/makestep 1 -1/' "${CHRONY_CONF}"
            changed_chrony=1
        fi
    else
        echo "makestep 1 -1" | sudo tee -a "${CHRONY_CONF}" >/dev/null
        changed_chrony=1
    fi

    # gpsd: -n is required for timekeeping (feed SHM without a waiting client)
    if [ -f "${GPSD_DEFAULTS}" ]; then
        # shellcheck disable=SC1090
        local current_options
        current_options=$(. "${GPSD_DEFAULTS}" && echo "${GPSD_OPTIONS:-}")
        case " ${current_options} " in
            *" -n "*) ;;
            *)
                if sudo grep -q '^GPSD_OPTIONS=' "${GPSD_DEFAULTS}"; then
                    sudo sed -i \
                        "s|^GPSD_OPTIONS=.*|GPSD_OPTIONS=\"-n ${current_options}\"|" \
                        "${GPSD_DEFAULTS}"
                else
                    printf 'GPSD_OPTIONS="-n %s"\n' "${current_options}" \
                        | sudo tee -a "${GPSD_DEFAULTS}" >/dev/null
                fi
                changed_gpsd=1
                ;;
        esac
    else
        echo "Warning: ${GPSD_DEFAULTS} not found; is gpsd installed?" >&2
    fi

    if [ "${changed_gpsd}" -eq 1 ]; then
        sudo systemctl restart gpsd.socket gpsd 2>/dev/null || true
        echo "gpsd options updated (-n added) and gpsd restarted."
    fi
    if [ "${changed_chrony}" -eq 1 ]; then
        sudo systemctl restart "${SERVICE_NAME}"
        echo "chrony configuration updated (refclock/makestep) and restarted."
    fi
    if [ "${changed_gpsd}" -eq 0 ] && [ "${changed_chrony}" -eq 0 ]; then
        echo "Time chain configuration already up to date."
    fi
}

restart_chrony() {
    sudo systemctl restart "${SERVICE_NAME}"
}

show_status() {
    systemctl status "${SERVICE_NAME}" --no-pager || true
    if command -v chronyc >/dev/null 2>&1; then
        chronyc tracking || true
        chronyc sources -v || true
    else
        echo "chronyc is not installed."
    fi
}

case "${1:-install}" in
    install|enable)
        install_chrony
        ;;
    configure)
        configure_time_chain
        ;;
    restart)
        restart_chrony
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 {install|enable|configure|restart|status}" >&2
        exit 2
        ;;
esac
