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

# Reserve only GPIO13 for legacy PWM, leaving GPIO12 free to release/reset
# the AW9523B before startup identification on any supported carrier.
mfnavis_pwm_overlay() {
    printf '%s\n' 'dtoverlay=pwm,pin=13,func=4'
}

mfnavis_configure_i2c_boot() {
    local boot_config="$1"
    # BNO086/AW9523/FRAM on A0 and legacy BNO055 share GPIO2/3.
    # RP1 supports hardware clock stretching; older Pis retain software I2C.
    # Replace individual settings, but preserve compound dtparam lines (which
    # may also configure unrelated hardware). The final [all] block wins.
    sudo sed -i -E \
        -e '/^# BEGIN MFNavis I2C$/,/^# END MFNavis I2C$/d' \
        -e '/^[[:space:]]*dtparam=i2c_arm(=[^,[:space:]#]+)?[[:space:]]*(#.*)?$/d' \
        -e '/^[[:space:]]*dtparam=i2c_arm_baudrate=[^,[:space:]#]+[[:space:]]*(#.*)?$/d' \
        -e '/^[[:space:]]*dtoverlay=i2c-gpio([,#[:space:]]|$)/d' \
        "${boot_config}" || return
    {
        printf '%s\n' '# BEGIN MFNavis I2C' '[all]'
        if [[ "$(mfnavis_board_profile)" == pi5_class ]]; then
            printf '%s\n' 'dtparam=i2c_arm=on' 'dtparam=i2c_arm_baudrate=400000'
        else
            printf '%s\n' 'dtparam=i2c_arm=off' \
                'dtoverlay=i2c-gpio,i2c_gpio_sda=2,i2c_gpio_scl=3,bus=3'
        fi
        printf '%s\n' '# END MFNavis I2C'
    } | sudo tee -a "${boot_config}" >/dev/null
}

mfnavis_configure_keypad_boot() {
    local boot_config="$1"
    # Migrate older installations as well as replacing our own managed block.
    # A0 GPIO12 must not be claimed by the legacy PWM controller.
    sudo sed -i -E \
        -e '/^# BEGIN MFNavis keypad$/,/^# END MFNavis keypad$/d' \
        -e '/^[[:space:]]*dtoverlay=pwm(-2chan)?([,#[:space:]]|$)/d' \
        "${boot_config}"
    {
        printf '%s\n' '# BEGIN MFNavis keypad' '[all]'
        printf '%s\n' 'gpio=12=op,dl,pd'
        mfnavis_pwm_overlay
        printf '%s\n' '# END MFNavis keypad'
    } | sudo tee -a "${boot_config}" >/dev/null
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
