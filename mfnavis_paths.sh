#!/usr/bin/env bash
# Shared path helpers for MFNavis shell install/update scripts.

set -e

if [[ -z "${MFNAVIS_REPO_DIR:-}" ]]; then
    MFNAVIS_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [[ -z "${MFNAVIS_USER:-}" ]]; then
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        MFNAVIS_USER="${SUDO_USER}"
    else
        MFNAVIS_USER="$(id -un)"
        if [[ "${MFNAVIS_USER}" == "root" ]]; then
            MFNAVIS_USER="$(stat -c '%U' "${MFNAVIS_REPO_DIR}")"
        fi
    fi
fi

if [[ "${MFNAVIS_USER}" == "root" ]]; then
    echo "MFNavis must be installed for a non-root OS user." >&2
    echo "Set MFNAVIS_USER=<user> when the checkout is owned by root." >&2
    exit 1
fi

MFNAVIS_GROUP="$(id -gn "${MFNAVIS_USER}")"

if [[ -z "${MFNAVIS_HOME:-}" ]]; then
    MFNAVIS_HOME="$(getent passwd "${MFNAVIS_USER}" | cut -d: -f6)"
fi

if [[ -z "${MFNAVIS_HOME}" || ! -d "${MFNAVIS_HOME}" ]]; then
    echo "Could not determine home directory for ${MFNAVIS_USER}" >&2
    exit 1
fi

if [[ -z "${MFNAVIS_DATA_DIR:-}" ]]; then
    MFNAVIS_DATA_DIR="${MFNAVIS_HOME}/MFNavis_data"
fi

export MFNAVIS_USER
export MFNAVIS_GROUP
export MFNAVIS_HOME
export MFNAVIS_REPO_DIR
export MFNAVIS_DATA_DIR

mfnavis_render_config() {
    local source_file="$1"
    local target_file="$2"

    sudo sed \
        -e "s|__MFNAVIS_USER__|${MFNAVIS_USER}|g" \
        -e "s|__MFNAVIS_HOME__|${MFNAVIS_HOME}|g" \
        -e "s|__MFNAVIS_REPO_DIR__|${MFNAVIS_REPO_DIR}|g" \
        -e "s|__MFNAVIS_DATA_DIR__|${MFNAVIS_DATA_DIR}|g" \
        "${source_file}" | sudo tee "${target_file}" >/dev/null
}

mfnavis_prepare_wpa_supplicant_config() {
    sudo install -d -m 755 /etc/wpa_supplicant
    sudo touch /etc/wpa_supplicant/wpa_supplicant.conf
    sudo chown "${MFNAVIS_USER}:${MFNAVIS_GROUP}" /etc/wpa_supplicant/wpa_supplicant.conf
    sudo chmod 600 /etc/wpa_supplicant/wpa_supplicant.conf
}

mfnavis_prepare_apsta_nat_config() {
    local config_path="${1:-/etc/mfnavis_apsta_nat.conf}"
    if [[ ! -f "${config_path}" ]]; then
        printf "%s\n" \
            "# MFNavis AP+STA internet sharing setting" \
            "MFNAVIS_APSTA_SHARE_INTERNET=0" | sudo tee "${config_path}" >/dev/null
    # Earlier MFNavis installs used this key in the same config file.
    elif sudo grep -q '^PIFINDER_APSTA_SHARE_INTERNET=' "${config_path}"; then
        if sudo grep -q '^MFNAVIS_APSTA_SHARE_INTERNET=' "${config_path}"; then
            sudo sed -i '/^PIFINDER_APSTA_SHARE_INTERNET=/d' "${config_path}"
        else
            sudo sed -i 's/^PIFINDER_APSTA_SHARE_INTERNET=/MFNAVIS_APSTA_SHARE_INTERNET=/' \
                "${config_path}"
        fi
    fi
    sudo chmod 644 "${config_path}"
}

mfnavis_prepare_sta_band_config() {
    local config_path="${1:-/etc/mfnavis_sta_band.conf}"
    if [[ ! -f "${config_path}" ]]; then
        printf "%s\n" \
            "# MFNavis STA band preference" \
            "MFNAVIS_STA_BAND=auto" | sudo tee "${config_path}" >/dev/null
    # Earlier MFNavis installs used this key in the same config file.
    elif sudo grep -q '^PIFINDER_STA_BAND=' "${config_path}"; then
        if sudo grep -q '^MFNAVIS_STA_BAND=' "${config_path}"; then
            sudo sed -i '/^PIFINDER_STA_BAND=/d' "${config_path}"
        else
            sudo sed -i 's/^PIFINDER_STA_BAND=/MFNAVIS_STA_BAND=/' \
                "${config_path}"
        fi
    fi
    sudo chmod 644 "${config_path}"
}

mfnavis_boot_config_path() {
    if [[ -e /boot/firmware/config.txt ]]; then
        printf "%s\n" "/boot/firmware/config.txt"
    else
        printf "%s\n" "/boot/config.txt"
    fi
}

mfnavis_board_model() {
    if [[ -r /proc/device-tree/model ]]; then
        tr -d '\0' </proc/device-tree/model
    fi
}

mfnavis_board_profile() {
    local model="${1:-}"

    if [[ -z "${model}" ]]; then
        model="$(mfnavis_board_model)"
    fi

    case "${model}" in
        *"Raspberry Pi 5"*|*"Compute Module 5"*)
            printf "%s\n" "pi5_class"
            ;;
        *"Raspberry Pi 4"*)
            printf "%s\n" "pi4"
            ;;
        *)
            printf "%s\n" "legacy"
            ;;
    esac
}

mfnavis_uart_overlay() {
    case "$(mfnavis_board_profile)" in
        pi5_class)
            printf "%s\n" "dtoverlay=uart2-pi5"
            ;;
        *)
            printf "%s\n" "dtoverlay=uart3"
            ;;
    esac
}

# Device-tree overlay that exposes the keypad backlight PWM on GPIO13
# (PWM channel 1).  Pi 1-4 use the SoC PWM block via the single-channel "pwm"
# overlay; the Pi 5 / CM5 drive PWM through the RP1 controller, which needs the
# two-channel overlay to map GPIO13 to channel 1.
#
# NOTE(pi5): the RP1 pin function selector (func2=4) is a best-effort default
# and should be confirmed on Pi 5 hardware together with pwm_chip=2 in
# python/MFNavis/board_config.py.
mfnavis_pwm_overlay() {
    case "$(mfnavis_board_profile)" in
        pi5_class)
            printf "%s\n" "dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4"
            ;;
        *)
            printf "%s\n" "dtoverlay=pwm,pin=13,func=4"
            ;;
    esac
}

mfnavis_gps_device() {
    case "$(mfnavis_board_profile)" in
        pi5_class)
            printf "%s\n" "/dev/ttyAMA2"
            ;;
        pi4)
            printf "%s\n" "/dev/ttyAMA3"
            ;;
        *)
            printf "%s\n" "/dev/ttyAMA1"
            ;;
    esac
}
