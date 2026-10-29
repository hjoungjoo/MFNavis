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

**MFNavis_A0 keypad detection:** at startup, release GPIO12 reset and read
register `0x10` at I2C address `0x5B`. ID `0x23` selects the AW9523BTQR driver
and persists `"board_mode": "MFNavis_A0"` in `~/MFNavis_data/config.json`.
This uses the actual chip, not the CM5 model string. Reprobe on each startup;
unchanged modes do not rewrite the file. An absent chip selects and saves
`legacy` with the existing GPIO13 PWM, regardless of the previously saved mode.
Switching legacy → A0 → legacy requires no manual option or config deletion.
A missing ACK is retried three times. Bus faults, permission errors and timeouts
are not interpreted as absence: preserve the saved mode and disable illumination.

Detection lives in `python/MFNavis/keypad_led.py`; shared mode names and the
`get_board_mode(cfg)` accessor live in `python/MFNavis/board_config.py`.
Future A0-specific behavior should use that accessor, not infer a carrier from
the CPU model. Detection itself changes only `board_mode`. Legacy keeps the
existing settings; A0 uses the FRAM synchronization policy below. Power off before replacing
boards; identification runs on the next application startup.

**A0 IMU selection:** the same detected `board_mode` selects BNO086 at I2C1
address `0x4B` on A0, and BNO055 on legacy boards. Normal installation includes
`adafruit-circuitpython-bno08x==1.3.3`; no extra option is needed. Game Rotation
Vector uses a startup-only compass seed on A0. The initial magnetic field is
tilt-compensated using Game RV and several stable yaw offsets are averaged.
Magnetic reports and magnetic calibration are then disabled; a fixed world-yaw
offset preserves the initial reference while Game RV continues without a reset.
Acquisition is bounded to five seconds; invalid fields, stale readings or motion
fall back to relative orientation. Each app start or sensor reinitialization
reacquires the reference; it is not stored in FRAM/config.json. A0 always uses this
policy, preserving `imu_use_magnetometer` for legacy boards. Native axes and
`screen_direction` are retained. `/api/imu` reports
`heading_reference=startup_magnetic` and `startup_heading_status=acquired`, or
`relative`/`unavailable` on failure. After startup, `fusion_mode` is
`game_rotation_vector` and `uses_magnetometer` is false. This is approximate
magnetic north, not a true-north or precision alignment. Existing location/time
conversion supplies initial RA/Dec; plate-solve and alignment coordinates retain
priority.

**Installation and full updates:** normal setup and the full-update path in
`mfnavis_post_update.sh` share Python dependency installation. Trixie uses the
runtime `.venv-trixie`; Bookworm uses the selected runtime Python. Both IMU drivers
are verified through package metadata without importing GPIO drivers or requiring
connected sensors. A shared helper normalizes Pi 5/CM5 I2C1 to 400 kHz and retains
software I2C3 on earlier Pis. Full updates apply this and the GPIO12 AW9523 reset
reservation after legacy migrations. Camera/fan settings and user configuration
are preserved. Reboot when boot settings change. No A0 or IMU installation option
is needed; application startup detects the carrier and acquires its compass seed.

`mfnavis_update.sh` remains a code-only transactional updater. Releases adding
dependencies, including this IMU driver, stop before activation and direct the
user to normal `mfnavis_setup.sh` installation. Code-only updates do not mutate
packages or boot settings in the running environment.

