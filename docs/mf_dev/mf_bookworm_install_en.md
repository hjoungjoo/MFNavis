# MF_PiFinder Bookworm 64-bit Installation Manual

> Historical Bookworm installation record. Current installations use
> [MFNavis Trixie 64-bit](mf_trixie_install_en.md). The procedures and
> device state below describe the earlier PiFinder installation.

This document records the installation procedure used to install the
brickbots/PiFinder `release` branch on a Raspberry Pi Compute Module 5 (CM5)
running Raspberry Pi OS Bookworm 64-bit. It is based on CM5 hardware testing and
is used as the baseline install document for the `mf_pifinder` Pi4/Pi5/CM5
compatibility work.

For board profiles and automatic defaults when installing the `mf_pifinder`
branch across Raspberry Pi 4, Raspberry Pi 5, and CM5, see
`docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md`.

The official PiFinder documentation recommends using the distributed image for
normal stable use, and treats direct installation mainly as a procedure for
image builders and developers. The official direct-install instructions are
also written for Raspberry Pi OS Legacy Bullseye. On CM5 Bookworm, the
following differences matter:

- The boot config file is `/boot/firmware/config.txt`, not `/boot/config.txt`.
- Python is 3.11, and global `pip` installs require `--break-system-packages`.
- Bookworm uses NetworkManager by default. PiFinder's Wi-Fi/AP switching
  scripts assume the older `dhcpcd`, `wpa_supplicant`, `hostapd`, and
  `dnsmasq` model.
- The repository Nox configuration prefers Python 3.9, but `noxfile.py`
  falls back to the running interpreter when 3.9 is absent, so plain
  `nox -s <session>` works on Bookworm's 3.11 (the old `--force-python 3.11`
  advice is no longer needed).

## Wireless Keyboard Power Key

Versions of `pifinder_setup.sh` and `pifinder_post_update.sh` containing this
change automatically disable the power-off key on the XING WEI 2.4G USB
keyboard (USB ID `1915:1025`). Installation also works with the keyboard
disconnected; the mapping applies on subsequent hotplug and boot. Other keys,
including sleep/wake, the Pi's onboard power button, and menu shutdown are
unchanged. This is a device-specific mapping, not a blanket keyboard policy.

For the manual installation below, or to apply only this setting to an existing
device, run from a checkout containing this change:

```bash
bash scripts/install_keyboard_power_ignore.sh
```

The helper uses sudo when needed, installs
`pi_config_files/90-pifinder-keyboard-power-ignore.hwdb` into `/etc/udev/hwdb.d/`,
rebuilds the database, and reapplies the mapping to the connected receiver.
It is repeatable and does not restart PiFinder or logind. To undo it, remove
only `/etc/udev/hwdb.d/90-pifinder-keyboard-power-ignore.hwdb`, run
`sudo systemd-hwdb update`, and reconnect the keyboard. A subsequent install
or update will apply the setting again.

## Current Installation State On This Device

- Source directory: `/home/pifinder/PiFinder`
  - This device was installed with the OS user `pifinder`.
  - New installs may use any unique username and hostname.
- Branch: `release`
- Submodules: initialized
- Python runtime/development dependencies: installed
- Data directory: `/home/pifinder/PiFinder_data`
- systemd services: `pifinder`, `cedar_detect`, and `pifinder_splash` enabled
- CM5 boot config: PiFinder SPI/I2C/PWM/UART settings added to
  `/boot/firmware/config.txt`
- To protect the remote SSH connection, automatic startup for `dhcpcd`,
  `dnsmasq`, and `hostapd` is disabled
- Bookworm compatibility patch: added `PiFinder.boot_config` and changed camera
  switching/display code so PiFinder prefers `/boot/firmware/config.txt`
- CM5/Pi 5 SPI compatibility patch: OLED/LCD display initialization now
  auto-selects the available SPI device when `/dev/spidev0.0` is absent and
  only `/dev/spidev10.0` exists
- CM5/Pi 5 UART note: `dtoverlay=uart3` uses GPIO8/9 on Pi 5-class hardware and
  conflicts with the SSD1351 OLED `CS=GPIO8/CE0` wiring. On this board,
  `uart3` is disabled and GPS UART uses GPIO4/5 via `dtoverlay=uart2-pi5`.
