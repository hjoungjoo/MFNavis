#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MFNAVIS_REPO_DIR="${MFNAVIS_REPO_DIR:-${REPO_ROOT}}"
source "${REPO_ROOT}/mfnavis_paths.sh"
ARCHIVE="${1:-}"
VERIFY_ONLY="${2:-}"
FASTAPI_VERSION="${FASTAPI_VERSION:-0.103.2}"
STARLETTE_VERSION="${STARLETTE_VERSION:-0.27.0}"
UVICORN_VERSION="${UVICORN_VERSION:-0.23.2}"
ANYIO_VERSION="${ANYIO_VERSION:-3.7.1}"

usage() {
    echo "Usage: $0 <mfnavis-indi-OS-arm64.tar.gz> [--verify-only]" >&2
    echo "       If the archive is split, pass the .tar.gz path and keep .tar.gz.part-* next to it." >&2
}

if [[ -z "${ARCHIVE}" || ( -n "${VERIFY_ONLY}" && "${VERIFY_ONLY}" != --verify-only ) || "$#" -gt 2 ]]; then
    usage
    exit 1
fi

# Reject unsupported binaries before reconstructing archives or touching apt,
# Python packages, system services or files under /usr.
source "${REPO_ROOT}/scripts/indi_archive_platform.sh"
require_indi_archive_platform

if [[ "${VERIFY_ONLY}" != --verify-only ]]; then
    LOG_DIR="${MFNAVIS_DATA_DIR}/logs"
    mkdir -p "${LOG_DIR}"
    INDI_INSTALL_LOG="${MFNAVIS_INSTALL_LOG:-${LOG_DIR}/indi-install-$(date +%Y%m%d-%H%M%S)-$$.log}"
    (umask 077; touch "${INDI_INSTALL_LOG}")
    exec > >(tee -a "${INDI_INSTALL_LOG}") 2>&1
    echo "INDI install log: ${INDI_INSTALL_LOG}"
fi
SAFETY_TOOL="${REPO_ROOT}/scripts/indi_archive_transaction.py"
for merged in lib bin sbin; do
    if [[ ! -L "/${merged}" || "$(readlink -f "/${merged}")" != "/usr/${merged}" ]]; then
        echo "ERROR: /${merged} does not have the expected usrmerge link; recover the OS before installing INDI." >&2
        exit 1
    fi
done
if [[ "${VERIFY_ONLY}" != --verify-only ]]; then
    exec {INSTALL_LOCK_FD}>"${MFNAVIS_REPO_DIR}/.indi-install.lock"
    if ! flock -n "${INSTALL_LOCK_FD}"; then
        echo "Another INDI installation is already running." >&2
        exit 1
    fi
fi

# mfnavis_setup.sh mounts /tmp as a small tmpfs (SD-wear reduction), far too
# small to rebuild the split archive and extract its rootfs; use disk-backed
# /var/tmp instead of the mktemp default.
INDI_TMPDIR="$(mktemp -d /var/tmp/mfnavis-indi.XXXXXX)"
APP_WAS_ACTIVE=0
INDI_WAS_ACTIVE=0
CHRONY_WAS_ACTIVE=0
TRANSACTION_READY=0
COMMITTED=0
KEEP_BACKUP=0
cleanup() {
    local status=$?
    trap - EXIT
    set +e
    if [[ "${TRANSACTION_READY}" == 1 && "${COMMITTED}" == 0 ]]; then
        echo "Installation failed; restoring the previous INDI installation." >&2
        sudo systemctl stop mfnavis.service indiwebmanager.service
        if sudo /usr/bin/python3 "${SAFETY_TOOL}" rollback "${INDI_TMPDIR}/rollback"; then
            if ! sudo ldconfig || ! sudo systemctl daemon-reload; then
                KEEP_BACKUP=1
                status=1
                echo "Files restored, but runtime refresh failed. Services remain stopped; snapshot retained: ${INDI_TMPDIR}/rollback" >&2
            fi
            if [[ "${CHRONY_WAS_ACTIVE}" == 1 ]]; then
                sudo systemctl restart chrony || status=1
            fi
        else
            KEEP_BACKUP=1
            status=1
            echo "Rollback failed. Services remain stopped. Recovery snapshot: ${INDI_TMPDIR}/rollback" >&2
            echo "Recover with: sudo /usr/bin/python3 ${SAFETY_TOOL} rollback ${INDI_TMPDIR}/rollback" >&2
        fi
    fi
    if [[ "${KEEP_BACKUP}" == 1 ]]; then
        exit "${status}"
    fi
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
trap 'exit 130' INT
trap 'exit 143' TERM

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
    local bytes=0 part
    for part in "${parts[@]}"; do
        bytes=$((bytes + $(stat -c '%s' "${part}")))
    done
    /usr/bin/python3 "${SAFETY_TOOL}" space "${INDI_TMPDIR}" "${bytes}" >&2 || return
    cat "${parts[@]}" > "${rebuilt}" || return

    printf "%s\n" "${rebuilt}"
}

