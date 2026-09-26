#!/usr/bin/env bash
set -e

MFNAVIS_REPO_DIR="${MFNAVIS_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
source "${MFNAVIS_REPO_DIR}/mfnavis_paths.sh"

python3 "${MFNAVIS_REPO_DIR}/scripts/check_cedar_free.py" --repo "${MFNAVIS_REPO_DIR}"
# The transactional updater already prepared the pinned native build. Its
# activation must never mutate system packages or run OS migrations.
if [[ "${MFNAVIS_CODE_UPDATE:-0}" == "1" ]]; then
    echo "Prepared code update activated; system installation unchanged."
    return 0 2>/dev/null || exit 0
fi
bash "${MFNAVIS_REPO_DIR}/scripts/ensure_tetra3_link.sh" "${MFNAVIS_REPO_DIR}"
bash "${MFNAVIS_REPO_DIR}/scripts/setup_mfds.sh"
MFNAVIS_REPO_DIR="$(realpath "${MFNAVIS_REPO_DIR}")"
MFNAVIS_DATA_DIR="$(realpath -m "${MFNAVIS_DATA_DIR}")"
export MFNAVIS_REPO_DIR MFNAVIS_DATA_DIR
sudo python3 -m pip install --break-system-packages -r "${MFNAVIS_REPO_DIR}/python/requirements.txt"
mfnavis_prepare_apsta_nat_config
mfnavis_prepare_sta_band_config
bash "${MFNAVIS_REPO_DIR}/scripts/install_runtime_control.sh" "${MFNAVIS_USER}"

# wifi_status.txt is runtime state and no longer tracked, so the update that
# untracked it deletes any unmodified copy. Re-seed it to the installer's
# default rather than leaving the file absent. A device that was in AP or
# AP+STA reads as Client after this and has to have the mode re-selected --
# the OS network config is untouched, only this record of it is lost.
if ! [ -f "${MFNAVIS_REPO_DIR}/wifi_status.txt" ]
then
    echo -n "Client" > "${MFNAVIS_REPO_DIR}/wifi_status.txt"
fi

# Set up migrations folder if it does not exist
if ! [ -d "${MFNAVIS_DATA_DIR}/migrations" ]
then
    mkdir -p "${MFNAVIS_DATA_DIR}/migrations"
fi

# v1.x.x
# everying prior to selecitve migrations
if ! [ -f "${MFNAVIS_DATA_DIR}/migrations/v1.x.x" ]
then
    source "${MFNAVIS_REPO_DIR}/migration_source/v1.x.x.sh"
    touch "${MFNAVIS_DATA_DIR}/migrations/v1.x.x"
fi

# v2.1.0
# Switch to Cedar
if ! [ -f "${MFNAVIS_DATA_DIR}/migrations/v2.1.0" ]
then
    source "${MFNAVIS_REPO_DIR}/migration_source/v2.1.0.sh"
    touch "${MFNAVIS_DATA_DIR}/migrations/v2.1.0"
fi

# v2.2.1
# Install libinput
if ! [ -f "${MFNAVIS_DATA_DIR}/migrations/v2.2.1" ]
then
    source "${MFNAVIS_REPO_DIR}/migration_source/v2.2.1.sh"
    touch "${MFNAVIS_DATA_DIR}/migrations/v2.2.1"
fi

# v2.2.2
# Enable host usb on usb-c port
if ! [ -f "${MFNAVIS_DATA_DIR}/migrations/v2.2.2" ]
then
    source "${MFNAVIS_REPO_DIR}/migration_source/v2.2.2.sh"
    touch "${MFNAVIS_DATA_DIR}/migrations/v2.2.2"
fi

# v2.4.0
# Switch detect to system process
if ! [ -f "${MFNAVIS_DATA_DIR}/migrations/v2.4.0" ]
then
    source "${MFNAVIS_REPO_DIR}/migration_source/v2.4.0.sh"
    touch "${MFNAVIS_DATA_DIR}/migrations/v2.4.0"
fi

# v2.6.0
# Clear stale flop_image=true on the default Dobsonian (flip/flop now live)
if ! [ -f "${MFNAVIS_DATA_DIR}/migrations/v2.6.0" ]
then
    source "${MFNAVIS_REPO_DIR}/migration_source/v2.6.0.sh"
    touch "${MFNAVIS_DATA_DIR}/migrations/v2.6.0"
fi

# mf_apsta_wifi
# Install AP+STA Wi-Fi support files and systemd units.
if ! [ -f "${MFNAVIS_DATA_DIR}/migrations/mf_apsta_wifi" ]
then
    source "${MFNAVIS_REPO_DIR}/migration_source/mf_apsta_wifi.sh"
    touch "${MFNAVIS_DATA_DIR}/migrations/mf_apsta_wifi"
fi

# mf_wifi_settings
# Import OS-provisioned Wi-Fi profiles into MFNavis's editable STA list.
if ! [ -f "${MFNAVIS_DATA_DIR}/migrations/mf_wifi_settings" ]
then
    source "${MFNAVIS_REPO_DIR}/migration_source/mf_wifi_settings.sh"
    touch "${MFNAVIS_DATA_DIR}/migrations/mf_wifi_settings"
fi

# mf_removeipc
# RemoveIPC=no so SSH logouts can't reap the solver's shared memory
if ! [ -f "${MFNAVIS_DATA_DIR}/migrations/mf_removeipc" ]
then
    source "${MFNAVIS_REPO_DIR}/migration_source/mf_removeipc.sh"
    touch "${MFNAVIS_DATA_DIR}/migrations/mf_removeipc"
fi

# Keep the device-specific power-key mapping in sync on existing installs too.
# Idempotent; also installs the rule when the keyboard is not connected.
bash "${MFNAVIS_REPO_DIR}/scripts/install_keyboard_power_ignore.sh" || return $?

# DONE
echo "MFNavis system update complete"
