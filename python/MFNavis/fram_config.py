"""A0 settings synchronization using /config.json in the shared FRAM file store."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path

from PiFinder.board_config import A0_MODE

from PiFinder.fram_fs import CorruptFileError, FRAMFileSystem, FRAMStore, canonical

logger = logging.getLogger("FRAMConfig")

READY_FILE = "fram-config-ready.json"
CONFIG_FILE = "/config.json"


def open_store():
    from PiFinder.i2c_bus import get_i2c

    return FRAMStore(get_i2c())


def open_filesystem(runtime_dir, store=None):
    return FRAMFileSystem(
        store or open_store(), Path(runtime_dir) / "fram-storage.lock"
    )


def read_settings(filesystem):
    try:
        raw = filesystem.read_file(CONFIG_FILE)
    except (FileNotFoundError, CorruptFileError):
        return None
    try:
        settings = json.loads(raw)
        canonical(settings)
        return settings
    except (ValueError, TypeError, UnicodeError):
        return None


def atomic_json(path, settings):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(settings, handle, ensure_ascii=False, indent=4, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        tmp.unlink(missing_ok=True)


def _process_stamp(pid):
    # /proc stat's comm field may contain spaces; starttime is field 22.
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]


def disable(runtime_dir):
    (Path(runtime_dir) / READY_FILE).unlink(missing_ok=True)


def enabled(config_path, runtime_dir):
    try:
        marker = json.loads((Path(runtime_dir) / READY_FILE).read_text())
        return marker["config_path"] == str(Path(config_path).resolve()) and marker[
            "starttime"
        ] == _process_stamp(int(marker["pid"]))
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return False


def activate(config_path, runtime_dir):
    atomic_json(
        Path(runtime_dir) / READY_FILE,
        {
            "config_path": str(Path(config_path).resolve()),
            "pid": os.getpid(),
            "starttime": _process_stamp(os.getpid()),
        },
    )


@contextmanager
def config_lock(runtime_dir):
    directory = Path(runtime_dir)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "config.json.lock").open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def startup_sync(
    config_path, defaults_path, runtime_dir, *, seed_current=False, store=None
):
    with config_lock(runtime_dir):
        return _startup_sync(
            config_path,
            defaults_path,
            runtime_dir,
            seed_current=seed_current,
            store=store,
        )


def _startup_sync(
    config_path, defaults_path, runtime_dir, *, seed_current=False, store=None
):
    """Call once after actual A0 detection, before Config or worker startup.

    FRAM is authoritative on normal startup. Explicit first-install migration
    may seed the current file. No valid slot on normal startup means defaults.
    An I/O error raises without replacing config.json or enabling backup writes.
    """
    disable(runtime_dir)
    defaults = json.loads(Path(defaults_path).read_text())
    canonical(defaults)
    try:
        local = json.loads(Path(config_path).read_text())
        canonical(local)
    except (FileNotFoundError, ValueError, TypeError):
        local = None
    filesystem = open_filesystem(runtime_dir, store)
    backup = read_settings(filesystem)
    if seed_current:
        if local is None:
            raise ValueError("Cannot seed FRAM from invalid or missing config.json")
        settings = {**defaults, **local, "board_mode": A0_MODE}
        action = "seed_current"
    elif backup is None:
        settings = {**defaults, "board_mode": A0_MODE}
        action = "defaults"
    else:
        settings = {**backup, "board_mode": A0_MODE}
        action = "restored" if settings != local else "unchanged"
    # Preserve the prior SD file before replacement, including corrupt JSON.
    if local != settings and Path(config_path).exists():
        source = Path(config_path).read_bytes()
        recovery = Path(config_path).with_name(
            f"config.before-fram-{hashlib.sha256(source).hexdigest()[:12]}.json"
        )
        if not recovery.exists():
            with recovery.open("xb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(source)
                handle.flush()
                os.fsync(handle.fileno())
    saved = filesystem.write_file(CONFIG_FILE, canonical(settings))
    if local != settings:
        atomic_json(config_path, settings)
    activate(config_path, runtime_dir)
    logger.info(
        "FRAM configuration %s: generation=%s sha256=%s",
        action,
        saved["generation"],
        saved["sha256"],
    )
    return {
        "action": action,
        **saved,
        "settings": settings,
        "file_sha256": hashlib.sha256(canonical(settings)).hexdigest(),
    }


def backup_if_enabled(config_path, runtime_dir, settings, defaults_path):
    """Called under the shared config write lock, before publishing config.json."""
    if not enabled(config_path, runtime_dir):
        return
    if settings.get("board_mode") != A0_MODE:
        return
    defaults = json.loads(Path(defaults_path).read_text())
    snapshot = {**defaults, **settings, "board_mode": A0_MODE}
    open_filesystem(runtime_dir).write_file(CONFIG_FILE, canonical(snapshot))


def sync_restored_file(config_path, runtime_dir, defaults_path):
    """Archive restore must update FRAM before its caller requests a restart."""
    if enabled(config_path, runtime_dir):
        settings = json.loads(Path(config_path).read_text())
        canonical(settings)
        settings["board_mode"] = A0_MODE
        atomic_json(config_path, settings)
        backup_if_enabled(config_path, runtime_dir, settings, defaults_path)
