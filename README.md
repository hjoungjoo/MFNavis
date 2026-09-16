# MF PiFinder

[English](./README.md) | [한국어](./README_ko.md)

MF PiFinder is based on the original [PiFinder™](https://github.com/brickbots/PiFinder)
and supports Raspberry Pi OS Bookworm 64-bit on Pi 4, Pi 5, and CM5. It adds
practical features including web catalogs, optional INDI mount control, and
operational documentation. The original creator's project description and
basic references remain below under **Original PiFinder Project**.

## Quick start

### 1. Prepare Raspberry Pi OS

Install **Raspberry Pi OS Bookworm 64-bit** on the Pi 4, Pi 5, or CM5 boot
media with Raspberry Pi Imager. Configure a username, hostname, SSH, and Wi-Fi
before first boot, then log in as that user and confirm internet access.
Choose Bookworm explicitly for this installation.

See the [Raspberry Pi OS installation instructions](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-an-operating-system)
for imaging and first boot, and the [board compatibility guide](./docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md)
for Pi 4/Pi 5/CM5 wiring differences.

### 2. Install MF PiFinder: release or main

Check the [MF PiFinder releases page](https://github.com/hjoungjoo/MF_PiFinder/releases)
for the latest published version, its exact tag, and release-specific instructions.
Use the tagged release for a fixed version, or `main` for the latest development
changes. These instructions install MF PiFinder onto the prepared OS.

Run **one** of the following on a new installation, as the target OS user
without `sudo`; the script requests sudo where needed. It installs dependencies,
configures hardware interfaces and services, and **automatically installs the MFDS
detector**. The installation method differs by version:

| Version | Automatic detector installation |
| --- | --- |
| Published release | Uses the detector installation method included in the selected tag. Check the release notes for installation requirements and any build steps. |
| `main` | Downloads and verifies the MFDS binary release pinned in `deployment/mfds.lock.json`; no detector source build is required. |

Both paths are handled by the installation script; no separate manual MFDS
installation is needed.

**Published release:**

The command automatically looks up the latest published release on GitHub and
installs that tag. No version entry is needed. If the lookup fails, installation
stops. These commands are for a new installation with no existing `~/PiFinder`.

```bash
PF_RELEASE_TAG="$(python3 -c 'import json, urllib.request; print(json.load(urllib.request.urlopen("https://api.github.com/repos/hjoungjoo/MF_PiFinder/releases/latest"))["tag_name"])')" &&
[ -n "$PF_RELEASE_TAG" ] &&
wget -O /tmp/mf-pifinder-setup.sh "https://raw.githubusercontent.com/hjoungjoo/MF_PiFinder/${PF_RELEASE_TAG}/pifinder_setup.sh" &&
PIFINDER_INSTALL_BRANCH="$PF_RELEASE_TAG" bash /tmp/mf-pifinder-setup.sh
```

**Development version (main):**

```bash
wget -O /tmp/mf-pifinder-setup.sh https://raw.githubusercontent.com/hjoungjoo/MF_PiFinder/main/pifinder_setup.sh &&
PIFINDER_INSTALL_BRANCH=main bash /tmp/mf-pifinder-setup.sh
```

After the script reports successful completion, reboot:

```bash
sudo reboot
```

#### Installation paths and existing checkouts

| Situation | Behavior / action |
| --- | --- |
| User `pifinder` | Code: `/home/pifinder/PiFinder`; data: `/home/pifinder/PiFinder_data`. |
| Another OS user | The same commands use that user's home: `~/PiFinder` and `~/PiFinder_data`. Use that user's account for subsequent commands. |
| Custom code directory, such as `~/PiFinder_main` | The setup script always targets `PiFinder` in the selected user's home, even when launched elsewhere; setting `PIFINDER_REPO_DIR` does not override this. Use the standard location for a new installation. |
| Custom data directory | Pass `PIFINDER_DATA_DIR=/absolute/path` with the installation command. Use the same value for later updates and cache commands. This does not move existing data. |
| `~/PiFinder` already exists | Setup updates its **current branch** with a fast-forward merge; `PIFINDER_INSTALL_BRANCH` only selects a version when cloning a new directory. Local tracked changes cause setup to stop. |
| Existing tagged release checkout | A fresh tag install succeeds, but rerunning setup on its detached HEAD stops. Do not use these fresh-install commands to switch an existing checkout between a release and `main`. |

For an existing deployment, first check `git -C ~/PiFinder status -sb` and
back up `~/PiFinder_data` and any local changes. A branch checkout must be on
the intended branch before updating. After updating an existing installation's
code, run `bash pifinder_post_update.sh` from its repository root to apply
runtime updates, including automatic MFDS installation. This is an update hook,
not a substitute for first-time OS and service setup.

See the [MFDS binary installation guide](./docs/MFDS_BINARY_DISTRIBUTION_ko.md)
for package details. INDI mount support is optional: setup installs it only
when an INDI archive is available/configured; otherwise follow the
[INDI installation guide](./docs/mf_dev/mf_indi_mount_install_en.md).

### 3. Download offline caches

**The full image download takes a long time.** Thousands of survey images can
take hours depending on the connection and survey servers; reserve time before
an observing trip. Keep the PiFinder itself online and powered, and allow at
least **6 GB free** for the full POSS+SDSS cache. A phone connected to PiFinder's
AP alone does not necessarily give the device internet access.

From the installed repository, build the star/catalog runtime caches and
download both image surveys:

```bash
cd ~/PiFinder
python3 scripts/warm_pifinder_caches.py
```

To download only the POSS images used by the device and web catalog:

```bash
python3 scripts/warm_pifinder_caches.py --images poss
```

Use `--images none` to prepare runtime caches without downloading images.
The terminal shows progress; `Cache warm-up complete` indicates completion.
You can stop with `Ctrl-C` and rerun the same command to resume; existing images
are skipped. Keep the SSH session open while downloading. For a custom data
location, prefix the command with `PIFINDER_DATA_DIR=/absolute/path`.

[Offline cache guide](./docs/mf_dev/mf_cache_download_en.md) |
[한국어](./docs/mf_dev/mf_cache_download_ko.md)

### 4. Basic device setup

1. **Check startup and controls.** After reboot, confirm the LCD and keypad
   respond. See [input controls](./docs/mf_dev/mf_input_controls_en.md) and
   [keyboard mapping](./docs/mf_dev/mf_keyboard_mapping_en.md).
2. **Select the hardware.** In `Settings > Advanced`, set `PiFinder Type` to
   match the mounting orientation, select `Camera Type`, and check the GPS
   type, port, and baud rate in `GPS Settings`. Follow any restart prompts.
3. **Check networking and the web UI.** On the same network, open
   `http://<hostname>.local` (`http://pifinder.local` if that is your hostname).
   In AP mode, use `http://10.10.10.1` if name resolution fails. See
   [AP+STA setup](./docs/mf_dev/mf_wifi_apsta_ko.md) to configure field Wi-Fi.
4. **Confirm location and time.** Outdoors, use `Start > GPS Status` and wait
   for a fix. Without GPS, enter location and time in `Tools > Place & Time`.
5. **Focus the lens.** Remove the lens cap, point at a clear star field, and
   open `Start > Focus`. Adjust the lens for sharp stars and a low HFD reading.
6. **Measure the lens automatically.** Select
   `Settings > Advanced > Lens > Auto (Measure)` and hold the device still.
   After five stable star frames, the screen shows `MEASURED`, the measured
   field of view, and focal length. The result is automatically saved as a
   **Manual** lens; seeing Manual selected afterwards is normal. Auto measures
   field of view and effective focal length; it does not focus the lens, so
   complete the previous step first. If stars are insufficient or measurement
   fails, check focus and sky conditions, then retry. Pressing LEFT during
   measurement cancels it and keeps the previous lens setting.
7. **Measure lens distortion.** After Auto completes, select
   `Settings > Advanced > Distortion > Measure Sky`. Aim at a star field with
   stars extending to the image edges and hold still until at least five valid
   frames and a stable result produce `MEASURED`. The result is saved
   automatically. Press LEFT to return, then check `Distortion > Status` for
   `Sky measured` and the `k1` value. If `Need edge stars` persists, point at a
   more evenly populated star field and hold still again. Auto and distortion
   measurement are separate operations. Repeat both after changing the lens
   or camera, then confirm that sky positions solve. See the
   [lens correction guide](./docs/mf_dev/mf_lens_distortion_correction_en.md)
   for profile application conditions and details.
8. **Align with the telescope.** Center a known star in the eyepiece and use
   `Start > Align` to align PiFinder's pointing with the telescope. Select a
   catalog target and check the Push-to directions.
9. **Configure optional mount control.** INDI is disabled by default. Follow
   the [INDI setup guide](./docs/mf_dev/mf_indi_mount_install_en.md) and verify
   connection, GoTo, and Sync with Telescope Simulator before a physical mount.

See the [quick-start manual](./docs/source/quick_start.rst) and
[user manual](./docs/source/user_guide.rst) for detailed device operation.

### 5. MF feature documentation

The [MF additional-features index](./docs/mf_dev/mf_additional_features_en.md)
covers web catalogs, location catalogs, LiveCam, automatic exposure, MFDS,
SQM, and IMU calibration. Its Korean equivalent is
[available here](./docs/mf_dev/mf_additional_features_ko.md). For validation
status, see the [feature review checklist](./docs/mf_dev/mf_feature_review_checklist_en.md).

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

## MF detector distribution

The detector and Python integration are maintained and built at [MFDS](https://github.com/hjoungjoo/MFDS).
For a tagged PiFinder release, consult its release notes for the detector installation method.
The current `main` branch installs a pinned [MFDS binary release](https://github.com/hjoungjoo/MFDS/releases)
using `bash scripts/setup_mfds.sh`; it does not clone or compile MFDS sources.
The version, source revision and platform-specific checksums are pinned in `deployment/mfds.lock.json`.
See [binary installation and update guide](docs/MFDS_BINARY_DISTRIBUTION_ko.md).
MFDS native licensing and the GPL Python integration remain separately documented in the package.
