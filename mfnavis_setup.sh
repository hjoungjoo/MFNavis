#!/usr/bin/bash
# Install or update MFNavis on a prepared Raspberry Pi OS.
#
# Install with:
#   wget -O - https://raw.githubusercontent.com/hjoungjoo/MFNavis/main/mfnavis_setup.sh | bash

set -e

if [[ "$(id -u)" -eq 0 ]]; then
    echo "Do not run this script with sudo." >&2
    echo "Run it as the target OS user; the script will use sudo when needed." >&2
    exit 1
fi

MFNAVIS_USER="${MFNAVIS_USER:-${SUDO_USER:-$(id -un)}}"
if [[ "${MFNAVIS_USER}" == "root" ]]; then
    echo "Run as the target OS user, or set MFNAVIS_USER=<user>." >&2
    exit 1
fi

MFNAVIS_HOME="$(getent passwd "${MFNAVIS_USER}" | cut -d: -f6)"
if [[ -z "${MFNAVIS_HOME}" || ! -d "${MFNAVIS_HOME}" ]]; then
    echo "Could not determine home directory for ${MFNAVIS_USER}" >&2
    exit 1
fi

cd "${MFNAVIS_HOME}"

sudo bash -c '
set -e
if [ ! -e /usr/sbin/policy-rc.d ] && [ ! -L /usr/sbin/policy-rc.d ]; then
    printf "%s\n" "#!/bin/sh" "exit 101" > /usr/sbin/policy-rc.d
    trap "rm -f /usr/sbin/policy-rc.d" EXIT
    chmod 755 /usr/sbin/policy-rc.d
fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git sudo python3-pip python3-venv python3-dev build-essential pkg-config \
    samba samba-common-bin dnsmasq hostapd dhcpcd gpsd wget iw nftables \
    libinput10 libcap2-bin libjpeg-dev zlib1g-dev libfreetype6-dev \
    liblcms2-dev libopenjp2-7-dev libtiff-dev libffi-dev libssl-dev \
    python3-picamera2 rpicam-apps i2c-tools spi-tools
'

mfnavis_update_checkout() {
    local requested="${MFNAVIS_INSTALL_BRANCH:-}"
    local branch target local_tip

    if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
        echo "Tracked files have local changes; refusing setup update." >&2
        return 1
    fi

    if [[ -z "${requested}" ]]; then
        requested="$(git symbolic-ref --quiet --short HEAD)" || {
            echo "Detached checkout: set MFNAVIS_INSTALL_BRANCH to main, release, or a release tag." >&2
            return 1
        }
    fi
    if ! git check-ref-format "refs/heads/${requested}" >/dev/null; then
        echo "Invalid MFNAVIS_INSTALL_BRANCH: ${requested}" >&2
        return 1
    fi

    if git ls-remote --exit-code --heads origin "refs/heads/${requested}" >/dev/null; then
        branch="${requested}"
        git fetch --no-tags origin "refs/heads/${branch}:refs/remotes/origin/${branch}"
    elif git ls-remote --exit-code --tags --refs origin "refs/tags/${requested}" >/dev/null; then
        branch=""
        git fetch --no-tags origin "refs/tags/${requested}"
    else
        echo "Branch or release tag not found on origin: ${requested}" >&2
        return 1
    fi

    target="$(git rev-parse 'FETCH_HEAD^{commit}')"
    git cat-file -e "${target}:deployment/cedar_free.json"
    if ! git merge-base --is-ancestor HEAD "${target}"; then
        echo "The selected version is not a fast-forward from this installation; refusing to replace local history." >&2
        return 1
    fi

    if [[ -z "${branch}" ]]; then
        git switch --detach "${target}"
    elif [[ "$(git symbolic-ref --quiet --short HEAD || true)" == "${branch}" ]]; then
        git merge --ff-only "${target}"
    elif git show-ref --verify --quiet "refs/heads/${branch}"; then
        local_tip="$(git rev-parse "refs/heads/${branch}")"
        if ! git merge-base --is-ancestor "${local_tip}" "${target}"; then
            echo "Local ${branch} has commits outside the selected version; refusing to replace it." >&2
            return 1
        fi
        git switch "${branch}"
        git merge --ff-only "${target}"
    else
        git switch -c "${branch}" --track "origin/${branch}"
    fi
}

if [[ -d MFNavis/ ]]; then
    cd MFNavis/
    mfnavis_update_checkout
else
    git clone --recursive --branch "${MFNAVIS_INSTALL_BRANCH:-main}" https://github.com/hjoungjoo/MFNavis.git MFNavis
fi

