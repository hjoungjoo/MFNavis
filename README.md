# MF PiFinder

[English](./README.md) | [한국어](./README_ko.md)

MF PiFinder is based on the original [PiFinder™](https://github.com/brickbots/PiFinder)
and supports Raspberry Pi OS Bookworm 64-bit on Pi 4, Pi 5, and CM5. It adds
practical features including web catalogs, optional INDI mount control, and
operational documentation. The original creator's project description and
basic references remain below under **Original PiFinder Project**.

## Quick start

### 1. Install

For a first installation, the original project's prebuilt release image is the
simplest option. For a source-based Bookworm installation or Pi 4/Pi 5/CM5
setup, start with these references:

- [Original software setup](https://pifinder.readthedocs.io/en/release/software.html)
- [Bookworm 64-bit setup (한국어)](./docs/mf_dev/mf_bookworm_install_ko.md)
- [Pi 4/Pi 5/CM5 compatibility (한국어)](./docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md)
- [AP+STA Wi-Fi (한국어)](./docs/mf_dev/mf_wifi_apsta_ko.md)

After installation, connect a phone, tablet, or computer to the same network as
PiFinder and open `http://pifinder.local`. In AP mode, use
`http://10.10.10.1` if the hostname does not resolve.

### 2. Download offline caches

While internet access is available, pre-download the star/catalog runtime caches
and survey images for faster offline catalog browsing and detail pages.

```bash
cd /home/pifinder/PiFinder
python3 scripts/warm_pifinder_caches.py
```

To download only the POSS images used by the web catalog:

```bash
python3 scripts/warm_pifinder_caches.py --images poss
```

[Offline cache guide](./docs/mf_dev/mf_cache_download_en.md) |
[한국어](./docs/mf_dev/mf_cache_download_ko.md)

### 3. Configure an INDI mount

INDI is optional and disabled by default. First verify the connection, GoTo, and
Sync using Telescope Simulator before using a physical mount.

- [INDI mount installation and setup](./docs/mf_dev/mf_indi_mount_install_en.md) |
  [한국어](./docs/mf_dev/mf_indi_mount_install_ko.md)
- [Mount-mode compatibility (한국어)](./docs/mf_dev/mf_mount_mode_compatibility_ko.md)

### 4. Keypad and keyboard controls

Use these references for global LCD controls, page-specific controls, and
USB/Bluetooth keyboard mapping:

- [Input controls](./docs/mf_dev/mf_input_controls_en.md) |
  [한국어](./docs/mf_dev/mf_input_controls_ko.md)
- [Keyboard mapping](./docs/mf_dev/mf_keyboard_mapping_en.md) |
  [한국어](./docs/mf_dev/mf_keyboard_mapping_ko.md)

### 5. MF feature documentation

The [MF additional-features index](./docs/mf_dev/mf_additional_features_en.md)
groups documentation for web catalogs, location catalogs, LiveCam, automatic
exposure, Cedar/SEP solving, SQM, and IMU calibration. Its Korean equivalent is
[available here](./docs/mf_dev/mf_additional_features_ko.md). For current test
status and history, see the [feature review checklist](./docs/mf_dev/mf_feature_review_checklist_en.md)
and [Korean change history](./docs/mf_dev/mf_change_history_ko.md).

---

# Original PiFinder™ Project

This section describes upstream history. This fork's main uses MF Detect Star
and no longer includes Cedar Detect binaries. See the
[current integration](docs/DETECTOR_INTEGRATION_ko.md) and
[merge/deployment record](docs/MAIN_FINALIZATION_ko.md).

A plate solving telescope finder based around a Raspberry PI, imx296 camera, and custom UI 'hat'

For an overview of what the PiFinder™ is and how it came to be visit the official project website at [PiFinder.io](https://www.pifinder.io/build-yours) 

The PiFinder™ uses the [Cedar Detect](https://github.com/smroid/cedar-detect) and
[Cedar Solve](https://github.com/smroid/cedar-solve) libraries by
[smroid](https://github.com/smroid). Cedar Solve is licensed under Apache-2.0.

**Cedar Detect** is published under the Functional Source License (`FSL-1.1-MIT`),
which permits broad non-commercial use but excludes commercial uses that compete
with Cedar Detect. Because the PiFinder™ is also offered commercially, it bundles
and distributes the Cedar Detect binaries under a **separate license granted
expressly by the copyright holder** — not under the public FSL terms. The prebuilt
binaries were part of the upstream distribution; this fork has removed them.
See [`bin/README.md`](./bin/README.md) for the current binary policy. Note this is
distinct from the PiFinder project's own GPL-3.0 [`LICENSE`](./LICENSE).

Thank you to [smroid](https://github.com/smroid) for all your support of the PiFinder project!

![Banner](./docs/source/images/PiFinder_v3_banner.png)
The PiFinder™ is my attempt to improve my time at my telescope.  I don't get nearly enough of it and I want to enjoy it as much as possible.  So after years of observing with paper charts and, later, a Nexus DSC here is what I felt I was missing:
* **Reliable telescope positioning:**  The Nexus DSC is great, but my scope just isn't built for solid encoder integration.  The slop in the way I have to couple the encoders means poor pointing accuracy.
* **Easy setup:**  The Nexus DSC needs multi-star alignment to understand how the encoders map to the sky.  The process is not terrible, but I'd like to avoid it.
* **Good push-to functionality**:  This is one place the Nexus DSC shines... if it's well aligned.  The catalog system is okay, and once you select and object the screen is clear and helpful to get the telescope pointed correctly.
* **Observation logging**:  I like to keep track of what I see each night.  I don't often sketch, just record what I saw when, with what eyepiece and some basic info about the experience.  If I could do this right at the eyepiece, that'd save time.

My hope is that other people will find this combination of functionality useful, will build their own PiFinder™ and help the whole project improve by making suggestions and potentially contributing to the software.  It's a pretty easy build with off the shelf parts and beginner friendly soldering.  

## Features
* Zero setup: Just turn it on and point it at the sky!  
* Accurate pointing: Onboard GPS determines location and time while the camera determines where the scope is pointing.  Inertial Measurement Unit tracks scope motion and updates sky position between camera solves
* Self-contained:  Includes catalog search/filtering, sky/object charting, push-to guidance and logging all via the screen and keypad on the unit.
* Dark site friendly:  Red OLED screen and soft backlit keys have wide brightness adjustment, right down to 'off'. No need for bright cell phones or tablets
* Easy access: Can be mounted by the eyepiece just like a finder.
- Wifi Access Point / SkySafari Integration:  The PiFinder™ can act as a WIFI access point to connect your tablet or phone to sync SkySafari or other planetarium software with your scope.

## Build Your Own
The PiFinder™ is fully open-source hardware and software.  You can order PCB's and 3d print the case with the files in this repo and order all the parts from the [parts List](https://pifinder.readthedocs.io/en/release/BOM.html).

If you would like pre-assembled units, kits or other items to jump start your PiFinder™ journey, visit [PiFinder.io](https://www.pifinder.io/build-pifinder) to see what's available and place an order.

## Docs

* [Quick Start](https://pifinder.readthedocs.io/en/release/quick_start.html)
* [User Manual](https://pifinder.readthedocs.io/en/release/user_guide.html)
* [Parts List](https://pifinder.readthedocs.io/en/release/BOM.html)
* [Build Guide](https://pifinder.readthedocs.io/en/release/build_guide.html)
* [Software Setup](https://pifinder.readthedocs.io/en/release/software.html)
* [Developer Guide](https://pifinder.readthedocs.io/en/release/dev_guide.html)

## Releases and Updates

If you are using a PiFinder, I recommend you watch releases in this repo.  Click the 'Watch' button up at the top right of the page, choose 'Custom' and then 'Releases' to make sure you don't miss any new features!

![PiFinder™ on my Dob](./images/PiFinder_on_scope.jpg)

If you'd like to learn more about how it works, and potentially build your own, everything you need should be here.  I recommend starting with the [User Manual](https://pifinder.readthedocs.io/en/release/user_guide.html) and then checking out the build process using the links below.

## Discord
Join the  [PiFinder™ Discord server](https://discord.gg/Nk5fHcAtWD) for support with your build, usage questions, and suggestions for improvement.

## Public MF detector source (m2.6.6)

The detector and its PiFinder integration are maintained at [MFDS](https://github.com/hjoungjoo/MFDS),
a public, pinned submodule at `python/mf_detect_star`. This release uses [MFDS v0.2.1](https://github.com/hjoungjoo/MFDS/releases/tag/v0.2.1); see [release notes](release_notes/m2.6.6.md). No private repository key
is required. Native FSL five-year/MIT and the integration's GPL terms remain
separate; see [migration and license scope](docs/MFDS_MIGRATION_ko.md).
