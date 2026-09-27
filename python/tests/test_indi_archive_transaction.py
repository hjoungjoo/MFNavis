"""INDI installation failures must restore files without changing system dirs."""

import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.unit


@pytest.fixture
def transaction(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "indi_transaction", ROOT / "scripts/indi_archive_transaction.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Small artificial installations must also fit the device's 256 MiB /tmp.
    monkeypatch.setattr(module, "RESERVE", 1024 * 1024)
    return module


def test_disk_requirements_are_combined_on_shared_filesystem(
    tmp_path, monkeypatch, transaction
):
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _: shutil._ntuple_diskusage(1000, 0, transaction.RESERVE + 150),
    )
    with pytest.raises(ValueError, match="insufficient disk space"):
        transaction.check_space(((tmp_path, 100), (tmp_path, 100)))


def test_snapshot_restores_native_python_and_configuration(tmp_path, transaction):
    root = tmp_path / "system"
    payload = tmp_path / "rootfs"
    for tree in (root, payload):
        (tree / "usr/bin").mkdir(parents=True)
        (tree / "usr/bin/indiserver").write_text("old" if tree == root else "new")
    (payload / "usr/bin/indi_new").write_text("new driver")
    venv = root / "home/user/venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin/python").symlink_to("/usr/bin/python3")
    (venv / "old.py").write_text("old Python")
    config = root / "etc/systemd/system/indiwebmanager.service"
    config.parent.mkdir(parents=True)
    config.write_text("old service")
    watched = (root, root / "usr", root / "usr/bin")
    for path in watched:
        path.chmod(0o750)
    for path in (payload, payload / "usr", payload / "usr/bin"):
        path.chmod(0o775)
    backup = tmp_path / "rollback"
    transaction.snapshot(payload, backup, root, venv)
    archive = tmp_path / "payload.tar"
    subprocess.run(["tar", "-C", str(payload), "-cf", str(archive), "."], check=True)
    subprocess.run(
        [
            "tar",
            "-C",
            str(root),
            "--keep-directory-symlink",
            "--no-overwrite-dir",
            "-xpf",
            str(archive),
        ],
        check=True,
    )
    assert (root / "usr/bin/indiserver").read_text() == "new"
    assert all(path.stat().st_mode & 0o777 == 0o750 for path in watched)
    (venv / "old.py").unlink()
    (venv / "new.py").write_text("partial pip install")
    (venv / "new-package").mkdir()
    (venv / "new-package/file.py").write_text("new")
    config.write_text("new service")
    transaction.rollback(backup)
    assert (root / "usr/bin/indiserver").read_text() == "old"
    assert not (root / "usr/bin/indi_new").exists()
    assert (venv / "old.py").read_text() == "old Python"
    assert not (venv / "new.py").exists()
    assert not (venv / "new-package").exists()
    assert (venv / "bin/python").is_symlink()
    assert config.read_text() == "old service"
    assert all(path.stat().st_mode & 0o777 == 0o750 for path in watched)


def test_destination_parent_symlink_is_rejected_before_snapshot(tmp_path, transaction):
    root = tmp_path / "system"
    payload = tmp_path / "payload"
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "usr").mkdir(parents=True)
    (root / "usr/bin").symlink_to(outside)
    (payload / "usr/bin").mkdir(parents=True)
    (payload / "usr/bin/indiserver").write_text("new")
    with pytest.raises(ValueError, match="symlink"):
        transaction.snapshot(payload, tmp_path / "backup", root)
    assert not list(outside.iterdir())
    assert not (tmp_path / "backup").exists()
