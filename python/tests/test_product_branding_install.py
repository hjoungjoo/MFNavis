"""Exercise service migration and rollback without touching the host system."""

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def migration(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "product_migration", REPO / "scripts/apply_product_branding.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def rooted(value):
        path = Path(value)
        if path.is_relative_to(tmp_path):
            return path
        return tmp_path / str(path).lstrip("/") if path.is_absolute() else path

    monkeypatch.setattr(module, "Path", rooted)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module, "network_plan", lambda: [])
    commands = []

    def run(*args, check=True):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, "enabled\n", "")

    monkeypatch.setattr(module, "run", run)
    system = rooted("/etc/systemd/system")
    system.mkdir(parents=True)
    old = system / "pifinder.service"
    old.write_text(
        "[Unit]\nDescription=PiFinder\n[Service]\n"
        "ExecStart=/custom/python -m PiFinder.main --camera debug\n"
        "[Install]\nWantedBy=multi-user.target\n"
    )
    monkeypatch.setattr(sys, "argv", ["branding", "--apply", "--services-only"])
    return module, system, commands


def test_migration_preserves_runtime_and_legacy_alias_and_is_idempotent(migration):
    module, system, commands = migration
    module.main()
    new = system / "mfnavis.service"
    assert "Description=MFNavis" in new.read_text()
    assert "ExecStart=/custom/python -m PiFinder.main --camera debug" in new.read_text()
    assert "Alias=pifinder.service" in new.read_text()
    assert (system / "pifinder.service").resolve() == new
    assert ("systemctl", "enable", "mfnavis.service") in commands
    assert ("systemctl", "start", "mfnavis.service") in commands
    commands.clear()
    module.main()
    assert not commands  # No duplicate backup, restart, or network change.


def test_failed_start_restores_original_unit(migration, monkeypatch):
    module, system, commands = migration
    old = system / "pifinder.service"
    original = old.read_text()
    run = module.run

    def fail_start(*args, check=True):
        if args == ("systemctl", "start", "mfnavis.service"):
            raise subprocess.CalledProcessError(1, args)
        return run(*args, check=check)

    monkeypatch.setattr(module, "run", fail_start)
    with pytest.raises(subprocess.CalledProcessError):
        module.main()
    assert not old.is_symlink()
    assert old.read_text() == original
    assert not (system / "mfnavis.service").exists()
    assert ("systemctl", "start", "pifinder.service") in commands


def test_gps_only_operation_leaves_main_service_untouched(migration, monkeypatch):
    module, system, commands = migration
    monkeypatch.setattr(
        sys,
        "argv",
        ["branding", "--apply", "--services-only", "--unit", "pifinder_gps_time_sync"],
    )
    module.main()
    assert not (system / "pifinder.service").is_symlink()
    assert not commands


def test_optional_networkmanager_absent(migration, monkeypatch):
    # Load the real function, which was replaced in the migration fixture.
    spec = importlib.util.spec_from_file_location(
        "network_migration", REPO / "scripts/apply_product_branding.py"
    )
    network_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(network_module)
    monkeypatch.setattr(network_module.shutil, "which", lambda name: None)
    assert network_module.network_plan() == []
