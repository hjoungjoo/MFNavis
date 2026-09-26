#!/usr/bin/env bash
# Supported build/host pairs. Archive metadata must also match before install.

check_indi_archive_platform() {
    local codename="$1"
    local architecture="$2"
    local python_version="$3"

    if [[ "${architecture}" != aarch64 ]] || \
       [[ "${codename}:${python_version}" != bookworm:3.11 && \
          "${codename}:${python_version}" != trixie:3.13 ]]; then
        echo "ERROR: INDI binary archives require aarch64 with Bookworm/Python 3.11 or Trixie/Python 3.13." >&2
        echo "Found OS=${codename:-unknown}, machine=${architecture}, Python=${python_version}." >&2
        echo "For another OS/Python ABI, use a matching source build; renaming the archive is insufficient." >&2
        return 1
    fi
}

require_indi_archive_platform() {
    local codename=""
    if [[ -r /etc/os-release ]]; then
        codename="$(. /etc/os-release; printf '%s' "${VERSION_CODENAME:-}")"
    fi
    check_indi_archive_platform "${codename}" "$(uname -m)" \
        "$("${MFNAVIS_PYTHON:-python3}" -c 'import sys; print("%s.%s" % sys.version_info[:2])')"
}
