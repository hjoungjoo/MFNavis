import socket
import logging
import os
import zipfile
import tempfile

# For testing, use a directory structure that mimics the production setup
# but in a writable location. The server serves from /home/pifinder/PiFinder_data
# so we need to create a backup file that can be served from there.
# Since we can't write to /home/pifinder as a regular user, we'll use the current
# user's directory structure that mirrors the production layout.
from PiFinder import utils

_pifinder_data_dir = str(utils.data_dir)
os.makedirs(_pifinder_data_dir, exist_ok=True)
BACKUP_PATH = os.path.join(_pifinder_data_dir, "MFNavis_backup.zip")

logger = logging.getLogger("SysUtils.Fake")
ONSTEPX_DEVICE_NAME = "LX200 OnStepX"
LEGACY_ONSTEP_DEVICE_NAME = "LX200 OnStep"
ONSTEP_SERIAL_BAUD_RATES = (9600, 19200, 38400, 57600, 115200, 230400, 460800)
DEFAULT_ONSTEP_DEVICE_NAME = ONSTEPX_DEVICE_NAME
ONSTEP_CONNECTION_USB = "usb"
ONSTEP_CONNECTION_NETWORK = "network"
ONSTEP_SERIAL_AUTO_VALUE = "__auto__"
DEFAULT_ONSTEP_SERIAL_BAUD = 9600
DEFAULT_ONSTEP_NETWORK_PORT = 9999


def is_onstepx_device_name(device_name):
    return (device_name or "").strip().lower() == ONSTEPX_DEVICE_NAME.lower()


def is_onstep_family_device_name(device_name):
    return (device_name or "").strip().lower() in {
        ONSTEPX_DEVICE_NAME.lower(),
        LEGACY_ONSTEP_DEVICE_NAME.lower(),
    }


def ensure_uhid_loaded():
    return True


def pause_wifi_for_bt_pairing(safety_timeout=150):
    logger.info("FAKE SYS: pause_wifi_for_bt_pairing (no-op)")
    # Nothing was paused, so callers skip their resume path too.
    return False


def resume_wifi_after_bt_pairing():
    logger.info("FAKE SYS: resume_wifi_after_bt_pairing (no-op)")


def get_indi_profile_drivers(profile_name=None, profiles_db_path=None):
    return {"profile": "MF_PiFinder", "drivers": [DEFAULT_ONSTEP_DEVICE_NAME]}


def get_indi_profile_device_name(
    profile_name=None, fallback=DEFAULT_ONSTEP_DEVICE_NAME
):
    return DEFAULT_ONSTEP_DEVICE_NAME


def resolve_indi_device_name(device_name=None):
    return (device_name or "").strip() or get_indi_profile_device_name()


def list_onstep_serial_ports():
    return []


def discover_onstep_serial(**_kwargs):
    return {
        "ok": False,
        "state": "not_found",
        "candidate_count": 0,
        "verified_count": 0,
        "selected": None,
        "verified": [],
        "probable": [],
        "attempts": [],
    }


def is_local_indi_server_host(host):
    return str(host or "").strip().lower() in {
        "",
        "localhost",
        "localhost.localdomain",
        "127.0.0.1",
        "::1",
    }


def normalize_onstep_connection_config(values, source=""):
    if not isinstance(values, dict):
        return None
    connection_type = str(values.get("connection_type", "")).strip().lower()
    if connection_type not in {ONSTEP_CONNECTION_USB, ONSTEP_CONNECTION_NETWORK}:
        return None
    serial_port = str(values.get("serial_port", "") or "").strip()
    network_host = str(values.get("network_host", "") or "").strip()
    if connection_type == ONSTEP_CONNECTION_USB:
        try:
            serial_baud = int(values.get("serial_baud", DEFAULT_ONSTEP_SERIAL_BAUD))
        except (TypeError, ValueError):
            return None
        if (
            not serial_port.startswith("/dev/")
            or serial_baud not in ONSTEP_SERIAL_BAUD_RATES
        ):
            return None
        try:
            network_port = int(values.get("network_port", DEFAULT_ONSTEP_NETWORK_PORT))
        except (TypeError, ValueError):
            network_port = DEFAULT_ONSTEP_NETWORK_PORT
    else:
        try:
            network_port = int(values.get("network_port", DEFAULT_ONSTEP_NETWORK_PORT))
        except (TypeError, ValueError):
            return None
        if not network_host or not 1 <= network_port <= 65535:
            return None
        try:
            serial_baud = int(values.get("serial_baud", DEFAULT_ONSTEP_SERIAL_BAUD))
        except (TypeError, ValueError):
            serial_baud = DEFAULT_ONSTEP_SERIAL_BAUD
        if serial_baud not in ONSTEP_SERIAL_BAUD_RATES:
            serial_baud = DEFAULT_ONSTEP_SERIAL_BAUD
    return {
        "connection_type": connection_type,
        "serial_port": serial_port,
        "serial_baud": serial_baud,
        "network_host": network_host,
        "network_port": network_port,
        "source": source or str(values.get("source", "") or ""),
        "verified": bool(values.get("verified", False)),
    }


