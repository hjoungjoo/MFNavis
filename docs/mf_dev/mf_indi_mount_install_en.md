# MFNavis INDI Mount Control

This document covers the optional INDI mount-control work for Raspberry Pi 4 and Raspberry Pi 5 Bookworm 64-bit builds.

The feature is disabled by default. Normal MFNavis installs do not import PyIndi or start the INDI mount-control process unless `mount_control` is enabled in the MFNavis config.

The installer has been validated on a Raspberry Pi 4 Model B running Bookworm 64-bit. Raspberry Pi 5 and CM5 use the same Bookworm 64-bit packages and aarch64 build path, and the script does not contain Pi 4-only paths or model-specific branches.

## Status

INDI mount control is experimental. Test with the INDI Telescope Simulator first, then test with the real mount in a safe indoor setup before using it under the sky.

The first integrated scope includes:

- INDI server connection through PyIndi
- telescope/mount device detection
- location and UTC time sync from MFNavis
- mount sync from MFNavis plate-solved RA/Dec
- GoTo for the object currently shown in Object Details
- stop command
- small manual RA/Dec offset moves

Automatic target refinement, drift compensation, and alignment-subsystem management from the older reference branch are not enabled in this first modular port.

## Install INDI Support

The default installation path is the **shared Pi 4/Pi 5 binary archive**. The
Bookworm 64-bit/aarch64 archive shipped with MFNavis installs the validated
INDI core, third-party drivers, PyIndi, and MFNavis OnStepX patch set together.
Use the full source install and build below only when modifying the source or
changing/testing driver patches.

```bash
cd ~/MFNavis
bash scripts/install_indi_mount_archive.sh \
  dist/mfnavis-indi-bookworm-arm64-v2.2.3.1-current.tar.gz
```

During a full `mfnavis_setup.sh` install, this archive path is selected
automatically when an archive is in `dist/` or `MFNAVIS_INDI_ARCHIVE` is set.

### For changes: full source install and build

Run the dedicated installer from the MFNavis checkout:

```bash
cd ~/MFNavis
bash scripts/install_indi_mount_OnstepX.sh
```

The script installs INDI, INDI third-party drivers, PyIndi, INDI Web Manager, and Chrony GPS time support. During binary installation it stops the running `mfnavis` and INDI Web Manager services, then restores their prior running state even if installation fails.

INDI Web Manager dependencies are pinned to `FastAPI 0.103.2`, `Starlette 0.27.0`, `Uvicorn 0.23.2`, and `AnyIO 3.7.1`. Newer Starlette releases changed the template response call signature used by this INDI Web Manager branch, which can make the root Web UI return `500 Internal Server Error`.

Useful environment overrides:

```bash
JOBS=4 bash scripts/install_indi_mount_OnstepX.sh
```

`JOBS=2` is the conservative default for Raspberry Pi 4 memory use. On Raspberry Pi 5 or CM5, `JOBS=3` or `JOBS=4` can reduce build time if cooling and power are stable. `INDI_VERSION` / `INDI_3RDPARTY_VERSION` can also be overridden the same way.

The script checks out INDI `v2.2.3.1` under `~/indi-latest`, builds it, and automatically applies `scripts/patches/indi-v2.2.3.1-onstepx.patch`. The patch leaves the upstream `LX200 OnStep` driver unchanged and adds a separate `LX200 OnStepX` device and executable link. The OnStepX patch also carries the MFNavis Backlash range/readback fixes and writable `GUIDE_RATE` handling for driver compatibility.

`install_indi_mount_OnstepX.sh` strips `-march=native`, `-mcpu=*`, and `-mtune=*`, then uses `-march=armv8-a` so a build made on Raspberry Pi 5 stays compatible with Raspberry Pi 4. To test pure upstream INDI without the bundled MFNavis patch:

```bash
INDI_PATCH_DIR=none bash scripts/install_indi_mount_OnstepX.sh
```

`INDI_PATCH_DIR=none` requires a clean INDI checkout. If
`~/indi-latest/indi` already contains the OnStepX patch, set a separate empty
`BUILD_ROOT` to test unpatched upstream code. The installer checks the source
checkout and job count before changing system packages.

### Default installation: Pi 4/Pi 5 shared binary archive

