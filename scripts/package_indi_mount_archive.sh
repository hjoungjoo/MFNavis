#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_ROOT="${BUILD_ROOT:-$HOME/indi-latest}"
OUT_DIR="${OUT_DIR:-${REPO_ROOT}/dist}"
INDI_BUILD_DIR="${INDI_BUILD_DIR:-${BUILD_ROOT}/indi/build}"
INDI_3RDPARTY_BUILD_DIR="${INDI_3RDPARTY_BUILD_DIR:-${BUILD_ROOT}/indi-3rdparty/build-drivers}"
INDI_3RDPARTY_LIBS_BUILD_DIR="${INDI_3RDPARTY_LIBS_BUILD_DIR:-${BUILD_ROOT}/indi-3rdparty/build-libs}"
INDI_MANIFEST="${INDI_BUILD_DIR}/install_manifest.txt"
INDI_3RDPARTY_MANIFEST="${INDI_3RDPARTY_BUILD_DIR}/install_manifest.txt"
# The 3rd-party build has a separate "build-libs" stage that installs support
# libraries. With all camera drivers disabled it currently installs nothing (no
# manifest is produced), but if a driver that ships a bundled lib is ever
# enabled, those libs must go into the archive too. Include it when present.
INDI_3RDPARTY_LIBS_MANIFEST="${INDI_3RDPARTY_LIBS_BUILD_DIR}/install_manifest.txt"
PYTHON_SITE="${PYTHON_SITE:-$(python3 -c 'import site; print(site.getsitepackages()[0])')}"
SPLIT_ARCHIVE="${SPLIT_ARCHIVE:-auto}"
ARCHIVE_SPLIT_SIZE="${ARCHIVE_SPLIT_SIZE:-47M}"
ARCHIVE_SPLIT_THRESHOLD_BYTES="${ARCHIVE_SPLIT_THRESHOLD_BYTES:-95000000}"

require_file() {
    if [ ! -f "$1" ]; then
        echo "Missing required file: $1" >&2
        exit 1
    fi
}

