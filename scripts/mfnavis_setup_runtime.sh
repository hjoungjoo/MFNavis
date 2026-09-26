#!/usr/bin/env bash
# Shared runtime setup for the main installer and the local Trixie installer.

mfnavis_select_setup_python() {
    MFNAVIS_OS_CODENAME="$(. /etc/os-release; printf '%s' "${VERSION_CODENAME:-}")"
    case "${MFNAVIS_OS_CODENAME}" in
        bookworm) MFNAVIS_PYTHON="${MFNAVIS_PYTHON:-/usr/bin/python3}" ;;
        trixie) MFNAVIS_PYTHON="${MFNAVIS_PYTHON:-${MFNAVIS_REPO_DIR}/.venv-trixie/bin/python}" ;;
        *)
            echo "Unsupported setup OS: ${MFNAVIS_OS_CODENAME:-unknown}" >&2
            return 1
            ;;
    esac
    export MFNAVIS_PYTHON
}

find_mfnavis_indi_archive() (
    # A subshell keeps nullglob changes out of the caller's shell.
    shopt -s nullglob
    archives=("${MFNAVIS_REPO_DIR}"/dist/mfnavis-indi-"${MFNAVIS_OS_CODENAME}"-arm64-*.tar.gz)
    parts=("${MFNAVIS_REPO_DIR}"/dist/mfnavis-indi-"${MFNAVIS_OS_CODENAME}"-arm64-*.tar.gz.part-00)
    for part in "${parts[@]}"; do
        archives+=("${part%.part-00}")
    done
    if [[ "${#archives[@]}" -gt 0 ]]; then
        printf '%s\n' "${archives[@]}" | sort -Vu | tail -n 1
    fi
)

mfnavis_prepare_indi_archive() {
    local mode="${MFNAVIS_INSTALL_INDI_ARCHIVE:-true}"
    mode="${mode,,}"
    MFNAVIS_SELECTED_INDI_ARCHIVE=""
    case "${mode}" in
        1|true|yes|on|archive|auto) ;;
        0|false|no|off|none|skip)
            echo "INDI archive installation explicitly disabled."
            return 0
            ;;
        *)
            echo "Invalid MFNAVIS_INSTALL_INDI_ARCHIVE value: ${mode}; use true or false." >&2
            return 1
            ;;
    esac

    local archive="${MFNAVIS_INDI_ARCHIVE:-}"
    if [[ -z "${archive}" ]]; then
        archive="$(find_mfnavis_indi_archive)" || return
    fi
    archive="${archive%.part-00}"
    if [[ -z "${archive}" || ( ! -f "${archive}" && ! -f "${archive}.part-00" ) ]]; then
        echo "Required INDI archive not found for ${MFNAVIS_OS_CODENAME}." >&2
        echo "Place the matching archive and .sha256 in ${MFNAVIS_REPO_DIR}/dist," >&2
        echo "or set MFNAVIS_INDI_ARCHIVE=/path/to/mfnavis-indi-${MFNAVIS_OS_CODENAME}-arm64.tar.gz." >&2
        return 1
    fi
    # Validate using the host Python before creating a new virtual environment.
    # The installer checks the selected app interpreter again during installation.
    local verify_python="${MFNAVIS_PYTHON}"
    if [[ ! -x "${verify_python}" ]]; then
        verify_python=/usr/bin/python3
    fi
    MFNAVIS_PYTHON="${verify_python}" bash \
        "${MFNAVIS_REPO_DIR}/scripts/install_indi_mount_archive.sh" \
        "${archive}" --verify-only || return
    MFNAVIS_SELECTED_INDI_ARCHIVE="${archive}"
}

mfnavis_install_setup_python() {
    if [[ "${MFNAVIS_OS_CODENAME}" == trixie ]]; then
        if [[ "${MFNAVIS_PYTHON}" == "${MFNAVIS_REPO_DIR}/.venv-trixie/bin/python" && ! -x "${MFNAVIS_PYTHON}" ]]; then
            python3 -m venv --system-site-packages "${MFNAVIS_REPO_DIR}/.venv-trixie" || return
        fi
        "${MFNAVIS_PYTHON}" -c 'import sys; assert sys.prefix != sys.base_prefix, "Trixie setup requires a virtual environment"' || return
        PIP_CONFIG_FILE=/dev/null "${MFNAVIS_PYTHON}" -m pip install \
            -r "${MFNAVIS_REPO_DIR}/python/requirements-trixie.txt" || return
        if [[ "$(mfnavis_board_profile)" == pi5_class ]]; then
            # Blinka pulls in classic RPi.GPIO, which shadows the working OS shim.
            "${MFNAVIS_PYTHON}" -m pip uninstall -y RPi.GPIO || return
            sudo apt-get install -y python3-rpi-lgpio || return
        fi
    else
        sudo "${MFNAVIS_PYTHON}" -m pip install --break-system-packages \
            -r "${MFNAVIS_REPO_DIR}/python/requirements.txt" || return
    fi
}

mfnavis_install_setup_indi() {
    if [[ -z "${MFNAVIS_SELECTED_INDI_ARCHIVE:-}" ]]; then
        return 0
    fi
    echo "Installing INDI from ${MFNAVIS_SELECTED_INDI_ARCHIVE}"
    MFNAVIS_PYTHON="${MFNAVIS_PYTHON}" bash \
        "${MFNAVIS_REPO_DIR}/scripts/install_indi_mount_archive.sh" \
        "${MFNAVIS_SELECTED_INDI_ARCHIVE}"
}

mfnavis_configure_python_services() {
    local service module
    for service in mfnavis mfnavis_splash; do
        module=main
        if [[ "${service}" == mfnavis_splash ]]; then module=splash; fi
        sudo install -d -m 755 "/etc/systemd/system/${service}.service.d" || return
        # This also supersedes the previous local 60-trixie-python.conf override.
        printf '[Service]\nExecStart=\nExecStart="%s" -m MFNavis.%s\n' \
            "${MFNAVIS_PYTHON}" "${module}" \
            | sudo tee "/etc/systemd/system/${service}.service.d/70-mfnavis-python.conf" >/dev/null || return
    done
}