For normal installs, use the prebuilt Bookworm 64-bit/aarch64 archive. Switch to
the full source build in the preceding section only when source modifications or
new patch validation are required:

```bash
cd ~/MFNavis
bash scripts/install_indi_mount_archive.sh dist/mfnavis-indi-bookworm-arm64-v2.2.3.1-current.tar.gz
```

The Git repository may store large archives as split files named
`.tar.gz.part-00`, `.part-01`, and so on. Use the same `.tar.gz` path in the
command above; `install_indi_mount_archive.sh` rebuilds the archive from the
parts and verifies the `.sha256` checksum before installation.

The main MFNavis setup script can use the same archive installer:

```bash
cd ~
MFNAVIS_INDI_ARCHIVE="$HOME/MFNavis/dist/mfnavis-indi-bookworm-arm64-v2.2.3.1-current.tar.gz" \
  bash "$HOME/MFNavis/mfnavis_setup.sh"
```

`MFNAVIS_INSTALL_INDI_ARCHIVE` defaults to `auto`. If a `dist/mfnavis-indi-bookworm-arm64-*.tar.gz` file exists or `MFNAVIS_INDI_ARCHIVE` is set, the setup script installs INDI support. If no archive is found, setup continues with the normal MFNavis install only. To force-disable the archive installer:

```bash
MFNAVIS_INSTALL_INDI_ARCHIVE=false bash "$HOME/MFNavis/mfnavis_setup.sh"
```

To create a new binary archive from the currently installed build:

```bash
cd ~/MFNavis
bash scripts/package_indi_mount_archive.sh
```

`package_indi_mount_archive.sh` creates the full `.tar.gz` and `.sha256` files.
When the archive is larger than the GitHub-friendly threshold, it also creates
`.tar.gz.part-*` split files automatically so the archive can be committed with
the source tree.

A binary archive created after the latest source build includes the patched `LX200 OnStepX` driver and can be reused on Raspberry Pi 4 and Raspberry Pi 5 Bookworm 64-bit systems. Archive metadata records the OnStepX patch name and checksum so the installed binary can be traced back to the patch file.

## Configure The Mount Driver

Open INDI Web Manager:

```text
http://<hostname>.local:8624
```

If mDNS does not resolve, use the MFNavis IP address:

```text
http://<pifinder-ip>:8624
```

Create a profile, choose the correct telescope driver, enable Auto Start and Auto Connect if desired, then start the profile. Common drivers include EQMod, LX200, iOptron, Celestron, and Telescope Simulator.

When the active INDI profile uses `LX200 OnStepX`, its connection settings can be configured from the MFNavis web UI:

```text
INDI > LX200 OnStepX Driver Connection
```

For USB connections, choose a detected `/dev/serial/by-id`,
`/dev/serial/by-path`, `/dev/ttyUSB*`, or `/dev/ttyACM*` port, or enter the
serial port manually. Communication Speed
offers `9600`, `19200`, `38400`, `57600`, `115200`, `230400`, and `460800`
baud. Aliases that resolve to the same physical serial device are collapsed
into one entry, preferring the stable `/dev/serial/by-id/...` path when
available. Selecting `Auto (Find connected OnStep)` also switches Communication
Speed to Auto. Only when Apply is pressed, MFNavis removes the configured GPS
and duplicate aliases from local candidates, then probes supported baud rates
with the read-only `:GVP#`/`:GVN#` queries. A concrete stable port and detected
baud are applied only when exactly one OnStep is verified; zero or multiple
matches restore the previous connection without saving. Apply
disconnects the driver, writes `DEVICE_PORT` and the standard INDI
`DEVICE_BAUD_RATE`, reconnects and verifies the connection, then performs
`CONFIG_SAVE`. Baud applies only to USB Serial and defaults to 9600. For
network connections, choose an IP from the AP connected-device list, or enter
a host/IP and TCP port manually when the device is not listed. The default
OnStep network TCP port is `9999`.

The effective OnStep transport is resolved in this order: live INDI
properties, the INDI-saved XML, then the last verified MFNavis mirror. At
startup, a valid live/XML value updates only the MFNavis mirror; it does not
roll back or reapply a working driver configuration. The MFNavis mirror is
applied once only when both live and XML settings are incomplete, followed by
live readback verification. If every source is incomplete, automatic connect
stops with `config_invalid` instead of trying guessed defaults.