ARCHIVE_REQUESTED="${ARCHIVE}"
ARCHIVE="$(prepare_archive "${ARCHIVE_REQUESTED}")"
"${MFNAVIS_PYTHON:-python3}" "${REPO_ROOT}/scripts/verify_indi_archive.py" \
    "${ARCHIVE}" "${ARCHIVE_REQUESTED}.sha256" --check-host

if [[ "${VERIFY_ONLY}" == --verify-only ]]; then
    echo "Archive and host compatibility verified; no installation performed."
    exit 0
fi

SERVICE_USER="${MFNAVIS_USER}"

/usr/bin/python3 "${SAFETY_TOOL}" preflight "${ARCHIVE}" "${INDI_TMPDIR}"
tar -C "${INDI_TMPDIR}" -xzf "${ARCHIVE}"
# Normalize old archives as well as newly packaged ones; existing system
# directory metadata is independently protected by --no-overwrite-dir below.
find "${INDI_TMPDIR}/rootfs" -type d -exec chmod 755 {} +

if [ ! -d "${INDI_TMPDIR}/rootfs" ] || [ ! -f "${INDI_TMPDIR}/metadata/build_info.txt" ]; then
    echo "Invalid archive format: missing rootfs or metadata/build_info.txt" >&2
    exit 1
fi

echo "Installing INDI binary archive:"
cat "${INDI_TMPDIR}/metadata/build_info.txt"
echo

ARCHIVE_FORMAT="$(sed -n 's/^archive_format=//p' "${INDI_TMPDIR}/metadata/build_info.txt")"
if [[ "${ARCHIVE_FORMAT}" == mfnavis-indi-binary-v2 ]]; then
    if [[ -z "${MFNAVIS_PYTHON:-}" ]]; then
        if [[ -x "${MFNAVIS_REPO_DIR}/.venv-trixie/bin/python" ]]; then
            MFNAVIS_PYTHON="${MFNAVIS_REPO_DIR}/.venv-trixie/bin/python"
        else
            python3 -m venv --system-site-packages "${MFNAVIS_REPO_DIR}/.venv-indi"
            MFNAVIS_PYTHON="${MFNAVIS_REPO_DIR}/.venv-indi/bin/python"
        fi
    fi
    "${MFNAVIS_PYTHON}" -c 'import sys; assert sys.prefix != sys.base_prefix, "Set MFNAVIS_PYTHON to a virtualenv interpreter"'
    "${MFNAVIS_PYTHON}" "${REPO_ROOT}/scripts/verify_indi_archive.py" \
        "${ARCHIVE}" "${ARCHIVE_REQUESTED}.sha256" --check-host
    # Ensure the wheelhouse contains the complete pinned dependency closure
    # before stopping either service or overwriting any native files.
    "${MFNAVIS_PYTHON}" -m pip install --dry-run --ignore-installed --no-index \
        --find-links "${INDI_TMPDIR}/wheels" -r "${INDI_TMPDIR}/metadata/python-requirements.txt"
    mapfile -t RUNTIME_PACKAGES < "${INDI_TMPDIR}/metadata/runtime-packages.txt"
    sudo apt-get update
    sudo apt-get install -y "${RUNTIME_PACKAGES[@]}" chrony
    INDI_WEB_EXEC="$("${MFNAVIS_PYTHON}" -c 'import sysconfig; print(sysconfig.get_path("scripts") + "/indi-web")')"
