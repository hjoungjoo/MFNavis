"""Portable user-data archives with support for legacy absolute-path ZIPs."""

from pathlib import Path, PurePosixPath
import stat
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
            entries.append((info, target))
        for info, target in entries:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
