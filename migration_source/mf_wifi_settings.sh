echo "Installing Wi-Fi settings support"

mfnavis_prepare_wpa_supplicant_config
mfnavis_prepare_apsta_nat_config
mfnavis_prepare_sta_band_config
sudo python3 "${MFNAVIS_REPO_DIR}/scripts/import_initial_wifi_networks.py"
