#!/usr/bin/env bash
# Runs only in the disposable candidate checkout. No system installation.
set -euo pipefail
candidate_dir="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$candidate_dir/scripts/check_cedar_free.py" --repo "$candidate_dir"
bash "$candidate_dir/scripts/ensure_tetra3_link.sh" "$candidate_dir"
bash "$candidate_dir/scripts/setup_mfds.sh" --runtime
python3 -m pip check
