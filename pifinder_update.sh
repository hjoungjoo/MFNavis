#! /usr/bin/bash
set -e
PIFINDER_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"
python3 "${PIFINDER_REPO_DIR}/scripts/transactional_update.py" "${PIFINDER_REPO_DIR}"
echo "PiFinder code update complete, please restart the Pi"
