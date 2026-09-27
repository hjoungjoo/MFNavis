#!/usr/bin/env python3
"""Disk preflight and recoverable snapshots for INDI archive installation."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


RESERVE = 256 * 1024**2
CONFIG_PATHS = (
    "etc/ld.so.cache",
    "etc/systemd/system/indiwebmanager.service",
    "etc/systemd/system/multi-user.target.wants/indiwebmanager.service",
    "etc/chrony/chrony.conf",
)


def existing_parent(path):
    while not path.exists():
        path = path.parent
    return path


def check_space(requirements):
    """Add requirements when staging, system and virtualenv share a filesystem."""
    devices = {}
    for path, size in requirements:
        path = existing_parent(Path(path))
        device = path.stat().st_dev
        previous = devices.get(device, (path, RESERVE))
        devices[device] = (path, previous[1] + size)
    for path, needed in devices.values():
        free = shutil.disk_usage(path).free
        if free < needed:
            raise ValueError(
                f"insufficient disk space at {path}: need {needed} bytes, available {free}"
            )


def extraction_preflight(archive, stage, target):
    expanded = native = 0
    with tarfile.open(archive) as contents:
        for member in contents:
            if member.isfile():
                expanded += member.size
                if member.name.removeprefix("./").startswith("rootfs/"):
                    native += member.size
    check_space(((stage, expanded), (target, native)))


def check_destination(root, relative, directory=False):
    path = root / relative
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f"installation parent is a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"installation parent is not a directory: {parent}")
    if directory and path.is_symlink():
        raise ValueError(f"installation directory is a symlink: {path}")
    if path.exists() and path.is_dir() != directory and not path.is_symlink():
        raise ValueError(f"installation path has incompatible type: {path}")


def snapshot(rootfs, backup, target, venv=None, check_only=False):
    target = target.resolve()
    paths = set(CONFIG_PATHS)
    native_bytes = 0
    for source in rootfs.rglob("*"):
        relative = str(source.relative_to(rootfs))
        check_destination(target, relative, source.is_dir() and not source.is_symlink())
        paths.add(relative)
        if source.is_file() and not source.is_symlink():
            native_bytes += source.stat().st_size
    venv_relative = None
    venv_bytes = 0
    if venv:
        venv = venv.resolve()
        venv_relative = str(venv.relative_to(target))
        paths.add(venv_relative)
        for path in venv.rglob("*"):
            paths.add(str(path.relative_to(target)))
            if path.is_file() and not path.is_symlink():
                venv_bytes += path.stat().st_size
    existing = []
    missing = []
    backup_bytes = 0
    for relative in sorted(paths):
        path = target / relative
        if path.exists() or path.is_symlink():
            existing.append(relative)
            if path.is_file() and not path.is_symlink():
                backup_bytes += path.stat().st_size
        else:
            missing.append(relative)
    requirements = [(backup, backup_bytes), (target, native_bytes)]
    if venv:
        # pip may briefly hold both old and replacement package files.
        requirements.append((venv, venv_bytes))
    check_space(requirements)
    if check_only:
        return
    backup.mkdir(parents=True, exist_ok=True)
    file_list = backup / "files.list"
    file_list.write_bytes(b"".join(os.fsencode(p) + b"\0" for p in existing))
    subprocess.run(
        [
            "tar",
            "-C",
            str(target),
            "--no-recursion",
            "--null",
            "-T",
            str(file_list),
            "-cpf",
            str(backup / "previous.tar"),
        ],
        check=True,
    )
    (backup / "state.json").write_text(
        json.dumps(
            {
                "target": str(target),
                "existing": existing,
                "missing": missing,
                "venv": venv_relative,
            }
        )
    )
    print(f"INDI rollback snapshot ready: {backup}", flush=True)


def remove_new_path(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        # Keep unrelated files created by another process in a new directory.
        try:
            path.rmdir()
        except OSError:
            if not any(path.iterdir()):
                raise


def rollback(backup):
    state = json.loads((backup / "state.json").read_text())
    target = Path(state["target"])
    remove = set(state["missing"])
    if state["venv"]:
        venv = target / state["venv"]
        before = set(state["existing"])
        remove.update(
            str(p.relative_to(target))
            for p in venv.rglob("*")
            if str(p.relative_to(target)) not in before
        )
    for relative in sorted(remove, key=lambda p: (p.count("/"), p), reverse=True):
        remove_new_path(target / relative)
    subprocess.run(
        [
            "tar",
            "-C",
            str(target),
            "--keep-directory-symlink",
            "--no-overwrite-dir",
            "-xpf",
            str(backup / "previous.tar"),
        ],
        check=True,
    )
    print(
        "INDI native files, Python environment and configuration restored.", flush=True
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    space = sub.add_parser("space")
    space.add_argument("directory", type=Path)
    space.add_argument("bytes", type=int)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("archive", type=Path)
    preflight.add_argument("stage", type=Path)
    preflight.add_argument("--target", type=Path, default=Path("/"))
    save = sub.add_parser("snapshot")
    save.add_argument("rootfs", type=Path)
    save.add_argument("backup", type=Path)
    save.add_argument("--target", type=Path, default=Path("/"))
    save.add_argument("--venv", type=Path)
    save.add_argument("--check-only", action="store_true")
    restore = sub.add_parser("rollback")
    restore.add_argument("backup", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "space":
            check_space(((args.directory, args.bytes),))
        elif args.command == "preflight":
            extraction_preflight(args.archive, args.stage, args.target)
        elif args.command == "snapshot":
            snapshot(args.rootfs, args.backup, args.target, args.venv, args.check_only)
        else:
            rollback(args.backup)
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        tarfile.TarError,
    ) as exc:
        print(f"INDI installation safety check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
