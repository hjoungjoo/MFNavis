"""FRAM commit interruption, corruption, startup authority and config integration."""

import json
import random

import pytest

from PiFinder import fram_config as fc
from PiFinder import fram_fs as fs

pytestmark = pytest.mark.unit


class MemoryBus:
    def __init__(self):
        self.memory = bytearray(fs.SIZE)
        self.writes = 0
        self.fail_at = None
        self.fail_read = False
        self.is_locked = False

    def try_lock(self):
        assert not self.is_locked
        self.is_locked = True
        return True

    def unlock(self):
        assert self.is_locked
        self.is_locked = False

    def writeto_then_readfrom(self, addr, pointer, data):
        assert addr == 0x50 and len(pointer) == 2
        if self.fail_read:
            raise OSError("bus unavailable")
        offset = int.from_bytes(pointer, "big")
        data[:] = self.memory[offset : offset + len(data)]

    def writeto(self, addr, data):
        assert addr == 0x50
        self.writes += 1
        offset = int.from_bytes(data[:2], "big")
        payload = data[2:]
        if self.writes == self.fail_at:
            self.memory[offset : offset + len(payload) // 2] = payload[
                : len(payload) // 2
            ]
            raise OSError("power interrupted")
        self.memory[offset : offset + len(payload)] = payload


@pytest.fixture
def store():
    return fc.FRAMStore(MemoryBus())


@pytest.fixture
def paths(tmp_path):
    cfg = tmp_path / "config.json"
    defaults = tmp_path / "defaults.json"
    defaults.write_text(json.dumps({"language": "en", "camera_exp": 1000}))
    cfg.write_text(json.dumps({"language": "ko", "camera_exp": 9000}))
    return cfg, defaults, tmp_path / "runtime"


def test_round_trip_slots_hash_and_unchanged_does_not_write(store):
    a = store.save({"language": "한국어", "x": [1, True]})
    assert a["generation"] == 1 and a["slot"] == 0 and len(a["sha256"]) == 64
    count = store.bus.writes
    assert store.save(a["settings"]) == a
    assert store.bus.writes == count
    b = store.save({"language": "ko", "x": 2})
    assert b["generation"] == 2 and b["slot"] == 1
    assert store.latest() == b
    assert fs.decode_slot(bytes(store.bus.memory[:4096]))["settings"] == a["settings"]


def test_every_torn_write_preserves_previous_committed_copy(store):
    old = {"x": "old"}
    rng = random.Random(42)
    new = {"x": bytes(rng.randrange(256) for _ in range(1000)).hex()}
    store.save(old)
    baseline = bytes(store.bus.memory)
    store.bus.writes = 0
    store.save(new)
    count = store.bus.writes
    for failure in range(1, count + 1):
        bus = MemoryBus()
        bus.memory[:] = baseline
        bus.fail_at = failure
        interrupted = fc.FRAMStore(bus)
        with pytest.raises(OSError, match="power interrupted"):
            interrupted.save(new)
        assert interrupted.latest()["settings"] == old


@pytest.mark.parametrize("offset", [0, 8, 10, 17, 22, 30, fs.HEADER_SIZE + 2])
def test_corrupt_header_or_data_uses_older_valid_slot(store, offset):
    store.save({"x": "old"})
    store.save({"x": "new"})
    store.bus.memory[4096 + offset] ^= 0x80
    assert store.latest()["settings"] == {"x": "old"}


def test_capacity_failure_does_not_touch_existing_backup(store):
    store.save({"x": "original"})
    original = bytes(store.bus.memory)
    rng = random.Random(99)
    huge = {"x": bytes(rng.randrange(256) for _ in range(9000)).hex()}
    with pytest.raises(ValueError, match="capacity"):
        store.save(huge)
    assert bytes(store.bus.memory) == original


@pytest.mark.parametrize("broken", [False, True])
def test_valid_fram_overrides_different_or_corrupt_sd(store, paths, broken):
    cfg, _, runtime = paths
    store.save({"language": "ko", "camera_exp": 5000, "board_mode": "MFNavis_A0"})
    before = cfg.read_bytes()
    if broken:
        before = b"{damaged"
        cfg.write_bytes(before)
    result = fc.startup_sync(*paths, store=store)
    assert result["action"] == "restored"
    assert json.loads(cfg.read_text()) == result["settings"]
    assert list(cfg.parent.glob("config.before-fram-*.json"))[0].read_bytes() == before
    assert fc.enabled(cfg, runtime)
    stamp = cfg.stat().st_mtime_ns
    result = fc.startup_sync(*paths, store=store)
    assert result["action"] == "unchanged"
    assert cfg.stat().st_mtime_ns == stamp


