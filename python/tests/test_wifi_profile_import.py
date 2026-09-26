"""Netplan runtime profiles must survive in the application's saved list."""

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def importer(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "wifi_importer", ROOT / "scripts/import_initial_wifi_networks.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.WPA_PATH = tmp_path / "wpa_supplicant.conf"
    module.NM_DIR = tmp_path / "persistent"
    module.NM_RUNTIME_DIR = tmp_path / "runtime"
    module.BOOT_WPA_PATHS = []
    module.NM_DIR.mkdir()
    module.NM_RUNTIME_DIR.mkdir()
    monkeypatch.setattr(sys, "argv", ["importer", "--initial-only"])
    # main changes the process umask; contain it in tests.
    monkeypatch.setattr(module.os, "umask", lambda mask: None)
    return module


def write_profile(directory):
    (directory / "netplan-wlan0.nmconnection").write_text(
        "[wifi]\nssid=Observatory\n[wifi-security]\nkey-mgmt=wpa-psk\npsk=fixture-only\n"
    )


def test_imports_runtime_profile_and_credentials(importer):
    write_profile(importer.NM_RUNTIME_DIR)
    assert importer.main() == 0
    networks = importer.parse_wpa_networks(importer.WPA_PATH.read_text())
    assert networks == [
        {"ssid": "Observatory", "key_mgmt": "WPA-PSK", "psk": "fixture-only"}
    ]
    assert importer.WPA_PATH.with_suffix(".imported").exists()
    importer.main()
    assert len(importer.parse_wpa_networks(importer.WPA_PATH.read_text())) == 1


def test_missing_boot_profile_retries_when_networkmanager_ready(importer):
    importer.main()
    assert not importer.WPA_PATH.with_suffix(".imported").exists()
    write_profile(importer.NM_RUNTIME_DIR)
    importer.main()
    assert importer.parse_wpa_networks(importer.WPA_PATH.read_text())


def test_deleted_networks_are_not_resurrected_on_restart(importer):
    write_profile(importer.NM_RUNTIME_DIR)
    importer.main()
    importer.WPA_PATH.write_text("")
    importer.main()
    assert importer.WPA_PATH.read_text() == ""


def test_existing_saved_list_is_preserved(importer):
    write_profile(importer.NM_RUNTIME_DIR)
    saved = 'network={\nssid="Custom"\nkey_mgmt=NONE\n}\n'
    importer.WPA_PATH.write_text(saved)
    importer.main()
    assert importer.WPA_PATH.read_text() == saved


def test_persistent_and_runtime_profiles_are_deduplicated(importer):
    write_profile(importer.NM_DIR)
    write_profile(importer.NM_RUNTIME_DIR)
    importer.main()
    assert len(importer.parse_wpa_networks(importer.WPA_PATH.read_text())) == 1
