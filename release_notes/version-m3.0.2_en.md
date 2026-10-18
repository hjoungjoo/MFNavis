# MFNavis m3.0.2 — Web UI and Tools status fixes

## Changes

- Moved the STA network form out of the narrow table column. Selecting a scanned SSID and switching to manual entry now update the input correctly. Save validates required fields and password length.
- Fixed overlapping GPS date/time labels and long select captions. Improved mobile form spacing and long button text; equipment, location and observation tables scroll within their sections.
- Fixed Tools remaining on “Loading” after repeated visits. Each visit reconnects to the download job, late responses cannot overwrite the current page, and initial connection failures show an error while retrying.
- Unified disabled regular, small, icon and link-style buttons across grey and red themes. Disabled controls use a darker surface, muted text, a dashed edge and no shadow. The INDI HOLD button now also has a native disabled attribute.
- Fixed download actions that should stay hidden until results exist and restored visible select arrows.

## Installation and validation

Baseline: Raspberry Pi OS Trixie 64-bit / Python 3.13 and the existing pinned MFDS v0.4.4 package.
Run as the installation user and reboot after installation:

```bash
wget -O /tmp/mfnavis-m3.0.2-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/m3.0.2/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=m3.0.2 bash /tmp/mfnavis-m3.0.2-setup.sh
```

Reload the web UI after updating. All 48 targeted regression tests and lint/format checks for changed Python tests passed. Firefox checks covered 25 screens in Korean and English at 375px and 1280px; button states were also checked across 23 screens in both themes. UI validation did not start real downloads or telescope motion.

[Installation](https://github.com/hjoungjoo/MFNavis/blob/m3.0.2/README.md) ·
[Validation record](https://github.com/hjoungjoo/MFNavis/blob/m3.0.2/docs/mf_report/m3.0.2_validation_ko.md) ·
[Full comparison](https://github.com/hjoungjoo/MFNavis/compare/m3.0.1...m3.0.2)

This release provides software source and installation materials. A fresh SD-card installation and OS image build were outside this validation scope.