BNO086 calibration uses sensor flash DCD, separate from the BNO055 offset file.
Automatic saving occurs once per run after all required report accuracies reach 3,
when enabled. Manual save waits for an acknowledgement; load reinitializes the
sensor to load its DCD (the existence of a previously saved DCD is not detectable).
On A0, the calibration-clear action resets **RAM calibration**, retaining flash
DCD, and reports `RAM cal reset; flash retained` in the console, matching
[CEVA's Clear DCD and Reset semantics](https://github.com/ceva-dsp/sh2/blob/master/sh2.c).
The adapter separates SHTP transmit sequences and control channels and processes
batched reports in arrival order. Missing reports for one second or repeated I/O
errors invalidate the IMU and trigger recovery; a failed A0 BNO086 never silently
selects BNO055.

The 2026-10-29 CM5/A0 check read product ID `10004563`, firmware `3.12.6`
(build 62). A 30-second run through the application's `Imu` entry point received
334 orientations without communication errors, ending at accuracy `(3,3,2,0)`
and tracking status 3 in the default relative mode. Earlier physical movement
tests confirmed rotation and settling. Flash erasure, absolute heading calibration
and telescope/camera axis alignment were not tested.

A subsequent hardware check on the same day confirmed startup compass acquisition
(`startup_magnetic` / `acquired`), followed by 308 orientations in 30 seconds without
errors. No magnetic reports arrived after the initial packet drain; only acceleration,
gyro, linear acceleration and Game RV reports remained active. The device report is
`MFNavis_data/test_data/bno086-20261029/startup-heading.json`.

No extra option or package is required. Setup reserves GPIO12 for reset with
`gpio=12=op,dl,pd`, and prepares only GPIO13 for legacy PWM using
`dtoverlay=pwm,pin=13,func=4`. A0 never starts PWM output. Old `pwm-2chan`
settings are removed; reboot after changing boot settings.

The chip uses I2C1 (SDA GPIO2, SCL GPIO3), address `0x5B` (AD0/AD1 HIGH),
and active-low reset GPIO12 (header pin 32). DIM0..15 correspond to LED1..16.
Existing keypad offsets, Off, display brightness linkage and quarter-brightness
sleep behavior remain. GCR ISEL=3 and DIM<=128 limit each LED to approximately
4.64 mA typical, based on the
[AW9523B V2.4 datasheet](https://xpulabs.github.io/files/datasheet/DS_AW9523B_EN_V2.4.pdf).
The retained menu scale gives approximately 1.20 mA at display brightness 255
with keypad offset 0, or 2.36 mA with +3. Very dim nonzero settings use DIM=1;
Off uses DIM=0. All DIM registers are cleared before enabling LED mode.
Shutdown/SIGTERM or communication failure asserts reset to turn LEDs off.
A failed A0 initialization disables illumination without stopping navigation;
a successfully identified A0 is not treated as legacy on an LED write failure.

When replacing an older CM5 carrier with A0, rerun setup and reboot.
Code-only updates do not migrate boot settings. On kernel
`6.18.50+rpt-rpi-2712`, live PWM `unbind` triggers a kernel fault in
`rp1_pwm_remove`; release the PWM pins by rebooting instead.
To migrate only these settings
from the new checkout, run:

```bash
cd ~/MFNavis
source mfnavis_paths.sh
mfnavis_configure_keypad_boot "$(mfnavis_boot_config_path)"
```

Then reboot. Mock tests cover initialization order, all 16 channels, current
limits, failure shutdown, menu/sleep integration, chip identification, persistent
mode reload and boot setup. On 2026-10-29, CM5/A0 hardware passed three
initialization cycles and acknowledged 12 brightness writes, with chip ID and
LED mode registers verified and GPIO12 LOW at shutdown. Two app restarts
confirmed AW9523 driver selection and persisted `board_mode=MFNavis_A0`.
All 103 related automated tests passed, including bidirectional board changes
and preservation of all user settings. The user confirmed illumination and
brightness changes. DIM registers are write-only and cannot be read back;
current and temperature still require instrument checks.

**MFNavis_A0 FRAM hardware check (2026-10-29):** U12 FM24CL64B-GTR is
an 8 KiB memory at I2C1 address `0x50` (A0/A1/A2 LOW). Using the
[manufacturer datasheet](https://www.infineon.com/assets/row/public/documents/10/49/infineon-fm24cl64b-64-kbit-8-k-8-serial-i2c-f-ram-datasheet-en.pdf),
we tested two-byte memory addressing and immediate reads without write delays.
Two full reads agreed before backing up the original image. With the app stopped,
all seven full-memory patterns (00, FF, 55, AA, address low/high and pseudorandom)
passed over `0x0000–0x1FFF`. Ten single-byte writes at endpoints and address
boundaries preserved every other byte. The original image was restored with
an identical SHA-256 and remained unchanged after the app restarted.
The backup, check script and JSON report are stored on the tested device under
`~/MFNavis_data/test_data/fram-20261029-8abe582d/`.

This confirms read/write operation with write protection inactive. Power-off
retention was not tested. The following backup feature was added after this
hardware check.

**Configuration source version**

Both board modes record `source_version` in `config.json`: the `version.txt`
release (`version`), full Git commit (`git_commit`), and uncommitted changes
(`git_dirty`). Git fields are `null` when unavailable. Startup updates this
metadata after FRAM restoration; persistent settings saves include it as well.
A0 also commits the metadata to its verified FRAM backup. It identifies the
source last using/saving the configuration, independently of configuration
schema and FRAM storage format versions.

**A0 FRAM file storage and configuration synchronization**

FRAM stores named files; `/config.json` is one file alongside future calibration
or other small data files. Absolute paths form a virtual namespace, not an OS
mount. Use `PiFinder.fram_fs.open_filesystem()` and its `write_file(name, bytes)`,
`read_file(name)`, `delete_file(name)`, `list_files()` and `stat()` methods.
Use the Config API, not raw file writes, to modify application settings.

Two 4 KiB banks alternate complete compressed directory snapshots. Each file has
SHA-256 for its original bytes; bank metadata and payload have another SHA-256.
The new bank is read back before its commit marker is written last. Interrupted
writes or a corrupt newest bank leave the previous valid snapshot available.
All files share **4,039 compressed bytes** after the bank header. Current settings
use about 2.35 KB, leaving about 1.69 KB including metadata for future files.
Capacity errors preserve existing data. Cross-process locks serialize file writes.

After actual A0 detection, synchronization runs before startup settings consumers.
A valid FRAM `/config.json` is authoritative: replace a different local config
atomically, retaining its previous contents in `config.before-fram-<hash>.json`.
No valid config backup means initialize from `default_config.json` plus the detected
A0 mode and back it up, retaining other valid FRAM files. Bus errors are not empty
backups, and unknown filesystem versions are not overwritten.

This installation explicitly seeds **current settings first**, as requested.
Subsequent startups use the FRAM-first/defaults policy. Persistent Config saves
and user ZIP restores also update and verify FRAM. A failed or oversized backup
fails the settings change without publishing it to the local file. Session-only
settings are excluded. Manual SD-only edits are replaced at startup; use the UI,
web or `Config.set_option/set_options` for persistent changes. Legacy hardware
continues using the existing file-only storage.

On 2026-10-29, current settings were migrated on the physical A0 device.
The 5,492-byte config and directory occupy 2,348 compressed bytes, leaving
1,691 bytes. Hardware checks passed for independent file create/read/delete,
recovery of a damaged SD config copy, live Config-to-FRAM backup, and actual app
startup restoring a local-only settings difference. Temporary test entries were
removed. All 146 related automated tests passed. Backups and the hardware report
are under `~/MFNavis_data/test_data/fram-config-20261029-504457cb/` on the tested
device. Physical power-cut testing was not performed.

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
