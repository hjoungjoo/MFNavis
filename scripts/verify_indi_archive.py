#!/usr/bin/env python3
"""Verify the INDI binary archive before it is extracted or installed."""

import argparse
import hashlib
from pathlib import Path
import posixpath
import re
import sys
import tarfile


def verify_checksum(archive: Path, checksum_file: Path) -> None:
    if not checksum_file.is_file():
        raise ValueError(f"missing archive checksum: {checksum_file}")
    expected = checksum_file.read_text(encoding="ascii").split()[0]
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError(f"invalid archive checksum: {checksum_file}")
    digest = hashlib.sha256()
    with archive.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected.lower():
        raise ValueError(f"archive checksum mismatch: {archive}")


def verify_members(archive: Path) -> None:
    seen = set()
    symlinks = {}
    types = {}
    required = {"metadata/build_info.txt", "rootfs/usr"}
    with tarfile.open(archive, "r:gz") as contents:
        for member in contents:
            name = member.name.removeprefix("./")
            parts = name.split("/")
            if name == ".":
                continue
            if any(part in {"", ".", ".."} for part in parts) or "\\" in name:
                raise ValueError(f"unsafe archive path: {member.name}")
            if (
                name not in {"rootfs", "metadata"}
                and not (name.startswith("rootfs/usr/") or name.startswith("metadata/"))
                and name != "rootfs/usr"
            ):
                raise ValueError(f"unexpected archive path: {member.name}")
            if name in seen:
                raise ValueError(f"duplicate archive path: {member.name}")
            seen.add(name)
            types[name] = member
            if not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError(f"unsupported archive member: {member.name}")
            if member.issym() and (
                not member.linkname
                or member.linkname in {".", ".."}
                or "/" in member.linkname
                or "\\" in member.linkname
            ):
                raise ValueError(f"unsafe archive symlink: {member.name}")
            if member.issym():
                symlinks[name] = member.linkname
    if not required.issubset(seen):
        raise ValueError(f"missing required archive members: {sorted(required - seen)}")
    if not types["rootfs/usr"].isdir() or not types["metadata/build_info.txt"].isfile():
        raise ValueError("invalid archive rootfs or build_info type")
    if any(path.startswith(f"{link}/") for link in symlinks for path in seen):
        raise ValueError("archive member is nested below a symlink")
    for link, target in symlinks.items():
        if posixpath.join(posixpath.dirname(link), target) not in seen:
            raise ValueError(f"archive symlink target is missing: {link}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("checksum_file", type=Path)
    args = parser.parse_args()
    try:
        verify_checksum(args.archive, args.checksum_file)
        verify_members(args.archive)
    except (OSError, ValueError, tarfile.TarError, IndexError) as exc:
        print(f"INDI archive verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"INDI archive verified: {args.archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
