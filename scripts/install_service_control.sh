#!/usr/bin/env bash
# Allow the application user to restart only the MFNavis service.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MFNAVIS_USER="${1:-${MFNAVIS_USER:-${SUDO_USER:-$(id -un)}}}"

if [[ ! "${MFNAVIS_USER}" =~ ^[a-z_][a-z0-9_-]*\$?$ || "${MFNAVIS_USER}" == root ]]; then
    echo "Specify a non-root MFNavis service user." >&2
    exit 1
fi
id "${MFNAVIS_USER}" >/dev/null

if [[ "${EUID}" -ne 0 ]]; then
    exec sudo bash "${SCRIPT_DIR}/install_service_control.sh" "${MFNAVIS_USER}"
fi

policy_tmp="$(mktemp)"
trap 'rm -f "${policy_tmp}"' EXIT
printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl --no-block restart mfnavis.service\n' \
    "${MFNAVIS_USER}" > "${policy_tmp}"
/usr/sbin/visudo -cf "${policy_tmp}"
install -o root -g root -m 0440 "${policy_tmp}" /etc/sudoers.d/90-mfnavis-service-control
echo "Installed MFNavis restart permission for ${MFNAVIS_USER}."
