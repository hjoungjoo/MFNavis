#! /usr/bin/bash
set -e

PIFINDER_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

cd "${PIFINDER_REPO_DIR}"
# Stay on the installed branch. Never silently switch a test/main installation
# back to release. Detached snapshots are updated by an explicit deployment.
branch="$(git symbolic-ref --quiet --short HEAD)" || {
    echo "Detached checkout: select the reviewed deployment branch first." >&2
    exit 1
}
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "Tracked files have local changes; refusing automatic update." >&2
    exit 1
fi
git fetch --no-tags origin "refs/heads/${branch}"
python3 "${PIFINDER_REPO_DIR}/scripts/check_cedar_free.py" --repo "${PIFINDER_REPO_DIR}" --ref FETCH_HEAD
git merge --ff-only FETCH_HEAD
source "${PIFINDER_REPO_DIR}/pifinder_post_update.sh"

echo "PiFinder software update complete, please restart the Pi"
