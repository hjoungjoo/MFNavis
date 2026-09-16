#!/usr/bin/env bash
# Compatibility entry point for commands in existing release notes.
set -euo pipefail
exec bash "$(dirname "$0")/setup_mfds.sh" "$@"
