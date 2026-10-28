#!/usr/bin/env bash
# Sourced by full setup after mfnavis_paths.sh and runtime OS selection.
# Code-only updates deliberately do not install kernel modules or select sensors.

mfnavis_plan_setup_camera() {
    local camera="${MFNAVIS_CAMERA:-keep}"
    local mode="${MFNAVIS_INSTALL_IMX678:-auto}"
    local boot_config="${BOOT_CONFIG:-$(mfnavis_boot_config_path)}"
    local required=false
    MFNAVIS_PREPARE_IMX678=false
    case "${camera}" in
        keep|imx462|imx296|imx477|imx678) ;;
        imx678-cm5-converter)
            if [[ "$(mfnavis_board_model)" != *"Compute Module 5"* ]]; then
                echo 'IMX678 CSI0 converter requires CM5, GPIO34/35 wiring.' >&2
                return 1
            fi
            ;;
        *) echo "Invalid MFNAVIS_CAMERA: ${camera}" >&2; return 1 ;;
    esac
    if [[ "${camera}" == imx678* ]] || {
        [[ "${camera}" == keep && -f "${boot_config}" ]] &&
        grep -Eq '^[[:space:]]*dtoverlay=imx678-mfnavis([,-]|[[:space:]]*$)' "${boot_config}"
    }; then
        required=true
    fi
    case "${mode,,}" in
        auto)
            if [[ "${required}" == true ]] || {
                [[ "${MFNAVIS_OS_CODENAME}" == trixie ]] &&
                [[ "$(mfnavis_board_profile)" == pi5_class ]]
            }; then
                MFNAVIS_PREPARE_IMX678=true
            fi
            ;;
        1|true|yes|on) MFNAVIS_PREPARE_IMX678=true ;;
        0|false|no|off)
            if [[ "${required}" == true ]]; then
                echo 'IMX678 is selected; cannot disable its installation.' >&2
                return 1
            fi
            ;;
        *) echo "Invalid MFNAVIS_INSTALL_IMX678: ${mode}; use auto, true or false." >&2; return 1 ;;
    esac
    echo "Camera setup: ${camera}; prepare IMX678: ${MFNAVIS_PREPARE_IMX678}"
}

mfnavis_install_setup_camera() {
    mfnavis_plan_setup_camera || return
    local camera="${MFNAVIS_CAMERA:-keep}"
    local action=--install
    if [[ "${camera}" == imx678-cm5-converter ]]; then
        action=--activate-converter
    fi
    if [[ "${MFNAVIS_PREPARE_IMX678}" == true ]]; then
        sudo env MFNAVIS_USER="${MFNAVIS_USER}" bash \
            "${MFNAVIS_REPO_DIR}/scripts/install_imx678.sh" "${action}" || return
        bash "${MFNAVIS_REPO_DIR}/scripts/install_imx678.sh" --check || return
    fi
    case "${camera}" in
        keep)
            # Existing overlays, including custom IMX678 parameters, win.
            sudo env PYTHONPATH="${MFNAVIS_REPO_DIR}/python" python3 \
                -m MFNavis.switch_camera --default imx462
            ;;
        imx678-cm5-converter) ;; # Installer backed up and selected this profile.
        *)
            sudo env PYTHONPATH="${MFNAVIS_REPO_DIR}/python" python3 \
                -m MFNavis.switch_camera "${camera}"
            ;;
    esac
}
