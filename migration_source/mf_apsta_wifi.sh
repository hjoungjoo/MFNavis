echo "Installing AP+STA Wi-Fi support"

sudo cp "${PIFINDER_REPO_DIR}"/pi_config_files/dhcpcd.* /etc
if [[ ! -f /etc/dnsmasq.conf ]]; then
    sudo cp "${PIFINDER_REPO_DIR}/pi_config_files/dnsmasq.conf" /etc/dnsmasq.conf
fi
if [[ ! -f /etc/hostapd/hostapd.conf ]]; then
    sudo install -d -m 755 /etc/hostapd
    sudo cp "${PIFINDER_REPO_DIR}/pi_config_files/hostapd.conf" /etc/hostapd/hostapd.conf
fi

pifinder_render_config \
    "${PIFINDER_REPO_DIR}/pi_config_files/mfnavis_apsta_prepare.service" \
    /lib/systemd/system/mfnavis_apsta_prepare.service
pifinder_render_config \
    "${PIFINDER_REPO_DIR}/pi_config_files/mfnavis_apsta_monitor.service" \
    /lib/systemd/system/mfnavis_apsta_monitor.service

sudo systemctl daemon-reload

if [[ "$(tr -d '\n' <"${PIFINDER_REPO_DIR}/wifi_status.txt" 2>/dev/null || true)" == "AP+STA" ]]; then
    sudo systemctl enable mfnavis_apsta_prepare
    sudo systemctl enable mfnavis_apsta_monitor
fi
