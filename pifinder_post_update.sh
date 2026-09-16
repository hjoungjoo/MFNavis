PIFINDER_REPO_DIR="${PIFINDER_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

python3 "${PIFINDER_REPO_DIR}/scripts/check_cedar_free.py" --repo "${PIFINDER_REPO_DIR}"
# The transactional updater already prepared the pinned native build. Its
# activation must never mutate system packages or run OS migrations.
if [[ "${PIFINDER_CODE_UPDATE:-0}" == "1" ]]; then
    echo "Prepared code update activated; system installation unchanged."
    return 0 2>/dev/null || exit 0
fi
bash "${PIFINDER_REPO_DIR}/scripts/ensure_tetra3_link.sh" "${PIFINDER_REPO_DIR}"
bash "${PIFINDER_REPO_DIR}/scripts/setup_mfds.sh"
sudo python3 -m pip install --break-system-packages -r "${PIFINDER_REPO_DIR}/python/requirements.txt"

# wifi_status.txt is runtime state and no longer tracked, so the update that
# untracked it deletes any unmodified copy. Re-seed it to the installer's
# default rather than leaving the file absent. A device that was in AP or
# AP+STA reads as Client after this and has to have the mode re-selected --
# the OS network config is untouched, only this record of it is lost.
if ! [ -f "${PIFINDER_REPO_DIR}/wifi_status.txt" ]
then
    echo -n "Client" > "${PIFINDER_REPO_DIR}/wifi_status.txt"
fi

# Set up migrations folder if it does not exist
if ! [ -d "${PIFINDER_DATA_DIR}/migrations" ]
then
    mkdir -p "${PIFINDER_DATA_DIR}/migrations"
fi

# v1.x.x
# everying prior to selecitve migrations
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/v1.x.x" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/v1.x.x.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/v1.x.x"
fi

# v2.1.0
# Switch to Cedar
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/v2.1.0" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/v2.1.0.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/v2.1.0"
fi

# v2.2.1
# Install libinput
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/v2.2.1" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/v2.2.1.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/v2.2.1"
fi

# v2.2.2
# Enable host usb on usb-c port
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/v2.2.2" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/v2.2.2.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/v2.2.2"
fi

# v2.4.0
# Switch detect to system process
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/v2.4.0" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/v2.4.0.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/v2.4.0"
fi

# v2.6.0
# Clear stale flop_image=true on the default Dobsonian (flip/flop now live)
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/v2.6.0" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/v2.6.0.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/v2.6.0"
fi

# mf_apsta_wifi
# Install AP+STA Wi-Fi support files and systemd units.
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/mf_apsta_wifi" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/mf_apsta_wifi.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/mf_apsta_wifi"
fi

# mf_wifi_settings
# Import OS-provisioned Wi-Fi profiles into PiFinder's editable STA list.
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/mf_wifi_settings" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/mf_wifi_settings.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/mf_wifi_settings"
fi

# mf_removeipc
# RemoveIPC=no so SSH logouts can't reap the solver's shared memory
if ! [ -f "${PIFINDER_DATA_DIR}/migrations/mf_removeipc" ]
then
    source "${PIFINDER_REPO_DIR}/migration_source/mf_removeipc.sh"
    touch "${PIFINDER_DATA_DIR}/migrations/mf_removeipc"
fi

# Keep the device-specific power-key mapping in sync on existing installs too.
# Idempotent; also installs the rule when the keyboard is not connected.
bash "${PIFINDER_REPO_DIR}/scripts/install_keyboard_power_ignore.sh" || return $?

# DONE
echo "Post Update Complete"
