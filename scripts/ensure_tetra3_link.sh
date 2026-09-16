#!/usr/bin/env bash
# Create the import alias for the vendored Tetra3 source. Preserve any old
# directory or nonstandard link before replacing it; never follow it on move.
set -eu

repo_dir="$(cd "${1:?PiFinder repository path required}" && pwd)"
link_path="${repo_dir}/python/tetra3"
target="PiFinder/tetra3/tetra3"

if ! [ -d "${repo_dir}/python/${target}" ]; then
    echo "vendored tetra3 source is missing: ${repo_dir}/python/${target}" >&2
    exit 1
fi

if [ -L "${link_path}" ] && [ "$(readlink "${link_path}")" = "${target}" ]; then
    exit 0
fi

if [ -e "${link_path}" ] || [ -L "${link_path}" ]; then
    backup_dir="$(mktemp -d "${repo_dir}/python/tetra3.backup.XXXXXX")"
    mv -- "${link_path}" "${backup_dir}/original"
    echo "Previous tetra3 path preserved at ${backup_dir}/original"
fi
ln -s "${target}" "${link_path}"
