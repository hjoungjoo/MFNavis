"""A failed restore must preserve the complete original user-data set."""

import os
from pathlib import Path
import zipfile

import pytest

from PiFinder import userdata_backup

pytestmark = pytest.mark.unit


@pytest.fixture
def backup(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.json").write_bytes(b"original-config")
    (data / "observations.db").write_bytes(b"original-db")
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("config.json", b"replacement-config")
        output.writestr("obslists/new.txt", b"new-list")
        output.writestr("observations.db", b"replacement-db")
    return data, archive


def assert_original(data):
    assert (data / "config.json").read_bytes() == b"original-config"
    assert (data / "observations.db").read_bytes() == b"original-db"
    assert not (data / "obslists").exists()


def test_later_crc_failure_leaves_all_original_files(backup):
    data, archive = backup
    content = archive.read_bytes().replace(b"replacement-db", b"corrupt-data!!")
    assert content != archive.read_bytes()
    archive.write_bytes(content)
    with pytest.raises(zipfile.BadZipFile):
        userdata_backup.restore_backup(archive, data)
    assert_original(data)


def test_later_install_failure_rolls_back_files_and_new_directories(
    backup, monkeypatch
):
    data, archive = backup
    replace = os.replace

    def fail_database_install(source, target):
        if (
            Path(source).name.startswith("new-")
            and Path(target).name == "observations.db"
        ):
            raise OSError("simulated installation failure")
        return replace(source, target)

    monkeypatch.setattr(userdata_backup.os, "replace", fail_database_install)
    with pytest.raises(OSError, match="installation failure"):
        userdata_backup.restore_backup(archive, data)
    assert_original(data)


def test_duplicate_targets_are_rejected_before_writing(backup):
    data, archive = backup
    with zipfile.ZipFile(archive, "a") as output:
        output.writestr("home/user/MFNavis_data/config.json", b"duplicate")
    with pytest.raises(ValueError, match="Duplicate"):
        userdata_backup.restore_backup(archive, data)
    assert_original(data)


def test_successful_restore_installs_every_member(backup):
    data, archive = backup
    userdata_backup.restore_backup(archive, data)
    assert (data / "config.json").read_bytes() == b"replacement-config"
    assert (data / "observations.db").read_bytes() == b"replacement-db"
    assert (data / "obslists/new.txt").read_bytes() == b"new-list"
