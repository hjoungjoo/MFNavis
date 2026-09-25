#! /usr/bin/bash
set -e
MFNAVIS_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${MFNAVIS_REPO_DIR}/mfnavis_paths.sh"
python3 "${MFNAVIS_REPO_DIR}/scripts/transactional_update.py" "${MFNAVIS_REPO_DIR}"
echo "MFNavis code update complete, please restart the Pi"
