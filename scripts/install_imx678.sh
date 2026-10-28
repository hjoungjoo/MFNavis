#!/usr/bin/env bash
# Prepare IMX678; --activate-converter also selects the CM5 CSI0 board.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
SOURCE_DIR="${REPO_DIR}/deployment/imx678"
ACTION="${1:---check}"
KERNEL="$(uname -r)"
VERSION=0.2.0
PACKAGE=mfnavis-imx678

fail() { echo "IMX678: $*" >&2; exit 1; }
[[ $# -le 2 ]] || fail "Usage: $0 --check | --build-only [directory] | --install | --activate-converter"
case "${ACTION}" in --check|--build-only|--install|--activate-converter) ;; *) fail "Unknown action: ${ACTION}" ;; esac
[[ $# -le 1 || "${ACTION}" == --build-only ]] || fail "Only --build-only accepts a directory"
if [[ "${ACTION}" == --activate-converter ]]; then
    grep -aq 'raspberrypi,5-compute-module' /proc/device-tree/compatible \
        || fail "The converter profile requires CM5 with GPIO34/35 and CSI0"
fi

verify_source() {
    python3 - "${SOURCE_DIR}" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
lock = json.loads((root / 'upstream.json').read_text())
if hashlib.sha256((root / 'imx678.c').read_bytes()).hexdigest() != lock['sha256']:
    raise SystemExit('Upstream IMX678 source SHA-256 mismatch')
print('Upstream Linux commit:', lock['commit'])
PY
}

check_userspace() {
    local library
    PIPELINE=vc4
    if grep -aq 'brcm,bcm2712' /proc/device-tree/compatible; then
        PIPELINE=pisp
    fi
    library="/usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)/libcamera/ipa/ipa_rpi_${PIPELINE}.so"
    [[ -f "${library}" ]] || fail "Raspberry Pi libcamera IPA not found: ${library}"
    # Write strings to a file: avoid pipefail/SIGPIPE with an early grep exit.
    strings "${library}" > "${WORK_DIR}/ipa-strings"
    grep -Eq 'CamHelper(Imx678|Starvis2)' "${WORK_DIR}/ipa-strings" \
        || fail "Install Raspberry Pi libcamera >= 0.7.2 with IMX678 support first"
    grep -qx 'imx678' "${WORK_DIR}/ipa-strings" || fail "IMX678 helper registration is missing"
    [[ -f "/usr/share/libcamera/ipa/rpi/${PIPELINE}/uncalibrated.json" ]] \
        || fail "Official uncalibrated ${PIPELINE} tuning is missing"
}

imx678_kernel_targets() {
    local modules_root="${1:-/lib/modules}" directory
    local flavour="${KERNEL##*-rpi-}"
    [[ "${KERNEL}" == *-rpi-* ]] || { printf '%s\n' "${KERNEL}"; return; }
    for directory in "${modules_root}/"*-rpi-"${flavour}"; do
        [[ -d "${directory}" ]] || continue
        [[ -d "${directory}/build" ]] || {
            echo "Missing headers for ${directory##*/}; install matching headers before reboot." >&2
            return 1
        }
        printf '%s\n' "${directory##*/}"
    done
}

verify_source
WORK_DIR="$(mktemp -d -t mfnavis-imx678.XXXXXXXX)"
trap 'rm -rf "${WORK_DIR}"' EXIT

if [[ "${ACTION}" == --install || "${ACTION}" == --activate-converter ]]; then
    [[ ${EUID} -eq 0 ]] || fail "Run --install with sudo"
    MFNAVIS_USER="${MFNAVIS_USER:-${SUDO_USER:-}}"
    [[ "${MFNAVIS_USER}" =~ ^[a-z_][a-z0-9_-]*\$?$ && "${MFNAVIS_USER}" != root ]] \
        || fail "Set MFNAVIS_USER to the non-root service account"
    HEADER_PACKAGES=("linux-headers-${KERNEL}")
    case "${KERNEL}" in
        *-rpi-2712) HEADER_PACKAGES+=(linux-headers-rpi-2712) ;;
        *-rpi-v8) HEADER_PACKAGES+=(linux-headers-rpi-v8) ;;
    esac
    # The header metapackage keeps DKMS working after subsequent OS upgrades.
    # Install dependencies BEFORE checking libcamera on a fresh OS image.
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        dkms device-tree-compiler build-essential patch binutils dpkg-dev \
        libcamera-ipa python3-picamera2 rpicam-apps "${HEADER_PACKAGES[@]}"
    imx678_kernel_targets /lib/modules > "${WORK_DIR}/kernels"
fi
check_userspace

if [[ "${ACTION}" == --check ]]; then
    modinfo imx678 >/dev/null 2>&1 || fail "Kernel module not installed; run --install"
    [[ "$(modinfo -F mfnavis_converter imx678)" == 1 ]] || fail "Converter sequencing module missing; run --install"
    [[ "$(modinfo -F version imx678)" == "${VERSION}" ]] || fail "IMX678 module is outdated; run --install"
    [[ -f /boot/firmware/overlays/imx678-mfnavis.dtbo ]] || fail "Overlay not installed"
    [[ -f /boot/firmware/overlays/imx678-mfnavis-cm5-converter.dtbo ]] || fail "Converter overlay not installed"
    [[ -f "/usr/share/libcamera/ipa/rpi/${PIPELINE}/imx678.json" ]] || fail "Tuning not installed"
    echo "IMX678 software is prepared for ${KERNEL}. Sensor capture is not tested by this check."
    exit 0
fi

