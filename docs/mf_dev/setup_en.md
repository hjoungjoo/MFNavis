# MFNavis installation

Current baseline: Raspberry Pi OS Trixie 64-bit / Python 3.13.
The runtime uses `.venv-trixie`; development uses `.venv-dev-trixie`.
This English installation procedure is retained for users of the English README.
The consolidated development reference is [the topic index](README.md).

## Installation and first boot

[English](setup_en.md) | [한국어](setup_ko.md)

Updated: 2026-10-04. The installation baseline is Raspberry Pi OS Trixie
64-bit / Python 3.13 on Raspberry Pi 4, Pi 5, and CM5. The board profiles are
shared, but current Trixie hardware validation was performed on Raspberry Pi 5;
Pi 4 and CM5 require their own Trixie checks. Earlier Bookworm measurements
remain in the [historical installation record](../history/development/setup.md#mf_bookworm_install_ko).

### Prepare the OS

Use Raspberry Pi Imager to install **Raspberry Pi OS Trixie 64-bit**. Set a
username, a unique hostname, SSH, and Wi-Fi before first boot. Log in as that
user and confirm the OS, Python version, and network:

```bash
cat /etc/os-release
python3 --version
hostname -I
nmcli device status
```

Expect `VERSION_CODENAME=trixie` and Python 3.13. Installation uses that user's
`~/MFNavis` for code and `~/MFNavis_data` for settings and observations.
Configure custom data paths with `MFNAVIS_DATA_DIR=/absolute/path` and use the
same setting for subsequent setup and cache commands.

### Install or update MFNavis

Run the setup script as the target OS user, without `sudo`. It requests sudo
for package and service configuration. Install or update the Trixie-based
`main` branch with:

```bash
wget -O /tmp/mfnavis-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/main/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=main bash /tmp/mfnavis-setup.sh
```

**Fresh installations default to IMX462.** The ordinary setup command also
installs IMX678 dependencies, the DKMS driver, overlays, generic tuning and menu
permissions on Pi 5/CM5 Trixie. No camera installation options are required.

After installation, select `Settings > Advanced > Camera Type > IMX678 (Auto)`.
On CM5, this automatically selects the verified **CSI0 converter** (GPIO34/35,
four lanes, 74.25 MHz and the board power sequence), then reboots. Switching to
IMX462/IMX296/IMX477 and back preserves the converter configuration. Selecting
the already-active IMX678 does not reboot. Power off before changing hardware.

The following environment variables are optional administrative overrides.

| Option | Behavior |
| --- | --- |
| `MFNAVIS_CAMERA=keep` (default) | Preserve the existing camera; select IMX462 only when none is configured |
| `MFNAVIS_CAMERA=imx678-cm5-converter` | Install and select the CM5 CSI0 converter |
| `MFNAVIS_CAMERA=imx678` | Install and select IMX678; CM5 defaults to the CSI0 converter, saved wiring takes precedence |
| `MFNAVIS_CAMERA=imx462` / `imx296` / `imx477` | Explicitly select that sensor |
| `MFNAVIS_INSTALL_IMX678=auto` (default) | Prepare support on Pi 5/CM5 Trixie or when IMX678 is selected |
| `MFNAVIS_INSTALL_IMX678=true` | Request support on another system, subject to compatibility checks |
| `MFNAVIS_INSTALL_IMX678=false` | Skip support; rejected when IMX678 is the current/requested camera |

Omit `MFNAVIS_CAMERA` on reinstalls to retain the selected sensor and wiring.
Preparing support alone does not switch the camera. CM5's first IMX678 menu
selection defaults to the CSI0 converter; other boards use the generic CAM1,
two-lane, 24 MHz configuration. Previously saved custom IMX678 wiring is preserved.
Existing tuning files are preserved. The kernel header metapackage enables
future DKMS rebuilds; already-installed kernels of the same flavour are also
prepared before reboot. Missing headers or build failures stop installation.
Code-only updates remain code-only: use full setup or
`sudo bash scripts/install_imx678.sh --install` for driver updates.

For a published version, use the tagged-release procedure in the
[README](../../README.md#2-install-mfnavis-release-or-main) and check that tag's
OS requirements. A source update does not upgrade Bookworm to Trixie. Back up
`~/MFNavis_data` and local changes before preparing a new Trixie OS.

Existing checkouts must have no tracked changes and must be able to
fast-forward to the chosen branch or tag. `mfnavis_update.sh` handles code-only
updates; use full setup when dependencies, services, or OS configuration change.

The setup script:

- Installs OS packages and the MFDS binary package pinned in `deployment/mfds.lock.json`.
- Installs the required `avahi-daemon` package for `.local` access and enables
  automatic startup. Setup and reinstalls restart the service; setup stops if
  the service fails to start or its active-state check fails.
- Creates `.venv-trixie` with `--system-site-packages` and installs
  the pinned `python-libinput` wheel from piwheels before
  `python/requirements-trixie.txt`, avoiding its source package's Python 3.13
  build failure. Picamera2 and GPIO come from the OS; Pi 5
  uses `python3-rpi-lgpio` instead of the pip RPi.GPIO package.
- Selects and verifies the Trixie/aarch64/Python 3.13 INDI archive, then installs
  PyIndi and INDI Web Manager wheels into the same app environment. The archive
  and `.sha256` must be available; split `.part-*` files are reassembled.
- Configures `mfnavis.service`, `mfnavis_splash.service`, GPSD, hardware groups,
  board-specific boot settings, and device-management permissions.
- Imports initial NetworkManager/Netplan Wi-Fi profiles into MFNavis's network
  configuration and preserves existing Wi-Fi settings during reinstallation.

INDI archive installation is required by default; absence or ABI/checksum
mismatch stops setup before app Python installation and GPS/network changes.
Mount control remains disabled in the app until explicitly enabled.
See the [INDI archive options](#indi-archive-options) for an explicit installation
without INDI, custom archives, and driver development. MFDS runs as native
child workers and needs no separate Cedar service.

Fresh installations use **IMX462 Color with a measured manual focal length of
8.2409 mm**. The sky-measured Brown–Conrady calibration has `k1=-0.12` and
`k2=k3=p1=p2=0`. `default_config.json` includes the matching active profile,
lens key, and optical fingerprint. Keep all four focal-length decimals for
calibration lookup, even though the displayed value is about 8.24 mm.
The app loads these defaults on first startup; no separate calibration-file
copy is needed. Saved lens and calibration settings in
`~/MFNavis_data/config.json` retain precedence during reinstallation and
updates. For another camera or lens, use Lens → Auto (Measure) and
Distortion → Measure Sky to measure that optical combination.

### Check hardware and startup

The active boot config is `/boot/firmware/config.txt`. Follow the
[board connectivity](connectivity_ko.md):
Pi 4 uses `uart3` / `/dev/ttyAMA3`; Pi 5 and CM5 use `uart2-pi5` /
`/dev/ttyAMA2`. The latter avoids the OLED GPIO8/9 conflict. SPI display
selection supports `/dev/spidev0.0` and `/dev/spidev10.0`. On a CM5 IO board,
an IMX462 connected to CAM0 may require the `cam0` overlay parameter.

After setup completes, reboot to apply boot overlays and hardware groups:

```bash
sudo reboot
```

After reconnecting, check:

```bash
systemctl status mfnavis mfnavis_splash indiwebmanager gpsd gpsd.socket avahi-daemon --no-pager
journalctl -u mfnavis -b -n 100 --no-pager
~/MFNavis/.venv-trixie/bin/python -c 'import sys, PyIndi; print(sys.version)'
```

Use `http://<hostname>.local` for MFNavis and port `8624` for INDI Web Manager.
Check display/keypad, camera, GPS location/time, and network access before GoTo.
Download runtime and offline image caches with:

```bash
cd ~/MFNavis
python3 scripts/warm_mfnavis_caches.py
```

The command selects `.venv-trixie` automatically. Allow at least 6 GB for the
full POSS+SDSS cache; see the [offline cache guide](interfaces_ko.md).

### Development and documentation checks

From an installed checkout:

```bash
cd ~/MFNavis
bash scripts/setup_dev_trixie.sh
source scripts/activate_dev_trixie.sh
nox --no-venv
nox --no-venv -s docs
```

Activation selects `.venv-dev-trixie`, Python 3.13, and separate development
data/runtime directories, then changes to `python/`. Use
`requirements_dev-trixie.txt` and `requirements_docs-trixie.txt`. The
[Trixie development guide](setup_ko.md) explains INDI wheels,
GPIO handling, debugging, and isolated Nox sessions.

The default Nox run includes lint, formatting, type checks, smoke tests, the full
unit suite, and UI integration tests. Run it before pushing; a selected pytest
subset does not cover type errors or incompatible test doubles elsewhere.
GitHub's `Bookworm compatibility (Python 3.11)` job retains compatibility checks
and exposes each check as a separate step so the actual failure is visible.

### Validation scope

The user reported no major problems in the 2026-09-27 Trixie GoTo field test.
This is a field-test report, not a claim that every board or mount feature has
been validated. Detailed earlier checks and fixes are listed in the
[field reports](../mf_report/README.md), including serial Auto detection,
solve-failure fallback, Sync acknowledgements, and INDI limit settings.
The [2026-09-26 deployment record](../history/development/setup.md#TRIXIE_20260926_ko) preserves results and
limitations at that date; it does not describe the later field-test outcome.


## INDI archive options

Full setup requires a compatible archive by default. Set `MFNAVIS_INDI_ARCHIVE`
to select an archive by absolute path. An explicitly INDI-free installation uses:

```bash
MFNAVIS_INSTALL_INDI_ARCHIVE=false bash "$HOME/MFNavis/mfnavis_setup.sh"
```

To verify or install the current Trixie archive into the application's runtime environment:

```bash
cd ~/MFNavis
bash scripts/install_indi_mount_archive.sh \
  dist/mfnavis-indi-trixie-arm64-v2.2.3.1-current.tar.gz --verify-only
MFNAVIS_PYTHON="$PWD/.venv-trixie/bin/python" \
  bash scripts/install_indi_mount_archive.sh \
  dist/mfnavis-indi-trixie-arm64-v2.2.3.1-current.tar.gz
```

Split `.part-*` files and their `.sha256` checksum can be supplied together.
See [the Korean installation reference](setup_ko.md) for native driver development,
rollback and packaging, and [mount control](mount_control_ko.md) for connection and GoTo.
