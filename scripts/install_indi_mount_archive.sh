#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIFINDER_REPO_DIR="${REPO_ROOT}"
source "${REPO_ROOT}/pifinder_paths.sh"
ARCHIVE="${1:-}"
FASTAPI_VERSION="${FASTAPI_VERSION:-0.103.2}"
STARLETTE_VERSION="${STARLETTE_VERSION:-0.27.0}"
UVICORN_VERSION="${UVICORN_VERSION:-0.23.2}"
ANYIO_VERSION="${ANYIO_VERSION:-3.7.1}"

usage() {
    echo "Usage: $0 <mf-pifinder-indi-bookworm-arm64.tar.gz>" >&2
    echo "       If the archive is split, pass the .tar.gz path and keep .tar.gz.part-* next to it." >&2
}

if [ -z "${ARCHIVE}" ]; then
    usage
    exit 1
fi

# mfnavis_setup.sh mounts /tmp as a small tmpfs (SD-wear reduction), far too
# small to rebuild the split archive and extract its rootfs; use disk-backed
# /var/tmp instead of the mktemp default.
INDI_TMPDIR="$(mktemp -d /var/tmp/mfnavis-indi.XXXXXX)"
APP_WAS_ACTIVE=0
INDI_WAS_ACTIVE=0
cleanup() {
    local status=$?
    trap - EXIT
    if [ "${INDI_WAS_ACTIVE}" -eq 1 ]; then
        sudo systemctl start indiwebmanager.service || status=1
    fi
    if [ "${APP_WAS_ACTIVE}" -eq 1 ]; then
        sudo systemctl start mfnavis.service || status=1
    fi
    rm -rf "${INDI_TMPDIR}"
    exit "${status}"
}
trap cleanup EXIT

prepare_archive() {
    local requested="$1"
    local rebuilt

    if [ -f "${requested}" ]; then
        printf "%s\n" "${requested}"
        return 0
    fi

    shopt -s nullglob
    local parts=("${requested}".part-*)
    shopt -u nullglob

    if [ "${#parts[@]}" -eq 0 ]; then
        echo "Archive not found: ${requested}" >&2
        echo "No split archive parts found at: ${requested}.part-*" >&2
        exit 1
    fi

    rebuilt="${INDI_TMPDIR}/$(basename "${requested}")"
    echo "Rebuilding split archive: ${requested}" >&2
    cat "${parts[@]}" > "${rebuilt}"

    printf "%s\n" "${rebuilt}"
}

ARCHIVE_REQUESTED="${ARCHIVE}"
ARCHIVE="$(prepare_archive "${ARCHIVE_REQUESTED}")"
python3 "${REPO_ROOT}/scripts/verify_indi_archive.py" \
    "${ARCHIVE}" "${ARCHIVE_REQUESTED}.sha256"

if [ "$(uname -m)" != "aarch64" ]; then
    echo "This archive installer supports only Raspberry Pi OS Bookworm 64-bit/aarch64." >&2
    exit 1
fi

if [ -r /etc/os-release ]; then
    . /etc/os-release
    if [ "${VERSION_CODENAME:-}" != "bookworm" ]; then
        echo "WARNING: expected Bookworm, found ${PRETTY_NAME:-unknown OS}." >&2
    fi
fi

SERVICE_USER="${PIFINDER_USER}"

tar -C "${INDI_TMPDIR}" -xzf "${ARCHIVE}"

if [ ! -d "${INDI_TMPDIR}/rootfs" ] || [ ! -f "${INDI_TMPDIR}/metadata/build_info.txt" ]; then
    echo "Invalid archive format: missing rootfs or metadata/build_info.txt" >&2
    exit 1
fi

echo "Installing INDI binary archive:"
cat "${INDI_TMPDIR}/metadata/build_info.txt"
echo

sudo apt update
sudo apt install -y \
    libev4 libgps28 libgsl27 libraw20 zlib1g libftdi1-2 \
    libjpeg62-turbo libkrb5-3 libnova-0.16-0 libtiff6 \
    libfftw3-double3 librtlsdr0 libcfitsio10 libgphoto2-6 \
    libusb-1.0-0 libdc1394-25 libboost-regex1.74.0 \
    libcurl3-gnutls libtheora0 liblimesuite22.09-1 \
    libavcodec59 libavdevice59 libavformat59 libavutil57 \
    libswscale6 libzmq5 libudev1 libdbus-1-3 libglib2.0-0 \
    python3-pip python3-setuptools chrony