- IMX462 camera: Bookworm firmware includes `imx462.dtbo`, so the dedicated
  overlay is used. When connected to `CAM0` on the CM5 IO board, the `cam0`
  parameter is required. When connected to `CAM1`, use the default overlay
  without `cam0`.

A reboot is required for boot overlays and user group changes to fully take
effect. If you are connected remotely, reboot only after every other check is
finished.

## Installation For Regular Users

This procedure is for users who want to run PiFinder without editing source
code. On CM5 Bookworm, avoid running the official install script as-is; split
the work into the steps below instead.

### 1. Prepare The Base OS

1. Install Raspberry Pi OS Bookworm 64-bit.
2. Create the username and hostname with any unique names you want. If several
   PiFinders may be nearby, use distinct names such as `scope-a` and `scope-b`.
3. Configure SSH and Wi-Fi in Raspberry Pi Imager before first boot. The mDNS
   address will be `<hostname>.local`.
4. After first login, confirm that the current network connection is stable.

```bash
hostname -I
nmcli device status

export PI_USER="$(id -un)"
export PI_HOME="$(getent passwd "$PI_USER" | cut -d: -f6)"
export PF_REPO="$PI_HOME/PiFinder"
export PF_DATA="$PI_HOME/PiFinder_data"
```

### 2. Clone The Source

```bash
cd "$PI_HOME"
git clone --recursive --branch release https://github.com/brickbots/PiFinder.git
```

If the repository already exists, update it as follows.

```bash
cd "$PF_REPO"
git fetch --all
git checkout release
git pull
git submodule update --init --recursive
```

### 3. Install Debian Packages

During remote work, it is safer to temporarily prevent services from
auto-starting while packages are installed. Use `policy-rc.d` for that.

```bash
sudo bash -c '
set -e
trap "rm -f /usr/sbin/policy-rc.d" EXIT
printf "%s\n" "#!/bin/sh" "exit 101" > /usr/sbin/policy-rc.d
chmod 755 /usr/sbin/policy-rc.d
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  git python3-pip python3-venv python3-dev build-essential pkg-config \
  samba samba-common-bin dnsmasq hostapd dhcpcd gpsd \
  libinput10 libcap2-bin libjpeg-dev zlib1g-dev libfreetype6-dev \
  liblcms2-dev libopenjp2-7-dev libtiff-dev libffi-dev libssl-dev \
  python3-picamera2 rpicam-apps i2c-tools spi-tools
'
```

### 4. Install Python Runtime Dependencies

```bash
cd "$PF_REPO"
sudo python3 -m pip install --break-system-packages -r python/requirements.txt
```

### 5. Create Data Directories And Install Services

```bash
source "$PF_REPO/pifinder_paths.sh"

sudo install -d -o "$PI_USER" -g "$PI_USER" -m 755 \
  "$PF_DATA" \
  "$PF_DATA/captures" \
  "$PF_DATA/obslists" \
  "$PF_DATA/screenshots" \
  "$PF_DATA/solver_debug_dumps" \
  "$PF_DATA/logs" \
  "$PF_DATA/migrations"

printf Client > "$PF_REPO/wifi_status.txt"

sudo cp "$PF_REPO/pi_config_files/gpsd.conf" /etc/default/gpsd
pifinder_render_config "$PF_REPO/pi_config_files/smb.conf" /etc/samba/smb.conf
pifinder_render_config "$PF_REPO/pi_config_files/pifinder.service" /lib/systemd/system/pifinder.service
pifinder_render_config "$PF_REPO/pi_config_files/pifinder_splash.service" /lib/systemd/system/pifinder_splash.service
pifinder_render_config "$PF_REPO/pi_config_files/cedar_detect.service" /lib/systemd/system/cedar_detect.service

sudo systemctl daemon-reload
sudo systemctl enable cedar_detect pifinder pifinder_splash smbd nmbd gpsd.socket
```

Also confirm hardware access groups.

```bash
for group in input video render dialout gpio i2c spi; do
  getent group "$group" >/dev/null && sudo usermod -aG "$group" "$PI_USER"
done
```

### 6. Configure CM5 Bookworm Boot Settings

Check that the following lines exist in `/boot/firmware/config.txt`; add them if
they are missing.

