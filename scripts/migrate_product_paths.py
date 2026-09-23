#!/usr/bin/env python3
"""Move standard product paths without changing the Linux login account.

Default is a read-only plan. --apply requires root, preserves legacy aliases,
backs up affected system configuration, and rolls back on ordinary failures.
Custom installation/data directories are not relocated.
"""

import argparse
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import shutil
import subprocess


def run(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check)


def path_moves(home, system=Path("/")):
    pairs = [
        (home / "PiFinder", home / "MFNavis"),
        (home / "PiFinder_data", home / "MFNavis_data"),
        (system / "dev/shm/pifinder", system / "dev/shm/mfnavis"),
        (system / "etc/pifinder_apsta_nat.conf", system / "etc/mfnavis_apsta_nat.conf"),
        (system / "etc/pifinder_sta_band.conf", system / "etc/mfnavis_sta_band.conf"),
    ]
    moves = []
    for old, new in pairs:
        if old.is_symlink():
            if old.resolve() != new.resolve():
                raise ValueError(f"Custom legacy symlink needs review: {old}")
            continue
        if not old.exists():
            continue
        if new.exists() or new.is_symlink():
            raise ValueError(f"Both paths exist; refusing to merge: {old}, {new}")
        if old.stat().st_dev != new.parent.stat().st_dev:
            raise ValueError(f"Cross-filesystem migration needs review: {old}")
        moves.append((old, new))
    return moves


def updated_text(text, home):
    # Replace longer data paths before their common repository prefix.
    for old, new in [
        (home / "PiFinder_data", home / "MFNavis_data"),
        (home / "PiFinder", home / "MFNavis"),
    ]:
        # Avoid changing unrelated paths such as PiFinder_test_data.

        text = re.sub(
            re.escape(str(old)) + r'(?=[/\s"\x27]|$)', lambda match: str(new), text
        )
    text = re.sub(r"/dev/shm/pifinder(?=[/\s\"\x27]|$)", "/dev/shm/mfnavis", text)
    if str(home / "MFNavis") in text:
        text = text.replace("-m PiFinder.", "-m MFNavis.")
        text = text.replace("/scripts/pifinder_apsta.sh", "/scripts/mfnavis_apsta.sh")
    return text


def config_changes(home, system=Path("/")):
    roots = [system / "etc/systemd/system", system / "lib/systemd/system"]
    paths = [system / "etc/samba/smb.conf"]
    for root in roots:
        paths.extend(root.glob("*.service"))
        paths.extend(root.glob("*.service.d/*.conf"))
    changes = []
    for path in sorted(set(paths)):
        if not path.is_file() or path.is_symlink():
            continue
        before = path.read_text()
        after = updated_text(before, home)
        if before != after:
            changes.append((path, before, after))
    return changes


def apply(home, moves, changes, backup):
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
    active = []
    units = set()
    for path, _, _ in changes:
        if path.name.endswith(".service"):
            units.add(path.name)
        elif path.parent.name.endswith(".service.d"):
            units.add(path.parent.name[:-2])
    if moves:
        units.update(
            {"mfnavis.service", "pifinder.service", "mfnavis_gps_time_sync.service"}
        )
    for unit in sorted(units):
        identity = run(
            "systemctl", "show", unit, "-p", "Id", "--value", check=False
        ).stdout.strip()
        if (
            identity
            and identity not in active
            and run(
                "systemctl", "is-active", "--quiet", identity, check=False
            ).returncode
            == 0
        ):
            active.append(identity)
    files = []
    for path, _, _ in changes:
        destination = backup / str(path).lstrip("/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        files.append({"path": str(path), "backup": str(destination)})
    (backup / "journal.json").write_text(
        json.dumps(
            {
                "home": str(home),
                "moves": [[str(a), str(b)] for a, b in moves],
                "files": files,
                "active_units": active,
            },
            indent=2,
        )
    )
    moved = []
    try:
        for unit in active:
            run("systemctl", "stop", unit)
        for old, new in moves:
            old.rename(new)
            moved.append((old, new))
            old.symlink_to(new.name)
        for path, _, after in changes:
            path.write_text(after)
        run("systemctl", "daemon-reload")
        for unit in active:
            run("systemctl", "start", unit)
            run("systemctl", "is-active", "--quiet", unit)
        samba = any(str(p).endswith("/samba/smb.conf") for p, _, _ in changes)
        if (
            samba
            and run("systemctl", "is-active", "--quiet", "smbd", check=False).returncode
            == 0
        ):
            run("systemctl", "reload", "smbd")
        (backup / "complete").touch()
    except BaseException:
        for unit in active:
            run("systemctl", "stop", unit, check=False)
        for path, before, _ in changes:
            path.write_text(before)
        for old, new in reversed(moved):
            if old.is_symlink():
                old.unlink()
            new.rename(old)
        run("systemctl", "daemon-reload", check=False)
        for unit in active:
            run("systemctl", "start", unit, check=False)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    home = args.home.resolve()
    if not home.is_dir() or home == Path("/"):
        parser.error("An existing user home is required")
    moves, changes = path_moves(home), config_changes(home)
    print(
        json.dumps(
            {
                "moves": [[str(a), str(b)] for a, b in moves],
                "config_files": [str(p) for p, _, _ in changes],
                "login_account": "unchanged",
            },
            indent=2,
        )
    )
    if not args.apply or not (moves or changes):
        return
    if os.geteuid() != 0:
        parser.error("--apply requires root")
    backup = args.backup or Path("/var/backups") / (
        "mfnavis-paths-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    apply(home, moves, changes, backup)
    print(f"MFNavis paths applied; rollback record: {backup}")


if __name__ == "__main__":
    main()
