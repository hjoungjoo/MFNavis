from __future__ import annotations
from pathlib import Path

import PiFinder.i18n  # noqa: F401

from PiFinder.ui import menu_structure


REPO = Path(__file__).resolve().parents[2]


def _iter_menu_nodes(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_menu_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_menu_nodes(item)


def test_wifi_menu_includes_apsta_mode():
    wifi_entries = [
        node
        for node in _iter_menu_nodes(menu_structure.pifinder_menu)
        if node.get("name") == "WiFi Mode"
    ]

    assert len(wifi_entries) == 1
    values = [item["value"] for item in wifi_entries[0]["items"]]
    assert values == ["Client", "AP", "AP+STA"]
    callbacks = {item["value"]: item["callback"] for item in wifi_entries[0]["items"]}
    assert callbacks["AP+STA"] is menu_structure.callbacks.go_wifi_apsta


def test_network_page_includes_apsta_option():
    network_html = (REPO / "python/views/network.html").read_text()

    assert 'option value="AP+STA"' in network_html
    assert 'net.wifi_mode() == "AP+STA"' in network_html
    assert 'name="ap_security"' in network_html
    assert 'name="ap_password"' in network_html
    assert 'name="ap_ip"' in network_html
    assert 'name="apsta_share_internet"' in network_html
    assert 'name="sta_band_preference"' in network_html
    assert "Prefer 2.4 GHz" in network_html
    assert 'name="ssid_select"' in network_html
    assert "AP Connected Devices" in network_html
    assert "Lease only" in network_html


def test_apsta_system_files_target_virtual_ap_interface():
    dhcpcd = (REPO / "pi_config_files/dhcpcd.conf.apsta").read_text()
    prepare_service = (
        REPO / "pi_config_files/pifinder_apsta_prepare.service"
    ).read_text()
    monitor_service = (
        REPO / "pi_config_files/pifinder_apsta_monitor.service"
    ).read_text()
    manager = (REPO / "scripts/pifinder_apsta.sh").read_text()

    assert "interface uap0" in dhcpcd
    assert "static ip_address=10.10.10.1/24" in dhcpcd
    assert "Before=hostapd.service dnsmasq.service" in prepare_service
    assert (
        "ExecStart=/usr/bin/bash __PIFINDER_REPO_DIR__/scripts/pifinder_apsta.sh prepare"
        in prepare_service
    )
    assert (
        "ExecStart=/usr/bin/bash __PIFINDER_REPO_DIR__/scripts/pifinder_apsta.sh monitor"
        in monitor_service
    )
    assert 'AP_IFACE="${PIFINDER_AP_IFACE:-uap0}"' in manager
    assert "interface add" in manager
    assert "restart hostapd" in manager
    assert "wait_sta_channel" in manager
    assert "current_hostapd_channel" in manager
    assert "PIFINDER_APSTA_SHARE_INTERNET=1" in manager
    assert "add table ip" in manager
    assert "masquerade" in manager


def test_mode_switch_scripts_manage_apsta_services():
    switch_apsta = (REPO / "switch-apsta.sh").read_text()
    switch_ap = (REPO / "switch-ap.sh").read_text()
    switch_cli = (REPO / "switch-cli.sh").read_text()

    assert 'echo -n "AP+STA"' in switch_apsta
    assert "mfnavis_apsta_prepare" in switch_apsta
    assert "mfnavis_apsta_monitor" in switch_apsta
    assert 'pifinder_apsta.sh" cleanup' in switch_ap
    assert 'pifinder_apsta.sh" cleanup' in switch_cli


def test_wifi_profile_import_is_installed_by_setup_and_update():
    setup = (REPO / "pifinder_setup.sh").read_text()
    post_update = (REPO / "pifinder_post_update.sh").read_text()
    migration = (REPO / "migration_source/mf_wifi_settings.sh").read_text()
    paths = (REPO / "pifinder_paths.sh").read_text()

    assert "scripts/import_initial_wifi_networks.py" in setup
    assert "mf_wifi_settings" in post_update
    assert "scripts/import_initial_wifi_networks.py" in migration
    assert "pifinder_prepare_wpa_supplicant_config" in paths
    assert "pifinder_prepare_apsta_nat_config" in paths
    assert "pifinder_prepare_sta_band_config" in paths
    assert "PIFINDER_APSTA_SHARE_INTERNET=0" in paths
    assert "PIFINDER_STA_BAND=auto" in paths
    assert "chmod 600 /etc/wpa_supplicant/wpa_supplicant.conf" in paths


def test_wifi_credentials_are_not_made_world_readable():
    for path in [
        REPO / "pifinder_setup.sh",
        REPO / "pifinder_paths.sh",
        REPO / "pifinder_post_update.sh",
        *sorted((REPO / "migration_source").glob("*.sh")),
    ]:
        assert "chmod 666 /etc/wpa_supplicant" not in path.read_text()