[[ -d "/lib/modules/${KERNEL}/build" ]] || fail "Matching kernel headers are required"
BUILD_DIR="${WORK_DIR}/build"
mkdir "${BUILD_DIR}"
cp "${SOURCE_DIR}/imx678.c" "${SOURCE_DIR}/Makefile" "${BUILD_DIR}/"
patch --batch --fuzz=0 -d "${BUILD_DIR}" -p1 < "${SOURCE_DIR}/0001-cm5-converter-power-sequence.patch"
make -C "/lib/modules/${KERNEL}/build" M="${BUILD_DIR}" modules -j2
dtc -@ -I dts -O dtb -o "${BUILD_DIR}/imx678-mfnavis.dtbo" \
    "${SOURCE_DIR}/imx678-mfnavis-overlay.dts"
dtc -@ -I dts -O dtb -o "${BUILD_DIR}/imx678-mfnavis-cm5-converter.dtbo" \
    "${SOURCE_DIR}/imx678-mfnavis-cm5-converter-overlay.dts"

if [[ "${ACTION}" == --build-only ]]; then
    OUTPUT_DIR="${2:-${REPO_DIR}/.imx678-build}"
    mkdir -p "${OUTPUT_DIR}"
    cp "${BUILD_DIR}/imx678.ko" "${BUILD_DIR}/"*.dtbo "${OUTPUT_DIR}/"
    echo "Build passed for ${KERNEL}; artifacts: ${OUTPUT_DIR}. Nothing installed."
    exit 0
fi

# Never replace an unrelated vendor's module. The converter requires our patch.
EXISTING="$(modinfo -n imx678 2>/dev/null || true)"
if [[ -n "${EXISTING}" ]] && ! dkms status -m "${PACKAGE}" | grep -q "${PACKAGE}"; then
    modinfo -F author imx678 > "${WORK_DIR}/authors"
    grep -q 'Jai Luthra' "${WORK_DIR}/authors" || fail "An unrelated IMX678 driver is already installed"
fi
DESTINATION="/usr/src/${PACKAGE}-${VERSION}"
if [[ ! -d "${DESTINATION}" ]]; then
    install -d -m 0755 "${DESTINATION}"
    install -m 0644 "${BUILD_DIR}/imx678.c" "${SOURCE_DIR}/Makefile" \
        "${SOURCE_DIR}/dkms.conf" "${SOURCE_DIR}/COPYING" "${SOURCE_DIR}/upstream.json" \
        "${SOURCE_DIR}/0001-cm5-converter-power-sequence.patch" "${DESTINATION}/"
else
    cmp -s "${BUILD_DIR}/imx678.c" "${DESTINATION}/imx678.c" \
        || fail "Installed converter source differs; bump DKMS version first"
    for file in Makefile dkms.conf; do
        cmp -s "${SOURCE_DIR}/${file}" "${DESTINATION}/${file}" \
            || fail "Installed ${DESTINATION}/${file} differs; resolve the existing DKMS version first"
    done
fi
dkms status -m "${PACKAGE}" -v "${VERSION}" | grep -q "${PACKAGE}" \
    || dkms add -m "${PACKAGE}" -v "${VERSION}"
while IFS= read -r target_kernel; do
    # Also prepare an already-installed newer kernel before its first reboot.
    dkms install -m "${PACKAGE}" -v "${VERSION}" -k "${target_kernel}"
    depmod -a "${target_kernel}"
done < "${WORK_DIR}/kernels"

install -m 0644 "${BUILD_DIR}/"*.dtbo /boot/firmware/overlays/
# Use the official generic tuning unchanged until sensor-specific calibration
# is available. Never overwrite an operator's calibrated IMX678 tuning.
for pipeline in pisp vc4; do
    TUNING_DIR="/usr/share/libcamera/ipa/rpi/${pipeline}"
    [[ -f "${TUNING_DIR}/uncalibrated.json" ]] || continue
    if [[ ! -e "${TUNING_DIR}/imx678.json" ]]; then
        install -m 0644 "${TUNING_DIR}/uncalibrated.json" "${TUNING_DIR}/imx678.json"
    fi
done

# Make the new menu action available on an existing installation as well.
install -d -m 0755 /usr/local/lib/mfnavis
install -m 0644 "${REPO_DIR}/python/MFNavis/switch_camera.py" \
    "${REPO_DIR}/python/MFNavis/boot_config.py" /usr/local/lib/mfnavis/
printf '%s ALL=(root) NOPASSWD: /usr/bin/python3 /usr/local/lib/mfnavis/switch_camera.py imx678\n' \
    "${MFNAVIS_USER}" > "${WORK_DIR}/sudoers"
visudo -cf "${WORK_DIR}/sudoers"
install -m 0440 "${WORK_DIR}/sudoers" /etc/sudoers.d/91-mfnavis-imx678
if [[ "${ACTION}" == --activate-converter ]]; then
    python3 - <<'PY'
import datetime
import pathlib
import shutil
import sys
sys.path.insert(0, '/usr/local/lib/mfnavis')
from boot_config import get_boot_config_path
from switch_camera import switch_boot
boot = pathlib.Path(get_boot_config_path())
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
backup = boot.with_name(f'config.txt.before-imx678-{stamp}')
shutil.copy2(boot, backup)
switch_boot('imx678', converter=True)
print(f'Boot config backup: {backup}')
PY
    echo 'CM5 CSI0 converter selected. Reboot to load the new driver and wiring.'
    exit 0
fi
echo 'IMX678 prepared. Current camera and boot config are unchanged.'
echo 'After connecting the sensor, select Settings > Advanced > Camera Type > IMX678 (Auto).'
