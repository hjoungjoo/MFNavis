#!/usr/bin/env bash
# Prepare a development venv and INDI wheelhouse without changing system services.
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MFNAVIS_REPO_DIR="${repo_dir}"
source "${repo_dir}/scripts/mfnavis_setup_runtime.sh"
mfnavis_select_setup_python
if [[ "${MFNAVIS_OS_CODENAME}" != trixie || "${EUID}" -eq 0 ]]; then
    echo "Run this script as the development user on Trixie." >&2
    exit 1
fi

dev_dir="${repo_dir}/.venv-dev-trixie"
if [[ ! -x "${dev_dir}/bin/python" ]]; then
    python3 -m venv --system-site-packages "${dev_dir}"
fi
archive="${MFNAVIS_INDI_ARCHIVE:-$(find_mfnavis_indi_archive)}"
archive="${archive%.part-00}"
wheel_dir="${repo_dir}/.dev-indi"
mkdir -p "${wheel_dir}"
rebuilt=""
cleanup() { if [[ -n "${rebuilt}" ]]; then rm -f "${rebuilt}"; fi; }
trap cleanup EXIT
if [[ ! -f "${archive}" ]]; then
    shopt -s nullglob
    parts=("${archive}".part-*)
    shopt -u nullglob
    if [[ -z "${archive}" || "${#parts[@]}" -eq 0 ]]; then
        echo "Trixie INDI archive not found; set MFNAVIS_INDI_ARCHIVE." >&2
        exit 1
    fi
    rebuilt="$(mktemp "${wheel_dir}/archive.XXXXXX.tar.gz")"
    cat "${parts[@]}" > "${rebuilt}"
fi
payload="${rebuilt:-${archive}}"
"${dev_dir}/bin/python" "${repo_dir}/scripts/verify_indi_archive.py" \
    "${payload}" "${archive}.sha256" --check-host
tar -xzf "${payload}" -C "${wheel_dir}" ./wheels ./metadata/python-requirements.txt
cp "${wheel_dir}/metadata/python-requirements.txt" "${wheel_dir}/python-requirements.txt"
"${dev_dir}/bin/python" - "${wheel_dir}" <<'PY'
from pathlib import Path
import sys
directory = Path(sys.argv[1])
lines = []
for name, pattern in [('pyindi-client', 'pyindi_client-*.whl'), ('indiweb', 'indiweb-*.whl')]:
    matches = list((directory / 'wheels').glob(pattern))
    if len(matches) != 1:
        raise SystemExit('Expected exactly one archive wheel for ' + name)
    lines.append(name + ' @ ' + matches[0].resolve().as_uri())
(directory / 'python-custom.txt').write_text('\n'.join(lines) + '\n')
PY

# python-libinput ships a Python 3 wheel via piwheels; its old sdist uses imp.
if [[ ! -f "${wheel_dir}/wheels/python_libinput-0.3.0a0-py3-none-any.whl" ]]; then
    PIP_CONFIG_FILE=/dev/null "${dev_dir}/bin/python" -m pip download \
        --index-url https://www.piwheels.org/simple --only-binary=:all: --no-deps \
        --dest "${wheel_dir}/wheels" "python-libinput==0.3.0a0"
fi
PIP_CONFIG_FILE=/dev/null "${dev_dir}/bin/python" -m pip install \
    -r "${repo_dir}/python/requirements_dev-trixie.txt"
# Provide a venv entry point even when apt already has this exact mypy version.
PIP_CONFIG_FILE=/dev/null "${dev_dir}/bin/python" -m pip install --ignore-installed --no-deps "mypy==1.15.0"
source "${repo_dir}/mfnavis_paths.sh"
if [[ "$(mfnavis_board_profile)" == pi5_class ]]; then
    "${dev_dir}/bin/python" -m pip uninstall -y RPi.GPIO
fi
bash "${repo_dir}/scripts/ensure_tetra3_link.sh" "${repo_dir}"
bash "${repo_dir}/scripts/setup_mfds.sh"
"${dev_dir}/bin/python" -c 'import PyIndi, picamera2, numpy, pandas, sep, quaternion'
echo "Development environment ready."
echo "source ${repo_dir}/scripts/activate_dev_trixie.sh"