normalize_usrmerge_path() {
    # Bookworm uses the usrmerge layout: /lib, /bin, /sbin and /lib64 are
    # symlinks into /usr. Some INDI drivers install files under /lib (e.g.
    # /lib/udev/rules.d), so the manifest lists /lib/... paths. Shipping those
    # as a real ./lib in the archive would clobber the /lib -> usr/lib symlink
    # on extraction and brick the system. Since /lib and /usr/lib are the same
    # location, rewrite these prefixes to their /usr counterparts so the archive
    # only ever contains ./usr/... and is safe to extract with any tar.
    local path="$1"
    case "${path}" in
        /lib/*|/lib|/bin/*|/bin|/sbin/*|/sbin|/lib64/*|/lib64)
            printf '/usr%s\n' "${path}"
            ;;
        *)
            printf '%s\n' "${path}"
            ;;
    esac
}

copy_path_to_rootfs() {
    local path="$1"
    local rootfs="$2"
    local dest

    if [ ! -e "${path}" ] && [ ! -L "${path}" ]; then
        echo "ERROR: missing installed path: ${path}" >&2
        return 1
    fi

    dest="${rootfs}$(normalize_usrmerge_path "${path}")"
    mkdir -p "$(dirname "${dest}")"
    cp -a "${path}" "${dest}"
}

copy_manifest_paths() {
    local manifest="$1"
    local rootfs="$2"

    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        copy_path_to_rootfs "${path}" "${rootfs}"
    done < "${manifest}"
}

split_archive_if_needed() {
    local archive_path="$1"
    local mode
    local archive_size
    local part_prefix

    mode="${SPLIT_ARCHIVE,,}"
    archive_size="$(stat -c '%s' "${archive_path}")"
    part_prefix="${archive_path}.part-"

    case "${mode}" in
        1|true|yes|on|always)
            ;;
        auto|"")
            if [ "${archive_size}" -le "${ARCHIVE_SPLIT_THRESHOLD_BYTES}" ]; then
                echo "Archive is ${archive_size} bytes; split parts not needed."
                return 0
            fi
            ;;
        0|false|no|off|none|skip)
            echo "Skipping split archive parts."
            return 0
            ;;
        *)
            echo "Invalid SPLIT_ARCHIVE value: ${SPLIT_ARCHIVE}" >&2
            echo "Use auto, true, or false." >&2
            exit 1
            ;;
    esac

    rm -f "${part_prefix}"*
    split -b "${ARCHIVE_SPLIT_SIZE}" -d -a 2 "${archive_path}" "${part_prefix}"
    echo "Created split archive parts:"
    find "$(dirname "${archive_path}")" \
        -maxdepth 1 \
        -type f \
        -name "$(basename "${archive_path}").part-*" \
        -printf "  %f (%s bytes)\n" \
        | sort
}

check_arm64_compatibility() {
    local report="$1"
    local cache
    local cpu_flag_pattern='-m(arch|cpu|tune)=(native|cortex-a76|armv8\.2-a|armv8\.3-a|armv8\.4-a|armv9[^[:space:]]*)'

    : > "${report}"
    {
        echo "PiFinder INDI archive compatibility report"
        echo "Generated: $(date -Is)"
        echo "Host machine: $(uname -m)"
        echo
    } >> "${report}"

    if [ "$(uname -m)" != "aarch64" ]; then
        echo "ERROR: this package must be created on aarch64/arm64." | tee -a "${report}" >&2
        exit 1
    fi

    for cache in "${INDI_BUILD_DIR}/CMakeCache.txt" "${INDI_3RDPARTY_BUILD_DIR}/CMakeCache.txt"; do
        require_file "${cache}"
        {
            echo "Checking CMake flags: ${cache}"
            grep -E 'CMAKE_(C|CXX)_FLAGS' "${cache}" || true
            echo
        } >> "${report}"
        if grep -Eq -- "${cpu_flag_pattern}" "${cache}"; then
            echo "ERROR: Pi 5-specific/native CPU flags found in ${cache}" | tee -a "${report}" >&2
            exit 1
        fi
    done

    for binary in /usr/bin/indiserver /usr/bin/indi_lx200generic /usr/bin/indi_lx200_OnStep /usr/bin/indi_lx200_OnStepX; do
        if [ -e "${binary}" ] || [ -L "${binary}" ]; then
            echo "file ${binary}: $(file -b "${binary}")" >> "${report}"
        fi
    done
}

require_file "${INDI_MANIFEST}"
require_file "${INDI_3RDPARTY_MANIFEST}"

mkdir -p "${OUT_DIR}"
# /tmp is a small tmpfs on installed devices; the uncompressed rootfs needs disk.
STAGING="$(mktemp -d /var/tmp/mfnavis-indi-package.XXXXXX)"
trap 'rm -rf "${STAGING}"' EXIT

ROOTFS="${STAGING}/rootfs"
METADATA="${STAGING}/metadata"
mkdir -p "${ROOTFS}" "${METADATA}"

check_arm64_compatibility "${METADATA}/compatibility_report.txt"

copy_manifest_paths "${INDI_MANIFEST}" "${ROOTFS}"
copy_manifest_paths "${INDI_3RDPARTY_MANIFEST}" "${ROOTFS}"
if [ -f "${INDI_3RDPARTY_LIBS_MANIFEST}" ]; then
    copy_manifest_paths "${INDI_3RDPARTY_LIBS_MANIFEST}" "${ROOTFS}"
fi

while IFS= read -r path; do
    copy_path_to_rootfs "${path}" "${ROOTFS}"
done < <(find /usr/bin -maxdepth 1 -type l \( -lname indi_lx200generic -o -lname indi_tcfs_focus \) -print | sort)

for path in \
    "${PYTHON_SITE}/PyIndi.py" \
    "${PYTHON_SITE}/_PyIndi.cpython-311-aarch64-linux-gnu.so" \
    "${PYTHON_SITE}/pyindi_client-2.1.2.dist-info" \
    "${PYTHON_SITE}/indiweb" \
    "${PYTHON_SITE}/indiweb-1.0.0.dist-info" \
    /usr/local/bin/indi-web; do
    copy_path_to_rootfs "${path}" "${ROOTFS}"
done

{
    echo "archive_format=mf-pifinder-indi-binary-v1"
    echo "created_at=$(date -Is)"
    echo "host=$(hostname)"
    echo "machine=$(uname -m)"
    echo "python_site=${PYTHON_SITE}"
    echo "indi_core_tag=$(git -C "${BUILD_ROOT}/indi" describe --tags --exact-match HEAD 2>/dev/null || git -C "${BUILD_ROOT}/indi" rev-parse --short HEAD)"
    echo "indi_3rdparty_tags=$(git -C "${BUILD_ROOT}/indi-3rdparty" tag --points-at HEAD 2>/dev/null | tr '\n' ' ')"
    echo "pyindi_version=2.1.2"
    echo "indiweb_version=1.0.0"
    echo "arm64_compatibility=checked-no-native-or-pi5-specific-cpu-flags"
    echo "recommended_build_flag=-march=armv8-a"
    if [ -f "${REPO_ROOT}/scripts/patches/indi-v2.2.3.1-onstepx.patch" ]; then
        echo "onstepx_patch=indi-v2.2.3.1-onstepx.patch"
        echo "onstepx_patch_sha256=$(sha256sum "${REPO_ROOT}/scripts/patches/indi-v2.2.3.1-onstepx.patch" | awk '{print $1}')"
    fi
} > "${METADATA}/build_info.txt"

ldd /usr/bin/indiserver > "${METADATA}/ldd-indiserver.txt"
ldd /usr/bin/indi_lx200generic > "${METADATA}/ldd-indi_lx200generic.txt"
cp "${INDI_MANIFEST}" "${METADATA}/indi-install_manifest.txt"
cp "${INDI_3RDPARTY_MANIFEST}" "${METADATA}/indi-3rdparty-install_manifest.txt"
if [ -f "${INDI_3RDPARTY_LIBS_MANIFEST}" ]; then
    cp "${INDI_3RDPARTY_LIBS_MANIFEST}" \
        "${METADATA}/indi-3rdparty-libs-install_manifest.txt"
fi

ARCHIVE_NAME="${ARCHIVE_NAME:-mf-pifinder-indi-bookworm-arm64-$(date +%Y%m%d-%H%M%S).tar.gz}"
ARCHIVE_PATH="${OUT_DIR}/${ARCHIVE_NAME}"

tar --owner=0 --group=0 --numeric-owner -C "${STAGING}" -czf "${ARCHIVE_PATH}" .
sha256sum "${ARCHIVE_PATH}" > "${ARCHIVE_PATH}.sha256"
split_archive_if_needed "${ARCHIVE_PATH}"

echo "Created archive: ${ARCHIVE_PATH}"
echo "Checksum: ${ARCHIVE_PATH}.sha256"
