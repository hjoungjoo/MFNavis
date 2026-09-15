#!/usr/bin/env bash
# Initialize the pinned detector source and build it; no service/config changes.
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
build_mode="${1:---with-tools}"
if [[ $# -gt 1 || ( "$build_mode" != --runtime && "$build_mode" != --with-tools ) ]]; then
    echo "Usage: $0 [--runtime|--with-tools]" >&2
    exit 2
fi
git -C "$repo_dir" submodule update --init -- python/mf_detect_star
if [[ "$build_mode" == --runtime ]]; then
    make -C "$repo_dir/python/mf_detect_star" -j2 runtime
else
    make -C "$repo_dir/python/mf_detect_star" -j2 all
    make -C "$repo_dir/python/mf_detect_star" test
fi