PIP_BREAK_SYSTEM_PACKAGES=1 sudo python3 -m pip install --break-system-packages \
    jinja2 \
    "fastapi==${FASTAPI_VERSION}" \
    "starlette==${STARLETTE_VERSION}" \
    "uvicorn==${UVICORN_VERSION}" \
    "anyio==${ANYIO_VERSION}" \
    "bottle==0.12.25" \
    "psutil==6.0.0" \
    "requests==2.32.4" \
    "importlib_metadata==8.5.0"

if sudo systemctl is-active --quiet mfnavis.service; then
    APP_WAS_ACTIVE=1
    sudo systemctl stop mfnavis.service
fi
if sudo systemctl is-active --quiet indiwebmanager.service; then
    INDI_WAS_ACTIVE=1
    sudo systemctl stop indiwebmanager.service
fi

# --keep-directory-symlink is REQUIRED: on Bookworm /lib, /bin, /sbin and
# /lib64 are symlinks into /usr (the "usrmerge" layout). The rootfs overlay
# ships real ./lib and ./usr directories, and without this flag GNU tar would
# replace the /lib -> usr/lib symlink with a fresh real directory. That makes
# /lib/ld-linux-aarch64.so.1 (the dynamic loader) disappear, so every
# dynamically-linked binary — sudo, rm, bash — dies with
# "cannot execute: required file not found" and the whole system is bricked.
# The flag tells tar to descend into the existing symlinked directory instead.
sudo tar -C "${INDI_TMPDIR}/rootfs" --owner=0 --group=0 --numeric-owner -cf - . \
    | sudo tar -C / --numeric-owner --keep-directory-symlink -xpf -
sudo ldconfig

# Safety net: if a previous run (or an older archive) already clobbered the
# usrmerge symlinks, restore them so the system stays bootable.
for merged in lib bin sbin lib64; do
    if [ -d "/${merged}" ] && [ ! -L "/${merged}" ] && [ -d "/usr/${merged}" ]; then
        echo "WARNING: /${merged} is a real directory but should be a symlink to /usr/${merged}." >&2
        echo "         Merging its contents back into /usr/${merged} and restoring the symlink." >&2
        sudo cp -a "/${merged}/." "/usr/${merged}/"
        sudo rm -rf "/${merged}"
        sudo ln -s "usr/${merged}" "/${merged}"
    fi
done
sudo ldconfig

cat > "${INDI_TMPDIR}/indiwebmanager.service" <<EOF
[Unit]
Description=INDI Web Manager
After=multi-user.target

[Service]
Type=idle
User=${SERVICE_USER}
WorkingDirectory=${REPO_ROOT}
ExecStart=/usr/local/bin/indi-web -v
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo cp "${INDI_TMPDIR}/indiwebmanager.service" /etc/systemd/system/indiwebmanager.service
sudo chown root:root /etc/systemd/system/indiwebmanager.service
sudo chmod 644 /etc/systemd/system/indiwebmanager.service
sudo systemctl daemon-reload
sudo systemctl enable indiwebmanager.service
sudo systemctl restart indiwebmanager.service
INDI_WAS_ACTIVE=0

if ! sudo grep -q "refclock SHM 0 poll 3 refid gps1" /etc/chrony/chrony.conf; then
    echo "" | sudo tee -a /etc/chrony/chrony.conf >/dev/null
    echo "# Sync time from GPSD" | sudo tee -a /etc/chrony/chrony.conf >/dev/null
    echo "refclock SHM 0 poll 3 refid gps1" | sudo tee -a /etc/chrony/chrony.conf >/dev/null
fi
sudo systemctl restart chrony
if [ "${APP_WAS_ACTIVE}" -eq 1 ]; then
    sudo systemctl start mfnavis.service
    APP_WAS_ACTIVE=0
fi

echo
echo "INDI archive install complete."
echo "Open INDI Web Manager at: http://$(hostname).local:8624"