def parse_indi_onstep_connection_properties(properties, device_name=None):
    return None


def read_saved_indi_onstep_connection_config(device_name=None, config_path=None):
    return None


def onstep_connection_configs_match(left, right):
    left = normalize_onstep_connection_config(left)
    right = normalize_onstep_connection_config(right)
    if (
        left is None
        or right is None
        or left["connection_type"] != right["connection_type"]
    ):
        return False
    keys = (
        ("serial_port", "serial_baud")
        if left["connection_type"] == ONSTEP_CONNECTION_USB
        else ("network_host", "network_port")
    )
    return all(left[key] == right[key] for key in keys)


def onstep_connection_mirror_options(connection):
    connection = normalize_onstep_connection_config(connection)
    if connection is None:
        raise ValueError("Invalid OnStep connection configuration")
    if connection["connection_type"] == ONSTEP_CONNECTION_USB:
        return {
            "onstep_connection_type": ONSTEP_CONNECTION_USB,
            "onstep_serial_port": connection["serial_port"],
            "onstep_serial_baud": connection["serial_baud"],
        }
    return {
        "onstep_connection_type": ONSTEP_CONNECTION_NETWORK,
        "onstep_network_host": connection["network_host"],
        "onstep_network_port": connection["network_port"],
    }


def get_indi_onstep_properties(
    server_host="localhost",
    server_port=7624,
    device_name=None,
):
    device_name = resolve_indi_device_name(device_name)
    return {}


def apply_indi_onstep_connection(
    connection_type,
    serial_port="",
    serial_baud=9600,
    network_host="",
    network_port=9999,
    server_host="localhost",
    server_port=7624,
    device_name=None,
    save_config=True,
):
    device_name = resolve_indi_device_name(device_name)
    return {
        "ok": True,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "properties": [],
    }


def apply_indi_onstep_properties(
    properties,
    server_host="localhost",
    server_port=7624,
):
    return {
        "ok": True,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "properties": properties,
    }


def apply_indi_onstep_backlash(
    backlash_ra,
    backlash_de,
    server_host="localhost",
    server_port=7624,
    device_name=None,
):
    device_name = resolve_indi_device_name(device_name)
    return {
        "ok": True,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "properties": [
            f"{device_name}.Backlash.Backlash RA={int(backlash_ra)}",
            f"{device_name}.Backlash.Backlash DEC={int(backlash_de)}",
        ],
    }


def apply_indi_onstep_location_time(
    latitude=None,
    longitude=None,
    elevation=None,
    utc_datetime=None,
    utc_offset_hours=None,
    server_host="localhost",
    server_port=7624,
    device_name=None,
):
    device_name = resolve_indi_device_name(device_name)
    properties = []
    if latitude is not None and longitude is not None:
        properties.extend(
            [
                f"{device_name}.GEOGRAPHIC_COORD.LAT={float(latitude)}",
                f"{device_name}.GEOGRAPHIC_COORD.LONG={float(longitude)}",
            ]
        )
        if elevation is not None:
            properties.append(f"{device_name}.GEOGRAPHIC_COORD.ELEV={float(elevation)}")
    if utc_datetime is not None:
        properties.append(f"{device_name}.TIME_UTC.UTC={utc_datetime}")
        if utc_offset_hours is not None:
            properties.append(
                f"{device_name}.TIME_UTC.OFFSET={float(utc_offset_hours):.2f}"
            )
    return {
        "ok": True,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "properties": properties,
    }