def test_empty_fram_uses_defaults_not_existing_sd(store, paths):
    result = fc.startup_sync(*paths, store=store)
    assert result["action"] == "defaults"
    assert result["settings"] == {
        "language": "en",
        "camera_exp": 1000,
        "board_mode": "MFNavis_A0",
    }
    assert fc.read_settings(fc.open_filesystem(paths[2], store)) == json.loads(
        paths[0].read_text()
    )


def test_both_corrupt_slots_initialize_defaults(store, paths):
    store.save({"x": 1})
    store.save({"x": 2})
    store.bus.memory[30] ^= 1
    store.bus.memory[4096 + 30] ^= 1
    assert fc.startup_sync(*paths, store=store)["action"] == "defaults"


def test_explicit_initial_migration_preserves_current_settings(store, paths):
    result = fc.startup_sync(*paths, seed_current=True, store=store)
    assert result["action"] == "seed_current"
    assert result["settings"]["camera_exp"] == 9000
    assert result["settings"]["language"] == "ko"


def test_bus_failure_is_not_empty_backup(store, paths):
    original = paths[0].read_bytes()
    store.bus.fail_read = True
    with pytest.raises(OSError):
        fc.startup_sync(*paths, store=store)
    assert paths[0].read_bytes() == original
    assert not fc.enabled(paths[0], paths[2])


def test_stale_or_different_process_marker_does_not_enable_hardware(paths):
    cfg, _, runtime = paths
    fc.activate(cfg, runtime)
    assert fc.enabled(cfg, runtime)
    assert not fc.enabled(cfg.with_name("other.json"), runtime)
    marker = runtime / fc.READY_FILE
    data = json.loads(marker.read_text())
    data["starttime"] = "incorrect"
    marker.write_text(json.dumps(data))
    assert not fc.enabled(cfg, runtime)


@pytest.fixture
def live_config(paths, store, monkeypatch):
    from PiFinder import config

    cfg, _, runtime = paths
    monkeypatch.setattr(config.utils, "data_dir", cfg.parent)
    monkeypatch.setattr(config.utils, "runtime_dir", runtime)
    monkeypatch.setattr(fc, "open_store", lambda: store)
    fc.startup_sync(*paths, seed_current=True, store=store)
    return config.Config(), store, paths


def test_config_save_updates_fram_and_reload(live_config):
    from PiFinder import config

    cfg, store, paths = live_config
    cfg.set_option("camera_exp", 1234)
    assert fc.read_settings(fc.open_filesystem(paths[2], store))["camera_exp"] == 1234
    assert json.loads(paths[0].read_text())["camera_exp"] == 1234
    assert config.Config().get_option("camera_exp") == 1234
    assert (
        fc.read_settings(fc.open_filesystem(paths[2], store))["source_version"]
        == (json.loads(paths[0].read_text())["source_version"])
    )


def test_startup_source_version_migration_updates_fram_once(live_config):
    from PiFinder import config

    cfg, store, paths = live_config
    old = json.loads(paths[0].read_text())
    cfg.ensure_source_version()
    expected = {**old, "source_version": config.get_source_version()}
    assert json.loads(paths[0].read_text()) == expected
    snapshot = {**json.loads(cfg.default_file_path.read_text()), **expected}
    assert fc.read_settings(fc.open_filesystem(paths[2], store)) == snapshot
    writes = store.bus.writes
    cfg.ensure_source_version()
    assert store.bus.writes == writes
    assert fc.startup_sync(*paths, store=store)["settings"] == snapshot


def test_failed_fram_save_preserves_file_and_in_memory_settings(live_config):
    cfg, store, paths = live_config
    before = paths[0].read_bytes()
    old = cfg.get_option("camera_exp")
    store.bus.fail_at = store.bus.writes + 2
    with pytest.raises(OSError):
        cfg.set_option("camera_exp", 5555)
    assert paths[0].read_bytes() == before
    assert cfg.get_option("camera_exp") == old
    assert fc.read_settings(fc.open_filesystem(paths[2], store))["camera_exp"] == old