A Web save updates MFNavis's transport/server settings in one atomic write
only after INDI reconnect, live readback, and `CONFIG_SAVE` have all
succeeded. Failure preserves the previous mirror. Reconciliation status is
written to the tmpfs `mount_control_status.json` file.

## MFNavis INDI Web Menu

The MFNavis web UI now has a dedicated `INDI` top-level menu. This page links to INDI Web Manager and reads the active driver name from the running INDI profile. OnStepX-specific setup and control sections are shown only when that active driver is `LX200 OnStepX`.

### Current INDI Driver State

This section shows the active INDI profile, active driver, and available driver properties. OnStepX connection mode, serial/network settings, OnStep location, and OnStep UTC time appear after the profile is started and the `LX200 OnStepX` driver is loaded.

### Location And Time

The `Location and Time` section is shown for `LX200 OnStepX` and sends MFNavis's current location and UTC time to OnStep.

- If MFNavis has a GPS lock, it uses the GPS/loaded location.
- If there is no GPS lock, it shows `GPS Lock: Not locked` and uses the default location from MFNavis `Locations` as `Location to Send`.
- The UTC time field keeps ticking while the page is open.
- `Reload Current Values` refreshes the MFNavis location/time and the displayed OnStep location/time without leaving the page.
- When `Send Location and Time` is pressed, the server recalculates MFNavis system UTC at the moment the request is received and sends that value to OnStep. The final transmitted time is therefore based on MFNavis, not on the phone or browser clock.
- The web request starts a bounded background sync so the page remains responsive even while a driver is slow or unavailable. The state area is refreshed automatically after the request completes; it reports the result and reads back the driver values.
- A newly locked GPS location is applied automatically. Later GPS changes are filtered to avoid mount updates from jitter (more than 500 m, checked no more than once per minute). Loading a location or setting it as the default in `Locations` is an explicit selection and applies the chosen coordinates immediately.
- LX200 OnStepX is the MFNavis custom INDI driver. Location/time sync uses full INDI `GEOGRAPHIC_COORD` and `TIME_UTC` vector updates, and the driver converts those values to OnStep LX200 commands internally.
- Avoid partial `indi_setprop` CLI writes for these vectors. MFNavis uses PyIndi full-vector updates.
- In a UTC+9 environment such as Korea, MFNavis sends INDI `TIME_UTC.OFFSET=+9.00`, and the driver converts it to the OnStep `:SG-09:00#` convention.

### Mount Control

The `Mount Control` section is shown for `LX200 OnStepX` and provides simple initialize/park/manual-motion controls.

- Home and Park are displayed as separate states. OnStep can report `At Home`
  while still being `Unparked`; the OnStep Web UI disables the Park button for
  both `At Home` and `Parked`, so MFNavis also shows the raw `:GU#` mount
  status for diagnostics.
- `At Home`, `Return Home`, `Park`, `Unpark`, and `Set-Park` commands are available.
- Slew Rate uses OnStep's native 0-9 scale: `Off`, `1/2`, `1`, `2`, `4`, `8`, `20`, `48`, `1/2 MAX`, `MAX`.
- Direction buttons move while held and send a stop command when released.
- Diagonal buttons send the paired North/South and East/West commands together.

This web control page sends commands directly to the INDI driver. It can be used alongside the Object Details numeric-key Sync/GoTo flow.

### OnStepX Settings

The `Settings > INDI Setting` menu includes OnStepX maintenance controls.
(It used to live under `Start > INDI > Setting`; it now sits alongside the
other configuration menus under `Settings`.)

- `Multi Align` is driven by one shared session controller used by the Web UI,
  LCD UI, and SkySafari bridge. At start, MFNavis sends its location/time to
  the mount, syncs the mount to MFNavis's current pointing, and verifies the
  readback. Native OnStepX `:A<n>#` start is deferred because it resets the
  mount home/frame, and stale native align state is cleared with direct
  `:SX09,0#` before the MFNavis-managed flow continues. See
  `docs/mf_dev/mf_multipoint_align_flow_en.md` for the detailed flow.
