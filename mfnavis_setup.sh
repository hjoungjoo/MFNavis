#!/usr/bin/bash
# This script installs MFNavis on a prepared Raspberry Pi OS.
# It clones this fork (hjoungjoo/MFNavis, main branch) instead of the
# upstream release, and adds the fork's SD-wear, evdev and console-boot steps.
# The old upstream installer is archived in docs/history/pifinder_setup_legacy.txt.
# See https://pifinder.readthedocs.io/en/release/software.html for more info.
#
# Install with:
#   wget -O - https://raw.githubusercontent.com/hjoungjoo/MFNavis/main/mfnavis_setup.sh | bash

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

if [[ -d MFNavis/ || -d PiFinder/ ]]; then
    if [[ -d MFNavis/ ]]; then cd MFNavis/; else cd PiFinder/; fi
    branch="$(git symbolic-ref --quiet --short HEAD)" || {
        echo "Detached checkout: select the reviewed deployment branch first." >&2
        exit 1
    }
    if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
        echo "Tracked files have local changes; refusing setup update." >&2
        exit 1
    fi
    # Keep existing installations on the new product repository.
    case "$(git remote get-url origin)" in
        https://github.com/hjoungjoo/MF_PiFinder|https://github.com/hjoungjoo/MF_PiFinder.git|git@github.com:hjoungjoo/MF_PiFinder.git)
            git remote set-url origin https://github.com/hjoungjoo/MFNavis.git
            ;;
    esac
    git fetch --no-tags origin "refs/heads/${branch}"
    git cat-file -e FETCH_HEAD:deployment/cedar_free.json
    git merge --ff-only FETCH_HEAD
else
    git clone --recursive --branch "${PIFINDER_INSTALL_BRANCH:-main}" https://github.com/hjoungjoo/MFNavis.git MFNavis
fi

PIFINDER_REPO_DIR="$(pwd -P)"
if [[ ! -f "${PIFINDER_REPO_DIR}/mfnavis_paths.sh" ]]; then
    PIFINDER_REPO_DIR="${PIFINDER_HOME}/MFNavis"
fi
# Migrate an existing standard installation before rendering new unit paths.
sudo python3 "${PIFINDER_REPO_DIR}/scripts/migrate_product_paths.py" --home "${PIFINDER_HOME}" --apply
PIFINDER_REPO_DIR="${PIFINDER_HOME}/MFNavis"
cd "${PIFINDER_REPO_DIR}"
source "${PIFINDER_REPO_DIR}/mfnavis_paths.sh"

cd "${PIFINDER_REPO_DIR}"
python3 "${PIFINDER_REPO_DIR}/scripts/check_cedar_free.py" --repo "${PIFINDER_REPO_DIR}"

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

bash "${PIFINDER_REPO_DIR}/scripts/ensure_tetra3_link.sh" "${PIFINDER_REPO_DIR}"
bash "${PIFINDER_REPO_DIR}/scripts/setup_mfds.sh"
sudo python3 -m pip install --break-system-packages -r python/requirements.txt

# Setup GPSD
sudo cp "${PIFINDER_REPO_DIR}/pi_config_files/gpsd.conf" /etc/default/gpsd
sudo sed -i "s|^DEVICES=.*|DEVICES=\"$(pifinder_gps_device)\"|" /etc/default/gpsd
bash "${PIFINDER_REPO_DIR}/scripts/install_gpsd_stable.sh"

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
# Preserve an existing AP password and custom SSID on reinstall.
if [[ ! -f /etc/hostapd/hostapd.conf ]]; then
    sudo install -d -m 755 /etc/hostapd
    sudo cp "${PIFINDER_REPO_DIR}/pi_config_files/hostapd.conf" /etc/hostapd/hostapd.conf
fi
echo -n "Client" > "${PIFINDER_REPO_DIR}/wifi_status.txt"
sudo systemctl unmask hostapd

# allow the PiFinder service user to adjust network config
pifinder_prepare_wpa_supplicant_config
pifinder_prepare_apsta_nat_config
pifinder_prepare_sta_band_config
sudo python3 "${PIFINDER_REPO_DIR}/scripts/import_initial_wifi_networks.py"

