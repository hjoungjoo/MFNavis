MFNAVIS_REPO_DIR="${MFNAVIS_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "${MFNAVIS_REPO_DIR}/mfnavis_paths.sh"

# swap tetra3 submodule
git submodule sync
git submodule update --init --recursive

# The post-update script now owns the import alias after submodule setup.
