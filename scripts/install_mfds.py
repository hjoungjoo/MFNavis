#!/usr/bin/env python3
"""Install a hash-pinned MFDS release without Git checkout or compilation."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

MAX_ARCHIVE = 64 * 1024**2
MAX_EXPANDED = 128 * 1024**2


def load_lock(path):
    data = json.loads(Path(path).read_text())
    if data.get("schema") != 1 or not re.fullmatch(
        r"\d+\.\d+\.\d+", data.get("version", "")
    ):
        raise ValueError("Invalid MFDS lock schema/version")
    if not re.fullmatch(r"[0-9a-f]{40}", data.get("source_commit", "")):
        raise ValueError("Invalid MFDS source identity")
    prefix = f"https://github.com/hjoungjoo/MFDS/releases/download/v{data['version']}/"
    for arch in ("aarch64", "x86_64"):
        asset = data["assets"][f"linux-{arch}"]
        expected = f"MFDS-{data['version']}-linux-{arch}.tar.gz"
        if asset["url"] != prefix + expected or not re.fullmatch(
            r"[0-9a-f]{64}", asset["sha256"]
        ):
            raise ValueError("Invalid MFDS asset URL/checksum")
        if not re.fullmatch(r"[0-9a-f]{64}", asset.get("manifest_sha256", "")):
            raise ValueError("Invalid MFDS manifest checksum")
    return data


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_package(root, lock, platform_key, execute=True):
    if digest(root / "PACKAGE.json") != lock["assets"][platform_key]["manifest_sha256"]:
        raise ValueError("MFDS package manifest hash differs from lock")
    manifest = json.loads((root / "PACKAGE.json").read_text())
    for key, value in (
        ("schema", 1),
        ("version", lock["version"]),
        ("source_commit", lock["source_commit"]),
        ("platform", platform_key),
        ("abi", 1),
    ):
        if manifest.get(key) != value:
            raise ValueError(f"MFDS package {key} differs from lock")
    if (root / "VERSION").read_text().strip() != lock["version"]:
        raise ValueError("MFDS VERSION differs from lock")
    for name, expected in manifest["files"].items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError("Unsafe MFDS manifest path")
        file = root / name
        if file.is_symlink() or not file.is_file() or digest(file) != expected:
            raise ValueError(f"MFDS package file mismatch: {name}")
    if execute:
        actual = subprocess.check_output(
            [str(root / "build/mf_detect_star_server"), "--version"],
            text=True,
            timeout=5,
        ).strip()
        if actual != f"MFDS {lock['version']}":
            raise ValueError("MFDS executable version differs from lock")
    return manifest


def extract(archive, directory):
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        total = 0
        seen = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                not member.isfile()
                or path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] != "MFDS"
                or "\\" in member.name
                or member.name in seen
            ):
                raise ValueError("Unsafe/duplicate MFDS archive entry")
            seen.add(member.name)
            total += member.size
            if total > MAX_EXPANDED or len(seen) > 2000:
                raise ValueError("MFDS archive exceeds limits")
        for member in members:
            target = directory / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    return directory / "MFDS"


def install(repo, archive=None):
    repo = Path(repo).resolve()
    lock = load_lock(repo / "deployment/mfds.lock.json")
    key = f"linux-{platform.machine()}"
    if platform.system() != "Linux" or key not in lock["assets"]:
        raise RuntimeError(
            f"Unsupported MFDS platform: {platform.system()} {platform.machine()}"
        )
    libc, libc_version = platform.libc_ver()
    if libc != "glibc" or tuple(map(int, libc_version.split("."))) < (2, 36):
        raise RuntimeError("MFDS binary requires glibc >= 2.36")
    asset = lock["assets"][key]
    cache = repo / "python/.mfds"
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / "install.lock").open("w") as mutex:
        fcntl.flock(mutex, fcntl.LOCK_EX)
        target = cache / asset["sha256"]
        if target.exists():
            verify_package(target, lock, key)
        else:
            with tempfile.TemporaryDirectory(prefix="stage-", dir=cache) as temporary:
                stage = Path(temporary)
                download = stage / "asset.tar.gz"
                if archive is not None:
                    shutil.copyfile(archive, download)
                else:
                    with urllib.request.urlopen(
                        asset["url"], timeout=60
                    ) as response, download.open("wb") as output:
                        size = 0
                        while block := response.read(1024 * 1024):
                            size += len(block)
                            if size > MAX_ARCHIVE:
                                raise ValueError("MFDS download exceeds limit")
                            output.write(block)
                if (
                    download.stat().st_size > MAX_ARCHIVE
                    or digest(download) != asset["sha256"]
                ):
                    raise ValueError("MFDS archive SHA-256 mismatch")
                unpacked = extract(download, stage)
                verify_package(unpacked, lock, key)
                unpacked.rename(target)
        current = repo / "python/MFDS"
        # Source-to-binary migration is staged explicitly, never silently remove
        # a checkout that could contain user edits or a developer build.
        if current.exists() and not current.is_symlink():
            raise RuntimeError(
                "MFDS source checkout remains: stop service and move it out before binary installation"
            )
        temporary_link = cache / "activate"
        temporary_link.unlink(missing_ok=True)
        temporary_link.symlink_to(os.path.relpath(target, current.parent))
        os.replace(temporary_link, current)
        print(f"MFDS {lock['version']} ({key}) installed from verified release")
        return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--archive", type=Path, help="Offline archive; pinned hash still required"
    )
    args = parser.parse_args()
    install(args.repo, args.archive)
