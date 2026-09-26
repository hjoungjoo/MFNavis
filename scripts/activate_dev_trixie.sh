#!/usr/bin/env bash
# Source this file to select the development environment and isolated app data.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Use: source $0" >&2
    exit 1
fi
_mfnavis_dev_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "${_mfnavis_dev_repo}/.venv-dev-trixie/bin/python" ]]; then
    echo "Run bash ${_mfnavis_dev_repo}/scripts/setup_dev_trixie.sh first." >&2
    return 1
fi
export PATH="${HOME}/.local/bin:${PATH}"
source "${_mfnavis_dev_repo}/.venv-dev-trixie/bin/activate"
export PYTHONPATH="${_mfnavis_dev_repo}/python${PYTHONPATH:+:${PYTHONPATH}}"
export NOX_PYTHON=3.13
export PIP_CONFIG_FILE=/dev/null
export MFNAVIS_PYTHON="${_mfnavis_dev_repo}/.venv-dev-trixie/bin/python"
if [[ "$(bash -c 'source "$1/mfnavis_paths.sh"; mfnavis_board_profile' dev "${_mfnavis_dev_repo}")" == pi5_class ]]; then
    export MFNAVIS_DEV_USE_OS_GPIO=1
else
    export MFNAVIS_DEV_USE_OS_GPIO=0
fi
export MFNAVIS_DATA_DIR="${MFNAVIS_DEV_DATA_DIR:-${HOME}/MFNavis_dev_data}"
export MFNAVIS_RUNTIME_DIR="${MFNAVIS_DEV_RUNTIME_DIR:-/tmp/mfnavis-dev-${UID}}"
export DO_NOT_TRACK=1
mkdir -p "${MFNAVIS_DATA_DIR}" "${MFNAVIS_RUNTIME_DIR}"
cd "${_mfnavis_dev_repo}/python" || return
unset _mfnavis_dev_repo