- `Backlash` reads and writes the INDI driver properties
  `Backlash.Backlash RA` and `Backlash.Backlash DEC`, which map to OnStep
  RA/Azm and Dec/Alt backlash in arc-seconds.
- In Alt/Az mode, the UI labels the first value, `Backlash.Backlash RA`, as
  `AZ` (Axis1 RA/Azm) and the second value, `Backlash.Backlash DEC`, as `ALT`
  (Axis2 Dec/Alt). In EQ mode the UI keeps the normal `RA` / `DEC` labels.
- The manual `Save Backlash` action is safe to test indoors because it only
  updates driver/device settings and does not command mount motion.
- `Auto Backlash` keeps the internal `compass_goto_loop` mode name, but the
  actual measurement motion is INDI GoTo. The calculation, filtering, and
  recommendation logic stay unchanged. Alt/Az mounts test `AZ` and `ALT`
  separately, while EQ mounts test `RA` and `DEC` separately. See
  `docs/mf_dev/mf_backlash_measurement_flow_en.md` for the detailed flow and formulas.
- The automatic Backlash test must turn tracking off with
  `TELESCOPE_TRACK_STATE.TRACK_OFF` before measurement and restore the original
  tracking state afterward. With tracking enabled, sidereal motion can appear as
  IMU movement and be misread as backlash.
- The automatic Backlash test no longer checks the IMU magnetometer. It requires
  a valid plate-solved `PointingCoordinateService.solved` coordinate instead.
  If no fresh solved coordinate is available, the test waits/fails before
  sending mount motion commands.
- If a measurement reaches the `3600 arc-sec` limit, the UI reports low
  confidence. Do not save that value blindly; it may mean the mechanical
  backlash exceeds the configured range or that the solved coordinate sample
  was stale or captured at the wrong time.
- Automatic measurement does not reset Backlash to zero and does not apply the
  calculated value automatically. Results are shown as recommendations only; the
  user reviews the input values and presses `Save Backlash` to write them. On
  completion, MFNavis restores the original tracking state when it was enabled
  before the test.

## Enable MFNavis Control

On the MFNavis UI:

```text
Tools > Experimental > Mount Control > On
```

Changing this option restarts MFNavis so the optional `MountControl` process can start or stop cleanly.

The Mount Control process no longer connects to INDI immediately at MFNavis startup. It initializes the INDI connection when a mount command is sent from Object Details, such as `1`, Sync, or GoTo.

Advanced config keys in `default_config.json`:

```json
"mount_control": false,
"mount_control_indi_host": "localhost",
"mount_control_indi_port": 7624,
"onstep_connection_type": "network",
"onstep_serial_port": "",
"onstep_serial_baud": 9600,
"onstep_network_host": "",
"onstep_network_port": 9999
```

## Object Details Key Map

When Mount Control is enabled, numeric keys on the Object Details screen send mount commands:

| Key | Action |
| --- | --- |
| 0 | Stop mount |
| 1 | Initialize INDI connection and sync if MFNavis has a solve |
| 2 | Move south by the current step size |
| 3 | Decrease step size |
| 4 | Move west by the current step size |
| 5 | GoTo the displayed object |
| 6 | Move east by the current step size |
| 7 | Sync mount to the current MFNavis solved position |
| 8 | Move north by the current step size |
| 9 | Increase step size |

Manual movement is implemented as a small RA/Dec GoTo offset from the current mount coordinates. The default step size is 1 degree; key `3` halves it and key `9` doubles it within safe bounds.

## Logs And Status

MFNavis logs mount-control messages under `MountControl.Indi`.

A small status file is written here:

```text
~/MFNavis_data/mount_control_status.json
```

Useful service checks:

```bash
systemctl status indiwebmanager.service
systemctl status mfnavis.service
journalctl -u indiwebmanager.service -n 100
tail -n 100 ~/MFNavis_data/pifinder.log
```

## Safe Test Flow

1. Install INDI support.
2. Start the Telescope Simulator in INDI Web Manager.
3. Enable MFNavis Mount Control.
4. Open any Object Details screen.
5. Press `1` to initialize.
6. After MFNavis has a solve, press `7` to sync.
7. Press `5` to send GoTo.
8. Press `0` to verify stop behavior.

Only move to a real mount after simulator behavior is understood.
