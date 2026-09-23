#!/usr/bin/env bash
# Shared path helpers for PiFinder shell install/update scripts.

set -e

if [[ -z "${PIFINDER_REPO_DIR:-}" ]]; then
    PIFINDER_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [[ -z "${PIFINDER_USER:-}" ]]; then
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        PIFINDER_USER="${SUDO_USER}"
    else
        PIFINDER_USER="$(id -un)"
    fi
fi

if [[ "${PIFINDER_USER}" == "root" ]]; then
    echo "MFNavis must be installed for a non-root OS user." >&2
    echo "Set PIFINDER_USER=<user> when running as root." >&2
    exit 1
fi

if [[ -z "${PIFINDER_HOME:-}" ]]; then
    PIFINDER_HOME="$(getent passwd "${PIFINDER_USER}" | cut -d: -f6)"
fi

if [[ -z "${PIFINDER_HOME}" || ! -d "${PIFINDER_HOME}" ]]; then
    echo "Could not determine home directory for ${PIFINDER_USER}" >&2
    exit 1
fi

PIFINDER_DATA_DIR="${PIFINDER_DATA_DIR:-${PIFINDER_HOME}/PiFinder_data}"

export PIFINDER_USER
export PIFINDER_HOME
export PIFINDER_REPO_DIR
export PIFINDER_DATA_DIR

pifinder_render_config() {
    local source_file="$1"
    local target_file="$2"

    sudo sed \
        -e "s|__PIFINDER_USER__|${PIFINDER_USER}|g" \
        -e "s|__PIFINDER_HOME__|${PIFINDER_HOME}|g" \
        -e "s|__PIFINDER_REPO_DIR__|${PIFINDER_REPO_DIR}|g" \
        -e "s|__PIFINDER_DATA_DIR__|${PIFINDER_DATA_DIR}|g" \
        "${source_file}" | sudo tee "${target_file}" >/dev/null
}

pifinder_prepare_wpa_supplicant_config() {
    sudo install -d -m 755 /etc/wpa_supplicant
    sudo touch /etc/wpa_supplicant/wpa_supplicant.conf
    sudo chown "${PIFINDER_USER}:${PIFINDER_USER}" /etc/wpa_supplicant/wpa_supplicant.conf
    sudo chmod 600 /etc/wpa_supplicant/wpa_supplicant.conf
}

pifinder_prepare_apsta_nat_config() {
    if [[ ! -f /etc/pifinder_apsta_nat.conf ]]; then
        printf "%s\n" \
            "# PiFinder AP+STA internet sharing setting" \
            "PIFINDER_APSTA_SHARE_INTERNET=0" | sudo tee /etc/pifinder_apsta_nat.conf >/dev/null
    fi
    sudo chmod 644 /etc/pifinder_apsta_nat.conf
}

pifinder_prepare_sta_band_config() {
    if [[ ! -f /etc/pifinder_sta_band.conf ]]; then
        printf "%s\n" \
            "# PiFinder STA band preference" \
            "PIFINDER_STA_BAND=auto" | sudo tee /etc/pifinder_sta_band.conf >/dev/null
    fi
    sudo chmod 644 /etc/pifinder_sta_band.conf
}

pifinder_boot_config_path() {
    if [[ -e /boot/firmware/config.txt ]]; then
        printf "%s\n" "/boot/firmware/config.txt"
    else
        printf "%s\n" "/boot/config.txt"
    fi
}

pifinder_board_model() {
    if [[ -r /proc/device-tree/model ]]; then
        tr -d '\0' </proc/device-tree/model
    fi
}

pifinder_board_profile() {
    local model="${1:-}"

    if [[ -z "${model}" ]]; then
        model="$(pifinder_board_model)"
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

pifinder_uart_overlay() {
    case "$(pifinder_board_profile)" in
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
# python/PiFinder/board_config.py.
pifinder_pwm_overlay() {
    case "$(pifinder_board_profile)" in
        pi5_class)
            printf "%s\n" "dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4"
            ;;
        *)
            printf "%s\n" "dtoverlay=pwm,pin=13,func=4"
            ;;
    esac
}

pifinder_gps_device() {
    case "$(pifinder_board_profile)" in
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
