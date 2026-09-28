#!/usr/bin/env bash
# Prepare the upstream IMX678 driver without selecting a camera or rebooting.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
SOURCE_DIR="${REPO_DIR}/deployment/imx678"
ACTION="${1:---check}"
KERNEL="$(uname -r)"
VERSION=0.1.0
PACKAGE=mfnavis-imx678

fail() { echo "IMX678: $*" >&2; exit 1; }
[[ $# -le 2 ]] || fail "Usage: $0 --check | --build-only [directory] | --install"
case "${ACTION}" in --check|--build-only|--install) ;; *) fail "Unknown action: ${ACTION}" ;; esac

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
    library="/usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)/libcamera/ipa/ipa_rpi_pisp.so"
    [[ -f "${library}" ]] || fail "Raspberry Pi libcamera IPA not found: ${library}"
    # Write strings to a file: avoid pipefail/SIGPIPE with an early grep exit.
    strings "${library}" > "${WORK_DIR}/ipa-strings"
    grep -q 'CamHelperImx678' "${WORK_DIR}/ipa-strings" \
        || fail "Install Raspberry Pi libcamera >= 0.7.2 with IMX678 support first"
    [[ -f /usr/share/libcamera/ipa/rpi/pisp/uncalibrated.json ]] \
        || fail "Official uncalibrated PiSP tuning is missing"
}

verify_source
WORK_DIR="$(mktemp -d -t mfnavis-imx678.XXXXXXXX)"
trap 'rm -rf "${WORK_DIR}"' EXIT
check_userspace

if [[ "${ACTION}" == --check ]]; then
    modinfo imx678 >/dev/null 2>&1 || fail "Kernel module not installed; run --install"
    [[ -f /boot/firmware/overlays/imx678-mfnavis.dtbo ]] || fail "Overlay not installed"
    [[ -f /usr/share/libcamera/ipa/rpi/pisp/imx678.json ]] || fail "Tuning not installed"
    echo "IMX678 software is prepared for ${KERNEL}. Sensor capture is not tested by this check."
    exit 0
fi

if [[ "${ACTION}" == --install ]]; then
    [[ ${EUID} -eq 0 ]] || fail "Run --install with sudo"
    MFNAVIS_USER="${MFNAVIS_USER:-${SUDO_USER:-}}"
    [[ "${MFNAVIS_USER}" =~ ^[a-z_][a-z0-9_-]*\$?$ && "${MFNAVIS_USER}" != root ]] \
        || fail "Set MFNAVIS_USER to the non-root service account"
    if ! command -v dkms >/dev/null || ! command -v dtc >/dev/null \
        || [[ ! -d "/lib/modules/${KERNEL}/build" ]]; then
        apt-get install -y dkms device-tree-compiler build-essential "linux-headers-${KERNEL}"
    fi
fi

[[ -d "/lib/modules/${KERNEL}/build" ]] || fail "Matching kernel headers are required"
BUILD_DIR="${WORK_DIR}/build"
mkdir "${BUILD_DIR}"
cp "${SOURCE_DIR}/imx678.c" "${SOURCE_DIR}/Makefile" "${BUILD_DIR}/"
make -C "/lib/modules/${KERNEL}/build" M="${BUILD_DIR}" modules -j2
dtc -@ -I dts -O dtb -o "${BUILD_DIR}/imx678-mfnavis.dtbo" \
    "${SOURCE_DIR}/imx678-mfnavis-overlay.dts"

if [[ "${ACTION}" == --build-only ]]; then
    OUTPUT_DIR="${2:-${REPO_DIR}/.imx678-build}"
    mkdir -p "${OUTPUT_DIR}"
    cp "${BUILD_DIR}/imx678.ko" "${BUILD_DIR}/imx678-mfnavis.dtbo" "${OUTPUT_DIR}/"
    echo "Build passed for ${KERNEL}; artifacts: ${OUTPUT_DIR}. Nothing installed."
    exit 0
fi

# Never replace an unrelated vendor's module. An in-tree upstream module wins.
EXISTING="$(modinfo -n imx678 2>/dev/null || true)"
if [[ -n "${EXISTING}" ]] && ! dkms status -m "${PACKAGE}" | grep -q "${PACKAGE}"; then
    modinfo -F author imx678 > "${WORK_DIR}/authors"
    grep -q 'Jai Luthra' "${WORK_DIR}/authors" || fail "An unrelated IMX678 driver is already installed"
    echo "Using existing upstream module: ${EXISTING}"
else
    DESTINATION="/usr/src/${PACKAGE}-${VERSION}"
    if [[ ! -d "${DESTINATION}" ]]; then
        install -d -m 0755 "${DESTINATION}"
        install -m 0644 "${SOURCE_DIR}/imx678.c" "${SOURCE_DIR}/Makefile" \
            "${SOURCE_DIR}/dkms.conf" "${SOURCE_DIR}/COPYING" "${SOURCE_DIR}/upstream.json" "${DESTINATION}/"
    else
        for file in imx678.c Makefile dkms.conf; do
            cmp -s "${SOURCE_DIR}/${file}" "${DESTINATION}/${file}" \
                || fail "Installed ${DESTINATION}/${file} differs; resolve the existing DKMS version first"
        done
    fi
    dkms status -m "${PACKAGE}" -v "${VERSION}" | grep -q "${PACKAGE}" \
        || dkms add -m "${PACKAGE}" -v "${VERSION}"
    dkms install -m "${PACKAGE}" -v "${VERSION}" -k "${KERNEL}"
fi

install -m 0644 "${BUILD_DIR}/imx678-mfnavis.dtbo" /boot/firmware/overlays/
# Use the official generic tuning unchanged until sensor-specific calibration
# is available. Never overwrite an operator's calibrated IMX678 tuning.
for pipeline in pisp vc4; do
    TUNING_DIR="/usr/share/libcamera/ipa/rpi/${pipeline}"
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
depmod -a "${KERNEL}"
echo 'IMX678 prepared. Current camera and boot config are unchanged.'
echo 'After connecting the sensor, select Settings > Advanced > Camera Type > IMX678 (Auto).'