def sync_onstep_location_time_exclusive(
    connection_type,
    latitude,
    longitude,
    utc_datetime,
    network_host="",
    network_port=9999,
    serial_port="",
    serial_baud=9600,
    server_host="localhost",
    server_port=7624,
    elevation=None,
):
    return {
        "ok": True,
        "commands": [],
        "responses": [],
        "stop_result": {"ok": True},
        "start_result": {"ok": True},
        "connect_result": {"ok": True},
        "elevation": elevation,
    }


def restart_indi_web_manager(timeout=30.0):
    return {
        "ok": True,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "service": "indiwebmanager.service",
    }


def connect_indi_onstep_driver(
    server_host="localhost",
    server_port=7624,
    device_name=None,
    wait_timeout=15.0,
):
    device_name = resolve_indi_device_name(device_name)
    return {
        "ok": True,
        "returncode": 0,
        "stdout": f"{device_name} already connected",
        "stderr": "",
        "properties": [f"{device_name}.CONNECTION.CONNECT=On"],
    }


class Network:
    """
    Provides wifi network info
    """

    def __init__(self):
        self.sta_dirty = False

    def populate_wifi_networks(self):
        """
        Parses wpa_supplicant.conf to get current config
        """
        pass

    def get_wifi_networks(self):
        return ""

    def move_wifi_network(self, network_id, direction):
        pass

    def apply_sta_changes(self):
        self.sta_dirty = False

    def connect_wifi_network(self, network_id, async_switch=True):
        return False, "FAKE SYS: connect_wifi_network (no-op)"

    def get_last_connect_result(self):
        return None

    def delete_wifi_network(self, network_id):
        """
        Immediately deletes a wifi network
        """
        pass

    def add_wifi_network(self, ssid, key_mgmt, psk=None):
        """
        Add a wifi network
        """
        pass

    def scan_wifi_networks(self):
        return []

    def get_ap_name(self):
        return "UNKN"

    def set_ap_name(self, ap_name):
        pass

    def get_ap_security(self):
        return "OPEN"

    def get_ap_password(self):
        return ""

    def set_ap_security(self, security, password):
        pass

    def get_ap_ip(self):
        return "10.10.10.1"

    def set_ap_ip(self, ap_ip):
        pass

    def get_apsta_internet_sharing(self):
        return False

    def set_apsta_internet_sharing(self, enabled):
        pass

    def get_sta_band_preference(self):
        return "auto"

    def set_sta_band_preference(self, preference):
        pass

    def get_ap_clients(self):
        return []

    def get_host_name(self):
        return socket.gethostname()

    def get_connected_ssid(self):
        """
        Returns the SSID of the connected wifi network or
        None if not connected or in AP mode
        """
        return "UNKN"

    def set_host_name(self, hostname):
        if hostname == self.get_host_name():
            return

    def wifi_mode(self):
        return "UNKN"

    def set_wifi_mode(self, mode):
        pass

    def local_ip(self):
        return "NONE"


def remove_backup():
    """
    Removes backup file
    """
    try:
        if os.path.exists(BACKUP_PATH):
            os.remove(BACKUP_PATH)
    except OSError:
        pass


