"""Exercise relocations, collisions, rollback and legacy archive portability."""

import importlib.util
from pathlib import Path
import subprocess
import zipfile

import pytest

from PiFinder import utils
from PiFinder.userdata_backup import create_backup, restore_backup

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "path_migration", REPO / "scripts/migrate_product_paths.py"
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


@pytest.fixture
def installation(tmp_path, monkeypatch):
    home = tmp_path / "home/user"
    for folder in [
        home / "PiFinder",
        home / "PiFinder_data",
        tmp_path / "etc/systemd/system",
        tmp_path / "dev/shm",
    ]:
        folder.mkdir(parents=True)
    (home / "PiFinder_data/config.json").write_text('{"preserve": true}')
    unit = tmp_path / "etc/systemd/system/mfnavis.service"
    unit.write_text(
        f"[Service]\nWorkingDirectory={home}/PiFinder/python\nExecStart=/usr/bin/python -m PiFinder.main\n"
    )
    commands = []

    def run(*args, check=True):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, "mfnavis.service\n", "")

    monkeypatch.setattr(migration, "run", run)
    return home, unit, commands


def test_relocation_preserves_data_aliases_and_service_command(installation, tmp_path):
    home, unit, commands = installation
    migration.apply(
        home,
        migration.path_moves(home, tmp_path),
        migration.config_changes(home, tmp_path),
        tmp_path / "backup",
    )
    assert (home / "MFNavis_data/config.json").read_text() == '{"preserve": true}'
    assert (home / "PiFinder").resolve() == home / "MFNavis"
    assert (home / "PiFinder_data").resolve() == home / "MFNavis_data"
    assert "-m MFNavis.main" in unit.read_text()
    assert "MFNavis/python" in unit.read_text()
    assert migration.path_moves(home, tmp_path) == []
    assert migration.config_changes(home, tmp_path) == []
    assert ("systemctl", "start", "mfnavis.service") in commands


def test_failed_start_restores_paths_and_config(installation, tmp_path, monkeypatch):
    home, unit, _ = installation
    before = unit.read_bytes()
    run = migration.run

    def fail(*args, check=True):
        if args[:2] == ("systemctl", "start") and check:
            raise subprocess.CalledProcessError(1, args)
        return run(*args, check=check)

    monkeypatch.setattr(migration, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        migration.apply(
            home,
            migration.path_moves(home, tmp_path),
            migration.config_changes(home, tmp_path),
            tmp_path / "backup",
        )
    assert unit.read_bytes() == before
    assert not (home / "PiFinder_data").is_symlink()
    assert (home / "PiFinder_data/config.json").is_file()
    assert not (home / "MFNavis_data").exists()


def test_existing_destination_is_never_merged(installation, tmp_path):
    home, _, _ = installation
    (home / "MFNavis_data").mkdir()
    with pytest.raises(ValueError, match="Both paths exist"):
        migration.path_moves(home, tmp_path)
    assert (home / "PiFinder_data/config.json").is_file()


def test_unrelated_installation_paths_are_not_rewritten(tmp_path):
    text = f"{tmp_path}/PiFinder_test/python {tmp_path}/PiFinder_data_backup\n"
    assert migration.updated_text(text, tmp_path) == text


@pytest.mark.parametrize(
    "prefix", ["", "home/pifinder/PiFinder_data/", "home/other/MFNavis_data/"]
)
def test_old_and_new_backups_restore_into_current_data(tmp_path, prefix):
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as f:
        f.writestr(prefix + "config.json", '{"user":"keep"}')
        f.writestr(prefix + "obslists/list.txt", "target")
    destination = tmp_path / "MFNavis_data"
    restore_backup(archive, destination)
    assert (destination / "config.json").read_text() == '{"user":"keep"}'
    assert (destination / "obslists/list.txt").read_text() == "target"
    portable = tmp_path / "portable.zip"
    create_backup(destination, portable)
    with zipfile.ZipFile(portable) as f:
        assert set(f.namelist()) == {"config.json", "obslists/list.txt"}


def test_restore_rejects_escape_before_writing(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as f:
        f.writestr("config.json", "would replace")
        f.writestr("../escape", "bad")
    with pytest.raises(ValueError):
        restore_backup(archive, tmp_path / "data")
    assert not (tmp_path / "data/config.json").exists()


def test_data_default_and_override(tmp_path, monkeypatch):
    monkeypatch.delenv("MFNAVIS_DATA_DIR", raising=False)
    assert utils.resolve_data_dir(tmp_path) == tmp_path / "MFNavis_data"
    (tmp_path / "PiFinder_data").mkdir()
    assert utils.resolve_data_dir(tmp_path) == tmp_path / "MFNavis_data"
    (tmp_path / "MFNavis_data").mkdir()
    assert utils.resolve_data_dir(tmp_path) == tmp_path / "MFNavis_data"
    monkeypatch.setenv("MFNAVIS_DATA_DIR", str(tmp_path / "product-override"))
    assert utils.resolve_data_dir(tmp_path) == tmp_path / "product-override"
