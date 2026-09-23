#! /usr/bin/bash
set -e
PIFINDER_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${PIFINDER_REPO_DIR}/mfnavis_paths.sh"
python3 "${PIFINDER_REPO_DIR}/scripts/transactional_update.py" "${PIFINDER_REPO_DIR}"
echo "MFNavis code update complete, please restart the Pi"
