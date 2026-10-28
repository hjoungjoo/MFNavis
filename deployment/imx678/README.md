# Upstream IMX678 driver

`imx678.c` is an **unmodified** copy from Linux upstream:
https://github.com/torvalds/linux/blob/bf40cc53b1e00c312046f6dd88e9054bc91865af/drivers/media/i2c/imx678.c

`upstream.json` pins its commit and SHA-256. Original copyright and GPL-2.0
notices are retained; `COPYING` contains the upstream license text.

The Raspberry Pi 6.18.50 package does not contain this driver. The DKMS
packaging verifies the pristine source, then applies the separately maintained
`0001-cm5-converter-power-sequence.patch` when building version 0.2.0.
The Pi Device Tree adapter (`imx678-mfnavis-overlay.dts`) is MFNavis code,
not an upstream Raspberry Pi overlay. It uses upstream's generic
`sony,imx678` match to identify the mono/colour variant from the sensor ID.
Regulators use the Pi camera module convention: CAM GPIO enables module power;
the module provides the internal 1.1 V / 1.8 V rails.

Supported baseline: 3856×2180, RAW12, mono or RGGB, manual exposure and
analogue gain. This upstream version does not implement binning or HDR.
No vendor HCG/LCG extension or replacement libcamera is installed.

Run `bash scripts/install_imx678.sh --build-only /tmp/imx678-build` from the
repository root for a compile check, or `sudo bash scripts/install_imx678.sh
--install` to prepare DKMS, the overlay, official generic tuning, and menu
permissions. Neither action switches the active sensor or reboots.

The official libcamera generic `uncalibrated.json` is copied unchanged to
`imx678.json` at installation, unless a tuning file already exists. It is an
uncalibrated starting point for RAW acquisition, not measured IMX678 colour
or photometric calibration. See ../../docs/mf_dev/setup_ko.md.

## MFNavis A0 PWR2-PD converter on CM5 CSI0

The separate `imx678-mfnavis-cm5-converter` overlay matches the supplied
2026-10-04 converter schematic and the confirmed mainboard GPIO34/35 wiring:

| Signal | Configuration |
| --- | --- |
| CSI | CSI0, four data lanes, 445.5 MHz link frequency |
| Sensor input clock | U10 fixed 74.25 MHz oscillator |
| MIPI_GPIO0 | RP1 GPIO34, active HIGH, U11 power sequencer enable |
| MIPI_GPIO1 | RP1 GPIO35, active LOW reset; also gates U10 oscillator |
| I2C | Dedicated CSI0 I2C6, GPIO38 SDA / GPIO39 SCL, address 0x1a |

The patch applies only to compatible `mfnavis,imx678-cm5-converter`.
Generic `sony,imx678*` devices keep their original sequencing. There is no
generic compatible fallback on the converter overlay: an unpatched driver
must not bind to this board.

On startup, hold SDA/SCL and reset LOW, enable the sequencer and wait 150 ms
through the fixed regulator's startup delay, release reset, wait 5 ms for the
oscillator, and return the bus to I2C before writing sensor registers.
On shutdown, after sensor standby, clamp SCL then SDA LOW, assert reset,
wait 1 ms, disable the sequencer and wait 150 ms for discharge. The I2C pins
remain LOW until the next power-up. Runtime power-off and system shutdown
use the same sequence. The adapter pinctrl handle is used under the I2C bus
lock; this requires a dedicated bus, without other devices or probing tools.
This is software sequencing; rail voltages and actual timing still require
oscilloscope validation on the assembled converter.

Ordinary MFNavis setup needs no camera options on CM5 Trixie: it installs IMX678
support while keeping IMX462 as the fresh-install default. Afterwards, select
**IMX678 (Auto)** in the camera menu. On CM5, the first selection automatically
uses this CSI0 converter overlay and reboots. Switching away and back preserves
it. Previously saved custom wiring takes precedence; non-CM5 boards retain the
generic IMX678 default.

For manual repair of an older installation, install and select this board
(backs up config.txt; does not reboot):

```bash
sudo bash scripts/install_imx678.sh --activate-converter
sudo reboot
```

Full setup preserves the existing sensor on reinstalls and prepares IMX678
support by default on Pi 5/CM5 Trixie. The administrative override
`MFNAVIS_CAMERA=imx678-cm5-converter` can preselect the board but is not required. Set
`MFNAVIS_INSTALL_IMX678=false` to opt out when IMX678 is not selected.

Installation includes the appropriate kernel header metapackage and builds
the DKMS module for all installed kernels of the running kernel flavour.
This covers an OS update awaiting its first reboot. Future kernel/header
updates use DKMS autoinstall; compatibility with future kernels is not assumed
without a successful build. Missing headers stop installation. Code-only
MFNavis updates do not change system drivers.

The resulting `[all]` section selects:

```ini
camera_auto_detect=0
dtoverlay=imx678-mfnavis-cm5-converter
```

`--install` still prepares software without changing the active camera.
After activation, switching away and back through the camera menu preserves
the converter profile. Do not use the generic overlay for this converter.
The CM5 overlay cannot be reused on a Pi 5 or different carrier pinout.

Tests in `python/tests/test_imx678_converter.py` compile and exercise the
actual patched C power functions with mocked kernel calls (nine normal/error
cases), and merge the overlay with CM5 IO and CM4 IO firmware DTBs to check
GPIOs, clock, CSI endpoints and pinctrl. These do not substitute for capture
or electrical tests.

On 2026-10-29 this CM5 converter also passed real RAW capture, manual
exposure/gain and three reopen cycles; see
[`docs/mf_report/imx678_cm5_csi0_20261029_ko.md`](../../docs/mf_report/imx678_cm5_csi0_20261029_ko.md).
With the app stopped, reproduce using the runtime venv:

```bash
timeout 120s .venv-trixie/bin/python scripts/check_imx678_capture.py \
  --output /home/mfnavis/MFNavis_data/imx678-validation/capture
```
