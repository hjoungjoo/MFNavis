# MFNavis m2.6.15 — Trixie support and pointing / mount tracking improvements

- SkySafari pointing updates after boot without requiring an initial GoTo. Valid IMU estimates are used before solving; solved alignment anchors subsequent estimates. A configured observer site or the last site sent to OnStep supplies coordinate conversion while GPS is unavailable. Unaligned IMUPLUS absolute heading remains provisional.
- LCD `0` / Mount Stop cancels manual motion, GoTo and guide corrections, and confirms that native mount tracking is Off before reporting success. Releasing a direction key continues to stop only manual motion while preserving tracking.
- Remove the duplicate Push camera overlay title. Improve target continuity, centred camera zoom and Focus camera controls.
- Support Raspberry Pi OS **Trixie 64-bit / Python 3.13**, with validated INDI archives, ABI/checksum checks, transactional installation and Avahi startup checks for `.local` access.
- Improve INDI serial Auto discovery, sustained manual movement, OnStep Sync acknowledgements, altitude / meridian limits and native GoTo / tracking during solve outages.
- Add RAW star drift correction, asynchronous alignment and Moon / planet / manual target integration. The new correction mode defaults to On while preserving saved settings; actual correction requires a verified equipment profile and a start request. Prediction during star loss remains bounded by verified time, error and travel limits.
- Add IMX678 mono / colour profiles and an optional driver installation. Sensor photometric and SQM calibration still require measurement.
- Fix web API authentication, backup restoration and Korean tracking-screen translations. Update fresh-install IMX462 Color lens defaults and alignment persistence.
- Pin the detector to **MFDS v0.4.2**.

Use Trixie 64-bit for this release. Updating source does not upgrade Bookworm to Trixie. Back up configuration, observation data and local changes, then follow the [Trixie installation guide](../docs/mf_dev/mf_trixie_install_en.md). Hardware checks were performed on Pi 5; separate Trixie checks on Pi 4 and CM5 remain outstanding.

Run as the intended installation user:

```bash
wget -O /tmp/mfnavis-m2.6.15-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/m2.6.15/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=m2.6.15 bash /tmp/mfnavis-m2.6.15-setup.sh
```

Reboot after installation and refresh open browser pages. Existing lens / distortion settings are preserved.

This release provides software source and installation materials. It does not include an OS image, private observation frames or equipment configuration. See the [validation record](../docs/mf_report/m2.6.15_validation_ko.md) and [full comparison](https://github.com/hjoungjoo/MFNavis/compare/m2.6.14...m2.6.15).