MFNAVIS_REPO_DIR="${MFNAVIS_HOME}/MFNavis"
cd "${MFNAVIS_REPO_DIR}"
source "${MFNAVIS_REPO_DIR}/mfnavis_paths.sh"

python3 "${MFNAVIS_REPO_DIR}/scripts/check_cedar_free.py" --repo "${MFNAVIS_REPO_DIR}"

source "${MFNAVIS_REPO_DIR}/scripts/mfnavis_setup_runtime.sh"
mfnavis_select_setup_python
mfnavis_prepare_indi_archive

bash "${MFNAVIS_REPO_DIR}/scripts/ensure_tetra3_link.sh" "${MFNAVIS_REPO_DIR}"
bash "${MFNAVIS_REPO_DIR}/scripts/setup_mfds.sh"
mfnavis_install_setup_python
mfnavis_install_setup_indi

# Setup GPSD
sudo cp "${MFNAVIS_REPO_DIR}/pi_config_files/gpsd.conf" /etc/default/gpsd
sudo sed -i "s|^DEVICES=.*|DEVICES=\"$(mfnavis_gps_device)\"|" /etc/default/gpsd
bash "${MFNAVIS_REPO_DIR}/scripts/install_gpsd_stable.sh"

# data dirs
sudo install -d -o "${MFNAVIS_USER}" -g "${MFNAVIS_GROUP}" -m 755 \
    "${MFNAVIS_DATA_DIR}" \
    "${MFNAVIS_DATA_DIR}/captures" \
    "${MFNAVIS_DATA_DIR}/obslists" \
    "${MFNAVIS_DATA_DIR}/screenshots" \
    "${MFNAVIS_DATA_DIR}/solver_debug_dumps" \
    "${MFNAVIS_DATA_DIR}/logs" \
    "${MFNAVIS_DATA_DIR}/migrations"

# Wi-Fi config: retain the current mode and live network files on reinstall.
for template in "${MFNAVIS_REPO_DIR}"/pi_config_files/dhcpcd.*; do
    target="/etc/${template##*/}"
    if [[ ! -f "${target}" ]]; then
        sudo cp "${template}" "${target}"
    fi
done
if [[ ! -f "${MFNAVIS_REPO_DIR}/wifi_status.txt" ]]; then
    sudo cp "${MFNAVIS_REPO_DIR}/pi_config_files/dhcpcd.conf.sta" /etc/dhcpcd.conf
    sudo cp "${MFNAVIS_REPO_DIR}/pi_config_files/dnsmasq.conf" /etc/dnsmasq.conf
    printf '%s' 'Client' > "${MFNAVIS_REPO_DIR}/wifi_status.txt"
fi
# Preserve an existing AP password and custom SSID on reinstall.
if [[ ! -f /etc/hostapd/hostapd.conf ]]; then
    sudo install -d -m 755 /etc/hostapd
    sudo cp "${MFNAVIS_REPO_DIR}/pi_config_files/hostapd.conf" /etc/hostapd/hostapd.conf
fi
sudo systemctl unmask hostapd

# Allow the MFNavis service user to adjust network config.
mfnavis_prepare_wpa_supplicant_config
mfnavis_prepare_apsta_nat_config
mfnavis_prepare_sta_band_config
sudo python3 "${MFNAVIS_REPO_DIR}/scripts/import_initial_wifi_networks.py"

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
bash "${MFNAVIS_REPO_DIR}/scripts/install_keyboard_power_ignore.sh"

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
    su ${MFNAVIS_USER} ${MFNAVIS_GROUP}
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
sudo tee /etc/systemd/journald.conf.d/mfnavis-ram-cap.conf >/dev/null <<'JOURNALD_EOF'
[Journal]
RuntimeMaxUse=32M
JOURNALD_EOF

# Samba config
mfnavis_render_config "${MFNAVIS_REPO_DIR}/pi_config_files/smb.conf" /etc/samba/smb.conf

# Hipparcos catalog
HIP_MAIN_DAT="${MFNAVIS_REPO_DIR}/astro_data/hip_main.dat"
if [[ ! -e $HIP_MAIN_DAT ]]; then
    wget -O $HIP_MAIN_DAT https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat
fi

# Enable interfaces
BOOT_CONFIG="$(mfnavis_boot_config_path)"
# Drop any previously-written keypad PWM overlay so we only ever keep the one
# that matches this board (Pi 1-4 vs Pi 5 / RP1 -- see mfnavis_pwm_overlay).
sudo sed -i \
    -e '/^dtoverlay=pwm,/d' \
    -e '/^dtoverlay=pwm-2chan,/d' \
    "${BOOT_CONFIG}"