def test_legacy_saves_never_open_fram(paths, monkeypatch):
    from PiFinder import config

    monkeypatch.setattr(config.utils, "data_dir", paths[0].parent)
    monkeypatch.setattr(config.utils, "runtime_dir", paths[2])
    monkeypatch.setattr(fc, "open_store", lambda: pytest.fail("Legacy touched FRAM"))
    cfg = config.Config()
    cfg.set_option("camera_exp", 3333)
    assert json.loads(paths[0].read_text())["camera_exp"] == 3333


def test_archive_restore_updates_fram_before_restart(live_config, tmp_path):
    import zipfile
    from PiFinder import userdata_backup

    _, store, paths = live_config
    archive = tmp_path / "restore.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(
            "config.json", json.dumps({"camera_exp": 4321, "board_mode": "legacy"})
        )
    userdata_backup.restore_backup(archive, paths[0].parent)
    assert fc.read_settings(fc.open_filesystem(paths[2], store))["camera_exp"] == 4321
    assert json.loads(paths[0].read_text())["board_mode"] == "MFNavis_A0"
    assert fc.startup_sync(*paths, store=store)["settings"]["camera_exp"] == 4321


def test_archive_restore_rolls_back_when_fram_cannot_save(live_config, tmp_path):
    import zipfile
    from PiFinder import userdata_backup

    _, store, paths = live_config
    before = paths[0].read_bytes()
    archive = tmp_path / "restore.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("config.json", json.dumps({"camera_exp": 4321}))
    store.bus.fail_at = store.bus.writes + 2
    with pytest.raises(OSError):
        userdata_backup.restore_backup(archive, paths[0].parent)
    assert paths[0].read_bytes() == before
    assert fc.read_settings(fc.open_filesystem(paths[2], store))["camera_exp"] == 9000


def test_two_config_instances_merge_in_fram_as_well_as_sd(live_config):
    from PiFinder import config

    first, store, paths = live_config
    stale = config.Config()
    first.set_option("camera_exp", 5678)
    stale.set_option("language", "fr")
    assert fc.read_settings(fc.open_filesystem(paths[2], store))["camera_exp"] == 5678
    assert fc.read_settings(fc.open_filesystem(paths[2], store))["language"] == "fr"


def test_runtime_capacity_failure_preserves_local_and_backup(live_config):
    cfg, store, paths = live_config
    before = paths[0].read_bytes()
    memory = bytes(store.bus.memory)
    rng = random.Random(1)
    with pytest.raises(ValueError, match="capacity"):
        cfg.set_option(
            "large_value", bytes(rng.randrange(256) for _ in range(9000)).hex()
        )
    assert paths[0].read_bytes() == before
    assert bytes(store.bus.memory) == memory
    assert cfg.get_stored_option("large_value") is None


def test_bootstrap_legacy_never_synchronizes_fram(monkeypatch, tmp_path):
    from unittest.mock import Mock
    from PiFinder import main, keypad_led

    monkeypatch.setattr(main.utils, "runtime_dir", tmp_path)
    monkeypatch.setattr(main, "keypad_led", None)
    driver = Mock(spec=keypad_led.PWMKeypad)
    monkeypatch.setattr(keypad_led, "create_keypad_led", lambda: driver)
    sync = Mock()
    monkeypatch.setattr(fc, "startup_sync", sync)
    main.prepare_hardware_settings()
    sync.assert_not_called()
    assert main.keypad_led is driver


def test_bootstrap_a0_synchronizes_before_config_loading(monkeypatch, tmp_path):
    from unittest.mock import Mock
    from PiFinder import main, keypad_led

    monkeypatch.setattr(main.utils, "runtime_dir", tmp_path)
    monkeypatch.setattr(main, "keypad_led", None)
    driver = Mock(spec=keypad_led.AW9523Keypad)
    monkeypatch.setattr(keypad_led, "create_keypad_led", lambda: driver)
    sync = Mock()
    monkeypatch.setattr(fc, "startup_sync", sync)
    main.prepare_hardware_settings()
    sync.assert_called_once()
    assert main.keypad_led is driver