def backup_userdata():
    """
    Back up userdata to a single zip file for later
    restore.  Returns the path to the zip file.

    Backs up:
        config.json
        observations.db
        obslist/*
    """
    remove_backup()

    # Use actual files from ~/PiFinder_data directory
    source_dir = _pifinder_data_dir

    # Create zip file with actual user data
    with zipfile.ZipFile(BACKUP_PATH, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Add config.json if it exists
        config_path = os.path.join(source_dir, "config.json")
        if os.path.exists(config_path):
            zipf.write(config_path, "home/pifinder/PiFinder_data/config.json")

        # Add observations.db if it exists
        db_path = os.path.join(source_dir, "observations.db")
        if os.path.exists(db_path):
            zipf.write(db_path, "home/pifinder/PiFinder_data/observations.db")

        # Add all files from obslists directory if it exists
        obslists_dir = os.path.join(source_dir, "obslists")
        if os.path.exists(obslists_dir):
            for filename in os.listdir(obslists_dir):
                file_path = os.path.join(obslists_dir, filename)
                if os.path.isfile(file_path):
                    zipf.write(
                        file_path, f"home/pifinder/PiFinder_data/obslists/{filename}"
                    )

    return BACKUP_PATH


def restore_userdata(zip_path):
    """
    Compliment to backup_userdata
    "restores" userdata

    For the fake version, this compares the zip contents
    with the current ~/PiFinder_data contents and throws
    an exception if they don't match.
    """
    import zipfile
    import filecmp

    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"Backup file not found: {zip_path}")

    # Extract zip to temporary directory for comparison
    with tempfile.TemporaryDirectory() as temp_dir:
        with zipfile.ZipFile(zip_path, "r") as zipf:
            # Extract all files
            zipf.extractall(temp_dir)

        # Compare extracted files with actual files in ~/PiFinder_data
        extracted_base = os.path.join(temp_dir, "home", "pifinder", "PiFinder_data")
        actual_base = _pifinder_data_dir

        if not os.path.exists(extracted_base):
            raise ValueError(
                "Invalid backup file: missing expected directory structure"
            )

        # Check each file that should exist
        files_to_check = ["config.json", "observations.db"]

        for filename in files_to_check:
            extracted_file = os.path.join(extracted_base, filename)
            actual_file = os.path.join(actual_base, filename)

            # If file exists in backup but not in actual directory
            if os.path.exists(extracted_file) and not os.path.exists(actual_file):
                raise ValueError(
                    f"Backup contains {filename} but it doesn't exist in {actual_base}"
                )

            # If file exists in both, compare contents
            if os.path.exists(extracted_file) and os.path.exists(actual_file):
                if not filecmp.cmp(extracted_file, actual_file, shallow=False):
                    raise ValueError(
                        f"Backup file {filename} differs from current version in {actual_base}"
                    )

        # Check obslists directory
        extracted_obslists = os.path.join(extracted_base, "obslists")
        actual_obslists = os.path.join(actual_base, "obslists")

        if os.path.exists(extracted_obslists):
            if not os.path.exists(actual_obslists):
                raise ValueError(
                    "Backup contains obslists directory but it doesn't exist in current data"
                )

            # Compare each file in obslists
            for filename in os.listdir(extracted_obslists):
                extracted_obslist = os.path.join(extracted_obslists, filename)
                actual_obslist = os.path.join(actual_obslists, filename)

                if os.path.isfile(extracted_obslist):
                    if not os.path.exists(actual_obslist):
                        raise ValueError(
                            f"Backup contains obslist {filename} but it doesn't exist in current obslists"
                        )

                    if not filecmp.cmp(
                        extracted_obslist, actual_obslist, shallow=False
                    ):
                        raise ValueError(
                            f"Backup obslist {filename} differs from current version"
                        )

        # If we get here, all files match
        logger.info("Restore validation successful: backup contents match current data")
        return True


def shutdown():
    """
    shuts down the Pi
    """
    logger.info("SYS: Initiating Shutdown")
    return True


def update_software():
    """
    Uses systemctl to git pull and then restart
    service
    """
    logger.info("SYS: Running update")
    return True


def restart_pifinder():
    """
    Uses systemctl to restart the PiFinder
    service
    """
    logger.info("SYS: Restarting MFNavis")
    return True


def restart_system():
    """
    Restarts the system
    """
    logger.info("SYS: Initiating System Restart")


def go_wifi_ap():
    logger.info("SYS: Switching to AP")
    return True


def go_wifi_cli():
    logger.info("SYS: Switching to Client")
    return True


def go_wifi_apsta():
    logger.info("SYS: Switching to AP+STA")
    return True


def verify_password(username, password):
    """
    Checks the provided password against the provided user
    password
    """
    return True


def change_password(username, current_password, new_password):
    """
    Changes the PiFinder User password
    """
    return False


def switch_cam_imx477() -> None:
    logger.info("SYS: Switching cam to imx477")
    logger.info('sh.sudo("python", "-m", "PiFinder.switch_camera", "imx477")')


def switch_cam_imx296() -> None:
    logger.info("SYS: Switching cam to imx296")
    logger.info('sh.sudo("python", "-m", "PiFinder.switch_camera", "imx296")')


def switch_cam_imx462() -> None:
    logger.info("SYS: Switching cam to imx462")
    logger.info('sh.sudo("python", "-m", "PiFinder.switch_camera", "imx462")')
