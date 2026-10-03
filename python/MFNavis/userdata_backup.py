"""Portable user-data archives with support for legacy absolute-path ZIPs."""

from pathlib import Path, PurePosixPath
import os
import shutil
import stat
import tempfile
import zipfile


def create_backup(data_dir, destination):
    data_dir, destination = Path(data_dir), Path(destination)
    files = [data_dir / "config.json", data_dir / "observations.db"]
    files.extend((data_dir / "obslists").glob("*"))
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if path.is_file():
                archive.write(path, path.relative_to(data_dir).as_posix())
    return str(destination)


def restore_backup(source, data_dir):
    root = Path(data_dir).resolve()
    with zipfile.ZipFile(source) as archive:
        entries = []
        targets = set()
        for info in archive.infolist():
            parts = PurePosixPath(info.filename).parts
            if ".." in parts or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Unsafe backup member")
            for marker in ("MFNavis_data", "PiFinder_data"):
                if marker in parts:
                    parts = parts[parts.index(marker) + 1 :]
                    break
            if info.is_dir():
                continue
            if not parts or not (
                parts in [("config.json",), ("observations.db",)]
                or (len(parts) > 1 and parts[0] == "obslists")
            ):
                raise ValueError(f"Unsupported backup member: {info.filename}")
            target = root.joinpath(*parts)
            if not target.resolve().is_relative_to(root):
                raise ValueError("Backup target escapes data directory")
            if target.is_symlink() or target.resolve() in targets:
                raise ValueError("Duplicate or symbolic-link backup target")
            targets.add(target.resolve())
            entries.append((info, target))

        # Keep staging on the destination filesystem so each replacement is atomic.
        root.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".mfnavis-restore-", dir=root.parent))
        cleanup = True
        installed = []
        created_dirs = []
        try:
            prepared = []
            for index, (info, target) in enumerate(entries):
                replacement = stage / f"new-{index}"
                with (
                    archive.open(info) as source_file,
                    replacement.open("wb") as output,
                ):
                    shutil.copyfileobj(source_file, output)
                replacement.chmod(0o600)
                previous = None
                if target.exists():
                    previous = stage / f"old-{index}"
                    shutil.copy2(target, previous)
                    shutil.copystat(target, replacement)
                prepared.append((target, replacement, previous))

            # Every member's CRC and every original copy are checked before mutation.
            try:
                for target, replacement, previous in prepared:
                    missing_dirs = []
                    parent = target.parent
                    while not parent.exists():
                        missing_dirs.append(parent)
                        parent = parent.parent
                    for directory in reversed(missing_dirs):
                        directory.mkdir()
                        created_dirs.append(directory)
                    os.replace(replacement, target)
                    installed.append((target, previous))
            except BaseException:
                rollback_errors = []
                for target, previous in reversed(installed):
                    try:
                        if previous is None:
                            target.unlink()
                        else:
                            os.replace(previous, target)
                    except OSError as exc:
                        rollback_errors.append(exc)
                for directory in reversed(created_dirs):
                    try:
                        directory.rmdir()
                    except OSError:
                        pass
                if rollback_errors:
                    cleanup = False
                    raise RuntimeError(
                        f"Backup rollback failed; recovery files kept at {stage}"
                    ) from rollback_errors[0]
                raise
        finally:
            if cleanup:
                shutil.rmtree(stage)
