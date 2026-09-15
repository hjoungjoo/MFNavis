#!/usr/bin/env bash
# Initialize the pinned detector source and build it; no service/config changes.
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
git -C "$repo_dir" submodule update --init -- python/mf_detect_star
make -C "$repo_dir/python/mf_detect_star" -j2
make -C "$repo_dir/python/mf_detect_star" test
