# Upstream IMX678 driver

`imx678.c` is an **unmodified** copy from Linux upstream:
https://github.com/torvalds/linux/blob/bf40cc53b1e00c312046f6dd88e9054bc91865af/drivers/media/i2c/imx678.c

`upstream.json` pins its commit and SHA-256. Original copyright and GPL-2.0
notices are retained; `COPYING` contains the upstream license text.

The Raspberry Pi 6.18.50 package does not contain this driver. The DKMS
packaging backports the upstream source without changing its implementation.
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
