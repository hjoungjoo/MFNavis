#!/usr/bin/bash
# This script installs the PiFinder software on a prepared Raspberry Pi OS.
# See https://pifinder.readthedocs.io/en/release/software.html for more info.

set -e

if [[ "$(id -u)" -eq 0 ]]; then
    echo "Do not run this script with sudo." >&2
    echo "Run it as the target OS user; the script will use sudo when needed." >&2
    exit 1
fi

PIFINDER_USER="${PIFINDER_USER:-${SUDO_USER:-$(id -un)}}"
if [[ "${PIFINDER_USER}" == "root" ]]; then
    echo "Run as the target OS user, or set PIFINDER_USER=<user>." >&2
    exit 1
fi

PIFINDER_HOME="$(getent passwd "${PIFINDER_USER}" | cut -d: -f6)"
if [[ -z "${PIFINDER_HOME}" || ! -d "${PIFINDER_HOME}" ]]; then
    echo "Could not determine home directory for ${PIFINDER_USER}" >&2
    exit 1
fi

cd "${PIFINDER_HOME}"

sudo bash -c '
set -e
trap "rm -f /usr/sbin/policy-rc.d" EXIT
printf "%s\n" "#!/bin/sh" "exit 101" > /usr/sbin/policy-rc.d
chmod 755 /usr/sbin/policy-rc.d
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git python3-pip python3-venv python3-dev build-essential pkg-config \
    samba samba-common-bin dnsmasq hostapd dhcpcd gpsd wget iw nftables \
    libinput10 libcap2-bin libjpeg-dev zlib1g-dev libfreetype6-dev \
    liblcms2-dev libopenjp2-7-dev libtiff-dev libffi-dev libssl-dev \
    python3-picamera2 rpicam-apps i2c-tools spi-tools
'

if [[ -d PiFinder/ ]]; then
    cd PiFinder/ && git config pull.rebase false && git pull
else
    git clone --recursive --branch release https://github.com/brickbots/PiFinder.git
fi

PIFINDER_REPO_DIR="${PIFINDER_HOME}/PiFinder"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

cd "${PIFINDER_REPO_DIR}"

find_pifinder_indi_archive() {
    local archives=()
    local part_archives=()
    shopt -s nullglob
    archives=("${PIFINDER_REPO_DIR}"/dist/mf-pifinder-indi-bookworm-arm64-*.tar.gz)
    part_archives=("${PIFINDER_REPO_DIR}"/dist/mf-pifinder-indi-bookworm-arm64-*.tar.gz.part-00)
    shopt -u nullglob

    if [[ "${#archives[@]}" -gt 0 ]]; then
        printf "%s\n" "${archives[@]}" | sort | tail -n 1
    elif [[ "${#part_archives[@]}" -gt 0 ]]; then
        local latest_part
        latest_part="$(printf "%s\n" "${part_archives[@]}" | sort | tail -n 1)"
        printf "%s\n" "${latest_part%.part-00}"
    fi
}

install_optional_indi_archive() {
    local mode="${PIFINDER_INSTALL_INDI_ARCHIVE:-auto}"
    local archive="${PIFINDER_INDI_ARCHIVE:-}"

    mode="${mode,,}"
    if [[ -z "${archive}" ]]; then
        archive="$(find_pifinder_indi_archive || true)"
    fi

    case "${mode}" in
        1|true|yes|on|archive)
            if [[ -z "${archive}" ]]; then
                echo "PIFINDER_INSTALL_INDI_ARCHIVE is enabled, but no INDI archive was found." >&2
                echo "Set PIFINDER_INDI_ARCHIVE=/path/to/mf-pifinder-indi-bookworm-arm64.tar.gz." >&2
                exit 1
            fi
            ;;
        auto|"")
            if [[ -z "${archive}" ]]; then
                echo "No INDI binary archive found; skipping optional INDI mount support."
                echo "To install it during setup, put the archive in ${PIFINDER_REPO_DIR}/dist or set PIFINDER_INDI_ARCHIVE."
                return 0
            fi
            ;;
        0|false|no|off|none|skip)
            echo "Skipping optional INDI mount support."
            return 0
            ;;
        *)
            echo "Invalid PIFINDER_INSTALL_INDI_ARCHIVE value: ${mode}" >&2
            echo "Use auto, true, or false." >&2
            exit 1
            ;;
    esac

    if [[ ! -f "${archive}" && ! -f "${archive}.part-00" ]]; then
        echo "INDI archive not found: ${archive}" >&2
        exit 1
    fi

    echo "Installing optional INDI mount support from ${archive}"
    bash "${PIFINDER_REPO_DIR}/scripts/install_indi_mount_archive.sh" "${archive}"
}

