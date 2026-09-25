MFNAVIS_REPO_DIR="${MFNAVIS_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "${MFNAVIS_REPO_DIR}/mfnavis_paths.sh"

# GPSD
sudo apt install -y gpsd
sudo dpkg-reconfigure -plow gpsd
sudo cp "${MFNAVIS_REPO_DIR}/pi_config_files/gpsd.conf" /etc/default/gpsd

# PWM
BOOT_CONFIG="$(mfnavis_boot_config_path)"
sudo sed -zi '/dtoverlay=pwm,pin=13,func=4\n/!s/$/\ndtoverlay=pwm,pin=13,func=4\n/' "${BOOT_CONFIG}"

# Uart for GPS
sudo sed -zi '/dtoverlay=uart3\n/!s/$/\ndtoverlay=uart3\n/' "${BOOT_CONFIG}"

# Migrate DB
if [ -f "${MFNAVIS_REPO_DIR}/astro_data/observations.db" ]
then
    echo "Migrating astro_data DB"
    python -c "from PiFinder import setup;setup.create_logging_tables();"
    sed \
        -e "s|__MFNAVIS_REPO_DIR__|${MFNAVIS_REPO_DIR}|g" \
        -e "s|__MFNAVIS_DATA_DIR__|${MFNAVIS_DATA_DIR}|g" \
        "${MFNAVIS_REPO_DIR}/migrate_db.sql" | sqlite3
    rm "${MFNAVIS_REPO_DIR}/astro_data/observations.db"
fi

# Migrate Config files
if ! [ -f "${MFNAVIS_DATA_DIR}/config.json" ] && [ -f "${MFNAVIS_REPO_DIR}/config.json" ]
then
    echo "Migrating config.json"
    mv "${MFNAVIS_REPO_DIR}/config.json" "${MFNAVIS_DATA_DIR}/config.json"
fi

# The full post-update path has already migrated existing service definitions.
# Only create missing units; do not discard installed command-line overrides.
if ! systemctl cat mfnavis.service >/dev/null 2>&1; then
    mfnavis_render_config "${MFNAVIS_REPO_DIR}/pi_config_files/mfnavis.service" /lib/systemd/system/mfnavis.service
fi
if ! systemctl cat mfnavis_splash.service >/dev/null 2>&1; then
    mfnavis_render_config "${MFNAVIS_REPO_DIR}/pi_config_files/mfnavis_splash.service" /lib/systemd/system/mfnavis_splash.service
fi
sudo systemctl daemon-reload
sudo systemctl enable mfnavis mfnavis_splash

# allow the PiFinder service user to adjust network config without exposing
# saved Wi-Fi credentials to every local user
mfnavis_prepare_wpa_supplicant_config

# DONE
echo "Post Update Complete"
