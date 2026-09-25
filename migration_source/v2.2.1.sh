MFNAVIS_REPO_DIR="${MFNAVIS_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "${MFNAVIS_REPO_DIR}/mfnavis_paths.sh"

# install lib input
sudo apt install -y libinput10

# Add PiFinder user to input group
sudo usermod -G input -a "${MFNAVIS_USER}"