sudo python3 -m pip install --break-system-packages -r python/requirements.txt

# Setup GPSD
sudo cp "${PIFINDER_REPO_DIR}/pi_config_files/gpsd.conf" /etc/default/gpsd
sudo sed -i "s|^DEVICES=.*|DEVICES=\"$(pifinder_gps_device)\"|" /etc/default/gpsd

# data dirs
sudo install -d -o "${PIFINDER_USER}" -g "${PIFINDER_USER}" -m 755 \
    "${PIFINDER_DATA_DIR}" \
    "${PIFINDER_DATA_DIR}/captures" \
    "${PIFINDER_DATA_DIR}/obslists" \
    "${PIFINDER_DATA_DIR}/screenshots" \
    "${PIFINDER_DATA_DIR}/solver_debug_dumps" \
    "${PIFINDER_DATA_DIR}/logs" \
    "${PIFINDER_DATA_DIR}/migrations"

# Wifi config
sudo cp "${PIFINDER_REPO_DIR}"/pi_config_files/dhcpcd.* /etc
sudo cp "${PIFINDER_REPO_DIR}/pi_config_files/dhcpcd.conf.sta" /etc/dhcpcd.conf
sudo cp "${PIFINDER_REPO_DIR}/pi_config_files/dnsmasq.conf" /etc/dnsmasq.conf
sudo cp "${PIFINDER_REPO_DIR}/pi_config_files/hostapd.conf" /etc/hostapd/hostapd.conf
echo -n "Client" > "${PIFINDER_REPO_DIR}/wifi_status.txt"
sudo systemctl unmask hostapd

# allow the PiFinder service user to adjust network config
pifinder_prepare_wpa_supplicant_config
pifinder_prepare_apsta_nat_config
pifinder_prepare_sta_band_config
sudo python3 "${PIFINDER_REPO_DIR}/scripts/import_initial_wifi_networks.py"

# Bluetooth HID keyboards
if [[ -f /etc/bluetooth/input.conf ]]; then
    sudo sed -i \
        -e 's/^#\?UserspaceHID=.*/UserspaceHID=true/' \
        -e 's/^#\?LEAutoSecurity=.*/LEAutoSecurity=true/' \
        /etc/bluetooth/input.conf
fi
# BlueZ needs the uhid module to expose a paired BT keyboard as an input
# device; without it the keyboard connects but sends no keystrokes.
echo uhid | sudo tee /etc/modules-load.d/uhid.conf >/dev/null
sudo modprobe uhid || true

# Samba config
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/smb.conf" /etc/samba/smb.conf

# Hipparcos catalog
HIP_MAIN_DAT="${PIFINDER_REPO_DIR}/astro_data/hip_main.dat"
if [[ ! -e $HIP_MAIN_DAT ]]; then
    wget -O $HIP_MAIN_DAT https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat
fi

# Enable interfaces
BOOT_CONFIG="$(pifinder_boot_config_path)"
# Drop any previously-written keypad PWM overlay so we only ever keep the one
# that matches this board (Pi 1-4 vs Pi 5 / RP1 -- see pifinder_pwm_overlay).
sudo sed -i \
    -e '/^dtoverlay=pwm,/d' \
    -e '/^dtoverlay=pwm-2chan,/d' \
    "${BOOT_CONFIG}"
for line in \
    "dtparam=spi=on" \
    "$(pifinder_pwm_overlay)" \
    "$(pifinder_uart_overlay)"
do
    grep -qxF "${line}" "${BOOT_CONFIG}" || echo "${line}" | sudo tee -a "${BOOT_CONFIG}"
done

