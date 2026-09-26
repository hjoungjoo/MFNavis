#!/usr/bin/env python3
"""Verify the INDI binary archive before it is extracted or installed."""

import argparse
import hashlib
from pathlib import Path
import posixpath
import platform
import re
import sys
import sysconfig
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


def verify_members(archive: Path) -> dict:
    seen = set()
    symlinks = {}
    types = {}
    required = {"metadata/build_info.txt", "rootfs/usr"}
    info = {}
    metadata_text = {}
    with tarfile.open(archive, "r:gz") as contents:
        for member in contents:
            name = member.name.removeprefix("./")
            parts = name.split("/")
            if name == ".":
                continue
            if any(part in {"", ".", ".."} for part in parts) or "\\" in name:
                raise ValueError(f"unsafe archive path: {member.name}")
            if (
                name not in {"rootfs", "metadata", "wheels"}
                and not (name.startswith("rootfs/usr/") or name.startswith("metadata/"))
                and name != "rootfs/usr"
                and not (
                    len(parts) == 2 and parts[0] == "wheels" and name.endswith(".whl")
                )
            ):
                raise ValueError(f"unexpected archive path: {member.name}")
            if name in seen:
                raise ValueError(f"duplicate archive path: {member.name}")
            seen.add(name)
            types[name] = member
            if name.startswith("wheels/") and not member.isfile():
                raise ValueError(f"invalid wheel member: {member.name}")
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
            if name in {
                "metadata/build_info.txt",
                "metadata/runtime-packages.txt",
                "metadata/python-requirements.txt",
            }:
                if not member.isfile() or member.size > 65536:
                    raise ValueError(f"invalid archive metadata: {name}")
                metadata_text[name] = (
                    contents.extractfile(member).read().decode("utf-8")
                )
    for line in metadata_text.get("metadata/build_info.txt", "").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            if key in info:
                raise ValueError(f"duplicate build metadata: {key}")
            info[key] = value
    if info.get("archive_format") == "mfnavis-indi-binary-v2":
        required.update(
            {
                "wheels",
                "metadata/runtime-packages.txt",
                "metadata/python-requirements.txt",
            }
        )
        if not any(name.startswith("wheels/pyindi_client-") for name in seen):
            raise ValueError("missing PyIndi wheel")
        if not any(name.startswith("wheels/indiweb-") for name in seen):
            raise ValueError("missing INDI Web Manager wheel")
        if "wheels" in types and not types["wheels"].isdir():
            raise ValueError("invalid wheel directory")
        for name, pattern in (
            ("metadata/runtime-packages.txt", r"[a-z0-9][a-z0-9+.-]*"),
            ("metadata/python-requirements.txt", r"[a-zA-Z0-9_.-]+==[a-zA-Z0-9_.+!-]+"),
        ):
            lines = metadata_text.get(name, "").splitlines()
            if not lines or any(not re.fullmatch(pattern, line) for line in lines):
                raise ValueError(f"invalid dependency list: {name}")
    if not required.issubset(seen):
        raise ValueError(f"missing required archive members: {sorted(required - seen)}")
    if not types["rootfs/usr"].isdir() or not types["metadata/build_info.txt"].isfile():
        raise ValueError("invalid archive rootfs or build_info type")
    if any(path.startswith(f"{link}/") for link in symlinks for path in seen):
        raise ValueError("archive member is nested below a symlink")
    for link, target in symlinks.items():
        if posixpath.join(posixpath.dirname(link), target) not in seen:
            raise ValueError(f"archive symlink target is missing: {link}")
    return info


def verify_platform(info, codename, machine, python_version, soabi):
    archive_format = info.get("archive_format")
    if archive_format in {"mfnavis-indi-binary-v1", "mf-pifinder-indi-binary-v1"}:
        expected = ("bookworm", "aarch64", "3.11")
        actual = (codename, machine, python_version)
        if actual != expected or info.get("machine") != "aarch64":
            raise ValueError(f"Bookworm archive requires {expected}; host is {actual}")
    elif archive_format == "mfnavis-indi-binary-v2":
        expected = tuple(
            info.get(key)
            for key in ("os_codename", "machine", "python_version", "python_soabi")
        )
        actual = (codename, machine, python_version, soabi)
        if expected != actual or info.get("python_payload") != "wheels":
            raise ValueError(
                f"archive platform mismatch: archive={expected}, host={actual}"
            )
    else:
        raise ValueError(f"unsupported archive format: {archive_format}")


def host_codename():
    for line in Path("/etc/os-release").read_text().splitlines():
        key, _, value = line.partition("=")
        if key == "VERSION_CODENAME":
            return value.strip("\"'")
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("checksum_file", type=Path)
    parser.add_argument("--check-host", action="store_true")
    args = parser.parse_args()
    try:
        verify_checksum(args.archive, args.checksum_file)
        info = verify_members(args.archive)
        if args.check_host:
            verify_platform(
                info,
                host_codename(),
                platform.machine(),
                f"{sys.version_info.major}.{sys.version_info.minor}",
                sysconfig.get_config_var("SOABI"),
            )
    except (OSError, ValueError, tarfile.TarError, IndexError) as exc:
        print(f"INDI archive verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"INDI archive verified: {args.archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
