# MFNavis Raspberry Pi 4/5 Trixie Compatibility Summary

Date: 2026-06-26 / updated: 2026-09-27

This note summarizes how the `main` branch handles Raspberry Pi 4 and
Raspberry Pi 5-class boards (Pi 5 and CM5) through the same install/runtime flow
on Raspberry Pi OS Trixie 64-bit.

For the runtime venv and `main` installation commands, follow the
[Trixie installation guide](mf_trixie_install_en.md).

## Summary

- New installs still run `mfnavis_setup.sh` as the normal OS user.
- On Trixie, the active boot config is `/boot/firmware/config.txt`; legacy OS
  images fall back to `/boot/config.txt`.
- The default GPS port setting is `gps_port: auto`; the board profile resolves
  the real port.
- Pi 5-class boards use `uart2-pi5` instead of `uart3`, avoiding the OLED CS
  conflict.
- Pi4 keeps the existing PiFinder SPI/OLED path and uses `/dev/ttyAMA3` for GPS
  UART.
- Bluetooth HID keyboards on Trixie BlueZ need userspace HID enabled so a
  stable `/dev/input/event*` device is created.

## Board Profiles

| Profile | Target | UART overlay | Default GPS port |
| --- | --- | --- | --- |
| `pi5_class` | Raspberry Pi 5, Compute Module 5 | `dtoverlay=uart2-pi5` | `/dev/ttyAMA2` |
| `pi4` | Raspberry Pi 4 | `dtoverlay=uart3` | `/dev/ttyAMA3` |
| `legacy` | Other/unknown Raspberry Pi boards | `dtoverlay=uart3` | `/dev/ttyAMA1` |

## Abstraction Points

Shell install path:

- `mfnavis_paths.sh`
- `mfnavis_board_model()`: reads `/proc/device-tree/model`.
- `mfnavis_board_profile()`: returns `pi5_class`, `pi4`, or `legacy`.
- `mfnavis_uart_overlay()`: returns the UART overlay to add to boot config.
- `mfnavis_gps_device()`: returns the initial `/etc/default/gpsd` `DEVICES`
  value.

Python runtime path:

- `python/MFNavis/board_config.py`
- `BoardProfile`: groups each board's `gps_device` and `uart_overlay`.
- `get_board_profile()`: returns the runtime board profile.
- `get_default_gpsd_device()`: resolves `gps_port: auto` to the real gpsd device.

Other hardware abstraction:

- `python/MFNavis/boot_config.py`: returns the active boot config path.
- `python/MFNavis/displays.py`: selects the first available SPI device from
  `/dev/spidev0.0` and `/dev/spidev10.0`.
- `python/MFNavis/sys_utils.py`: synchronizes GPS port/baud settings to
  `/etc/default/gpsd`.
- `python/MFNavis/ui/menu_structure.py`: exposes `Auto`, `ttyAMA1`, `ttyAMA2`,
  `ttyAMA3`, and USB serial candidates in the `GPS Port` menu.

The shell and Python profile detection are intentionally separate because the
install script runs before Python dependencies and services are fully installed.
Both implementations use the same profile names and defaults; the Python path is
covered by unit tests.

## Install-Time Behavior

`mfnavis_setup.sh` applies these board/OS-aware settings:

- Installs the required Trixie packages.
- Sets the initial gpsd device in `/etc/default/gpsd`.
- Creates `MFNavis_data` directories owned by the current OS user.
- Creates `/etc/wpa_supplicant/wpa_supplicant.conf` if it is missing.
- Adds SPI/I2C/PWM/UART settings to `/boot/firmware/config.txt` or
  `/boot/config.txt`.
- Comments out any stale `uart3` entry on Pi 5-class boards and uses
  `uart2-pi5`.
- Enables `UserspaceHID=true` and `LEAutoSecurity=true` for Bluetooth input.
- Renders systemd/Samba config files with the current OS user and paths.

## Board-Specific Checks

Raspberry Pi 4:

- Confirm `/dev/spidev0.0` appears for the OLED/LCD SPI device.
- Confirm boot config contains `dtoverlay=uart3`.
- Confirm GPS UART defaults to `/dev/ttyAMA3`.
- Pi4 camera ports usually do not need the CM5 `cam0` camera overlay parameter.

Raspberry Pi 5 / CM5:

- Seeing only `/dev/spidev10.0` can be normal.
- `uart3` uses GPIO8/9 and can conflict with SSD1351 OLED `CS=GPIO8/CE0`, so use
  `dtoverlay=uart2-pi5`.
- Confirm GPS UART defaults to `/dev/ttyAMA2`.
- If a camera is connected to `CAM0` on the CM5 IO board, the camera overlay may
  need the `cam0` parameter.

Bluetooth keyboard:

- Use `bluetoothctl devices Paired` to list paired devices.
- After connection, the keyboard must appear in `/dev/input/event*` and
  `libinput list-devices`.
- If key input is missing, run `libinput debug-events --device /dev/input/eventX`
  to verify actual events.

## Verification Commands

```bash
cd ~/MFNavis
bash -n mfnavis_paths.sh mfnavis_setup.sh

source ./mfnavis_paths.sh
mfnavis_board_profile
mfnavis_uart_overlay
mfnavis_gps_device

source scripts/activate_dev_trixie.sh
python -m ruff check MFNavis tests
python -m pytest tests/test_sys_utils.py -q
python -m pytest -m smoke
```

Hardware status checks:

```bash
ls -l /boot/config.txt /boot/firmware/config.txt 2>/dev/null || true
grep -n "dtparam\|dtoverlay\|camera_auto_detect" /boot/config.txt /boot/firmware/config.txt 2>/dev/null || true
ls -l /dev/i2c-* /dev/spidev* /dev/ttyAMA* /dev/ttyUSB* /dev/ttyACM* /dev/input/event* 2>/dev/null || true
systemctl status mfnavis mfnavis_splash indiwebmanager gpsd gpsd.socket bluetooth --no-pager
```

## Current Hardware Status

- CM5 Bookworm 64-bit: used as the baseline for Pi 5-class support.
- Raspberry Pi 4 Bookworm 64-bit: install, services, camera, GPS UART detection,
  and Bluetooth HID keyboard event creation have been verified.
- Raspberry Pi 5 Trixie/Python 3.13: installation, runtime services, and
  OnStepX checks were performed on 2026-09-26/27. The user reported no major
  problems in the 2026-09-27 GoTo field test.
- Pi 4 and CM5 Trixie hardware validation remains separate from the earlier
  Bookworm results. Shared profiles do not establish hardware test coverage.