# I2C for the BNO055 IMU (and the BQ25895 charger on Rev-4 boards).
#
# Pi 5 / CM5 drive I2C through the RP1 controller, which honours clock
# stretching, so hardware I2C at 400 kbps is safe there.  Pi 4 and earlier use
# the BCM2835/BCM2711 I2C block, which has a known clock-stretching bug that
# corrupts transfers with a clock-stretching device like the BNO055.  On those
# boards, use a software (bit-banged) i2c-gpio bus on the same SDA/SCL pins
# (GPIO2/GPIO3 -> /dev/i2c-3) instead, and disable the hardware i2c_arm block
# so it does not fight the software bus for the pins.  Keep the two paths
# mutually exclusive by removing the other path's lines first.
if [[ "$(pifinder_board_profile)" == "pi5_class" ]]; then
    sudo sed -i \
        -e '/^dtoverlay=i2c-gpio/d' \
        "${BOOT_CONFIG}"
    for line in \
        "dtparam=i2c_arm=on" \
        "dtparam=i2c_arm_baudrate=400000"
    do
        grep -qxF "${line}" "${BOOT_CONFIG}" || echo "${line}" | sudo tee -a "${BOOT_CONFIG}"
    done
else
    sudo sed -i \
        -e '/^dtparam=i2c_arm=on/d' \
        -e '/^dtparam=i2c_arm_baudrate=/d' \
        "${BOOT_CONFIG}"
    I2C_GPIO_OVERLAY="dtoverlay=i2c-gpio,i2c_gpio_sda=2,i2c_gpio_scl=3,bus=3"
    grep -qxF "${I2C_GPIO_OVERLAY}" "${BOOT_CONFIG}" \
        || echo "${I2C_GPIO_OVERLAY}" | sudo tee -a "${BOOT_CONFIG}"
fi
if [[ "$(pifinder_uart_overlay)" == "dtoverlay=uart2-pi5" ]]; then
    sudo sed -i 's/^dtoverlay=uart3/#dtoverlay=uart3/' "${BOOT_CONFIG}"
fi

# GPIO library for the keypad matrix (PiFinder/keyboard_pi.py imports RPi.GPIO).
# The classic C-extension RPi.GPIO (python3-rpi.gpio) talks to the SoC directly
# and does not work on the Pi 5 / CM5, whose GPIOs hang off the RP1 controller.
# python3-rpi-lgpio provides the same RPi.GPIO API on top of lgpio and does work
# there, so install it on Pi 5-class boards (apt replaces python3-rpi.gpio).
if [[ "$(pifinder_board_profile)" == "pi5_class" ]]; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-rpi-lgpio \
        || echo "WARNING: could not install python3-rpi-lgpio; keypad GPIO may not work on Pi 5." >&2
fi
# Note: camera types are added lateron by python/PiFinder/switch_camera.py

# Keep POSIX shared memory alive across SSH logouts: logind's default
# RemoveIPC=yes deletes all IPC owned by the pifinder user (including the
# solver's cedar-detect /dev/shm segment) the moment that user's last login
# session ends — the PiFinder services run as pifinder but hold no login
# session of their own, so a plain SSH logout used to degrade solving.
# The solver also survives this in software (PFCedarDetectClient._del_shmem),
# but this keeps the fast shared-memory handoff in place.
sudo mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nRemoveIPC=no\n' | sudo tee /etc/systemd/logind.conf.d/pifinder-removeipc.conf

# Disable unwanted services
sudo systemctl disable ModemManager 2>/dev/null || true
sudo systemctl disable dhcpcd dnsmasq hostapd 2>/dev/null || true
# CUPS printing stack ships enabled on desktop Raspberry Pi OS but is unused by
# PiFinder; its background daemons compete for CPU and SD-card I/O on the Pi.
sudo systemctl disable cups cups.socket cups-browsed 2>/dev/null || true

# Enable service
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/pifinder.service" /lib/systemd/system/pifinder.service
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/pifinder_splash.service" /lib/systemd/system/pifinder_splash.service
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/cedar_detect.service" /lib/systemd/system/cedar_detect.service
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/pifinder_apsta_prepare.service" /lib/systemd/system/pifinder_apsta_prepare.service
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/pifinder_apsta_monitor.service" /lib/systemd/system/pifinder_apsta_monitor.service
sudo systemctl daemon-reload
sudo systemctl enable cedar_detect
sudo systemctl enable pifinder
sudo systemctl enable pifinder_splash

for group in input video render dialout gpio i2c spi; do
    if getent group "${group}" >/dev/null; then
        sudo usermod -aG "${group}" "${PIFINDER_USER}"
    fi
done

install_optional_indi_archive

echo "PiFinder setup complete, please restart the Pi"