```bash
sudo cp -a /boot/firmware/config.txt /boot/firmware/config.txt.before-pifinder
for line in \
  "dtparam=spi=on" \
  "dtparam=i2c_arm=on" \
  "dtparam=i2c_arm_baudrate=10000" \
  "dtoverlay=pwm,pin=13,func=4" \
  "dtoverlay=uart2-pi5"
do
  grep -qxF "$line" /boot/firmware/config.txt || echo "$line" | sudo tee -a /boot/firmware/config.txt
done
```

When using an IMX462 camera, disable camera auto-detection and add the dedicated
overlay. For the `CAM0` connector on the CM5 IO board:

```bash
sudo sed -i 's/^camera_auto_detect=1/#camera_auto_detect=1/' /boot/firmware/config.txt
grep -qxF "dtoverlay=imx462,cam0,clock-frequency=74250000" /boot/firmware/config.txt || \
  echo "dtoverlay=imx462,cam0,clock-frequency=74250000" | sudo tee -a /boot/firmware/config.txt
```

When using the `CAM1` connector, omit `cam0` and use:

```text
dtoverlay=imx462,clock-frequency=74250000
```

### 7. Network Caution

If remote SSH depends on Wi-Fi, do not immediately enable `dhcpcd`, `dnsmasq`,
or `hostapd`. On this device, Wi-Fi is managed by NetworkManager, so keeping the
PiFinder AP services disabled is safer.

```bash
sudo systemctl disable dhcpcd dnsmasq hostapd
```

If you want PiFinder's Wi-Fi/AP switching menu to behave like the official
image, first make sure you have a local console, wired LAN, or physical access
for recovery.

### 8. Reboot Last

Reboot only after all other work is complete.

```bash
sudo reboot
```

After reconnecting, verify the services.

```bash
systemctl status pifinder cedar_detect pifinder_splash
journalctl -u pifinder -n 100 --no-pager
```

Optionally download catalog images. This can take a long time and requires more
than about 5 GB of storage.

```bash
cd "$PF_REPO/python"
python3 -m PiFinder.get_images
```

## Installation For Developers

Developers should perform the regular-user installation first, then add the
development dependencies and testing tools below.

### 1. Install Development Dependencies

```bash
cd "$PF_REPO"
sudo python3 -m pip install --break-system-packages -r python/requirements_dev.txt
```

### 2. Configure Forks And Remotes

If you want to push to your own GitHub fork, make your fork `origin` and keep
the upstream repository as `upstream`.

```bash
cd "$PF_REPO"
git remote rename origin upstream
git remote add origin git@github.com:<YOUR_ID>/PiFinder.git
git fetch --all
```

If you only need read access, keeping the current `origin` is fine.

### 3. Run Tests On Bookworm

The recommended setup is a venv with the project's pinned tool versions
(ruff/mypy/pytest etc.), matching the CLAUDE.md development flow; Bookworm
has no 3.9, so use the system 3.11.

```bash
cd "$PF_REPO/python"
python3 -m venv .venv
source .venv/bin/activate
# On a pifinder_setup.sh install /tmp is a 256M tmpfs, which pip's temp
# files can overflow — point them at disk:
TMPDIR=/var/tmp pip install -r requirements.txt -r requirements_dev.txt

nox -s lint format type_hints smoke_tests   # or individual sessions
nox -s docs                                 # build the manual; one warning fails it
pytest -m smoke
```

`requirements_dev.txt` references `docs/source/requirements.txt`, so that one
install also brings in the Sphinx toolchain (Sphinx, the RTD theme, the
mermaid extension). They are the same pins Read the Docs uses, so a local
build matches what gets published.

Run `nox -s docs` after touching `docs/source/*.rst`. It catches broken
cross-references (`:ref:`), substitutions (`|v3_docs|` and friends) and image
paths — which matters most after applying an upstream doc change only in
part. Output lands in `docs/build/html/index.html` and is gitignored.

`noxfile.py` prefers Python 3.9 but falls back to the running interpreter
when 3.9 is absent, so `nox -s <session>` works as-is inside the 3.11 venv;
the old `--force-python 3.11` advice is no longer needed. For a quick check
without a venv, running the system python3 directly is still fine:

