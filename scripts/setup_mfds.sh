#!/usr/bin/env bash
# Install only MFDS release artifacts; never clone or compile detector sources.
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
# Retain old callers' mode arguments; the package contains all runtime tools.
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --runtime && "$1" != --with-tools ) ]]; then
    echo "Usage: $0 [--runtime|--with-tools]" >&2
    exit 2
fi
exec python3 "$repo_dir/scripts/install_mfds.py" --repo "$repo_dir"