for line in \
    "dtparam=spi=on" \
    "$(mfnavis_pwm_overlay)" \
    "$(mfnavis_uart_overlay)"
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
if [[ "$(mfnavis_board_profile)" == "pi5_class" ]]; then
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
if [[ "$(mfnavis_uart_overlay)" == "dtoverlay=uart2-pi5" ]]; then
    sudo sed -i 's/^dtoverlay=uart3/#dtoverlay=uart3/' "${BOOT_CONFIG}"
fi

# GPIO library for the keypad matrix (MFNavis/keyboard_pi.py imports RPi.GPIO).
# The classic C-extension RPi.GPIO (python3-rpi.gpio) talks to the SoC directly
# and does not work on the Pi 5 / CM5, whose GPIOs hang off the RP1 controller.
# python3-rpi-lgpio provides the same RPi.GPIO API on top of lgpio and does work
# there, so install it on Pi 5-class boards (apt replaces python3-rpi.gpio).
if [[ "$(mfnavis_board_profile)" == "pi5_class" ]]; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-rpi-lgpio \
        || echo "WARNING: could not install python3-rpi-lgpio; keypad GPIO may not work on Pi 5." >&2
fi
# Joystick/gamepad button input (MFNavis/joystick_input.py reads evdev
# directly; libinput does not deliver joystick events).
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-evdev \
    || echo "WARNING: could not install python3-evdev; joystick input will be disabled." >&2
# Use the product IMX462 sensor on a fresh boot config; keep an existing camera
# overlay when this script is rerun on a device with a deliberate selection.
sudo env PYTHONPATH="${MFNAVIS_REPO_DIR}/python" python3 \
    -m MFNavis.switch_camera --default imx462

# Keep POSIX shared memory alive across SSH logouts: logind's default
# RemoveIPC=yes deletes all IPC owned by the MFNavis user (including the
# solver's /dev/shm segment) the moment that user's last login
# session ends — the MFNavis services hold no login
# session of their own, so a plain SSH logout used to degrade solving.
# The solver also survives this in software (PFCedarDetectClient._del_shmem),
# but this keeps the fast shared-memory handoff in place.
sudo mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nRemoveIPC=no\n' | sudo tee /etc/systemd/logind.conf.d/mfnavis-removeipc.conf

# Disable unwanted services
sudo systemctl disable ModemManager 2>/dev/null || true
sudo systemctl disable dhcpcd dnsmasq hostapd 2>/dev/null || true
# CUPS printing stack ships enabled on desktop Raspberry Pi OS but is unused by
# MFNavis; its background daemons compete for CPU and SD-card I/O on the Pi.
sudo systemctl disable cups cups.socket cups-browsed 2>/dev/null || true
# Boot to console (with autologin) instead of the desktop: MFNavis runs
# headless, and the Wayland taskbar (wf-panel-pi) busy-loops near 100% CPU
# when no monitor is attached. B2 = console autologin (takes effect on reboot).
if command -v raspi-config >/dev/null 2>&1; then
    sudo raspi-config nonint do_boot_behaviour B2
else
    sudo systemctl set-default multi-user.target
fi

# Enable service
mfnavis_render_config "${MFNAVIS_REPO_DIR}/pi_config_files/mfnavis.service" /lib/systemd/system/mfnavis.service
mfnavis_render_config "${MFNAVIS_REPO_DIR}/pi_config_files/mfnavis_splash.service" /lib/systemd/system/mfnavis_splash.service
mfnavis_render_config "${MFNAVIS_REPO_DIR}/pi_config_files/mfnavis_apsta_prepare.service" /lib/systemd/system/mfnavis_apsta_prepare.service
mfnavis_render_config "${MFNAVIS_REPO_DIR}/pi_config_files/mfnavis_apsta_monitor.service" /lib/systemd/system/mfnavis_apsta_monitor.service
mfnavis_configure_python_services
bash "${MFNAVIS_REPO_DIR}/scripts/install_service_control.sh" "${MFNAVIS_USER}"
bash "${MFNAVIS_REPO_DIR}/scripts/install_runtime_control.sh" "${MFNAVIS_USER}"
sudo systemctl daemon-reload
sudo systemctl enable mfnavis
sudo systemctl enable mfnavis_splash

for group in input video render dialout gpio i2c spi netdev bluetooth; do
    if getent group "${group}" >/dev/null; then
        sudo usermod -aG "${group}" "${MFNAVIS_USER}"
    fi
done

echo "MFNavis setup complete, please restart the Pi"