else

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

    # Keep Web Manager dependencies out of the OS Python on Bookworm too.
    MFNAVIS_PYTHON="${MFNAVIS_PYTHON:-python3}"
    if ! "${MFNAVIS_PYTHON}" -c 'import sys; assert sys.prefix != sys.base_prefix'; then
        python3 -m venv --system-site-packages "${MFNAVIS_REPO_DIR}/.venv-indi"
        MFNAVIS_PYTHON="${MFNAVIS_REPO_DIR}/.venv-indi/bin/python"
    fi
    cat > "${INDI_TMPDIR}/bookworm-requirements.txt" <<EOF
jinja2
fastapi==${FASTAPI_VERSION}
starlette==${STARLETTE_VERSION}
uvicorn==${UVICORN_VERSION}
anyio==${ANYIO_VERSION}
bottle==0.12.25
psutil==6.0.0
requests==2.32.4
importlib_metadata==8.5.0
EOF
    "${MFNAVIS_PYTHON}" -m pip install --dry-run -r "${INDI_TMPDIR}/bookworm-requirements.txt"
    INDI_WEB_EXEC="${MFNAVIS_PYTHON} /usr/local/bin/indi-web"
fi

VENV_DIR="$("${MFNAVIS_PYTHON}" -c 'import sys; print(sys.prefix)')"
sudo /usr/bin/python3 "${SAFETY_TOOL}" snapshot "${INDI_TMPDIR}/rootfs" \
    "${INDI_TMPDIR}/rollback" --venv "${VENV_DIR}" --check-only

if sudo systemctl is-active --quiet chrony; then
    CHRONY_WAS_ACTIVE=1
fi

if sudo systemctl is-active --quiet mfnavis.service; then
    APP_WAS_ACTIVE=1
    sudo systemctl stop mfnavis.service
fi
if sudo systemctl is-active --quiet indiwebmanager.service; then
    INDI_WAS_ACTIVE=1
    sudo systemctl stop indiwebmanager.service
fi

sudo /usr/bin/python3 "${SAFETY_TOOL}" snapshot "${INDI_TMPDIR}/rootfs" \
    "${INDI_TMPDIR}/rollback" --venv "${VENV_DIR}"
TRANSACTION_READY=1

if [[ "${ARCHIVE_FORMAT}" != mfnavis-indi-binary-v2 ]]; then
    "${MFNAVIS_PYTHON}" -m pip install -r "${INDI_TMPDIR}/bookworm-requirements.txt"
fi

sudo tar -C "${INDI_TMPDIR}/rootfs" --owner=0 --group=0 --numeric-owner -cf - . \
    | sudo tar -C / --numeric-owner --keep-directory-symlink --no-overwrite-dir -xpf -
sudo ldconfig

if [[ "${ARCHIVE_FORMAT}" == mfnavis-indi-binary-v2 ]]; then
    "${MFNAVIS_PYTHON}" -m pip install --no-index --no-deps --force-reinstall \
        --find-links "${INDI_TMPDIR}/wheels" -r "${INDI_TMPDIR}/metadata/python-requirements.txt"
fi
"${MFNAVIS_PYTHON}" -c 'import PyIndi, indiweb, fastapi; print("INDI Python imports OK")'

# Never attempt to repair usrmerge by deleting system directories mid-install.
# A damaged OS must be recovered separately with its package manager.

cat > "${INDI_TMPDIR}/indiwebmanager.service" <<EOF
[Unit]
Description=INDI Web Manager
After=multi-user.target

[Service]
Type=idle
User=${SERVICE_USER}
WorkingDirectory=${MFNAVIS_REPO_DIR}
ExecStart=${INDI_WEB_EXEC} -v
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

if ! sudo grep -q "refclock SHM 0 poll 3 refid gps1" /etc/chrony/chrony.conf; then
    echo "" | sudo tee -a /etc/chrony/chrony.conf >/dev/null
    echo "# Sync time from GPSD" | sudo tee -a /etc/chrony/chrony.conf >/dev/null
    echo "refclock SHM 0 poll 3 refid gps1" | sudo tee -a /etc/chrony/chrony.conf >/dev/null
fi
sudo systemctl restart chrony
if [ "${APP_WAS_ACTIVE}" -eq 1 ]; then
    sudo systemctl start mfnavis.service
fi
COMMITTED=1
APP_WAS_ACTIVE=0
INDI_WAS_ACTIVE=0

echo
echo "INDI archive install complete."
echo "Open INDI Web Manager at: http://$(hostname).local:8624"