```bash
python3 -m ruff check PiFinder tests
python3 -m pytest -m smoke
```

### 4. Run And Debug From The Command Line

Running the service and a manual process at the same time can make both
processes contend for the same hardware. Stop the services before a manual run.

```bash
sudo systemctl stop pifinder cedar_detect
```

Run on real PiFinder hardware:

```bash
cd "$PF_REPO/python"
python3 -m PiFinder.main -x
```

For UI/catalog development without hardware, use fake hardware options:

```bash
cd "$PF_REPO/python"
python3 -m PiFinder.main -fh -k local --camera debug --display pg_128 -x
```

If you need to run the Cedar detect server separately, start it in another
terminal.

```bash
"$PF_REPO/bin/cedar-detect-server-aarch64" -p 50551
```

### 5. Apply Code Changes While Running As A Service

After editing Python code, restart the services to load the new code.

```bash
sudo systemctl restart cedar_detect pifinder
```

Changes to boot configuration, user groups, camera overlays, or the network
stack require a reboot. If you are connected remotely, do that only at the end.

## Verification Checklist

- `python3 -m PiFinder.main -h` prints help.
- `python3 -m pytest -m smoke` passes.
- `/boot/firmware/config.txt` contains the PiFinder overlays.
- `id pifinder` shows `input`, `video`, `render`, `dialout`, `gpio`, `i2c`,
  and `spi`.
- `systemctl is-enabled pifinder cedar_detect pifinder_splash` prints
  `enabled`.
- During remote Wi-Fi access, `dhcpcd`, `dnsmasq`, and `hostapd` do not
  auto-start.

## Peripheral Connection Order

Whenever possible, power off the device, connect peripherals one at a time, and
check the following items after boot.

1. OLED/LCD And Keypad

   ```bash
   ls /dev/spidev*
   sudo systemctl restart pifinder_splash pifinder
   journalctl -u pifinder -b -n 80 --no-pager
   ```

   On CM5, seeing only `/dev/spidev10.0` can be normal. If `pinctrl get 8`
   reports `TXD3`, then `dtoverlay=uart3` has taken the OLED CS pin. Disable
   `uart3` in `/boot/firmware/config.txt` and reboot.

2. IMU (BNO055)

   ```bash
   i2cdetect -y 1
   sudo systemctl restart pifinder
   journalctl -u pifinder -b -n 100 --no-pager
   ```

   The default address is `0x28`. When the `No I2C device at address: 0x28` log
   disappears, the IMU is being detected.

3. Camera

   ```bash
   rpicam-hello --list-cameras
   sudo systemctl stop pifinder
   rpicam-still -n -t 2000 -o /tmp/imx462-test.jpg
   sudo systemctl start pifinder
   journalctl -u pifinder -b -n 120 --no-pager
   ```

   With no camera, the reference output is `No cameras available!`. After
   connecting the camera, that message should disappear and the camera model
   should be listed.

   If IMX462 appears as `imx290`, or if you see `Error writing reg 0x303a:
   -121`, `Failed to queue buffer`, or `Remote I/O error`, the camera was
   detected but stream startup failed. Check that the camera line in
   `/boot/firmware/config.txt` matches the physical port. For `CAM0` on the CM5
   IO board, use `dtoverlay=imx462,cam0,clock-frequency=74250000`. For `CAM1`,
   use `dtoverlay=imx462,clock-frequency=74250000`. Then check CSI cable
   orientation, camera power, I2C pull-ups, and whether the module is 2-lane or
   4-lane.

4. GPS

   ```bash
   gpspipe -r -n 5
   journalctl -u gpsd -b -n 80 --no-pager
   ```

   For UART GPS, choose the actual wired port from `GPS Settings > GPS Port` in
   PiFinder. This CM5 build uses `/dev/ttyAMA2`; typical PiFinder builds often use
   `/dev/ttyAMA1`. When the port or baud rate changes, PiFinder updates
   `/etc/default/gpsd` `DEVICES` and `GPSD_OPTIONS`, then restarts gpsd.

## References

- PiFinder repository: https://github.com/brickbots/PiFinder
- PiFinder Software Setup: https://pifinder.readthedocs.io/en/release/software.html
- PiFinder Contributors Guide: https://pifinder.readthedocs.io/en/release/dev_guide.html