# mDNS reliability (reaching <hostname>.local from phones)
# 1) brcmfmac WiFi power save drops multicast frames while the radio dozes, so
#    mDNS queries go unanswered intermittently.  PCs mask this with caching and
#    retries, but Android's .local resolver times out fast and caches little,
#    which shows up as the hostname resolving one moment and failing the next.
sudo mkdir -p /etc/NetworkManager/conf.d
sudo tee /etc/NetworkManager/conf.d/wifi-powersave.conf >/dev/null <<'POWERSAVE_EOF'
[connection]
# 2 = disable WiFi power saving on NetworkManager-managed WiFi devices
wifi.powersave = 2
POWERSAVE_EOF
# 2) The Pi carries only a link-local IPv6 address (fe80::) on wlan0, but avahi
#    still advertises it as an AAAA record.  Android prefers IPv6 and a fe80::
#    address without a zone index can never connect, so clients that pick the
#    AAAA answer fail while A-record picks work.  IPv4-only mDNS avoids this.
if [[ -f /etc/avahi/avahi-daemon.conf ]]; then
    sudo sed -i 's/^use-ipv6=yes/use-ipv6=no/' /etc/avahi/avahi-daemon.conf
    grep -q '^publish-aaaa-on-ipv4=' /etc/avahi/avahi-daemon.conf \
        || sudo sed -i '/^\[publish\]/a publish-aaaa-on-ipv4=no' /etc/avahi/avahi-daemon.conf
fi

# Disable the supported wireless keyboard's power key, including on hotplug.
bash "${PIFINDER_REPO_DIR}/scripts/install_keyboard_power_ignore.sh"

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

# SD-card wear reduction: keep steady log writers off the card.
# 1) /tmp on tmpfs -- indiserver's stdout log (redirected there by indi-web)
#    and INDI FIFOs/sockets then live in RAM.
if ! grep -qE '^\s*tmpfs\s+/tmp\s+tmpfs' /etc/fstab; then
    echo "tmpfs /tmp tmpfs defaults,noatime,nosuid,nodev,mode=1777,size=256M 0 0" \
        | sudo tee -a /etc/fstab >/dev/null
fi
# 2) Cap the indiserver log on that tmpfs (no rotation of its own).
#    'su' is required because /tmp is world-writable (1777).
sudo tee /etc/logrotate.d/indiserver >/dev/null <<LOGROTATE_EOF
/tmp/indiserver.log {
    su ${PIFINDER_USER} ${PIFINDER_USER}
    size 10M
    rotate 2
    copytruncate
    missingok
    notifempty
    compress
}
LOGROTATE_EOF
# 3) journald is volatile (RAM); cap it below the default 15%-of-/run.
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/pifinder-ram-cap.conf >/dev/null <<'JOURNALD_EOF'
[Journal]
RuntimeMaxUse=32M
JOURNALD_EOF

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
# Joystick/gamepad button input (PiFinder/joystick_input.py reads evdev
# directly; libinput does not deliver joystick events).
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-evdev \
    || echo "WARNING: could not install python3-evdev; joystick input will be disabled." >&2
# Note: camera types are added lateron by python/MFNavis/switch_camera.py

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
# Boot to console (with autologin) instead of the desktop: PiFinder runs
# headless, and the Wayland taskbar (wf-panel-pi) busy-loops near 100% CPU
# when no monitor is attached. B2 = console autologin (takes effect on reboot).
if command -v raspi-config >/dev/null 2>&1; then
    sudo raspi-config nonint do_boot_behaviour B2
else
    sudo systemctl set-default multi-user.target
fi

# Enable service
# Migrate legacy units before installing canonical templates to avoid duplicate services.
sudo python3 "${PIFINDER_REPO_DIR}/scripts/apply_product_branding.py" --apply
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/mfnavis.service" /lib/systemd/system/mfnavis.service
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/mfnavis_splash.service" /lib/systemd/system/mfnavis_splash.service
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/mfnavis_apsta_prepare.service" /lib/systemd/system/mfnavis_apsta_prepare.service
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/mfnavis_apsta_monitor.service" /lib/systemd/system/mfnavis_apsta_monitor.service
sudo systemctl daemon-reload
sudo systemctl enable mfnavis
sudo systemctl enable mfnavis_splash

for group in input video render dialout gpio i2c spi; do
    if getent group "${group}" >/dev/null; then
        sudo usermod -aG "${group}" "${PIFINDER_USER}"
    fi
done

install_optional_indi_archive

echo "MFNavis setup complete, please restart the Pi"
