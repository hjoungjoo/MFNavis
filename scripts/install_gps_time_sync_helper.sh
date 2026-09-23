#!/usr/bin/env bash
# Install or manage the optional privileged MFNavis time-sync helper service.
#
# chronyd is the preferred default system-clock manager. This helper is still
# useful for RTC writes and for the explicit `time_sync_clock_manager=pifinder`
# fallback mode.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIFINDER_REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

SERVICE_NAME="mfnavis_gps_time_sync.service"
SERVICE_TEMPLATE="${PIFINDER_REPO_DIR}/pi_config_files/${SERVICE_NAME}"
SERVICE_TARGET="/lib/systemd/system/${SERVICE_NAME}"
SERVICE_DROPIN_DIR="/etc/systemd/system/${SERVICE_NAME}.d"
DRY_RUN_DROPIN="${SERVICE_DROPIN_DIR}/dry-run.conf"

migrate_service() {
    sudo python3 "${PIFINDER_REPO_DIR}/scripts/apply_product_branding.py" \
        --apply --services-only --unit pifinder_gps_time_sync
}

install_service() {
    migrate_service
    pifinder_render_config "${SERVICE_TEMPLATE}" "${SERVICE_TARGET}"
    sudo systemctl daemon-reload
    echo "Installed ${SERVICE_NAME}"
    echo "Note: chronyd remains the preferred system-clock manager."
    echo "      MFNavis helper writes the system clock only in pifinder clock-manager mode."
}

install_dry_run_override() {
    sudo install -d -m 755 "${SERVICE_DROPIN_DIR}"
    printf "%s\n" \
        "[Service]" \
        "ExecStart=" \
        "ExecStart=/usr/bin/python -m MFNavis.gps_time_sync_helper --dry-run" \
        | sudo tee "${DRY_RUN_DROPIN}" >/dev/null
    sudo systemctl daemon-reload
    echo "Installed dry-run override for ${SERVICE_NAME}"
}

remove_dry_run_override() {
    sudo rm -f "${DRY_RUN_DROPIN}" \
        /etc/systemd/system/pifinder_gps_time_sync.service.d/dry-run.conf
    sudo rmdir "${SERVICE_DROPIN_DIR}" 2>/dev/null || true
    sudo systemctl daemon-reload
}

case "${1:-install}" in
    install)
        install_service
        echo "Service installed but not enabled."
        echo "Run: $0 enable"
        ;;
    enable)
        install_service
        remove_dry_run_override
        echo "Enabling helper. Keep time_sync_clock_manager=chrony for normal installs."
        sudo systemctl enable --now "${SERVICE_NAME}"
        ;;
    enable-dry-run)
        install_service
        install_dry_run_override
        sudo systemctl enable --now "${SERVICE_NAME}"
        ;;
    disable)
        migrate_service
        sudo systemctl disable --now "${SERVICE_NAME}" 2>/dev/null || true
        remove_dry_run_override
        ;;
    restart)
        install_service
        sudo systemctl restart "${SERVICE_NAME}"
        ;;
    restart-dry-run)
        install_service
        install_dry_run_override
        sudo systemctl restart "${SERVICE_NAME}"
        ;;
    status)
        systemctl status "${SERVICE_NAME}" --no-pager
        ;;
    *)
        echo "Usage: $0 {install|enable|enable-dry-run|disable|restart|restart-dry-run|status}" >&2
        exit 2
        ;;
esac