@pytest.fixture
def filesystem(store, tmp_path):
    return fs.FRAMFileSystem(store, tmp_path / "fram.lock")


def test_files_can_be_read_updated_listed_and_deleted_independently(filesystem):
    settings = b'{"camera_exp":1234}'
    payload = bytes(range(256))
    filesystem.write_file("/config.json", settings)
    filesystem.write_file("/calibration/imu.bin", payload)
    assert filesystem.read_file("/config.json") == settings
    assert filesystem.read_file("/calibration/imu.bin") == payload
    listing = filesystem.list_files()
    assert sorted(listing) == ["/calibration/imu.bin", "/config.json"]
    assert listing["/calibration/imu.bin"]["size"] == 256
    assert len(listing["/config.json"]["sha256"]) == 64
    filesystem.write_file("/calibration/imu.bin", b"new")
    assert filesystem.read_file("/config.json") == settings
    filesystem.delete_file("/calibration/imu.bin")
    assert list(filesystem.list_files()) == ["/config.json"]
    with pytest.raises(FileNotFoundError):
        filesystem.read_file("/calibration/imu.bin")
    stats = filesystem.stat()
    assert stats["physical_bytes"] == 8192
    assert (
        stats["payload_capacity"] == stats["packed_bytes"] + stats["free_packed_bytes"]
    )


@pytest.mark.parametrize(
    "name", ["relative", "/", "/../x", "/a/../x", "/a//b", "/a\x00b", "/" + "a" * 129]
)
def test_invalid_file_names_leave_directory_unchanged(filesystem, name):
    with pytest.raises(ValueError):
        filesystem.write_file(name, b"data")
    assert filesystem.list_files() == {}


def test_other_files_survive_config_defaults_and_updates(store, paths):
    files = fc.open_filesystem(paths[2], store)
    files.write_file("/calibration/imu.bin", b"keep this")
    result = fc.startup_sync(*paths, store=store)
    assert result["action"] == "defaults"
    assert files.read_file("/calibration/imu.bin") == b"keep this"
    assert files.read_file("/config.json") == fc.canonical(result["settings"])


def test_per_file_hash_failure_only_resets_config(store, paths):
    files = fc.open_filesystem(paths[2], store)
    files.write_file("/config.json", b'{"camera_exp":7000}')
    files.write_file("/calibration/imu.bin", b"preserve")
    directory = store.latest()["settings"]
    directory["files"]["/config.json"]["sha256"] = "0" * 64
    store.save(directory)  # valid bank hash, invalid per-file hash
    with pytest.raises(fs.CorruptFileError):
        files.read_file("/config.json")
    assert fc.startup_sync(*paths, store=store)["action"] == "defaults"
    assert files.read_file("/calibration/imu.bin") == b"preserve"


def test_out_of_space_keeps_all_existing_files(filesystem):
    filesystem.write_file("/config.json", b'{"keep":true}')
    original = bytes(filesystem.store.bus.memory)
    rng = random.Random(123)
    with pytest.raises(ValueError, match="capacity"):
        filesystem.write_file(
            "/huge.bin", bytes(rng.randrange(256) for _ in range(8192))
        )
    assert bytes(filesystem.store.bus.memory) == original
    assert list(filesystem.list_files()) == ["/config.json"]


def test_parallel_file_writers_preserve_both_files(filesystem):
    from concurrent.futures import ThreadPoolExecutor

    other = fs.FRAMFileSystem(filesystem.store, filesystem.lock_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(filesystem.write_file, "/a.bin", b"a" * 100),
            pool.submit(other.write_file, "/b.bin", b"b" * 100),
        ]
        for future in futures:
            future.result(timeout=5)
    assert filesystem.read_file("/a.bin") == b"a" * 100
    assert filesystem.read_file("/b.bin") == b"b" * 100


def test_unknown_filesystem_version_is_not_overwritten(store, paths):
    store.save({"format": "future-version", "files": {}})
    original = bytes(store.bus.memory)
    local = paths[0].read_bytes()
    with pytest.raises(ValueError, match="Unsupported"):
        fc.startup_sync(*paths, store=store)
    assert bytes(store.bus.memory) == original
    assert paths[0].read_bytes() == local
